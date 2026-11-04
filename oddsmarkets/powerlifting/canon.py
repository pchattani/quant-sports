"""Ids, equipment groups and the published DOTS polynomial (Konertz / BVDK 2019).

DOTS is a bodyweight-adjusted points formula: points = total_kg * 500 / poly4(bw). The coefficients
are published; bodyweights outside the stated bounds are clamped to the bound, matching the formula
as used in competition. We invert it to turn a predicted DOTS into an expected total at a bodyweight.
"""
from __future__ import annotations

import hashlib
import re

# equipment categories in the OpenPowerlifting dump → our ranking streams
EQ_GROUP = {
    "Raw": "raw",
    "Wraps": "wraps",
    "Single-ply": "equipped",
    "Multi-ply": "equipped",
    "Unlimited": "equipped",
}
# Straps is exhibition-only and is dropped from ratings

STREAMS = {
    "men_raw": {"sex": "M", "eq": "raw", "label": "Men · Raw", "short": "Men raw"},
    "women_raw": {"sex": "F", "eq": "raw", "label": "Women · Raw", "short": "Women raw"},
    "men_wraps": {"sex": "M", "eq": "wraps", "label": "Men · Wraps", "short": "Men wraps"},
    "women_wraps": {"sex": "F", "eq": "wraps", "label": "Women · Wraps", "short": "Women wraps"},
    "men_eq": {"sex": "M", "eq": "equipped", "label": "Men · Equipped", "short": "Men equipped"},
    "women_eq": {"sex": "F", "eq": "equipped", "label": "Women · Equipped", "short": "Women equipped"},
}

# Konertz 2019, as published for competition use (men 40-210 kg, women 40-150 kg)
_DOTS = {
    "M": (-0.0000010930, 0.0007391293, -0.1918759221, 24.0900756, -307.75076, 40.0, 210.0),
    "F": (-0.0000010706, 0.0005158568, -0.1126655495, 13.6175032, -57.96288, 40.0, 150.0),
}


def pid(name: str) -> str:
    """Stable filesystem-safe id of a lifter's OpenPowerlifting Name (disambiguated with #N)."""
    return hashlib.blake2s(name.encode("utf-8"), digest_size=8).hexdigest()


def meet_id(fed: str, date: str, name: str, country: str) -> str:
    key = f"{fed}|{date}|{name}|{country}"
    return hashlib.blake2s(key.encode("utf-8"), digest_size=8).hexdigest()


def slug(s: str) -> str:
    t = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return t or "x"


def dots_coeff(sex: str, bw: float) -> float:
    """500 / poly4(bw): multiply by total kg to get DOTS. Mx uses the men's polynomial."""
    a, b, c, d, e, lo, hi = _DOTS["F" if sex == "F" else "M"]
    x = min(hi, max(lo, float(bw)))
    poly = (((a * x + b) * x + c) * x + d) * x + e
    return 500.0 / poly if poly else 0.0


def dots(sex: str, bw: float, total: float) -> float:
    return dots_coeff(sex, bw) * float(total)


def total_from_dots(sex: str, bw: float, points: float) -> float:
    k = dots_coeff(sex, bw)
    return float(points) / k if k else 0.0
