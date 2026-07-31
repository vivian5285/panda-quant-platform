# 20U内测 - 用curl发送
Write-Host "=" * 50
Write-Host "20U内测 (20%保证金 x 5杠杆 = 20U名义)"
Write-Host "=" * 50

$signals = @(
    @{symbol = "ETHUSDT.P"; action = "LONG";  price = 3300; stop_loss = 3200; tp1 = 3330; tp2 = 3360; tp3 = 3400; atr = 15},
    @{symbol = "ETHUSDT.P"; action = "SHORT"; price = 3300; stop_loss = 3400; tp1 = 3270; tp2 = 3240; tp3 = 3200; atr = 15},
    @{symbol = "XAUUSDT.P"; action = "LONG";  price = 2380; stop_loss = 2350; tp1 = 2390; tp2 = 2400; tp3 = 2410; atr = 12},
    @{symbol = "XAUUSDT.P"; action = "SHORT"; price = 2380; stop_loss = 2410; tp1 = 2370; tp2 = 2360; tp3 = 2350; atr = 12}
)

foreach ($sig in $signals) {
    Write-Host ""
    Write-Host ">>> $($sig.symbol) $($sig.action)"

    $payload = @{
        symbol = $sig.symbol
        action = $sig.action
        secret = "528586"
        price = $sig.price
        stop_loss = $sig.stop_loss
        tp1 = $sig.tp1
        tp2 = $sig.tp2
        tp3 = $sig.tp3
        atr = $sig.atr
        regime = 2
        bar_index = [int64](Get-Date).ToFileTimeUtc() % 100000
        seq = [int64](Get-Date).ToFileTimeUtc() % 10000
        qty = 1
    }

    $body = $payload | ConvertTo-Json -Compress
    Write-Host "Payload: $body"

    # 用curl发送
    $result = curl -X POST "https://twinstar.pro/gemini/webhook" -H "Content-Type: application/json" -d $body --connect-timeout 10 --max-time 20 2>&1
    Write-Host "Response: $result"

    Start-Sleep -Seconds 3
}

Write-Host ""
Write-Host "测试完成!"
