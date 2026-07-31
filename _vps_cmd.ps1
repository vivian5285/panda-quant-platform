ssh root@187.77.130.144 "ssh srv1738754 'sudo tail -500 /var/log/nginx/access.log'" | Out-String | Select-Object -Last 100
