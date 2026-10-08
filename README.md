# Plumbline

**Conversational bathroom design with verified spatial compliance**
AI Lab Case Study — Track 1: AI Bathroom Designer & Planner | MIT-WPU

---
**Prompts documentation:** [`docs/Plumbline_promptlog.pdf`](docs/Plumbline_promptlog.pdf)

**Pitch deck:** [`docs/Plumbline_ppt.pdf`](docs/Plumbline_ppt.pdf)

**Product requirements:** [`docs/Plumbline_prd.pdf`](docs/Plumbline_prd.pdf)

**Prototype walkthrough:**https://youtu.be/HDnUypq6zeM

---

## What it does

Plumbline turns a plain-English request — *"8×10 spa bathroom, family of 4, ₹6 lakh, touchless"* — into a costed, clearance-verified, WaterSense-certified floor plan in under 2 seconds.

The product is named after its verifier, not its generator. A plumb line designs nothing — it only tells you whether what was built is true. The language model proposes; deterministic geometry disposes.

---

## The architecture

The core problem: LLMs are excellent at reading intent and making aesthetic judgements, and unreliable at metric geometry. Ask a model for fixture coordinates and it will cheerfully overlap a toilet with a shower.

Plumbline's answer is a **constrained action space + verify–repair–fallback loop**:

| Stage | Owner | What happens |
|---|---|---|
| 1. Understand | Gemini | Free text → structured brief. Regex parser is the fallback. |
| 2. Select | Python | Enumerates all 256 catalogue bundles. Filters by budget and 40% floor-area limit. Cannot return an over-budget bundle. |
| 3. Arrange | Gemini | Proposes `(wall, offset)` per fixture — never raw x/y. Coordinates are derived in code. |
| 4. Verify | Python | `verify_layout()` re-checks clearances, door swing and overlaps independently. |
| 5. Repair | Gemini | Violations fed back as a critique. Model retries, forbidden from repeating the rejected arrangement. Max 2 repairs. |
| 6. Fall back | Python | Constraint search ships a guaranteed-valid layout. A user never sees a broken plan. |
| 7. Narrate | Gemini | Rationale written using only the verified numbers — cannot invent a saving figure. |

The self-correction trace is returned under `data.ai.trace` and rendered in the UI — you can watch the model fail, receive a machine critique, and fix itself.

---

## What's new — Kohler Lab feedback

| Feedback | What shipped |
|---|---|
| Multiple layout options | Every generation returns **3 verified options** for the chosen products. Option A is the original propose → verify → repair → fallback loop; B and C come from one extra Gemini call (each proposal verified independently, rejects shown in the trace) with any empty slots filled by a deterministic enumerator that guarantees genuinely different wall assignments. |
| Visible AI reasoning | A six-step **reasoning panel** (understand → select → arrange/verify/repair → independent verification → alternatives → narrate) built from what the pipeline actually did: the model's reading of the brief, how many of 256 bundles each gate removed, every proposal, the verifier's reasons and the exact critique sent back to the model. |
| 3D rendering | Three.js view (lazy-loaded) with orbit/zoom/pan, real fixture heights from the catalogue, clearance zones, door swing and an automatic wall cut-away so fixtures stay visible from any angle. |
| Drag-and-drop editing | Drag any fixture in the 2D plan (or focus it and use arrow keys / `R`); it snaps to the nearest wall. Every drop goes to `POST /api/layout/verify`, which rebuilds geometry from catalogue specs and runs the **same verifier the AI is held to**. Violations highlight in 2D and 3D. |
| Admin / authority role | Email + password login with `user` and `admin` roles. Users submit designs for approval; admins review (approve/reject with a note), manage roles and see stats. The server re-verifies a layout before it can be submitted, so an authority never reviews a broken plan. |
| Cloud save | Projects persist to **Neon Postgres** (SQLite locally). Re-open, rename, delete; editing an approved design sends it back to draft. |

