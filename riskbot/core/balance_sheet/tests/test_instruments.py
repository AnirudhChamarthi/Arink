"""Independent oracles for the instrument maths: closed forms, finite differences, simulation."""

from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pytest

from riskbot.core.balance_sheet import instruments as ins


# ------------------------------------------------------------------------------------------------ duration


@pytest.mark.parametrize("T,y", [(1.0, 0.03), (5.0, 0.04), (10.0, 0.05), (7.5, 0.02)])
def test_zero_coupon_modified_duration_is_T_over_1_plus_y(T, y):
    mac, dmod, conv = ins.bond_risk(T, 0.0, y)
    assert mac == pytest.approx(T, rel=1e-12)
    assert dmod == pytest.approx(T / (1 + y), rel=1e-12)
    assert conv == pytest.approx(T * (T + 1) / (1 + y) ** 2, rel=1e-12)


@pytest.mark.parametrize("T,c", [(2, 0.03), (5, 0.04), (10, 0.0175), (30, 0.06)])
def test_par_bond_duration_matches_closed_form(T, c):
    """Closed form for a par bond: D_mac = (1+y)/y (1 - (1+y)^-T)."""
    mac, dmod, _ = ins.bond_risk(float(T), c, c)
    assert ins.bond_price(float(T), c, c) == pytest.approx(1.0, abs=1e-12)
    closed = (1 + c) / c * (1 - (1 + c) ** (-T))
    assert mac == pytest.approx(closed, rel=1e-10)
    assert dmod == pytest.approx(closed / (1 + c), rel=1e-10)


@pytest.mark.parametrize("T,c", [(3.0, 0.03), (8.0, 0.02), (12.5, 0.045)])
def test_derived_duration_and_convexity_match_finite_differences(T, c):
    """Direct cash-flow repricing: D = -P'/P and C = P''/P by central differences."""
    _, dmod, conv = ins.bond_risk(T, c, c)
    h = 1e-5
    p0, pu, pd = (ins.bond_price(T, c, c + d) for d in (0.0, h, -h))
    assert dmod == pytest.approx(-(pu - pd) / (2 * h) / p0, rel=1e-7)
    assert conv == pytest.approx((pu - 2 * p0 + pd) / h**2 / p0, rel=1e-4)


@pytest.mark.parametrize("T,c", [(3.0, 0.03), (10.0, 0.02), (15.0, 0.035), (5.0, 0.0)])
@pytest.mark.parametrize("bp", [-100, 100])
def test_duration_convexity_approximation_vs_full_revaluation(T, c, bp):
    y = c if c > 0 else 0.04
    dy = bp / 1e4
    _, d, cv = ins.bond_risk(T, c, y)
    p0 = ins.bond_price(T, c, y)
    exact = ins.bond_price(T, c, y + dy) / p0 - 1
    approx = ins.value_change(1.0, d, cv, dy)
    assert approx == pytest.approx(exact, abs=6e-4)  # third-order error
    assert abs(approx - exact) < abs(-d * dy - exact)  # convexity term helps


def test_zero_maturity_has_no_rate_risk():
    assert ins.bond_risk(0.0, 0.05, 0.05) == (0.0, 0.0, 0.0)


def test_zero_coupon_convexity_for_given_duration():
    T, y = 7.0, 0.05
    assert ins.zero_coupon_convexity_for_duration(T / (1 + y), y) == pytest.approx(T * (T + 1) / (1 + y) ** 2)


# ------------------------------------------------------------------------------------------------ Vasicek


def test_vasicek_hand_computed_value():
    """PD 2%, rho 0.15, q 0.99. Hand: (Φ⁻¹(.02) + √.15 Φ⁻¹(.99)) / √.85 = (-2.053749 + 0.900990)/0.921954
    = -1.250344, Φ(-1.250344) = 0.105584 (stdlib NormalDist, independent of scipy)."""
    nd = NormalDist()
    hand = nd.cdf((nd.inv_cdf(0.02) + math.sqrt(0.15) * nd.inv_cdf(0.99)) / math.sqrt(0.85))
    assert ins.vasicek_pd(0.02, 0.15, 0.99) == pytest.approx(hand, rel=1e-9)
    assert ins.vasicek_pd(0.02, 0.15, 0.99) == pytest.approx(0.10558, abs=2e-5)


