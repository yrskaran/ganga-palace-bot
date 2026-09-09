import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

VERIFY_TOKEN = "ganga_bot_secret_123"
ACCESS_TOKEN = "EAAcF7hlfsRQBSZA01hZCQyvBPULJ1B4CSIgvNT0Uv9BG1Kwu0SAJQweZCf2m65WeNIcx7nl9Es97SckC0QDMQSu0dINxTwDsexZAKzcQjPKXoFOBBETdGomRJpwdFiNduIIa2LZAZCQ4kl3HNqqTnvl70ufkBIjryCK2FFN70HWDvraL91ptZCZAg9CXWZAUAlLblPWvM7ZBRm0uqKJ76dmenjiZAIOugtEqKdHcryM05Vq4GiNBrx63nr60OQn2xhinTZBvFszugHulfTWB81Qg1AuVugZDZD"
PHONE_NUMBER_ID = "1357005434155447"

@app.route('/', methods=['GET'])
def home():
    return "Ganga Palace WhatsApp Bot is Live!", 200

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    # Webhook Verification (Meta GET request)
    if request.method == 'GET':
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')

        if mode == 'subscribe' and token == VERIFY_TOKEN:
            return challenge, 200
        return 'Verification failed', 403

    # Message Handling (Meta POST request)
    if request.method == 'POST':
        data = request.get_json()
        print("Incoming Webhook Data:", data)

        try:
            entries = data.get('entry', [])
            for entry in entries:
                changes = entry.get('changes', [])
                for change in changes:
                    value = change.get('value', {})
                    messages = value.get('messages', [])
                    
                    for msg in messages:
                        sender_id = msg.get('from')
                        user_text = msg.get('text', {}).get('body', '').lower()

                        print(f"Message from {sender_id}: {user_text}")

                        # Bot reply logic
                        reply_text = "Namaste! Welcome to Hotel Ganga Palace, Haridwar.\n\nHow can we help you today?\n1. Room Tariffs & Availability\n2. Location & Directions\n3. Ghat Distance & Aarti Timings\n\nPlease reply with a number or your query."

                        send_whatsapp_message(sender_id, reply_text)

        except Exception as e:
            print(f"Error handling message: {e}")

        return jsonify({"status": "success"}), 200

def send_whatsapp_message(to_number, text):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
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
    print("Meta API Response:", res.status_code, res.text)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
