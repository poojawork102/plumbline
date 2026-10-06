"""Plumbline API -- Flask, JSON only. The React frontend lives in ../frontend.

Request path for POST /api/design:

    free text -> ai_engine.parse_intent          Gemini, regex fallback
                        |
                        v
              solver.solve_bathroom_bundle       deterministic: cannot break
                        |                        budget or floor-area limits
                        v
          ai_engine.layout_options               Option A = Gemini proposes
                        |                        (wall, offset), layout.verify_layout
                        |                        critiques, Gemini repairs, solver
                        |                        backstops. Options B, C: extra
                        |                        verified alternatives.
                        v
                ai_engine.explain                rationale grounded on the
                                                 verified numbers only

The app starts and serves a valid design with no API key and no network.
"""
import logging
import os
import re
import time

from dotenv import load_dotenv
from flask import Flask, g, jsonify, request
from flask_cors import CORS

load_dotenv()

import ai_engine  # noqa: E402
import auth  # noqa: E402
import db  # noqa: E402
import reasoning  # noqa: E402
from intent_parser import parse_prompt  # noqa: E402
from layout import describe_layout, layout_features, mount_faucet, verify_layout  # noqa: E402
from solver import _fx, currency_of, load_catalog, solve_bathroom_bundle, water_use  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

THEMES = ["Minimalist Modern", "Japanese Zen", "Classic Luxury"]
LIMITS = {"length_ft": (4, 30), "width_ft": (4, 30), "household": (1, 12)}
OPTION_COUNT = 3
MAX_PROJECT_BYTES = 512 * 1024
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# EPA WaterSense maximums -- the spec KOHLER certifies its products against.
WATERSENSE = {"toilet_gpf": 1.28, "shower_gpm": 2.0, "faucet_gpm": 1.5}

DEV_SECRET = "plumbline-dev-secret-change-me"


def _err(message, code=400):
    return jsonify({"status": "error", "message": message}), code


