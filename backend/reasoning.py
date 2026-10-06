"""Builds the step-by-step reasoning shown in the UI.

Every step is assembled from what the pipeline actually did -- the parsed
brief, the solver's selection counts, the LLM's proposals and the verifier's
critiques -- never from a separate "explain yourself" LLM call that could
drift from the real decision.
"""


def _understand(parsed):
    src = parsed.get("source")
    who = {"gemini": "Gemini read the brief",
           "regex": "Offline parser read the brief (no LLM available)",
           "controls": "Values taken directly from the manual controls"}.get(src, src)
    detail = [f"Room {parsed['length_ft']:g} x {parsed['width_ft']:g} ft",
              f"budget {parsed['budget']:,.0f}", f"theme {parsed['theme']}",
              f"household of {parsed['household']}"]
    if parsed.get("prioritize_smart"):
        detail.append("smart fixtures prioritised")
    notes = [f"Assumed: {a}" for a in parsed.get("assumed") or []]
    short = (f"{parsed['length_ft']:g}×{parsed['width_ft']:g} ft · {parsed['theme']} · "
             f"{parsed['household']} people")
    return {"stage": "understand", "title": "Understand the brief", "actor": src, "short": short,
            "summary": who + ".", "said": parsed.get("reading"),
            "details": ["; ".join(detail)] + notes}


def _select(sel):
    details = [
        f"{sel['combinations']} possible bundles from the catalogue",
        f"{sel['within_floor_limit']} fit the 40% floor-area limit",
        f"{sel['within_budget']} are within budget",
        f"Ranked by theme fit (x{sel['weights']['theme']}), smart features "
        f"(x{sel['weights']['smart']}), budget use (x{sel['weights']['budget_use']}) "
        f"and water flow (-{sel['weights']['water']} per gpf/gpm)",
    ]
    for r in sel.get("runners_up", []):
        details.append(f"Runner-up at {r['cost_label']} swaps: {', '.join(r['differs_by'])}")
    rank = f"#{sel['rank']}" if sel.get("rank") else "the best valid"
    short = (f"Best of {sel['within_budget']} in-budget bundles · "
             f"{sel['theme_matches']}/4 match the theme")
    return {"stage": "select", "title": "Select products", "actor": "solver", "short": short,
            "summary": f"Chose bundle {rank} of {sel['within_budget']} affordable options "
                       f"({sel['theme_matches']} of 4 items match the theme).",
            "said": None, "details": details}


def _arrange(trace, source, llm_live):
    attempts = []
    for t in trace:
        if not llm_live and t.get("source") == "gemini" and not t.get("arrangement"):
            continue        # the model was never reachable: not an attempt worth showing
        attempts.append({
            "attempt": t.get("attempt"), "source": t.get("source"),
            "stage": t.get("stage", "primary"), "accepted": t.get("accepted"),
            "ms": t.get("ms"), "reasoning": t.get("reasoning"),
            "problems": t.get("problems") or [], "critique": t.get("critique"),
            "arrangement": t.get("arrangement")})
    # Only count proposals the verifier actually judged -- a model that never
    # answered (offline, timeout, bad JSON) was not "caught" by anything.
    rejected = sum(1 for t in trace if not t.get("accepted") and t.get("arrangement")
                   and t.get("stage", "primary") == "primary")
    by = {"gemini": "Gemini's proposal passed verification",
          "cache": "Re-used a previously verified layout",
          "deterministic": "Gemini could not produce a valid layout, so the "
                           "constraint solver supplied one"}.get(source, source)
    if source == "deterministic" and not llm_live:
        by = "No LLM available; the constraint solver placed the fixtures"
    elif source == "deterministic" and not rejected:
        by = "Gemini did not return a usable layout, so the constraint solver supplied one"
    short = {"gemini": "AI layout passed" + (f" after {rejected} fix(es)" if rejected else " first time"),
             "cache": "Re-used a verified layout"}.get(
        source, "Solver layout (AI offline)" if not llm_live else "Solver stepped in")
    return {"stage": "arrange", "title": "Arrange, verify & repair", "actor": source, "short": short,
            "summary": f"{by}. {rejected} rejected proposal(s) were caught by the verifier.",
            "said": None, "details": [], "attempts": attempts}


def _verify(checks, watersense):
    details = [f"{'PASS' if c['passed'] else 'FAIL'} {c['name']}: {c['detail']}"
               for c in checks]
    for w in watersense["items"]:
        details.append(f"{'PASS' if w['certified'] else 'FAIL'} WaterSense {w['category']}: "
                       f"{w['rated']} {w['unit']} (limit {w['limit']})")
    short = (f"{sum(c['passed'] for c in checks)}/{len(checks)} spatial · "
             f"{watersense['certified_count']}/{watersense['total']} WaterSense")
    return {"stage": "verify", "title": "Independent verification", "actor": "verifier", "short": short,
            "summary": f"{sum(c['passed'] for c in checks)}/{len(checks)} spatial checks and "
                       f"{watersense['certified_count']}/{watersense['total']} "
                       "EPA WaterSense checks passed.",
            "said": None, "details": details}


def _options(options):
    return {"stage": "options", "title": "Offer alternatives", "actor": "mixed",
            "short": f"{len(options)} verified layouts to compare",
            "summary": f"{len(options)} verified layout option(s) for the same products.",
            "said": None,
            "details": [f"{o['id']} - {o['name']} ({o['source']}): {o['summary']}"
                        for o in options]}


def _narrate(rationale):
    if not rationale:
        return {"stage": "narrate", "title": "Explain the design", "actor": "offline",
                "short": "No explanation available", "summary": "", "said": None, "details": []}
    actor = "gemini" if rationale.get("source") == "gemini" else "solver"
    return {"stage": "narrate", "title": "Explain the design", "actor": actor,
            "short": rationale.get("headline") or "Design explained",
            "summary": ("Written by Gemini using only the verified numbers." if actor == "gemini"
                        else "Written from the verified numbers (AI offline)."),
            "said": rationale.get("why_this_works"),
            "details": [v for k, v in rationale.items()
                        if k in ("sustainability", "tradeoff") and v]}


def build(parsed, result, options, trace, source, llm_live=True):
    steps = [_understand(parsed)]
    if result.get("selection"):
        steps.append(_select(result["selection"]))
    steps.append(_arrange(trace, source, llm_live))
    steps.append(_verify(result.get("checks", []), result["watersense"]))
    if options:
        steps.append(_options(options))
    steps.append(_narrate(result.get("rationale")))
    return steps
