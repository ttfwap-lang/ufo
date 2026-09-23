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
foreach ($l in $ocr.Lines) {
    $r = $l.BoundingRect
    Write-Host ("[{0,4},{1,4} {2,4}x{3,4}] {4}" -f [int]$r.X, [int]$r.Y, [int]$r.Width, [int]$r.Height, $l.Text)
}
$fs.Close()