SELECT u.id, u.username, a.exchange, a.api_key_masked, b.id as bot_id, b.symbol, b.status
FROM users u 
JOIN accounts a ON u.id = a.user_id 
JOIN bots b ON u.id = b.user_id 
WHERE u.id = 6;