| Role-based PDF reports | **Download PDF report** on the Planner, Sustainability and My projects pages. The server builds it and recomputes every number from the catalogue. Detail follows the signed-in role: **Homeowner** (cost, water, products, plan), **Architect / designer** (+ dimensions, clearances, placement schedule, compliance), **Kohler team** (+ SKUs, bundle-selection maths, AI trace, features). People pick Homeowner or Architect at sign-up; an admin grants Kohler team or admin. |
| Usability | Slider controls (no fiddly number boxes), one-line reasoning and checks that expand on tap, a short explanation even with the AI offline, and a dark-mode toggle that follows your OS until you choose. |

EPA WaterSense checks and the verify–repair–fallback loop are unchanged and still gate every layout.

---

## Repository layout

```
backend/            Flask JSON API  → Render (persistent web service)
  app.py            routes: design, layout verify, auth, projects, admin
  ai_engine.py      Gemini loop: intent, arrange + repair, alternatives, narrate
  solver.py         deterministic bundle selection (budget, 40% floor rule)
  layout.py         geometry, verifier, option enumeration
  reasoning.py      step-by-step reasoning shown in the UI
  db.py / auth.py   Postgres (Neon) persistence, bearer-token auth + roles
  report.py         role-based PDF report (fpdf2)
  tests/            pytest
frontend/           React + Vite + Three.js → Vercel
  src/components/   FloorPlan (drag/drop), Room3D, ReasoningPanel, OptionPicker
  src/pages/        Planner, Projects, Admin, Login, Sustainability
  src/__tests__/    Vitest + Testing Library
render.yaml         Render blueprint for the API
run.py              one-command local runner (build + serve on :5000)
frontend/vercel.json  Vercel config (SPA rewrites, caching headers)
```

In production the frontend calls the API over HTTPS at `VITE_API_URL`; locally it is served from the same origin by `run.py`. Auth uses signed bearer tokens in the `Authorization` header (no cross-site cookies), and the API only accepts browser requests from `ALLOWED_ORIGINS`.

---

## Run locally — one command

Needs **Python 3.10+** and **Node.js 18+**.

```bash
git clone https://github.com/poojawork102/plumbline.git
cd plumbline
python run.py                  # → http://localhost:5000 opens in your browser
```

`run.py` does every setup step that is still needed, then starts **one server** that serves both the app and the API:

1. installs missing Python packages (`backend/requirements.txt`)
2. creates `backend/.env` on first run — add `GEMINI_API_KEY` there for live AI
3. installs frontend packages (`npm ci`) when needed
4. rebuilds the React app only when its source has changed
5. starts Flask on `:5000`, serving the built app and `/api/*` from the same origin (no CORS, no second terminal)

Ctrl+C stops everything.

| Command | Use it for |
|---|---|
| `python run.py` | Demo / normal use — one port, production build |
| `python run.py --dev` | Frontend work — Vite hot reload on `:5173`, API proxied to `:5000`, still one terminal |
| `python run.py --port 8000` | Port 5000 is taken |
| `python run.py --rebuild` | Force a fresh frontend build |
| `python run.py --no-browser` | Don't open a browser tab |

Use a virtual environment if you prefer (`python -m venv venv`, activate it, then `python run.py`).

**The app runs with no API key and no database setup.** AI stages degrade to deterministic code, and storage falls back to a local SQLite file. Check what is live:

```
GET /api/health
→ {"status":"ok","gemini":"live","model":"gemini-3.6-flash","catalog":16,"database":"postgresql"}
```

Set `ADMIN_EMAIL` / `ADMIN_PASSWORD` to create the first admin account at startup. People sign up as Homeowner or Architect; admins grant the Kohler team or admin roles from the Admin console.

---

## Deploy

