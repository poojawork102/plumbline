"""Multiple layout options + visible reasoning.

Every option offered to the user must pass the same independent verifier as
the primary layout, and options must actually differ from each other.
"""
import ai_engine
from layout import enumerate_layouts, layout_features, place_fixtures, verify_layout, wall_signature

FIXTURES = [
    {"category": "shower", "width": 36, "depth": 36, "side_min": 0, "front_min": 24},
    {"category": "toilet", "width": 20, "depth": 28, "side_min": 15, "front_min": 21},
    {"category": "vanity", "width": 30, "depth": 22, "side_min": 0, "front_min": 21},
]
W, L = 96.0, 120.0


def test_enumerated_layouts_are_valid_and_distinct():
    for w, l in [(96, 120), (60, 96), (72, 96), (144, 180)]:
        opts = enumerate_layouts(w, l, FIXTURES, limit=3)
        assert len(opts) == 3, (w, l)
        sigs = [wall_signature(o) for o in opts]
        assert len(set(sigs)) == 3
        for o in opts:
            assert verify_layout(o, w, l) == []


def test_enumeration_respects_excluded_signatures():
    first = place_fixtures(W, L, FIXTURES)
    opts = enumerate_layouts(W, L, FIXTURES, limit=2, exclude=[wall_signature(first)])
    assert wall_signature(first) not in {wall_signature(o) for o in opts}


def test_enumeration_returns_nothing_for_impossible_room():
    assert enumerate_layouts(54, 72, FIXTURES, limit=3) == []


def test_place_fixtures_can_pin_walls():
    p = place_fixtures(W, L, FIXTURES, walls={"shower": "right", "toilet": "left"})
    assert p and {x["category"]: x["side"] for x in p}["shower"] == "right"
    assert verify_layout(p, W, L) == []


def test_layout_features():
    p = place_fixtures(W, L, FIXTURES, walls={"shower": "top", "toilet": "top", "vanity": "left"})
    f = layout_features(p, W, L)
    assert f["toilet_screened"] is False         # toilet faces the door
    assert f["wet_zone_grouped"] is True
    assert 0 < f["open_floor_pct"] < 100


def test_offline_options_are_all_deterministic_and_valid():
    opts, trace, source = ai_engine.layout_options(FIXTURES, W, L, "Japanese Zen", "", count=3)
    assert source == "deterministic"
    assert [o["id"] for o in opts] == ["Option A", "Option B", "Option C"]
    assert len({wall_signature(o["placements"]) for o in opts}) == 3
    assert len({o["name"] for o in opts}) == 3, "option names must be distinguishable"
    for o in opts:
        assert o["problems"] == [] and o["summary"] and o["name"]


def test_llm_alternatives_are_verified_and_bad_ones_dropped(monkeypatch):
    """Gemini proposes two alternatives: one overlapping (must be dropped),
    one valid (must be kept). The remaining slot is filled deterministically."""
    good_primary = {p["category"]: {"wall": p["side"], "offset": p["u"]}
                    for p in place_fixtures(W, L, FIXTURES)}
    alt_good = {p["category"]: {"wall": p["side"], "offset": p["u"]}
                for p in place_fixtures(W, L, FIXTURES,
                                        walls={"shower": "right", "toilet": "left", "vanity": "left"})}
    alt_bad = {"shower": {"wall": "left", "offset": 0}, "toilet": {"wall": "left", "offset": 0},
               "vanity": {"wall": "left", "offset": 0}}

    def fake(prompt, system=None, temperature=0.4, as_json=True, **kw):
        if "ALREADY TAKEN" in prompt:
            return {"options": [dict(alt_bad, name="Bad", reasoning="overlaps"),
                                dict(alt_good, name="Split zones", reasoning="good one")]}
        return dict(good_primary, reasoning="primary")

    monkeypatch.setattr(ai_engine, "_generate", fake)
    monkeypatch.setattr(ai_engine, "get_client", lambda: object())
    opts, trace, source = ai_engine.layout_options(FIXTURES, W, L, "Minimalist Modern", "x")
    assert source == "gemini"
    assert [o["source"] for o in opts] == ["gemini", "gemini", "deterministic"]
    assert opts[1]["name"] == "Split zones" and opts[1]["reasoning"] == "good one"
    alt_trace = [t for t in trace if t.get("stage") == "alternatives"]
    assert [t["accepted"] for t in alt_trace] == [False, True]
    assert alt_trace[0]["problems"]
    for o in opts:
        assert verify_layout(o["placements"], W, L) == []


def test_repair_critique_is_recorded_for_the_ui(monkeypatch):
    good = {p["category"]: {"wall": p["side"], "offset": p["u"]}
            for p in place_fixtures(W, L, FIXTURES)}
    replies = iter([{"shower": {"wall": "left", "offset": 0},
                     "toilet": {"wall": "left", "offset": 0},
                     "vanity": {"wall": "left", "offset": 0}}, good])
    monkeypatch.setattr(ai_engine, "_generate", lambda *a, **k: next(replies))
    _, trace = ai_engine.arrange_with_repair(FIXTURES, W, L, "Japanese Zen", "")
    assert "REJECTED" in trace[0]["critique"]
    assert "critique" not in trace[1]


def test_reasoning_counts_only_verifier_rejections():
    import reasoning
    trace = [
        {"attempt": 1, "source": "gemini", "accepted": False, "problems": ["timed out"], "arrangement": None},
        {"attempt": 2, "source": "gemini", "accepted": False, "problems": ["toilet overlaps shower"],
         "arrangement": {"toilet": {"wall": "left", "offset": 0}}, "critique": "REJECTED"},
        {"attempt": 3, "source": "gemini", "accepted": True, "problems": [], "arrangement": {}},
    ]
    step = reasoning._arrange(trace, "gemini", llm_live=True)
    assert step["summary"] == ("Gemini's proposal passed verification. "
                               "1 rejected proposal(s) were caught by the verifier.")
    assert step["attempts"][1]["critique"] == "REJECTED"
