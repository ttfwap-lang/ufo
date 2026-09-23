Write-Output "User: $([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)"
$id = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$pr = New-Object System.Security.Principal.WindowsPrincipal($id)
Write-Output "Elevated: $($pr.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator))"
Write-Output "SessionId: $((Get-Process -Id $PID).SessionId)"
Write-Output "---"
Write-Output "Telegram owner:"
Get-Process Telegram -ErrorAction SilentlyContinue | Select-Object Id, SessionId, UserName | Format-Table -AutoSize | Out-String -Width 120 | Write-Output