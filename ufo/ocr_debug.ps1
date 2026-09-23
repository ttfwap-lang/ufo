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

Write-Host "=== Bitmap ==="
Write-Host "Size: $($bmp.PixelWidth)x$($bmp.PixelHeight)"
Write-Host "Format: $($bmp.BitmapPixelFormat)"
Write-Host "Alpha: $($bmp.BitmapAlphaMode)"
Write-Host "DPI: $($bmp.DpiX)x$($bmp.DpiY)"

# Check supported formats
Write-Host "`n=== Supported formats ==="
[Enum]::GetNames([Windows.Graphics.Imaging.BitmapPixelFormat]) | Where-Object { $_ -like '*Bgra*' -or $_ -like '*Rgba*' } | ForEach-Object { Write-Host $_ }

# Try converting to BGRA8
$conv = [Windows.Graphics.Imaging.SoftwareBitmap]::Convert($bmp, [Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8, [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied)
Write-Host "`n=== Converted BGRA8 ==="
Write-Host "Size: $($conv.PixelWidth)x$($conv.PixelHeight)"
Write-Host "Format: $($conv.BitmapPixelFormat)"

# Try with converted bitmap
Write-Host "`n=== OCR on converted ==="
$eng = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new("en-US"))
if (-not $eng) { $eng = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
Write-Host "Engine: $($eng.GetType().Name)"
$ocr = Await ($eng.RecognizeAsync($conv)) ([Windows.Media.Ocr.OcrResult])
Write-Host "Lines: $($ocr.Lines.Count)"
foreach ($l in $ocr.Lines) {
    $r = $l.BoundingRect
    Write-Host ("[{0,4},{1,4} {2,4}x{3,4}] {4}" -f [int]$r.X, [int]$r.Y, [int]$r.Width, [int]$r.Height, $l.Text)
}

$fs.Close()