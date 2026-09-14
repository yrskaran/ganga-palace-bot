import os
import json
import re
from datetime import datetime
import requests
from flask import Flask, request, jsonify
import cohere
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# ==========================================
# ENVIRONMENT VARIABLES
# ==========================================
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "ganga_bot_secret_123")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "1357005434155447")
COHERE_API_KEY = os.getenv("COHERE_API_KEY")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Hotel Ganga Palace Orders")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")

co = cohere.Client(COHERE_API_KEY) if COHERE_API_KEY else None

# ==========================================
# GOOGLE SHEETS HELPER
# ==========================================
def get_sheet_client():
    if not GOOGLE_CREDS_JSON:
        return None
    try:
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        creds_dict = json.loads(GOOGLE_CREDS_JSON)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        return gspread.authorize(creds)
    except Exception as e:
        print(f"[SHEET CLIENT ERROR]: {str(e)}", flush=True)
        return None

def fetch_hotel_context_from_sheet():
    client = get_sheet_client()
    if not client:
        return ""
    try:
        sheet = client.open(GOOGLE_SHEET_NAME)
        worksheets = {ws.title: ws for ws in sheet.worksheets()}
        context_parts = []
        
        # 1. Rules Worksheet
        if "Rules" in worksheets:
            rules_data = worksheets["Rules"].get_all_values()
            rules_txt = "\n".join([" | ".join([c.strip() for c in r if c.strip()]) for r in rules_data if r])
            context_parts.append(f"HOTEL RULES & TIMINGS:\n{rules_txt}")
            
        # 2. Kitchen Menu Worksheet
        if "Menu" in worksheets:
            menu_data = worksheets["Menu"].get_all_values()
            menu_txt = "\n".join([" | ".join([c.strip() for c in r if c.strip()]) for r in menu_data if r])
            context_parts.append(f"KITCHEN MENU & PRICING:\n{menu_txt}")
            
        return "\n\n".join(context_parts)
    except Exception as e:
        print(f"[SHEET READ ERROR]: {str(e)}", flush=True)
        return ""

def log_interaction(sender, message, reply):
    client = get_sheet_client()
    if not client:
        return
    try:
        sheet = client.open(GOOGLE_SHEET_NAME)
        worksheets = {ws.title: ws for ws in sheet.worksheets()}
        ws = worksheets.get("Logs", sheet.sheet1)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ws.append_row([timestamp, sender, message, reply])
        print(f"[LOG OK] Saved interaction for {sender}", flush=True)
    except Exception as e:
        print(f"[LOG ERROR]: {str(e)}", flush=True)

def log_kitchen_order(sender, order_details):
    client = get_sheet_client()
    if not client:
        return
    try:
        sheet = client.open(GOOGLE_SHEET_NAME)
        worksheets = {ws.title: ws for ws in sheet.worksheets()}
        if "Kitchen_Orders" in worksheets:
            ws = worksheets["Kitchen_Orders"]
        else:
            ws = sheet.sheet1
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ws.append_row([timestamp, sender, order_details])
        print(f"[KITCHEN LOG OK] Saved food order for {sender}", flush=True)
    except Exception as e:
        print(f"[KITCHEN LOG ERROR]: {str(e)}", flush=True)

# ==========================================
# WHATSAPP SENDER
# ==========================================
def send_whatsapp_message(recipient_id, text):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient_id,
        "type": "text",
        "text": {"body": text}
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        if res.status_code == 200:
            print(f"[MSG DELIVERED OK] To: {recipient_id}", flush=True)
        else:
            print(f"[WHATSAPP ERROR {res.status_code}] {res.text}", flush=True)
    except Exception as e:
        print(f"[NETWORK ERROR]: {str(e)}", flush=True)

