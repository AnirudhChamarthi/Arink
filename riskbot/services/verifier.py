"""Number verifier (``ports.NumberVerifier``): every number shown to a reader must come from a trace.

check_outputs
    For every successful variation, every metric must link to an existing trace step whose value equals it
    (``math.isclose``, rel. tol 1e-9, abs. tol 1e-12). One ``matched=False`` finding per problem; a clean
    run returns ``[]``.

verify_text
    1. *Mask identifiers*: tokens that start with a letter or ``_`` and contain a digit, including chains
       joined by ``. - : /`` (``q1.var``, ``v1a2b3c``, ``run-0001``, ``q2.reverse_stress-0a1b2c3d4e5f``,
       ``CET1``, ``loss_p05``) are blanked so their digits are not read as numbers.
    2. *Extract numbers*: optional sign (only when not glued to a preceding word/number, so ``1%-2%`` is a
       range), optional currency (``$``, ``US$``, ``USD``), digits with optional thousands separators and
       decimals, optional unit suffix: ``%``/``percent``/``pp``, ``bp``/``bps``/``basis points``,
       ``k``/``thousand``, ``m``/``mn``/``million``, ``b``/``bn``/``billion``, ``tn``/``trillion``, ``x``.
       A number glued to other letters (``5th``, ``0a1b``) or part of a dotted version is not a number.
    3. *Ignore* unsigned plain integers 1-5 without unit, currency or decimals (ratings) and plain integers
       1900-2100 without separators (years).
    4. *Candidates*: every metric of every successful variation, in the representations its unit allows:
       fractions/probabilities as raw, x100 for ``%`` and x10,000 for ``bp``; basis points as raw and /100
       for ``%``; ratios as raw (and x100 for ``%``); currency and other absolute units as raw and /1e3,
       /1e6, /1e9, /1e12 for the scale suffixes. A currency symbol restricts candidates to currency metrics.
    5. *Match* if ``|printed - candidate| <= 0.5 x 10^-decimals`` (half a unit of the last printed digit,
       plus a 1e-9 relative epsilon). An explicitly signed number must match the sign; an unsigned one is
       compared by magnitude (prose like "a fall of 1.2bn" describes a negative ``delta_eve``).
    One ``VerifierFinding`` per extracted number: ``value`` is the number as printed (e.g. 31.2 for
    "31.2%"), ``matched`` says whether a candidate was found, ``message`` names the metric or explains.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from riskbot.contract.types import Unit, VariationResult, VerifierFinding

_IDENT = re.compile(r"(?<![\w])[A-Za-z_]\w*(?:[.\-:/]\w+)*")

_NUM = re.compile(
    r"""
    (?P<sign>(?<![\w.%)\]])[-+−])?
    (?P<cur>US\$|\$|USD\s?)?
    (?P<num>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)
    (?P<suf>
        \s?(?:%|percent\b|pp\b|bps?\b|basis\ points?\b|thousand\b|million\b|mn\b|billion\b|bn\b|trillion\b)
      | (?:k|m|b|tn|x)\b
    )?
    (?![\w])(?!\.\d)(?!,\d{3})
    """,
    re.VERBOSE | re.IGNORECASE,
)

_SCALES = {"thousand": 1e3, "k": 1e3, "million": 1e6, "mn": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9, "b": 1e9,
           "trillion": 1e12, "tn": 1e12}
_FRACTIONS = {Unit.FRACTION, Unit.FRACTION_OF_GROSS, Unit.PROBABILITY}
_ABSOLUTE = {Unit.CURRENCY, Unit.COUNT, Unit.TCO2E, Unit.TCO2E_PER_MUSD, Unit.DAYS, Unit.YEARS}


@dataclass(frozen=True)
class _Token:
    text: str
    value: float  # as printed, signed if a sign was printed
    signed: bool
    decimals: int
    kind: str  # "plain" | "pct" | "bp" | "scale"
    scale: float
    currency: bool


@dataclass(frozen=True)
class _Candidate:
    value: float
    kind: str
    scale: float
    unit: Unit
    label: str  # "q1.var.var = 0.0312 (fraction_of_gross) in variation v..."


def _mask_identifiers(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        tok = m.group(0)
        return " " * len(tok) if any(c.isdigit() for c in tok) else tok

    return _IDENT.sub(repl, text)


def extract_numbers(text: str) -> list[_Token]:
    """Numbers in ``text`` after masking identifiers and dropping ratings and years (see module docstring)."""
    masked = _mask_identifiers(text)
    tokens: list[_Token] = []
    for m in _NUM.finditer(masked):
        start = m.start()
        if start > 0 and (masked[start - 1].isalnum() or masked[start - 1] in "._"):
            continue
        raw_num = m.group("num")
        sign = m.group("sign")
        cur = bool(m.group("cur"))
        suf = (m.group("suf") or "").strip().lower()
        decimals = len(raw_num.split(".", 1)[1]) if "." in raw_num else 0
        value = float(raw_num.replace(",", ""))
        if sign in ("-", "−"):
            value = -value
        is_plain_int = not sign and not cur and not suf and decimals == 0
        if is_plain_int and 1 <= value <= 5:
            continue  # rating
        if is_plain_int and "," not in raw_num and 1900 <= value <= 2100:
            continue  # year
        if suf in ("%", "percent", "pp"):
            kind, scale = "pct", 1.0
        elif suf.startswith("bp") or suf.startswith("basis"):
            kind, scale = "bp", 1.0
        elif suf in _SCALES:
            kind, scale = "scale", _SCALES[suf]
        else:
            kind, scale = "plain", 1.0
        tokens.append(_Token(text=text[start:m.end()].strip(), value=value, signed=bool(sign), decimals=decimals,
                             kind=kind, scale=scale, currency=cur))
    return tokens


def _candidates(results: list[VariationResult]) -> list[_Candidate]:
    out: list[_Candidate] = []
    for r in results:
        if r.output is None or r.error:
            continue
        for key, m in r.output.metrics.items():
            v, u = m.value, m.unit
            label = f"{r.spec.model_id}.{key} = {v:.6g} ({u.value}) in variation {r.spec.variation_id}"
            if m.trace_id:
                label += f", trace {m.trace_id}"
            out.append(_Candidate(v, "plain", 1.0, u, label))
            if u in _FRACTIONS:
                out.append(_Candidate(v * 100, "pct", 1.0, u, label))
                out.append(_Candidate(v * 1e4, "bp", 1.0, u, label))
            elif u == Unit.BASIS_POINTS:
                out.append(_Candidate(v, "bp", 1.0, u, label))
                out.append(_Candidate(v / 100, "pct", 1.0, u, label))
            elif u == Unit.RATIO:
                out.append(_Candidate(v * 100, "pct", 1.0, u, label))
            elif u in _ABSOLUTE:
                for s in sorted(set(_SCALES.values())):
                    out.append(_Candidate(v / s, "scale", s, u, label))
    return out


def _match(tok: _Token, cands: list[_Candidate]) -> tuple[_Candidate | None, float]:
    tol = 0.5 * 10 ** (-tok.decimals) + 1e-9 * max(1.0, abs(tok.value))
    best, best_diff = None, math.inf
    for c in cands:
        if c.kind != tok.kind or (tok.kind == "scale" and c.scale != tok.scale):
            continue
        if tok.currency and c.unit != Unit.CURRENCY:
            continue
        diff = abs(tok.value - c.value) if tok.signed else abs(abs(tok.value) - abs(c.value))
        if diff <= tol and diff < best_diff:
            best, best_diff = c, diff
    return best, tol


class TraceNumberVerifier:
    """``NumberVerifier`` implementation; see the module docstring."""

    def check_outputs(self, results: list[VariationResult]) -> list[VerifierFinding]:
        findings: list[VerifierFinding] = []
        for r in results:
            if r.output is None or r.error:
                continue
            steps = {(t.trace_id, s.id): s for t in r.output.traces for s in t.steps}
            for key, m in r.output.metrics.items():
                loc = f"variation:{r.spec.variation_id}/metric:{key}"
                text = f"{key}={m.value!r}"
                if m.trace_id is None or m.trace_step is None:
                    msg = f"metric {key!r} of {r.spec.model_id} is not linked to a trace step"
                elif (m.trace_id, m.trace_step) not in steps:
                    msg = f"metric {key!r} links to missing trace step {m.trace_id}/{m.trace_step}"
                else:
                    sv = steps[(m.trace_id, m.trace_step)].value
                    if sv is not None and math.isclose(sv, m.value, rel_tol=1e-9, abs_tol=1e-12):
                        continue
                    msg = f"metric {key!r}={m.value!r} differs from trace step {m.trace_id}/{m.trace_step} value {sv!r}"
                findings.append(VerifierFinding(location=loc, text=text, value=m.value, matched=False, message=msg))
        return findings

    def verify_text(self, location: str, text: str, results: list[VariationResult]) -> list[VerifierFinding]:
        cands = _candidates(results)
        n_ok = sum(1 for r in results if r.output is not None and not r.error)
        findings: list[VerifierFinding] = []
        for tok in extract_numbers(text):
            best, tol = _match(tok, cands)
            if best is not None:
                msg = f"{tok.text!r} matches {best.label}"
            else:
                how = {"pct": "as a percentage", "bp": "in basis points", "scale": f"scaled by {tok.scale:g}",
                       "plain": "as a plain number"}[tok.kind]
                cur = " (currency metrics only)" if tok.currency else ""
                msg = (f"{tok.text!r} does not match any metric value of the {n_ok} successful variation(s) "
                       f"{how}{cur} within +/-{tol:.2g}; quote numbers from the results only")
            findings.append(VerifierFinding(location=location, text=tok.text, value=tok.value,
                                            matched=best is not None, message=msg))
        return findings
