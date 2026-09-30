"""Single-process production entry point (Windows/Linux)."""
import os
os.environ['BOT_AUTOSTART'] = '0'
from app import app, startup
from waitress import serve

if __name__ == '__main__':
    required = ['WHATSAPP_TOKEN', 'PHONE_NUMBER_ID', 'VERIFY_TOKEN',
                'WHATSAPP_APP_SECRET', 'GOOGLE_SERVICE_ACCOUNT_JSON', 'SHEET_ID', 'BOT_DB_PATH']
    missing = [name for name in required if not os.getenv(name, '').strip()]
    if missing:
        raise SystemExit('Missing environment settings: ' + ', '.join(missing))
    startup()
    serve(app, host='0.0.0.0', port=int(os.getenv('PORT', '10000')), threads=8)
