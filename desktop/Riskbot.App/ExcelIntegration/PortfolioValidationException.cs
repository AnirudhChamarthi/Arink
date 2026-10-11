namespace Riskbot.App.ExcelIntegration;

public sealed class PortfolioValidationException : Exception
{
    public PortfolioValidationException(string message) : base(message) { }
    public PortfolioValidationException(IReadOnlyList<string> errors)
        : base(string.Join(Environment.NewLine, errors))
    {
        Errors = errors;
    }

    public IReadOnlyList<string>? Errors { get; }
}
