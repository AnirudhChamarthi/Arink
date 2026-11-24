"""``q1.var``: portfolio Value at Risk and expected shortfall under six methods.

See README.md in this package for the model documentation (formulas, assumptions, limitations).

Pipeline
--------
1. Weights :math:`w_i = MV_i/G`, :math:`G=\\sum_i|MV_i|`; listwise deletion of dates with a missing return.
2. Estimation window: the most recent ``window_days`` clean rows :math:`R` (all rows, with a warning, if fewer).
3. Portfolio return series :math:`r_p = Rw`.
4. 1-day VaR/ES by ``method``; multi-day by :math:`\\sqrt h` (montecarlo simulates the h-day distribution).
5. Optional moving-block bootstrap interval for VaR; optional rolling 250-day backtest at 1-day horizon.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import stats

from riskbot.contract import catalog, rules
from riskbot.contract.conformance import resolve_params
from riskbot.contract.errors import ValidationFailed
from riskbot.contract.hashing import model_input_hash
from riskbot.contract.tracing import TraceBuilder
from riskbot.contract.types import DataQualityFinding, Metric, ModelOutput, Severity, TableCell, Unit

from . import estimators as E
from ._data import Portfolio, as_market_dataset, build_portfolio

MIN_OBS = 30  # minimum clean observations for any estimate
BACKTEST_WINDOW = 250
FHS_REFIT_EVERY = 20
BOOTSTRAP_MC_CAP = 5000

FG = Unit.FRACTION_OF_GROSS

_ASSUMPTIONS = {
    "common": [
        "Weights are signed market value / gross exposure, held constant over the horizon.",
        "Cash has price 1 per unit and zero return.",
        "Returns are simple daily returns; the portfolio return is the weighted sum of asset returns.",
        "Dates with a missing return for any held ticker are removed (listwise deletion).",
    ],
    "normal": ["Portfolio returns are i.i.d. Gaussian with zero mean.",
               "Multi-day figures use square-root-of-time scaling (i.i.d. returns)."],
    "student_t": ["Portfolio returns are i.i.d. Student-t (scaled to unit variance) with zero mean.",
                  "Multi-day figures use square-root-of-time scaling (i.i.d. returns)."],
    "historical": ["The estimation window is representative of tomorrow's return distribution.",
                   "Multi-day figures use square-root-of-time scaling (i.i.d. returns)."],
    "fhs": ["Portfolio return volatility follows a zero-mean Gaussian GARCH(1,1) fitted by quasi-MLE.",
            "Standardised residuals are i.i.d.; their empirical distribution is used for the tail.",
            "Multi-day figures scale the 1-day figure by sqrt(h) (ignores volatility mean reversion)."],
    "evt": ["Losses above the threshold u follow a generalized Pareto distribution (Pickands-Balkema-de Haan).",
            "Exceedances are treated as i.i.d. (no declustering).",
            "Multi-day figures use square-root-of-time scaling."],
    "montecarlo": ["Asset returns are i.i.d. multivariate normal N(mu, Sigma) with the sample mean mu.",
                   "The h-day return is simulated as N(h mu, h Sigma); no square-root scaling."],
}


def _f(x: float, d: int = 6) -> str:
    return f"{x:.{d}g}"


# --------------------------------------------------------------------------------------------
# Point estimates (full detail, used once per run)
# --------------------------------------------------------------------------------------------


@dataclass
class Estimate:
    var: float  # horizon-h VaR (fraction of gross)
    es: float
    var_1d: float | None  # None for montecarlo (simulated directly at h)
    es_1d: float | None
    warnings: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)  # small state reused by bootstrap


def _cov_table(tickers: list[str], S: np.ndarray, w: np.ndarray) -> list[dict[str, TableCell]]:
    rows: list[dict[str, TableCell]] = []
    for i, t in enumerate(tickers):
        row: dict[str, TableCell] = {"ticker": t, "weight": float(w[i]), "daily_vol": float(math.sqrt(S[i, i]))}
        for j, t2 in enumerate(tickers):
            row[f"cov_{t2}"] = float(S[i, j])
        rows.append(row)
    return rows


def _covariance_steps(tb: TraceBuilder, R: np.ndarray, w: np.ndarray, tickers: list[str], kind: str) -> tuple[np.ndarray, float]:
    S, delta = E.covariance(R, kind)
    if kind == "ledoit_wolf":
        Ssample = E.sample_cov(R)
        sd = np.sqrt(np.diag(Ssample))
        k = len(tickers)
        rbar = float(((Ssample / np.outer(sd, sd)).sum() - k) / (k * (k - 1))) if k > 1 else 0.0
        tb.step("average_correlation", "Average pairwise sample correlation (target correlation)",
                r"\bar r = \frac{2}{N(N-1)}\sum_{i<j} r_{ij}", f"rbar = {_f(rbar)} over N = {k} assets",
                value=rbar, unit=Unit.RATIO)
        tb.step("shrinkage_intensity", "Ledoit-Wolf optimal shrinkage intensity (constant correlation)",
                r"\delta^*=\max\left(0,\min\left(1,\frac{\hat\pi-\hat\rho}{T\hat\gamma}\right)\right)",
                f"delta* = {_f(float(delta))} with T = {R.shape[0]}", value=float(delta), unit=Unit.FRACTION,
                note="Ledoit & Wolf (2004). Sigma = delta* F + (1 - delta*) S, F has constant correlation rbar.")
        formula = r"\hat\Sigma=\delta^*F+(1-\delta^*)S"
        subst = f"delta* = {_f(float(delta))}; table gives the shrunk covariance"
    else:
        formula = r"S=\frac{1}{n-1}\sum_t (R_t-\bar R)(R_t-\bar R)^\top"
        subst = f"n = {R.shape[0]} observations, {len(tickers)} assets; table gives S"
    tb.step("covariance", f"Asset covariance matrix ({kind})", formula, subst, table=_cov_table(tickers, S, w))
    var_p = float(w @ S @ w)
    sigma = math.sqrt(max(var_p, 0.0))
    tb.step("portfolio_sigma", "Portfolio daily volatility", r"\sigma_p=\sqrt{w^\top\Sigma w}",
            f"sigma_p = sqrt({_f(var_p)}) = {_f(sigma)}", value=sigma, unit=FG)
    return S, sigma


def point_estimate(method: str, R: np.ndarray, w: np.ndarray, tickers: list[str], eff: dict[str, Any],
                   tb: TraceBuilder, rng: np.random.Generator) -> Estimate:
    """Compute the run's VaR/ES and record method-specific trace steps."""
    c = eff["confidence"]
    h = eff["horizon_days"]
    r = R @ w
    warn: list[str] = []
    ctx: dict[str, Any] = {"r": r}
    if method in ("normal", "student_t"):
        _, sigma = _covariance_steps(tb, R, w, tickers, eff["covariance"])
        if method == "normal":
            z = float(stats.norm.ppf(c))
            tb.step("quantile", "Standard normal quantile", r"z_c=\Phi^{-1}(c)", f"z_{{{c}}} = {_f(z)}",
                    value=z, unit=Unit.RATIO)
            v1, e1 = E.normal_var_es(sigma, c)
            tb.step("var_1d", "1-day VaR (normal)", r"VaR_1=z_c\sigma_p", f"{_f(z)} x {_f(sigma)} = {_f(v1)}",
                    value=v1, unit=FG)
            tb.step("es_1d", "1-day ES (normal)", r"ES_1=\sigma_p\frac{\varphi(z_c)}{1-c}",
                    f"{_f(sigma)} x {_f(float(stats.norm.pdf(z)))} / {_f(1 - c)} = {_f(e1)}", value=e1, unit=FG)
        else:
            nu = eff["t_dof"]
            tc = float(stats.t.ppf(c, nu))
            scale = math.sqrt((nu - 2) / nu)
            tb.step("quantile", "Student-t quantile", r"t_c=t_\nu^{-1}(c)", f"t_{{{nu}}}^{{-1}}({c}) = {_f(tc)}",
                    value=tc, unit=Unit.RATIO)
            tb.step("variance_scale", "Unit-variance scaling of the t distribution", r"\sqrt{(\nu-2)/\nu}",
                    f"sqrt(({nu} - 2) / {nu}) = {_f(scale)}", value=scale, unit=Unit.RATIO)
            v1, e1 = E.student_t_var_es(sigma, c, nu)
            tb.step("var_1d", "1-day VaR (Student-t)", r"VaR_1=\sigma_p\,t_c\sqrt{(\nu-2)/\nu}",
                    f"{_f(sigma)} x {_f(tc)} x {_f(scale)} = {_f(v1)}", value=v1, unit=FG)
            ftc = float(stats.t.pdf(tc, nu))
            tb.step("es_1d", "1-day ES (Student-t)",
                    r"ES_1=\sigma_p\sqrt{\tfrac{\nu-2}{\nu}}\,\frac{f_\nu(t_c)}{1-c}\,\frac{\nu+t_c^2}{\nu-1}",
                    f"{_f(sigma)} x {_f(scale)} x {_f(ftc)} / {_f(1 - c)} x ({nu} + {_f(tc)}^2) / ({nu} - 1) = {_f(e1)}",
                    value=e1, unit=FG)
    elif method == "historical":
        L = -r
        v1, e1 = E.empirical_var_es(L, c)
        tb.step("var_1d", "1-day VaR (empirical loss quantile)", r"VaR_1=Q_c(L),\ L=-r_p",
                f"np.quantile(L, {c}) with linear interpolation over n = {L.size} losses = {_f(v1)}",
                value=v1, unit=FG)
        tail = np.sort(L[L >= v1])[::-1]
        tb.step("es_1d", "1-day ES (mean of losses >= VaR)", r"ES_1=\frac{1}{|\{L_t\ge VaR\}|}\sum_{L_t\ge VaR}L_t",
                f"mean of {tail.size} tail losses = {_f(e1)}", value=e1, unit=FG,
                table=[{"rank": i + 1, "loss": float(x)} for i, x in enumerate(tail)])
    elif method == "fhs":
        res = E.fhs_var_es(r, c)
        fit = res.fit
        assert fit is not None
        if res.filter == "garch":
            pers = fit.alpha + fit.beta
            lr_vol = math.sqrt(fit.omega / (1 - pers)) / 100.0 if pers < 1 - 1e-6 else None
            if lr_vol is None:
                warn.append(f"GARCH fit is on the stationarity boundary (alpha+beta = {pers:.6f}): integrated "
                            "volatility, no long-run variance; the one-step forecast is still used.")
            tb.step("garch_fit", "GARCH(1,1) fit to portfolio returns in percent (arch, zero mean, normal QMLE)",
                    r"\sigma_t^2=\omega+\alpha x_{t-1}^2+\beta\sigma_{t-1}^2,\ x_t=100\,r_{p,t}",
                    f"omega = {_f(fit.omega)}, alpha = {_f(fit.alpha)}, beta = {_f(fit.beta)}, alpha+beta = {_f(pers)}",
                    value=pers, unit=Unit.RATIO,
                    table=[{"parameter": "omega", "value": fit.omega}, {"parameter": "alpha", "value": fit.alpha},
                           {"parameter": "beta", "value": fit.beta}, {"parameter": "persistence", "value": pers},
                           {"parameter": "long_run_daily_vol", "value": lr_vol},
                           {"parameter": "loglik", "value": fit.loglik}],
                    note="Initial variance: arch backcast (0.94-weighted mean of the first 75 squared returns).")
            ctx["garch_params"] = (fit.omega, fit.alpha, fit.beta)
        else:
            msg = f"GARCH(1,1) fit failed or did not converge ({fit.message}); EWMA(lambda=0.94) filter used instead."
            warn.append(msg)
            tb.step("garch_fit", "Volatility filter: EWMA fallback", r"\sigma_t^2=\lambda\sigma_{t-1}^2+(1-\lambda)x_{t-1}^2",
                    "lambda = 0.94, sigma_0^2 = mean(x^2)", value=0.94, unit=Unit.RATIO, note=msg)
        tb.step("sigma_forecast", "One-day-ahead volatility forecast", r"\sigma_{T+1}^2=\omega+\alpha x_T^2+\beta\sigma_T^2",
                f"sigma_T+1 = {_f(res.sigma_next)} (decimal)", value=res.sigma_next, unit=FG)
        tb.step("standardized_residuals", "Standardised residuals", r"z_t=x_t/\sigma_t",
                f"n = {res.z.size}, std(z) = {_f(float(res.z.std(ddof=1)))}, min(z) = {_f(float(res.z.min()))}",
                value=float(res.z.std(ddof=1)), unit=Unit.RATIO)
        tb.step("var_1d", "1-day VaR (FHS)", r"VaR_1=Q_c\left(-\sigma_{T+1}z_t\right)",
                f"np.quantile(-{_f(res.sigma_next)} z, {c}) = {_f(res.var)}", value=res.var, unit=FG)
        tb.step("es_1d", "1-day ES (FHS)", r"ES_1=\mathrm{mean}\{-\sigma_{T+1}z_t:\ -\sigma_{T+1}z_t\ge VaR_1\}",
                f"tail mean = {_f(res.es)}", value=res.es, unit=FG)
        v1, e1 = res.var, res.es
    elif method == "evt":
        q = eff["evt_threshold_quantile"]
        try:
            ev = E.evt_var_es(r, c, q)
        except ValueError as exc:
            raise ValidationFailed(f"q1.var evt: {exc}; use a longer window or a lower threshold quantile",
                                   method="evt") from exc
        if ev.es is None:
            raise ValidationFailed(f"q1.var evt: fitted xi = {ev.xi:.3f} >= 1, expected shortfall is infinite",
                                   method="evt", xi=ev.xi)
        tb.step("threshold", "POT threshold", r"u=Q_q(L)", f"np.quantile(L, {q}) = {_f(ev.u)}", value=ev.u, unit=FG)
        tb.step("exceedances", "Number of exceedances", r"N_u=\#\{L_t>u\}", f"N_u = {ev.n_u} of n = {ev.n}",
                value=ev.n_u, unit=Unit.COUNT)
        tb.step("gpd_shape", "GPD shape (scipy genpareto MLE, loc = 0)", r"\hat\xi",
                f"xi = {_f(ev.xi)}", value=ev.xi, unit=Unit.RATIO)
        tb.step("gpd_scale", "GPD scale (scipy genpareto MLE, loc = 0)", r"\hat\beta",
                f"beta = {_f(ev.beta)}", value=ev.beta, unit=FG)
        if 1 - c >= ev.n_u / ev.n:
            warn.append(f"EVT: tail probability 1-c = {1 - c:.4f} is not below the exceedance rate "
                        f"{ev.n_u / ev.n:.4f}; the GPD formula is used outside its intended range.")
        tb.step("var_1d", "1-day VaR (EVT)",
                r"VaR_1=u+\frac{\beta}{\xi}\left[\left(\frac{n}{N_u}(1-c)\right)^{-\xi}-1\right]",
                f"{_f(ev.u)} + {_f(ev.beta)}/{_f(ev.xi)} x [({ev.n}/{ev.n_u} x {_f(1 - c)})^(-{_f(ev.xi)}) - 1] = {_f(ev.var)}",
                value=ev.var, unit=FG,
                note="Exponential limit u - beta log(n(1-c)/N_u) is used when |xi| < 1e-6.")
        tb.step("es_1d", "1-day ES (EVT)", r"ES_1=\frac{VaR_1+\beta-\xi u}{1-\xi}",
                f"({_f(ev.var)} + {_f(ev.beta)} - {_f(ev.xi)} x {_f(ev.u)}) / (1 - {_f(ev.xi)}) = {_f(ev.es)}",
                value=ev.es, unit=FG)
        v1, e1 = ev.var, ev.es
    elif method == "montecarlo":
        S, sigma = _covariance_steps(tb, R, w, tickers, eff["covariance"])
        mu = R.mean(axis=0)
        tb.step("mean_vector", "Sample mean returns", r"\mu=\frac1n\sum_t R_t",
                f"portfolio mean w'mu = {_f(float(w @ mu))}", value=float(w @ mu), unit=FG,
                table=[{"ticker": t, "mean": float(m)} for t, m in zip(tickers, mu)])
        n_sims = eff["n_sims"]
        Z = rng.standard_normal((n_sims, len(tickers)))
        losses = E.montecarlo_losses(mu, S, w, h, Z)
        var, es = E.empirical_var_es(losses, c)
        ctx["Z"] = Z[:BOOTSTRAP_MC_CAP]
        tb.step("simulation", "Monte Carlo simulation of h-day losses",
                r"X^{(s)}\sim N(h\mu,h\Sigma),\ L^{(s)}=-w^\top X^{(s)}",
                f"{n_sims} paths, h = {h}, numpy default_rng(seed) standard normals x Cholesky(Sigma)",
                value=n_sims, unit=Unit.COUNT,
                note=f"Analytic normal check: -h w'mu + z_c sqrt(h) sigma_p = "
                     f"{_f(-h * float(w @ mu) + float(stats.norm.ppf(c)) * math.sqrt(h) * sigma)}")
        return Estimate(var, es, None, None, warn, ctx)
    else:  # pragma: no cover - resolve_params validates choices
        raise ValidationFailed(f"unknown method {method!r}")
    s = math.sqrt(h)
    return Estimate(v1 * s, e1 * s, v1, e1, warn, ctx)


