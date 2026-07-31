# 20U内测 - PowerShell直接发送
$headers = @{"Content-Type" = "application/json"}
$url = "https://twinstar.pro/gemini/webhook"

$signals = @(
    @{
        symbol = "ETHUSDT.P"; action = "LONG"; price = 3300; stop_loss = 3200
        tp1 = 3330; tp2 = 3360; tp3 = 3400; atr = 15; regime = 2
        bar_index = (Get-Date).ToFileTimeUtc() % 100000
        seq = (Get-Date).ToFileTimeUtc() % 10000; qty = 1; secret = "528586"
    },
    @{
        symbol = "ETHUSDT.P"; action = "SHORT"; price = 3300; stop_loss = 3400
        tp1 = 3270; tp2 = 3240; tp3 = 3200; atr = 15; regime = 2
        bar_index = (Get-Date).ToFileTimeUtc() % 100000
        seq = (Get-Date).ToFileTimeUtc() % 10000; qty = 1; secret = "528586"
    },
    @{
        symbol = "XAUUSDT.P"; action = "LONG"; price = 2380; stop_loss = 2350
        tp1 = 2390; tp2 = 2400; tp3 = 2410; atr = 12; regime = 2
        bar_index = (Get-Date).ToFileTimeUtc() % 100000
        seq = (Get-Date).ToFileTimeUtc() % 10000; qty = 1; secret = "528586"
    },
    @{
        symbol = "XAUUSDT.P"; action = "SHORT"; price = 2380; stop_loss = 2410
        tp1 = 2370; tp2 = 2360; tp3 = 2350; atr = 12; regime = 2
        bar_index = (Get-Date).ToFileTimeUtc() % 100000
        seq = (Get-Date).ToFileTimeUtc() % 10000; qty = 1; secret = "528586"
    }
)

Write-Host "=" * 50
Write-Host "20U内测 (20%保证金 x 5杠杆 = 20U名义)"
Write-Host "=" * 50

foreach ($sig in $signals) {
    Write-Host ""
    Write-Host ">>> $($sig.symbol) $($sig.action)"
    try {
        $body = $sig | ConvertTo-Json -Compress
        Write-Host "Payload: $body"
        $resp = Invoke-WebRequest -Uri $url -Method Post -Headers $headers -Body $body -TimeoutSec 15
        Write-Host "Response: $($resp.Content)"
    } catch {
        Write-Host "Error: $($_.Exception.Message)"
    }
    Start-Sleep -Seconds 3
}

Write-Host ""
Write-Host "测试完成!"
