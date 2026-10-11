using Riskbot.App.ApiClient;
using Riskbot.App.Models;

namespace Riskbot.App.Services;

/// <summary>Synchronous limit checks — no I/O.</summary>
public static class RiskLimitMonitor
{
    public const string Concentration = "concentration";
    public const string Exclusion = "exclusion";
    public const string EsgPosition = "esg_position";
    public const string VarLimit = "var_limit";
    public const string PortfolioEsg = "portfolio_esg";

    public static RiskLimitEvaluation Evaluate(
        IReadOnlyList<BlotterRow> rows,
        RiskLimitsDto limits,
        double? portfolioVarDecimal,
        double? portfolioEsgScore)
    {
        var positionBreaches = new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);
        var portfolioBreaches = new List<string>();

        foreach (var row in rows)
        {
            var reasons = new List<string>();

            if (limits.MaxConcentration is { } maxConc
                && row.WeightPercent is { } w
                && w / 100.0 > maxConc + 1e-9)
                reasons.Add(Concentration);

            if (limits.EsgMinScore is { } minEsg
                && row.EsgScore is { } esg
                && esg < minEsg - 1e-9)
                reasons.Add(EsgPosition);

            var exclusionHits = ExclusionChecker.MatchingFilters(
                row.Ticker, row.Name, row.Sector, limits.ExclusionFilters);
            if (exclusionHits.Count > 0)
                reasons.Add(Exclusion);

            if (reasons.Count > 0)
                positionBreaches[row.Ticker] = reasons;
        }

        if (limits.VarLimit is { } varLimit
            && portfolioVarDecimal is { } pVar
            && pVar > varLimit + 1e-9)
            portfolioBreaches.Add(VarLimit);

        if (limits.EsgMinScore is { } portfolioMin
            && portfolioEsgScore is { } pEsg
            && pEsg < portfolioMin - 1e-9)
            portfolioBreaches.Add(PortfolioEsg);

        return new RiskLimitEvaluation(positionBreaches, portfolioBreaches);
    }

    public static double? WeightedPortfolioEsg(IReadOnlyList<BlotterRow> rows)
    {
        var totalMv = rows.Sum(r => r.MarketValue ?? 0);
        if (totalMv <= 1e-9)
            return null;

        double sum = 0;
        foreach (var row in rows)
        {
            if (row.EsgScore is not { } esg || row.MarketValue is not { } mv)
                continue;
            sum += esg * (mv / totalMv);
        }

        return sum;
    }
}

public sealed class RiskLimitEvaluation
{
    public RiskLimitEvaluation(
        Dictionary<string, List<string>> positionBreaches,
        List<string> portfolioBreaches)
    {
        PositionBreaches = positionBreaches.ToDictionary(
            kv => kv.Key,
            kv => (IReadOnlyList<string>)kv.Value,
            StringComparer.OrdinalIgnoreCase);
        PortfolioBreaches = portfolioBreaches;
    }

    public IReadOnlyDictionary<string, IReadOnlyList<string>> PositionBreaches { get; }
    public IReadOnlyList<string> PortfolioBreaches { get; }
}
