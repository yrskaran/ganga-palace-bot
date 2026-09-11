import os
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

# In-memory chat history (per user)
chat_histories = {}

# ==========================================
# 2. MASTER SYSTEM PROMPT
# ==========================================
SYSTEM_PROMPT = f"""
Aap '{HOTEL_NAME}' (Haridwar) ke polite aur professional AI Receptionist aur Local Concierge hain.

MUKHYA NIYAM:

1. STRICTLY PURE VEGETARIAN MENU (HARIDWAR POLICY):
   - Chai: Normal Chai (₹30), Masala Chai (₹40)
   - Roti/Breads: Tandoori Roti (₹15), Butter Roti (₹20), Butter Naan (₹45)
   - Paneer: Paneer Butter Masala (₹220), Matar Paneer (₹200), Kadhai Paneer (₹230), Shahi Paneer (₹220)
   - Dal: Dal Makhani (₹180), Dal Tadka (₹150)
   - Rice: Plain Rice (₹100), Veg Fried Rice (₹150), Jeera Rice (₹120)
   - Extras: Mineral Water (₹20)

2. FOOD ORDER RULES (NO GUESSWORK):
   - AMBIGUOUS DISH CLARIFICATION:
     * Agar guest sirf 'paneer' ya 'paneer ki sabji' bole, toh apne mann se koi dish select MAT karo.
     * Pehle options poochein: "Humare paas Paneer Butter Masala (₹220), Matar Paneer (₹200), Kadhai Paneer (₹230) aur Shahi Paneer (₹220) uplabdh hain. Aap kaun sa pasand karenge?"
     * Yahi rule Dal (Makhani ya Tadka) aur Chai (Normal ya Masala) par bhi lagayein.
   - MANDATORY ROOM NUMBER:
     * Agar dish final hai par room number nahi bataya, toh pehle room number poochein: "Ji bilkul, kripya apna Room Number bata dijiye taaki order confirm kiya ja sake."
     * Dish aur Room Number dono milne ke baad hi confirm karein aur aakhiri me ye exact tag lagayein:
       [KITCHEN_ALERT: Room <room_number> | Order: <items>]

3. STAFF & HOUSEKEEPING REQUESTS:
   - Towel, safai (cleaning), extra blanket, pani, ya luggage help ke liye:
     * Agar Room Number nahi pata, toh alert mat bhejo. Pehle room number poochein: "Ji zaroor, kripya apna Room Number bata dijiye taaki mai staff ko bhej sakun."
     * Room number milne par confirm karein aur aakhiri me ye exact tag lagayein:
       [STAFF_ALERT: Room <room_number> | Task: <service_details>]

4. LOCAL TOURIST GUIDANCE:
   - Har Ki Pauri Sandhya Aarti: 5:15 PM tak pahunchne ki salah dein.
   - Mansa Devi / Chandi Devi Ropeway: Subah 7:00 AM se open rehta hai.
   - Local Food Spots: Mohan Ji Puri Wale aur Pandit Sevaram Doodh Jalebi.

5. TONE:
   - Namaskar/Pranaam sahit shisht Hinglish ya Hindi me crisp jawab dein.
"""

# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================
def send_whatsapp_message(to_number, text):
    """WhatsApp Cloud API se message bhejne ka helper"""
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

def transcribe_audio_groq(audio_id):
    """WhatsApp se audio download karke Groq Whisper se Text me convert karna"""
    try:
        # Step 1: Media URL get karna
        media_url_res = requests.get(
            f"https://graph.facebook.com/v20.0/{audio_id}",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        )
        media_url = media_url_res.json().get("url")

        if not media_url:
            return None

        # Step 2: Audio file download karna
        audio_file_res = requests.get(
            media_url,
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        )

        # Step 3: Groq Whisper API ko bhejna
        files = {
            "file": ("audio.ogg", audio_file_res.content, "audio/ogg")
        }
        data = {
            "model": "whisper-large-v3",
            "language": "hi",  # Hindi / Hinglish transcription
            "response_format": "text"
        }
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}"
        }
        
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

