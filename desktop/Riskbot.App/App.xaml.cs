using System.Net.Http;
using System.Windows;
using Microsoft.Extensions.DependencyInjection;
using Riskbot.App.ApiClient;
using Riskbot.App.Infrastructure;
using Riskbot.App.Bus;
using Riskbot.App.ExcelIntegration;
using Riskbot.App.Services;
using Riskbot.App.ViewModels;

namespace Riskbot.App;

public partial class App : Application
{
    public static IServiceProvider Services { get; private set; } = null!;

    protected override void OnStartup(StartupEventArgs e)
    {
        DispatcherUnhandledException += (_, args) =>
        {
            MessageBox.Show(
                args.Exception.Message,
                "Riskbot — unexpected error",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
            args.Handled = true;
        };

        EnvFileLoader.LoadRepoEnv();

        var services = new ServiceCollection();
        ConfigureServices(services);
        Services = services.BuildServiceProvider();

        _ = Services.GetRequiredService<EnrichmentService>();
        _ = Services.GetRequiredService<PortfolioRiskService>();
        _ = Services.GetRequiredService<ResultViewModel>();
        _ = Services.GetRequiredService<RtdFeedService>();
        _ = Services.GetRequiredService<RiskLimitMonitorService>();

        var main = Services.GetRequiredService<MainWindow>();
        main.Show();
        base.OnStartup(e);
    }

    protected override async void OnExit(ExitEventArgs e)
    {
        if (Services is not null)
        {
            var engine = Services.GetService<EngineHostService>();
            if (engine is not null)
                await engine.DisposeAsync().ConfigureAwait(true);
            var risk = Services.GetService<PortfolioRiskService>();
            if (risk is not null)
                await risk.DisposeAsync().ConfigureAwait(true);
            var nlq = Services.GetService<NlqService>();
            if (nlq is not null)
                await nlq.DisposeAsync().ConfigureAwait(true);
            if (Services is IDisposable disposable)
                disposable.Dispose();
        }
        base.OnExit(e);
    }

    private static void ConfigureServices(IServiceCollection services)
    {
        services.AddSingleton<MessageBus>();
        services.AddSingleton<PortfolioValidator>();
        services.AddSingleton<PortfolioFileManager>();
        services.AddSingleton<TemplateWriter>();
        services.AddSingleton<RecentFilesStore>();
        services.AddSingleton<VarSettingsStore>();
        services.AddSingleton<PortfolioWorkspaceService>();
        services.AddSingleton<PortfolioSessionState>();
        services.AddSingleton<SelectionService>();
        services.AddSingleton<EnvFileStore>();

        services.AddSingleton(_ =>
        {
            var client = new HttpClient
            {
                BaseAddress = new Uri(EngineHostService.BaseUrl),
                Timeout = TimeSpan.FromMinutes(3),
            };
            return new RiskbotApiClient(client);
        });

        services.AddSingleton<EngineHostService>();
        services.AddSingleton<VarSettingsService>();
        services.AddSingleton<EsgPreferencesStore>();
        services.AddSingleton<EsgPreferencesService>();
        services.AddSingleton<EnrichmentService>();
        services.AddSingleton<PortfolioRiskService>();
        services.AddSingleton<RiskAnalysisService>();
        services.AddSingleton<RtdFeedService>();
        services.AddSingleton<RiskLimitMonitorService>();
        services.AddSingleton<NlqService>();

        services.AddSingleton<BlotterViewModel>();
        services.AddSingleton<TreemapViewModel>();
        services.AddSingleton<ResultViewModel>();
        services.AddSingleton<NlqViewModel>();
        services.AddTransient<ApiKeySettingsViewModel>();
        services.AddSingleton<MainViewModel>();

        services.AddSingleton<MainWindow>();
    }
}
