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

# Separate Alert Numbers
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
# 2. MASTER SYSTEM PROMPT (5 RULES)
# ==========================================
SYSTEM_PROMPT = f"""
You are the WhatsApp AI Receptionist for '{HOTEL_NAME}' in Haridwar.

CORE DIRECTIVE - ULTRA CRISP REPLIES:
- Always reply in maximum 1 to 2 short sentences. No essays, no bulleted lists, no step-by-step guides.
- NEVER use Devanagari script (क, ख, ग) unless the user typed in Devanagari script.
- If user writes/speaks in English -> reply 100% in English.
- If user writes/speaks in Hindi/Hinglish (Latin alphabet) -> reply in polite Hinglish (Latin alphabet).

1. ROOM INQUIRIES & PRICING RULES (IMPORTANT):
   Room Categories & Tariffs:
   - Deluxe Room (Non-AC): Rs. 1000/night
   - Super Deluxe (AC): Rs. 1500/night
   - Executive Ganga View (AC): Rs. 2200/night
   - Family Suite (4 Bed AC): Rs. 3200/night

   * CASE A - GUEST ASKS ONLY AVAILABILITY ("Room hai?", "Rooms available?", "Room chahiye"):
     - RATES APNE AAP BILKUL MAT BATAO.
     - ID proof bilkul mat maango.
     - Sirf categories bata kar date poochein: "Ji haan, humare paas Deluxe, Super Deluxe AC, Ganga View AC aur Family Suites available hain. Aap kis date ke liye book karna chahte hain?"
     - (English): "Yes, we have Deluxe, Super Deluxe AC, Ganga View AC, and Family Suites available. Which dates are you planning for?"

   * CASE B - GUEST ASKS RATES ("Kitne ka hai?", "Tariff / Price?", "Rate kya hai?"):
     - Tabhi rates batayein: "Deluxe Non-AC Rs. 1000, Super Deluxe AC Rs. 1500, Ganga View AC Rs. 2200, aur Family Suite Rs. 3200 per night hai. Aap kis category me interested hain?"

2. FOOD ORDERS & MENU (PURE VEG ONLY):
   - Menu: Chai (Normal Rs. 30, Masala Rs. 40), Roti (Tandoori Rs. 15, Butter Rs. 20, Naan Rs. 45), Paneer (Butter Masala Rs. 220, Matar Rs. 200, Kadhai Rs. 230, Shahi Rs. 220), Dal (Makhani Rs. 180, Tadka Rs. 150), Rice (Plain Rs. 100, Fried Rs. 150, Jeera Rs. 120), Mineral Water (Rs. 20).
   - Generic dish par 1 line me options poochein.
   - Room number maangna mandatory hai.
   - Final hone par alert lagayein: [KITCHEN_ALERT: Room <room_number> | Order: <items>]

3. STAFF & HOUSEKEEPING REQUESTS:
   - Safai, towel, ya luggage ke liye room number lein aur tag lagayein:
     [STAFF_ALERT: Room <room_number> | Task: <service_details>]

4. CHECK-IN / ID GUIDANCE:
   - Sirf tabhi ID maangein jab guest KHUD bole ki "ID bhej du?", "Check-in karna hai", ya "Documents send kru?".
   - Tab reply karein: "Ji bilkul, aap sabhi guests ke valid ID proof (Aadhaar, Driving License, ya Passport) ki saaf photo yahan send kar dijiye." (English me: "Yes, please share clear photos of valid Govt ID proofs right here.")
   - KABHI BHI room number mat maango aur chat me koi alert tag mat likho.

5. GREETINGS:
   - "Hi" ya "Hello" par seedha 1-line welcome: "Namaste! Welcome to {HOTEL_NAME}. How may I help you today?"
"""

# ==========================================
# 3. HELPER FUNCTIONS & KEEP-ALIVE
# ==========================================
def keep_awake_ping():
    """Render sleep prevention self-ping loop"""
    time.sleep(30)
    while True:
        try:
            if RENDER_EXTERNAL_URL:
                ping_url = f"{RENDER_EXTERNAL_URL.rstrip('/')}/health"
                requests.get(ping_url, timeout=10)
        except Exception as e:
            print(f"[KEEP-ALIVE] Ping failed: {e}")
        time.sleep(12 * 60)

def mark_message_as_read(message_id):
    """WhatsApp message ko read mark karta hai taaki green/blue tick turant show ho"""
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
        requests.post(url, json=payload, headers=headers, timeout=5)
    except Exception as e:
        print(f"Failed to mark as read: {e}")

def send_whatsapp_message(to_number, text):
    """WhatsApp Cloud API dispatcher"""
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
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        return res.json()
    except Exception as e:
        print(f"Failed to send message to {to_number}: {e}")
        return None

def download_media(media_id):
    """WhatsApp Media download helper"""
    try:
        res = requests.get(
            f"https://graph.facebook.com/v20.0/{media_id}",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            timeout=10
        )
        url = res.json().get("url")
        if not url:
            return None
        file_res = requests.get(url, headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}, timeout=15)
        return file_res.content
    except Exception as e:
        print(f"Media download error: {e}")
        return None

