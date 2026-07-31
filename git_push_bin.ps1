$ErrorActionPreference = "Continue"
$RepoDir = "C:\Users\Administrator\Desktop\panda-quant-platform"
Set-Location $RepoDir
Write-Host "Git add..."
git add backend/app/core/binance_client.py
Write-Host "Git commit..."
git commit -m "fix: replace force_refresh with ensure_fresh in binance_client.estimate_atr"
if ($LASTEXITCODE -ne 0) { Write-Host "Commit failed: $LASTEXITCODE"; exit 1 }
Write-Host "Git push..."
git push
if ($LASTEXITCODE -ne 0) { Write-Host "Push failed"; exit 1 }
Write-Host "All done!"
