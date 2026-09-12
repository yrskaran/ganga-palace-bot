import os
import re
import csv
import io
import base64
import time
import threading
from datetime import datetime
import pytz
import requests
from flask import Flask, request, jsonify

# ==========================================
# 1. INITIALIZE APP & CONFIGURATION
# ==========================================
app = Flask(__name__)

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
COHERE_API_KEY = os.getenv("COHERE_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

KITCHEN_PHONE = os.getenv("KITCHEN_PHONE", "919058514478")
STAFF_PHONE = os.getenv("STAFF_PHONE", "919058514488")

HOTEL_LAT = "29.9530"
HOTEL_LON = "78.1700"
SHEET_ID = "1E7iI0vSkRlwpiog-GUjN7Gfh35REAhfY_yVG0t63wqY"

RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "https://ganga-palace-bot.onrender.com")

chat_histories = {}
processed_msg_ids = set()

# In-Memory Cache for Sheet & Concierge Alerts
sheet_cache = {"data": [], "last_fetched": 0}
CACHE_TTL_SECONDS = 45

welcomed_guests = set()
alerts_sent_today = {
    "breakfast": None,
    "tourism": None,
    "aarti": None,
    "dinner": None
}

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
# 3. HELPER FUNCTIONS & SHEET SYNC
# ==========================================
def keep_awake_ping():
    """Pings the health endpoint every 8 minutes to prevent sleep."""
    time.sleep(15)
    while True:
        try:
            target_url = f"{RENDER_EXTERNAL_URL.rstrip('/')}/health"
            res = requests.get(target_url, timeout=15)
            print(f"[KEEP-ALIVE PING]: Status {res.status_code}", flush=True)
        except Exception as e:
            print(f"[KEEP-ALIVE PING FAIL]: {e}", flush=True)
        time.sleep(8 * 60)

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
            print(f"[WHATSAPP DISPATCH ERROR] Target: {clean_number} | Body: {res_json}", flush=True)
        return res_json
    except Exception as e:
        print(f"[SEND MSG EXCEPTION]: {e}", flush=True)
        return None

def download_media(media_id):
    try:
        meta_url = f"https://graph.facebook.com/v20.0/{media_id}"
        res = requests.get(meta_url, headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}, timeout=10)
        media_url = res.json().get("url")
        if not media_url:
            return None
        
        file_res = requests.get(
            media_url,
            headers={
                "Authorization": f"Bearer {WHATSAPP_TOKEN}",
                "User-Agent": "curl/7.68.0"
            },
            timeout=20
        )
        if file_res.status_code == 200:
            return file_res.content
        return None
    except Exception as e:
        print(f"[MEDIA DOWNLOAD EXCEPTION]: {e}", flush=True)
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
            return None

        base64_image = base64.b64encode(image_content).decode("utf-8")
        prompt = (
            "You are a Hotel Document Verification Assistant. "
            "Determine if this image is a valid Indian Government ID Proof "
            "(Aadhaar Card, PAN Card, Voter ID, Driving License, or Passport). "
            "Never output identification numbers. "
            "If valid Govt ID, reply strictly: VALID | ID_TYPE: <type> | NAME: <guest name or Not Visible> "
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
            "temperature": 0.1,
            "max_tokens": 100
        }

        res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=30)
        if res.status_code != 200:
            return None

        return res.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[GROQ VISION EXCEPTION]: {e}", flush=True)
        return None

def fetch_sheet_records():
    """Caches sheet in memory for CACHE_TTL_SECONDS to avoid API lag"""
    now = time.time()
    if sheet_cache["data"] and (now - sheet_cache["last_fetched"] < CACHE_TTL_SECONDS):
        return sheet_cache["data"]

    csv_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"
    try:
        response = requests.get(csv_url, timeout=6)
        if response.status_code == 200:
            content = response.content.decode("utf-8")
            reader = list(csv.DictReader(io.StringIO(content)))
            sheet_cache["data"] = reader
            sheet_cache["last_fetched"] = now
            return reader
    except Exception as e:
        print(f"[SHEET CACHE REFRESH ERROR]: {e}", flush=True)
    
    return sheet_cache.get("data", [])

