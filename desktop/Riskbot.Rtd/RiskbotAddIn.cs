using ExcelDna.ComInterop;
using ExcelDna.Integration;

namespace Riskbot.Rtd;

/// <summary>Registers COM classes (including RTD server ProgId Riskbot.RTD) when the add-in loads.</summary>
public sealed class RiskbotAddIn : IExcelAddIn
{
    public void AutoOpen() => ComServer.DllRegisterServer();

    public void AutoClose() => ComServer.DllUnregisterServer();
}
