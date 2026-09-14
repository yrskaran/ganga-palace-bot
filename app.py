import os
import json
import threading
import requests
from flask import Flask, request, jsonify
import gspread

app = Flask(__name__)

PORT = int(os.environ.get("PORT", 10000))
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "ganga_bot_secret_123")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
SPREADSHEET_NAME = os.environ.get("SPREADSHEET_NAME", "Ganga_Palace_Guests")

# Google Sheets Connection
sheet_client = None
if GOOGLE_CREDENTIALS_JSON:
    try:
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        sheet_client = gspread.service_account_from_dict(creds_dict)
        print("[SHEETS] Connected successfully.", flush=True)
    except Exception as e:
        print(f"[SHEETS ERROR] Connection failed: {e}", flush=True)


def send_whatsapp_message(to_phone, text):
    """WhatsApp Text Message Dispatcher"""
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print("[META ERROR] Token or Phone Number ID missing!", flush=True)
        return False
    
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": str(to_phone),
        "type": "text",
        "text": {"body": text}
    }
    
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        print(f"[META DISPATCH] Status: {r.status_code} | Target: {to_phone} | Response: {r.text}", flush=True)
        return r.status_code == 200
    except Exception as e:
        print(f"[META DISPATCH ERROR] {e}", flush=True)
        return False


def get_guest_status(phone_number):
    """Check if guest is currently checked in"""
    if not sheet_client:
        return None
    try:
        sheet = sheet_client.open(SPREADSHEET_NAME).sheet1
        records = sheet.get_all_records()
        clean_phone = str(phone_number).replace("+", "").strip()
        for row in records:
            guest_phone = str(row.get("Phone", "")).replace("+", "").strip()
            if guest_phone and (guest_phone in clean_phone or clean_phone in guest_phone):
                status = str(row.get("Status", "")).strip().lower()
                if status == "checked-in":
                    return row
        return None
    except Exception as e:
        print(f"[GUEST CHECK ERROR] {e}", flush=True)
        return None


def process_message_pipeline(user_phone, user_text, msg_id):
    """Core Receptionist & Guest Service Pipeline"""
    try:
        clean_text = user_text.lower().strip()
        print(f"[PROCESS START] '{clean_text}' from {user_phone}", flush=True)

        guest = get_guest_status(user_phone)

        if guest:
            # In-House Guest Handling
            room = guest.get("Room", "Your Room")
            name = guest.get("Name", "Guest")

            if any(w in clean_text for w in ["chai", "tea", "coffee", "khana", "food", "paratha", "order", "water"]):
                reply = f"Namaste {name} ji! Room {room} ke liye aapka request receive ho gaya hai. Humari kitchen team 10-15 minute me deliver kar degi. ☕🛎️"
            elif any(w in clean_text for w in ["wifi", "wi-fi", "password"]):
                reply = f"Room {room} Wi-Fi details:\nNetwork: GangaView_Guest\nPassword: Ganga@2026"
            elif any(w in clean_text for w in ["checkout", "check out", "bill"]):
                reply = f"Namaste {name} ji, front desk aapke Room {room} ka bill taiyar kar raha hai. 5 minute me finalize ho jayega."
            else:
                reply = f"Namaste {name} ji (Room {room})! Ganga View desk par aapka message mil gaya hai. Reception team turant assist kar rahi hai."
        else:
            # Inquiry / Outside Guest Handling
            if any(w in clean_text for w in ["photo", "photos", "pic", "pics", "image", "room"]):
                reply = (
                    "Hotel Ganga View, Haridwar Rooms & Rates:\n\n"
                    "1. Standard AC Room: ₹1,800/night\n"
                    "2. Deluxe Ganga View Room: ₹2,500/night\n\n"
                    "Har Ki Pauri se sirf 500m door. Booking ke liye date aur guests count batayein!"
                )
            elif any(w in clean_text for w in ["location", "kahan", "address", "map", "rasta"]):
                reply = (
                    "📍 Hotel Ganga View, Haridwar\n"
                    "Near Har Ki Pauri, Haridwar, Uttarakhand.\n"
                    "Google Maps Link: https://maps.google.com/?q=Har+Ki+Pauri+Haridwar"
                )
            elif any(w in clean_text for w in ["hi", "hello", "namaste", "hey"]):
                reply = (
                    "Namaste! Hotel Ganga View, Haridwar me aapka swagat hai. 🌸\n\n"
                    "Main aapki kya madad kar sakta hoon?\n"
                    "• Rooms & Tariffs\n"
                    "• Hotel Location\n"
                    "• Current Bookings"
                )
            else:
                reply = "Hotel Ganga View me aapka swagat hai! Room booking ya jankari ke liye 'Rooms' ya 'Location' likhein."

        send_whatsapp_message(user_phone, reply)
    except Exception as pipeline_err:
        print(f"[PIPELINE ERROR] Unhandled crash: {pipeline_err}", flush=True)


@app.route('/', methods=['GET'])
def index():
    return "Hotel Ganga View WhatsApp Receptionist is Active.", 200


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy", "service": "ganga-palace-bot"}), 200


@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')
        if mode == 'subscribe' and token == VERIFY_TOKEN:
            print("[META WEBHOOK] Verification passed.", flush=True)
            return challenge, 200
        print("[META WEBHOOK] Verification failed.", flush=True)
        return "Forbidden", 403

    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        print(f"[INCOMING PACKET RAW] {json.dumps(data)}", flush=True)

        try:
            entries = data.get("entry", [])
            for entry in entries:
                changes = entry.get("changes", [])
                for change in changes:
                    value = change.get("value", {})
                    
                    # Status events (sent, delivered, read)
                    if "statuses" in value:
                        status_info = value["statuses"][0]
                        print(f"[META STATUS TICK] Status: {status_info.get('status')} | Recipient: {status_info.get('recipient_id')}", flush=True)
                    
                    # Asli user messages
                    if "messages" in value:
                        for msg in value.get("messages", []):
                            sender = msg.get("from")
                            msg_id = msg.get("id")
                            msg_type = msg.get("type")

                            if msg_type == "text":
                                text_body = msg.get("text", {}).get("body", "")
                                if sender and text_body:
                                    t = threading.Thread(
                                        target=process_message_pipeline,
                                        args=(sender, text_body, msg_id),
                                        daemon=True
                                    )
                                    t.start()
        except Exception as e:
            print(f"[WEBHOOK EXCEPTION] {e}", flush=True)

        return "EVENT_RECEIVED", 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT)
