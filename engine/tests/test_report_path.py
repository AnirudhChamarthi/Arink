import pytest

from reports.excel_writer import validate_report_path


def test_validate_report_path_accepts_file_in_reports_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("reports.excel_writer._REPORTS_DIR", tmp_path)
    report = tmp_path / "riskbot_test.xlsx"
    report.write_bytes(b"")
    assert validate_report_path(str(report)) == str(report.resolve())


def test_validate_report_path_rejects_outside_reports(tmp_path, monkeypatch):
    monkeypatch.setattr("reports.excel_writer._REPORTS_DIR", tmp_path / "reports")
    outside = tmp_path / "evil.xlsx"
    outside.write_bytes(b"")
    with pytest.raises(ValueError, match="outside"):
        validate_report_path(str(outside))
