import os
import re
import csv
import io
import json
import time
import threading
from datetime import datetime, timezone, timedelta
import requests
import gspread
from google.oauth2.service_account import Credentials
from flask import Flask, request, jsonify

IST = timezone(timedelta(hours=5, minutes=30))

app = Flask(__name__)

# ==========================================
# 1. CONFIGURATION
# ==========================================
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "").strip()
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "").strip()
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "").strip()
COHERE_API_KEY = os.getenv("COHERE_API_KEY", "").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")

KITCHEN_PHONE = os.getenv("KITCHEN_PHONE", "919058514478")
STAFF_PHONE = os.getenv("STAFF_PHONE", "919058514488")
SHEET_ID = "1E7iI0vSkRlwpiog-GUjN7Gfh35REAhfY_yVG0t63wqY"

shared_store = {
    "rooms": [],
    "kitchen_orders": [],
    "last_synced": 0
}

welcomed_guests = set()
checked_out_guests = set()

MENU_PRICES = {
    "chai": 30, "tea": 30, "coffee": 50, "aloo paratha": 90, "paratha": 90,
    "poha": 70, "chole bhature": 120, "bhature": 120, "dahi": 70, "green salad": 50,
    "salad": 50, "roti": 15, "butter roti": 20, "dal tadka": 160, "dal fry": 160,
    "dal makhani": 190, "dal makhni": 190, "paneer": 220, "kadai paneer": 240,
    "shahi paneer": 240, "rice": 100, "jeera rice": 120, "water": 20, "mineral water": 20
}

def resolve_item_price(order_text):
    clean_raw = str(order_text).lower().strip().replace("parathe", "paratha")
    clean_raw = re.sub(r"\b(garam|hot|cold|thandi|fresh|special|plate|cup|ek|do|teen)\b", "", clean_raw)
    parts = clean_raw.split(",")
    line_total = 0
    for part in parts:
        part = part.strip()
        if not part:
            continue
        match = re.match(r"^(\d+)?\s*(.+)$", part)
        qty = int(match.group(1)) if match and match.group(1) else 1
        raw_name = match.group(2).strip() if match else part
        matched_rate = 0
        if raw_name in MENU_PRICES:
            matched_rate = MENU_PRICES[raw_name]
        else:
            for item_key, item_val in MENU_PRICES.items():
                if item_key in raw_name:
                    matched_rate = item_val
                    break
        line_total += (matched_rate * qty) if matched_rate > 0 else 30
    return max(30, line_total)

def format_whatsapp_number(raw_phone):
    digits = re.sub(r"\D", "", str(raw_phone))
    if len(digits) == 10:
        return f"91{digits}"
    elif len(digits) == 12 and digits.startswith("91"):
        return digits
    elif len(digits) > 10:
        return f"91{digits[-10:]}"
    return None

# ==========================================
# 2. SHEETS SYNC ENGINE
# ==========================================
def get_gspread_client():
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        return None
    try:
        creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        print(f"[GSPREAD CLIENT ERROR]: {e}", flush=True)
        return None

def sync_sheets_in_background():
    while True:
        try:
            # 1. Rooms Tab
            csv_rooms = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=Rooms"
            synced = False
            try:
                res_r = requests.get(csv_rooms, timeout=6)
                if res_r.status_code == 200 and len(res_r.text) > 15:
                    records = list(csv.DictReader(io.StringIO(res_r.text)))
                    if records:
                        shared_store["rooms"] = records
                        synced = True
            except Exception:
                pass

            if not synced:
                client = get_gspread_client()
                if client:
                    try:
                        sh = client.open_by_key(SHEET_ID)
                        shared_store["rooms"] = sh.worksheet("Rooms").get_all_records()
                        synced = True
                    except Exception as e:
                        print(f"[GSPREAD SYNC ROOMS FAIL]: {e}", flush=True)

            # 2. Kitchen Orders Tab
            csv_kitch = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=Kitchen_Orders"
            try:
                res_k = requests.get(csv_kitch, timeout=6)
                if res_k.status_code == 200 and len(res_k.text) > 15:
                    k_records = list(csv.DictReader(io.StringIO(res_k.text)))
                    if k_records:
                        shared_store["kitchen_orders"] = k_records
            except Exception:
                pass

            shared_store["last_synced"] = time.time()
        except Exception as e:
            print(f"[BACKGROUND SYNC ERROR]: {e}", flush=True)

        time.sleep(10)

