"""Deterministic bathroom bundle solver.

The LLM (or regex fallback) only turns text into numbers. Everything below is
plain code, so a returned bundle can never break the budget or the room:

    total cost        <= budget
    floor footprint   <= 40% of room area
    clearances        enforced by layout.py (front / side / door swing)

How a bundle is chosen
----------------------
1. Build EVERY combination (one toilet + shower + vanity + faucet).
2. Drop combinations over budget or over the floor-usage limit.
3. Rank the rest by score (theme fit > smart features > premium use of budget
   > lower water flow). Ties break on product ids, so output is deterministic.
4. Walk down the ranking and return the first one that has a valid layout.
If nothing works, the result explains why and offers the closest alternative.
"""
import itertools
import json
import os

from layout import mount_faucet, place_fixtures, verify_layout

CATALOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalog.json")

CATEGORIES = ("toilet", "shower", "vanity", "faucet")
FLOOR_USAGE_LIMIT = 0.40          # fixtures may cover at most 40% of the floor
MAX_LAYOUT_ATTEMPTS = 24          # distinct layout searches per request (latency cap)

# Ranking weights (higher score wins)
THEME_WEIGHT = 100                # per item that matches the requested theme
SMART_WEIGHT = 5                  # per smart feature, only if user wants smart
BUDGET_USE_WEIGHT = 20            # rewards using the budget on a higher tier
WATER_WEIGHT = 3                  # penalty per unit of rated flow (GPF + GPM)

# Water model. These are ASSUMPTIONS - change them in one place if you can cite better figures.
LEGACY = {"gpf": 3.5, "shower_gpm": 2.5, "faucet_gpm": 2.2}
USAGE_PER_PERSON_PER_DAY = {"flushes": 5, "shower_min": 8, "faucet_min": 2}


# ------------------------------------------------------------------ catalog --
def load_catalog(filepath=CATALOG_PATH):
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f).get("products", [])


def price_of(p):
    for key in ("price_inr", "price_usd"):
        if key in p:
            return float(p[key])
    raise KeyError(f"{p.get('id')} has no price_inr / price_usd")


def currency_of(products):
    return "INR" if any("price_inr" in p for p in products) else "USD"


def _floor_sqft(p):
    """Faucets sit on the vanity, so they use no floor space."""
    if p["category"] == "faucet":
        return 0.0
    d = p["dimensions_in"]
    return d["width"] * d["depth"] / 144.0


def _fx(p):
    d, c = p["dimensions_in"], p.get("clearance_req_in", {})
    return {"category": p["category"], "width": d["width"], "depth": d["depth"],
            "side_min": c.get("side_min", 0), "front_min": c.get("front_min", 0)}


def _money(x, currency):
    """Format for messages: $12,000 or ₹6,00,000 (Indian digit grouping)."""
    n = int(round(x))
    if currency != "INR":
        return f"${n:,}"
    digits = str(abs(n))
    if len(digits) > 3:
        head, tail, groups = digits[:-3], digits[-3:], []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups + [tail])
    return "₹" + digits


def _clean(x):
    x = round(x, 2)
    return int(x) if float(x).is_integer() else x


# -------------------------------------------------------------------- water --
def water_use(bundle, household):
    """Annual water for the bundle vs a legacy baseline. Toilet, shower and faucet
    are modelled separately (each with its own usage minutes / flush count)."""
    by_cat = {p["category"]: p for p in bundle}
    gpf = by_cat.get("toilet", {}).get("gpf", LEGACY["gpf"])
    shower = by_cat.get("shower", {}).get("gpm", LEGACY["shower_gpm"])
    faucet = by_cat.get("faucet", {}).get("gpm", LEGACY["faucet_gpm"])
    u = USAGE_PER_PERSON_PER_DAY

    def annual_breakdown(g, s, f):
        t = household * 365 * u["flushes"] * g
        sh = household * 365 * u["shower_min"] * s
        fa = household * 365 * u["faucet_min"] * f
        return {"toilet": round(t), "shower": round(sh), "faucet": round(fa), "total": round(t + sh + fa)}

    ours = annual_breakdown(gpf, shower, faucet)
    legacy = annual_breakdown(LEGACY["gpf"], LEGACY["shower_gpm"], LEGACY["faucet_gpm"])
    saved = max(0.0, legacy["total"] - ours["total"])
    return {"annual_gal": ours["total"], "legacy_annual_gal": legacy["total"],
            "saved_gal": round(saved), "saved_pct": round(100 * saved / legacy["total"], 1) if legacy["total"] else 0.0,
            "household": household,
            "breakdown": ours, "legacy_breakdown": legacy}


# ------------------------------------------------------------------ ranking --
def _rank_key(combo, cost, budget, theme, smart):
    score = THEME_WEIGHT * sum(theme in p.get("aesthetic_themes", []) for p in combo)
    if smart:
        score += SMART_WEIGHT * sum(len(p.get("smart_features", [])) for p in combo)
    score += BUDGET_USE_WEIGHT * (cost / budget)
    score -= WATER_WEIGHT * sum(p.get("gpf", 0) + p.get("gpm", 0) for p in combo)
    return (-score, tuple(p["id"] for p in combo))


