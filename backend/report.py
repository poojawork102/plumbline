"""Downloadable PDF design report, tailored to who is reading it.

    homeowner  one page: cost vs budget, water saved, products, plan
    architect  + room geometry, placement schedule, clearance checks
    kohler     + SKU/flow detail, bundle selection maths, AI pipeline trace
               (admins get the kohler report)

The browser sends the design it is showing, but every number that matters
is recomputed here from the catalogue: prices, water use, WaterSense and the
layout verification. A tampered payload cannot produce a report that claims
a broken layout passes or a different water saving.
"""
import datetime as dt

from fpdf import FPDF

from layout import door_keepout, verify_layout
from solver import load_catalog, price_of, water_use

LEVELS = {"homeowner": 1, "architect": 2, "kohler": 3, "admin": 3}
TITLES = {1: "Homeowner summary", 2: "Architect report", 3: "Kohler team report"}
WATERSENSE = {"toilet": ("gpf", 1.28), "shower": ("gpm", 2.0), "faucet": ("gpm", 1.5)}

INK = (20, 20, 18)
MUTED = (120, 118, 110)
GOLD = (184, 151, 88)
OK = (47, 107, 79)
BAD = (211, 47, 47)
FILL = {"shower": (90, 125, 140), "toilet": (244, 242, 236), "vanity": (139, 115, 85),
        "faucet": (184, 151, 88)}


class ReportError(ValueError):
    pass


def _txt(value):
    """Core PDF fonts are Latin-1: replace the few symbols we use."""
    s = str(value)
    for a, b in (("₹", "Rs "), ("→", "->"), ("–", "-"), ("—", "-"), ("’", "'"),
                 ("“", '"'), ("”", '"'), ("′", "ft"), ("″", "in"), ("✓", "PASS"),
                 ("✗", "FAIL")):
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


def _money(x, currency):
    n = int(round(x))
    if currency != "INR":
        return f"${n:,}"
    digits = str(n)
    if len(digits) > 3:
        head, tail, groups = digits[:-3], digits[-3:], []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups + [tail])
    return "Rs " + digits


def _chosen_layout(design, selected, edits):
    options = design.get("options") or []
    chosen = next((o for o in options if o.get("id") == selected), options[0] if options else None)
    edit = (edits or {}).get(chosen["id"]) if chosen else None
    placements = ((edit or {}).get("placements") or (chosen or {}).get("placements")
                  or (design.get("layout") or {}).get("placements"))
    return chosen, placements, bool(edit)


def build_context(design, selected=None, edits=None, role="homeowner"):
    """Everything the PDF prints, recomputed from trusted sources."""
    if not isinstance(design, dict) or design.get("status") != "ok":
        raise ReportError("A valid design is needed for a report")
    try:
        inputs = design["inputs"]
        room = design["layout"]["room_in"]
        ids = [p["id"] for p in design["bundle"]]
        W, L = float(room["width"]), float(room["length"])
        household = int(inputs["household"])
        budget = float(inputs["budget"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReportError(f"design is incomplete: {exc}") from exc

    catalog = {p["id"]: p for p in load_catalog()}
    unknown = [i for i in ids if i not in catalog]
    if unknown:
        raise ReportError(f"unknown product id(s): {', '.join(unknown)}")
    bundle = [catalog[i] for i in ids]

    chosen, placements, edited = _chosen_layout(design, selected, edits)
    if not placements:
        raise ReportError("design has no layout")
    problems = verify_layout(placements, W, L)
    cost = sum(price_of(p) for p in bundle)
    foot = sum(p["dimensions_in"]["width"] * p["dimensions_in"]["depth"] / 144
               for p in bundle if p["category"] != "faucet")
    area = W * L / 144

    ws = []
    for p in bundle:
        if p["category"] in WATERSENSE:
            unit, limit = WATERSENSE[p["category"]]
            rated = p.get(unit, 0)
            ws.append({"category": p["category"], "name": p["name"], "rated": rated,
                       "unit": unit, "limit": limit, "ok": rated <= limit + 1e-9})

    return {
        "level": LEVELS.get(role, 1), "role": role, "currency": design.get("currency", "INR"),
        "inputs": inputs, "W": W, "L": L, "household": household, "budget": budget,
        "bundle": bundle, "cost": cost, "footprint_sqft": foot, "area_sqft": area,
        "water": water_use(bundle, household), "watersense": ws,
        "option": chosen, "edited": edited, "placements": placements, "problems": problems,
        "selection": design.get("selection"), "ai": design.get("ai"),
        "reasoning": design.get("reasoning"), "rationale": design.get("rationale"),
    }


class _PDF(FPDF):
    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*MUTED)
        self.cell(0, 5, _txt(f"Plumbline - generated {dt.date.today().isoformat()} - "
                             f"page {self.page_no()}"), align="C")


def _h(pdf, text):
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*INK)
    pdf.cell(0, 6, _txt(text.upper()), new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*GOLD)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(2)


