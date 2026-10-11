using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Spreadsheet;
using Riskbot.App.Models;

namespace Riskbot.App.ExcelIntegration;

public sealed class PortfolioFileManager
{
    private readonly PortfolioValidator _validator;

    public PortfolioFileManager(PortfolioValidator validator) => _validator = validator;

    public PortfolioFile Read(string filePath)
    {
        if (!File.Exists(filePath))
            throw new FileNotFoundException("Portfolio file not found.", filePath);

        using var doc = SpreadsheetDocument.Open(filePath, false);
        var wb = doc.WorkbookPart ?? throw new PortfolioValidationException("Workbook is empty.");
        var holdings = ReadHoldings(wb);
        var metadata = ReadMetadata(wb);
        _validator.Validate(metadata, holdings);
        return new PortfolioFile
        {
            FilePath = Path.GetFullPath(filePath),
            Metadata = metadata,
            Holdings = holdings,
        };
    }

    public void Save(PortfolioFile portfolio)
    {
        _validator.Validate(portfolio.Metadata, portfolio.Holdings);
        var path = portfolio.FilePath;
        if (File.Exists(path))
            File.Delete(path);

        using var doc = SpreadsheetDocument.Create(path, SpreadsheetDocumentType.Workbook);
        var wbPart = doc.AddWorkbookPart();
        wbPart.Workbook = new Workbook();
        var sheets = wbPart.Workbook.AppendChild(new Sheets());
        OpenXmlSheetHelper.AddWorksheet(wbPart, "Holdings", 1, sheets);
        OpenXmlSheetHelper.AddWorksheet(wbPart, "Metadata", 2, sheets);
        WriteHoldings(wbPart, portfolio.Holdings);
        WriteMetadata(wbPart, portfolio.Metadata);
        wbPart.Workbook.Save();
    }

    private static List<HoldingLine> ReadHoldings(WorkbookPart wb)
    {
        var sheet = FindSheet(wb, "Holdings") ?? wb.Workbook?.Sheets?.Elements<Sheet>().FirstOrDefault()
            ?? throw new PortfolioValidationException("Holdings sheet not found.");
        var part = (WorksheetPart)wb.GetPartById(sheet.Id!);
        var data = part.Worksheet.GetFirstChild<SheetData>();
        if (data is null)
            throw new PortfolioValidationException("Holdings sheet has no data.");

        var sst = wb.SharedStringTablePart?.SharedStringTable;
        var rows = data.Elements<Row>().ToList();
        if (rows.Count < 2)
            throw new PortfolioValidationException("Holdings sheet must include a header and at least one row.");

        var headers = OpenXmlSheetHelper.ReadHeaderMap(rows[0], sst);
        var required = new[] { "Ticker", "AssetClass", "Quantity", "CostPrice", "Currency" };
        foreach (var col in required)
        {
            if (!headers.ContainsKey(col))
                throw new PortfolioValidationException($"Holdings sheet missing column: {col}");
        }

        var holdings = new List<HoldingLine>();
        foreach (var row in rows.Skip(1))
        {
            var ticker = OpenXmlSheetHelper.GetColumn(row, headers, "Ticker", sst);
            if (string.IsNullOrWhiteSpace(ticker))
                continue;

            holdings.Add(new HoldingLine
            {
                Date = ParseDate(OpenXmlSheetHelper.GetColumn(row, headers, "Date", sst)),
                Ticker = ticker.ToUpperInvariant(),
                Isin = NullIfEmpty(OpenXmlSheetHelper.GetColumn(row, headers, "ISIN", sst))?.ToUpperInvariant(),
                AssetClass = OpenXmlSheetHelper.GetColumn(row, headers, "AssetClass", sst) ?? "",
                Quantity = ParseDouble(OpenXmlSheetHelper.GetColumn(row, headers, "Quantity", sst)),
                CostPrice = ParseDouble(OpenXmlSheetHelper.GetColumn(row, headers, "CostPrice", sst)),
                Currency = (OpenXmlSheetHelper.GetColumn(row, headers, "Currency", sst) ?? "USD").ToUpperInvariant(),
                Sector = NullIfEmpty(OpenXmlSheetHelper.GetColumn(row, headers, "Sector", sst)),
                Country = NullIfEmpty(OpenXmlSheetHelper.GetColumn(row, headers, "Country", sst))?.ToUpperInvariant(),
                EsgOverride = ParseNullableDouble(OpenXmlSheetHelper.GetColumn(row, headers, "ESGOverride", sst)),
            });
        }
        return holdings;
    }

