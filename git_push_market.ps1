$ErrorActionPreference = "Continue"
Set-Location "C:\Users\Administrator\Desktop\panda-quant-platform"
Write-Host "Git add..."
git add backend/app/core/market_engine.py
Write-Host "Git status..."
git status --short
Write-Host "Git commit..."
git commit -m "fix: add force_refresh=ensure_fresh alias for backward compat + remove dead import"
if ($LASTEXITCODE -ne 0) { Write-Host "Commit failed"; exit 1 }
Write-Host "Git push..."
git push
if ($LASTEXITCODE -ne 0) { Write-Host "Push failed"; exit 1 }
Write-Host "Push done!"