# --------------------------------------------------------------------------------------------
# Fast re-estimation (bootstrap) and rolling forecasts (backtest)
# --------------------------------------------------------------------------------------------


def quick_var(method: str, R: np.ndarray, w: np.ndarray, eff: dict[str, Any], ctx: dict[str, Any]) -> tuple[float, str]:
    """Horizon-h VaR only, for bootstrap resamples. Returns ``(var, flag)``; flag notes fallbacks."""
    c, h = eff["confidence"], eff["horizon_days"]
    r = R @ w
    s = math.sqrt(h)
    if method in ("normal", "student_t", "montecarlo"):
        S, _ = E.covariance(R, eff["covariance"])
        if method == "montecarlo":
            losses = E.montecarlo_losses(R.mean(axis=0), S, w, h, ctx["Z"])
            return float(np.quantile(losses, c)), ""
        sigma = math.sqrt(max(float(w @ S @ w), 0.0))
        if method == "normal":
            return E.normal_var_es(sigma, c)[0] * s, ""
        return E.student_t_var_es(sigma, c, eff["t_dof"])[0] * s, ""
    if method == "historical":
        return float(np.quantile(-r, c)) * s, ""
    if method == "fhs":
        gp = ctx.get("garch_params")
        res = E.fhs_var_es(r, c, params=gp, condition_on=ctx["r"], force_ewma=gp is None)
        return res.var * s, ""
    if method == "evt":
        ev = E.evt_var_es(r, c, eff["evt_threshold_quantile"], fast=True)
        return ev.var * s, ""
    raise ValueError(method)  # pragma: no cover


