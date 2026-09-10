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
You are Aman, the polite front desk manager at Hotel Ganga Palace Haridwar.
Respond directly to the guest in WhatsApp chat style. 

CRITICAL INSTRUCTIONS:
- Give DIRECT OUTPUT ONLY. Never write internal thoughts, reasoning steps, or checklists.
- Language: Natural, polite Hinglish.
- Length: Exactly 1 to 2 short sentences.
- Use 'Ji', 'Aap', and be respectful.
- If asked about rooms, rates, location, food, or menu, answer directly from HOTEL DATA.
- If asking something totally absent from HOTEL DATA, ask them to call {HOTEL_PHONE}.

HOTEL DATA:
{HOTEL_CONTEXT}
"""
    try:
        # Extra_body me reasoning disable ki gayi hai
        completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            model=ACTIVE_MODEL,
            temperature=0.2,
            max_tokens=400,
            extra_body={"reasoning_format": "hidden"}
        )
        reply = completion.choices[0].message.content.strip()
        print(f"--- BOT RAW OUTPUT: '{reply}' ---")
        return reply if reply else "Namaste ji! Hotel Ganga Palace me aapka swagat hai. Batayein kaise help kar sakta hu?"
    except Exception as e:
        print(f"--- GROQ API ERROR: {e} ---")
        # Fallback without extra_body if unsupported
        try:
            fallback_comp = groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                model=ACTIVE_MODEL,
                temperature=0.2,
                max_tokens=400
            )
            raw = fallback_comp.choices[0].message.content.strip()
            # If model still prints thought steps, grab the last quoted sentence
            if '"' in raw:
                quotes = re.findall(r'"([^"]*)"', raw)
                if quotes:
                    return quotes[-1]
            return raw
        except Exception as err2:
            print(f"--- COMPLETE FAILURE: {err2} ---")
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
                            print(f"--- DELIVERING REPLY: '{reply_text}' ---")

                            send_whatsapp_message(sender_phone, reply_text)
    except Exception as err:
        print(f"Webhook Error: {err}")

    return jsonify({"status": "success"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
