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

# Alert Numbers (Kitchen & Staff)
KITCHEN_PHONE = os.getenv("KITCHEN_PHONE", "919058514478")
STAFF_PHONE = os.getenv("STAFF_PHONE", "919058514488")

# Hotel Information (Haridwar)
HOTEL_NAME = "Hotel Ganga View"
HOTEL_LAT = "29.9530"
HOTEL_LON = "78.1700"

# In-memory chat history (per user)
chat_histories = {}

# ==========================================
# 2. MASTER SYSTEM PROMPT (STRICT RULES)
# ==========================================
SYSTEM_PROMPT = f"""
Aap '{HOTEL_NAME}' (Haridwar) ke polite aur professional AI Receptionist aur Local Concierge hain.

MUKHYA NIYAM:

1. STRICTLY PURE VEGETARIAN (HARIDWAR POLICY):
   - Haridwar me non-veg strictly mana hai. Keval shuddh shakahari/satvik bhojan uplabdh hai.
   - Menu Options: Chai (₹30), Masala Chai (₹40), Veg Fried Rice (₹150), Dal Makhani (₹180), Paneer Butter Masala (₹220), Tandoori Roti (₹15), Mineral Water (₹20).

2. FOOD ORDER RULES & ALERT:
   - Jab koi khana/peena order kare, PEHLE UNKA ROOM NUMBER POOCHEIN agar unhone nahi bataya hai.
   - BINA ROOM NUMBER KE ORDER CONFIRM NA KAREIN.
   - Room number milne par confirm karein aur message ke aakhiri me ye exact tag lagayein:
     [KITCHEN_ALERT: Room <room_number> | Order: <items>]

3. STAFF & HOUSEKEEPING REQUESTS (MANDATORY ROOM NUMBER):
   - Agar guest towel, pani, safai (cleaning), luggage, blanket ya room service maangta hai:
     * AGAR ROOM NUMBER NAHI BATAYA HAI: Toh alert tag trigger NA karein. Pehle vinamrata se room number maangein: "Ji bilkul, kripya apna Room Number bata dijiye taaki mai staff ko turant bhej sakun."
     * JAB ROOM NUMBER MIL JAYE: Tab confirm karein aur message ke aakhiri me ye exact tag lagayein:
       [STAFF_ALERT: Room <room_number> | Task: <service_details>]

4. LOCAL TOURIST GUIDANCE:
   - Har Ki Pauri: Sandhya Aarti ke liye 5:15 PM tak pahunchne ki salah dein.
   - Mansa Devi / Chandi Devi Ropeway (Udan Khatola): Subah 7:00 AM se open rehta hai.
   - Local Food: Mohan Ji Puri Wale (Har Ki Pauri) aur Pandit Sevaram (Doodh Jalebi).

5. TONE:
   - Namaskar/Pranaam sahit shisht Hinglish ya Hindi me crisp aur helpful jawab dein.
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
        
        # Update rolling chat history
        history.append({"role": "USER", "message": user_message})
        history.append({"role": "CHATBOT", "message": reply_text})
        chat_histories[sender_phone] = history[-6:]
        
        return reply_text
    except Exception as e:
        print(f"Cohere API error: {e}")
        return "Namaste! Hamari service me thodi takneeki samasya aa rahi hai, kripya thodi der me message karein."

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
        # FLOW 1: TEXT MESSAGES (ORDERS, STAFF, CHAT)
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
                    f"📞 *Guest Contact:* +{sender_phone}\n\n"
                    f"⚡ Kripya order turant taiyar karke deliver karein!"
                )
                send_whatsapp_message(KITCHEN_PHONE, kitchen_msg)

            # 2. STAFF / HOUSEKEEPING ALERT (9058514488)
            if "[STAFF_ALERT:" in bot_reply:
                service_details = bot_reply.split("[STAFF_ALERT:")[1].split("]")[0].strip()
                bot_reply = bot_reply.split("[STAFF_ALERT:")[0].strip()
                
                staff_msg = (
                    f"🛎️ *STAFF / HOUSEKEEPING ALERT*\n\n"
                    f"📌 *Details:* {service_details}\n"
                    f"📞 *Guest Contact:* +{sender_phone}\n\n"
                    f"⚡ Kripya kamre me turant sahayata bhejein!"
                )
                send_whatsapp_message(STAFF_PHONE, staff_msg)
            
            send_whatsapp_message(sender_phone, bot_reply)

        # --------------------------------------------------
        # FLOW 2: LOCATION SHARING (DIRECT NAVIGATION, NO LLM)
        # --------------------------------------------------
        elif msg_type == "location":
            loc_data = message.get("location", {})
            user_lat = loc_data.get("latitude")
            user_lon = loc_data.get("longitude")
            
            maps_route_url = f"https://www.google.com/maps/dir/?api=1&origin={user_lat},{user_lon}&destination={HOTEL_LAT},{HOTEL_LON}"
            
            nav_reply = (
                f"Namaskar! 🙏 Aapki live location receive ho gayi hai.\n\n"
                f"📍 *Hotel Navigation Route Link:*\n"
                f"{maps_route_url}\n\n"
                f"🚗 *Directions:*\n"
                f"Upar diye gaye Google Maps link par click karke aap seedha hotel ka rasta follow kar sakte hain, "
                f"ya apne auto/cab driver ko yeh route dikha dijiye.\n\n"
                f"Hotel pahunchne me koi pareshani ho toh humein batayein!"
            )
            
            send_whatsapp_message(sender_phone, nav_reply)

    except Exception as e:
        print(f"Error processing webhook: {e}")

    return jsonify({"status": "success"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