@dataclass
class BacktestForecasts:
    var: np.ndarray  # 1-day VaR forecasts for days W..N-1
    losses: np.ndarray  # realised losses on those days
    notes: list[str]


def rolling_forecasts(method: str, R: np.ndarray, w: np.ndarray, eff: dict[str, Any],
                      window: int = BACKTEST_WINDOW) -> BacktestForecasts:
    """1-day VaR forecast for each day t >= window using rows t-window..t-1 only (no look-ahead).

    * normal/student_t (sample covariance): sigma_t = rolling std of r_p (identical to sqrt(w'Sw)).
    * ledoit_wolf: the shrunk covariance is re-estimated every day.
    * montecarlo: analytic N(mu_t, Sigma_t) quantile -w'mu_t + z_c sigma_t (the simulation converges to it).
    * fhs: GARCH re-fitted every 20 days (arch), daily re-filtering with fixed parameters in between.
    * evt: GPD re-fitted every day with the fast profile-likelihood MLE.
    """
    c = eff["confidence"]
    r = R @ w
    N = r.size
    T = N - window
    L = -r
    notes: list[str] = []
    out = np.empty(T)
    if method in ("normal", "student_t", "montecarlo"):
        if eff["covariance"] == "sample":
            win = np.lib.stride_tricks.sliding_window_view(r, window)[:T]
            sig = win.std(axis=1, ddof=1)
        else:
            sig = np.empty(T)
            for i in range(T):
                S, _ = E.ledoit_wolf_cc(R[i:i + window])
                sig[i] = math.sqrt(max(float(w @ S @ w), 0.0))
        if method == "normal":
            out = stats.norm.ppf(c) * sig
        elif method == "student_t":
            nu = eff["t_dof"]
            out = stats.t.ppf(c, nu) * math.sqrt((nu - 2) / nu) * sig
        else:
            mu_p = np.lib.stride_tricks.sliding_window_view(r, window)[:T].mean(axis=1)
            out = -mu_p + stats.norm.ppf(c) * sig
    elif method == "historical":
        win = np.lib.stride_tricks.sliding_window_view(L, window)[:T]
        out = np.quantile(win, c, axis=1)
    elif method == "fhs":
        params = None
        fallbacks = 0
        start = None
        for i in range(T):
            seg = r[i:i + window]
            if i % FHS_REFIT_EVERY == 0:
                fit = E.fit_garch(100.0 * seg, start)
                if fit.converged:
                    params = (fit.omega, fit.alpha, fit.beta)
                    start = params
                else:
                    params = None
                    fallbacks += 1
            res = E.fhs_var_es(seg, c, params=params) if params else _ewma_fhs(seg, c)
            out[i] = res.var
        if fallbacks:
            notes.append(f"FHS backtest: {fallbacks} of {-(-T // FHS_REFIT_EVERY)} GARCH re-fits failed; EWMA used for those blocks.")
    elif method == "evt":
        q = eff["evt_threshold_quantile"]
        for i in range(T):
            out[i] = E.evt_var_es(r[i:i + window], c, q, fast=True).var  # ValueError if too few exceedances
    else:  # pragma: no cover
        raise ValueError(method)
    return BacktestForecasts(np.asarray(out, dtype=float), L[window:], notes)