def _bullet(pdf, text, color=INK):
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*color)
    pdf.multi_cell(0, 5, _txt(f"- {text}"), new_x="LMARGIN", new_y="NEXT")


def _table(pdf, header, rows, widths, align=None):
    pdf.set_font("Helvetica", "B", 7.5)
    pdf.set_text_color(*MUTED)
    for i, (h, w) in enumerate(zip(header, widths)):
        pdf.cell(w, 6, _txt(h.upper()), border="B", align=(align or {}).get(i, "L"))
    pdf.ln()
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*INK)
    for row in rows:
        for i, (v, w) in enumerate(zip(row, widths)):
            pdf.cell(w, 6, _txt(v), border="B", align=(align or {}).get(i, "L"))
        pdf.ln()


def _stats(pdf, items):
    """Row of big-number tiles."""
    x0, y0 = pdf.l_margin, pdf.get_y()
    w = (pdf.w - pdf.l_margin - pdf.r_margin - 4 * (len(items) - 1)) / len(items)
    for i, (label, value, note) in enumerate(items):
        x = x0 + i * (w + 4)
        pdf.set_draw_color(*GOLD)
        pdf.rect(x, y0, w, 20)
        pdf.set_xy(x + 3, y0 + 2)
        pdf.set_font("Helvetica", "B", 6.5)
        pdf.set_text_color(*MUTED)
        pdf.cell(w - 6, 4, _txt(label.upper()))
        pdf.set_xy(x + 3, y0 + 7)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(*INK)
        pdf.cell(w - 6, 6, _txt(value))
        pdf.set_xy(x + 3, y0 + 14)
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(*MUTED)
        pdf.cell(w - 6, 4, _txt(note))
    pdf.set_y(y0 + 24)


def _plan(pdf, ctx, max_w=80, max_h=90, show_clearance=False):
    W, L = ctx["W"], ctx["L"]
    s = min(max_w / W, max_h / L)
    x0 = pdf.l_margin + (pdf.w - pdf.l_margin - pdf.r_margin - W * s) / 2
    y0 = pdf.get_y() + 4
    bad = {p.split(" ")[0] for p in ctx["problems"]}
    if show_clearance:
        pdf.set_draw_color(*GOLD)
        pdf.set_line_width(0.2)
        for p in ctx["placements"]:
            c = p.get("clearance")
            if c and p["category"] != "faucet":
                pdf.set_dash_pattern(dash=1, gap=1)
                pdf.rect(x0 + c["x"] * s, y0 + c["y"] * s, c["w"] * s, c["d"] * s)
        pdf.set_dash_pattern()
    for p in ctx["placements"]:
        pdf.set_fill_color(*FILL.get(p["category"], (200, 200, 200)))
        pdf.set_draw_color(*(BAD if p["category"] in bad else INK))
        pdf.set_line_width(0.5 if p["category"] in bad else 0.25)
        pdf.rect(x0 + p["x"] * s, y0 + p["y"] * s, max(p["w"] * s, 0.6), max(p["d"] * s, 0.6),
                 style="DF")
    # labels last, centred, so the faucet never covers the vanity's label
    pdf.set_font("Helvetica", "B", 6)
    for p in ctx["placements"]:
        if p["category"] == "faucet":
            continue
        label = _txt(p["category"].upper())
        pdf.set_text_color(*((255, 255, 255) if p["category"] in ("shower", "vanity") else INK))
        pdf.text(x0 + (p["x"] + p["w"] / 2) * s - pdf.get_string_width(label) / 2,
                 y0 + (p["y"] + p["d"] / 2) * s + 1, label)
    dx, dy, dw, _ = door_keepout(L)
    pdf.set_draw_color(*GOLD)
    pdf.set_line_width(0.3)
    pdf.line(x0 + (dx + dw) * s, y0 + L * s, x0 + (dx + dw) * s, y0 + dy * s)
    pdf.set_draw_color(*INK)
    pdf.set_line_width(0.8)
    pdf.rect(x0, y0, W * s, L * s)
    pdf.set_line_width(0.2)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*MUTED)
    pdf.text(x0, y0 + L * s + 4, _txt(f"{W / 12:g} ft x {L / 12:g} ft - door bottom-left"))
    pdf.set_y(y0 + L * s + 7)


