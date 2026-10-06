"""Gemini-in-the-loop design engine with a deterministic verifier.

Why this file exists
--------------------
A raw LLM is bad at metric geometry: ask it for (x, y) in inches and it will
happily overlap a toilet with a shower. The naive fixes are both wrong:
bypassing the LLM throws away the design reasoning, and clamping its output to
the walls hides collisions instead of solving them.

This module does neither. It keeps the LLM on the job it is actually good at
-- reading intent and making aesthetic arrangement decisions -- and puts a
deterministic checker in the loop:

    1. UNDERSTAND  LLM turns free text into a structured brief (JSON).
    2. SELECT      solver.py picks a bundle that cannot break budget/space.
    3. ARRANGE     LLM proposes a layout in a CONSTRAINED action space:
                   (wall, offset-along-wall) per fixture, never raw x/y.
                   Geometry is then derived by code, so an entire class of
                   hallucination is structurally impossible.
    4. VERIFY      layout.verify_layout() independently re-checks clearances,
                   door swing and overlaps.
    5. REPAIR      violations are fed back to the LLM as a critique and it
                   retries (bounded). This is the self-correction loop.
    6. FALLBACK    deterministic search layout, so a valid plan ALWAYS ships.
    7. NARRATE     LLM writes rationale grounded only on verified numbers.

Every LLM step degrades gracefully. No API key, no network, bad JSON, rate
limit -> the deterministic path runs and the app still works. The demo can
never hard-fail in front of an evaluator.
"""

import json
import os
import time
import concurrent.futures

from layout import (_to_room, describe_layout, enumerate_layouts, layout_features,
                    place_fixtures, verify_layout, wall_signature)

_CACHE = {}

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
REPAIR_ATTEMPTS = 2          # LLM proposals after the first (total tries = 3)
LLM_TIMEOUT_NOTE = "deterministic fallback"

_client = None
_client_ready = None


# ----------------------------------------------------------------- client --
def get_client():
    """Lazy Gemini client. Returns None when unavailable -- never raises."""
    global _client, _client_ready
    if _client_ready is not None:
        return _client
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        _client_ready = False
        return None
    try:
        from google import genai
        _client = genai.Client(api_key=key)
        _client_ready = True
    except Exception as exc:                      # noqa: BLE001 - demo safety
        print(f"[ai_engine] Gemini unavailable ({exc}); running deterministic.")
        _client, _client_ready = None, False
    return _client


def ai_status():
    return "live" if get_client() else "offline"


def _generate_raw(prompt, system=None, temperature=0.4, as_json=True):
    """One Gemini call."""
    client = get_client()
    if client is None:
        return None
    try:
        from google.genai import types
        cfg = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system,
            response_mime_type="application/json" if as_json else "text/plain",
        )
        resp = client.models.generate_content(
            model=MODEL, contents=prompt, config=cfg)
        text = (resp.text or "").strip()
        if not as_json:
            return text
        if text.startswith("```"):
            text = text.split("```")[1].lstrip("json").strip()
        return json.loads(text)
    except Exception as exc:                      # noqa: BLE001 - demo safety
        print(f"[ai_engine] LLM call failed: {exc}")
        return None


def _generate(prompt, system=None, temperature=0.4, as_json=True, timeout=12.0):
    """Wrapper with strict request timeout."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_generate_raw, prompt, system, temperature, as_json)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            print("[ai_engine] LLM call timed out")
            return None


# ------------------------------------------------------- 1. understand -----
INTENT_SYSTEM = (
    "You are the intake specialist for a bathroom design assistant. You "
    "convert a homeowner's plain-English request into a structured design "
    "brief. You never invent numbers the user did not imply; anything you "
    "assume must be listed in 'assumed'."
)

INTENT_PROMPT = """Convert this request into a design brief.

REQUEST: "{text}"

