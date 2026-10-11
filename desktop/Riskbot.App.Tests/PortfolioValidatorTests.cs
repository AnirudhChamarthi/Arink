using Riskbot.App.ExcelIntegration;
using Riskbot.App.Models;

namespace Riskbot.App.Tests;

public class PortfolioValidatorTests
{
    [Fact]
    public void Validate_rejects_more_than_max_holdings()
    {
        var validator = new PortfolioValidator();
        var metadata = new PortfolioMetadata
        {
            PortfolioName = "Big Book",
            BaseCurrency = "USD",
        };
        var holdings = Enumerable.Range(0, PortfolioValidator.MaxHoldings + 1)
            .Select(i => new HoldingLine
            {
                Ticker = $"T{i:D4}",
                AssetClass = "Equity",
                Quantity = 1,
                CostPrice = 10,
                Currency = "USD",
            })
            .ToList();

        var ex = Assert.Throws<PortfolioValidationException>(() => validator.Validate(metadata, holdings));
        Assert.True(ex.Errors.Any(e => e.Contains("maximum", StringComparison.OrdinalIgnoreCase)));
    }
}
