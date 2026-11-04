param([Parameter(Mandatory=$true)][string]$InputFile,[Parameter(Mandatory=$true)][string]$OutputFolder,[int]$Page=0)
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
        if($shape.HasTable -eq -1) {
            # Cell.Shape.Left/Top can be zero while text bounds are slide-relative.
            # Derive cell origins from the actual table grid in the same units.
            $seenTableRanges=@{}
            $columnLefts=@();$columnPosition=[double]$shape.Left
            for($columnIndex=1;$columnIndex -le $shape.Table.Columns.Count;$columnIndex++) {
                $columnLefts+=,$columnPosition;$columnPosition+=[double]$shape.Table.Columns.Item($columnIndex).Width
            }
            $rowTops=@();$rowPosition=[double]$shape.Top
            for($rowIndex=1;$rowIndex -le $shape.Table.Rows.Count;$rowIndex++) {
                $rowTops+=,$rowPosition;$rowPosition+=[double]$shape.Table.Rows.Item($rowIndex).Height
            }
            for($row=1;$row -le $shape.Table.Rows.Count;$row++) {
                for($col=1;$col -le $shape.Table.Columns.Count;$col++) {
                    try {
                        $cell=$shape.Table.Cell($row,$col).Shape;$range=$cell.TextFrame.TextRange
                        if(!$range.Text.Trim()){continue}
                        # Covered merged cells may expose the exact origin text range again.
                        $boundLeft=[double]$range.BoundLeft;$boundTop=[double]$range.BoundTop
                        $boundWidth=[double]$range.BoundWidth;$boundHeight=[double]$range.BoundHeight
                        $rangeKey=[string]::Join('|',@($boundLeft,$boundTop,$boundWidth,$boundHeight,$range.Text))
                        if($seenTableRanges.ContainsKey($rangeKey)){continue}
                        $seenTableRanges[$rangeKey]=$true
                        $values+=@{id=([string]$shape.Id+'/'+$row+'/'+$col);shape_id=[int]$shape.Id;row=$row-1;col=$col-1;
                            x=[double]$columnLefts[$col-1];y=[double]$rowTops[$row-1];width=[double]$cell.Width;height=[double]$cell.Height;
                            bound_x=$boundLeft;bound_y=$boundTop;bound_width=$boundWidth;bound_height=$boundHeight}
                    }catch{}
                }
            }
            continue
        }
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
    $security=$application.AutomationSecurity
    $application.AutomationSecurity=3
    # ReadOnly, no untitled copy and no presentation window. Never save the source.
    $deck=$application.Presentations.Open([IO.Path]::GetFullPath($InputFile),-1,0,0)
    $application.AutomationSecurity=$security
    if($Page -lt 0 -or $Page -gt $deck.Slides.Count) { throw 'Invalid page' }
    $null=New-Item -ItemType Directory -Path $OutputFolder -Force
    $width=1280
    $height=[int][Math]::Round($width*$deck.PageSetup.SlideHeight/$deck.PageSetup.SlideWidth)
    $pages=@()
    $progressFile=Join-Path $OutputFolder 'progress.json'
    [IO.File]::WriteAllText($progressFile,(@{done=0;total=$deck.Slides.Count}|ConvertTo-Json -Compress),[Text.UTF8Encoding]::new($false))
    $first=1;$last=$deck.Slides.Count
    if($Page -gt 0) { $first=$Page;$last=$Page }
    for($number=$first;$number -le $last;$number++) {
        if(Test-Path -LiteralPath (Join-Path $OutputFolder 'cancel')) { throw 'Cancelled' }
        $slide=$deck.Slides.Item($number)
        $file="page-$number.png"
        $slide.Export((Join-Path $OutputFolder $file),'PNG',$width,$height)
        $pages+=@{file=$file;shapes=@(Read-TextShapes $slide.Shapes)}
        [IO.File]::WriteAllText($progressFile,(@{done=$number;total=$deck.Slides.Count}|ConvertTo-Json -Compress),[Text.UTF8Encoding]::new($false))
    }
    $manifest=@{pages=$pages;native=$true;total=$deck.Slides.Count}|ConvertTo-Json -Depth 8 -Compress
    [IO.File]::WriteAllText((Join-Path $OutputFolder 'manifest.json'),$manifest,[Text.UTF8Encoding]::new($false))
} finally {
    if($null -ne $deck) { $deck.Close();[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($deck) }
    if($null -ne $application) {
        if($null -ne $security) { $application.AutomationSecurity=$security }
        if($existing -eq 0 -and $application.Presentations.Count -eq 0) { $application.Quit() }
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($application)
    }
    if($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
