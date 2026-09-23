param([string]$Path = 'C:\Users\lnxzf\Desktop\projects\ufo\ufo\astro_state.png')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]

function Await($op, $type) {
    $methods = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and $_.GetParameters().Count -eq 1
    }
    $hit = $null
    foreach ($m in $methods) {
        $pt = $m.GetParameters()[0].ParameterType
        if ($pt.IsGenericType -and $pt.GetGenericTypeDefinition().Name -eq 'IAsyncOperation`1') {
            $hit = $m; break
        }
    }
    if (-not $hit) { throw "No AsTask for $($op.GetType().Name)" }
    $task = $hit.MakeGenericMethod($type).Invoke($null, @($op))
    $task.Wait() | Out-Null
    $task.Result
}

$fs = [System.IO.File]::OpenRead($Path)
$stream = [System.IO.WindowsRuntimeStreamExtensions]::AsRandomAccessStream($fs)
$dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bmp = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

$eng = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new("en-US"))
if (-not $eng) { $eng = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
$ocr = Await ($eng.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])

# Inspect first line
$first = $ocr.Lines[0]
Write-Host "Line type: $($first.GetType().FullName)"
Write-Host "Line members:"
$first | Get-Member | Select-Object Name, MemberType, Definition | Format-Table -AutoSize | Out-String -Width 200 | Write-Host

# Inspect BoundingRect
$rect = $first.BoundingRect
Write-Host "`nRect type: $($rect.GetType().FullName)"
$rect | Get-Member | Select-Object Name, MemberType, Definition | Format-Table -AutoSize | Out-String -Width 200 | Write-Host
Write-Host "Rect raw: X=$($rect.X) Y=$($rect.Y) W=$($rect.Width) H=$($rect.Height)"

# Try with TryCreateFromUserProfileLanguages
$eng2 = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
$ocr2 = Await ($eng2.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
Write-Host "`n=== TryCreateFromUserProfileLanguages ==="
Write-Host "Lines: $($ocr2.Lines.Count)"
$first2 = $ocr2.Lines[0]
$r2 = $first2.BoundingRect
Write-Host "Rect2: X=$($r2.X) Y=$($r2.Y) W=$($r2.Width) H=$($r2.Height)"

$fs.Close()