"""HTTP-level tests: design options, reasoning, drag-edit verification,
auth + roles, cloud project save and admin review."""
import pytest

import db
from app import create_app
from layout import verify_layout


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "admin@plumbline.test")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-pass-123")
    app = create_app(database_url="sqlite://", secret_key="test-secret")
    app.config["TESTING"] = True
    # fresh schema per test
    db.metadata.drop_all(db.engine())
    db.init_db("sqlite://")
    with app.test_client() as c:
        yield c


def _login(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.get_json()
    return {"Authorization": f"Bearer {r.get_json()['token']}"}


def _register(client, email="user@plumbline.test", password="user-pass-123"):
    r = client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.get_json()
    return {"Authorization": f"Bearer {r.get_json()['token']}"}


def _design(client):
    r = client.post("/api/design", json={"prompt": "8x10 spa bathroom, family of 4, 6 lakh"})
    assert r.status_code == 200
    return r.get_json()["data"]


# ------------------------------------------------------------------ design --
def test_health_reports_database(client):
    j = client.get("/api/health").get_json()
    assert j["status"] == "ok" and j["database"] == "sqlite"


def test_design_returns_three_verified_options(client):
    d = _design(client)
    W, L = d["layout"]["room_in"]["width"], d["layout"]["room_in"]["length"]
    assert len(d["options"]) == 3
    for o in d["options"]:
        assert verify_layout(o["placements"], W, L) == []
        assert any(p["category"] == "faucet" for p in o["placements"])
        assert all("id" in p and "name" in p for p in o["placements"])
    assert d["layout"]["placements"] == d["options"][0]["placements"]
    assert d["watersense"]["total"] == 3


def test_design_includes_reasoning_steps(client):
    d = _design(client)
    stages = [s["stage"] for s in d["reasoning"]]
    assert stages == ["understand", "select", "arrange", "verify", "options", "narrate"]
    select = d["reasoning"][1]
    assert "256 possible bundles" in select["details"][0]
    verify = d["reasoning"][3]
    assert "WaterSense" in verify["summary"]
    # every step has a one-line summary for the compact UI
    assert all(s["short"] for s in d["reasoning"])
    # offline, the design is still explained from the verified numbers
    narrate = d["reasoning"][-1]
    assert narrate["actor"] == "solver" and narrate["said"]
    assert d["rationale"]["source"] == "solver" and d["rationale"]["headline"]
    assert d["reasoning"][2]["attempts"], "arrange step must expose the attempt trace"
    # offline: the summary must not blame Gemini or claim the verifier caught anything
    assert d["reasoning"][2]["summary"].startswith("No LLM available")
    assert all(a["source"] != "gemini" for a in d["reasoning"][2]["attempts"])
    assert "0 rejected" in d["reasoning"][2]["summary"]


def test_infeasible_design_has_no_options(client):
    r = client.post("/api/design", json={"params": {"length_ft": 4, "width_ft": 4, "budget": 600000,
                                                    "theme": "Japanese Zen", "household": 2}})
    d = r.get_json()["data"]
    assert d["status"] == "infeasible" and "options" not in d


# ---------------------------------------------------------- drag-and-drop --
def _verify_body(d, arrangement):
    return {"room": {"width_in": d["layout"]["room_in"]["width"],
                     "length_in": d["layout"]["room_in"]["length"]},
            "bundle_ids": [p["id"] for p in d["bundle"]], "arrangement": arrangement}


def test_drag_edit_valid_move_is_accepted(client):
    d = _design(client)
    arrangement = {p["category"]: {"wall": p["side"], "offset": p["u"]}
                   for p in d["options"][1]["placements"] if p["category"] != "faucet"}
    j = client.post("/api/layout/verify", json=_verify_body(d, arrangement)).get_json()
    assert j["valid"] is True and j["problems"] == []
    assert any(p["category"] == "faucet" for p in j["placements"])


def test_drag_edit_collision_is_rejected_with_reasons(client):
    d = _design(client)
    stacked = {c: {"wall": "left", "offset": 0} for c in ("shower", "toilet", "vanity")}
    j = client.post("/api/layout/verify", json=_verify_body(d, stacked)).get_json()
    assert j["valid"] is False
    assert any("overlaps" in p for p in j["problems"])


def test_drag_edit_offsets_are_clamped_inside_room(client):
    d = _design(client)
    arrangement = {p["category"]: {"wall": p["side"], "offset": 99999}
                   for p in d["options"][0]["placements"] if p["category"] != "faucet"}
    j = client.post("/api/layout/verify", json=_verify_body(d, arrangement)).get_json()
    W = d["layout"]["room_in"]["width"]
    L = d["layout"]["room_in"]["length"]
    for p in j["placements"]:
        assert 0 <= p["x"] and p["x"] + p["w"] <= W + 1e-6
        assert 0 <= p["y"] and p["y"] + p["d"] <= L + 1e-6


@pytest.mark.parametrize("body", [
    None, {}, {"room": {"width_in": 96, "length_in": 120}, "bundle_ids": ["NOPE"], "arrangement": {}},
    {"room": {"width_in": 1, "length_in": 120}, "bundle_ids": [], "arrangement": {}},
])
def test_drag_edit_rejects_bad_input(client, body):
    r = client.post("/api/layout/verify", json=body)
    assert r.status_code == 400


def test_drag_edit_missing_wall_is_400(client):
    d = _design(client)
    j = client.post("/api/layout/verify", json=_verify_body(d, {"shower": {"wall": "up"}}))
    assert j.status_code == 400


# -------------------------------------------------------------------- auth --
def test_register_login_me(client):
    h = _register(client)
    me = client.get("/api/auth/me", headers=h).get_json()["user"]
    assert me["email"] == "user@plumbline.test" and me["role"] == "homeowner"
    assert "password_hash" not in me


def test_register_validation_and_duplicates(client):
    assert client.post("/api/auth/register", json={"email": "bad", "password": "longenough"}).status_code == 400
    assert client.post("/api/auth/register", json={"email": "a@b.co", "password": "short"}).status_code == 400
    _register(client, "a@b.co")
    assert client.post("/api/auth/register", json={"email": "A@B.co", "password": "longenough"}).status_code == 409


def test_register_picks_a_self_service_role(client):
    r = client.post("/api/auth/register", json={"email": "a@y.co", "password": "longenough", "role": "architect"})
    assert r.status_code == 201 and r.get_json()["user"]["role"] == "architect"


@pytest.mark.parametrize("role", ["admin", "kohler", "superuser"])
def test_register_cannot_self_assign_privileged_roles(client, role):
    r = client.post("/api/auth/register", json={"email": "x@y.co", "password": "longenough", "role": role})
    assert r.status_code == 400


def test_legacy_user_role_reads_as_homeowner(client):
    u = db.create_user("old@x.co", "longenough")
    with db.engine().begin() as c:
        c.execute(db.users.update().where(db.users.c.id == u["id"]).values(role="user"))
    assert db.get_user(u["id"])["role"] == "homeowner"


def test_bad_credentials_and_tokens(client):
    _register(client)
    assert client.post("/api/auth/login", json={"email": "user@plumbline.test",
                                                "password": "wrong-pass"}).status_code == 401
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer forged"}).status_code == 401


def test_token_from_another_secret_is_rejected(client):
    other = create_app(database_url="sqlite://", secret_key="different")
    with other.test_request_context():
        import auth
        forged = auth.issue_token({"id": 1})
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_admin_is_seeded_from_env(client):
    h = _login(client, "admin@plumbline.test", "admin-pass-123")
    assert client.get("/api/auth/me", headers=h).get_json()["user"]["role"] == "admin"


# ---------------------------------------------------------------- projects --
def _save(client, h, d, name="My bath"):
    r = client.post("/api/projects", headers=h, json={
        "name": name, "data": {"design": d, "selected_option": "Option B", "edits": {}}})
    assert r.status_code == 201, r.get_json()
    return r.get_json()["project"]


def test_project_crud_is_owner_scoped(client):
    d = _design(client)
    alice, bob = _register(client, "alice@x.co"), _register(client, "bob@x.co")
    p = _save(client, alice, d)
    assert p["status"] == "draft" and p["data"]["summary"]["option"] == "Option B"

    listed = client.get("/api/projects", headers=alice).get_json()["projects"]
    assert [x["id"] for x in listed] == [p["id"]] and "data" not in listed[0]
    assert client.get("/api/projects", headers=bob).get_json()["projects"] == []
    assert client.get(f"/api/projects/{p['id']}", headers=bob).status_code == 404
    assert client.delete(f"/api/projects/{p['id']}", headers=bob).status_code == 404
    assert client.put(f"/api/projects/{p['id']}", headers=bob, json={"name": "x"}).status_code == 404

    r = client.put(f"/api/projects/{p['id']}", headers=alice, json={"name": "Renamed"})
    assert r.get_json()["project"]["name"] == "Renamed"
    assert client.delete(f"/api/projects/{p['id']}", headers=alice).status_code == 200
    assert client.get(f"/api/projects/{p['id']}", headers=alice).status_code == 404


def test_projects_require_auth_and_valid_payload(client):
    assert client.get("/api/projects").status_code == 401
    h = _register(client)
    assert client.post("/api/projects", headers=h, json={"name": "x", "data": {}}).status_code == 400


# ------------------------------------------------------------------- admin --
def test_non_admin_cannot_reach_admin_routes(client):
    h = _register(client)
    for url in ("/api/admin/users", "/api/admin/projects", "/api/admin/stats"):
        assert client.get(url, headers=h).status_code == 403
    assert client.get("/api/admin/users").status_code == 401


def test_admin_review_workflow(client):
    d = _design(client)
    user = _register(client)
    admin = _login(client, "admin@plumbline.test", "admin-pass-123")
    p = _save(client, user, d)

    assert client.post(f"/api/projects/{p['id']}/submit", headers=user).get_json()["project"]["status"] == "submitted"
    queue = client.get("/api/admin/projects?status=submitted", headers=admin).get_json()["projects"]
    assert [x["id"] for x in queue] == [p["id"]] and queue[0]["owner_email"] == "user@plumbline.test"

    # admin can open any user's project
    assert client.get(f"/api/projects/{p['id']}", headers=admin).status_code == 200
    assert client.post(f"/api/admin/projects/{p['id']}/review", headers=admin,
                       json={"decision": "maybe"}).status_code == 400
    r = client.post(f"/api/admin/projects/{p['id']}/review", headers=admin,
                    json={"decision": "approved", "note": "Clearances look good"})
    assert r.get_json()["project"]["status"] == "approved"
    assert client.get(f"/api/projects/{p['id']}", headers=user).get_json()["project"]["review_note"] == "Clearances look good"

    # editing the design sends it back to draft for re-review
    r = client.put(f"/api/projects/{p['id']}", headers=user, json={"data": {"design": d}})
    assert r.get_json()["project"]["status"] == "draft"

    stats = client.get("/api/admin/stats", headers=admin).get_json()["stats"]
    assert stats["users"] == 2 and stats["projects"] == 1


def test_admin_role_management_and_last_admin_guard(client):
    admin = _login(client, "admin@plumbline.test", "admin-pass-123")
    _register(client)
    users = client.get("/api/admin/users", headers=admin).get_json()["users"]
    uid = next(u["id"] for u in users if u["email"] == "user@plumbline.test")
    admin_id = next(u["id"] for u in users if u["role"] == "admin")

    assert client.patch(f"/api/admin/users/{admin_id}", headers=admin,
                        json={"role": "homeowner"}).status_code == 409
    assert client.patch(f"/api/admin/users/{uid}", headers=admin,
                        json={"role": "superuser"}).status_code == 400
    r = client.patch(f"/api/admin/users/{uid}", headers=admin, json={"role": "kohler"})
    assert r.get_json()["user"]["role"] == "kohler"
    r = client.patch(f"/api/admin/users/{uid}", headers=admin, json={"role": "admin"})
    assert r.get_json()["user"]["role"] == "admin"
    # role is re-read per request: the promoted user can now reach admin routes
    promoted = _login(client, "user@plumbline.test", "user-pass-123")
    assert client.get("/api/admin/users", headers=promoted).status_code == 200


def test_cors_allows_configured_origin(client):
    r = client.options("/api/design", headers={"Origin": "http://localhost:5173",
                                               "Access-Control-Request-Method": "POST"})
    assert r.headers.get("Access-Control-Allow-Origin") == "http://localhost:5173"
    r = client.options("/api/design", headers={"Origin": "https://evil.example",
                                               "Access-Control-Request-Method": "POST"})
    assert r.headers.get("Access-Control-Allow-Origin") is None


def test_database_url_normalisation():
    assert db.normalize_url("postgres://u:p@h/db?sslmode=require") == \
        "postgresql+psycopg://u:p@h/db?sslmode=require"
    assert db.normalize_url("postgresql://u:p@h/db").startswith("postgresql+psycopg://")
    assert db.normalize_url("sqlite://") == "sqlite://"


def test_submit_rejects_an_invalid_saved_layout(client):
    d = _design(client)
    h = _register(client)
    bad = [dict(p) for p in d["options"][0]["placements"]]
    for p in bad:                       # stack every fixture in the same corner
        if p["category"] != "faucet":
            p.update(x=40, y=40)
    r = client.post("/api/projects", headers=h, json={"name": "broken", "data": {
        "design": d, "selected_option": "Option A", "edits": {"Option A": {"placements": bad}}}})
    pid = r.get_json()["project"]["id"]
    r = client.post(f"/api/projects/{pid}/submit", headers=h)
    assert r.status_code == 422 and "overlaps" in r.get_json()["message"]
    assert client.get(f"/api/projects/{pid}", headers=h).get_json()["project"]["status"] == "draft"


def test_submit_rejects_incomplete_design(client):
    h = _register(client)
    pid = client.post("/api/projects", headers=h, json={"name": "x", "data": {"design": {}}}).get_json()["project"]["id"]
    assert client.post(f"/api/projects/{pid}/submit", headers=h).status_code == 422


def test_admin_seeding_survives_a_concurrent_worker(monkeypatch, tmp_path):
    """Two gunicorn workers boot together and both try to seed the admin."""
    monkeypatch.setenv("ADMIN_EMAIL", "race@plumbline.test")
    monkeypatch.setenv("ADMIN_PASSWORD", "race-pass-123")
    url = f"sqlite:///{tmp_path / 'race.db'}"
    db.init_db(url)
    real_select = db.select
    # Simulate the race: the second worker's lookup misses the row the first inserted.
    calls = {"n": 0}

    def stale_select(*a, **k):
        q = real_select(*a, **k)
        calls["n"] += 1
        return q.where(db.users.c.id < 0) if a and a[0] is db.users else q

    monkeypatch.setattr(db, "select", stale_select)
    db.init_db(url)                       # must not raise IntegrityError
    monkeypatch.setattr(db, "select", real_select)
    assert db.authenticate("race@plumbline.test", "race-pass-123")["role"] == "admin"
    db.init_db("sqlite://")



# ------------------------------------------------------------------ report --
def _pdf_text(raw):
    """Decompress the PDF's content streams so tests can search the text."""
    import re
    import zlib
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
        try:
            out.append(zlib.decompress(m.group(1)).decode("latin-1"))
        except zlib.error:
            pass
    return "\n".join(out)


def _report(client, d, headers=None, **extra):
    body = {"design": d, "selected_option": "Option A", "edits": {}}
    body.update(extra)
    return client.post("/api/report", json=body, headers=headers or {})


def test_report_is_a_pdf_and_tiers_by_role(client):
    d = _design(client)
    anon = _report(client, d)
    assert anon.status_code == 200 and anon.mimetype == "application/pdf"
    assert anon.data.startswith(b"%PDF")
    assert "homeowner.pdf" in anon.headers["Content-Disposition"]
    home = _pdf_text(anon.data)
    assert "HOMEOWNER SUMMARY" in home and "PLACEMENT SCHEDULE" not in home

    arch = _register(client, "arch@x.co")
    db.set_role(db.authenticate("arch@x.co", "user-pass-123")["id"], "architect")
    text = _pdf_text(_report(client, d, arch).data)
    assert "ARCHITECT REPORT" in text and "PLACEMENT SCHEDULE" in text
    assert "AI PIPELINE" not in text

    admin = _login(client, "admin@plumbline.test", "admin-pass-123")
    text = _pdf_text(_report(client, d, admin).data)
    assert "KOHLER TEAM REPORT" in text and "AI PIPELINE" in text and "BUNDLE SELECTION" in text


def test_report_recomputes_numbers_and_flags_broken_layouts(client):
    d = _design(client)
    tampered = dict(d, metrics=dict(d["metrics"], total_cost=1))
    bad = [dict(p) for p in d["options"][0]["placements"]]
    for p in bad:
        if p["category"] != "faucet":
            p.update(x=40, y=40)
    text = _pdf_text(_report(client, tampered, edits={"Option A": {"placements": bad}}).data)
    assert "Not valid" in text and "overlaps" in text
    real_cost = sum(p.get("price_inr", 0) for p in d["bundle"])
    import report
    assert report._money(real_cost, "INR") in text          # catalogue price, not the tampered 1
    assert "Rs 1 " not in text


def test_report_rejects_bad_input(client):
    assert client.post("/api/report", json={}).status_code == 400
    d = _design(client)
    d_bad = dict(d, bundle=[dict(d["bundle"][0], id="FAKE")] + d["bundle"][1:])
    assert _report(client, d_bad).status_code == 400


def test_saved_project_report_is_owner_scoped(client):
    d = _design(client)
    alice, bob = _register(client, "alice@x.co"), _register(client, "bob@x.co")
    p = _save(client, alice, d)
    r = client.get(f"/api/projects/{p['id']}/report", headers=alice)
    assert r.status_code == 200 and r.data.startswith(b"%PDF")
    assert "My-bath" in r.headers["Content-Disposition"]
    assert client.get(f"/api/projects/{p['id']}/report", headers=bob).status_code == 404



def test_report_type_can_be_chosen_within_permissions(client):
    d = _design(client)
    # anonymous: homeowner and architect are free choices
    r = _report(client, d, report_type="architect")
    assert r.status_code == 200 and "architect.pdf" in r.headers["Content-Disposition"]
    assert "ARCHITECT REPORT" in _pdf_text(r.data)
    # ...but the Kohler team report needs a Kohler/admin sign-in
    assert _report(client, d, report_type="kohler").status_code == 403
    home = _register(client, "h@x.co")
    assert _report(client, d, home, report_type="kohler").status_code == 403
    assert _report(client, d, report_type="ceo").status_code == 400

    admin = _login(client, "admin@plumbline.test", "admin-pass-123")
    r = _report(client, d, admin, report_type="homeowner")
    assert "HOMEOWNER SUMMARY" in _pdf_text(r.data)          # admins can pick a lighter one
    assert "KOHLER TEAM REPORT" in _pdf_text(_report(client, d, admin, report_type="kohler").data)


def test_project_report_type_query(client):
    d = _design(client)
    h = _register(client)
    p = _save(client, h, d)
    r = client.get(f"/api/projects/{p['id']}/report?type=architect", headers=h)
    assert r.status_code == 200 and "architect.pdf" in r.headers["Content-Disposition"]
    assert client.get(f"/api/projects/{p['id']}/report?type=kohler", headers=h).status_code == 403
