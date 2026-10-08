"""`python run.py` serves the built React app and the API from one origin.

These tests point FRONTEND_DIST at a fake build so they run without Node.
"""
import app as app_module


def _client(monkeypatch, dist):
    monkeypatch.setattr(app_module, "FRONTEND_DIST", str(dist))
    return app_module.create_app(database_url="sqlite://").test_client()


def _fake_build(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    return dist


def test_root_and_client_routes_serve_the_spa(monkeypatch, tmp_path):
    c = _client(monkeypatch, _fake_build(tmp_path))
    for path in ("/", "/planner", "/admin/users"):
        r = c.get(path)
        assert r.status_code == 200 and b"id=root" in r.data, path


def test_built_assets_are_served(monkeypatch, tmp_path):
    r = _client(monkeypatch, _fake_build(tmp_path)).get("/assets/app.js")
    assert r.status_code == 200 and b"console.log" in r.data


def test_api_routes_win_and_unknown_api_paths_404(monkeypatch, tmp_path):
    c = _client(monkeypatch, _fake_build(tmp_path))
    assert c.get("/api/health").get_json()["status"] == "ok"
    assert c.get("/api/does-not-exist").status_code == 404


def test_api_only_when_frontend_not_built(monkeypatch, tmp_path):
    """Render deploys the backend alone: no dist, so stay JSON-only."""
    r = _client(monkeypatch, tmp_path / "missing").get("/")
    assert r.status_code == 200 and r.get_json()["service"] == "plumbline-api"


def test_path_traversal_is_not_served(monkeypatch, tmp_path):
    (tmp_path / "secret.txt").write_text("nope")
    r = _client(monkeypatch, _fake_build(tmp_path)).get("/../secret.txt")
    assert b"nope" not in r.data
