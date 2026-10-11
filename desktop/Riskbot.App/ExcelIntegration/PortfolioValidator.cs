using System.Text.RegularExpressions;
using Riskbot.App.Models;

namespace Riskbot.App.ExcelIntegration;

public sealed class PortfolioValidator
{
    public const int MaxHoldings = 1000;

    private static readonly string[] AssetClasses = ["Equity", "FixedIncome", "Commodity", "Cash"];
    private static readonly Regex CurrencyRx = new("^[A-Z]{3}$", RegexOptions.Compiled);
    private static readonly Regex CountryRx = new("^[A-Z]{2}$", RegexOptions.Compiled);
    private static readonly Regex IsinRx = new("^[A-Z]{2}[A-Z0-9]{10}$", RegexOptions.Compiled);

    public void Validate(PortfolioMetadata metadata, IReadOnlyList<HoldingLine> holdings)
    {
        var errors = new List<string>();

        if (string.IsNullOrWhiteSpace(metadata.PortfolioName))
            errors.Add("Metadata: PortfolioName is required.");
        if (string.IsNullOrWhiteSpace(metadata.BaseCurrency) || !CurrencyRx.IsMatch(metadata.BaseCurrency))
            errors.Add("Metadata: BaseCurrency must be a 3-letter ISO 4217 code.");

        if (metadata.VarLimit is < 0 or > 1)
            errors.Add("Metadata: VaRLimit must be between 0 and 1.");
        if (metadata.MaxConcentration is < 0 or > 1)
            errors.Add("Metadata: MaxConcentration must be between 0 and 1.");

        if (holdings.Count == 0)
            errors.Add("Holdings: at least one position is required.");
        else if (holdings.Count > MaxHoldings)
            errors.Add($"Holdings: maximum {MaxHoldings} positions allowed (file has {holdings.Count}).");

        for (var i = 0; i < holdings.Count; i++)
        {
            var h = holdings[i];
            var row = i + 2;
            if (string.IsNullOrWhiteSpace(h.Ticker))
                errors.Add($"Holdings row {row}: Ticker is required.");
            else if (h.Ticker.Length > 20)
                errors.Add($"Holdings row {row}: Ticker exceeds 20 characters.");

            if (!AssetClasses.Contains(h.AssetClass))
                errors.Add($"Holdings row {row}: AssetClass must be Equity, FixedIncome, Commodity, or Cash.");

            if (h.Quantity == 0)
                errors.Add($"Holdings row {row}: Quantity cannot be zero.");

            if (h.CostPrice < 0)
                errors.Add($"Holdings row {row}: CostPrice cannot be negative.");

            if (string.IsNullOrWhiteSpace(h.Currency) || !CurrencyRx.IsMatch(h.Currency))
                errors.Add($"Holdings row {row}: Currency must be a 3-letter ISO code.");

            if (!string.IsNullOrWhiteSpace(h.Country) && !CountryRx.IsMatch(h.Country))
                errors.Add($"Holdings row {row}: Country must be a 2-letter ISO code.");

            if (!string.IsNullOrWhiteSpace(h.Isin) && !IsinRx.IsMatch(h.Isin))
                errors.Add($"Holdings row {row}: ISIN format is invalid.");

            if (h.EsgOverride is < 0 or > 100)
                errors.Add($"Holdings row {row}: ESGOverride must be between 0 and 100.");
        }

        if (errors.Count > 0)
            throw new PortfolioValidationException(errors);
    }
}