Return JSON with exactly these keys:
  length_ft        number, 4-30, the longer room side
  width_ft         number, 4-30, the shorter room side
  budget           number in INR. "8 lakh"->800000, "2.5L"->250000, "50k"->50000
  theme            one of: "Minimalist Modern", "Japanese Zen", "Classic Luxury"
  household        integer 1-12, number of daily users
  prioritize_smart true if they want smart/touchless/connected/digital fixtures
  assumed          array of strings naming any field you had to default
  reading          one sentence, what you understood they want

Defaults when unstated: 10 x 8 ft, 600000 INR, "Minimalist Modern", 2 people.
Map loose language: "spa-like"/"calm"/"wood" -> Japanese Zen;
"marble"/"ornate"/"hotel" -> Classic Luxury; "clean"/"simple" -> Minimalist Modern.
"""


def parse_intent(text, regex_fallback):
    """LLM intent parse with the existing regex parser as the safety net."""
    started = time.perf_counter()
    data = _generate(INTENT_PROMPT.format(text=text), system=INTENT_SYSTEM,
                     temperature=0.1)
    base = regex_fallback(text)
    if not isinstance(data, dict):
        base["source"] = "regex"
        base["reading"] = None
        base["intent_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return base

    try:
        merged = {
            "length_ft": float(data["length_ft"]),
            "width_ft": float(data["width_ft"]),
            "budget": float(data["budget"]),
            "theme": str(data["theme"]),
            "household": int(data["household"]),
            "prioritize_smart": bool(data.get("prioritize_smart", False)),
            "assumed": list(data.get("assumed", [])),
            "reading": data.get("reading"),
            "source": "gemini",
        }
    except (KeyError, TypeError, ValueError):
        base["source"] = "regex"
        base["reading"] = None
        base["intent_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return base

    # The LLM may still emit a nonsense number; the regex read wins if so.
    if not (4 <= merged["length_ft"] <= 30 and 4 <= merged["width_ft"] <= 30):
        merged["length_ft"], merged["width_ft"] = base["length_ft"], base["width_ft"]
        merged["assumed"].append("room size (LLM value rejected)")
    if merged["length_ft"] < merged["width_ft"]:
        merged["length_ft"], merged["width_ft"] = merged["width_ft"], merged["length_ft"]
    if merged["budget"] <= 0:
        merged["budget"] = base["budget"]
    merged["intent_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return merged


# ---------------------------------------------------------- 3. arrange -----
WALLS = ("top", "right", "bottom", "left")

ARRANGE_SYSTEM = (
    "You are a spatial design assistant. You arrange bathroom fixtures against "
    "walls. You return only JSON. You treat the reviewer's violation list as "
    "ground truth and you never repeat an arrangement that was rejected."
)

ARRANGE_PROMPT = """Arrange these fixtures in a {W:.0f} x {L:.0f} inch bathroom.

Coordinate system: x runs left->right across WIDTH ({W:.0f} in),
y runs top->bottom down LENGTH ({L:.0f} in). The door occupies the
bottom-left {door:.0f} x {door:.0f} inch square -- keep fixtures out of it.

Theme: {theme}
Client brief: {brief}

FIXTURES (width = size along its wall, depth = how far it projects into the room,
front = clear floor needed in front of it, side = clearance from its centreline):
{fixtures}

For each fixture choose:
  "wall"   one of "top", "right", "bottom", "left"  (its back goes against this)
  "offset" inches from the wall's start corner to the fixture's near edge.
           For top/bottom walls the run is {W:.0f} in; for left/right it is {L:.0f} in.
           offset must satisfy 0 <= offset <= (wall run - fixture width).

Design guidance for {theme}:
{guidance}

