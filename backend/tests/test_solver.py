"""Run with:  python -m unittest discover -s tests -v

These tests are the evidence behind the project's core claim: the solver never
returns a bundle that breaks the budget, the floor-usage limit, a clearance
zone or the door swing. The checker below is written independently of
layout.verify_layout on purpose.
"""
import os
import random
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intent_parser import parse_prompt  # noqa: E402
from solver import (LEGACY, USAGE_PER_PERSON_PER_DAY,  # noqa: E402
                    load_catalog, price_of, solve_bathroom_bundle, water_use)

THEMES = ["Minimalist Modern", "Japanese Zen", "Classic Luxury"]
FLOOR_LIMIT = 0.40  # hardcoded on purpose: the spec, not imported from the code under test


# ------------------------------------------------------------ test fixtures --
def make_test_catalog():
    """16 SYNTHETIC products (4 per category) so the solver has real choices.
    Not Kohler data - only used to stress-test the maths."""
    rng = random.Random(7)
    specs = {  # category: (width, depth, side_min, front_min, base_price)
        "toilet": (15, 26, 15, 21, 1500), "shower": (36, 36, 0, 30, 900),
        "vanity": (30, 21, 0, 24, 700), "faucet": (6, 6, 4, 6, 150)}
    products = []
    for cat, (w, d, side, front, price) in specs.items():
        for i in range(4):
            products.append({
                "id": f"T-{cat[:3].upper()}-{i}", "name": f"Test {cat} {i}", "category": cat,
                "sku": f"SKU-{cat}-{i}", "price_usd": price * (i + 1),
                "dimensions_in": {"width": w + 2 * i, "depth": d + i, "height": 30},
                "clearance_req_in": {"side_min": side, "front_min": front},
                "gpf": 1.0 + 0.3 * i, "gpm": 1.2 + 0.3 * i,
                "aesthetic_themes": rng.sample(THEMES, k=rng.randint(1, 3)),
                "smart_features": ["x"] * i})
    return products


def rects_overlap(a, b):
    return a[0] < b[0] + b[2] - 1e-6 and b[0] < a[0] + a[2] - 1e-6 and \
        a[1] < b[1] + b[3] - 1e-6 and b[1] < a[1] + a[3] - 1e-6


def assert_result_valid(tc, r, budget, length_ft, width_ft):
    """Independent proof that a status=='ok' result really is valid."""
    tc.assertEqual(r["status"], "ok")
    cost = sum(price_of(p) for p in r["bundle"])
    tc.assertLessEqual(cost, budget + 1e-9, "over budget")

    area = length_ft * width_ft
    foot = sum(p["dimensions_in"]["width"] * p["dimensions_in"]["depth"] / 144
               for p in r["bundle"] if p["category"] != "faucet")
    tc.assertLessEqual(foot, area * FLOOR_LIMIT + 1e-9, "floor usage exceeded")

    W, L = width_ft * 12, length_ft * 12
    door = (0, L - 30, 30, 30)
    by_id = {p["id"]: p for p in r["bundle"]}
    floor = [p for p in r["layout"]["placements"] if p["category"] != "faucet"]
    tc.assertEqual(len(floor), 3)

    def envelope(p):
        """Clearance zone recomputed FROM THE CATALOG SPECS (not from the solver's output)."""
        spec = by_id[p["id"]]["clearance_req_in"]
        x, y, w, d = p["x"], p["y"], p["w"], p["d"]
        front = spec["front_min"]
        if p["side"] in ("top", "bottom"):
            half = max(w / 2, spec["side_min"])
            cx = x + w / 2
            return (cx - half, y if p["side"] == "top" else y - front, 2 * half, d + front)
        half = max(d / 2, spec["side_min"])
        cy = y + d / 2
        return (x if p["side"] == "left" else x - front, cy - half, w + front, 2 * half)

    for p in floor:
        foot_r = (p["x"], p["y"], p["w"], p["d"])
        env = envelope(p)
        for rect in (foot_r, env):
            tc.assertTrue(rect[0] >= -1e-6 and rect[1] >= -1e-6 and
                          rect[0] + rect[2] <= W + 1e-6 and rect[1] + rect[3] <= L + 1e-6,
                          f"{p['category']} footprint/clearance outside room")
        tc.assertFalse(rects_overlap(foot_r, door), f"{p['category']} in door swing")
        for q in floor:
            if q is not p:
                qr = (q["x"], q["y"], q["w"], q["d"])
                tc.assertFalse(rects_overlap(foot_r, qr), "fixtures overlap")
                tc.assertFalse(rects_overlap(env, qr), f"{p['category']} clearance blocked by {q['category']}")
    tc.assertTrue(all(c["passed"] for c in r["checks"]))


