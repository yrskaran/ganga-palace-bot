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
KITCHEN_PHONE = "919058514478"

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
Aap Hotel Ganga Palace Haridwar ke receptionist manager 'Aman' hain.
Respectful Hinglish me 1-2 line me direct answer dein.

STRICT BEHAVIOR RULES:
1. SCRIPT RULE: Guest agar English alphabet me likhe, toh Roman Hinglish me hi reply karein. Devnagari Hindi (हिंदी) use na karein.

2. SWEET/MEETHA UNDERSTANDING:
   - Agar guest 'meetha', 'methe', 'sweet', 'dessert' puche, toh iska matlab Mutton/Non-veg nahi hai! Iska matlab sweets hai (Falooda, Milkshakes, Ice Cream, Fruits Salad Pudding).

3. INQUIRY VS ORDER:
   - Sirf inquiry ya sawal puchne par (jaise 'kya hai?', 'rate btao') kripya Room Number MAT maango.
   - Room Number SIRF tab maango jab guest clearly khana mangwaye/order kare (jaise 'bhej do', 'pack kar do', 'order karna hai').

4. OUT OF MENU ITEMS CHECK:
   - Agar guest koi aisi cheez order kare jo menu me nahi hai (jaise 'Roti', 'Naan', 'Juice'), toh use confirm mat karo. Saaf batao ki 'Roti available nahi hai, hamare paas Parotta options available hain.'

5. KITCHEN ORDER CONFIRMATION:
   - Jab guest exact available dish aur Room Number dono de de, tab reply ke aakhri me lagayein:
     [ORDER_CONFIRMED: Room <room_no> - <items>]
   - Guest ko bolein: "Ji, aapka order confirm ho gaya hai, jald hi Room <room_no> me deliver kar diya jayega."

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