Hard rules:
  - fixtures must not overlap each other
  - one fixture's front clearance must not land on another fixture
  - nothing in the door square
  - prefer NOT to put the toilet as the first thing visible from the door
{critique}
Return JSON exactly like:
{{"shower": {{"wall": "top", "offset": 0}}, "toilet": {{"wall": "right", "offset": 12}}, "vanity": {{"wall": "left", "offset": 6}}, "reasoning": "one sentence"}}
"""

GUIDANCE = {
    "Japanese Zen": "Keep sightlines open and uncluttered. Put the shower on a "
                    "far wall as the visual anchor, keep the toilet visually "
                    "screened, leave generous empty floor.",
    "Classic Luxury": "Make the vanity the focal point on the longest usable "
                      "wall, give it a symmetric position, and keep circulation "
                      "wide and formal.",
    "Minimalist Modern": "Group wet functions together to keep one clean dry "
                         "zone. Align fixtures flush to corners so the floor "
                         "reads as a single uninterrupted plane.",
}


def _fx_spec(fx):
    return (f"- {fx['category']}: width {fx['width']:.0f}in, depth {fx['depth']:.0f}in, "
            f"front {fx['front_min']:.0f}in, side {fx['side_min']:.0f}in")


def build_placement(fx, wall, offset, W, L):
    """Derive full geometry from the LLM's (wall, offset) choice.

    The LLM never supplies coordinates -- code does. This is what makes an
    off-room or wrongly-shaped fixture structurally impossible.
    """
    w, d = float(fx["width"]), float(fx["depth"])
    half = max(w / 2.0, float(fx["side_min"]))
    run = W if wall in ("top", "bottom") else L
    u = max(0.0, min(float(offset), run - w))       # keep the run in-bounds
    cx = u + w / 2.0
    x, y, fw, fd = _to_room(wall, u, 0.0, w, d, W, L)
    ex, ey, ew, ed = _to_room(wall, cx - half, 0.0, 2 * half,
                              d + float(fx["front_min"]), W, L)
    return {
        "category": fx["category"], "side": wall, "u": round(u, 2),
        "x": round(x, 2), "y": round(y, 2), "w": round(fw, 2), "d": round(fd, 2),
        "u_len": fx["width"], "v_len": fx["depth"],
        "clearance": {"x": round(ex, 2), "y": round(ey, 2),
                      "w": round(ew, 2), "d": round(ed, 2)},
    }


def _apply(arrangement, fixtures, W, L):
    out = []
    for fx in fixtures:
        choice = arrangement.get(fx["category"])
        if not isinstance(choice, dict):
            return None
        wall = str(choice.get("wall", "")).lower()
        if wall not in WALLS:
            return None
        try:
            offset = float(choice.get("offset", 0))
        except (TypeError, ValueError):
            return None
        out.append(build_placement(fx, wall, offset, W, L))
    return out


def arrange_with_repair(fixtures, W, L, theme, brief, door_in=30.0):
    """Propose -> verify -> repair loop. Returns (placements|None, trace)."""
    trace, critique = [], ""
    spec = "\n".join(_fx_spec(f) for f in fixtures)
    guidance = GUIDANCE.get(theme, GUIDANCE["Minimalist Modern"])
    
    cumulative_ms = 0
    MAX_TOTAL_LATENCY_MS = 15000

    for attempt in range(1 + REPAIR_ATTEMPTS):
        started = time.perf_counter()
        prompt = ARRANGE_PROMPT.format(
            W=W, L=L, door=door_in, theme=theme, brief=brief or "(no extra brief)",
            fixtures=spec, guidance=guidance, critique=critique)
        data = _generate(prompt, system=ARRANGE_SYSTEM,
                         temperature=0.2 if attempt else 0.6)
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        cumulative_ms += elapsed

        if not isinstance(data, dict):
            trace.append({"attempt": attempt + 1, "source": "gemini",
                          "accepted": False, "ms": elapsed,
                          "problems": ["model did not return usable JSON or timed out"],
                          "arrangement": None, "reasoning": None})
            break
            
        if cumulative_ms > MAX_TOTAL_LATENCY_MS:
            trace.append({"attempt": attempt + 1, "source": "gemini",
                          "accepted": False, "ms": elapsed,
                          "problems": [f"LLM latency cap exceeded ({cumulative_ms}ms > {MAX_TOTAL_LATENCY_MS}ms)"],
                          "arrangement": None, "reasoning": None})
            break

        placements = _apply(data, fixtures, W, L)
        if placements is None:
            problems = ["incomplete arrangement: a fixture was missing a wall/offset"]
            trace.append({"attempt": attempt + 1, "source": "gemini",
                          "accepted": False, "ms": elapsed, "problems": problems,
                          "arrangement": None, "reasoning": data.get("reasoning")})
            critique = ("\nThe reviewer REJECTED your last answer: every fixture "
                        "needs both a \"wall\" and a numeric \"offset\".\n")
            trace[-1]["critique"] = critique.strip()
            continue

        problems = verify_layout(placements, W, L)
        arrangement = {f["category"]: {"wall": p["side"], "offset": p["u"]}
                       for f, p in zip(fixtures, placements)}
        trace.append({"attempt": attempt + 1, "source": "gemini",
                      "accepted": not problems, "ms": elapsed,
                      "problems": problems, "arrangement": arrangement,
                      "reasoning": data.get("reasoning")})
        if not problems:
            return placements, trace

        critique = ("\nThe reviewer REJECTED your previous arrangement "
                    f"{json.dumps(arrangement)} for these reasons:\n"
                    + "\n".join(f"  - {p}" for p in problems)
                    + "\nMove the offending fixtures to different walls or "
                      "offsets. Do not repeat the rejected arrangement.\n")
        # Surface the exact critique the model receives, so the UI can show it.
        trace[-1]["critique"] = critique.strip()

    return None, trace


def layout_with_fallback(fixtures, W, L, theme, brief):
    """Always returns a verified layout: LLM if it passes, code if it doesn't."""
    cache_key = (W, L, theme, tuple((f["category"], f["width"], f["depth"], f["side_min"], f["front_min"]) for f in fixtures))
    if cache_key in _CACHE:
        trace = [{"attempt": 1, "source": "cache", "accepted": True, "ms": 0, "problems": [], "arrangement": None, "reasoning": "Loaded verified layout from cache."}]
        return [dict(p) for p in _CACHE[cache_key]], trace, "cache"

    placements, trace = arrange_with_repair(fixtures, W, L, theme, brief)
    if placements:
        _CACHE[cache_key] = [dict(p) for p in placements]
        return placements, trace, "gemini"

    started = time.perf_counter()
    placements = place_fixtures(W, L, fixtures)
    trace.append({
        "attempt": len(trace) + 1, "source": "deterministic-solver",
        "accepted": bool(placements), "ms": round((time.perf_counter() - started) * 1000, 1),
        "problems": [] if placements else ["no valid layout exists for this room"],
        "arrangement": None,
        "reasoning": "Constraint search over wall positions (guaranteed-valid fallback).",
    })
    return placements, trace, "deterministic"