def get_guest_stay_status(sender_phone):
    """Matches last 10 digits against cached sheet records"""
    clean_sender = re.sub(r"\D", "", str(sender_phone))[-10:]
    records = fetch_sheet_records()
    
    for row in records:
        sheet_phone = re.sub(r"\D", "", str(row.get("Phone", "")))[-10:]
        status = str(row.get("Status", "")).strip().upper()
        
        if sheet_phone and sheet_phone == clean_sender and status == "CHECKED_IN":
            return {
                "is_inhouse": True,
                "room": str(row.get("Room", "")).strip(),
                "name": str(row.get("Guest Name", "")).strip()
            }
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
        response = requests.post(url, json=payload, headers=headers, timeout=25)
        if response.status_code != 200:
            return "Namaste! Batayein mai aapki kya madad kar sakta hoon?"

        reply_text = response.json().get("text", "").strip()
        if not reply_text:
            return "Namaste! Batayein mai aapki kya madad kar sakta hoon?"
        
        history.append({"role": "USER", "message": user_message})
        history.append({"role": "CHATBOT", "message": reply_text})
        chat_histories[sender_phone] = history[-6:]
        return reply_text
    except Exception as e:
        print(f"[COHERE EXCEPTION]: {e}", flush=True)
        return "Namaste! Kripya batayein aapko kya chahiye?"

def process_and_reply(user_text, sender_phone):
    guest_info = get_guest_stay_status(sender_phone)
    
    # Block fake orders from outside guests
    service_keywords = ["order", "chai", "tea", "roti", "khana", "towel", "room service", "cleaning", "paani", "water"]
    is_service_query = any(w in user_text.lower() for w in service_keywords)
    
    if not guest_info and is_service_query:
        reject_reply = (
            "Namaste! 🙏 Hamari room service aur housekeeping suvidha sirf hotel me "
            "stay kar rahe registered guests ke liye hai.\n\n"
            "Agar aap hamare hotel me ruke hain, toh kripya reception counter par contact karke apna number register karwayein."
        )
        send_whatsapp_message(sender_phone, reject_reply)
        return  # Stop here, preventing double replies

    # Append guest context
    prompt_input = user_text
    if guest_info:
        prompt_input = f"[IN-HOUSE GUEST: Room {guest_info['room']} | Name: {guest_info['name']}] {user_text}"

    bot_reply = ask_cohere(prompt_input, sender_phone)
    print(f"[COHERE REPLY for {sender_phone}]: {bot_reply}", flush=True)

    # 1. Kitchen Alert
    if "[KITCHEN_ALERT:" in bot_reply:
        match = re.search(r"\[KITCHEN_ALERT:\s*(.*?)\]", bot_reply)
        order_details = match.group(1) if match else "New Order"
        bot_reply = re.sub(r"\[KITCHEN_ALERT:\s*.*?\]", "", bot_reply).strip()
        
        room_tag = f"Room {guest_info['room']} ({guest_info['name']})" if guest_info else "Unverified Room"
        kitchen_msg = (
            f"🍳 *NEW ROOM SERVICE ORDER*\n\n"
            f"📌 *Location:* {room_tag}\n"
            f"📋 *Details:* {order_details}\n"
            f"📞 *Guest Contact:* +{sender_phone}\n\n"
            f"⚡ Order deliver karein!"
        )
        send_whatsapp_message(KITCHEN_PHONE, kitchen_msg)
        if not bot_reply:
            bot_reply = f"Ji, aapka order note ho gaya hai aur jald {room_tag} me deliver kar diya jayega."

    # 2. Staff Alert
    if "[STAFF_ALERT:" in bot_reply:
        match = re.search(r"\[STAFF_ALERT:\s*(.*?)\]", bot_reply)
        service_details = match.group(1) if match else "Staff Assistance Requested"
        bot_reply = re.sub(r"\[STAFF_ALERT:\s*.*?\]", "", bot_reply).strip()
        
        room_tag = f"Room {guest_info['room']} ({guest_info['name']})" if guest_info else "Unverified Room"
        staff_msg = (
            f"🛎️ *STAFF ALERT*\n\n"
            f"📌 *Location:* {room_tag}\n"
            f"📋 *Details:* {service_details}\n"
            f"📞 *Guest Contact:* +{sender_phone}\n\n"
            f"⚡ Turant attend karein!"
        )
        send_whatsapp_message(STAFF_PHONE, staff_msg)
        if not bot_reply:
            bot_reply = "Ji, staff ko request bhej di gayi hai."

    bot_reply = re.sub(r"\[.*?\]", "", bot_reply).strip()
    if bot_reply:
        send_whatsapp_message(sender_phone, bot_reply)

