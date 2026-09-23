# Enable WebView2 remote debugging for ALL WebView2 apps via policy.
# Read by the WebView2 runtime itself, independent of how the host app
# (Telegram) was launched, so it survives runas/trustlevel launches.
$key = "HKLM:\SOFTWARE\Policies\Microsoft\Edge\WebView2"
if (-not (Test-Path $key)) { New-Item -Path $key -Force | Out-Null }
$json = '{"*":"--remote-debugging-port=9222"}'
Set-ItemProperty -Path $key -Name "BrowserAdditionalBrowserArguments" -Value $json -Type String
Write-Output ("policy set: " + (Get-ItemProperty -Path $key).BrowserAdditionalBrowserArguments)