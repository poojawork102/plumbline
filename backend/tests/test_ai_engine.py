"""Proves the AI loop without needing a live API key.

We stub the model so the FIRST proposal is deliberately bad (toilet and vanity
stacked on the same wall) and the second is good. The test asserts that the
verifier caught it, that the critique was fed back, and that the accepted
layout is geometrically valid.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai_engine
from layout import place_fixtures, verify_layout
from solver import _fx, load_catalog, solve_bathroom_bundle

FIXTURES = [
    {"category": "shower", "width": 36, "depth": 36, "side_min": 0, "front_min": 24},
    {"category": "toilet", "width": 20, "depth": 28, "side_min": 15, "front_min": 21},
    {"category": "vanity", "width": 30, "depth": 22, "side_min": 0, "front_min": 21},
]
W, L = 96.0, 120.0   # 8 x 10 ft


def test_repair_loop_recovers_from_a_bad_proposal(monkeypatch):
    # A known-good arrangement, borrowed from the deterministic solver so this
    # test cannot rot if the clearance maths is ever tuned.
    good = {p["category"]: {"wall": p["side"], "offset": p["u"]}
            for p in place_fixtures(W, L, FIXTURES)}

    replies = [
        # attempt 1: everything stacked on one wall -> must be rejected
        {"shower": {"wall": "left", "offset": 0},
         "toilet": {"wall": "left", "offset": 0},
         "vanity": {"wall": "left", "offset": 0},
         "reasoning": "bad on purpose"},
        dict(good, reasoning="separated onto different walls"),
    ]
    seen = []

    def fake(prompt, system=None, temperature=0.4, as_json=True):
        seen.append(prompt)
        return replies[min(len(seen) - 1, len(replies) - 1)]

    monkeypatch.setattr(ai_engine, "_generate", fake)
    placements, trace = ai_engine.arrange_with_repair(
        FIXTURES, W, L, "Japanese Zen", "calm spa bathroom")

    assert len(trace) == 2, "should have needed exactly one repair"
    assert trace[0]["accepted"] is False and trace[0]["problems"]
    assert trace[1]["accepted"] is True
    assert "REJECTED" in seen[1], "the critique was not fed back to the model"
    assert placements and verify_layout(placements, W, L) == []
    print("repair loop OK ->", trace[0]["problems"])


def test_falls_back_to_solver_when_the_model_never_succeeds(monkeypatch):
    monkeypatch.setattr(ai_engine, "_generate", lambda *a, **k: {
        "shower": {"wall": "left", "offset": 0},
        "toilet": {"wall": "left", "offset": 0},
        "vanity": {"wall": "left", "offset": 0}})
    placements, trace, source = ai_engine.layout_with_fallback(
        FIXTURES, W, L, "Minimalist Modern", "")
    assert source == "deterministic"
    assert placements and verify_layout(placements, W, L) == []
    print("fallback OK -> attempts:", len(trace))


def test_geometry_is_never_out_of_bounds_whatever_the_model_says():
    """Offsets are clipped by code, so a wild number cannot escape the room."""
    for offset in (-500, 0, 99999):
        p = ai_engine.build_placement(FIXTURES[1], "top", offset, W, L)
        assert 0 <= p["x"] and p["x"] + p["w"] <= W + 1e-6, p
        assert 0 <= p["y"] and p["y"] + p["d"] <= L + 1e-6, p
    print("bounds OK -> LLM cannot place a fixture outside the room")


def test_end_to_end_solver_still_valid():
    r = solve_bathroom_bundle(10, 8, 600000, "Japanese Zen", 4, True)
    assert r["status"] == "ok"
    assert all(c["passed"] for c in r["checks"]), r["checks"]
    print("solver OK ->", r["metrics"]["total_cost"], "INR,",
          r["metrics"]["water"]["saved_gal"], "gal/yr saved")