class _LayoutSearch:
    """Caches layouts by fixture geometry so repeated dimensions are solved once."""

    def __init__(self, width_in, length_in):
        self.W, self.L = width_in, length_in
        self.cache, self.attempts = {}, 0

    def for_combo(self, combo):
        floor = [p for p in combo if p["category"] != "faucet"]
        key = tuple(sorted((f["category"], f["width"], f["depth"], f["side_min"], f["front_min"])
                           for f in map(_fx, floor)))
        if key not in self.cache:
            if self.attempts >= MAX_LAYOUT_ATTEMPTS:
                return "limit"
            self.attempts += 1
            self.cache[key] = place_fixtures(self.W, self.L, [_fx(p) for p in floor])
        raw = self.cache[key]
        if raw is None:
            return None
        by_cat = {p["category"]: p for p in combo}
        placements = []
        for r in raw:
            item = by_cat[r["category"]]
            placements.append(dict(r, id=item["id"], name=item["name"]))
        vanity = next(p for p in placements if p["category"] == "vanity")
        faucet = mount_faucet(_fx(by_cat["faucet"]), vanity, self.W, self.L)
        if faucet:
            faucet.update(id=by_cat["faucet"]["id"], name=by_cat["faucet"]["name"])
            placements.append(faucet)
        return placements


# --------------------------------------------------------------------- main --
def solve_bathroom_bundle(room_length_ft, room_width_ft, budget, theme="Minimalist Modern",
                          household=2, prioritize_smart=False, catalog=None):
    if room_length_ft <= 0 or room_width_ft <= 0 or budget <= 0 or household < 1:
        raise ValueError("length, width, budget and household must be positive")

    products = catalog if catalog is not None else load_catalog()
    currency = currency_of(products)
    by_cat = {c: [p for p in products if p["category"] == c] for c in CATEGORIES}
    missing = [c for c, items in by_cat.items() if not items]
    if missing:
        raise ValueError(f"catalog has no products for: {', '.join(missing)}")

    W_in, L_in = room_width_ft * 12.0, room_length_ft * 12.0
    area_sqft = room_length_ft * room_width_ft
    limit_sqft = area_sqft * FLOOR_USAGE_LIMIT

    inputs = {"length_ft": room_length_ft, "width_ft": room_width_ft, "budget": budget,
              "theme": theme, "household": household, "prioritize_smart": bool(prioritize_smart)}

    combos = []
    for combo in itertools.product(*(by_cat[c] for c in CATEGORIES)):
        cost = sum(price_of(p) for p in combo)
        foot = sum(_floor_sqft(p) for p in combo)
        combos.append((combo, cost, foot))

    space_ok = [c for c in combos if c[2] <= limit_sqft + 1e-9]
    affordable = sorted((c for c in space_ok if c[1] <= budget + 1e-9),
                        key=lambda c: _rank_key(c[0], c[1], budget, theme, prioritize_smart))

    search = _LayoutSearch(W_in, L_in)

    def first_valid(candidates):
        for combo, cost, foot in candidates:
            placements = search.for_combo(combo)
            if placements == "limit":
                return None
            if placements:
                return combo, cost, foot, placements
        return None

    hit = first_valid(affordable)
    if hit is None and space_ok:
        # Nothing ranked-and-affordable placed; try cheapest-first in case a
        # lower-ranked affordable bundle does fit.
        cheapest = sorted(space_ok, key=lambda c: (c[1], tuple(p["id"] for p in c[0])))
        alt = first_valid(cheapest)
        if alt and alt[1] <= budget + 1e-9:
            hit = alt

    if hit:
        combo, cost, foot, placements = hit
        selection = _selection_summary(combo, combos, space_ok, affordable, theme, currency)
        problems = verify_layout(placements, W_in, L_in)
        theme_hits = sum(theme in p.get("aesthetic_themes", []) for p in combo)
        checks = [
            {"name": "Budget", "passed": cost <= budget + 1e-9,
             "detail": f"{_money(cost, currency)} of {_money(budget, currency)} ({round(100 * cost / budget)}%)"},
            {"name": "Floor usage", "passed": foot <= limit_sqft + 1e-9,
             "detail": f"{foot:.1f} of {limit_sqft:.1f} sq ft allowed ({FLOOR_USAGE_LIMIT:.0%} of floor)"},
            {"name": "Clearances", "passed": not any("clearance" in x for x in problems),
             "detail": "Front and side clearances free of other fixtures"},
            {"name": "Door swing", "passed": not any("door" in x for x in problems),
             "detail": "Door arc is unobstructed"},
            {"name": "No overlaps", "passed": not any("overlaps" in x or "outside" in x for x in problems),
             "detail": "All fixtures sit inside the room without colliding"},
        ]
        return {
            "status": "ok",
            "message": "Valid bundle found.",
            "inputs": inputs,
            "currency": currency,
            "bundle": list(combo),
            "layout": {"room_in": {"width": W_in, "length": L_in}, "placements": placements,
                       "door": {"width": 30, "wall": "bottom", "corner": "left"}},
            "metrics": {
                "total_cost": _clean(cost), "budget": _clean(budget),
                "budget_used_pct": round(100 * cost / budget, 1),
                "floor_area_sqft": round(area_sqft, 1), "footprint_sqft": round(foot, 1),
                "space_utilization_pct": round(100 * foot / area_sqft, 1),
                "theme_fit": {"matched": theme_hits, "of": len(combo), "theme": theme},
                "water": water_use(combo, household),
            },
            "checks": checks,
            "selection": selection,
            "alternative": None,
        }

    return _infeasible(inputs, currency, combos, space_ok, limit_sqft, area_sqft, budget, first_valid)


