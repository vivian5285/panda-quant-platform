$ErrorActionPreference = "Continue"
$RepoDir = "C:\Users\Administrator\Desktop\panda-quant-platform"
Write-Host "Starting git push..."
Set-Location $RepoDir
git add backend/app/core/adverse_radar_guard.py
if ($LASTEXITCODE -ne 0) { Write-Host "git add failed"; exit 1 }
Write-Host "Git add done"
git commit -m "fix: remove force_refresh circular import - use ensure_fresh"
if ($LASTEXITCODE -ne 0) { Write-Host "git commit failed"; exit 1 }
Write-Host "Git commit done"
git push
if ($LASTEXITCODE -ne 0) { Write-Host "git push failed"; exit 1 }
Write-Host "Git push done"
