param(
    [Parameter(Mandatory = $true)][string]$IconSource,
    [Parameter(Mandatory = $true)][string]$PortraitSource
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$projectRoot = Split-Path -Parent $PSScriptRoot
$buildDirectory = Join-Path $projectRoot 'build'
$assetsDirectory = Join-Path $projectRoot 'renderer/assets'
New-Item -ItemType Directory -Force -Path $assetsDirectory | Out-Null

# Only convert formats and sizes; preserve the supplied artwork and alpha channel.
function Convert-SquarePng([System.Drawing.Image]$Source, [int]$Size) {
    $bitmap = [System.Drawing.Bitmap]::new($Size, $Size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $stream = [System.IO.MemoryStream]::new()
    try {
        $graphics.Clear([System.Drawing.Color]::Transparent)
        $graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
        $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $scale = [Math]::Min($Size / $Source.Width, $Size / $Source.Height)
        $width = [int][Math]::Round($Source.Width * $scale)
        $height = [int][Math]::Round($Source.Height * $scale)
        $graphics.DrawImage($Source, [int](($Size - $width) / 2), [int](($Size - $height) / 2), $width, $height)
        $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
        return ,$stream.ToArray()
    } finally {
        $stream.Dispose()
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

$icon = [System.Drawing.Image]::FromFile((Resolve-Path -LiteralPath $IconSource).Path)
$portrait = [System.Drawing.Image]::FromFile((Resolve-Path -LiteralPath $PortraitSource).Path)
try {
    [System.IO.File]::WriteAllBytes((Join-Path $buildDirectory 'icon.png'), (Convert-SquarePng $icon 512))
    [System.IO.File]::WriteAllBytes((Join-Path $assetsDirectory 'app-icon.png'), (Convert-SquarePng $icon 128))
    [System.IO.File]::WriteAllBytes((Join-Path $assetsDirectory 'portrait.png'), (Convert-SquarePng $portrait 512))
    $sizes = @(16, 20, 24, 32, 40, 48, 64, 128, 256)
    $frames = @($sizes | ForEach-Object { ,(Convert-SquarePng $icon $_) })
    $file = [System.IO.File]::Create((Join-Path $buildDirectory 'icon.ico'))
    $writer = [System.IO.BinaryWriter]::new($file)
    try {
        $writer.Write([uint16]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]$sizes.Count)
        $offset = 6 + 16 * $sizes.Count
        for ($i = 0; $i -lt $sizes.Count; $i++) {
            $dimension = if ($sizes[$i] -eq 256) { 0 } else { $sizes[$i] }
            $writer.Write([byte]$dimension)
            $writer.Write([byte]$dimension)
            $writer.Write([byte]0)
            $writer.Write([byte]0)
            $writer.Write([uint16]1)
            $writer.Write([uint16]32)
            $writer.Write([uint32]$frames[$i].Length)
            $writer.Write([uint32]$offset)
            $offset += $frames[$i].Length
        }
        foreach ($frame in $frames) { $writer.Write([byte[]]$frame) }
    } finally { $writer.Dispose() }
} finally {
    $icon.Dispose()
    $portrait.Dispose()
}
Write-Output 'Brand PNG assets and multi-resolution Windows icon generated.'