def handle_incoming_async(message, sender_phone, msg_type):
    try:
        if msg_type == "text":
            user_text = message.get("text", {}).get("body", "")
            process_and_reply(user_text, sender_phone)

        elif msg_type in ["audio", "voice"]:
            audio_id = message.get("audio", {}).get("id") or message.get("voice", {}).get("id")
            transcribed_text = transcribe_audio_groq(audio_id)
            if transcribed_text:
                process_and_reply(transcribed_text, sender_phone)
            else:
                send_whatsapp_message(sender_phone, "Voice note clear nahi tha, kripya dobara bhejiyega.")

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
                if any(k in reason for k in ["blur", "unreadable", "clear", "quality", "dark", "upside"]):
                    reply_msg = "Aapki bheji gayi photo clear nahi hai ya text padha nahi ja raha. Kripya saaf photo dobara bhejein."
                else:
                    reply_msg = "Yeh valid Government ID proof nahi lag raha hai. Kripya Aadhaar, PAN Card, Driving License ya Passport share karein."
                send_whatsapp_message(sender_phone, reply_msg)
            else:
                send_whatsapp_message(sender_phone, "Photo process karne me samasya aayi. Kripya document ki saaf photo dobara send karein.")

        elif msg_type == "location":
            loc_data = message.get("location", {})
            user_lat = loc_data.get("latitude")
            user_lon = loc_data.get("longitude")
            maps_route_url = f"https://www.google.com/maps/dir/?api=1&origin={user_lat},{user_lon}&destination={HOTEL_LAT},{HOTEL_LON}"
            nav_reply = f"📍 *Hotel Navigation Route:*\n{maps_route_url}\n\nIs link par click karke aap direct hotel route dekh sakte hain."
            send_whatsapp_message(sender_phone, nav_reply)

    except Exception as e:
        print(f"[ASYNC WORKER ERROR]: {e}", flush=True)

# ==========================================
# 4. CONCIERGE & CHECK-IN AUTOMATIONS
# ==========================================
def send_checkin_feedback(phone, name, room):
    """Waits 30 minutes and sends comfort check message"""
    time.sleep(30 * 60)
    guest = get_guest_stay_status(phone)
    if guest and guest["is_inhouse"]:
        feedback_msg = (
            f"Namaste {name} ji! 🙏\n\n"
            f"Aapko Room {room} kaisa laga? Sab theek aur comfortable hai na?\n\n"
            f"Agar aapko extra towel, paani, chai ya kisi bhi cheez ki zaroorat ho, "
            f"toh aap mujhe yahan WhatsApp par bata sakte hain. Have a wonderful stay! 🌸"
        )
        send_whatsapp_message(phone, feedback_msg)
        print(f"[FEEDBACK SENT]: Delivered to {name} (Room {room})", flush=True)

def monitor_new_checkins():
    """Monitors Google Sheet for new CHECKED_IN guests for instant Welcome & 30-min Feedback"""
    while True:
        try:
            records = fetch_sheet_records()
            for row in records:
                phone = re.sub(r"\D", "", str(row.get("Phone", "")))[-10:]
                status = str(row.get("Status", "")).strip().upper()
                name = str(row.get("Guest Name", "")).strip()
                room = str(row.get("Room", "")).strip()

                if status == "CHECKED_IN" and phone and (phone not in welcomed_guests):
                    # 1. Instant Welcome Message
                    welcome_msg = (
                        f"Welcome to Hotel Ganga View, {name} ji! 🏨✨\n\n"
                        f"Aapka check-in Room {room} me complete ho gaya hai.\n"
                        f"Wi-Fi Password: *Ganga@2026*\n"
                        f"Room service ya kisi bhi sahayata ke liye bas yahan message karein. Namaste! 🙏"
                    )
                    send_whatsapp_message(phone, welcome_msg)
                    welcomed_guests.add(phone)
                    print(f"[WELCOME SENT]: {name} (Room {room})", flush=True)

                    # 2. Schedule 30-Minute Feedback
                    threading.Thread(
                        target=send_checkin_feedback,
                        args=(phone, name, room),
                        daemon=True
                    ).start()
        except Exception as e:
            print(f"[CHECKIN MONITOR ERROR]: {e}", flush=True)
            
        time.sleep(60)

def broadcast_to_inhouse_guests(message_template_fn):
    """Broadcasts targeted message only to currently CHECKED_IN guests"""
    records = fetch_sheet_records()
    for row in records:
        phone = re.sub(r"\D", "", str(row.get("Phone", "")))[-10:]
        status = str(row.get("Status", "")).strip().upper()
        name = str(row.get("Guest Name", "")).strip()
        room = str(row.get("Room", "")).strip()

        if status == "CHECKED_IN" and phone:
            msg = message_template_fn(name, room)
            send_whatsapp_message(phone, msg)
            time.sleep(1)

