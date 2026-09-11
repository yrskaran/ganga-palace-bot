import os
import base64
import time
import threading
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ==========================================
# 1. CONFIGURATION & ENVIRONMENT VARIABLES
# ==========================================
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
COHERE_API_KEY = os.getenv("COHERE_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Alert Numbers
KITCHEN_PHONE = os.getenv("KITCHEN_PHONE", "919058514478")
STAFF_PHONE = os.getenv("STAFF_PHONE", "919058514488")

# Hotel Information (Haridwar)
HOTEL_NAME = "Hotel Ganga View"
HOTEL_LAT = "29.9530"
HOTEL_LON = "78.1700"

# Render external URL for self-ping
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")

# In-memory chat history (per user)
chat_histories = {}

# ==========================================
# 2. MASTER SYSTEM PROMPT
# ==========================================
SYSTEM_PROMPT = f"""
Aap '{HOTEL_NAME}' (Haridwar) ke polite aur professional AI Receptionist aur Local Concierge hain.

MUKHYA NIYAM:

1. COMPLETE & EXCLUSIVE PURE VEGETARIAN MENU:
   Kewal aur kewal niche diye gaye items hi uplabdh hain:
   - Chai:
     * Normal Chai: Rs. 30
     * Masala Chai: Rs. 40
   - Roti/Breads:
     * Tandoori Roti: Rs. 15
     * Butter Roti: Rs. 20
     * Butter Naan: Rs. 45
   - Paneer Dishes:
     * Paneer Butter Masala: Rs. 220
     * Matar Paneer: Rs. 200
     * Kadhai Paneer: Rs. 230
     * Shahi Paneer: Rs. 220
   - Dal:
     * Dal Makhani: Rs. 180
     * Dal Tadka: Rs. 150
   - Rice:
     * Plain Rice: Rs. 100
     * Veg Fried Rice: Rs. 150
     * Jeera Rice: Rs. 120
   - Extras:
     * Mineral Water: Rs. 20

   *NOTE:* Agar guest is menu ke bahar ka koi item mange, toh kripya vinamrata se batayein ki kewal upar diye gaye shuddh shakahari vyanjan hi uplabdh hain.

2. FOOD ORDER RULES:
   - AMBIGUOUS DISH: Agar guest sirf 'paneer', 'daal', ya 'chai' bole, toh apne mann se choose na karein. Pehle unse option poochein (jaise Paneer Butter Masala, Matar Paneer, Kadhai Paneer, Shahi Paneer).
   - MANDATORY ROOM NUMBER: Bina Room Number ke food order confirm na karein.
   - Order confirm hone par aakhiri me ye exact tag lagayein:
     [KITCHEN_ALERT: Room <room_number> | Order: <items>]

3. STAFF & HOUSEKEEPING REQUESTS:
   - Safai, extra towel, blanket, ya luggage ke liye pehle Room Number poochein.
   - Confirm hone par aakhiri me ye tag lagayein:
     [STAFF_ALERT: Room <room_number> | Task: <service_details>]

4. CHECK-IN / ID GUIDANCE:
   - Agar guest documents bhejne ya check-in formalities ki baat kare, toh ROOM NUMBER MAT POOCHEIN.
   - Seedha kahein: "Ji bilkul! Aap sabhi adult guests ke Govt ID Proof (Aadhaar, Driving License, ya Passport) ki saaf photo yahan send kar dijiye."
   - Chat me koi bhi [CHECKIN_ALERT] tag message me mat likhein.

5. LOCAL TOURIST GUIDANCE:
   - Har Ki Pauri Sandhya Aarti: 5:15 PM tak pahunchne ki salah dein.
   - Mansa Devi / Chandi Devi Ropeway: Subah 7:00 AM se open rehta hai.
   - Local Food: Mohan Ji Puri Wale aur Pandit Sevaram Doodh Jalebi.

6. LANGUAGE & TONE RULES:
   - IF USER SPEAKS ENGLISH: Reply in crisp, polite English.
   - IF USER SPEAKS HINDI / HINGLISH: Reply in polite Hindi / Hinglish.
   - Tone hamesha respectful aur hospitable rakhein.
"""

# ==========================================
# 3. HELPER FUNCTIONS & BACKGROUND THREADS
# ==========================================
def keep_awake_ping():
    """Render ko sleep mode me jane se rokne ke liye auto self-ping"""
    time.sleep(30)
    while True:
        try:
            if RENDER_EXTERNAL_URL:
                ping_url = f"{RENDER_EXTERNAL_URL.rstrip('/')}/health"
                requests.get(ping_url, timeout=10)
        except Exception as e:
            print(f"[KEEP-ALIVE] Ping failed: {e}")
        time.sleep(12 * 60)

def send_whatsapp_message(to_number, text):
    """WhatsApp Cloud API helper"""
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": text}
    }
    try:
        res = requests.post(url, json=payload, headers=headers)
        return res.json()
    except Exception as e:
        print(f"Failed to send message to {to_number}: {e}")
        return None

