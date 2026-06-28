# Generate Hero console demo WebM for landing page
# Requires ffmpeg in PATH. Replace output with a real screen recording anytime.

$OutDir = Join-Path $PSScriptRoot "..\frontend\public\demo"
$OutFile = Join-Path $OutDir "console-demo.webm"

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
  Write-Host "ffmpeg not found — skip WebM generation. Hero falls back to animated canvas."
  exit 0
}

# Slow pan + subtle zoom over light UI-like gradient (placeholder until real recording)
$vf = "scale=1200:680:force_original_aspect_ratio=increase,crop=1200:680,zoompan=z='min(zoom+0.0004,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=240:s=1200x680,format=yuv420p"

ffmpeg -y `
  -f lavfi -i "color=c=f5f5f5:s=1200x680:d=8" `
  -vf "$vf" `
  -c:v libvpx-vp9 -b:v 1.2M -an `
  $OutFile

if ($LASTEXITCODE -eq 0) {
  Write-Host "Created $OutFile"
} else {
  Write-Host "ffmpeg failed — Hero will use canvas fallback."
  exit 1
}
