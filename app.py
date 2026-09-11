import os
import re
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
STAFF_PHONE = os.getenv("STAFF_PHONE", "919058514488")

HOTEL_LAT = "29.9530"
HOTEL_LON = "78.1700"

RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")
chat_histories = {}

# ==========================================
# 2. FILE-BASED SYSTEM PROMPT LOADER
# ==========================================
def get_system_prompt():
    file_path = os.path.join(os.path.dirname(__file__), "hotel_data.txt")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"[PROMPT ERROR]: {e}", flush=True)
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
            print(f"[KEEP-ALIVE ERROR]: {e}", flush=True)
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
        print(f"[READ TICK ERROR]: {e}", flush=True)

def send_whatsapp_message(to_number, text):
    # Clean phone number (strip spaces, +, hyphens)
    clean_number = re.sub(r"\D", "", str(to_number))
    
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": clean_number,
        "type": "text",
        "text": {"body": text}
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=12)
        res_json = res.json()
        if res.status_code != 200:
            print(f"[WHATSAPP DISPATCH ERROR] Status: {res.status_code} | Target: {clean_number} | Body: {res_json}", flush=True)
        else:
            print(f"[WHATSAPP DISPATCH SUCCESS] Target: {clean_number}", flush=True)
        return res_json
    except Exception as e:
        print(f"[SEND MSG EXCEPTION]: {e}", flush=True)
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
        print(f"[MEDIA DOWNLOAD ERROR]: {e}", flush=True)
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
        print(f"[WHISPER ERROR]: {e}", flush=True)
        return None

def verify_document_groq(image_id):
    try:
        image_content = download_media(image_id)
        if not image_content:
            print("[VISION ERROR]: Media download failed", flush=True)
            return None

        base64_image = base64.b64encode(image_content).decode("utf-8")

        prompt = (
            "You are a Hotel Document Verification Assistant. "
            "Examine this image. Determine if this is a valid Indian Government ID Proof "
            "(Aadhaar Card, e-Aadhaar, Voter ID, Driving License, or Passport). "
            "Do NOT print any numeric identity numbers. "
            "If valid Govt ID, reply strictly: VALID | ID_TYPE: Aadhaar/DL/Passport/VoterID | NAME: <guest name or Not Visible> "
            "If invalid, blurry, or not Govt ID, reply strictly: INVALID | REASON: <blurry or not_govt_id>"
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

        res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=30)
        
        if res.status_code != 200:
            print(f"[GROQ VISION HTTP FAIL] Status: {res.status_code} | Body: {res.text}", flush=True)
            return None

        data = res.json()
        result = data["choices"][0]["message"]["content"].strip()
        print(f"[GROQ VISION RESULT]: {result}", flush=True)
        return result
    except Exception as e:
        print(f"[GROQ VISION EXCEPTION]: {e}", flush=True)
        return None

def ask_cohere(user_message, sender_phone):
    history = chat_histories.get(sender_phone, [])
    
    url = "https://api.cohere.ai/v1/chat"
    headers = {
        "Authorization": f"Bearer {COHERE_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "message": user_message,
        "preamble": get_system_prompt(),
        "chat_history": history,
        "temperature": 0.1
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=50)
        
        if response.status_code != 200:
            print(f"[COHERE HTTP FAIL] Status: {response.status_code} | Body: {response.text}", flush=True)
            return "Namaste! Room number batayein aur aapko kya order karna hai?"

        res_data = response.json()
        reply_text = res_data.get("text", "").strip()
        
        if not reply_text:
            return "Namaste! Kripya batayein mai aapki kya madad kar sakta hoon?"
        
        history.append({"role": "USER", "message": user_message})
        history.append({"role": "CHATBOT", "message": reply_text})
        chat_histories[sender_phone] = history[-6:]
        
        return reply_text
    except Exception as e:
        print(f"[COHERE EXCEPTION]: {e}", flush=True)
        return "Namaste! Kripya batayein aapko kya chahiye?"

def process_and_reply(user_text, sender_phone):
    bot_reply = ask_cohere(user_text, sender_phone)
    print(f"[COHERE RAW REPLY for {sender_phone}]: {bot_reply}", flush=True)

    # 1. Kitchen Alert Routing
    if "[KITCHEN_ALERT:" in bot_reply:
        match = re.search(r"\[KITCHEN_ALERT:\s*(.*?)\]", bot_reply)
        order_details = match.group(1) if match else "New Order"
        bot_reply = re.sub(r"\[KITCHEN_ALERT:\s*.*?\]", "", bot_reply).strip()
        
        kitchen_msg = (
            f"🍳 *NEW ROOM SERVICE ORDER*\n\n"
            f"📋 *Details:* {order_details}\n"
            f"📞 *Guest Contact:* +{sender_phone}\n\n"
            f"⚡ Order deliver karein!"
        )
        send_whatsapp_message(KITCHEN_PHONE, kitchen_msg)
        
        if not bot_reply:
            bot_reply = "Ji, aapka order note kar liya gaya hai aur jald room me deliver ho jayega."

    # 2. Staff Alert Routing
    if "[STAFF_ALERT:" in bot_reply:
        match = re.search(r"\[STAFF_ALERT:\s*(.*?)\]", bot_reply)
        service_details = match.group(1) if match else "Staff Assistance Requested"
        bot_reply = re.sub(r"\[STAFF_ALERT:\s*.*?\]", "", bot_reply).strip()
        
        staff_msg = (
            f"🛎️ *STAFF ALERT*\n\n"
            f"📌 *Details:* {service_details}\n"
            f"📞 *Guest Contact:* +{sender_phone}\n\n"
            f"⚡ Turant attend karein!"
        )
        send_whatsapp_message(STAFF_PHONE, staff_msg)

        if not bot_reply:
            bot_reply = "Ji, staff ko request bhej di gayi hai."
    
    # Strip any rogue bracket tags
    bot_reply = re.sub(r"\[.*?\]", "", bot_reply).strip()
    
    if bot_reply:
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

        # 1. Text Message
        if msg_type == "text":
            user_text = message.get("text", {}).get("body", "")
            process_and_reply(user_text, sender_phone)

        # 2. Voice Notes
        elif msg_type in ["audio", "voice"]:
            audio_id = message.get("audio", {}).get("id") or message.get("voice", {}).get("id")
            transcribed_text = transcribe_audio_groq(audio_id)
            if transcribed_text:
                process_and_reply(transcribed_text, sender_phone)
            else:
                send_whatsapp_message(sender_phone, "Voice note clear nahi tha, please try again.")

        # 3. Document ID Verification
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
                    "Photo process karne me samasya aayi. Kripya document ki saaf photo dobara send karein."
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
        print(f"[WEBHOOK PROCESS ERROR]: {e}", flush=True)

    return jsonify({"status": "success"}), 200

# ==========================================
# 5. EXECUTION ENTRY POINT
# ==========================================
if __name__ == "__main__":
    threading.Thread(target=keep_awake_ping, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