# ==========================================
# AI AGENT & AUTOMATED WORKFLOW ENGINE
# ==========================================
def generate_hotel_response(sender, user_text):
    text_lower = user_text.lower()
    
    # --- TRIGGER 1: MANUAL / SYSTEM CHECK-IN TRIGGER ---
    if "check in" in text_lower or "check-in" in text_lower or "checked in" in text_lower:
        return (
            "🏨 *Namaste & Welcome to Hotel Ganga Palace!*\n\n"
            "Aapka hamare yahan aana hamare liye anandmay hai. Aapka check-in complete ho chuka hai.\n\n"
            "🔑 *Hotel Quick Info:*\n"
            "📶 *Wi-Fi:* GangaPalace_Guest | *Pass:* Ganga@2026\n"
            "🍽️ *In-Room Dining:* 24/7 uplabdh hai (Tea, Snacks, Thali, etc.)\n"
            "🛕 *Ganga Aarti Timing:* Sham 6:00 PM se Har Ki Pauri par\n\n"
            "Kisi bhi room service ya sahayata ke liye bas yahan message karein. Aapka stay shubh ho! 🙏"
        )

    # --- TRIGGER 2: MANUAL / SYSTEM CHECK-OUT TRIGGER ---
    if "check out" in text_lower or "check-out" in text_lower or "checked out" in text_lower:
        return (
            "🙏 *Thank You for Staying at Hotel Ganga Palace!*\n\n"
            "Aapka check-out process initiate kar diya gaya hai. Hamare staff aapse reception par room keys collect kar lenge.\n\n"
            "🧾 *Settlement:* Kripya reception counter par final billing & settlement check kar lein.\n"
            "⭐ Hame aasha hai ki aapka anubhav sukhad raha hoga. Kripya apna anubhav share karein aur aage bhi sewa ka mauka dein.\n\n"
            "Shubh Yatra! Aapka safar mangalmay ho. ✨"
        )

    # --- TRIGGER 3: COHERE AI FOR KITCHEN BILL & INQUIRIES ---
    sheet_data = fetch_hotel_context_from_sheet()
    
    default_rules = """
    HOTEL: Hotel Ganga Palace
    ROOMS: Deluxe (₹2,500/night), Super Deluxe (₹3,500/night)
    KITCHEN MENU & ITEMS:
    - Masala Tea (₹25), Special Coffee (₹40)
    - Poha (₹60), Aloo Paratha with Curd (₹80)
    - Veg Thali Deluxe (Paneer, Dal Makhani, 4 Roti, Rice, Sweet) (₹180)
    - Regular Thali (Dal, Sabzi, 4 Roti, Rice) (₹130)
    - Mineral Water Bottle (₹20)
    """

    system_prompt = f"""
You are the intelligent operations and room-service manager at Hotel Ganga Palace.
Below is the live operational hotel context and kitchen pricing:
{sheet_data if sheet_data else default_rules}

OPERATIONAL INSTRUCTIONS:
1. GUEST FOOD ORDER & KITCHEN BILL:
   - If the guest is ordering food, drinks, snacks, or tea:
   - Identify the items and quantity requested.
   - Calculate the exact total bill based on the menu pricing.
   - Present a neat, formatted *KITCHEN BILL / ORDER CONFIRMATION* formatted for WhatsApp:
     * Room / Guest Details
     * Itemized List with quantity & individual rate
     * Total Amount (₹)
     * Mention: "Aapka order kitchen ko bhej diya gaya hai, agle 20-25 minutes me serve kar diya jayega."
2. ROOM BOOKING & INQUIRIES:
   - State room rates, check-in time (12:00 PM), check-out time (11:00 AM), Wi-Fi, and Har Ki Pauri Ganga Aarti details politely.
3. TONE: Warm, courteous, professional Hindi/English mix (Hinglish/Hindi).
"""

    try:
        response = co.chat(
            model="command-r",
            message=user_text,
            preamble=system_prompt
        )
        reply = response.text.strip()
        
        # Agar reply me bill calculate hua hai toh kitchen sheet me note karlo
        if "bill" in reply.lower() or "₹" in reply or "order" in reply.lower():
            log_kitchen_order(sender, f"MSG: {user_text} | BOT: {reply}")
            
        return reply
    except Exception as e:
        print(f"[COHERE ERROR]: {str(e)}", flush=True)
        return "Namaste! Welcome to Hotel Ganga Palace. We have received your message. Our front desk & room service team is attending to your request."

# ==========================================
# WEBHOOK ENDPOINTS
# ==========================================
@app.route("/", methods=["GET"])
def health():
    return "Hotel Ganga Palace Enterprise Webhook Live 200 OK", 200

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("[WEBHOOK VERIFIED] Meta verification successful.", flush=True)
        return challenge, 200
    return "Forbidden", 403

@app.route("/webhook", methods=["POST"])
def incoming_webhook():
    data = request.get_json()
    print(f"[INCOMING PACKET RAW]: {json.dumps(data)}", flush=True)

    try:
        if not data or "entry" not in data:
            return jsonify({"status": "no_entry"}), 200

        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                
                if "messages" in value:
                    for msg in value.get("messages", []):
                        sender = msg.get("from")
                        msg_type = msg.get("type")
                        
                        user_text = ""
                        if msg_type == "text":
                            user_text = msg.get("text", {}).get("body", "").strip()
                        elif msg_type == "button":
                            user_text = msg.get("button", {}).get("text", "").strip()
                        elif msg_type == "interactive":
                            interactive_data = msg.get("interactive", {})
                            if interactive_data.get("type") == "button_reply":
                                user_text = interactive_data.get("button_reply", {}).get("title", "")
                            elif interactive_data.get("type") == "list_reply":
                                user_text = interactive_data.get("list_reply", {}).get("title", "")

                        if sender and user_text:
                            print(f"[PROCESS START] Sender: {sender} | Msg: {user_text}", flush=True)
                            
                            # 1. Processing (Check-in, Check-out, Kitchen Bill, Sheet Rules)
                            ai_reply = generate_hotel_response(sender, user_text)
                            print(f"[REPLY GENERATED]:\n{ai_reply}", flush=True)
                            
                            # 2. Send Message via WhatsApp
                            send_whatsapp_message(sender, ai_reply)
                            
                            # 3. Log to Interaction Sheet
                            log_interaction(sender, user_text, ai_reply)

    except Exception as e:
        print(f"[CRITICAL RUNTIME ERROR]: {str(e)}", flush=True)

    return jsonify({"status": "EVENT_RECEIVED"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
