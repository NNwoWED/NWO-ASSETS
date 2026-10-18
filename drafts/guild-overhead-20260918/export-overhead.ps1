param([string]$Atlas = (Join-Path $PSScriptRoot 'atlas-generated.png'))
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$out = Join-Path $PSScriptRoot 'overhead'
[IO.Directory]::CreateDirectory($out) | Out-Null
$source = [Drawing.Bitmap]::new($Atlas)
$palette = @('#171b24','#343844','#72501d','#ac751d','#e6aa38','#ffdb72','#fff1be',
  '#703016','#b95e12','#edaa0c','#870e21','#c5192a','#f53d3f',
  '#09576a','#008eaa','#17c4d2','#1d1668','#4621ad','#8639df',
  '#142458','#214eae','#4281ed','#194521','#28782d','#4daf3e',
  '#b5aea0','#eee8d2','#fff8e5') | ForEach-Object { [Drawing.ColorTranslator]::FromHtml($_) }
$outline = [Drawing.ColorTranslator]::FromHtml('#171b24')
$manifest = @()
function Export-Sprite([string]$Name, [int]$X, [int]$Y, [int]$Width, [int]$Height, [int]$Fit) {
  $left = $X + $Width; $right = $X; $top = $Y + $Height; $bottom = $Y
  for ($y1=$Y; $y1 -lt [Math]::Min($Y+$Height,$source.Height); $y1++) {
    for ($x1=$X; $x1 -lt [Math]::Min($X+$Width,$source.Width); $x1++) {
      if ($source.GetPixel($x1,$y1).A -ge 220) {
        $left=[Math]::Min($left,$x1); $right=[Math]::Max($right,$x1)
        $top=[Math]::Min($top,$y1); $bottom=[Math]::Max($bottom,$y1)
      }
    }
  }
  if ($right -le $left -or $bottom -le $top) { throw "Empty crop: $Name" }
  $scale = [Math]::Min($Fit/($right-$left+1),$Fit/($bottom-$top+1))
  $w=[Math]::Max(1,[int][Math]::Round(($right-$left+1)*$scale))
  $h=[Math]::Max(1,[int][Math]::Round(($bottom-$top+1)*$scale))
  $dx=[int][Math]::Floor((18-$w)/2); $dy=[int][Math]::Floor((18-$h)/2)
  $sprite=[Drawing.Bitmap]::new(18,18,[Drawing.Imaging.PixelFormat]::Format32bppArgb)
  # Native pixel sampling only: no smoothing, resampling filter, or partial alpha.
  for ($y1=0; $y1 -lt $h; $y1++) {
    for ($x1=0; $x1 -lt $w; $x1++) {
      $sx=$left+[int][Math]::Floor(($x1+0.5)*($right-$left+1)/$w)
      $sy=$top+[int][Math]::Floor(($y1+0.5)*($bottom-$top+1)/$h)
      $pixel=$source.GetPixel($sx,$sy)
      if ($pixel.A -lt 220) { continue }
      $best=$outline; $distance=[double]::MaxValue
      foreach ($color in $palette) {
        $d=[Math]::Pow($pixel.R-$color.R,2)+[Math]::Pow($pixel.G-$color.G,2)+[Math]::Pow($pixel.B-$color.B,2)
        if ($d -lt $distance) { $distance=$d; $best=$color }
      }
      $sprite.SetPixel($dx+$x1,$dy+$y1,$best)
    }
  }
  $final=[Drawing.Bitmap]::new(18,18,[Drawing.Imaging.PixelFormat]::Format32bppArgb)
  for ($y1=0; $y1 -lt 18; $y1++) {
    for ($x1=0; $x1 -lt 18; $x1++) {
      if ($sprite.GetPixel($x1,$y1).A -eq 0) { continue }
      foreach ($step in @(@(-1,0),@(1,0),@(0,-1),@(0,1))) {
        $nx=$x1+$step[0]; $ny=$y1+$step[1]
        if ($nx -ge 0 -and $nx -lt 18 -and $ny -ge 0 -and $ny -lt 18) { $final.SetPixel($nx,$ny,$outline) }
      }
    }
  }
  for ($y1=0; $y1 -lt 18; $y1++) {
    for ($x1=0; $x1 -lt 18; $x1++) {
      $pixel=$sprite.GetPixel($x1,$y1)
      if ($pixel.A -gt 0) { $final.SetPixel($x1,$y1,$pixel) }
    }
  }
  $path=Join-Path $out $Name
  $final.Save($path,[Drawing.Imaging.ImageFormat]::Png)
  $sprite.Dispose(); $final.Dispose()
  $script:manifest += [ordered]@{name=$Name; crop=@($X,$Y,$Width,$Height); bounds=@($left,$top,$right,$bottom); size=18; sha256=(Get-FileHash $path -Algorithm SHA256).Hash}
}
try {
  for ($shape=1; $shape -le 4; $shape++) {
    for ($color=1; $color -le 6; $color++) {
      Export-Sprite "banner-base-$shape-$color.png" (22+($color-1)*200) (($shape-1)*200) 200 200 16
    }
  }
  for ($logo=1; $logo -le 8; $logo++) {
    $x=[int][Math]::Floor(($logo-1)*$source.Width/8)
    $right=[int][Math]::Floor($logo*$source.Width/8)
    Export-Sprite "banner-logo-$logo.png" $x 800 ($right-$x) ($source.Height-800) 10
  }
} finally { $source.Dispose() }
$manifest | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $PSScriptRoot 'manifest.json') -Encoding UTF8

# All 192 combinations, both at 1:1 and enlarged without interpolation.
$sheet=[Drawing.Bitmap]::new(24*24,8*24,[Drawing.Imaging.PixelFormat]::Format32bppArgb)
$graphics=[Drawing.Graphics]::FromImage($sheet)
$graphics.Clear([Drawing.ColorTranslator]::FromHtml('#414956'))
for ($shape=1; $shape -le 4; $shape++) {
  for ($color=1; $color -le 6; $color++) {
    $base=[Drawing.Bitmap]::new((Join-Path $out "banner-base-$shape-$color.png"))
    for ($logo=1; $logo -le 8; $logo++) {
      $symbol=[Drawing.Bitmap]::new((Join-Path $out "banner-logo-$logo.png"))
      $x=(($shape-1)*6+$color-1)*24+3; $y=($logo-1)*24+3
      $graphics.DrawImageUnscaled($base,$x,$y); $graphics.DrawImageUnscaled($symbol,$x,$y)
      $symbol.Dispose()
    }
    $base.Dispose()
  }
}
$graphics.Dispose()
$sheet.Save((Join-Path $PSScriptRoot 'all-combinations-1x.png'),[Drawing.Imaging.ImageFormat]::Png)
$large=[Drawing.Bitmap]::new($sheet.Width*3,$sheet.Height*3,[Drawing.Imaging.PixelFormat]::Format32bppArgb)
for($y=0;$y -lt $large.Height;$y++) { for($x=0;$x -lt $large.Width;$x++) {
  $large.SetPixel($x,$y,$sheet.GetPixel([int][Math]::Floor($x/3),[int][Math]::Floor($y/3)))
} }
$large.Save((Join-Path $PSScriptRoot 'all-combinations-3x.png'),[Drawing.Imaging.ImageFormat]::Png)
$sheet.Dispose(); $large.Dispose()
Write-Output "Exported $($manifest.Count) RGBA icons; all 192 combinations rendered."
