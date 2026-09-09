import os
import requests
from flask import Flask, request, jsonify
from google import genai
from google.genai import types

app = Flask(__name__)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "ganga_bot_secret_123")
ACCESS_TOKEN = os.environ.get("WHATSAPP_TOKEN") or os.environ.get("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "1357005434155447")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")

# Processed message IDs (duplicate webhook drop karne ke liye)
processed_msg_ids = set()

# Native Gemini Chat sessions per user
chat_sessions = {}

try:
    with open("hotel_data.txt", "r", encoding="utf-8") as f:
        HOTEL_INFO = f.read()
except Exception:
    HOTEL_INFO = "Hotel Ganga Palace, Haridwar. Contact: 7500058655."

ai_client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None

SYSTEM_INSTRUCTION = f"""
Aap Hotel Ganga Palace (Haridwar) ke front desk manager hain.
Aapka mission ek real polite receptionist ki tarah 1-to-1 natural chat karna hai.

CRITICAL RULES:
1. Short Chat: WhatsApp par lambe bhashan ya poori menu list bilkul mat bhejein. Har reply sirf 1 ya 2 lines ka hona chahiye.
2. Step-by-Step Baat Karein:
   - Pehli baar guest puche "Room milega?": Sirf itna bolein: "Ji bilkul sir! Aap kis date ke liye plan kar rahe hain aur kitne log hain?" (Rates pehle se mat batao).
   - Jab guest date/log bataye ya specific room rate puche: Tabhi rate batao (Deluxe Rs. 2000, Super Deluxe Rs. 2800).
   - Booking ke liye: Front desk number 7500058655 par call ya WhatsApp karke advance dene ko bolein.
3. Clean Text: Stars (*), bold (**), ya bullet points bilkul mat lagana. Normal WhatsApp chat text likho.
4. Tone: Humble Hindi/Hinglish (e.g., "Ji sir", "Haanji bilkul").

HOTEL DATA:
{HOTEL_INFO}
"""

def get_or_create_chat(sender_id):
    if sender_id not in chat_sessions:
        chat_sessions[sender_id] = ai_client.chats.create(
            model="gemini-3.6-flash",
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.2,
                max_output_tokens=100
            )
        )
    return chat_sessions[sender_id]

def ask_ai(sender_id, user_msg):
    if not ai_client:
        return "Namaste! Front desk se connect karne ke liye 7500058655 par sampark karein."
    try:
        chat = get_or_create_chat(sender_id)
        response = chat.send_message(user_msg)
        reply = response.text.replace("*", "").replace("#", "").strip()
        return reply
    except Exception as e:
        print("Gemini Chat Error:", e)
        # Session reset on error
        chat_sessions.pop(sender_id, None)
        return "Namaste! Front desk se connect karne ke liye 7500058655 par sampark karein."

@app.route('/', methods=['GET'])
def home():
    return "Ganga Palace WhatsApp Bot is Running!", 200

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
                    value = change.get('value', {})
                    messages = value.get('messages', [])
                    for msg in messages:
                        msg_id = msg.get('id')
                        # Duplicate prevention
                        if msg_id in processed_msg_ids:
                            continue
                        processed_msg_ids.add(msg_id)
                        if len(processed_msg_ids) > 1000:
                            processed_msg_ids.clear()

                        sender_id = msg.get('from')
                        # Sirf real user text messages handle karein
                        if msg.get('type') == 'text':
                            user_text = msg.get('text', {}).get('body', '').strip()
                            if user_text:
                                reply_text = ask_ai(sender_id, user_text)
                                send_whatsapp_message(sender_id, reply_text)
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