# -------------------------------------------------------------------- tests --
class SolverGuarantees(unittest.TestCase):
    def test_random_inputs_never_violate_constraints(self):
        rng = random.Random(42)
        catalog = make_test_catalog()
        ok = infeasible = 0
        for _ in range(200):
            length = rng.choice([5, 6, 7, 8, 9, 10, 12, 14, 16])
            width = rng.choice([4, 5, 6, 7, 8, 9, 10, 12])
            budget = rng.choice([1500, 3000, 5000, 8000, 12000, 20000, 40000])
            theme = rng.choice(THEMES)
            r = solve_bathroom_bundle(length, width, budget, theme, household=rng.randint(1, 5),
                                      prioritize_smart=rng.random() < 0.5, catalog=catalog)
            if r["status"] == "ok":
                ok += 1
                assert_result_valid(self, r, budget, length, width)
            else:
                infeasible += 1
                self.assertEqual(r["bundle"], [])
        self.assertGreater(ok, 30, "test inputs too harsh to be meaningful")
        self.assertGreater(infeasible, 5, "test inputs never exercise the infeasible path")

    def test_regression_expensive_toilet_no_longer_blows_budget(self):
        # Old greedy solver: Numi-class toilet took most of the budget, then later
        # categories fell back to over-budget items. 15k budget returned ~18.7k.
        real = load_catalog()
        r = solve_bathroom_bundle(10, 8, 15000, "Japanese Zen", catalog=real)
        if r["status"] == "ok":
            self.assertLessEqual(sum(price_of(p) for p in r["bundle"]), 15000)

    def test_too_small_budget_is_reported_not_hidden(self):
        r = solve_bathroom_bundle(10, 8, 500, "Japanese Zen", catalog=make_test_catalog())
        self.assertEqual(r["status"], "infeasible")
        self.assertIn("Budget too low", r["message"])
        self.assertIsNotNone(r["alternative"])
        self.assertGreater(r["alternative"]["total_cost"], 500)
        self.assertGreater(r["alternative"]["over_budget_by"], 0)

    def test_tiny_room_is_reported(self):
        r = solve_bathroom_bundle(4, 4, 50000, "Japanese Zen", catalog=make_test_catalog())
        self.assertEqual(r["status"], "infeasible")
        self.assertIn("Room too small", r["message"])

    def test_deterministic(self):
        c = make_test_catalog()
        a = solve_bathroom_bundle(10, 8, 12000, "Classic Luxury", 3, True, catalog=c)
        b = solve_bathroom_bundle(10, 8, 12000, "Classic Luxury", 3, True, catalog=c)
        self.assertEqual([p["id"] for p in a["bundle"]], [p["id"] for p in b["bundle"]])
        self.assertEqual(a["layout"]["placements"], b["layout"]["placements"])

    def test_theme_influences_choice(self):
        c = make_test_catalog()
        picks = {t: tuple(p["id"] for p in solve_bathroom_bundle(12, 10, 30000, t, catalog=c)["bundle"])
                 for t in THEMES}
        self.assertGreater(len(set(picks.values())), 1, "theme has no effect on selection")

    def test_latency_under_two_seconds(self):
        c = make_test_catalog()
        worst = 0.0
        for length, width, budget in [(10, 8, 12000), (8, 6, 9000), (7, 6, 2000), (5, 5, 20000), (12, 12, 40000)]:
            t = time.perf_counter()
            solve_bathroom_bundle(length, width, budget, "Japanese Zen", catalog=c)
            worst = max(worst, time.perf_counter() - t)
        self.assertLess(worst, 2.0)

    def test_input_validation(self):
        for bad in [(0, 8, 1000), (10, -1, 1000), (10, 8, 0)]:
            with self.assertRaises(ValueError):
                solve_bathroom_bundle(*bad, catalog=make_test_catalog())


