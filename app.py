import os
import requests
from flask import Flask, request, jsonify
from google import genai
from google.genai import types

app = Flask(__name__)

# Environment variables
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "ganga_bot_secret_123")
ACCESS_TOKEN = os.environ.get("WHATSAPP_TOKEN") or os.environ.get("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "1357005434155447")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")

# Memory store (phone_number -> list of messages)
chat_histories = {}

# Server startup par hotel details load karna
try:
    with open("hotel_data.txt", "r", encoding="utf-8") as f:
        HOTEL_INFO = f.read()
except Exception:
    HOTEL_INFO = "Hotel Ganga Palace, Haridwar. Contact: 7500058655."

ai_client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None

SYSTEM_PROMPT = f"""
Aap Hotel Ganga Palace (Haridwar) ke real aur humble front-desk receptionist hain.
Aapka mission ek real human ki tarah helpful aur polite rehna hai.

STRICT CONVERSATION RULES:
1. Short & Crisp: WhatsApp par lambe essay bilkul nahi likhne. Max 1-3 lines me seedha reply karein.
2. Step-by-Step Flow:
   - Agar guest pooche "Room milega?": Seedha bolen "Ji bilkul! Aap kis date ke liye dekh rahe hain aur kitne log hain?" (Pehle se poori rate list mat chipkayein).
   - Agar guest specific room tariff pooche: Tabhi price batayein (Deluxe Rs. 2000, Super Deluxe Rs. 2800) aur poochein unhe konsa chahiye.
   - Advance Booking ke liye: Unhe front desk number 7500058655 par call ya direct payment karne ko kahein.
3. No Formatting Junk: Stars (*), bold tags ya hashtags bilkul mat lagayein. Plain readable text rakhein.
4. Tone: Humble Hinglish/Hindi (jaise: "Ji sir", "Haanji bilkul").

HOTEL DATA:
{HOTEL_INFO}
"""

def ask_ai(sender_id, user_msg):
    if not ai_client:
        return "Namaste! Front desk se connect karne ke liye kripya 7500058655 par call karein."

    if sender_id not in chat_histories:
        chat_histories[sender_id] = []

    # Pichle 12 messages maintain karna
    history = chat_histories[sender_id][-12:]
    history_text = "\n".join([f"{h['role']}: {h['text']}" for h in history])

    user_query = f"Previous conversation:\n{history_text}\nGuest: {user_msg}\nReceptionist reply:"

    try:
        response = ai_client.models.generate_content(
            model='gemini-3.6-flash',
            contents=user_query,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.3,
                max_output_tokens=150
            )
        )
        reply = response.text.replace("*", "").replace("#", "").strip()

        # Update chat memory
        chat_histories[sender_id].append({"role": "Guest", "text": user_msg})
        chat_histories[sender_id].append({"role": "Receptionist", "text": reply})
        return reply
    except Exception as e:
        print("Gemini API Error:", e)
        return "Namaste! Front desk se baat karne ke liye kripya 7500058655 par call karein."

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
