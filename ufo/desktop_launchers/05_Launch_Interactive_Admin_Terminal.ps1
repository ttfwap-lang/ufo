# Requires RunAsAdministrator
$UfoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoExit -Command \"cd '$UfoRoot'; Write-Host 'UFO Desktop Terminal - Full Access';\""
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
$task = New-ScheduledTask -Action $action -Principal $principal
Register-ScheduledTask -TaskName "UFODesktopTerminal" -InputObject $task -Force
Start-ScheduledTask -TaskName "UFODesktopTerminal"
Unregister-ScheduledTask -TaskName "UFODesktopTerminal" -Confirm:$false
