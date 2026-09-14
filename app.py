import os
import json
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
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "1355451974309498")
COHERE_API_KEY = os.getenv("COHERE_API_KEY")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Hotel Ganga Palace Orders")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")

# Cohere Client Init
co = cohere.Client(COHERE_API_KEY) if COHERE_API_KEY else None

# ==========================================
# GOOGLE SHEETS HELPER
# ==========================================
def log_to_google_sheet(sender, message, reply):
    if not GOOGLE_CREDS_JSON:
        print("[SHEET SKIP] No GOOGLE_CREDS_JSON provided", flush=True)
        return
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = json.loads(GOOGLE_CREDS_JSON)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open(GOOGLE_SHEET_NAME).sheet1
        sheet.append_row([sender, message, reply])
        print(f"[SHEET OK] Logged interaction for {sender}", flush=True)
    except Exception as e:
        print(f"[SHEET ERROR]: {str(e)}", flush=True)

# ==========================================
# WHATSAPP DISPATCH HELPER
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
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        res_json = response.json()
        if response.status_code == 200:
            print(f"[MSG DELIVERED OK] To: {recipient_id}", flush=True)
        else:
            print(f"[WHATSAPP DISPATCH ERROR {response.status_code}] Target: {recipient_id} | Body: {res_json}", flush=True)
    except Exception as e:
        print(f"[NETWORK ERROR SENDING MSG]: {str(e)}", flush=True)

# ==========================================
# AI GENERATION (COHERE)
# ==========================================
HOTEL_SYSTEM_PROMPT = """
You are the official front-desk WhatsApp assistant for Hotel Ganga Palace.
- Welcome guests warmly (Namaste / Welcome).
- Provide brief, polite, and helpful replies.
- Hotel services: Deluxe & Super Deluxe Rooms, 24x7 Room Service, Restaurant (North Indian, South Indian, Beverages), Free Wi-Fi, Ganga Aarti guide.
- If someone wants to order food (e.g., Chai, Snacks, Dinner) or book a room, take their details politely and confirm their request.
- Keep answers crisp, readable, and ready for WhatsApp chat.
"""

def generate_hotel_response(user_text):
    if not co:
        return "Namaste! Welcome to Hotel Ganga Palace. How can we assist you today?"
    try:
        response = co.chat(
            model="command-r",
            message=user_text,
            preamble=HOTEL_SYSTEM_PROMPT
        )
        return response.text.strip()
    except Exception as e:
        print(f"[COHERE ERROR]: {str(e)}", flush=True)
        return "Namaste! Welcome to Hotel Ganga Palace. We have received your request and our team will get back to you shortly."

# ==========================================
# WEBHOOK ENDPOINTS
# ==========================================
@app.route("/", methods=["GET"])
def health():
    return "Hotel Ganga Palace Bot Server is running 200 OK", 200

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == VERIFY_TOKEN:
            print("[WEBHOOK VERIFIED] Handshake successful.", flush=True)
            return challenge, 200
        else:
            print("[VERIFICATION FAILED] Token mismatch.", flush=True)
            return "Forbidden", 403
    return "Invalid Request", 400

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
                            print(f"[PROCESS START] From: {sender} | Msg: {user_text}", flush=True)
                            
                            # 1. AI Reply Generation
                            ai_reply = generate_hotel_response(user_text)
                            print(f"[COHERE REPLY for {sender}]: {ai_reply}", flush=True)
                            
                            # 2. WhatsApp Message Dispatch
                            send_whatsapp_message(sender, ai_reply)
                            
                            # 3. Google Sheets Logging
                            log_to_google_sheet(sender, user_text, ai_reply)

    except Exception as e:
        print(f"[PIPELINE RUNTIME ERROR]: {str(e)}", flush=True)

    return jsonify({"status": "EVENT_RECEIVED"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