def daily_concierge_scheduler():
    """Triggers timely concierge notifications throughout the day (IST)"""
    ist = pytz.timezone("Asia/Kolkata")
    
    while True:
        try:
            now = datetime.now(ist)
            today_str = now.strftime("%Y-%m-%d")
            current_time_str = now.strftime("%H:%M")

            # 1. 08:00 AM - Breakfast Buffet Alert
            if current_time_str == "08:00" and alerts_sent_today["breakfast"] != today_str:
                broadcast_to_inhouse_guests(lambda name, room: (
                    f"Shubh Prabhat {name} ji! ☀️\n\n"
                    f"Aapka fresh breakfast buffet dining hall me taiyar hai.\n"
                    f"⏰ *Timings:* 8:30 AM se 10:30 AM\n\n"
                    f"Agar aap room me breakfast mangwana chahte hain, toh yahan reply karein. Have a great morning! 🍳"
                ))
                alerts_sent_today["breakfast"] = today_str

            # 2. 10:30 AM - Sightseeing & Tourist Guide Alert
            elif current_time_str == "10:30" and alerts_sent_today["tourism"] != today_str:
                broadcast_to_inhouse_guests(lambda name, room: (
                    f"Har Har Gange {name} ji! 🚩\n\n"
                    f"Agar aap aaj Haridwar darshan ka plan bana rahe hain:\n"
                    f"🚠 *Mansa Devi & Chandi Devi:* Ropeway 11:00 AM se 4:00 PM tak best rehta hai.\n"
                    f"🛕 *Daksha Mahadev Temple:* Dopahar ka samay darshan ke liye sabse shant rehta hai.\n\n"
                    f"Taxi booking ya guidance ke liye reception se contact karein ya yahan batayein!"
                ))
                alerts_sent_today["tourism"] = today_str

            # 3. 05:00 PM - Har Ki Pauri Ganga Aarti Alert
            elif current_time_str == "17:00" and alerts_sent_today["aarti"] != today_str:
                broadcast_to_inhouse_guests(lambda name, room: (
                    f"Har Har Gange {name} ji! 🪔✨\n\n"
                    f"Har Ki Pauri par *Sandhya Ganga Aarti* shaam 6:15 PM se shuru hoti hai.\n\n"
                    f"📌 *Tip:* Bheed se bachne aur achhe darshan ke liye kripya 5:30 PM tak ghat par pahunch jayein.\n\n"
                    f"Aapke hotel se Har Ki Pauri lagbhag 10-15 minute ki doori par hai. Shubh Darshan! 🙏"
                ))
                alerts_sent_today["aarti"] = today_str

            # 4. 08:00 PM - Dinner Reminder Alert
            elif current_time_str == "20:00" and alerts_sent_today["dinner"] != today_str:
                broadcast_to_inhouse_guests(lambda name, room: (
                    f"Namaste {name} ji! 🌙\n\n"
                    f"Hotel Ganga View me dinner serve hona shuru ho gaya hai.\n"
                    f"⏰ *Restaurant Timings:* 8:00 PM se 10:30 PM\n\n"
                    f"Agar aap Room {room} me khana mangwana chahte hain, toh bas yahan apna order likhkar bhej dein!"
                ))
                alerts_sent_today["dinner"] = today_str

        except Exception as e:
            print(f"[CONCIERGE SCHEDULER ERROR]: {e}", flush=True)

        time.sleep(30)

# ==========================================
# 5. WEBHOOK & ENDPOINTS
# ==========================================
@app.route("/", methods=["GET"])
def index():
    return "Hotel Ganga View WhatsApp AI Receptionist is running live!", 200

@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "active", "service": "hotel-bot"}), 200

@app.route("/webhook", methods=["GET"], strict_slashes=False)
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

@app.route("/webhook", methods=["POST"], strict_slashes=False)
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

        if message_id in processed_msg_ids:
            return jsonify({"status": "already_processed"}), 200
            
        if message_id:
            processed_msg_ids.add(message_id)
            if len(processed_msg_ids) > 500:
                processed_msg_ids.pop()
            mark_message_as_read(message_id)

        threading.Thread(
            target=handle_incoming_async,
            args=(message, sender_phone, msg_type),
            daemon=True
        ).start()

    except Exception as e:
        print(f"[WEBHOOK PROCESS ERROR]: {e}", flush=True)

    return jsonify({"status": "success"}), 200

# ==========================================
# 6. ENTRY POINT
# ==========================================
if __name__ == "__main__":
    threading.Thread(target=keep_awake_ping, daemon=True).start()
    threading.Thread(target=monitor_new_checkins, daemon=True).start()
    threading.Thread(target=daily_concierge_scheduler, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