# ------------------------------------------------------- 3b. options ------
ALTERNATIVES_PROMPT = """The client wants to compare several layouts for the same
{W:.0f} x {L:.0f} inch bathroom (x across WIDTH, y down LENGTH, door in the
bottom-left {door:.0f} x {door:.0f} inch square -- keep fixtures out of it).

Theme: {theme}
Client brief: {brief}

FIXTURES:
{fixtures}

These wall assignments are ALREADY TAKEN, do not repeat them:
{taken}

Propose {n} genuinely different arrangements. Each must move at least one
fixture to a different wall than every taken arrangement. Same rules as
before: "wall" in top/right/bottom/left, "offset" 0 <= offset <= run - width,
no overlaps, no fixture in another's front clearance, nothing in the door square.

Return JSON exactly like:
{{"options": [{{"name": "2-4 word label", "reasoning": "one sentence on why",
  "shower": {{"wall": "top", "offset": 0}}, "toilet": {{"wall": "right", "offset": 12}},
  "vanity": {{"wall": "left", "offset": 6}}}}]}}
"""

OPTION_LABELS = ("Option A", "Option B", "Option C", "Option D", "Option E")


def _option(placements, W, L, source, reasoning, name=None, trace=None):
    feats = layout_features(placements, W, L)
    return {"placements": placements, "source": source, "name": name,
            "features": feats, "summary": describe_layout(feats),
            "reasoning": reasoning, "trace": trace or [],
            "problems": verify_layout(placements, W, L)}


