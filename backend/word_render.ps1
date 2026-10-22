param(
    [Parameter(Mandatory=$true)][ValidateSet('export','page')][string]$Mode,
    [Parameter(Mandatory=$true)][string]$InputFile,
    [Parameter(Mandatory=$true)][string]$OutputFile,
    [int]$Page=1
)
$ErrorActionPreference='Stop'
$InputFile=[IO.Path]::GetFullPath($InputFile)
$OutputFile=[IO.Path]::GetFullPath($OutputFile)
if($Mode -eq 'export') {
    $application=$null;$document=$null;$owned=$false;$settings=@{}
    $mutex=New-Object System.Threading.Mutex($false,'Local\StarTranslatorWordPreview')
    $locked=$false
    try {
        try { $locked=$mutex.WaitOne(30000) } catch [System.Threading.AbandonedMutexException] { $locked=$true }
        if(-not $locked) { throw 'Word preview is busy' }
        # Create a separate automation instance. Never attach to a user's open
        # document, save the input, run macros or refresh links/fields.
        $application=New-Object -ComObject Word.Application
        if($application.Documents.Count -ne 0) { throw 'Automation instance contains user documents' }
        $owned=$true
        $application.Visible=$false
        $application.DisplayAlerts=0
        $application.AutomationSecurity=3
        foreach($key in @('UpdateLinksAtOpen','UpdateFieldsAtPrint','UpdateLinksAtPrint')) {
            try { $settings[$key]=$application.Options.$key;$application.Options.$key=$false } catch {}
        }
        $document=$application.Documents.Open($InputFile,$false,$true,$false)
        $document.ExportAsFixedFormat($OutputFile,17)
        if(-not (Test-Path -LiteralPath $OutputFile)) { throw 'Word did not export a PDF' }
    } finally {
        foreach($key in @($settings.Keys)) { try { $application.Options.$key=$settings[$key] } catch {} }
        if($null -ne $document) {
            try { $document.Close(0) } catch {}
            try { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($document) } catch {}
        }
        if($owned) { try { $application.Quit(0) } catch {} }
        if($null -ne $application) { try { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($application) } catch {} }
        if($locked) { $mutex.ReleaseMutex() }
        $mutex.Dispose()
    }
    exit
}

# Windows supplies the PDF rasterizer; no browser repagination, additional
# runtime download or dependency on an installed PDF application is needed.
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null=[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null=[Windows.Data.Pdf.PdfDocument,Windows.Data.Pdf,ContentType=WindowsRuntime]
$null=[Windows.Storage.Streams.InMemoryRandomAccessStream,Windows.Storage.Streams,ContentType=WindowsRuntime]
function Await-Result($operation,[Type]$resultType) {
    $method=[System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    } | Select-Object -First 1
    $task=$method.MakeGenericMethod($resultType).Invoke($null,@($operation))
    $task.GetAwaiter().GetResult()
}
function Await-Action($operation) {
    $method=[System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and -not $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction'
    } | Select-Object -First 1
    $task=$method.Invoke($null,@($operation))
    $null=$task.GetAwaiter().GetResult()
}
$file=Await-Result ([Windows.Storage.StorageFile]::GetFileFromPathAsync($InputFile)) ([Windows.Storage.StorageFile])
$pdf=Await-Result ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])
if($Page -lt 1 -or $Page -gt $pdf.PageCount) { throw 'Page is out of range' }
$pdfPage=$pdf.GetPage($Page-1)
$stream=New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
$reader=$null
try {
    $options=New-Object Windows.Data.Pdf.PdfPageRenderOptions
    $factor=[Math]::Min(1440/$pdfPage.Size.Width,4096/$pdfPage.Size.Height)
    $options.DestinationWidth=[uint32][Math]::Max(1,[Math]::Round($pdfPage.Size.Width*$factor))
    $options.DestinationHeight=[uint32][Math]::Max(1,[Math]::Round($pdfPage.Size.Height*$factor))
    Await-Action ($pdfPage.RenderToStreamAsync($stream,$options))
    $reader=New-Object Windows.Storage.Streams.DataReader($stream.GetInputStreamAt(0))
    $null=Await-Result ($reader.LoadAsync([uint32]$stream.Size)) ([uint32])
    $bytes=New-Object byte[] $stream.Size
    $reader.ReadBytes($bytes)
    [IO.File]::WriteAllBytes($OutputFile,$bytes)
} finally {
    if($null -ne $reader) { $reader.Dispose() }
    $stream.Dispose();$pdfPage.Dispose()
}