def test_vasicek_median_factor_and_monotonicity():
    # q = 0.5 gives Φ(Φ⁻¹(PD)/√(1-ρ)) < PD for PD < 0.5 (median below mean): a known property
    assert ins.vasicek_pd(0.02, 0.2, 0.5) < 0.02
    assert ins.vasicek_pd(0.02, 0.2, 0.9) < ins.vasicek_pd(0.02, 0.2, 0.99)
    assert ins.vasicek_pd(0.02, 0.1, 0.99) < ins.vasicek_pd(0.02, 0.3, 0.99)


def test_vasicek_quantile_by_obligor_simulation():
    """Simulate a homogeneous pool of obligors: default iff √ρ Z + √(1-ρ) ε < Φ⁻¹(PD). The 90% quantile of the
    pool default rate across scenarios approaches the Vasicek PD_s (granularity and sampling error small)."""
    pd_, rho, q = 0.03, 0.15, 0.90
    rng = np.random.default_rng(7)
    n_scen, n_obl = 4000, 1500
    z = rng.standard_normal(n_scen)
    thr = NormalDist().inv_cdf(pd_)
    rates = np.empty(n_scen)
    for i in range(0, n_scen, 500):
        eps = rng.standard_normal((min(500, n_scen - i), n_obl)).astype(np.float32)
        # Z is the "bad" factor: higher Z -> more defaults, consistent with + √ρ Φ⁻¹(q)
        x = -math.sqrt(rho) * z[i:i + 500, None] + math.sqrt(1 - rho) * eps
        rates[i:i + 500] = (x < thr).mean(axis=1)
    assert np.quantile(rates, q) == pytest.approx(ins.vasicek_pd(pd_, rho, q), rel=0.06)
    assert rates.mean() == pytest.approx(pd_, rel=0.05)


# ------------------------------------------------------------------------------------------------ fire sale


def test_fire_sale_without_impact_sells_exactly_the_need():
    fs = ins.solve_fire_sale(need=300.0, pool=1000.0, impact=0.0)
    assert fs.share * 1000.0 == pytest.approx(300.0, rel=1e-12)
    assert fs.proceeds == pytest.approx(300.0, rel=1e-12)
    assert fs.price == 1.0 and fs.shortfall == 0.0


@pytest.mark.parametrize("impact", [0.05, 0.3, 0.8, 1.0])
@pytest.mark.parametrize("need_frac", [0.05, 0.3, 0.6])
def test_fire_sale_fixed_point_converges_to_root(impact, need_frac):
    pool = 2_000.0
    need = need_frac * pool * math.exp(-impact)  # always feasible
    fs = ins.solve_fire_sale(need, pool, impact)
    assert fs.converged and fs.shortfall == 0.0
    assert fs.proceeds == pytest.approx(need, rel=1e-9)
    assert fs.share * pool * math.exp(-impact * fs.share) == pytest.approx(need, rel=1e-9)
    # smallest root: proceeds below need for all smaller shares
    grid = np.linspace(0, fs.share, 50)[:-1]
    assert np.all(grid * pool * np.exp(-impact * grid) < need + 1e-9)
    if fs.method == "fixed_point":
        s_seq = [s for _, s, _ in fs.iterations]
        assert all(b >= a - 1e-15 for a, b in zip(s_seq, s_seq[1:]))  # monotone iterates from 0


def test_fire_sale_impact_increases_share_sold():
    a = ins.solve_fire_sale(500.0, 1000.0, 0.05)
    b = ins.solve_fire_sale(500.0, 1000.0, 0.5)
    assert b.share > a.share > 0.5


def test_fire_sale_shortfall_when_need_exceeds_max_proceeds():
    fs = ins.solve_fire_sale(990.0, 1000.0, 0.05)
    assert fs.method == "sell_all" and fs.share == 1.0
    assert fs.proceeds == pytest.approx(1000 * math.exp(-0.05))
    assert fs.shortfall == pytest.approx(990 - 1000 * math.exp(-0.05))


def test_fire_sale_near_tangency_uses_bisection_and_still_solves():
    need = 1000.0 * math.exp(-1.0) * (1 - 1e-9)  # lambda = 1, root at s ≈ 1 where g'(s*) ≈ 1
    fs = ins.solve_fire_sale(need, 1000.0, 1.0, max_iter=50)
    assert fs.proceeds == pytest.approx(need, rel=1e-6)
