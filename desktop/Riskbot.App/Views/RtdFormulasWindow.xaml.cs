using System.Text;
using System.Windows;
using Riskbot.App.Services;
using Riskbot.RtdBridge;

namespace Riskbot.App.Views;

public partial class RtdFormulasWindow : Window
{
    public RtdFormulasWindow(RtdFeedService rtdFeed)
    {
        InitializeComponent();
        PathText.Text = $"Snapshot: {rtdFeed.SnapshotPath}\nAdd-in: Riskbot.Rtd.xll (see desktop/Riskbot.Rtd/README.md)";

        var sampleTicker = "AAPL";
        var sb = new StringBuilder();
        sb.AppendLine("Example formulas (replace AAPL with your ticker):");
        sb.AppendLine();
        foreach (var field in RtdFields.All)
        {
            sb.AppendLine($"=RTD(\"{RtdSnapshot.ProgId}\",,\"{sampleTicker}\",\"{field}\")");
        }

        FormulaBox.Text = sb.ToString();
    }

    private void OnCopy(object sender, RoutedEventArgs e)
    {
        Clipboard.SetText(FormulaBox.Text);
        MessageBox.Show("Copied to clipboard.", "Riskbot", MessageBoxButton.OK, MessageBoxImage.Information);
    }
}