def append_kitchen_order_to_sheet(room, guest_name, order_details, amount):
    client = get_gspread_client()
    if not client:
        return
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("Kitchen_Orders")
        now_str = datetime.now(IST).strftime("%d-%b %I:%M %p")
        sheet.append_row([now_str, str(room), str(guest_name), str(order_details), str(amount), "PENDING"])
        print(f"[SHEET WRITE OK] Added order for Room {room}", flush=True)
    except Exception as e:
        print(f"[SHEET WRITE FAIL]: {e}", flush=True)

def get_guest_stay_status(sender_phone):
    clean_sender = re.sub(r"\D", "", str(sender_phone))[-10:]
    records = shared_store.get("rooms", [])

    for row in records:
        norm = {re.sub(r"[^a-zA-Z]", "", str(k)).lower(): str(v).strip() for k, v in row.items()}
        phone_val = norm.get("phone", "")
        status_val = norm.get("status", "").upper()

        sheet_phone = re.sub(r"\D", "", phone_val)[-10:]
        if sheet_phone and sheet_phone == clean_sender and "IN" in status_val:
            return {
                "is_inhouse": True,
                "room": norm.get("room", "101"),
                "name": norm.get("guestname", "Guest"),
                "category": norm.get("category", "Deluxe"),
                "price": norm.get("price", "1800")
            }
    return None

# ==========================================
# 3. DISPATCH ENGINE
# ==========================================
def send_whatsapp_message(to_number, text):
    clean_number = format_whatsapp_number(to_number)
    if not clean_number:
        print(f"[DISPATCH REJECTED] Bad Number: {to_number}", flush=True)
        return

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
        res = requests.post(url, json=payload, headers=headers, timeout=8)
        print(f"[DISPATCH SENT -> {clean_number}] HTTP: {res.status_code} | Body: {res.text}", flush=True)
    except Exception as e:
        print(f"[DISPATCH EXCEPTION]: {e}", flush=True)

def ask_cohere(user_message):
    if not COHERE_API_KEY:
        return None
    url = "https://api.cohere.ai/v1/chat"
    headers = {"Authorization": f"Bearer {COHERE_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "command-r",
        "message": user_message,
        "preamble": "You are the WhatsApp assistant for Hotel Ganga View, Haridwar near Har Ki Pauri. Reply politely in 1-2 short sentences in Hinglish.",
        "temperature": 0.2
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=5)
        if res.status_code == 200:
            return res.json().get("text", "").strip()
    except Exception as e:
        print(f"[COHERE TIMEOUT]: {e}", flush=True)
    return None

