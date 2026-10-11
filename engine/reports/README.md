# `engine/reports/` — Excel workbooks and charts

Generates **auditable Excel artifacts** after NLQ and full risk runs. Python owns this because `openpyxl` + `matplotlib` integrate tightly with model outputs in the same process.

## Modules

| File | Role |
|------|------|
| [`excel_writer.py`](excel_writer.py) | Multi-sheet NLQ workbook (Summary, Position Detail, Model Parameters, Charts) |
| [`report_charts.py`](report_charts.py) | Matplotlib figures embedded as images |
| [`excel_safety.py`](excel_safety.py) | Path traversal guards, safe filenames |
| [`master_report.py`](master_report.py) | Aggregates all risk models for **Risk → Run Full Risk Report** |
| [`stress_report.py`](stress_report.py) | Attaches stress-specific sheets/paths to `StressResult` |

Output directory: `engine/output/reports/` (timestamp + query slug filenames).

## Why Python for reports?

| Alternative | Issue |
|-------------|--------|
| C# Open XML only | Possible, but charts would need separate ScottPlot/OxyPlot pipeline duplicated from NLQ math |
| PDF-only | Poor trader workflow; users expect Excel |
| Jupyter | Not callable from `/nlq` synchronously |

**Competitive edge:** One NLQ call returns JSON **and** a path desktop opens with a single button — no second export step.

## Desktop links

| Step | File |
|------|------|
| Validate path | [`NlqReportPathValidator.cs`](../../desktop/Riskbot.App/Helpers/NlqReportPathValidator.cs) |
| Open workbook | `ResultViewModel` / shell “Open Excel Report” |
| Full report menu | [`RiskAnalysisService.cs`](../../desktop/Riskbot.App/Services/RiskAnalysisService.cs) → `POST /risk/full-report` |

Security tests: [`tests/test_step9_security.py`](../tests/test_step9_security.py), [`desktop/.../Step11SecurityTests.cs`](../../desktop/Riskbot.App.Tests/Step11SecurityTests.cs).

## API touchpoints

- `nlp/executor.py` → `write_nlq_report()` after model run
- `api/routes/risk.py` → `generate_full_report()`, `stress_result_with_report()`

Parent: [../README.md](../README.md)
