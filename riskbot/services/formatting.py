"""Unit-aware number formatting shared by the reporter.

Formats are chosen so that ``verifier.verify_text`` recognises them and matches the underlying value
within half a unit of the last printed digit:

| Unit                              | Format            | Example          |
|-----------------------------------|-------------------|------------------|
| fraction, fraction_of_gross       | percent, 2 dp     | ``3.12%``        |
| probability                       | plain, 3 dp       | ``0.042``        |
| bp                                | thousands, 0 dp   | ``125 bp``       |
| currency                          | thousands, 0 dp (2 dp below 1,000) | ``1,234,568`` |
| count                             | thousands, 0 dp   | ``12``           |
| ratio                             | 2 dp              | ``1.35``         |
| tCO2e / tCO2e per USDm            | thousands, 1 dp   | ``12,345.6 tCO2e`` |
| days / years                      | 0 dp / 2 dp       | ``780 days``     |
"""

from __future__ import annotations

from riskbot.contract.types import Unit


def format_value(value: float, unit: Unit) -> str:
    """Human format of ``value`` in ``unit`` (see the module table)."""
    if unit in (Unit.FRACTION, Unit.FRACTION_OF_GROSS):
        return f"{value * 100:.2f}%"
    if unit == Unit.PROBABILITY:
        return f"{value:.3f}"
    if unit == Unit.BASIS_POINTS:
        return f"{value:,.0f} bp"
    if unit == Unit.CURRENCY:
        return f"{value:,.0f}" if abs(value) >= 1000 else f"{value:,.2f}"
    if unit == Unit.COUNT:
        return f"{value:,.0f}"
    if unit == Unit.RATIO:
        return f"{value:,.2f}"
    if unit == Unit.TCO2E:
        return f"{value:,.1f} tCO2e"
    if unit == Unit.TCO2E_PER_MUSD:
        return f"{value:,.1f} tCO2e/USDm"
    if unit == Unit.DAYS:
        return f"{value:,.0f} days"
    if unit == Unit.YEARS:
        return f"{value:,.2f} years"
    return f"{value:,.6g}"


def format_difference(value: float, unit: Unit) -> str:
    """Format a difference of two values in ``unit`` (fractions become percentage points)."""
    if unit in (Unit.FRACTION, Unit.FRACTION_OF_GROSS):
        return f"{value * 100:.2f} pp"
    return format_value(value, unit)


def md_cell(text: object) -> str:
    """Escape a value for a Markdown table cell."""
    return str(text).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")
