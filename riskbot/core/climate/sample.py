"""Deterministic synthetic climate portfolio for Q3 (synthetic=True; all issuers fictitious).

Design (CONTRACT.md section 7): 21 holdings (20 long, 1 short) across 10 sectors; 6 of 21 (~29%) miss
scope 1-2, 17 miss scope 3, data quality mixed 1-5 / None, one stale emissions year, three controversy
flags and one exclusion flag. Magnitudes: market values in the tens of USD millions, EVIC and revenue in
USD billions, scope 1+2 intensities from ~5 (software) to ~1,600 tCO2e per USD m revenue (coal-heavy
power), so the default orderly/central scenario lands near the moderate/high boundary and the grid shows
flips in exposure_level.

``seed`` applies small multiplicative log-normal jitter (sd 3%) to magnitudes only; the structure (which
fields are missing, flags, sectors) is identical for every seed.
"""

from __future__ import annotations

import datetime as dt

import numpy as np

from riskbot.contract.types import ClimateHolding, ClimatePortfolio

M, B = 1e6, 1e9

# issuer, sector, MV (USD m), EVIC (USD bn), revenue (USD bn), scope1+2 intensity (t/USD m) or None if
# unreported, scope1 share, scope3 multiple of scope1+2 or None, data_quality, emissions_year,
# controversy flags, exclusion flags
_TEMPLATE = [
    ("Northsea Petroleum", "Energy", 22, 80, 60, 520, 0.92, 8.0, 2, 2025, ["oil_spill_2024"], []),
    ("Permian Shale Partners", "energy", 10, 12, 8, None, 0.9, None, None, None, [], []),
    ("Gulf Coast Refining", "energy", 8, 20, 45, 300, 0.85, None, 3, 2025, [], []),
    ("Continental Power", "Utilities", 15, 45, 18, 1600, 0.97, 0.3, 1, 2025, [],
     ["thermal_coal_power_above_30pct"]),
    ("Riverside Utilities", "utilities", 12, 22, 9, 1100, 0.95, None, 2, 2025, [], []),
    ("Sunbelt Electric", "utilities", 9, 15, 6, None, 0.95, None, None, None, [], []),
    ("Granite Cement", "Materials", 9, 18, 12, 1500, 0.9, None, 2, 2025, ["dust_emissions_fine"], []),
    ("Alpine Steel Works", "materials", 8, 14, 20, 900, 0.8, None, 3, 2021, [], []),
    ("Coastal Chemicals", "materials", 8, 25, 15, None, 0.7, None, None, None, [], []),
    ("Meridian Machinery", "Industrials", 30, 40, 25, 60, 0.4, None, 2, 2025, [], []),
    ("Atlas Aerospace", "industrials", 20, 55, 30, None, 0.5, None, 5, 2024, [], []),
    ("TransGlobal Airlines", "Transportation", 8, 20, 25, 750, 0.97, None, 2, 2025, [], []),
    ("Freightline Logistics", "transportation", 10, 12, 14, None, 0.9, None, None, None, [], []),
    ("Quantum Semiconductors", "Technology", 70, 300, 50, 25, 0.3, 5.0, 1, 2025, [], []),
    ("Cloudnine Software", "technology", 65, 250, 30, 6, 0.1, 6.0, 1, 2025, [], []),
    ("Harbour Bank", "Financials", 45, 150, 25, 3, 0.2, None, 2, 2025, [], []),
    ("Shield Insurance", "financials", 30, 60, 40, None, 0.2, None, None, None, [], []),
    ("Vita Pharma", "Health Care", 45, 120, 35, 18, 0.4, None, 2, 2025, ["pricing_investigation"], []),
    ("Everyday Foods", "Consumer", 35, 50, 40, 45, 0.5, None, 3, 2024, [], []),
    ("Urban REIT", "Real Estate", 25, 25, 3, 60, 0.3, None, 4, 2025, [], []),
    # the single short
    ("Legacy Coal Corp", "energy", -12, 5, 4, 2500, 0.95, None, 4, 2024, [], []),
]


def sample_dataset(seed: int = 0) -> ClimatePortfolio:
    """Return the deterministic synthetic Q3 portfolio (as of 2026-10-30)."""
    rng = np.random.default_rng(seed)
    jit = np.exp(0.03 * rng.standard_normal((len(_TEMPLATE), 4)))
    holdings = []
    for k, (name, sector, mv, evic, rev, inten, s1share, s3mult, dq, year, contro, excl) in enumerate(_TEMPLATE):
        j = jit[k]
        revenue = round(rev * B * j[2], -5)
        s1 = s2 = s3 = None
        if inten is not None:
            e12 = inten * j[3] * revenue / M
            s1 = float(round(e12 * s1share))
            s2 = float(round(e12 * (1 - s1share)))
            if s3mult is not None:
                s3 = float(round(e12 * s3mult))
        holdings.append(ClimateHolding(
            issuer=name, sector=sector, market_value=float(round(mv * M * j[0], -3)),
            evic=float(round(evic * B * j[1], -6)), revenue=float(revenue),
            ebitda=float(round(revenue * 0.18, -5)),
            scope1=s1, scope2=s2, scope3=s3, data_quality=dq, emissions_year=year,
            controversy_flags=list(contro), exclusion_flags=list(excl),
        ))
    return ClimatePortfolio(name="Synthetic transition-risk sample portfolio", as_of=dt.date(2026, 10, 30),
                            currency="USD", synthetic=True, holdings=holdings)