class Currency(unittest.TestCase):
    def test_inr_catalog_is_detected_and_formatted(self):
        inr = []
        for p in make_test_catalog():
            q = {k: v for k, v in p.items() if k != "price_usd"}
            q["price_inr"] = p["price_usd"] * 80
            inr.append(q)
        r = solve_bathroom_bundle(10, 8, 900000, "Japanese Zen", catalog=inr)
        self.assertEqual(r["currency"], "INR")
        self.assertEqual(r["status"], "ok")
        self.assertLessEqual(r["metrics"]["total_cost"], 900000)
        self.assertIn("₹", r["checks"][0]["detail"])
        low = solve_bathroom_bundle(10, 8, 1000, "Japanese Zen", catalog=inr)
        self.assertRegex(low["message"], r"₹[\d,]+")


class WaterModel(unittest.TestCase):
    def test_matches_hand_calculation_and_scales_with_household(self):
        bundle = [{"category": "toilet", "gpf": 1.0}, {"category": "shower", "gpm": 1.5},
                  {"category": "faucet", "gpm": 1.0}, {"category": "vanity", "gpm": 0.0}]
        u = USAGE_PER_PERSON_PER_DAY
        expected = 2 * 365 * (u["flushes"] * 1.0 + u["shower_min"] * 1.5 + u["faucet_min"] * 1.0)
        w = water_use(bundle, 2)
        self.assertEqual(w["annual_gal"], round(expected))
        legacy = 2 * 365 * (u["flushes"] * LEGACY["gpf"] + u["shower_min"] * LEGACY["shower_gpm"]
                            + u["faucet_min"] * LEGACY["faucet_gpm"])
        self.assertEqual(w["saved_gal"], round(legacy - expected))
        self.assertAlmostEqual(water_use(bundle, 4)["annual_gal"], 2 * w["annual_gal"], delta=1)


class RealCatalog(unittest.TestCase):
    def test_schema(self):
        products = load_catalog()
        self.assertGreaterEqual(len(products), 4)
        ids = [p["id"] for p in products]
        self.assertEqual(len(ids), len(set(ids)), "duplicate product ids")
        for p in products:
            for key in ("id", "name", "category", "sku", "dimensions_in", "clearance_req_in"):
                self.assertIn(key, p, f"{p.get('id')} missing {key}")
            self.assertGreater(price_of(p), 0)

    def test_real_catalog_results_are_valid_or_explained(self):
        for length, width, budget, theme in [(10, 8, 10000, "Japanese Zen"), (10, 8, 25000, "Classic Luxury"),
                                             (8, 6, 20000, "Minimalist Modern"), (6, 5, 20000, "Japanese Zen")]:
            r = solve_bathroom_bundle(length, width, budget, theme)
            if r["status"] == "ok":
                assert_result_valid(self, r, budget, length, width)
            else:
                self.assertTrue(r["message"])


class PromptParser(unittest.TestCase):
    def test_typical_prompt(self):
        p = parse_prompt("I have an 8x10 ft bathroom space with a $10,000 budget, "
                         "looking for a sleek Japanese Zen aesthetic with smart features.")
        self.assertEqual((p["length_ft"], p["width_ft"], p["budget"], p["theme"]), (10, 8, 10000, "Japanese Zen"))
        self.assertTrue(p["prioritize_smart"])
        self.assertEqual(p["assumed"], ["household size"])

    def test_indian_formats(self):
        self.assertEqual(parse_prompt("7 by 10 feet, budget ₹6 lakh, japandi")["budget"], 600000)
        self.assertEqual(parse_prompt("bathroom 6x9, ₹6L")["budget"], 600000)
        self.assertEqual(parse_prompt("Rs 450000 for a 9x12 bath")["budget"], 450000)
        self.assertEqual(parse_prompt("5k budget, 6x8")["budget"], 5000)
        self.assertEqual(parse_prompt("7 by 10 feet, budget ₹6 lakh, japandi")["theme"], "Japanese Zen")

    def test_household(self):
        self.assertEqual(parse_prompt("family of 4, 8x10, $9000")["household"], 4)
        self.assertEqual(parse_prompt("for 3 people 8x10 $9000")["household"], 3)

    def test_defaults_are_reported_not_silent(self):
        p = parse_prompt("something nice please")
        self.assertEqual(set(p["assumed"]), {"room size", "budget", "theme", "household size"})
        self.assertFalse(p["prioritize_smart"])

    def test_empty_and_garbage_never_crash(self):
        for text in ("", None, "@@@ ### 999999999999", "x" * 5000):
            parse_prompt(text)

    def test_length_is_always_the_longer_side(self):
        p = parse_prompt("10x8 bath")
        self.assertEqual((p["length_ft"], p["width_ft"]), (10, 8))


if __name__ == "__main__":
    unittest.main(verbosity=2)
