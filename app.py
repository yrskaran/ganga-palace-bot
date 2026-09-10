import os
import re
import requests
from flask import Flask, request, jsonify
from groq import Groq

app = Flask(__name__)

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "hotel_secret_token")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

groq_client = Groq(api_key=GROQ_API_KEY)
PROCESSED_MESSAGES = set()

# Groq ka primary tested model
ACTIVE_MODEL = "llama-3.3-70b-versatile"
HOTEL_PHONE = "+91-9876543210"

def load_hotel_data():
    try:
        with open("hotel_data.txt", "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"Error loading hotel_data.txt: {e}")
        return "Hotel Ganga Palace Haridwar. Rooms available: Deluxe AC ₹1800, Super Deluxe ₹2600. Contact: " + HOTEL_PHONE

HOTEL_CONTEXT = load_hotel_data()

def mark_message_as_read(message_id):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id
    }
    try:
        requests.post(url, headers=headers, json=payload, timeout=2)
    except Exception as e:
        print(f"Read receipt error: {e}")

def clean_reply(text):
    if not text:
        return ""
    # Think tag safe removal
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    return cleaned if cleaned else text.strip()

def get_ai_reply(user_message):
    system_prompt = f"""
Aap Hotel Ganga Palace Haridwar ke polite manager 'Aman' hain.
Aapka andaz bilkul natural, humble WhatsApp human typing jaisa hona chahiye.

RULES:
1. Har jawab 1 ya 2 short sentences me dein. Hamesha 'Ji', 'Aap', aur respectful Hinglish use karein.
2. Agar guest 'Khana', 'Room', 'Rate', 'Menu' ya milta julta kuch bhi puche, toh niche diye gaye HOTEL DATA se directly polite jawab dein.
3. Agar aisi koi cheez puche jo data me bilkul NAHI hai, tabhi reception number {HOTEL_PHONE} par call karne ko kahein.
4. Kabhi apna thinking process show na karein.

HOTEL DATA:
{HOTEL_CONTEXT}
"""
    try:
        completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            model=ACTIVE_MODEL,
            temperature=0.4,
            max_tokens=250
        )
        raw_text = completion.choices[0].message.content
        print(f"--- RAW GROQ OUTPUT: '{raw_text}' ---")
        
        reply = clean_reply(raw_text)
        if reply:
            return reply
        return "Namaste ji! Hotel Ganga Palace me aapka swagat hai. Batayein kaise help kar sakta hu?"
    except Exception as e:
        print(f"--- GROQ REAL ERROR: {e} ---")
        # Agar model not found ka error aaye toh Qwen par fallback
        try:
            fallback_completion = groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                model="qwen/qwen3.6-27b",
                temperature=0.4,
                max_tokens=250
            )
            raw_fallback = fallback_completion.choices[0].message.content
            return clean_reply(raw_fallback)
        except Exception as err2:
            print(f"--- FALLBACK ALSO FAILED: {err2} ---")
            return f"Namaste ji! Front desk par call kar lijiye: {HOTEL_PHONE}"

def send_whatsapp_message(to_number, message_text):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": message_text}
    }
    try:
        requests.post(url, headers=headers, json=payload, timeout=5)
    except Exception as e:
        print(f"Send Error: {e}")

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    try:
        if data.get("entry"):
            for entry in data["entry"]:
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    if "messages" in value:
                        message = value["messages"][0]
                        msg_id = message.get("id")
                        sender_phone = message.get("from")

                        if msg_id in PROCESSED_MESSAGES:
                            return jsonify({"status": "already_processed"}), 200
                        PROCESSED_MESSAGES.add(msg_id)

                        if len(PROCESSED_MESSAGES) > 500:
                            PROCESSED_MESSAGES.clear()

                        if message.get("type") == "text":
                            incoming_text = message["text"]["body"]
                            print(f"--- INCOMING: '{incoming_text}' from {sender_phone} ---")

                            mark_message_as_read(msg_id)
                            reply_text = get_ai_reply(incoming_text)
                            print(f"--- BOT FINAL REPLY: '{reply_text}' ---")

                            send_whatsapp_message(sender_phone, reply_text)
    except Exception as err:
        print(f"Webhook Error: {err}")

    return jsonify({"status": "success"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