1. **Neon** — create a project and copy the connection string (keep `?sslmode=require`). Tables are created automatically on first boot.
2. **Render (API)** — *New → Blueprint* → pick this repo; `render.yaml` defines the `plumbline-api` web service (root `backend/`, gunicorn, health check `/api/health`). Fill in the prompted env vars:
   `DATABASE_URL` (Neon), `ALLOWED_ORIGINS` (your Vercel URL, e.g. `https://plumbline.vercel.app`), `ADMIN_EMAIL`, `ADMIN_PASSWORD`, optionally `GEMINI_API_KEY`. `SECRET_KEY` is generated by Render. A `Procfile` is included for other hosts.
3. **Vercel (frontend)** — import the repo, set **Root Directory = `frontend`** (Vite is detected; `vercel.json` adds SPA rewrites), and set `VITE_API_URL=https://<your-service>.onrender.com`. Redeploy after changing it, since it is baked in at build time.

The blueprint uses Render's `starter` plan so the API stays warm (the free plan sleeps when idle; the UI shows a "waking up" message if it does).

---

## Tests

```bash
make test            # backend: pytest (in-memory SQLite, LLM stubbed offline)
make frontend-test   # frontend: vitest
```

The backend tests stub the model to prove the loop: a deliberately bad first proposal is caught, critiqued and repaired; bad alternatives are dropped; drag-edits get the same verifier; roles and project ownership are enforced. CI (`.github/workflows/ci.yml`) runs both suites plus a production build on every PR.

---

## Sustainability

Every design is checked against EPA WaterSense limits — the same thresholds independently tested per product:

- Toilet ≤ 1.28 gpf
- Shower ≤ 2.0 gpm
- Lavatory faucet ≤ 1.5 gpm

Annual water saving is modelled per fixture class against a legacy 3.5 gpf / 2.5 gpm baseline, scaled by household size. A typical family-of-four design saves **~27,886 gallons per year**.

Water savings are modelled from published flow ratings and assumed usage patterns, not metered data. Assumptions are stated in `solver.py` and changeable in one place.

---

## Scalability

Each extension below is a loader or config change — the solver and verifier don't move:

| Extension | Where it plugs in | Why it's not a rewrite |
|---|---|---|
| Live product catalogue | `load_catalog()` → PIM/API | Solver is catalogue-agnostic |
| Regional plumbing codes | Constants in `layout.py` → code profile | Clearances are data, not logic (IS 1172 / IBC / ADA) |
| Multi-room / whole-home | `solve_bathroom_bundle()` per room | Solver is pure and stateless — parallelises trivially |
| Dealer quote export | `/api/design` JSON payload | SKUs, prices and verified plan already in the response |

---

## Known limitations

- Catalogue is a 16-product representative sample, not a live product feed
- Rectangular rooms only; one fixed door position (bottom-left, 30-inch swing)
- Water savings modelled from published ratings, not metered usage data
- Auth is email + password with signed tokens; no password reset, SSO or login rate limiting yet
- The 3D view uses simplified fixture massing, not manufacturer CAD models

---

## Business alignment

| Commitment | What a design tool must do | How Plumbline delivers it |
|---|---|---|
| Design excellence | Theme fit and spatial quality as first-class objectives | Theme-weighted ranking; per-theme arrangement guidance in the LLM prompt |
| Water conservation | Efficiency as a hard constraint, not a badge | Per-product WaterSense check; modelled annual savings vs legacy baseline |
| Operational efficiency | Fewer rework cycles, quote-ready output | Non-compliant layouts caught at specification time — every rejected attempt in the trace is a rework cycle that never reached an installer |
| Manufacturer channel | Output specifiable through showroom/dealer | `/api/design` returns SKUs, prices, flow ratings and a verified plan in one payload |

---

## Notice

This repository is an independent student case-study prototype. It is not affiliated with or endorsed by any manufacturer. Product data is a representative sample compiled from public specifications for demonstration purposes only.

See [`NOTICE.md`](NOTICE.md) for full notice.
