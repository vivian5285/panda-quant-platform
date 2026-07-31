ssh -o StrictHostKeyChecking=no root@187.77.130.144 "sudo tail -500 /var/log/nginx/access.log | grep -E 'webhook|gemini' | tail -50"