def create_app(database_url=None, secret_key=None):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = (secret_key or os.environ.get("SECRET_KEY")
                                or os.environ.get("FLASK_SECRET") or DEV_SECRET)
    if app.config["SECRET_KEY"] == DEV_SECRET and os.environ.get("RENDER"):
        logging.warning("SECRET_KEY is not set -- auth tokens are forgeable!")
    app.config["MAX_CONTENT_LENGTH"] = MAX_PROJECT_BYTES * 2

    origins = [o.strip() for o in os.environ.get(
        "ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
    CORS(app, resources={r"/api/*": {"origins": origins}},
         allow_headers=["Content-Type", "Authorization"],
         methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])

    db.init_db(database_url)
    _register_routes(app)
    return app


# ----------------------------------------------------------------- helpers --
def _validate(p):
    for key, (lo, hi) in LIMITS.items():
        if not lo <= p[key] <= hi:
            return f"{key.replace('_', ' ')} must be between {lo} and {hi}"
    if p["budget"] <= 0:
        return "budget must be greater than zero"
    if p["theme"] not in THEMES:
        return f"theme must be one of: {', '.join(THEMES)}"
    return None


def _watersense_report(bundle):
    """Per-product pass/fail against the EPA WaterSense spec."""
    rows, passing = [], 0
    for p in bundle:
        cat = p["category"]
        if cat == "toilet":
            rated, limit, unit = p.get("gpf", 0), WATERSENSE["toilet_gpf"], "gpf"
        elif cat == "shower":
            rated, limit, unit = p.get("gpm", 0), WATERSENSE["shower_gpm"], "gpm"
        elif cat == "faucet":
            rated, limit, unit = p.get("gpm", 0), WATERSENSE["faucet_gpm"], "gpm"
        else:
            continue
        ok = rated <= limit + 1e-9
        passing += ok
        rows.append({"category": cat, "name": p["name"], "rated": rated,
                     "limit": limit, "unit": unit, "certified": ok})
    return {"items": rows, "certified_count": passing, "total": len(rows),
            "fully_certified": passing == len(rows) and bool(rows)}


def _finalize(placements, by_cat, W_in, L_in):
    """Attach product ids/names and mount the faucet on the vanity."""
    out = [dict(p) for p in placements]
    for p in out:
        item = by_cat[p["category"]]
        p.update(id=item["id"], name=item["name"])
    vanity = next((p for p in out if p["category"] == "vanity"), None)
    if vanity and "faucet" in by_cat:
        faucet = mount_faucet(_fx(by_cat["faucet"]), vanity, W_in, L_in)
        if faucet:
            faucet.update(id=by_cat["faucet"]["id"], name=by_cat["faucet"]["name"])
            out.append(faucet)
    return out


def _parse_request(body):
    prompt_text = str(body.get("prompt", ""))[:2000]
    if isinstance(body.get("params"), dict):
        raw = body["params"]
        parsed = {"length_ft": float(raw["length_ft"]), "width_ft": float(raw["width_ft"]),
                  "budget": float(raw["budget"]), "theme": str(raw["theme"]),
                  "household": int(raw["household"]),
                  "prioritize_smart": bool(raw.get("prioritize_smart", False)),
                  "source": "controls", "assumed": [], "reading": None}
    else:
        # STEP 1 -- LLM reads intent, regex parser is the safety net.
        parsed = ai_engine.parse_intent(prompt_text, parse_prompt)
    parsed["prompt"] = prompt_text
    return parsed, prompt_text


def _project_summary(data):
    """Small denormalised summary so project lists don't ship the whole design."""
    d = data.get("design") or {}
    m = d.get("metrics") or {}
    inputs = d.get("inputs") or {}
    return {"theme": inputs.get("theme"), "length_ft": inputs.get("length_ft"),
            "width_ft": inputs.get("width_ft"), "total_cost": m.get("total_cost"),
            "currency": d.get("currency"), "option": data.get("selected_option")}


def _saved_layout_problems(data):
    """Verify the layout a saved project would actually build."""
    design = data.get("design") or {}
    try:
        room = design["layout"]["room_in"]
        options = design.get("options") or []
        chosen = next((o for o in options if o.get("id") == data.get("selected_option")),
                      options[0] if options else None)
        edit = (data.get("edits") or {}).get(chosen["id"]) if chosen else None
        placements = (edit or {}).get("placements") or (chosen or {}).get("placements") \
            or design["layout"]["placements"]
        return verify_layout(placements, room["width"], room["length"])
    except (KeyError, TypeError, ValueError, StopIteration):
        return ["saved design is incomplete"]


def _can_access(project, user):
    return project is not None and (project["owner_id"] == user["id"]
                                    or user["role"] == "admin")


# ------------------------------------------------------------------ routes --
def _register_routes(app):

    @app.route("/")
    def root():
        return jsonify({"service": "plumbline-api", "docs": "/api/health"})

    @app.route("/api/health")
    def health():
        """Lets a reviewer confirm in one request what is live."""
        return jsonify({"status": "ok", "gemini": ai_engine.ai_status(),
                        "model": ai_engine.MODEL, "catalog": len(load_catalog()),
                        "database": db.backend_name() if db.ping() else "unavailable"})

    @app.route("/api/config")
    def config():
        return jsonify({"themes": THEMES, "limits": LIMITS, "watersense": WATERSENSE,
                        "currency": currency_of(load_catalog()),
                        "option_count": OPTION_COUNT})

    @app.route("/api/catalog")
    def catalog():
        return jsonify({"products": load_catalog()})

    @app.route("/api/sustainability")
    def sustainability():
        try:
            occupancy = max(1, min(12, int(request.args.get("household", 4))))
        except (TypeError, ValueError):
            occupancy = 4
        # Same water model as solver.py, so the pages can never disagree.
        default = solve_bathroom_bundle(8, 8, 500000, household=occupancy)
        water = water_use(default["bundle"], occupancy)
        return jsonify({"household": occupancy, "water": water,
                        "rupees_saved": int(water["saved_gal"] * 3.78 * 0.05),
                        "watersense": _watersense_report(default["bundle"])})

    # ---------------------------------------------------------- design --
    @app.route("/api/design", methods=["POST"])
    def generate_design():
        started = time.perf_counter()
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or ("prompt" not in body and "params" not in body):
            return _err('Send JSON with "prompt" or "params"')

        try:
            parsed, prompt_text = _parse_request(body)
            error = _validate(parsed)
            if error:
                return _err(error)
            # STEP 2 -- deterministic selection. Cannot exceed budget or floor limit.
            result = solve_bathroom_bundle(
                room_length_ft=parsed["length_ft"], room_width_ft=parsed["width_ft"],
                budget=parsed["budget"], theme=parsed["theme"],
                household=parsed["household"], prioritize_smart=parsed["prioritize_smart"])
        except (KeyError, TypeError, ValueError) as exc:
            return _err(f"Invalid request: {exc}")

        if result["status"] == "ok":
            W_in = result["layout"]["room_in"]["width"]
            L_in = result["layout"]["room_in"]["length"]
            by_cat = {p["category"]: p for p in result["bundle"]}
            floor = [_fx(p) for p in result["bundle"] if p["category"] != "faucet"]

            # STEP 3-6 -- propose, verify, repair, fall back (option A), plus
            # verified alternatives (options B, C). Every option ends valid.
            options, trace, source = ai_engine.layout_options(
                floor, W_in, L_in, parsed["theme"], prompt_text, count=OPTION_COUNT)

            if options:
                for opt in options:
                    opt["placements"] = _finalize(opt["placements"], by_cat, W_in, L_in)
                result["layout"]["placements"] = options[0]["placements"]
            result["options"] = [{k: v for k, v in o.items() if k != "trace"}
                                 for o in options]
            result["layout"]["fixtures"] = floor

            result["ai"] = {
                "layout_source": source,
                "intent_source": parsed.get("source"),
                "reading": parsed.get("reading"),
                "attempts": len(trace),
                "repairs": sum(1 for t in trace if not t["accepted"]
                               and t.get("stage", "primary") == "primary"),
                "trace": trace,
                "status": ai_engine.ai_status(),
            }
            result["watersense"] = _watersense_report(result["bundle"])

            # STEP 7 -- narration grounded on the verified numbers.
            result["rationale"] = ai_engine.explain(result, prompt_text, parsed)
            result["reasoning"] = reasoning.build(parsed, result, options, trace, source,
                                                 llm_live=ai_engine.ai_status() == "live")

            result["room_dimensions_in"] = result["layout"]["room_in"]
            result["total_bundle_cost_inr"] = result["metrics"]["total_cost"]
            result["space_utilization_pct"] = result["metrics"]["space_utilization_pct"]
            result["annual_water_savings_gal"] = result["metrics"]["water"]["saved_gal"]
            result["budget_compliant"] = True

        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        logging.info(
            "DesignRequest | intent_source=%s | layout_source=%s | attempts=%s | "
            "options=%s | total_latency_ms=%s", parsed.get("source", "unknown"),
            result.get("ai", {}).get("layout_source", "none"),
            result.get("ai", {}).get("attempts", 0), len(result.get("options", [])),
            elapsed_ms)
        return jsonify({"status": "success", "parsed": parsed, "data": result,
                        "elapsed_ms": elapsed_ms})

    @app.route("/api/layout/verify", methods=["POST"])
    def verify_edit():
        """Re-verify a layout after the user drags fixtures around.

        The client sends only (wall, offset) per fixture plus product ids;
        geometry is rebuilt here from catalogue specs, exactly as for an LLM
        proposal, so a hand edit gets the same verifier as the AI does.
        """
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return _err("Send JSON with room, bundle_ids and arrangement")
        try:
            room = body["room"]
            W_in, L_in = float(room["width_in"]), float(room["length_in"])
            ids = list(body["bundle_ids"])
            arrangement = body["arrangement"]
        except (KeyError, TypeError, ValueError) as exc:
            return _err(f"Invalid request: {exc}")
        lo, hi = LIMITS["width_ft"][0] * 12, LIMITS["length_ft"][1] * 12
        if not (lo <= W_in <= hi and lo <= L_in <= hi):
            return _err(f"room sides must be between {lo} and {hi} inches")
        if not isinstance(arrangement, dict):
            return _err("arrangement must be an object of {category: {wall, offset}}")

        products = {p["id"]: p for p in load_catalog()}
        unknown = [i for i in ids if i not in products]
        if unknown:
            return _err(f"unknown product id(s): {', '.join(map(str, unknown))}")
        by_cat = {products[i]["category"]: products[i] for i in ids}
        floor = [_fx(p) for c, p in by_cat.items() if c != "faucet"]

        placements = ai_engine._apply(arrangement, floor, W_in, L_in)
        if placements is None:
            return _err("every floor fixture needs a wall (top/right/bottom/left) "
                        "and a numeric offset")
        problems = verify_layout(placements, W_in, L_in)
        feats = layout_features(placements, W_in, L_in)
        return jsonify({"status": "success", "valid": not problems, "problems": problems,
                        "placements": _finalize(placements, by_cat, W_in, L_in),
                        "features": feats, "summary": describe_layout(feats)})

    # ------------------------------------------------------------ auth --
    @app.route("/api/auth/register", methods=["POST"])
    def register():
        body = request.get_json(silent=True) or {}
        email = str(body.get("email", "")).strip().lower()
        password = str(body.get("password", ""))
        name = str(body.get("name", "")).strip()[:120]
        if not EMAIL_RE.match(email):
            return _err("A valid email is required")
        if len(password) < 8:
            return _err("Password must be at least 8 characters")
        # Self-registration always creates a plain user; admins are seeded
        # from the environment or promoted by another admin.
        user = db.create_user(email, password, name=name or email.split("@")[0])
        if user is None:
            return _err("An account with that email already exists", 409)
        return jsonify({"status": "success", "token": auth.issue_token(user),
                        "user": user}), 201

    @app.route("/api/auth/login", methods=["POST"])
    def login():
        body = request.get_json(silent=True) or {}
        user = db.authenticate(body.get("email"), body.get("password"))
        if user is None:
            return _err("Incorrect email or password", 401)
        return jsonify({"status": "success", "token": auth.issue_token(user), "user": user})

    @app.route("/api/auth/me")
    @auth.require_auth
    def me():
        return jsonify({"status": "success", "user": g.user})

    # -------------------------------------------------------- projects --
    @app.route("/api/projects", methods=["GET"])
    @auth.require_auth
    def list_projects():
        return jsonify({"status": "success", "projects": db.list_projects(owner_id=g.user["id"])})

    def _project_payload(body):
        name = str(body.get("name") or "").strip()[:200]
        data = body.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("design"), dict):
            return None, None, "data.design is required"
        if len(request.get_data() or b"") > MAX_PROJECT_BYTES:
            return None, None, "project is too large"
        data = dict(data, summary=_project_summary(data))
        return name, data, None

    @app.route("/api/projects", methods=["POST"])
    @auth.require_auth
    def create_project():
        body = request.get_json(silent=True) or {}
        name, data, error = _project_payload(body)
        if error:
            return _err(error)
        project = db.create_project(g.user["id"], name or "Untitled design", data)
        return jsonify({"status": "success", "project": project}), 201

    @app.route("/api/projects/<int:pid>", methods=["GET"])
    @auth.require_auth
    def get_project(pid):
        project = db.get_project(pid)
        if not _can_access(project, g.user):
            return _err("Project not found", 404)
        return jsonify({"status": "success", "project": project})

    @app.route("/api/projects/<int:pid>", methods=["PUT"])
    @auth.require_auth
    def update_project(pid):
        project = db.get_project(pid)
        if project is None or project["owner_id"] != g.user["id"]:
            return _err("Project not found", 404)
        body = request.get_json(silent=True) or {}
        name, data = None, None
        if "data" in body:
            name, data, error = _project_payload(body)
            if error:
                return _err(error)
        if body.get("name"):
            name = str(body["name"]).strip()[:200]
        return jsonify({"status": "success",
                        "project": db.update_project(pid, name=name or None, data=data)})

    @app.route("/api/projects/<int:pid>", methods=["DELETE"])
    @auth.require_auth
    def delete_project(pid):
        project = db.get_project(pid)
        if not _can_access(project, g.user):
            return _err("Project not found", 404)
        db.delete_project(pid)
        return jsonify({"status": "success"})

    @app.route("/api/projects/<int:pid>/submit", methods=["POST"])
    @auth.require_auth
    def submit_project(pid):
        project = db.get_project(pid)
        if project is None or project["owner_id"] != g.user["id"]:
            return _err("Project not found", 404)
        if project["status"] == "approved":
            return _err("Project is already approved", 409)
        # Saved data comes from the client, so re-verify the chosen layout
        # here: an authority should never be asked to approve a broken plan.
        problems = _saved_layout_problems(project["data"])
        if problems:
            return _err("Layout fails verification: " + "; ".join(problems), 422)
        return jsonify({"status": "success",
                        "project": db.set_project_status(pid, "submitted")})

    # ----------------------------------------------------------- admin --
    @app.route("/api/admin/stats")
    @auth.require_admin
    def admin_stats():
        return jsonify({"status": "success", "stats": db.stats()})

    @app.route("/api/admin/users")
    @auth.require_admin
    def admin_users():
        return jsonify({"status": "success", "users": db.list_users()})

    @app.route("/api/admin/users/<int:uid>", methods=["PATCH"])
    @auth.require_admin
    def admin_set_role(uid):
        role = (request.get_json(silent=True) or {}).get("role")
        if role not in db.ROLES:
            return _err(f"role must be one of: {', '.join(db.ROLES)}")
        target = db.get_user(uid)
        if target is None:
            return _err("User not found", 404)
        if target["role"] == "admin" and role != "admin" and db.count_admins() <= 1:
            return _err("Cannot demote the last admin", 409)
        return jsonify({"status": "success", "user": db.set_role(uid, role)})

    @app.route("/api/admin/projects")
    @auth.require_admin
    def admin_projects():
        status = request.args.get("status") or None
        if status and status not in db.PROJECT_STATUSES:
            return _err(f"status must be one of: {', '.join(db.PROJECT_STATUSES)}")
        return jsonify({"status": "success", "projects": db.list_projects(status=status)})

    @app.route("/api/admin/projects/<int:pid>/review", methods=["POST"])
    @auth.require_admin
    def admin_review(pid):
        body = request.get_json(silent=True) or {}
        decision = body.get("decision")
        if decision not in ("approved", "rejected"):
            return _err('decision must be "approved" or "rejected"')
        if db.get_project(pid) is None:
            return _err("Project not found", 404)
        note = str(body.get("note") or "").strip()[:2000] or None
        return jsonify({"status": "success", "project": db.set_project_status(
            pid, decision, note=note, reviewer_id=g.user["id"])})


app = create_app()


if __name__ == "__main__":
    print(f"[plumbline] Gemini: {ai_engine.ai_status()} | model: {ai_engine.MODEL} "
          f"| db: {db.backend_name()}")
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