# ==========================================
# 4. MESSAGE ROUTER
# ==========================================
def process_message(user_text, sender_phone):
    print(f"[PROCESSING] Text: '{user_text}' | Sender: {sender_phone}", flush=True)
    text_lower = user_text.lower().strip()
    guest_info = get_guest_stay_status(sender_phone)
    print(f"[GUEST STATUS] In-house: {bool(guest_info)}", flush=True)

    # 1. GREETING
    greetings = ["hi", "hello", "namaste", "hey", "start", "hlo", "helo"]
    if text_lower in greetings or len(text_lower) <= 2:
        if guest_info:
            reply = (
                f"Namaste {guest_info['name']} ji! 🙏\n\n"
                f"Aapka swagat hai Room {guest_info['room']}.\n"
                f"📶 *Wi-Fi Password:* Ganga@2026\n\n"
                f"Room service ya chai/nashte ke liye bas yahan order likhein!"
            )
        else:
            reply = (
                "Namaste! 🙏 Welcome to *Hotel Ganga View, Haridwar* (Near Har Ki Pauri).\n\n"
                "• *Standard Room:* ₹1,800/night\n"
                "• *Deluxe AC Room:* ₹2,500/night\n\n"
                "Room photos dekhne ke liye 'Photo' likhein ya booking details batayein!"
            )
        send_whatsapp_message(sender_phone, reply)
        return

    # 2. KITCHEN / FOOD ORDER
    food_triggers = ["chai", "tea", "roti", "khana", "paratha", "poha", "bhature", "order", "coffee", "dahi", "water", "paneer"]
    if any(ft in text_lower for ft in food_triggers):
        total_price = resolve_item_price(user_text)
        room_num = guest_info['room'] if guest_info else "101"
        guest_name = guest_info['name'] if guest_info else "Guest"

        # Notify Kitchen
        kitchen_msg = (
            f"🍳 *NEW ROOM SERVICE ORDER*\n\n"
            f"📌 *Location:* Room {room_num} ({guest_name})\n"
            f"📋 *Order:* {user_text}\n"
            f"💰 *Bill Amount:* ₹{total_price}\n"
            f"📞 *Contact:* +{sender_phone}\n\n"
            f"⚡ Order deliver karein!"
        )
        threading.Thread(target=send_whatsapp_message, args=(KITCHEN_PHONE, kitchen_msg), daemon=True).start()

        # Append to Sheet
        threading.Thread(target=append_kitchen_order_to_sheet, args=(room_num, guest_name, user_text, total_price), daemon=True).start()

        # Reply to Guest
        guest_reply = (
            f"Ji {guest_name} ji! Aapka order note ho gaya hai:\n\n"
            f"🍽️ *Item:* {user_text}\n"
            f"💰 *Bill Amount:* ₹{total_price}\n"
            f"📍 *Delivering to:* Room {room_num}\n\n"
            f"Agle 15-20 minute me deliver kar diya jayega. Dhanyawad! 🙏"
        )
        send_whatsapp_message(sender_phone, guest_reply)
        return

    # 3. LOCATION
    if any(w in text_lower for w in ["location", "map", "address", "kahan", "pauri", "direction"]):
        loc_msg = (
            "📍 *Hotel Ganga View, Haridwar*\n"
            "Har Ki Pauri se sirf 2 minute ki paidal doori par sthit hai!\n\n"
            "🗺️ *Google Maps:* https://maps.google.com/?q=29.9530,78.1700"
        )
        send_whatsapp_message(sender_phone, loc_msg)
        return

    # 4. PHOTOS
    if any(w in text_lower for w in ["photo", "pic", "image", "tasveer"]):
        photo_msg = (
            "🏨 *Hotel Ganga View, Haridwar*\n\n"
            "📸 *Direct Photos Link:* https://raw.githubusercontent.com/yrskaran/ganga-palace-bot/main/images/main.jpg\n\n"
            "• Standard Non-AC: ₹1,800/night\n"
            "• Deluxe AC Room: ₹2,500/night"
        )
        send_whatsapp_message(sender_phone, photo_msg)
        return

    # 5. COHERE AI / FALLBACK
    ai_reply = ask_cohere(user_text)
    if not ai_reply:
        ai_reply = "Namaste! Hotel Ganga View, Haridwar me aapka swagat hai. Room booking ya sahayata ke liye batayein, hum turant reply karenge! 🙏"

    send_whatsapp_message(sender_phone, ai_reply)

# ==========================================
# 5. WEBHOOK HANDLERS
# ==========================================
@app.route("/", methods=["GET"])
def home():
    return "Hotel Ganga View WhatsApp Server is Active 200 OK", 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "running"}), 200

@app.route("/webhook", methods=["GET"], strict_slashes=False)
def verify():
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge"), 200
    return "Forbidden", 403

@app.route("/webhook", methods=["POST"], strict_slashes=False)
def incoming():
    data = request.get_json()
    try:
        if data and "entry" in data:
            for entry in data.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    for msg in value.get("messages", []):
                        sender = msg.get("from")
                        if msg.get("type") == "text":
                            text = msg.get("text", {}).get("body", "").strip()
                            if sender and text:
                                threading.Thread(target=process_message, args=(text, sender), daemon=True).start()
    except Exception as e:
        print(f"[HOOK PARSE ERROR]: {e}", flush=True)

    return jsonify({"status": "success"}), 200

# ==========================================
# 6. START THREADS & SERVER
# ==========================================
threading.Thread(target=sync_sheets_in_background, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
