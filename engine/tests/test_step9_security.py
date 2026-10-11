"""Step 9 security — report paths, Excel injection, chart bounds."""

import os

import pytest
from openpyxl import load_workbook

from reports.excel_safety import excel_safe_cell
from reports.excel_writer import validate_report_path, write_nlq_report


def test_excel_safe_cell_prefixes_formula_triggers():
    assert excel_safe_cell("=1+1").startswith("'")
    assert excel_safe_cell("+cmd").startswith("'")
    assert excel_safe_cell("-10").startswith("'")
    assert excel_safe_cell("@sum(A1)").startswith("'")
    assert excel_safe_cell("normal text") == "normal text"


def test_nlq_report_sanitizes_query_in_workbook(tmp_path, monkeypatch):
    monkeypatch.setattr("reports.excel_writer._REPORTS_DIR", tmp_path)
    malicious = '=cmd|"/C calc"!A0'
    path = write_nlq_report(
        slug="inj",
        topline_number="1%",
        topline_label="Test",
        formula_breakdown=[malicious],
        explanation=malicious,
        models_used=["var:parametric"],
        detail_rows=[],
        query=malicious,
    )
    wb = load_workbook(path)
    assert wb["Summary"]["B4"].value.startswith("'")
    assert wb["Summary"]["B4"].value == excel_safe_cell(malicious)
    os.remove(path)


def test_validate_report_path_rejects_outside_reports(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setattr("reports.excel_writer._REPORTS_DIR", reports)
    outside = tmp_path / "escape.xlsx"
    outside.write_bytes(b"")
    with pytest.raises(ValueError, match="outside"):
        validate_report_path(str(outside))
