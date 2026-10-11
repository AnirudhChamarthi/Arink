"""Create samples/SamplePortfolio.xlsx for manual Riskbot testing."""

from datetime import date
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "samples" / "SamplePortfolio.xlsx"

HOLDINGS = [
    ["Date", "Ticker", "ISIN", "AssetClass", "Quantity", "CostPrice", "Currency", "Sector", "Country", "ESGOverride"],
    [date.today().isoformat(), "AAPL", "", "Equity", 150, 175, "USD", "Technology", "US", ""],
    [date.today().isoformat(), "MSFT", "", "Equity", 80, 380, "USD", "Technology", "US", ""],
    [date.today().isoformat(), "JPM", "", "Equity", 200, 145, "USD", "Financials", "US", ""],
    [date.today().isoformat(), "XOM", "", "Equity", 120, 95, "USD", "Energy", "US", ""],
    [date.today().isoformat(), "NVDA", "", "Equity", 40, 450, "USD", "Technology", "US", ""],
]

METADATA = [
    ["Key", "Value"],
    ["PortfolioName", "Sample Portfolio"],
    ["BaseCurrency", "USD"],
    ["Benchmark", "SPY"],
    ["VaRLimit", "0.05"],
    ["MaxConcentration", "0.15"],
    ["ExclusionFilters", ""],
    ["EsgMinScore", "40"],
]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws_h = wb.active
    ws_h.title = "Holdings"
    for row in HOLDINGS:
        ws_h.append(row)

    ws_m = wb.create_sheet("Metadata")
    for row in METADATA:
        ws_m.append(row)

    wb.save(OUT)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
