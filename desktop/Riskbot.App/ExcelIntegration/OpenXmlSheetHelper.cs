using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Spreadsheet;

namespace Riskbot.App.ExcelIntegration;

internal static class OpenXmlSheetHelper
{
    public static string GetCellValue(Cell cell, SharedStringTable? sst)
    {
        if (cell.DataType?.Value == CellValues.InlineString)
            return cell.InlineString?.Text?.Text ?? cell.InlineString?.InnerText ?? "";

        if (cell.CellValue is null)
            return "";

        var text = cell.CellValue.InnerText;
        if (cell.DataType?.Value == CellValues.SharedString && sst is not null)
        {
            if (int.TryParse(text, out var idx) && idx < sst.ChildElements.Count)
                return sst.ChildElements[idx].InnerText;
        }

        return text;
    }

    public static Dictionary<string, int> ReadHeaderMap(Row headerRow, SharedStringTable? sst)
    {
        var map = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        foreach (var cell in headerRow.Elements<Cell>())
        {
            var name = GetCellValue(cell, sst).Trim();
            if (string.IsNullOrEmpty(name))
                continue;

            map[name] = ColumnIndexFromReference(cell.CellReference?.Value);
        }

        return map;
    }

    public static string? GetColumn(Row row, Dictionary<string, int> headers, string name, SharedStringTable? sst)
    {
        if (!headers.TryGetValue(name, out var colIndex))
            return null;

        foreach (var cell in row.Elements<Cell>())
        {
            if (ColumnIndexFromReference(cell.CellReference?.Value) == colIndex)
                return GetCellValue(cell, sst).Trim();
        }

        return null;
    }

    public static int ColumnIndexFromReference(string? cellReference)
    {
        if (string.IsNullOrWhiteSpace(cellReference))
            return 0;

        var letters = 0;
        foreach (var ch in cellReference)
        {
            if (!char.IsLetter(ch))
                break;
            letters = letters * 26 + (char.ToUpperInvariant(ch) - 'A' + 1);
        }

        return Math.Max(0, letters - 1);
    }

    public static void WriteRow(SheetData sheetData, uint rowIndex, IEnumerable<string> values)
    {
        var row = new Row { RowIndex = rowIndex };
        var col = 0;
        foreach (var v in values)
        {
            var colLetter = ColumnLetter(col);
            var cell = new Cell
            {
                CellReference = $"{colLetter}{rowIndex}",
                DataType = CellValues.String,
                CellValue = new CellValue(v ?? ""),
            };
            row.Append(cell);
            col++;
        }
        sheetData.Append(row);
    }

    public static string ColumnLetter(int index)
    {
        var dividend = index + 1;
        var columnName = "";
        while (dividend > 0)
        {
            var modulo = (dividend - 1) % 26;
            columnName = Convert.ToChar('A' + modulo) + columnName;
            dividend = (dividend - modulo) / 26;
        }
        return columnName;
    }

    public static WorksheetPart AddWorksheet(WorkbookPart workbookPart, string name, uint sheetId, Sheets sheets)
    {
        var part = workbookPart.AddNewPart<WorksheetPart>();
        part.Worksheet = new Worksheet(new SheetData());
        sheets.Append(new Sheet
        {
            Id = workbookPart.GetIdOfPart(part),
            SheetId = sheetId,
            Name = name,
        });
        return part;
    }
}
