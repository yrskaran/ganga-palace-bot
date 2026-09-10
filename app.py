import os
import re
import time
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

# Safe active model
ACTIVE_MODEL = "qwen/qwen3.6-27b"
HOTEL_PHONE = "+91-9876543210"

HOTEL_CONTEXT = f"""
Hotel: Hotel Ganga Palace Haridwar
Location: Upper Road, Haridwar (Har Ki Pauri se sirf 450 meter door, paidal 5 minute).
Contact Number: {HOTEL_PHONE}
Rooms & Rates: Deluxe AC Room: ₹1,800/night, Super Deluxe: ₹2,600/night.
Timings: Check-in 12:00 PM, Check-out 11:00 AM.
Sightseeing: Har Ki Pauri Evening Aarti: 6:30 PM, Morning: 5:30 AM. Mansa Devi Ropeway: 1.5 km door.
Facilities: Free Wi-Fi, 24/7 hot water, pure veg dining, parking available.

--- RESTAURANT MENU (Brief) ---
- Shakes: Vanilla (₹75), Strawberry (₹75), Chocolate (₹80), Badam Shake (₹100), Oreo Shake (₹80)
- Falooda: Royal (₹150), Pista (₹160), Butter (₹170)
- Non-Veg Starters: Mutton Chops (₹190), Mutton Fry (₹120), Fish Fry (₹100), Prawns Fry (₹170), Chilli Chicken (₹120)
- Breads/Dinner: Parotta (₹15), Veechu Parotta (₹25), Egg Parotta (₹70), Chicken Dum Parotta (₹300), Chappathi (₹40), Dosa (₹120-160)
- Rice & Noodles: Veg Fried Rice (₹80), Chicken Fried Rice (₹120), Veg Noodles (₹80), Chicken Noodles (₹110)
"""

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
    if "</think>" in text:
        text = text.split("</think>")[-1].strip()
    elif "<think>" in text:
        text = text.split("<think>")[0].strip()
    return text.strip()

def get_ai_reply(user_message):
    system_prompt = f"""
Aap Hotel Ganga Palace Haridwar ke polite reception manager 'Aman' hain.
Rules:
1. Har jawab 1 ya 2 short sentences me dein. Hamesha 'Ji', 'Aap', aur respectful Hinglish use karein.
2. Agar guest aisi koi cheez puche jo HOTEL DATA ya MENU me NAHI hai, toh man se na banayein. Seedha bole: "Ji, is baare me confirm nahi hai. Kripya aap reception number {HOTEL_PHONE} par call kar lijiye."
3. Kabhi apna reasoning ya think tag show na karein.

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
            temperature=0.3,
            max_tokens=300
        )
        raw_text = completion.choices[0].message.content
        reply = clean_reply(raw_text)
        return reply if reply else f"Namaste ji! Saari jaankari ke liye aap reception number {HOTEL_PHONE} par call kar sakte hain."
    except Exception as e:
        print(f"--- GROQ REAL ERROR: {e} ---")
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
