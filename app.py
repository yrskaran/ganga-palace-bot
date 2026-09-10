import os
import re
import time
import requests
from flask import Flask, request, jsonify
from groq import Groq

app = Flask(__name__)

# Environment Variables
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "hotel_secret_token")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

groq_client = Groq(api_key=GROQ_API_KEY)
PROCESSED_MESSAGES = set()

# Fixed working model
ACTIVE_MODEL = "qwen/qwen3.6-27b"

# Hotel & Restaurant Knowledge Base
HOTEL_PHONE = "+91-9876543210"

HOTEL_CONTEXT = f"""
Hotel: Hotel Ganga Palace Haridwar
Location: Upper Road, Haridwar (Har Ki Pauri se sirf 450 meter door, paidal 5 minute).
Contact Number: {HOTEL_PHONE}
Rooms & Rates: Deluxe AC Room: ₹1,800/night, Super Deluxe: ₹2,600/night.
Timings: Check-in 12:00 PM, Check-out 11:00 AM.
Sightseeing: Har Ki Pauri Evening Aarti: 6:30 PM, Morning: 5:30 AM. Mansa Devi Ropeway: 1.5 km door.
Facilities: Free Wi-Fi, 24/7 hot water, in-house dining/room service, parking available.

--- RESTAURANT FOOD MENU & RATES ---
MILK SHAKE & ICE CREAM:
- Vanilla: ₹75, Strawberry: ₹75, Chocolate: ₹80, Butter Scotch: ₹80, Pista: ₹80, Spanish Delite: ₹80, Black Current: ₹80, Cherry: ₹80, Cashew: ₹90, Fig Fruit: ₹100, Kashmir: ₹85, Oman: ₹80, Saudi: ₹80, Thamam: ₹80, Mango Shake: ₹80, Papaya: ₹80, Pineapple: ₹90, Chikku: ₹80, Aanaar: ₹80, Tender Coconut: ₹80, Semam: ₹80, Badam Shake: ₹100, Oreo Shake: ₹80, Cara Milk Nuts: ₹80, Til Tak: ₹80

FALOODA:
- Royal Falooda: ₹150, Pista Falooda: ₹160, Butter Falooda: ₹170, MGS Special Falooda: ₹210

FRESH LIMES:
- Fresh Limes: ₹20, Ginger Limes: ₹20, Mint Limes: ₹35, Soda Limes: ₹25, Grapes Limes: ₹30, Curry Leaves Limes: ₹35

FRUITS SALAD:
- Fruits Salad Pudding: ₹100, Dry Fruits Salad: ₹80

MUTTON:
- Mutton Chops: ₹190, Mutton Chukka: ₹130, Mutton Fry: ₹120, Mutton Boti Fry: ₹80

FISH & PRAWNS:
- Fish Fry: ₹100, Fish Curry: ₹100, Fish 65: ₹100, Fish Masala: ₹120, Chilli Fish: ₹130, Prawns Fry: ₹170, Prawns Masala: ₹180, Prawns Curry: ₹180, Chilli Prawns: ₹180

DINNER SPECIALS:
- Parotta: ₹15, Veechu Parotta: ₹25, Open Veechu Parotta: ₹25, Veechu Egg Parotta: ₹70, Piece Parotta: ₹25, Kothu Parotta: ₹70, Mutton Kaima Parotta: ₹180, Chicken Kaima Parotta: ₹170, Mutton Murtabak Parotta: ₹180, Chicken Murtabak Parotta: ₹170, Oil Parotta: ₹25, Without Oil Parotta: ₹20, Panchu Parotta: ₹25, Sweet Parotta: ₹30, Banana Leaf Mutton Parotta: ₹210, Banana Leaf Chicken Parotta: ₹170, Chappathi: ₹40, Chicken Dum Parotta: ₹300, Mushroom Dosa: ₹120, Chicken Dosa: ₹130, Mutton Dosa: ₹160, Idiyappam/Paya: ₹80, Appam/Chicken Gravy: ₹135

CHINESE:
- Veg Manchurian: ₹100, Gobi Manchurian: ₹90, Chilli Gobi Manchurian: ₹90, Mushroom Gravy: ₹120, Mushroom Manchurian: ₹120, Crispy Veg: ₹120, Szechwan Chicken: ₹150, Chilli Chicken: ₹120, Ginger Chicken: ₹140, Dragon Chicken: ₹150, Shawarma Roll: ₹80, Shawarma Plate: ₹110

FRIED RICE:
- Veg Fried Rice: ₹80, Egg Fried Rice: ₹90, Chicken Fried Rice: ₹120, Mushroom Fried Rice: ₹100, Paneer Fried Rice: ₹110, Mixed Fried Rice: ₹140, Schezwan Chicken Fried Rice: ₹140, Schezwan Veg Fried Rice: ₹100, Taiwanese Chicken Fried Rice: ₹130, Taiwanese Veg Fried Rice: ₹110

NOODLES:
- Chicken Noodles: ₹110, Veg Noodles: ₹80, Egg Noodles: ₹90, Mixed Noodles: ₹130, Schezwan Chicken Noodles: ₹140, Schezwan Veg Noodles: ₹110, Taiwanese Chicken Noodles: ₹140, Taiwanese Veg Noodles: ₹100
"""

def mark_message_as_read(message_id):
    """Message par blue tick lagane ke liye"""
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
        requests.post(url, headers=headers, json=payload, timeout=3)
    except Exception as e:
        print(f"Read receipt error: {e}")

def clean_reply(text):
    """Reasoning aur think tags hatane ke liye"""
    if not text:
        return ""
    if "</think>" in text:
        text = text.split("</think>")[-1].strip()
    elif "<think>" in text:
        text = text.split("<think>")[0].strip()
    return text.strip()

def get_ai_reply(user_message):
    system_prompt = f"""
Aap Hotel Ganga Palace Haridwar ke polite manager 'Aman' hain.
Aapka andaz bilkul natural, humble WhatsApp human typing jaisa hona chahiye.

RULES:
1. Har jawab 1 ya 2 short sentences me dein. Hamesha 'Ji', 'Aap', aur respectful Hinglish use karein.
2. FOOD ORDERS: Agar koi khana order kare ya rate puche (jaise "1 Chilli Chicken aur 2 Parotta ka kitna hua?"), toh upar diye gaye RESTAURANT MENU se exact rate calculate karke total batao aur order confirm karo.
3. STRICT RULE: Agar guest aisi koi cheez ya service puche jo upar HOTEL DATA ya MENU me NAHI hai, toh man se mat banao. Seedha bolo: "Ji, is baare me mujhe confirm nahi hai. Kripya aap reception number {HOTEL_PHONE} par call kar lijiye."
4. Kabhi apna reasoning ya thinking process show na karein.

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
            temperature=0.2,
            max_tokens=350
        )
        raw_text = completion.choices[0].message.content
        reply = clean_reply(raw_text)
        return reply if reply else f"Namaste ji! Saari details ke liye aap hamare front desk number {HOTEL_PHONE} par call kar lijiye."
    except Exception as e:
        print(f"--- Groq Error: {e} ---")
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
                            print(f"--- BOT FINAL REPLY: '{reply_text}' ---")

                            time.sleep(2)
                            send_whatsapp_message(sender_phone, reply_text)
    except Exception as err:
        print(f"Webhook Error: {err}")

    return jsonify({"status": "success"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
