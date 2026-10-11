using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;

namespace Riskbot.App.ApiClient;

/// <summary>Typed HTTP client for shared/openapi.yaml (subset implemented in Step 4).</summary>
public sealed class RiskbotApiClient
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly HttpClient _http;

    public RiskbotApiClient(HttpClient http) => _http = http;

    public Uri BaseAddress => _http.BaseAddress ?? new Uri("http://127.0.0.1:8765/");

    public async Task<HealthResponse?> GetHealthAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            return await _http.GetFromJsonAsync<HealthResponse>("/health", JsonOptions, cancellationToken)
                .ConfigureAwait(false);
        }
        catch
        {
            return null;
        }
    }

    public async Task<EnrichResponseDto> EnrichAsync(
        EnrichRequest request,
        CancellationToken cancellationToken = default)
    {
        var response = await _http
            .PostAsJsonAsync("/enrich?response_detail=display", request, JsonOptions, cancellationToken)
            .ConfigureAwait(false);

        if (!response.IsSuccessStatusCode)
        {
            var body = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
            throw new HttpRequestException(
                $"POST /enrich failed ({(int)response.StatusCode}): {body}");
        }

        var result = await response.Content
            .ReadFromJsonAsync<EnrichResponseDto>(JsonOptions, cancellationToken)
            .ConfigureAwait(false);

        return result ?? throw new InvalidOperationException("Empty enrich response.");
    }

    public async Task<VarResultDto> RunVarAsync(
        string portfolioSessionId,
        double confidence = 0.99,
        int horizonDays = 1,
        string method = "parametric",
        CancellationToken cancellationToken = default)
    {
        var body = new VarRequestDto
        {
            PortfolioSessionId = portfolioSessionId,
            Method = method,
            Confidence = confidence,
            HorizonDays = horizonDays,
        };

        var response = await _http
            .PostAsJsonAsync("/risk/var", body, JsonOptions, cancellationToken)
            .ConfigureAwait(false);

        if (!response.IsSuccessStatusCode)
        {
            var text = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
            throw new HttpRequestException($"POST /risk/var failed ({(int)response.StatusCode}): {text}");
        }

        var result = await response.Content
            .ReadFromJsonAsync<VarResultDto>(JsonOptions, cancellationToken)
            .ConfigureAwait(false);

        return result ?? throw new InvalidOperationException("Empty VaR response.");
    }

    public async Task<NlqResultDto> RunNlqAsync(
        NlqRequestDto request,
        CancellationToken cancellationToken = default)
    {
        var response = await _http
            .PostAsJsonAsync("/nlq", request, JsonOptions, cancellationToken)
            .ConfigureAwait(false);

        if (!response.IsSuccessStatusCode)
        {
            var text = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
            throw new HttpRequestException($"POST /nlq failed ({(int)response.StatusCode}): {text}");
        }

        var result = await response.Content
            .ReadFromJsonAsync<NlqResultDto>(JsonOptions, cancellationToken)
            .ConfigureAwait(false);

        return result ?? throw new InvalidOperationException("Empty NLQ response.");
    }

    public Task<PortfolioGreeksDto> RunGreeksAsync(
        string portfolioSessionId,
        CancellationToken cancellationToken = default) =>
        PostAsync<PortfolioGreeksDto>(
            "/risk/greeks",
            new PortfolioSessionRequestDto { PortfolioSessionId = portfolioSessionId },
            cancellationToken);

    public Task<StressResultDto> RunStressAsync(
        string portfolioSessionId,
        string scenario,
        CancellationToken cancellationToken = default) =>
        PostAsync<StressResultDto>(
            "/risk/stress",
            new StressRequestDto { PortfolioSessionId = portfolioSessionId, Scenario = scenario },
            cancellationToken);

    public Task<SustainabilityResultDto> RunSustainabilityAsync(
        SustainabilityRequestDto request,
        CancellationToken cancellationToken = default) =>
        PostAsync<SustainabilityResultDto>("/risk/sustainability", request, cancellationToken);

    public Task<FullReportResultDto> RunFullReportAsync(
        FullReportRequestDto request,
        CancellationToken cancellationToken = default) =>
        PostAsync<FullReportResultDto>("/risk/full-report", request, cancellationToken);

    private async Task<T> PostAsync<T>(
        string path,
        object body,
        CancellationToken cancellationToken)
    {
        var response = await _http
            .PostAsJsonAsync(path, body, JsonOptions, cancellationToken)
            .ConfigureAwait(false);

        if (!response.IsSuccessStatusCode)
        {
            var text = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
            throw new HttpRequestException($"POST {path} failed ({(int)response.StatusCode}): {text}");
        }

        var result = await response.Content
            .ReadFromJsonAsync<T>(JsonOptions, cancellationToken)
            .ConfigureAwait(false);

        return result ?? throw new InvalidOperationException($"Empty response from {path}.");
    }
}
