# VPS Deployment Script
$env:SSH_ASKPASS_REQUIRE = "never"

$commands = @(
    "cd ~/panda-quant-platform",
    "git log -3 --oneline",
    "echo '--- git status ---'",
    "git status --short | Select-Object -First 10",
    "echo '--- Docker containers ---'",
    "docker compose ps 2>&1 | Select-Object -First 10"
)

$command = $commands -join " && "

# Execute SSH with password using a temporary script
$sshScript = @"
set timeout 60
spawn ssh -o StrictHostKeyChecking=acceptnew -o ConnectTimeout=30 root@187.77.130.144 `"$command`"
expect `"password:`"
send `"w'tFzgg2vPZ0D,Z;\r`"
expect eof
"@

# Write expect script to temp file
$tempScript = "$env:TEMP\deploy_vps_$(Get-Random).expect"
Set-Content -Path $tempScript -Value $sshScript -Encoding ASCII

try {
    # Check if expect is available
    $expectPath = (Get-Command expect -ErrorAction SilentlyContinue).Source
    if ($expectPath) {
        & expect $tempScript
    } else {
        Write-Host "expect not found, trying with SSH key..."
        # Try SSH key approach or manual instructions
        ssh -o StrictHostKeyChecking=acceptnew -o ConnectTimeout=30 -o PasswordAuthentication=yes root@187.77.130.144 $command
    }
} finally {
    Remove-Item $tempScript -ErrorAction SilentlyContinue
}
