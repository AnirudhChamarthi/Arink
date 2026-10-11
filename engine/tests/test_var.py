import numpy as np

from models.var import parametric_var
from schemas.contract import AssetClass, EnrichedPortfolio, EnrichedPosition, VarMethod


def _make_position(ticker: str, weight_price: float = 100.0) -> EnrichedPosition:
  rng = np.random.default_rng(hash(ticker) % 2**32)
  returns = rng.normal(0.0002, 0.01, 252).tolist()
  return EnrichedPosition(
    ticker=ticker,
    asset_class=AssetClass.EQUITY,
    quantity=10.0,
    cost_price=90.0,
    currency="USD",
    current_price=weight_price,
    returns_252d=returns,
    implied_vol=0.25,
    risk_free_rate=0.04,
    esg_score=60.0,
    carbon_intensity=50.0,
  )


def test_parametric_var_positive():
  portfolio = EnrichedPortfolio(
    portfolio_name="Test",
    base_currency="USD",
    positions=[_make_position("AAPL"), _make_position("MSFT")],
  )
  result = parametric_var(portfolio, confidence=0.99, horizon_days=1)
  assert result.method == VarMethod.PARAMETRIC
  assert result.var > 0
  assert result.cvar >= result.var * 0.5
  assert len(result.contributions) == 2
  assert abs(sum(c.pct_of_total for c in result.contributions) - 1.0) < 1e-6
