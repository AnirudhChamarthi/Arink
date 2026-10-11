namespace Riskbot.App.Models;

public sealed class PortfolioFile
{
    public required string FilePath { get; init; }
    public required PortfolioMetadata Metadata { get; init; }
    public required IReadOnlyList<HoldingLine> Holdings { get; init; }
}
