import os
import requests
from flask import Flask, request, jsonify
from groq import Groq

app = Flask(__name__)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "ganga_bot_secret_123")
ACCESS_TOKEN = os.environ.get("WHATSAPP_TOKEN") or os.environ.get("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "1357005434155447")
GROQ_KEY = os.environ.get("GROQ_API_KEY")

processed_msg_ids = set()
chat_histories = {}

try:
    with open("hotel_data.txt", "r", encoding="utf-8") as f:
        HOTEL_INFO = f.read()
except Exception:
    HOTEL_INFO = "Hotel Ganga Palace, Haridwar. Phone: 7500058655."

groq_client = Groq(api_key=GROQ_KEY) if GROQ_KEY else None

SYSTEM_INSTRUCTION = f"""
Aap Hotel Ganga Palace (Haridwar) ke real reception manager hain. Aap WhatsApp par guests se seedhi, polite aur natural Hinglish me baat karte hain.

RULES:
1. Short & Crisp: WhatsApp par lamba menu ya paragraph mat bhejien. Har jawab sirf 1 ya 2 lines me hona chahiye.
2. Step-by-Step Baat:
   - Pehli baar guest puche 'room chahiye' ya 'available hai?': Seedha arrival date aur total guests poochhein (e.g. 'Ji bilkul sir! Aap kis date ke liye plan kar rahe hain aur kitne log hain?').
   - Price tabhi batayein jab guest maange: Deluxe AC Rs. 2,000 | Super Deluxe AC Rs. 2,800.
   - Advance booking ke liye front desk number 7500058655 mention karein.
3. No Formatting Junk: Kisi text me stars (*), hashtags (#), ya bullets use mat karein. Bilkul normal text bhejein.

HOTEL DATA:
{HOTEL_INFO}
"""

def ask_ai(sender_id, user_msg):
    if not groq_client:
        return "Namaste! Front desk se connect karne ke liye 7500058655 par call karein."

    if sender_id not in chat_histories:
        chat_histories[sender_id] = []

    chat_histories[sender_id].append({"role": "user", "content": user_msg})
    # Pichle 10 messages ki memory
    recent_history = chat_histories[sender_id][-10:]

    payload = [{"role": "system", "content": SYSTEM_INSTRUCTION}]
    payload.extend(recent_history)

    try:
        completion = groq_client.chat.completions.create(
            model="llama3-8b-8192",
            messages=payload,
            temperature=0.3,
            max_tokens=150
        )
        reply = completion.choices[0].message.content.replace("*", "").replace("#", "").strip()
        chat_histories[sender_id].append({"role": "assistant", "content": reply})
        return reply
    except Exception as e:
        print("Groq Error:", e)
        return "Namaste! Front desk se connect karne ke liye kripya 7500058655 par call karein."

@app.route('/', methods=['GET'])
def home():
    return "Ganga Palace Bot running on Groq (Llama-3.3-70B)!", 200

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')
        if mode == 'subscribe' and token == VERIFY_TOKEN:
            return challenge, 200
        return 'Verification failed', 403

    if request.method == 'POST':
        data = request.get_json()
        try:
            for entry in data.get('entry', []):
                for change in entry.get('changes', []):
                    val = change.get('value', {})
                    for msg in val.get('messages', []):
                        msg_id = msg.get('id')
                        if msg_id in processed_msg_ids:
                            continue
                        processed_msg_ids.add(msg_id)
                        if len(processed_msg_ids) > 1000:
                            processed_msg_ids.clear()

                        sender_id = msg.get('from')
                        if msg.get('type') == 'text':
                            user_text = msg.get('text', {}).get('body', '').strip()
                            if user_text:
                                reply = ask_ai(sender_id, user_text)
                                send_whatsapp_message(sender_id, reply)
        except Exception as e:
            print(f"Webhook processing error: {e}")
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
    requests.post(url, headers=headers, json=payload)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