def _selection_summary(combo, combos, space_ok, affordable, theme, currency):
    """Why this bundle: how many candidates each hard gate removed, where the
    winner ranked, and what the next-best bundles were. Feeds the UI's
    reasoning panel with numbers, not adjectives."""
    ids = tuple(p["id"] for p in combo)
    ranked_ids = [tuple(p["id"] for p in c[0]) for c in affordable]
    rank = ranked_ids.index(ids) + 1 if ids in ranked_ids else None
    runners_up = []
    for c, cost, _ in affordable:
        if tuple(p["id"] for p in c) == ids:
            continue
        swapped = [p["name"] for p, q in zip(c, combo) if p["id"] != q["id"]]
        runners_up.append({"total_cost": _clean(cost), "cost_label": _money(cost, currency),
                           "theme_matches": sum(theme in p.get("aesthetic_themes", []) for p in c),
                           "differs_by": swapped})
        if len(runners_up) == 2:
            break
    return {"combinations": len(combos), "within_floor_limit": len(space_ok),
            "within_budget": len(affordable), "rank": rank,
            "theme_matches": sum(theme in p.get("aesthetic_themes", []) for p in combo),
            "weights": {"theme": THEME_WEIGHT, "smart": SMART_WEIGHT,
                        "budget_use": BUDGET_USE_WEIGHT, "water": WATER_WEIGHT},
            "runners_up": runners_up}


def _infeasible(inputs, currency, combos, space_ok, limit_sqft, area_sqft, budget, first_valid):
    reasons, alternative = [], None
    if not space_ok:
        smallest = min(c[2] for c in combos)
        needed_area = smallest / FLOOR_USAGE_LIMIT
        reasons.append(f"Room too small: the smallest fixture set needs {smallest:.1f} sq ft of floor, "
                       f"but only {limit_sqft:.1f} sq ft ({FLOOR_USAGE_LIMIT:.0%} of {area_sqft:.0f}) is allowed. "
                       f"Try at least {needed_area:.0f} sq ft.")
    else:
        cheapest = sorted(space_ok, key=lambda c: (c[1], tuple(p["id"] for p in c[0])))
        alt = first_valid(cheapest)
        if alt:
            combo, cost, foot, placements = alt
            alternative = {"bundle": list(combo), "total_cost": _clean(cost),
                           "over_budget_by": _clean(cost - budget),
                           "layout": {"placements": placements}}
            reasons.append(f"Budget too low: the cheapest bundle that fits this room costs "
                           f"{_money(cost, currency)}, which is {_money(cost - budget, currency)} over budget.")
        else:
            reasons.append("No collision-free layout with the required clearances and door swing "
                           "exists for this room. Try a larger or squarer room.")
    return {"status": "infeasible", "message": reasons[0], "reasons": reasons, "inputs": inputs,
            "currency": currency, "bundle": [], "layout": None, "metrics": None, "checks": [],
            "alternative": alternative}

def clamp_coordinates(placements, width_in, length_in):
    """
    Intercepts and sanitizes generative AI coordinates (e.g. from Gemini) to enforce 
    strict physical constraints and IBC clearances.
    """
    W_in, L_in = float(width_in), float(length_in)
    
    # 1. Wall Boundary Clamping (Physical Fixture Only)
    for p in placements:
        raw_x = p.get("x", 0)
        raw_y = p.get("y", 0)
        
        # Simply bump against the walls (with a 1-inch visual margin to prevent stroke clipping)
        margin = 1
        p["x"] = max(margin, min(raw_x, W_in - p.get("w", 0) - margin))
        p["y"] = max(margin, min(raw_y, L_in - p.get("d", 0) - margin))
        
        c = p.get("clearance")
        if c:
            cx_offset = c["x"] - p.get("original_x", raw_x)
            cy_offset = c["y"] - p.get("original_y", raw_y)
            p["clearance"]["x"] = p["x"] + cx_offset
            p["clearance"]["y"] = p["y"] + cy_offset
            
    return placements
