import os
import requests
from flask import Flask, request, jsonify
import cohere

app = Flask(__name__)

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "hotel_secret_token")
COHERE_API_KEY = os.getenv("COHERE_API_KEY")

co = cohere.ClientV2(api_key=COHERE_API_KEY)
PROCESSED_MESSAGES = set()
HOTEL_PHONE = "+91-7500058655"

def load_hotel_data():
    try:
        with open("hotel_data.txt", "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"Error reading hotel_data.txt: {e}")
        return f"Hotel Ganga Palace Haridwar. Contact: {HOTEL_PHONE}"

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
    hotel_context = load_hotel_data()
    
    preamble = f"""
Aap Hotel Ganga Palace Haridwar ke polite reception manager 'Aman' hain.
Aapka andaz bilkul humble aur short WhatsApp human typing jaisa hona chahiye.

RULES:
1. Har jawab 1 ya 2 short sentences me respectful Hinglish me dein ('Ji', 'Aap' use karein).
2. Niche diye gaye HOTEL DATA se rooms, rates, timings aur food menu items confirm karke direct batayein.
3. Agar aisi koi cheez puchi jaye jo data me nahi hai, toh politely reception number {HOTEL_PHONE} par call karne ko kahein.
4. Kabhi koi explanation, rule ya checklist repeat na karein, seedha customer ko reply dein.

HOTEL DATA:
{hotel_context}
"""
    try:
        response = co.chat(
            model="command-r",
            messages=[
                {"role": "system", "content": preamble},
                {"role": "user", "content": user_message}
            ],
            temperature=0.3
        )
        reply = response.message.content[0].text.strip()
        print(f"--- BOT CLEAN REPLY: '{reply}' ---")
        return reply if reply else "Namaste ji! Hotel Ganga Palace me aapka swagat hai. Batayein kaise help kar sakta hu?"
    except Exception as e:
        print(f"--- COHERE ERROR: {e} ---")
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

                            send_whatsapp_message(sender_phone, reply_text)
    except Exception as err:
        print(f"Webhook Error: {err}")

    return jsonify({"status": "success"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
