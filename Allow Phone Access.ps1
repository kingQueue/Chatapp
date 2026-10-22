$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $PSCommandPath + '"')) -Wait
    exit
}
$pythonPath = (Get-Command python.exe).Source
$config = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'data/network.json') -Raw | ConvertFrom-Json
$address = [string]$config.address
if (-not $config.enabled -or -not $address -or -not (Get-NetIPAddress -IPAddress $address -ErrorAction SilentlyContinue)) {
    throw 'First enable Phone access in the app and select your home Wi-Fi address.'
}
$programs = @($pythonPath)
$pythonWindowless = Join-Path (Split-Path $pythonPath) 'pythonw.exe'
if (Test-Path -LiteralPath $pythonWindowless) { $programs += $pythonWindowless }
foreach ($program in $programs) {
    $ruleName = 'CharacterRoom-LocalNetwork-8766-' + [IO.Path]::GetFileNameWithoutExtension($program) + '-' + $address.Replace('.', '-')
    if (-not (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -Name $ruleName -DisplayName 'Character Room - local subnet phone access' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8766 -LocalAddress $address -Profile Private,Public -RemoteAddress LocalSubnet -Program $program | Out-Null
    }
}
Write-Host 'Phone access is allowed only for Python on your local subnet, on TCP port 8766.'
Write-Host 'Enable Phone access in Character Room, then open its displayed address on your phone.'
Write-Host 'To undo later, run as administrator: Get-NetFirewallRule -Name CharacterRoom-LocalNetwork-8766-* | Remove-NetFirewallRule'
