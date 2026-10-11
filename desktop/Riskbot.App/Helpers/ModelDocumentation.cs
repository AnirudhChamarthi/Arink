namespace Riskbot.App.Helpers;

/// <summary>In-app help text for Help → Model Documentation.</summary>
public static class ModelDocumentation
{
    public const string Content =
        """
        CONTRACT
        Single source of truth: shared/openapi.yaml (engine http://127.0.0.1:8765).

        ENDPOINTS
        • GET  /health — engine liveness
        • POST /enrich — 252d history, ESG, vol, rates (session id returned)
        • POST /nlq — natural-language query (Claude routing when ANTHROPIC_API_KEY set)
        • POST /risk/var — parametric, historical, or montecarlo VaR + CVaR
        • POST /risk/greeks — Black–Scholes deltas/gammas (equity & options)
        • POST /risk/stress — named scenarios (2008_credit, covid_2020, rate_shock_200bps, oil_spike_50pct)
        • POST /risk/sustainability — ESG score, carbon intensity, Paris alignment, exclusions
        • POST /risk/garch — GARCH(1,1) vol forecast for one ticker
        • POST /risk/full-report — all core models + Excel workbook with charts

        VaR (var.py)
        Parametric (variance–covariance), historical simulation, and Monte Carlo.
        User settings: Risk → VaR Settings (method, confidence %, horizon days).

        GREEKS (greeks.py)
        Black–Scholes with implied vol; portfolio delta/gamma aggregation.

        STRESS (stress.py)
        Scenario shocks from shared/scenarios.json; position and portfolio P&L.

        SUSTAINABILITY (sustainability.py)
        Weighted ESG, carbon intensity, carbon VaR, exclusion breaches.
        Custom filters: Risk → ESG & Exclusion Preferences (e.g. ticker:PLTR).

        GARCH (garch.py)
        ARMA–GARCH with AIC/BIC order selection; 10-day vol forecast.

        NLQ
        With API key: Claude returns JSON routing → executor runs models.
        Without key: keyword router (VaR, stress, ESG, etc.).

        EXCEL
        NLQ and full-report write 4-sheet workbooks under engine/output/reports/.
        RTD: =RTD("Riskbot.RTD",,"TICKER","Field") — see Help → Excel RTD Formulas.

        LIMITS
        Metadata sheet: VaRLimit, MaxConcentration, EsgMinScore, ExclusionFilters.
        Breaches show as amber row borders in the blotter.
        """;
}