def download_media(media_id):
    """WhatsApp Media download helper"""
    try:
        res = requests.get(
            f"https://graph.facebook.com/v20.0/{media_id}",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        )
        url = res.json().get("url")
        if not url:
            return None
        file_res = requests.get(url, headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"})
        return file_res.content
    except Exception as e:
        print(f"Media download error: {e}")
        return None

def transcribe_audio_groq(audio_id):
    """Audio to Text via Groq Whisper"""
    try:
        audio_content = download_media(audio_id)
        if not audio_content:
            return None

        files = {"file": ("audio.ogg", audio_content, "audio/ogg")}
        data = {"model": "whisper-large-v3", "language": "hi", "response_format": "text"}
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
        
        whisper_res = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers=headers,
            files=files,
            data=data
        )
        return whisper_res.text.strip()
    except Exception as e:
        print(f"Audio transcription error: {e}")
        return None

def verify_document_groq(image_id):
    """Document Image Verification via Groq Vision"""
    try:
        image_content = download_media(image_id)
        if not image_content:
            return None

        base64_image = base64.b64encode(image_content).decode("utf-8")

        prompt = (
            "You are a strict Hotel Reception Document Verification Assistant. "
            "Examine this image carefully. "
            "Determine if this is a valid Indian Government ID Proof (Aadhaar Card, Driving License, Passport, or Voter ID). "
            "If YES, respond strictly in this format: "
            "VALID | ID_TYPE: <type> | NAME: <guest name or Not Visible> "
            "If NO (blurry, meme, selfie, random object, invalid doc), respond: "
            "INVALID | REASON: <short reason>"
        )

        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama-3.2-11b-vision-preview",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }
            ],
            "temperature": 0.1
        }

        res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
        return res.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"Document verification error: {e}")
        return None

def ask_cohere(user_message, sender_phone):
    """Cohere API Chatbot reply"""
    history = chat_histories.get(sender_phone, [])
    
    url = "https://api.cohere.ai/v1/chat"
    headers = {
        "Authorization": f"Bearer {COHERE_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "message": user_message,
        "preamble": SYSTEM_PROMPT,
        "chat_history": history,
        "temperature": 0.2
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        res_data = response.json()
        reply_text = res_data.get("text", "Kshama karein, mai abhi samajh nahi paya.")
        
        history.append({"role": "USER", "message": user_message})
        history.append({"role": "CHATBOT", "message": reply_text})
        chat_histories[sender_phone] = history[-6:]
        
        return reply_text
    except Exception as e:
        print(f"Cohere error: {e}")
        return "Namaste! Hamari service me thodi takneeki samasya aa rahi hai."

def process_and_reply(user_text, sender_phone):
    """Order, service requests aur general chat router"""
    bot_reply = ask_cohere(user_text, sender_phone)
    
    # 1. Kitchen Alert
    if "[KITCHEN_ALERT:" in bot_reply:
        order_details = bot_reply.split("[KITCHEN_ALERT:")[1].split("]")[0].strip()
        bot_reply = bot_reply.split("[KITCHEN_ALERT:")[0].strip()
        
        kitchen_msg = (
            f"🍳 *NEW ROOM SERVICE ORDER*\n\n"
            f"📋 *Details:* {order_details}\n"
            f"📞 *Guest Contact:* +{sender_phone}\n\n"
            f"⚡ Kripya order turant deliver karein!"
        )
        send_whatsapp_message(KITCHEN_PHONE, kitchen_msg)

    # 2. Staff Alert
    if "[STAFF_ALERT:" in bot_reply:
        service_details = bot_reply.split("[STAFF_ALERT:")[1].split("]")[0].strip()
        bot_reply = bot_reply.split("[STAFF_ALERT:")[0].strip()
        
        staff_msg = (
            f"🛎️ *STAFF / HOUSEKEEPING ALERT*\n\n"
            f"📌 *Details:* {service_details}\n"
            f"📞 *Guest Contact:* +{sender_phone}\n\n"
            f"⚡ Kripya turant attend karein!"
        )
        send_whatsapp_message(STAFF_PHONE, staff_msg)
    
    bot_reply = bot_reply.replace("[CHECKIN_ALERT: Room <room_number> | Documents Shared]", "").strip()
    send_whatsapp_message(sender_phone, bot_reply)

# ==========================================
# 4. WEBHOOK & HEALTH ROUTES
# ==========================================
@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "active", "service": "hotel-bot"}), 200

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

