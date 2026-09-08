from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# Credentials
VERIFY_TOKEN = "ganga_palace_secure_token"
ACCESS_TOKEN = "EAAcF7hlfsRQBSRFWVx8RWH5jmotItREJUN9OFqlbxprh5sgCejCFbVmtj76XIeoetkNE8wgWx7kYncRcl3uJY3uLxXuOOnZAsaocSzq5cpuf0x71xPVCulNtQQ9sYRbRRKiQ325C4pp2EglKEG4UPWOstiQEFlTWcrVVZAzKUZCdj4dI435K1K4NW1ByJERrMPxLZAZAizXOQiFdM6ZBCs8gidu8dW66OYZAZA9ZC6QKfmLQEr7d5BzY4ZAkyJzh3slboeCzQg3lGF7gVRZAXGEDq71"
PHONE_NUMBER_ID = "1357005434155447"

@app.route('/webhook', methods=['GET'])
def verify():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')

    if mode and token:
        if mode == 'subscribe' and token == VERIFY_TOKEN:
            return str(challenge), 200
        return 'Verification token mismatch', 403
    return 'Hello Webhook', 200

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    try:
        if data.get('entry'):
            for entry in data['entry']:
                for change in entry.get('changes', []):
                    value = change.get('value', {})
                    messages = value.get('messages', [])
                    if messages:
                        msg = messages[0]
                        sender = msg.get('from')
                        text = msg.get('text', {}).get('body', '')
                        print(f"[WhatsApp Incoming] {sender}: {text}")
                        
                        # Hotel automated reply
                        reply = "Namaste! Hotel Ganga Palace, Haridwar mein aapka swagat hai. Room booking ya inquiry ke liye batayein, hum aapki kya sahayata kar sakte hain?"
                        send_whatsapp_message(sender, reply)
    except Exception as e:
        print(f"Error handling incoming message: {e}")
    return jsonify({'status': 'EVENT_RECEIVED'}), 200

def send_whatsapp_message(to_number, text):
    url = f"https://graph.facebook.com/v25.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": text}
    }
    res = requests.post(url, headers=headers, json=payload)
    print(f"[Send Status]: {res.status_code} - {res.text}")

if __name__ == '__main__':
    print("[+] Haridwar Hotel Ganga Palace WhatsApp Server Starting...")
    app.run(host='0.0.0.0', port=5000, debug=False)