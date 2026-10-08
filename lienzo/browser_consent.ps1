param(
    [Parameter(Mandatory=$true)][ValidateRange(1,65535)][int]$DebugPort,
    [ValidateRange(1,55)][int]$TimeoutSeconds = 45
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

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
    $condition = [Windows.Automation.PropertyCondition]::new(
        [Windows.Automation.AutomationElement]::ProcessIdProperty, $chromeProcessId)
    $titles = @('allow remote debugging', 'permitir la depuracion remota', 'permitir depuracion remota')
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $windows = [Windows.Automation.AutomationElement]::RootElement.FindAll(
            [Windows.Automation.TreeScope]::Children, $condition)
        $matches = @()
        foreach ($window in $windows) {
            if ($window.Current.ClassName -notin @('Chrome_WidgetWin_1', 'Chrome_WidgetWin_2')) { continue }
            if ($window.Current.NativeWindowHandle -eq 0 -or $window.Current.IsOffscreen) { continue }
            if ((Normalize-Label $window.Current.Name) -notin $titles) { continue }
            $buttonCondition = [Windows.Automation.PropertyCondition]::new(
                [Windows.Automation.AutomationElement]::ControlTypeProperty,
                [Windows.Automation.ControlType]::Button)
            $buttons = $window.FindAll([Windows.Automation.TreeScope]::Descendants, $buttonCondition)
            foreach ($button in $buttons) {
                if ($button.Current.ProcessId -ne $chromeProcessId -or $button.Current.IsOffscreen -or -not $button.Current.IsEnabled) { continue }
                if ((Normalize-Label $button.Current.Name) -notin @('allow', 'permitir')) { continue }
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
    throw 'Chrome debugging dialog was not identified within the time limit'
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
