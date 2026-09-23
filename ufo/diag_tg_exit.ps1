Write-Output "=== Application log: last 15 errors/warnings ==="
Get-WinEvent -FilterHashtable @{LogName='Application'; Level=1,2,3} -MaxEvents 15 -ErrorAction SilentlyContinue |
  ForEach-Object { Write-Output ("[{0}] {1} :: {2}" -f $_.TimeCreated, $_.ProviderName, ($_.Message -replace "`r?`n"," ").Substring(0,[Math]::Min(160,($_.Message -replace "`r?`n"," ").Length))) }

Write-Output ""
Write-Output "=== Telegram process now ==="
Get-Process Telegram -ErrorAction SilentlyContinue | Select-Object Id, StartTime | Format-Table -AutoSize | Out-String | Write-Output

Write-Output "=== Scheduled tasks mentioning telegram/ufo ==="
Get-ScheduledTask -ErrorAction SilentlyContinue |
  Where-Object { $_.TaskName -match "telegram|ufo|restart" } |
  Select-Object TaskName, State | Format-Table -AutoSize | Out-String | Write-Output