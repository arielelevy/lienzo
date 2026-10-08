param(
    [Parameter(Mandatory=$true)][ValidateRange(1,65535)][int]$DebugPort,
    [ValidateRange(1,55)][int]$TimeoutSeconds = 45
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class ChromeConsentWindows {
    public delegate bool Callback(IntPtr window, IntPtr data);
    [DllImport("user32.dll")] public static extern bool EnumWindows(Callback callback, IntPtr data);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr window, out uint pid);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr window, StringBuilder text, int size);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr window, StringBuilder text, int size);
}
'@

function Normalize-Label([string]$Label) {
    return ($Label.Normalize([Text.NormalizationForm]::FormD) -replace '\p{Mn}', '' -replace '[^a-zA-Z ]', '').Trim().ToLowerInvariant()
}

try {
    $listeners = @(Get-NetTCPConnection -LocalPort $DebugPort -State Listen |
        Where-Object { $_.LocalAddress -in @('127.0.0.1', '::1') })
    $owners = @($listeners.OwningProcess | Select-Object -Unique)
    if ($owners.Count -ne 1) { throw 'Chrome loopback listener is not unique' }
    $chromeProcessId = [int]$owners[0]
    $process = Get-Process -Id $chromeProcessId
    if ([IO.Path]::GetFileName($process.Path) -ine 'chrome.exe') { throw 'The listener does not belong to Chrome' }
    $titles = @('allow remote debugging', 'permitir la depuracion remota', 'permitir depuracion remota')
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $nativeDialogs = 0
    $nativeButtons = 0
    while ([DateTime]::UtcNow -lt $deadline) {
        $handles = [Collections.Generic.List[IntPtr]]::new()
        $callback = [ChromeConsentWindows+Callback] {
            param([IntPtr]$handle, [IntPtr]$data)
            [uint32]$owner = 0
            [void][ChromeConsentWindows]::GetWindowThreadProcessId($handle, [ref]$owner)
            if ($owner -ne $chromeProcessId -or -not [ChromeConsentWindows]::IsWindowVisible($handle)) { return $true }
            $title = [Text.StringBuilder]::new(512)
            $class = [Text.StringBuilder]::new(128)
            [void][ChromeConsentWindows]::GetWindowText($handle, $title, 512)
            [void][ChromeConsentWindows]::GetClassName($handle, $class, 128)
            if ($class.ToString() -in @('Chrome_WidgetWin_1', 'Chrome_WidgetWin_2') -and (Normalize-Label $title.ToString()) -in $titles) { $handles.Add($handle) }
            return $true
        }
        [void][ChromeConsentWindows]::EnumWindows($callback, [IntPtr]::Zero)
        $nativeDialogs = $handles.Count
        $matches = @()
        $nativeButtons = 0
        foreach ($handle in $handles) {
            $window = [Windows.Automation.AutomationElement]::FromHandle($handle)
            $buttonCondition = [Windows.Automation.PropertyCondition]::new(
                [Windows.Automation.AutomationElement]::ControlTypeProperty,
                [Windows.Automation.ControlType]::Button)
            $buttons = $window.FindAll([Windows.Automation.TreeScope]::Descendants, $buttonCondition)
            $nativeButtons += $buttons.Count
            foreach ($button in $buttons) {
                if ($button.Current.ProcessId -ne $chromeProcessId -or $button.Current.IsOffscreen -or -not $button.Current.IsEnabled) { continue }
                if ((Normalize-Label $button.Current.Name) -notin @('allow', 'permitir')) { continue }
                $ancestor = $button
                $isWebContent = $false
                while ($ancestor -and $ancestor -ne $window) {
                    if ($ancestor.Current.ControlType -eq [Windows.Automation.ControlType]::Document) { $isWebContent = $true; break }
                    $ancestor = [Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($ancestor)
                }
                if ($isWebContent) { continue }
                $matches += $button
            }
        }
        if ($matches.Count -gt 1) { throw 'More than one Chrome debugging approval button was found' }
        if ($matches.Count -eq 1) {
            $matches[0].GetCurrentPattern([Windows.Automation.InvokePattern]::Pattern).Invoke()
            '{"clicked":true}'
            exit 0
        }
        Start-Sleep -Milliseconds 350
    }
    throw "Chrome debugging dialog was not identified within the time limit (native dialogs: $nativeDialogs; buttons: $nativeButtons)"
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
