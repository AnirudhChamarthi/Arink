using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Spreadsheet;

namespace Riskbot.App.ExcelIntegration;

public sealed class TemplateWriter
{
    public static readonly string[] HoldingsHeaders =
    [
        "Date", "Ticker", "ISIN", "AssetClass", "Quantity", "CostPrice",
        "Currency", "Sector", "Country", "ESGOverride",
    ];

    public void WriteBlankTemplate(string filePath, string portfolioName = "New Portfolio", string baseCurrency = "USD")
    {
        if (File.Exists(filePath))
            File.Delete(filePath);

        using var doc = SpreadsheetDocument.Create(filePath, SpreadsheetDocumentType.Workbook);
        var wbPart = doc.AddWorkbookPart();
        wbPart.Workbook = new Workbook();
        var sheets = wbPart.Workbook.AppendChild(new Sheets());

        var holdingsPart = OpenXmlSheetHelper.AddWorksheet(wbPart, "Holdings", 1, sheets);
        var holdingsSheet = holdingsPart.Worksheet!.GetFirstChild<SheetData>()!;
        OpenXmlSheetHelper.WriteRow(holdingsSheet, 1, HoldingsHeaders);
        OpenXmlSheetHelper.WriteRow(holdingsSheet, 2,
        [
            DateOnly.FromDateTime(DateTime.Today).ToString("yyyy-MM-dd"),
            "AAPL", "", "Equity", "100", "150", "USD", "Technology", "US", "",
        ]);

        var metaPart = OpenXmlSheetHelper.AddWorksheet(wbPart, "Metadata", 2, sheets);
        var metaSheet = metaPart.Worksheet!.GetFirstChild<SheetData>()!;
        OpenXmlSheetHelper.WriteRow(metaSheet, 1, ["Key", "Value"]);
        WriteMetadataRow(metaSheet, 2, "PortfolioName", portfolioName);
        WriteMetadataRow(metaSheet, 3, "BaseCurrency", baseCurrency);
        WriteMetadataRow(metaSheet, 4, "Benchmark", "SPY");
        WriteMetadataRow(metaSheet, 5, "VaRLimit", "0.05");
        WriteMetadataRow(metaSheet, 6, "MaxConcentration", "0.15");
        WriteMetadataRow(metaSheet, 7, "ExclusionFilters", "");

        wbPart.Workbook.Save();
    }

    private static void WriteMetadataRow(SheetData sheetData, uint row, string key, string value)
    {
        OpenXmlSheetHelper.WriteRow(sheetData, row, [key, value]);
    }
}
