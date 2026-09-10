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

# Groq ka sabse stable non-reasoning direct model
ACTIVE_MODEL = "llama3-8b-8192"
HOTEL_PHONE = "+91-9876543210"

def load_hotel_data():
    try:
        with open("hotel_data.txt", "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"Error loading hotel_data.txt: {e}")
        return f"Hotel Ganga Palace Haridwar. Deluxe AC ₹1,800, Super Deluxe ₹2,600. Contact: {HOTEL_PHONE}"

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

def get_ai_reply(user_message):
    system_prompt = f"""
Aap Hotel Ganga Palace Haridwar ke polite manager 'Aman' hain.
Aapka andaz bilkul natural, humble WhatsApp human typing jaisa hona chahiye.

RULES:
1. Har jawab 1 ya 2 short sentences me dein. Hamesha 'Ji', 'Aap', aur respectful Hinglish use karein.
2. Agar guest khana, nashta, room, rates, timing ya menu se juda kuch bhi puche, toh HOTEL DATA se seedha jawab dein.
3. Agar koi aisi cheez puche jo data me NAHI hai, toh saaf bole: "Ji, is baare me mujhe confirm nahi hai. Kripya aap reception number {HOTEL_PHONE} par call kar lijiye."
4. Direct WhatsApp message reply likhein, koi extra notes ya explanation nahi.

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
            max_tokens=250
        )
        reply = completion.choices[0].message.content
        if reply:
            reply = reply.strip()
            print(f"--- BOT RAW OUTPUT: '{reply}' ---")
            return reply
        
        return "Namaste ji! Hotel Ganga Palace me aapka swagat hai. Batayein kaise help kar sakta hu?"
    except Exception as e:
        print(f"--- GROQ ERROR: {e} ---")
        return f"Namaste ji! Front desk par thoda rush hai, kripya direct call kar lijiye: {HOTEL_PHONE}"

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
                            print(f"--- DELIVERING REPLY: '{reply_text}' ---")

                            send_whatsapp_message(sender_phone, reply_text)
    except Exception as err:
        print(f"Webhook Error: {err}")

    return jsonify({"status": "success"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
