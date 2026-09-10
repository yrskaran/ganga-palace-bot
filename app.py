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
USER_CHATS = {}

ACTIVE_MODEL = "command-r-08-2024"
HOTEL_PHONE = "+91-7500058655"
KITCHEN_PHONE = "919058514478"  # WhatsApp format (country code + 10 digits)

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

def get_ai_reply(sender_phone, user_message):
    hotel_context = load_hotel_data()
    
    preamble = f"""
Aap Hotel Ganga Palace Haridwar ke polite reception manager 'Aman' hain.

STRICT LANGUAGE & SCRIPT MATCHING:
1. Agar guest Roman letters (English letters) me likhe, toh aapka jawab BHI 100% ROMAN SCRIPT (Hinglish) me hi hona chahiye. Devnagari Hindi (हिंदी) me bilkul mat likhna.
2. Agar guest Devnagari script me text kare, tabhi Devnagari me reply dein.

FOOD ORDER & ROOM NUMBER RULES:
3. Agar guest khana mangwaye ya order dene ki baat kare (jaise '1 dal makhni bhej do', 'order karna hai', 'room me bhej do'):
   - Agar guest ne abhi tak apna Room Number nahi bataya hai, toh order confirm karne se pehle politely Room Number puchein: "Ji bilkul, kripya apna Room Number batayein taaki order deliver kiya ja sake."
   - Agar guest ne dish ke sath Room Number pehle hi bata diya hai ya pichle message me bata chuka hai:
     Aapke reply ki aakhri line me exact yeh secret tag zaroor lagayein:
     [ORDER_CONFIRMED: Room <room_no> - <items>]
     Aur guest ko bolein: "Ji, aapka order confirm ho gaya hai, jald hi Room <room_no> me deliver kar diya jayega."

ACCURACY & MENU RULES:
4. Menu categories ka dhyan rakhein (Milkshake ko juice na bolein). Jo cheez menu me nahi hai, saaf mana karein.
5. Rate aur availability direct batayein. Faltu counter-questions na karein.
6. Max 1-2 short sentences me natural WhatsApp typing me reply dein.

HOTEL DATA & MENU:
{hotel_context}
"""
    if sender_phone not in USER_CHATS:
        USER_CHATS[sender_phone] = []

    history = USER_CHATS[sender_phone]
    history.append({"role": "user", "content": user_message})

    messages_payload = [{"role": "system", "content": preamble}] + history[-6:]

    try:
        response = co.chat(
            model=ACTIVE_MODEL,
            messages=messages_payload,
            temperature=0.0
        )
        reply = response.message.content[0].text.strip()
        print(f"--- BOT RAW REPLY: '{reply}' ---")

        # Kitchen notification check
        if "[ORDER_CONFIRMED:" in reply:
            order_detail = reply.split("[ORDER_CONFIRMED:")[1].split("]")[0].strip()
            reply = reply.split("[ORDER_CONFIRMED:")[0].strip()
            
            kitchen_alert = f"🛎️ *Naya Food Order*\nGuest Phone: +{sender_phone}\nDetails: {order_detail}"
            print(f"--- ALERTING KITCHEN: {kitchen_alert} ---")
            send_whatsapp_message(KITCHEN_PHONE, kitchen_alert)

        history.append({"role": "assistant", "content": reply})
        if len(history) > 10:
            USER_CHATS[sender_phone] = history[-6:]

        return reply if reply else "Namaste ji! Hotel Ganga Palace me aapka swagat hai. Batayein kaise help kar sakta hu?"
    except Exception as e:
        print(f"--- COHERE ERROR: {e} ---")
        return f"Namaste ji! Reception par call kar lijiye: {HOTEL_PHONE}"

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
                            reply_text = get_ai_reply(sender_phone, incoming_text)

                            send_whatsapp_message(sender_phone, reply_text)
    except Exception as err:
        print(f"Webhook Error: {err}")

    return jsonify({"status": "success"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