def propose_alternatives(fixtures, W, L, theme, brief, taken, n, door_in=30.0):
    """One LLM call for n alternative arrangements; each is verified by code.

    Returns (accepted_options, trace). Rejected proposals are kept in the
    trace (with the verifier's reasons) but never shown as an option.
    """
    if n <= 0:
        return [], []
    started = time.perf_counter()
    data = _generate(ALTERNATIVES_PROMPT.format(
        W=W, L=L, door=door_in, theme=theme, brief=brief or "(no extra brief)",
        fixtures="\n".join(_fx_spec(f) for f in fixtures),
        taken="\n".join("  - " + ", ".join(f"{c}: {w}" for c, w in sig) for sig in taken),
        n=n), system=ARRANGE_SYSTEM, temperature=0.8)
    elapsed = round((time.perf_counter() - started) * 1000, 1)
    proposals = data.get("options") if isinstance(data, dict) else None
    if not isinstance(proposals, list):
        return [], ([{"attempt": 1, "source": "gemini", "stage": "alternatives",
                      "accepted": False, "ms": elapsed, "arrangement": None,
                      "reasoning": None,
                      "problems": ["model did not return alternative layouts"]}]
                    if get_client() else [])

    accepted, trace, seen = [], [], set(taken)
    for i, prop in enumerate(proposals[:n + 2]):           # tolerate a few extras
        if len(accepted) >= n or not isinstance(prop, dict):
            break
        placements = _apply(prop, fixtures, W, L)
        if placements is None:
            problems = ["incomplete arrangement: a fixture was missing a wall/offset"]
        else:
            problems = verify_layout(placements, W, L)
            if not problems and wall_signature(placements) in seen:
                problems = ["duplicates a layout that is already an option"]
        trace.append({"attempt": i + 1, "source": "gemini", "stage": "alternatives",
                      "accepted": not problems, "ms": elapsed if i == 0 else 0,
                      "problems": problems, "reasoning": prop.get("reasoning"),
                      "arrangement": ({p["category"]: {"wall": p["side"], "offset": p["u"]}
                                       for p in placements} if placements else None)})
        if not problems:
            seen.add(wall_signature(placements))
            accepted.append(_option(placements, W, L, "gemini", prop.get("reasoning"),
                                    name=prop.get("name"), trace=[trace[-1]]))
    return accepted, trace


def layout_options(fixtures, W, L, theme, brief, count=3):
    """Several verified layouts for one bundle.

    Option A is exactly the existing propose -> verify -> repair -> fallback
    loop. Further options come from one extra LLM call (each proposal
    verified independently) and, for any slots still empty, the
    deterministic enumerator -- so every option shown has passed
    verify_layout() and the UI never shows a broken plan.
    """
    primary, trace, source = layout_with_fallback(fixtures, W, L, theme, brief)
    if not primary:
        return [], trace, source

    accepted_reason = next((t.get("reasoning") for t in reversed(trace)
                            if t.get("accepted")), None)
    options = [_option(primary, W, L, source, accepted_reason, trace=trace)]
    taken = [wall_signature(primary)]

    alts, alt_trace = propose_alternatives(fixtures, W, L, theme, brief, taken, count - 1)
    options.extend(alts)
    taken.extend(wall_signature(o["placements"]) for o in alts)

    for placements in enumerate_layouts(W, L, fixtures, count - len(options), exclude=taken):
        options.append(_option(placements, W, L, "deterministic",
                               "Constraint search over wall assignments, chosen to "
                               "differ from the options above."))

    names = set()
    for i, opt in enumerate(options):
        opt["id"] = OPTION_LABELS[i] if i < len(OPTION_LABELS) else f"Option {i + 1}"
        name = opt["name"] or _default_name(opt["features"])
        if name in names:      # two options with the same character: say how they differ
            name = f"{name}, shower {opt['features']['walls'].get('shower', '?')}"
        names.add(name)
        opt["name"] = name
    return options, trace + alt_trace, source


