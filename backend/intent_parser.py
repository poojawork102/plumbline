"""Turns a plain-English request into structured design parameters.

Today this is the deterministic regex fallback, which is what runs when no LLM
API key is configured (so the demo always works offline). The LLM parser plugs
in later by returning the same dict shape from `parse_prompt`.

Returned dict
    length_ft, width_ft, budget, theme, household, prioritize_smart,
    source ("regex"), assumed (list of fields that fell back to defaults)
"""
import re

DEFAULTS = {"length_ft": 10.0, "width_ft": 8.0, "budget": 600000.0,
            "theme": "Minimalist Modern", "household": 2}

# Longest phrases first so "minimalist modern" wins over "modern".
THEME_ALIASES = [
    ("minimalist modern", "Minimalist Modern"), ("japanese zen", "Japanese Zen"),
    ("classic luxury", "Classic Luxury"), ("minimalist", "Minimalist Modern"),
    ("japandi", "Japanese Zen"), ("zen", "Japanese Zen"),
    ("classic", "Classic Luxury"), ("luxury", "Classic Luxury"), ("modern", "Minimalist Modern"),
]
SMART_WORDS = ("smart", "intelligent", "voice", "touchless", "digital", "connected")

MULTIPLIERS = {"k": 1e3, "l": 1e5, "lakh": 1e5, "lac": 1e5, "lakhs": 1e5, "cr": 1e7, "crore": 1e7}
_NUM = r"(\d[\d,]*(?:\.\d+)?)"
_MULT = r"(?:\s?(lakhs|lakh|lac|crore|cr|k|l)\b)?"

_DIMS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:ft|feet|')?\s*(?:x|×|by|\*)\s*(\d+(?:\.\d+)?)", re.I)
_BUDGET_PATTERNS = [
    re.compile(r"(?:₹|\brs\.?|\binr\b|\$|\busd\b)\s*" + _NUM + _MULT, re.I),
    re.compile(r"\bbudget\b\s*(?:of|is|:|around|about)?\s*(?:₹|rs\.?|inr|\$|usd)?\s*" + _NUM + _MULT, re.I),
    re.compile(_NUM + _MULT + r"\s*(?:rs|inr|usd|rupees|dollars)?\s*budget\b", re.I),
    # Bare magnitude with no currency word: "6 lakh", "6L", "50k", "1.2 cr".
    # The multiplier is REQUIRED here so plain counts ("4 people", "8x10") and
    # dimensions can never be misread as a budget.
    re.compile(_NUM + r"\s?(lakhs|lakh|lac|crore|cr|k|l)\b", re.I),
]
_HOUSEHOLD = [
    re.compile(r"\b(?:family|household|home)\s+of\s+(\d+)\b", re.I),
    re.compile(r"\b(\d+)\s*(?:people|persons|person|members|adults|users)\b", re.I),
]


def _number(text, mult):
    value = float(text.replace(",", ""))
    return value * MULTIPLIERS.get((mult or "").lower(), 1)


def parse_prompt(text):
    text = text or ""
    assumed = []

    m = _DIMS.search(text)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        length, width = max(a, b), min(a, b)
    else:
        length, width = DEFAULTS["length_ft"], DEFAULTS["width_ft"]
        assumed.append("room size")

    budget = None
    for pat in _BUDGET_PATTERNS:
        bm = pat.search(text)
        if bm:
            budget = _number(bm.group(1), bm.group(2))
            break
    if budget is None or budget <= 0:
        budget = DEFAULTS["budget"]
        assumed.append("budget")

    lowered = text.lower()
    theme = next((canon for key, canon in THEME_ALIASES if key in lowered), None)
    if theme is None:
        theme = DEFAULTS["theme"]
        assumed.append("theme")

    household = None
    for pat in _HOUSEHOLD:
        hm = pat.search(text)
        if hm:
            household = int(hm.group(1))
            break
    if household is None or not 1 <= household <= 12:
        household = DEFAULTS["household"]
        assumed.append("household size")

    return {"length_ft": length, "width_ft": width, "budget": budget, "theme": theme,
            "household": household, "prioritize_smart": any(w in lowered for w in SMART_WORDS),
            "source": "regex", "assumed": assumed}
