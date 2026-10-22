param(
    [Parameter(Mandatory=$true)][string]$InputFile,
    [Parameter(Mandatory=$true)][string]$OutputFile
)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null=[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null=[Windows.Storage.Streams.IRandomAccessStream,Windows.Storage.Streams,ContentType=WindowsRuntime]
$null=[Windows.Graphics.Imaging.BitmapDecoder,Windows.Foundation,ContentType=WindowsRuntime]
$null=[Windows.Graphics.Imaging.SoftwareBitmap,Windows.Foundation,ContentType=WindowsRuntime]
$null=[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
function Await-Result($operation,[Type]$resultType) {
    $method=[System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    } | Select-Object -First 1
    $task=$method.MakeGenericMethod($resultType).Invoke($null,@($operation))
    $task.GetAwaiter().GetResult()
}
$languages=@([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages)
$language=$languages | Where-Object {$_.LanguageTag -match '^zh-Hans'} | Select-Object -First 1
if($null -eq $language) { throw 'Chinese OCR language is unavailable' }
$engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
if($null -eq $engine) { throw 'OCR engine is unavailable' }
$file=Await-Result ([Windows.Storage.StorageFile]::GetFileFromPathAsync([IO.Path]::GetFullPath($InputFile))) ([Windows.Storage.StorageFile])
$stream=$null;$bitmap=$null
try {
    $stream=Await-Result ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder=Await-Result ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap=Await-Result ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $result=Await-Result ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $lines=@(foreach($line in $result.Lines) {
        $words=@(foreach($word in $line.Words) {
            @{text=$word.Text;x=$word.BoundingRect.X;y=$word.BoundingRect.Y;width=$word.BoundingRect.Width;height=$word.BoundingRect.Height}
        })
        @{text=$line.Text;words=$words}
    })
    $value=@{language=$language.LanguageTag;width=$bitmap.PixelWidth;height=$bitmap.PixelHeight;angle=$result.TextAngle;lines=$lines}
    [IO.File]::WriteAllText([IO.Path]::GetFullPath($OutputFile),($value | ConvertTo-Json -Depth 8 -Compress),(New-Object Text.UTF8Encoding($false)))
} finally {
    if($null -ne $bitmap) {$bitmap.Dispose()}
    if($null -ne $stream) {$stream.Dispose()}
}