def ask_cohere(user_message, sender_phone):
    """Cohere API se context-aware response generate karna"""
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
        
        # Rolling chat history (last 6 messages)
        history.append({"role": "USER", "message": user_message})
        history.append({"role": "CHATBOT", "message": reply_text})
        chat_histories[sender_phone] = history[-6:]
        
        return reply_text
    except Exception as e:
        print(f"Cohere API error: {e}")
        return "Namaste! Hamari service me thodi samasya aa rahi hai, kripya thodi der me dobara prayas karein."

def process_and_reply(user_text, sender_phone):
    """Text process karke Cohere reply aur Kitchen/Staff alert bhejne ka core function"""
    bot_reply = ask_cohere(user_text, sender_phone)
    
    # 1. Kitchen Order Alert (9058514478)
    if "[KITCHEN_ALERT:" in bot_reply:
        order_details = bot_reply.split("[KITCHEN_ALERT:")[1].split("]")[0].strip()
        bot_reply = bot_reply.split("[KITCHEN_ALERT:")[0].strip()
        
        kitchen_msg = (
            f"🍳 *NEW ROOM SERVICE ORDER*\n\n"
            f"📋 *Details:* {order_details}\n"
            f"📞 *Guest Phone:* +{sender_phone}\n\n"
            f"⚡ Kripya order taiyar karke deliver karein!"
        )
        send_whatsapp_message(KITCHEN_PHONE, kitchen_msg)

    # 2. Staff / Housekeeping Alert (9058514488)
    if "[STAFF_ALERT:" in bot_reply:
        service_details = bot_reply.split("[STAFF_ALERT:")[1].split("]")[0].strip()
        bot_reply = bot_reply.split("[STAFF_ALERT:")[0].strip()
        
        staff_msg = (
            f"🛎️ *STAFF / HOUSEKEEPING ALERT*\n\n"
            f"📌 *Details:* {service_details}\n"
            f"📞 *Guest Phone:* +{sender_phone}\n\n"
            f"⚡ Kripya turant attend karein!"
        )
        send_whatsapp_message(STAFF_PHONE, staff_msg)
    
    send_whatsapp_message(sender_phone, bot_reply)

# ==========================================
# 4. WEBHOOK ROUTES
# ==========================================
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

        # --------------------------------------------------
        # FLOW 1: TEXT MESSAGES
        # --------------------------------------------------
        if msg_type == "text":
            user_text = message.get("text", {}).get("body", "")
            process_and_reply(user_text, sender_phone)

        # --------------------------------------------------
        # FLOW 2: VOICE NOTES / AUDIO (GROQ WHISPER)
        # --------------------------------------------------
        elif msg_type in ["audio", "voice"]:
            audio_id = message.get("audio", {}).get("id") or message.get("voice", {}).get("id")
            transcribed_text = transcribe_audio_groq(audio_id)
            
            if transcribed_text:
                process_and_reply(transcribed_text, sender_phone)
            else:
                send_whatsapp_message(sender_phone, "Kshama karein, aapka voice note saaf sunayi nahi diya. Kripya dobara bhejein ya text message karein.")

        # --------------------------------------------------
        # FLOW 3: LOCATION SHARING (DIRECT NAVIGATION LINK)
        # --------------------------------------------------
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
                f"Upar diye gaye link par click karke aap seedha hotel ka Google Maps route follow kar sakte hain, "
                f"ya apne auto/cab driver ko yeh route dikha dijiye.\n\n"
                f"Hotel pahunchne me koi asuvidha ho toh batayein!"
            )
            send_whatsapp_message(sender_phone, nav_reply)

    except Exception as e:
        print(f"Error processing webhook: {e}")

    return jsonify({"status": "success"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
