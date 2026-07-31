ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@187.77.130.144 "sudo tail -500 /var/log/nginx/access.log | Select-String -Pattern 'webhook|gemini' | Select-Object -Last 50"