def _ewma_fhs(seg: np.ndarray, c: float) -> E.FhsResult:
    x = 100.0 * seg
    s2, s2n = E.ewma_filter(x)
    z = x / np.sqrt(s2)
    sn = math.sqrt(s2n)
    var, es = E.empirical_var_es(-sn * z / 100.0, c)
    return E.FhsResult(var, es, sn / 100.0, "ewma", None, z)


# --------------------------------------------------------------------------------------------
# The model
# --------------------------------------------------------------------------------------------


class VarModel:
    """Implements ``catalog.Q1_VAR`` (structurally a ``contract.ports.Model``)."""

    spec = catalog.Q1_VAR

    def run(self, dataset: Any, params: dict[str, Any], seed: int) -> ModelOutput:
        mid = self.spec.model_id
        eff = resolve_params(self.spec, params)
        ds = as_market_dataset(dataset, mid)
        pf = build_portfolio(ds, mid)
        if not pf.risky:
            raise ValidationFailed(f"{mid}: no non-cash positions, nothing to measure", model_id=mid)
        n_clean = pf.R.shape[0]
        if n_clean < MIN_OBS:
            raise ValidationFailed(f"{mid}: only {n_clean} complete observations (need >= {MIN_OBS})",
                                   model_id=mid, observations=n_clean)
        method, c, h = eff["method"], eff["confidence"], eff["horizon_days"]
        window = eff["window_days"]
        rng = np.random.default_rng(seed)
        findings: list[DataQualityFinding] = []
        warnings: list[str] = []

        input_hash = model_input_hash(mid, ds, eff, seed)
        tb = TraceBuilder(
            mid, f"VaR and ES ({method}, {c:.3g}, {h}d, {window}d window)", input_hash,
            assumptions=_ASSUMPTIONS["common"] + _ASSUMPTIONS[method],
            inputs={"params": eff, "seed": seed, "n_positions": len(ds.positions), "history_days": len(ds.dates),
                    "dataset": ds.name, "synthetic": ds.synthetic},
        )

        # 1. weights ------------------------------------------------------------------------
        pos_by = {}
        for p in ds.positions:
            pos_by.setdefault(p.ticker, p)
        tb.step("weights", "Signed portfolio weights", r"w_i=\frac{MV_i}{\sum_j|MV_j|}",
                f"{len(pf.tickers)} lines, long {_f(float(pf.weights[pf.weights > 0].sum()))}, "
                f"short {_f(float(pf.weights[pf.weights < 0].sum()))}, cash {_f(pf.cash_weight)}",
                value=float(np.abs(pf.weights).sum()), unit=Unit.FRACTION,
                table=[{"ticker": t, "asset_class": pos_by[t].asset_class, "sector": pos_by[t].sector,
                        "market_value": float(mv), "weight": float(wt)}
                       for t, mv, wt in zip(pf.tickers, pf.market_values, pf.weights)],
                note="Value = sum of |w_i| (= 1). Cash market value = quantity.")
        tb.step("gross_exposure", "Gross exposure", r"G=\sum_i|MV_i|", f"G = {pf.gross:,.2f}",
                value=pf.gross, unit=Unit.CURRENCY)

        # 2. data cleaning and window ---------------------------------------------------------
        if pf.dropped_dates:
            nd = len(pf.dropped_dates)
            per = ", ".join(f"{t}: {k}" for t, k in pf.missing_by_ticker.items())
            msg = f"{nd} date(s) dropped because of missing returns among held tickers ({per})."
            findings.append(DataQualityFinding(check="missing_returns", severity=Severity.WARNING, field="returns",
                                               subject=",".join(pf.missing_by_ticker), count=nd, message=msg))
            tb.step("missing_values", "Listwise deletion of dates with missing returns",
                    r"n_{clean}=n-\#\{t:\exists i,\ R_{ti}=\mathrm{NA}\}", f"{len(ds.dates)} - {nd} = {n_clean}",
                    value=nd, unit=Unit.COUNT, note=msg,
                    table=[{"date": d.isoformat()} for d in pf.dropped_dates])
        if n_clean < window:
            msg = f"Only {n_clean} complete observations for a {window}-day window; all of them are used."
            warnings.append(msg)
            findings.append(DataQualityFinding(check="short_window", severity=Severity.WARNING, field="returns",
                                               count=n_clean, message=msg))
        Rw = pf.R[-window:]
        n = Rw.shape[0]
        tb.step("window", "Estimation window", r"R=\{R_t\}_{t=T-n+1}^{T}",
                f"n = {n} observations from {pf.dates[-n].isoformat()} to {pf.dates[-1].isoformat()}",
                value=n, unit=Unit.COUNT)
        r = Rw @ pf.w_risky
        tb.step("portfolio_returns", "Historical portfolio returns", r"r_{p,t}=\sum_i w_iR_{ti}",
                f"mean = {_f(float(r.mean()))}, std = {_f(float(r.std(ddof=1)))}, min = {_f(float(r.min()))}, "
                f"max = {_f(float(r.max()))}", value=float(r.std(ddof=1)), unit=FG,
                note="Value = sample standard deviation of r_p.")

        # 3. point estimate --------------------------------------------------------------------
        est = point_estimate(method, Rw, pf.w_risky, pf.risky, eff, tb, rng)
        warnings += est.warnings
        if est.var_1d is not None:
            tb.step("horizon_scaling", "Square-root-of-time scaling", r"\sqrt{h}", f"sqrt({h}) = {_f(math.sqrt(h))}",
                    value=math.sqrt(h), unit=Unit.RATIO)
            tb.step("var", f"{h}-day VaR", r"VaR_h=VaR_1\sqrt{h}", f"{_f(est.var_1d)} x {_f(math.sqrt(h))} = {_f(est.var)}",
                    value=est.var, unit=FG)
            tb.step("es", f"{h}-day ES", r"ES_h=ES_1\sqrt{h}", f"{_f(est.es_1d)} x {_f(math.sqrt(h))} = {_f(est.es)}",
                    value=est.es, unit=FG)
        else:
            tb.step("horizon_scaling", "No scaling: the h-day distribution is simulated", r"1", "montecarlo",
                    value=1.0, unit=Unit.RATIO)
            tb.step("var", f"{h}-day VaR (simulated loss quantile)", r"VaR_h=Q_c(L^{(s)})",
                    f"np.quantile(L, {c}) = {_f(est.var)}", value=est.var, unit=FG)
            tb.step("es", f"{h}-day ES (mean of simulated losses >= VaR)", r"ES_h=\mathrm{mean}\{L^{(s)}\ge VaR_h\}",
                    f"tail mean = {_f(est.es)}", value=est.es, unit=FG)
        var_amt, es_amt = est.var * pf.gross, est.es * pf.gross
        tb.step("var_amount", "VaR in currency", r"VaR\cdot G", f"{_f(est.var)} x {pf.gross:,.2f} = {var_amt:,.2f}",
                value=var_amt, unit=Unit.CURRENCY)
        tb.step("es_amount", "ES in currency", r"ES\cdot G", f"{_f(est.es)} x {pf.gross:,.2f} = {es_amt:,.2f}",
                value=es_amt, unit=Unit.CURRENCY)

        metrics: dict[str, Metric] = {
            "var": tb.metric("var", est.var, FG),
            "es": tb.metric("es", est.es, FG),
            "var_amount": tb.metric("var_amount", var_amt, Unit.CURRENCY),
            "es_amount": tb.metric("es_amount", es_amt, Unit.CURRENCY),
            "gross_exposure": tb.metric("gross_exposure", pf.gross, Unit.CURRENCY),
        }

        # 4. bootstrap ---------------------------------------------------------------------------
        B = eff["bootstrap"]
        if B > 0:
            self._bootstrap(tb, metrics, warnings, method, Rw, pf.w_risky, eff, est.context, rng, B)

        # 5. backtest ----------------------------------------------------------------------------
        labels = {"basel_zone": "n/a", "backtest_verdict": "n/a"}
        if eff["backtest"]:
            if n_clean < BACKTEST_WINDOW + 1:
                warnings.append(f"Backtest skipped: {n_clean} complete observations, need at least "
                                f"{BACKTEST_WINDOW + 1}.")
            else:
                self._backtest(tb, metrics, labels, warnings, method, pf, eff)

        for wmsg in warnings:
            tb.warn(wmsg)
        trace = tb.build(result={k: m.value for k, m in metrics.items()})
        return ModelOutput(model_id=mid, params=eff, metrics=metrics, labels=labels, traces=[trace],
                           findings=findings, warnings=warnings)

    # ------------------------------------------------------------------------------------------

    @staticmethod
    def _bootstrap(tb: TraceBuilder, metrics: dict[str, Metric], warnings: list[str], method: str, R: np.ndarray,
                   w: np.ndarray, eff: dict[str, Any], ctx: dict[str, Any], rng: np.random.Generator, B: int) -> None:
        n = R.shape[0]
        ell = E.block_length(n)
        vals: list[float] = []
        flags = {"ewma": 0, "failed": 0}
        for _ in range(B):
            idx = E.moving_block_indices(n, rng, ell)
            try:
                v, flag = quick_var(method, R[idx], w, eff, ctx)
            except ValueError:
                flags["failed"] += 1
                continue
            if flag:
                flags[flag] += 1
            if math.isfinite(v):
                vals.append(v)
            else:
                flags["failed"] += 1
        if len(vals) < max(10, B // 2):
            warnings.append(f"Bootstrap interval omitted: only {len(vals)} of {B} resamples succeeded.")
            return
        arr = np.asarray(vals)
        lo, hi = (float(x) for x in np.percentile(arr, [2.5, 97.5]))
        note = {
            "montecarlo": f"Each resample re-simulates with {ctx['Z'].shape[0] if 'Z' in ctx else 0} paths, "
                          "re-using the same normal draws (common random numbers).",
            "fhs": "Fast GARCH path: parameters fixed at the full-window estimate (no re-fit); each resample is "
                   "re-filtered to get its standardised residuals, and sigma_T+1 comes from the actual window. "
                   "The interval reflects sampling error in the residual tail, not GARCH parameter uncertainty.",
            "evt": "Each resample re-fits the GPD with the fast profile-likelihood MLE.",
        }.get(method, "Each resample re-estimates with the same method.")
        if flags["ewma"]:
            note += f" {flags['ewma']} resample(s) fell back to EWMA."
        if flags["failed"]:
            note += f" {flags['failed']} resample(s) failed and were dropped."
            warnings.append(f"Bootstrap: {flags['failed']} of {B} resamples failed and were dropped.")
        tb.step("bootstrap", "Moving-block bootstrap of the estimation window",
                r"\ell=\mathrm{round}(n^{1/3}),\ VaR^{*(b)}=\mathrm{VaR}(R^{*(b)}),\ b=1..B",
                f"B = {B}, n = {n}, block length = {ell}, successful = {arr.size}, "
                f"mean = {_f(float(arr.mean()))}, sd = {_f(float(arr.std(ddof=1)))}",
                value=arr.size, unit=Unit.COUNT, note=note)
        tb.step("var_ci_low", "Bootstrap 2.5% VaR", r"Q_{0.025}(VaR^{*})", f"np.percentile(VaR*, 2.5) = {_f(lo)}",
                value=lo, unit=FG)
        tb.step("var_ci_high", "Bootstrap 97.5% VaR", r"Q_{0.975}(VaR^{*})", f"np.percentile(VaR*, 97.5) = {_f(hi)}",
                value=hi, unit=FG)
        metrics["var_ci_low"] = tb.metric("var_ci_low", lo, FG)
        metrics["var_ci_high"] = tb.metric("var_ci_high", hi, FG)

    @staticmethod
    def _backtest(tb: TraceBuilder, metrics: dict[str, Metric], labels: dict[str, str], warnings: list[str],
                  method: str, pf: Portfolio, eff: dict[str, Any]) -> None:
        c = eff["confidence"]
        p = 1.0 - c
        try:
            fc = rolling_forecasts(method, pf.R, pf.w_risky, eff)
        except ValueError as exc:
            warnings.append(f"Backtest skipped: {exc} in a {BACKTEST_WINDOW}-day window.")
            return
        warnings += fc.notes
        hits = (fc.losses > fc.var).astype(int)
        nd, x = int(hits.size), int(hits.sum())
        rate = x / nd
        lr_pof, p_pof = E.kupiec_pof(nd, x, p)
        lr_ind, p_ind, counts = E.christoffersen_independence(hits)
        last = hits[-BACKTEST_WINDOW:]
        zone, cdf = E.basel_zone(int(last.sum()), int(last.size), p)
        verdict = rules.backtest_verdict(p_pof, p_ind)
        bt_dates = pf.dates[BACKTEST_WINDOW:]
        how = {"montecarlo": "analytic N(mu_t, Sigma_t) quantile (the simulation converges to it)",
               "fhs": f"GARCH re-fitted every {FHS_REFIT_EVERY} days, re-filtered daily with fixed parameters",
               "evt": "GPD re-fitted daily (fast profile-likelihood MLE)"}.get(method, "same estimator re-run daily")
        tb.step("backtest_days", "Rolling out-of-sample backtest days", r"T_{bt}=N-250",
                f"{pf.R.shape[0]} - {BACKTEST_WINDOW} = {nd} days ({bt_dates[0].isoformat()} to "
                f"{bt_dates[-1].isoformat()}); 1-day horizon, confidence {c}",
                value=nd, unit=Unit.COUNT,
                note=f"Forecast for day t uses rows t-250..t-1 only. {method}: {how}.")
        tb.step("backtest_exceptions", "Exceptions (loss > VaR forecast)", r"x=\sum_t \mathbb 1[L_t>VaR_t]",
                f"x = {x}", value=x, unit=Unit.COUNT,
                table=[{"date": bt_dates[i].isoformat(), "loss": float(fc.losses[i]), "var": float(fc.var[i])}
                       for i in np.flatnonzero(hits)])
        tb.step("backtest_exception_rate", "Exception rate", r"\hat p=x/T_{bt}", f"{x} / {nd} = {_f(rate)} (target {_f(p)})",
                value=rate, unit=Unit.FRACTION)
        tb.step("kupiec_lr", "Kupiec POF likelihood ratio",
                r"LR_{POF}=-2\ln\frac{(1-p)^{T-x}p^x}{(1-\hat p)^{T-x}\hat p^x}",
                f"T = {nd}, x = {x}, p = {_f(p)}: LR = {_f(lr_pof)}", value=lr_pof, unit=Unit.RATIO)
        tb.step("kupiec_p", "Kupiec POF p-value", r"p=1-F_{\chi^2_1}(LR_{POF})", f"p = {_f(p_pof)}",
                value=p_pof, unit=Unit.PROBABILITY)
        tb.step("independence_lr", "Christoffersen independence likelihood ratio",
                r"LR_{ind}=-2\ln\frac{(1-\pi)^{n_{00}+n_{10}}\pi^{n_{01}+n_{11}}}{(1-\pi_0)^{n_{00}}\pi_0^{n_{01}}(1-\pi_1)^{n_{10}}\pi_1^{n_{11}}}",
                ", ".join(f"{k} = {v}" for k, v in counts.items()) + f": LR = {_f(lr_ind)}",
                value=lr_ind, unit=Unit.RATIO)
        tb.step("independence_p", "Christoffersen independence p-value", r"p=1-F_{\chi^2_1}(LR_{ind})",
                f"p = {_f(p_ind)}", value=p_ind, unit=Unit.PROBABILITY)
        tb.step("basel_zone", "Basel traffic light on the last 250 forecasts",
                r"F(x_{250};250,p)<0.95\ \mathrm{green},\ <0.9999\ \mathrm{yellow},\ \mathrm{else\ red}",
                f"x_250 = {int(last.sum())} of {last.size}, binomial CDF = {_f(cdf)} -> {zone}",
                value=cdf, unit=Unit.PROBABILITY)
        tb.step("backtest_verdict", "Backtest verdict", r"\mathrm{pass}\iff p_{POF}\ge0.05\ \wedge\ p_{ind}\ge0.05",
                f"kupiec_p = {_f(p_pof)}, independence_p = {_f(p_ind)} -> {verdict}")
        metrics["backtest_days"] = tb.metric("backtest_days", nd, Unit.COUNT)
        metrics["backtest_exceptions"] = tb.metric("backtest_exceptions", x, Unit.COUNT)
        metrics["backtest_exception_rate"] = tb.metric("backtest_exception_rate", rate, Unit.FRACTION)
        metrics["kupiec_p"] = tb.metric("kupiec_p", p_pof, Unit.PROBABILITY)
        metrics["independence_p"] = tb.metric("independence_p", p_ind, Unit.PROBABILITY)
        labels["basel_zone"] = zone
        labels["backtest_verdict"] = verdict