def render(ctx):
    lvl, cur = ctx["level"], ctx["currency"]
    inp, water = ctx["inputs"], ctx["water"]
    pdf = _PDF(format="A4")
    pdf.set_auto_page_break(True, margin=16)
    pdf.set_margins(16, 14, 16)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*GOLD)
    pdf.cell(0, 5, _txt("PLUMBLINE - " + TITLES[lvl].upper()), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Times", "", 20)
    pdf.set_text_color(*INK)
    head = (ctx.get("rationale") or {}).get("headline") or f"{inp['theme']} bathroom"
    pdf.cell(0, 10, _txt(head), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*MUTED)
    opt = ctx["option"] or {}
    pdf.cell(0, 5, _txt(f"{inp['length_ft']:g} x {inp['width_ft']:g} ft - {inp['theme']} - "
                        f"household of {ctx['household']} - {opt.get('id', 'Layout')}"
                        f"{' (edited)' if ctx['edited'] else ''}"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    verified = not ctx["problems"]
    _stats(pdf, [
        ("Total cost", _money(ctx["cost"], cur), f"{round(100 * ctx['cost'] / ctx['budget'])}% of budget"),
        ("Water saved", f"{water['saved_gal']:,} gal/yr", f"{water['saved_pct']}% less"),
        ("WaterSense", f"{sum(w['ok'] for w in ctx['watersense'])}/{len(ctx['watersense'])}",
         "fixtures certified"),
        ("Layout", "Verified" if verified else "Not valid",
         "all clearances clear" if verified else f"{len(ctx['problems'])} problem(s)"),
    ])

    _h(pdf, "At a glance")
    within = ctx["cost"] <= ctx["budget"] + 1e-9
    _bullet(pdf, f"{'Within' if within else 'Over'} budget: {_money(ctx['cost'], cur)} of "
                 f"{_money(ctx['budget'], cur)}", OK if within else BAD)
    _bullet(pdf, f"Saves about {water['saved_gal']:,} gallons a year vs a legacy bathroom "
                 f"(~{_money(water['saved_gal'] * 3.78 * 0.05, 'INR')} on water bills)")
    _bullet(pdf, f"Fixtures use {round(100 * ctx['footprint_sqft'] / ctx['area_sqft'], 1)}% "
                 "of the floor (limit 40%)")
    if not verified:
        for p in ctx["problems"]:
            _bullet(pdf, p, BAD)
    elif opt.get("summary"):
        _bullet(pdf, opt["summary"])

    _h(pdf, "Floor plan")
    _plan(pdf, ctx, show_clearance=lvl >= 2)

    _h(pdf, "Products")
    rows = []
    for p in ctx["bundle"]:
        row = [p["category"].title(), p["name"][:52]]
        if lvl >= 2:
            d = p["dimensions_in"]
            row.append(f"{d['width']} x {d['depth']} in")
        if lvl >= 3:
            row.append(p.get("sku", ""))
        row.append(_money(price_of(p), cur))
        rows.append(row)
    rows.append(["", "Total"] + [""] * (lvl - 1) + [_money(ctx["cost"], cur)])
    widths = {1: [22, 128, 28], 2: [20, 98, 30, 30], 3: [18, 78, 26, 28, 28]}[lvl]
    header = ["Item", "Product"] + (["Size"] if lvl >= 2 else []) + \
        (["SKU"] if lvl >= 3 else []) + ["Price"]
    _table(pdf, header, rows, widths, align={len(header) - 1: "R"})

    _h(pdf, "Water & EPA WaterSense")
    for w in ctx["watersense"]:
        _bullet(pdf, f"{w['category'].title()}: {w['rated']} {w['unit']} "
                     f"(WaterSense max {w['limit']}) - {'certified' if w['ok'] else 'NOT certified'}",
                OK if w["ok"] else BAD)
    if lvl >= 2:
        b, lb = water["breakdown"], water["legacy_breakdown"]
        _table(pdf, ["Fixture", "Plumbline gal/yr", "Legacy gal/yr", "Saved"],
               [[k.title(), f"{b[k]:,}", f"{lb[k]:,}", f"{lb[k] - b[k]:,}"]
                for k in ("toilet", "shower", "faucet")],
               [40, 46, 46, 46], align={1: "R", 2: "R", 3: "R"})

    if lvl >= 2:
        _h(pdf, "Placement schedule (inches, origin top-left)")
        _table(pdf, ["Fixture", "Wall", "Offset", "X", "Y", "W x D"],
               [[p["category"].title(), p.get("side", ""), f"{p.get('u', 0):g}" if "u" in p else "-",
                 f"{p['x']:g}", f"{p['y']:g}", f"{p['w']:g} x {p['d']:g}"]
                for p in ctx["placements"]],
               [30, 24, 24, 24, 24, 52])
        _h(pdf, "Compliance checks")
        _bullet(pdf, "Clearances, door swing and overlaps re-verified for this report: "
                     + ("all pass" if verified else "FAILED"), OK if verified else BAD)
        _bullet(pdf, f"Floor usage {ctx['footprint_sqft']:.1f} of "
                     f"{ctx['area_sqft'] * 0.4:.1f} sq ft allowed (40%)")
        _bullet(pdf, "Door: 30 in leaf, bottom-left corner, swing kept clear")
        _bullet(pdf, "Shared clear floor between fixtures is permitted; no clearance "
                     "zone lands on another fixture")

    if lvl >= 3:
        sel = ctx.get("selection") or {}
        if sel:
            _h(pdf, "Bundle selection")
            _bullet(pdf, f"{sel.get('combinations')} bundles -> {sel.get('within_floor_limit')} "
                         f"fit the floor -> {sel.get('within_budget')} within budget; chosen rank "
                         f"#{sel.get('rank')}")
            for r in sel.get("runners_up", []):
                _bullet(pdf, f"Runner-up {r.get('cost_label')}: swaps {', '.join(r.get('differs_by', []))}")
        ai = ctx.get("ai") or {}
        if ai:
            _h(pdf, "AI pipeline")
            _bullet(pdf, f"Intent: {ai.get('intent_source')} - layout: {ai.get('layout_source')} - "
                         f"{ai.get('attempts')} attempt(s), {ai.get('repairs')} repair(s) - "
                         f"model {ai.get('status')}")
            for t in (ai.get("trace") or [])[:8]:
                status = "accepted" if t.get("accepted") else "rejected"
                why = "; ".join(t.get("problems") or []) or (t.get("reasoning") or "")
                _bullet(pdf, f"#{t.get('attempt')} {t.get('source')} ({t.get('stage', 'primary')}) "
                             f"{status}: {why[:140]}", OK if t.get("accepted") else MUTED)
        _h(pdf, "Smart & health features")
        for p in ctx["bundle"]:
            feats = (p.get("smart_features") or []) + (p.get("health_features") or [])
            if feats:
                _bullet(pdf, f"{p['category'].title()}: {', '.join(feats)}")

    return bytes(pdf.output())


def build(design, selected=None, edits=None, role="homeowner"):
    return render(build_context(design, selected, edits, role))
