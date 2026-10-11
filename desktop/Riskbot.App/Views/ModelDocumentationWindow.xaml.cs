using System.Windows;
using Riskbot.App.Helpers;

namespace Riskbot.App.Views;

public partial class ModelDocumentationWindow : Window
{
    public ModelDocumentationWindow()
    {
        InitializeComponent();
        DocText.Text = ModelDocumentation.Content;
    }

    private void OnClose(object sender, RoutedEventArgs e) => Close();
}
