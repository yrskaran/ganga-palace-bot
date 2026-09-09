import os
import requests
from flask import Flask, request, jsonify
from google import genai

app = Flask(__name__)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "ganga_bot_secret_123")
ACCESS_TOKEN = os.environ.get("WHATSAPP_TOKEN") or os.environ.get("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "1357005434155447")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")

# User chat memory dictionary
chat_histories = {}

def get_hotel_context():
    try:
        with open("hotel_data.txt", "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return "Hotel Ganga Palace, Haridwar. Contact: 7500058655."

ai_client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None

def ask_ai(sender_id, user_msg):
    if not ai_client:
        return "Namaste! Front desk se connect karne ke liye kripya 7500058655 par call karein."

    if sender_id not in chat_histories:
        chat_histories[sender_id] = []

    # Pichle 15 messages ki memory
    history = chat_histories[sender_id][-15:]
    history_text = "\n".join([f"{h['role']}: {h['text']}" for h in history])

    hotel_info = get_hotel_context()

    prompt = f"""
Aap Hotel Ganga Palace ke warm aur smart virtual manager hain.
Aapko neeche di gayi hotel details ke hisaab se customer se natural, polite Hinglish me baat karni hai.

Guidelines:
1. Short & WhatsApp friendly: Lambe paragraphs mat likhein, 2-3 lines me seedha jawab dein.
2. Bold text ya stars (**) ka use mat karein. Clean normal text rakhein.
3. Natural Context: Customer ki pichli baat yaad rakhein. Agar unhone pehle room maanga tha, toh baar-baar intro mat dein. Date aur guests naturally poochhein.
4. Booking ke liye front desk number 7500058655 mention karein.

Hotel Knowledge:
{hotel_info}

Conversation So Far:
{history_text}
Customer: {user_msg}
Assistant:"""

    try:
        response = ai_client.models.generate_content(
            model='gemini-3.6-flash',
            contents=prompt
        )
        reply = response.text.replace("*", "").strip()
        
        # Memory update
        chat_histories[sender_id].append({"role": "Customer", "text": user_msg})
        chat_histories[sender_id].append({"role": "Assistant", "text": reply})
        return reply
    except Exception as e:
        print("Gemini API Error:", e)
        return "Namaste! Kripya humare reception number par call karein: 7500058655."

@app.route('/', methods=['GET'])
def home():
    return "Ganga Palace WhatsApp Bot is Live!", 200

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
                    messages = change.get('value', {}).get('messages', [])
                    for msg in messages:
                        sender_id = msg.get('from')
                        user_text = msg.get('text', {}).get('body', '')
                        if user_text:
                            reply_text = ask_ai(sender_id, user_text)
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
    requests.post(url, headers=headers, json=payload)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
