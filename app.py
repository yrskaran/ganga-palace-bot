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

# Separate Alert Numbers
KITCHEN_PHONE = os.getenv("KITCHEN_PHONE", "919058514478")
STAFF_PHONE = os.getenv("STAFF_PHONE", "919058514488")

# Hotel Info & Coordinates (Haridwar)
HOTEL_NAME = "Hotel Ganga View"
HOTEL_LAT = "29.9530"
HOTEL_LON = "78.1700"

# In-memory chat history (per user)
chat_histories = {}

# ==========================================
# 2. MASTER SYSTEM PROMPT
# ==========================================
SYSTEM_PROMPT = f"""
Aap '{HOTEL_NAME}' (Haridwar) ke polite aur professional AI Receptionist aur Local Tourist Guide hain.

MUKHYA NIYAM & KARYA:
1. PURE VEGETARIAN ONLY (HARIDWAR POLICY):
   - Haridwar me non-veg strictly mana hai. Keval shuddh satvik shakahari bhojan uplabdh hai.
   - Menu Options: Chai (₹30), Masala Chai (₹40), Veg Fried Rice (₹150), Dal Makhani (₹180), Paneer Butter Masala (₹220), Tandoori Roti (₹15), Mineral Water (₹20).

2. KITCHEN ORDER CONFIRMATION TAG:
   - Jab guest room number aur food order confirm kare:
     End me ye tag likhein: [KITCHEN_ALERT: Room <room_number> | Items: <order_items>]

3. STAFF SERVICE ALERT TAG:
   - Jab guest housekeeping, cleaning, extra towel/blanket, luggage help, ya checkout/staff assistance maange:
     End me ye tag likhein: [STAFF_ALERT: Room <room_number> | Service: <request_details>]

4. LOCAL TOURIST GUIDE:
   - Har Ki Pauri Sandhya Aarti: 5:15 PM tak pahunchein.
   - Mansa Devi & Chandi Devi Ropeway: Subah 7:00 AM se open.
   - Food Outlets: Mohan Ji Puri Wale aur Pandit Sevaram Doodh Jalebi.
   - Local Transport: Battery rickshaw (E-rickshaw) suggest karein.

5. TONE:
   - Namaskar sahit aadarpoorvak Hinglish/Hindi me crisp jawab dein.
"""

# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================
def send_whatsapp_message(to_number, text):
    """WhatsApp Cloud API se message bhejne ka function"""
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
        print(f"Failed to send message: {e}")
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
        "temperature": 0.3
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        res_data = response.json()
        reply_text = res_data.get("text", "Kshama karein, mai abhi samajh nahi paya.")
        
        # History update
        history.append({"role": "USER", "message": user_message})
        history.append({"role": "CHATBOT", "message": reply_text})
        chat_histories[sender_phone] = history[-6:]
        
        return reply_text
    except Exception as e:
        print(f"Cohere error: {e}")
        return "Namaste! Hamari service me thodi samasya aa rahi hai, kripya thodi der me koshish karein."

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
        # FLOW 1: TEXT MESSAGES (FOOD / STAFF / CHAT)
        # --------------------------------------------------
        if msg_type == "text":
            user_text = message.get("text", {}).get("body", "")
            bot_reply = ask_cohere(user_text, sender_phone)
            
            # 1. KITCHEN ORDER ALERT (9058514478)
            if "[KITCHEN_ALERT:" in bot_reply:
                order_details = bot_reply.split("[KITCHEN_ALERT:")[1].split("]")[0].strip()
                bot_reply = bot_reply.split("[KITCHEN_ALERT:")[0].strip()
                
                kitchen_msg = (
                    f"🍳 *NEW ROOM SERVICE ORDER*\n\n"
                    f"📋 *Details:* {order_details}\n"
                    f"📞 *Guest Phone:* +{sender_phone}\n\n"
                    f"⚡ Kripya turant taiyar karke bhejwayein!"
                )
                send_whatsapp_message(KITCHEN_PHONE, kitchen_msg)

            # 2. STAFF / HOUSEKEEPING ALERT (9058514488)
            if "[STAFF_ALERT:" in bot_reply:
                service_details = bot_reply.split("[STAFF_ALERT:")[1].split("]")[0].strip()
                bot_reply = bot_reply.split("[STAFF_ALERT:")[0].strip()
                
                staff_msg = (
                    f"🛎️ *HOTEL STAFF / HOUSEKEEPING ALERT*\n\n"
                    f"📌 *Task:* {service_details}\n"
                    f"📞 *Guest Contact:* +{sender_phone}\n\n"
                    f"⚡ Kripya turant attend karein!"
                )
                send_whatsapp_message(STAFF_PHONE, staff_msg)
            
            # Guest ko clean reply bhejo
            send_whatsapp_message(sender_phone, bot_reply)

        # --------------------------------------------------
        # FLOW 2: LOCATION SHARING & DIRECTIONS
        # --------------------------------------------------
        elif msg_type == "location":
            loc_data = message.get("location", {})
            user_lat = loc_data.get("latitude")
            user_lon = loc_data.get("longitude")
            
            maps_route_url = f"https://www.google.com/maps/dir/?api=1&origin={user_lat},{user_lon}&destination={HOTEL_LAT},{HOTEL_LON}"
            
            nav_prompt = (
                f"[SYSTEM: Guest ne apni live location share ki hai (Lat: {user_lat}, Lon: {user_lon}). "
                f"Google Maps Route Link: {maps_route_url}. "
                f"Guest ko polite tone me route link provide karein, "
                f"aur Haridwar ke Devpura Chowk / Valmiki Chowk ke hisab se battery rickshaw ki advice dein.]"
            )
            bot_reply = ask_cohere(nav_prompt, sender_phone)
            send_whatsapp_message(sender_phone, bot_reply)

    except Exception as e:
        print(f"Error processing webhook: {e}")

    return jsonify({"status": "success"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
