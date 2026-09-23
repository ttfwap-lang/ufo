Get-WinEvent -FilterHashtable @{LogName='Application'; ProviderName='Application Error'} -MaxEvents 8 -ErrorAction SilentlyContinue |
  ForEach-Object {
    $m = $_.Message
    if ($m -match 'Telegram') {
        Write-Output ("[{0}] {1}" -f $_.TimeCreated, ($m -replace "`r?`n", ' ' | Select-Object -First 1).Substring(0, [Math]::Min(300, $m.Length)))
    }
  }
Write-Output "--- recent app errors (any) ---"
Get-WinEvent -FilterHashtable @{LogName='Application'; Level=2} -MaxEvents 8 -ErrorAction SilentlyContinue |
  ForEach-Object { Write-Output ("[{0}] {1}" -f $_.TimeCreated, ($_.ProviderName)) }