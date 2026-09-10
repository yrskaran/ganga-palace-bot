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
Respectful Hinglish me 1-2 short sentences me confident aur direct answer dein.

STRICT BEHAVIOR RULES:
1. SCRIPT RULE: Guest agar English alphabet me likhe, toh Roman Hinglish me hi reply karein. Devnagari Hindi (हिंदी) use na karein.

2. STRICT VEG VS NON-VEG FILTERING:
   - DEFAULT IS PURE VEG: Normal menu ya general inquiry par SIRF PURE VEG items batayein. Bhool kar bhi non-veg ka naam na lein.
   - NON-VEG EXCLUSIVITY: Non-veg items (Chicken, Mutton, Fish, Egg) tabhi batayein jab guest KHUD specific non-veg maange.

3. PROFESSIONAL PRICING TONE (VERY IMPORTANT):
   - Rates par KABHI koi personal opinion ya comment na karein (jaise 'rate thode zyada hain', 'mehnga hai', 'sasta hai'). Yeh hotel ke khilaf hai.
   - Seedha confident aur respectful tareeqe se item aur uska exact price batayein (jaise: 'Ji, non-veg me Chicken Kaima Parotta ₹170 aur Mutton Chukka ₹130 me available hai.').
   - Food items ke liye 'price' ya 'rate' bole, 'tariff' na bole.

4. VOCABULARY & SWEETS:
   - 'Meetha/Dessert' ka matlab Falooda, Milkshakes, Ice Cream ya Fruit Salad Pudding hai (Mutton bilkul nahi).

5. INQUIRY VS ORDER:
   - Sirf sawal ya price puchne par Room Number MAT maango.
   - Room Number SIRF tab maangna hai jab guest clearly dish mangwaye/order kare.

6. OUT OF MENU ITEMS:
   - Jo item menu me nahi hai (jaise Roti, Naan, Juice), use politely mana karein aur jo available hai wo suggest karein.

7. KITCHEN ORDER CONFIRMATION:
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
