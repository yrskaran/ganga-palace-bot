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

ACTIVE_MODEL = "qwen/qwen3.6-27b"

def clean_reply(text):
    if not text:
        return ""
    # Agar closing </think> tag hai, toh uske baad ka actual answer uthao
    if "</think>" in text:
        text = text.split("</think>")[-1].strip()
    # Agar model token limit ki wajah se beech me hi ruk gaya aur </think> nahi aaya
    elif "<think>" in text:
        text = text.split("<think>")[0].strip()
        
    return text.strip()

def get_ai_reply(user_message):
    system_prompt = (
        "Aap Hotel Ganga Palace Haridwar ke digital concierge hain. "
        "Guest ke sawal ka short, polite aur helpful Hinglish me reply karein. "
        "Deluxe AC: ₹2000/night, Super Deluxe: ₹2800/night. "
        "Location: Har Ki Pauri se 500m door. Check-in: 12 PM, Check-out: 11 AM."
    )
    
    try:
        completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            model=ACTIVE_MODEL,
            temperature=0.3,
            max_tokens=600  # Token limit badha di taaki actual answer cut na ho
        )
        raw_output = completion.choices[0].message.content
        reply = clean_reply(raw_output)
        
        if not reply:
            reply = "Namaste! Hotel Ganga Palace Haridwar me aapka swagat hai. Ji haan, hamare paas Deluxe aur Super Deluxe rooms available hain."
            
        return reply
    except Exception as e:
        print(f"--- GROQ REAL ERROR: {e} ---")
        return "Namaste! Hotel Ganga Palace me aapka swagat hai. Kripya batayein aapko room booking ya kisi service me sahayata chahiye?"

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
                        sender_phone = message["from"]

                        if msg_id in PROCESSED_MESSAGES:
                            return jsonify({"status": "already_processed"}), 200
                        PROCESSED_MESSAGES.add(msg_id)

                        if len(PROCESSED_MESSAGES) > 500:
                            PROCESSED_MESSAGES.clear()

                        if message.get("type") == "text":
                            incoming_text = message["text"]["body"]
                            print(f"--- INCOMING: '{incoming_text}' from {sender_phone} ---")

                            reply_text = get_ai_reply(incoming_text)
                            print(f"--- BOT FINAL REPLY: '{reply_text}' ---")

                            send_whatsapp_message(sender_phone, reply_text)
    except Exception as err:
        print(f"Webhook Error: {err}")

    return jsonify({"status": "success"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