    private static PortfolioMetadata ReadMetadata(WorkbookPart wb)
    {
        var sheet = FindSheet(wb, "Metadata")
            ?? throw new PortfolioValidationException("Metadata sheet not found.");
        var part = (WorksheetPart)wb.GetPartById(sheet.Id!);
        var data = part.Worksheet.GetFirstChild<SheetData>();
        if (data is null)
            throw new PortfolioValidationException("Metadata sheet has no data.");

        var sst = wb.SharedStringTablePart?.SharedStringTable;
        var map = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var row in data.Elements<Row>().Skip(1))
        {
            var cells = row.Elements<Cell>().ToList();
            if (cells.Count < 2) continue;
            var key = OpenXmlSheetHelper.GetCellValue(cells[0], sst).Trim();
            var val = OpenXmlSheetHelper.GetCellValue(cells[1], sst).Trim();
            if (!string.IsNullOrEmpty(key))
                map[key] = val;
        }

        return new PortfolioMetadata
        {
            PortfolioName = map.GetValueOrDefault("PortfolioName") ?? "Portfolio",
            BaseCurrency = (map.GetValueOrDefault("BaseCurrency") ?? "USD").ToUpperInvariant(),
            Benchmark = NullIfEmpty(map.GetValueOrDefault("Benchmark")),
            VarLimit = ParseNullableDouble(map.GetValueOrDefault("VaRLimit")),
            MaxConcentration = ParseNullableDouble(map.GetValueOrDefault("MaxConcentration")),
            EsgMinScore = ParseNullableDouble(map.GetValueOrDefault("EsgMinScore")),
            ExclusionFilters = NullIfEmpty(map.GetValueOrDefault("ExclusionFilters")),
        };
    }

    private static void WriteHoldings(WorkbookPart wb, IReadOnlyList<HoldingLine> holdings)
    {
        var sheet = FindSheet(wb, "Holdings")!;
        var part = (WorksheetPart)wb.GetPartById(sheet.Id!);
        part.Worksheet.RemoveAllChildren<SheetData>();
        var data = new SheetData();
        part.Worksheet.Append(data);
        OpenXmlSheetHelper.WriteRow(data, 1, TemplateWriter.HoldingsHeaders);
        uint r = 2;
        foreach (var h in holdings)
        {
            OpenXmlSheetHelper.WriteRow(data, r++,
            [
                h.Date?.ToString("yyyy-MM-dd") ?? "",
                h.Ticker,
                h.Isin ?? "",
                h.AssetClass,
                h.Quantity.ToString(System.Globalization.CultureInfo.InvariantCulture),
                h.CostPrice.ToString(System.Globalization.CultureInfo.InvariantCulture),
                h.Currency,
                h.Sector ?? "",
                h.Country ?? "",
                h.EsgOverride?.ToString(System.Globalization.CultureInfo.InvariantCulture) ?? "",
            ]);
        }
    }

    private static void WriteMetadata(WorkbookPart wb, PortfolioMetadata m)
    {
        var sheet = FindSheet(wb, "Metadata")!;
        var part = (WorksheetPart)wb.GetPartById(sheet.Id!);
        part.Worksheet.RemoveAllChildren<SheetData>();
        var data = new SheetData();
        part.Worksheet.Append(data);
        OpenXmlSheetHelper.WriteRow(data, 1, ["Key", "Value"]);
        uint r = 2;
        void Row(string k, string? v) => OpenXmlSheetHelper.WriteRow(data, r++, [k, v ?? ""]);
        Row("PortfolioName", m.PortfolioName);
        Row("BaseCurrency", m.BaseCurrency);
        Row("Benchmark", m.Benchmark);
        Row("VaRLimit", m.VarLimit?.ToString(System.Globalization.CultureInfo.InvariantCulture));
        Row("MaxConcentration", m.MaxConcentration?.ToString(System.Globalization.CultureInfo.InvariantCulture));
        Row("ExclusionFilters", m.ExclusionFilters);
    }

    private static Sheet? FindSheet(WorkbookPart wb, string name) =>
        wb.Workbook?.Sheets?.Elements<Sheet>().FirstOrDefault(s =>
            string.Equals(s.Name?.Value, name, StringComparison.OrdinalIgnoreCase));

    private static string? NullIfEmpty(string? s) => string.IsNullOrWhiteSpace(s) ? null : s.Trim();

    private static double ParseDouble(string? s) =>
        double.TryParse(s, System.Globalization.NumberStyles.Any,
            System.Globalization.CultureInfo.InvariantCulture, out var d) ? d : 0;

    private static double? ParseNullableDouble(string? s) =>
        string.IsNullOrWhiteSpace(s) ? null : ParseDouble(s);

    private static DateOnly? ParseDate(string? s) =>
        DateOnly.TryParse(s, out var d) ? d : null;
}