def transcribe_audio_groq(audio_id):
    """Groq Whisper audio transcription with auto-detected language"""
    try:
        audio_content = download_media(audio_id)
        if not audio_content:
            return None

        files = {"file": ("audio.ogg", audio_content, "audio/ogg")}
        data = {"model": "whisper-large-v3", "response_format": "text"}
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
        
        whisper_res = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers=headers,
            files=files,
            data=data,
            timeout=20
        )
        return whisper_res.text.strip()
    except Exception as e:
        print(f"Audio transcription error: {e}")
        return None

def verify_document_groq(image_id):
    """Groq Llama-Vision ID Verification"""
    try:
        image_content = download_media(image_id)
        if not image_content:
            return None

        base64_image = base64.b64encode(image_content).decode("utf-8")

        prompt = (
            "You are a Hotel Document Verification Assistant. "
            "Examine this image carefully. "
            "Determine if this is a valid Indian Government ID Proof (Aadhaar, Driving License, Passport, or Voter ID). "
            "Do NOT print any numeric identity numbers. "
            "If YES, respond strictly: VALID | ID_TYPE: <type> | NAME: <guest name or Not Visible> "
            "If NO, respond: INVALID | REASON: <short reason>"
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

        res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=20)
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
        "temperature": 0.1
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=12)
        res_data = response.json()
        reply_text = res_data.get("text", "Namaste! How may I assist you?")
        
        history.append({"role": "USER", "message": user_message})
        history.append({"role": "CHATBOT", "message": reply_text})
        chat_histories[sender_phone] = history[-6:]
        
        return reply_text
    except Exception as e:
        print(f"Cohere error: {e}")
        return "Namaste! Please try again in a moment."

def process_and_reply(user_text, sender_phone):
    """Core routing for user queries, orders, and alert tags"""
    bot_reply = ask_cohere(user_text, sender_phone)
    
    # 1. Kitchen Alert
    if "[KITCHEN_ALERT:" in bot_reply:
        order_details = bot_reply.split("[KITCHEN_ALERT:")[1].split("]")[0].strip()
        bot_reply = bot_reply.split("[KITCHEN_ALERT:")[0].strip()
        
        kitchen_msg = (
            f"🍳 *NEW ROOM SERVICE ORDER*\n\n"
            f"📋 *Details:* {order_details}\n"
            f"📞 *Guest Contact:* +{sender_phone}\n\n"
            f"⚡ Order deliver karein!"
        )
        send_whatsapp_message(KITCHEN_PHONE, kitchen_msg)

    # 2. Staff Alert
    if "[STAFF_ALERT:" in bot_reply:
        service_details = bot_reply.split("[STAFF_ALERT:")[1].split("]")[0].strip()
        bot_reply = bot_reply.split("[STAFF_ALERT:")[0].strip()
        
        staff_msg = (
            f"🛎️ *STAFF ALERT*\n\n"
            f"📌 *Details:* {service_details}\n"
            f"📞 *Guest Contact:* +{sender_phone}\n\n"
            f"⚡ Turant attend karein!"
        )
        send_whatsapp_message(STAFF_PHONE, staff_msg)
    
    # Strip any stray bracketed leak
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
        message_id = message.get("id")

        # INSTANT READ RECEIPT: Green/Blue tick activate karega
        if message_id:
            mark_message_as_read(message_id)

        # 1. TEXT
        if msg_type == "text":
            user_text = message.get("text", {}).get("body", "")
            process_and_reply(user_text, sender_phone)

        # 2. VOICE NOTES
        elif msg_type in ["audio", "voice"]:
            audio_id = message.get("audio", {}).get("id") or message.get("voice", {}).get("id")
            transcribed_text = transcribe_audio_groq(audio_id)
            if transcribed_text:
                process_and_reply(transcribed_text, sender_phone)
            else:
                send_whatsapp_message(sender_phone, "Voice note clear nahi tha, please try again.")

        # 3. ID VERIFICATION (GROQ VISION)
        elif msg_type == "image":
            image_id = message.get("image", {}).get("id")
            verification_result = verify_document_groq(image_id)

            if verification_result and verification_result.startswith("VALID"):
                send_whatsapp_message(
                    sender_phone,
                    "Thank you! 🙏 Your ID document has been verified. Pre-check-in register has been updated."
                )

                staff_doc_msg = (
                    f"🪪 *NEW GUEST ID VERIFIED*\n\n"
                    f"📋 *Doc Details:* {verification_result}\n"
                    f"📞 *Guest Contact:* +{sender_phone}\n\n"
                    f"✅ Pre-check-in verified."
                )
                send_whatsapp_message(STAFF_PHONE, staff_doc_msg)

            else:
                send_whatsapp_message(
                    sender_phone,
                    "Please share a clear photo of a valid Government ID proof (Aadhaar, Driving License, Passport, or Voter ID)."
                )

        # 4. LOCATION NAVIGATION
        elif msg_type == "location":
            loc_data = message.get("location", {})
            user_lat = loc_data.get("latitude")
            user_lon = loc_data.get("longitude")
            
            maps_route_url = f"https://www.google.com/maps/dir/?api=1&origin={user_lat},{user_lon}&destination={HOTEL_LAT},{HOTEL_LON}"
            nav_reply = (
                f"📍 *Hotel Navigation Route:*\n{maps_route_url}\n\n"
                f"Click the link above to view directions on Google Maps."
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
