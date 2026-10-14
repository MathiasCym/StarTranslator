param([Parameter(Mandatory=$true)][string]$InputFile,[Parameter(Mandatory=$true)][string]$OutputFolder)
$ErrorActionPreference='Stop'
$application=$null
$deck=$null
$existing=1
$mutex=New-Object System.Threading.Mutex($false,'Local\StarTranslatorPptxRender')
$locked=$false
function Read-TextShapes($items) {
    $values=@()
    foreach($shape in $items) {
        if($shape.Type -eq 6) { $values+=@(Read-TextShapes $shape.GroupItems);continue }
        if($shape.HasTextFrame -eq -1 -and $shape.TextFrame.HasText -eq -1) {
            $range=$shape.TextFrame.TextRange
            $values+=@{id=[int]$shape.Id;x=[double]$shape.Left;y=[double]$shape.Top;width=[double]$shape.Width;height=[double]$shape.Height;
                bound_x=[double]$range.BoundLeft;bound_y=[double]$range.BoundTop;bound_width=[double]$range.BoundWidth;bound_height=[double]$range.BoundHeight}
        }
    }
    return $values
}
try {
    while(-not $locked) {
        try { $locked=$mutex.WaitOne(500) } catch [System.Threading.AbandonedMutexException] { $locked=$true }
        if(Test-Path -LiteralPath (Join-Path $OutputFolder 'cancel')) { throw 'Cancelled' }
    }
    $application=New-Object -ComObject PowerPoint.Application
    $existing=$application.Presentations.Count
    # ReadOnly, no untitled copy and no presentation window. Never save the source.
    $deck=$application.Presentations.Open([IO.Path]::GetFullPath($InputFile),-1,0,0)
    $null=New-Item -ItemType Directory -Path $OutputFolder -Force
    $width=1280
    $height=[int][Math]::Round($width*$deck.PageSetup.SlideHeight/$deck.PageSetup.SlideWidth)
    $pages=@()
    for($number=1;$number -le $deck.Slides.Count;$number++) {
        if(Test-Path -LiteralPath (Join-Path $OutputFolder 'cancel')) { throw 'Cancelled' }
        $slide=$deck.Slides.Item($number)
        $file="page-$number.png"
        $slide.Export((Join-Path $OutputFolder $file),'PNG',$width,$height)
        $pages+=@{file=$file;shapes=@(Read-TextShapes $slide.Shapes)}
    }
    $manifest=@{pages=$pages;native=$true}|ConvertTo-Json -Depth 8 -Compress
    [IO.File]::WriteAllText((Join-Path $OutputFolder 'manifest.json'),$manifest,[Text.UTF8Encoding]::new($false))
} finally {
    if($null -ne $deck) { $deck.Close();[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($deck) }
    if($null -ne $application) {
        if($existing -eq 0 -and $application.Presentations.Count -eq 0) { $application.Quit() }
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($application)
    }
    if($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