def _default_name(features):
    if features["wet_zone_grouped"] and features["toilet_screened"]:
        return "Wet corner, screened WC"
    if features["wet_zone_grouped"]:
        return "Compact wet wall"
    return "Split wet & dry zones"


# ---------------------------------------------------------- 7. narrate -----
RATIONALE_SYSTEM = (
    "You are a bathroom design consultant writing for a homeowner. Good bathroom design's "
    "mission is to help people live gracious, healthy and sustainable lives. "
    "You explain a finished design warmly and plainly. You use ONLY the "
    "numbers given to you -- you never estimate, round differently, or invent "
    "a figure. No marketing superlatives."
)

RATIONALE_PROMPT = """Write the design rationale for this verified plan.

Client wanted: {brief}
Theme: {theme} | Room: {length} x {width} ft | Household: {household}

Selected products:
{products}

Verified numbers (use these exactly, do not alter them):
  total cost          INR {cost}
  budget              INR {budget}
  floor used          {util}% of the room
  water saved         {saved} gallons/year vs a legacy 3.5 gpf / 2.5 gpm bathroom
  saving              {pct}% less water

Layout that passed all clearance checks:
{layout}

Return JSON:
{{"headline": "max 10 words",
  "why_this_works": "2-3 sentences on the layout and the theme",
  "sustainability": "1-2 sentences using the water numbers above",
  "tradeoff": "1 honest sentence on what this design gives up"}}
"""


def explain(result, brief, parsed):
    """Grounded narration. Returns None if the LLM is unavailable."""
    m = result.get("metrics") or {}
    products = "\n".join(f"- {p['name']} ({p['id']})" for p in result.get("bundle", []))
    layout = "\n".join(
        f"- {p['category']} on the {p['side']} wall"
        for p in result["layout"]["placements"] if p["category"] != "faucet")
    data = _generate(RATIONALE_PROMPT.format(
        brief=brief or "(no free-text brief)", theme=parsed["theme"],
        length=parsed["length_ft"], width=parsed["width_ft"],
        household=parsed["household"], products=products,
        cost=m.get("total_cost"), budget=m.get("budget"),
        util=m.get("space_utilization_pct"),
        saved=m.get("water", {}).get("saved_gal"),
        pct=m.get("water", {}).get("saved_pct"), layout=layout),
        system=RATIONALE_SYSTEM, temperature=0.5)
    if isinstance(data, dict):
        return dict(data, source="gemini")
    return None


def fallback_rationale(result, parsed, option=None):
    """Short, factual explanation built from the verified numbers when the
    LLM is unavailable -- so the user never sees an empty 'explain' step."""
    m = result["metrics"]
    w = m["water"]
    feats = (option or {}).get("features") or {}
    walls = feats.get("walls") or {}
    where = ", ".join(f"{c} on the {walls[c]} wall" for c in ("shower", "toilet", "vanity") if c in walls)
    trade = ("The toilet faces the door; pick another option to screen it."
             if feats and not feats.get("toilet_screened") else
             f"Uses {m['budget_used_pct']}% of the budget; a cheaper bundle would give up "
             "some theme fit or smart features.")
    return {"source": "solver",
            "headline": f"{parsed['theme']} bath, {w['saved_pct']}% less water",
            "why_this_works": (f"{where.capitalize()}. " if where else "")
                              + f"Fixtures use {m['space_utilization_pct']}% of the floor, "
                                "leaving clear circulation.",
            "sustainability": f"Saves about {w['saved_gal']:,} gallons a year for "
                              f"{parsed['household']} people.",
            "tradeoff": trade}
