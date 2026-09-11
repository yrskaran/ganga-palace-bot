import os
import base64
import time
import threading
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ==========================================
# 1. ENVIRONMENT CONFIGURATION
# ==========================================
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
COHERE_API_KEY = os.getenv("COHERE_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

KITCHEN_PHONE = os.getenv("KITCHEN_PHONE", "919058514478")
STAFF_PHONE = os.getenv("STAFF_PHONE", "919058929796")

HOTEL_LAT = "29.9530"
HOTEL_LON = "78.1700"

RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")
chat_histories = {}

# ==========================================
# 2. FILE-BASED SYSTEM PROMPT LOADER
# ==========================================
def get_system_prompt():
    """Reads instructions and database completely from hotel_data.txt"""
    file_path = os.path.join(os.path.dirname(__file__), "hotel_data.txt")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"[PROMPT ERROR] Failed to read hotel_data.txt: {e}")
        return "You are the WhatsApp AI Receptionist for Hotel Ganga View in Haridwar. Reply politely in 1-2 lines."

# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================
def keep_awake_ping():
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
    try:
        image_content = download_media(image_id)
        if not image_content:
            print("[VISION ERROR] Could not download media from WhatsApp")
            return None

        base64_image = base64.b64encode(image_content).decode("utf-8")

        prompt = (
            "You are a Hotel Document Verification Assistant. "
            "Examine this image carefully. "
            "Determine if this is an Indian Government ID Proof (Aadhaar Card, e-Aadhaar, Voter ID, Driving License, or Passport). "
            "Do NOT print any Aadhaar or ID numbers. "
            "If it is a valid Govt ID, respond strictly: "
            "VALID | ID_TYPE: Aadhaar/DL/Passport/VoterID | NAME: <guest name or Not Visible> "
            "If it is blurry, unreadable, or not a government ID, respond strictly: "
            "INVALID | REASON: <blurry or not_govt_id>"
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
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            "temperature": 0.1,
            "max_tokens": 150
        }

        res = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if res.status_code != 200:
            print(f"[GROQ VISION HTTP ERROR] {res.status_code}: {res.text}")
            return None
            
        data = res.json()
        result = data["choices"][0]["message"]["content"].strip()
        print(f"[GROQ VISION SUCCESS]: {result}")
        return result
        
    except Exception as e:
        print(f"[GROQ VISION EXCEPTION]: {e}")
        return None

def ask_cohere(user_message, sender_phone):
    history = chat_histories.get(sender_phone, [])
    
    url = "https://api.cohere.ai/v1/chat"
    headers = {
        "Authorization": f"Bearer {COHERE_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "command-r",
        "message": user_message,
        "preamble": get_system_prompt(),
        "chat_history": history,
        "temperature": 0.1
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=50)
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
    bot_reply = ask_cohere(user_text, sender_phone)
    
    # Kitchen Tag Alert
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

    # Staff Tag Alert
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
    
    bot_reply = bot_reply.replace("[CHECKIN_ALERT: Room <room_number> | Documents Shared]", "").strip()
    send_whatsapp_message(sender_phone, bot_reply)

# ==========================================
# 4. WEBHOOK & HEALTH ENDPOINTS
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

        if message_id:
            mark_message_as_read(message_id)

        # 1. Text Messages
        if msg_type == "text":
            user_text = message.get("text", {}).get("body", "")
            process_and_reply(user_text, sender_phone)

        # 2. Voice Notes (Groq Whisper)
        elif msg_type in ["audio", "voice"]:
            audio_id = message.get("audio", {}).get("id") or message.get("voice", {}).get("id")
            transcribed_text = transcribe_audio_groq(audio_id)
            if transcribed_text:
                process_and_reply(transcribed_text, sender_phone)
            else:
                send_whatsapp_message(sender_phone, "Voice note clear nahi tha, please try again.")

        # 3. ID Document Verification (Groq Vision)
        elif msg_type == "image":
            image_id = message.get("image", {}).get("id")
            verification_result = verify_document_groq(image_id)

            if verification_result and verification_result.startswith("VALID"):
                send_whatsapp_message(
                    sender_phone,
                    "Thank you! 🙏 Aapka ID document verify ho gaya hai. Pre-check-in register update kar diya gaya hai."
                )
                staff_doc_msg = (
                    f"🪪 *NEW GUEST ID VERIFIED*\n\n"
                    f"📋 *Doc Details:* {verification_result}\n"
                    f"📞 *Guest Contact:* +{sender_phone}\n\n"
                    f"✅ Pre-check-in verified."
                )
                send_whatsapp_message(STAFF_PHONE, staff_doc_msg)

            elif verification_result and verification_result.startswith("INVALID"):
                reason = verification_result.split("REASON:")[1].strip().lower() if "REASON:" in verification_result else ""
                
                if any(k in reason for k in ["blur", "unreadable", "clear", "quality", "dark"]):
                    reply_msg = "Aapki bheji gayi photo clear nahi hai ya text padha nahi ja raha. Kripya saaf photo dobara bhejein."
                else:
                    reply_msg = "Yeh valid Government ID proof nahi lag raha hai. Kripya Aadhaar, Driving License, Passport ya Voter ID share karein."

                send_whatsapp_message(sender_phone, reply_msg)

            else:
                send_whatsapp_message(
                    sender_phone,
                    "Photo verify nahi ho paayi. Kripya saaf photo dobara send karein."
                )

        # 4. Location Navigation
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
# 5. EXECUTION ENTRY POINT
# ==========================================
if __name__ == "__main__":
    threading.Thread(target=keep_awake_ping, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
