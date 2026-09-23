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

$first = $ocr.Lines[0]
Write-Host "Line.Text: $($first.Text)"
Write-Host "Line.Words count: $($first.Words.Count)"

# Check words
foreach ($w in $first.Words) {
    Write-Host "Word: $($w.Text)"
    Write-Host "  Word type: $($w.GetType().FullName)"
    $w | Get-Member | Select-Object Name, MemberType | Format-Table -AutoSize | Out-String -Width 200 | Write-Host
    $wr = $w.BoundingRect
    if ($wr) {
        Write-Host "  Word Rect: X=$($wr.X) Y=$($wr.Y) W=$($wr.Width) H=$($wr.Height)"
    } else {
        Write-Host "  Word Rect: NULL"
    }
}

$fs.Close()