@app.route("/webhook", methods=["POST"])
def handle_webhook():
    data = request.get_json()
    
    try:
        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        
        if not messages:
            return jsonify({"status": "ignored"}), 200
            
        message = messages[0]
        sender_phone = message.get("from")
        msg_type = message.get("type")

        # 1. TEXT MESSAGES
        if msg_type == "text":
            user_text = message.get("text", {}).get("body", "")
            process_and_reply(user_text, sender_phone)

        # 2. VOICE NOTES (GROQ WHISPER)
        elif msg_type in ["audio", "voice"]:
            audio_id = message.get("audio", {}).get("id") or message.get("voice", {}).get("id")
            transcribed_text = transcribe_audio_groq(audio_id)
            if transcribed_text:
                process_and_reply(transcribed_text, sender_phone)
            else:
                send_whatsapp_message(sender_phone, "Kshama karein, aapka voice note saaf nahi tha. Kripya dobara bhejein.")

        # 3. DOCUMENT / ID PHOTO VERIFICATION (GROQ VISION)
        elif msg_type == "image":
            image_id = message.get("image", {}).get("id")
            verification_result = verify_document_groq(image_id)

            if verification_result and verification_result.startswith("VALID"):
                send_whatsapp_message(
                    sender_phone,
                    f"Dhanyawad! 🙏 Aapka ID Proof successfully verify ho gaya hai.\n\n"
                    f"Aapka fast check-in register update kar diya gaya hai. Hotel aane par aapko kamre ki chabi turant mil jayegi."
                )

                staff_doc_msg = (
                    f"🪪 *NEW GUEST ID VERIFIED*\n\n"
                    f"📋 *Doc Details:* {verification_result}\n"
                    f"📞 *Guest Contact:* +{sender_phone}\n\n"
                    f"✅ Pre-check-in verified. Entry register taiyar rakhein!"
                )
                send_whatsapp_message(STAFF_PHONE, staff_doc_msg)

            else:
                send_whatsapp_message(
                    sender_phone,
                    "Kshama karein, yeh valid ya saaf Government ID Proof nahi lag raha hai. "
                    "Kripya Aadhaar, Driving License ya Passport ki saaf photo bhejein taaki check-in proceed ho sake."
                )

        # 4. LOCATION SHARING (DIRECT NAVIGATION LINK)
        elif msg_type == "location":
            loc_data = message.get("location", {})
            user_lat = loc_data.get("latitude")
            user_lon = loc_data.get("longitude")
            
            maps_route_url = f"https://www.google.com/maps/dir/?api=1&origin={user_lat},{user_lon}&destination={HOTEL_LAT},{HOTEL_LON}"
            
            nav_reply = (
                f"Namaskar! 🙏 Aapki live location mil gayi hai.\n\n"
                f"📍 *Hotel Navigation Route Link:*\n"
                f"{maps_route_url}\n\n"
                f"🚗 *Directions:*\n"
                f"Upar diye gaye Google Maps link par click karke rasta follow karein ya driver ko yeh route dikha dein."
            )
            send_whatsapp_message(sender_phone, nav_reply)

    except Exception as e:
        print(f"Error processing webhook: {e}")

    return jsonify({"status": "success"}), 200

# ==========================================
# 5. START DAEMON THREAD & RUN APP
# ==========================================
if __name__ == "__main__":
    threading.Thread(target=keep_awake_ping, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
