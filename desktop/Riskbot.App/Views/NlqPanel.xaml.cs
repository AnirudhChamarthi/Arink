using System.Windows.Controls;
using System.Windows.Input;
using Riskbot.App.ViewModels;

namespace Riskbot.App.Views;

public partial class NlqPanel : UserControl
{
    public NlqPanel() => InitializeComponent();

    private void OnQueryKeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key != Key.Enter || DataContext is not NlqViewModel vm)
            return;
        if (vm.SendQueryCommand.CanExecute(null))
        {
            vm.SendQueryCommand.Execute(null);
            e.Handled = true;
        }
    }
}
