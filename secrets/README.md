# Docker Secrets

Place secret files here with 600 permissions:

- `postgres_password.txt` - PostgreSQL password
- `telegram_bot_token.txt` - Telegram Bot Token
- `telegram_api_hash.txt` - Telegram API Hash
- `amazon_tag.txt` - Amazon Associate Tag
- `mercadolivre_tag.txt` - Mercado Livre Tag
- `shopee_app_id.txt` - Shopee App ID
- `shopee_tag.txt` - Shopee Tag

Example:
```bash
echo "your_secure_password" > postgres_password.txt
chmod 600 postgres_password.txt
```
