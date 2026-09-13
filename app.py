import os
import re
import csv
import io
import json
import base64
import time
import threading
from datetime import datetime, timezone, timedelta
import requests
import gspread
from google.oauth2.service_account import Credentials
from flask import Flask, request, jsonify

# Indian Standard Time (IST)
IST = timezone(timedelta(hours=5, minutes=30))

# ==========================================
# 1. INITIALIZE APP & CONFIGURATION
# ==========================================
app = Flask(__name__)

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "1357005434155447")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
COHERE_API_KEY = os.getenv("COHERE_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")

KITCHEN_PHONE = os.getenv("KITCHEN_PHONE", "919058514478")
STAFF_PHONE = os.getenv("STAFF_PHONE", "919058514488")

HOTEL_LAT = "29.9530"
HOTEL_LON = "78.1700"
SHEET_ID = "1E7iI0vSkRlwpiog-GUjN7Gfh35REAhfY_yVG0t63wqY"

RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "https://ganga-palace-bot.onrender.com")

chat_histories = {}
processed_msg_ids = set()

# In-Memory Cache for Sheet Data
sheet_cache = {"data": [], "last_fetched": 0}
CACHE_TTL_SECONDS = 30

welcomed_guests = set()
checked_out_guests = set()

alerts_sent_today = {
    "breakfast": None,
    "tourism": None,
    "aarti": None,
    "dinner": None
}

# ==========================================
# HOTEL BASE RATES
# ==========================================
MENU_PRICES = {
    "chai": 30,
    "tea": 30,
    "coffee": 50,
    "aloo paratha": 90,
    "dahi": 70,
    "green salad": 50,
    "roti": 15,
    "butter roti": 20,
    "dal tadka": 160,
    "paneer": 220
}

def resolve_item_price(order_text):
    clean = str(order_text).lower().strip().replace("parathe", "paratha")
    parts = clean.split(",")
    line_total = 0
    for part in parts:
        part = part.strip()
        match = re.match(r"^(\d+)?\s*(.+)$", part)
        qty = int(match.group(1)) if match and match.group(1) else 1
        item_name = match.group(2).strip() if match else part
        line_total += MENU_PRICES.get(item_name, 0) * qty
    return line_total

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
# 2. FAIL-SAFE GOOGLE SHEET READ ENGINE
# ==========================================
def get_gspread_client():
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        return None
    try:
        creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        print(f"[GSPREAD AUTH ERROR]: {e}", flush=True)
        return None

def fetch_sheet_records():
    """Reads sheet with strict 4-second timeout to prevent webhook hang"""
    now = time.time()
    if sheet_cache["data"] and (now - sheet_cache["last_fetched"] < CACHE_TTL_SECONDS):
        return sheet_cache["data"]

    # 1. First try GSpread
    client = get_gspread_client()
    if client:
        try:
            sheet = client.open_by_key(SHEET_ID).worksheet("Rooms")
            records = sheet.get_all_records()
            sheet_cache["data"] = records
            sheet_cache["last_fetched"] = now
            return records
        except Exception as e:
            print(f"[API ROOMS ERROR]: {e}", flush=True)

    # 2. Strict Timeout CSV Fallback
    csv_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=Rooms"
    try:
        response = requests.get(csv_url, timeout=4)
        if response.status_code == 200:
            reader = list(csv.DictReader(io.StringIO(response.content.decode("utf-8"))))
            sheet_cache["data"] = reader
            sheet_cache["last_fetched"] = now
            return reader
    except Exception as e:
        print(f"[CSV FALLBACK TIMEOUT/ERROR]: {e}", flush=True)

    return sheet_cache.get("data", [])

def append_kitchen_order_to_sheet(room, guest_name, order_details, amount):
    client = get_gspread_client()
    if not client:
        return
    try:
        clean_amount = int(re.sub(r"\D", "", str(amount))) if re.sub(r"\D", "", str(amount)) else 0
        if clean_amount <= 0:
            clean_amount = resolve_item_price(order_details)

        sheet = client.open_by_key(SHEET_ID).worksheet("Kitchen_Orders")
        now_str = datetime.now(IST).strftime("%d-%b %I:%M %p")
        row_data = [now_str, str(room), str(guest_name), str(order_details), str(clean_amount), "PENDING"]
        sheet.append_row(row_data)
        print(f"[SHEET WRITE SUCCESS]: Room {room} (Rs. {clean_amount})", flush=True)
    except Exception as e:
        print(f"[SHEET WRITE EXCEPTION]: {e}", flush=True)

def get_guest_kitchen_bill_total(room_number):
    client = get_gspread_client()
    if not client:
        return 0, []

    total_amount = 0
    itemized_list = []
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("Kitchen_Orders")
        records = sheet.get_all_records()
        for r in records:
            r_room = str(r.get("Room") or r.get("Room (B)") or "").strip()
            r_status = str(r.get("Payment_Status") or r.get("Payment_Status (F)") or "").strip().upper()
            if r_room == str(room_number).strip() and r_status != "PAID":
                item_name = r.get("Order Details") or r.get("Order Details (D)") or "Item"
                raw_amt = str(r.get("Amount") or r.get("Amount (E)") or "0")
                amt_digits = re.sub(r"\D", "", raw_amt)
                amt = int(amt_digits) if amt_digits else 0
                if amt <= 0:
                    amt = resolve_item_price(item_name)
                total_amount += amt
                itemized_list.append(f"• {item_name} - ₹{amt}")
        return total_amount, itemized_list
    except Exception as e:
        print(f"[BILL CALCULATION ERROR]: {e}", flush=True)
        return 0, []

def calculate_stay_nights(check_in_str):
    if not check_in_str:
        return 1
    clean_date = str(check_in_str).strip()
    date_formats = ["%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y"]
    check_in_dt = None
    for fmt in date_formats:
        try:
            check_in_dt = datetime.strptime(clean_date, fmt).date()
            break
        except ValueError:
            continue
    if not check_in_dt:
        return 1
    today = datetime.now(IST).date()
    return max(1, (today - check_in_dt).days)

# ==========================================
# 3. PROMPT & DISPATCH
# ==========================================
def get_system_prompt():
    file_path = os.path.join(os.path.dirname(__file__), "hotel_data.txt")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return "You are the WhatsApp AI Receptionist for Hotel Ganga View in Haridwar. Reply politely in 1-2 lines."

def keep_awake_ping():
    time.sleep(15)
    while True:
        try:
            target_url = f"{RENDER_EXTERNAL_URL.rstrip('/')}/health"
            requests.get(target_url, timeout=5)
        except:
            pass
        time.sleep(8 * 60)

def mark_message_as_read(message_id):
    pid = PHONE_NUMBER_ID or "1357005434155447"
    url = f"https://graph.facebook.com/v20.0/{pid}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "status": "read", "message_id": message_id}
    try:
        requests.post(url, json=payload, headers=headers, timeout=5)
    except:
        pass

def send_whatsapp_message(to_number, text):
    clean_number = format_whatsapp_number(to_number)
    if not clean_number:
        print(f"[DISPATCH ABORTED]: Invalid number {to_number}", flush=True)
        return None

    pid = PHONE_NUMBER_ID or "1357005434155447"
    url = f"https://graph.facebook.com/v20.0/{pid}/messages"
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
        res_json = res.json()
        print(f"[META DISPATCH] Status: {res.status_code} | Target: {clean_number} | Body: {res_json}", flush=True)
        return res_json
    except Exception as e:
        print(f"[SEND MSG EXCEPTION]: {e}", flush=True)
        return None

# ==========================================
# 4. GUEST & AI ENGINE
# ==========================================
def get_guest_stay_status(sender_phone):
    clean_sender = re.sub(r"\D", "", str(sender_phone))[-10:]
    try:
        records = fetch_sheet_records()
        for row in records:
            sheet_phone_val = row.get("Phone") or row.get("Phone (E)") or ""
            status_val = row.get("Status") or row.get("Status (F)") or ""
            sheet_phone = re.sub(r"\D", "", str(sheet_phone_val))[-10:]
            status = str(status_val).strip().upper()
            
            if sheet_phone and sheet_phone == clean_sender and status == "CHECKED_IN":
                return {
                    "is_inhouse": True,
                    "room": str(row.get("Room") or row.get("Room (A)") or "").strip(),
                    "name": str(row.get("Guest Name") or row.get("Guest Name (D)") or "").strip(),
                    "category": str(row.get("Category") or row.get("Category (B)") or "Standard").strip(),
                    "price": str(row.get("Price") or row.get("Price (C)") or "2000").strip(),
                    "check_in_date": str(row.get("Check_In_Date") or row.get("Check_In_Date (G)") or "").strip()
                }
    except Exception as e:
        print(f"[GET GUEST STATUS EXCEPTION]: {e}", flush=True)
    return None

def get_room_inventory_summary():
    try:
        records = fetch_sheet_records()
        available_rooms = []
        for row in records:
            status_val = str(row.get("Status") or row.get("Status (F)") or "").strip().upper()
            room_no = str(row.get("Room") or row.get("Room (A)") or "").strip()
            category = str(row.get("Category") or row.get("Category (B)") or "Deluxe").strip()
            price_val = str(row.get("Price") or row.get("Price (C)") or "2000").strip()
            if status_val != "CHECKED_IN" and room_no:
                try:
                    num_price = int(re.sub(r"\D", "", price_val)) if re.sub(r"\D", "", price_val) else 2000
                except:
                    num_price = 2000
                available_rooms.append({"room": room_no, "category": category, "price": num_price})
                
        if available_rooms:
            available_rooms.sort(key=lambda x: x["price"])
            return f"Rooms Available: {len(available_rooms)}. Budget: {available_rooms[0]['category']} at Rs. {available_rooms[0]['price']}/night."
    except:
        pass
    return "Rooms available starting from Rs. 2000/night."

def ask_cohere(user_message, sender_phone):
    history = chat_histories.get(sender_phone, [])
    url = "https://api.cohere.ai/v1/chat"
    headers = {"Authorization": f"Bearer {COHERE_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "message": user_message,
        "preamble": get_system_prompt(),
        "chat_history": history,
        "temperature": 0.1
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=12)
        if res.status_code == 200:
            reply_text = res.json().get("text", "").strip()
            if reply_text:
                history.append({"role": "USER", "message": user_message})
                history.append({"role": "CHATBOT", "message": reply_text})
                chat_histories[sender_phone] = history[-6:]
                return reply_text
    except Exception as e:
        print(f"[COHERE ERROR]: {e}", flush=True)
    return "Namaste! Batayein Hotel Ganga View me aapki kya madad kar sakta hoon?"

def process_and_reply(user_text, sender_phone):
    print(f"[PROCESS START] Message: '{user_text}' from {sender_phone}", flush=True)
    clean_phone_key = re.sub(r"\D", "", str(sender_phone))[-10:]
    
    guest_info = get_guest_stay_status(sender_phone)
    print(f"[PROCESS] In-house guest: {bool(guest_info)}", flush=True)

    text_lower = user_text.lower().strip()
    
    # 1. GREETINGS & AUTO-WELCOME
    greetings = ["hi", "hello", "namaste", "hey", "start", "hlo", "helo"]
    if guest_info and (text_lower in greetings or len(text_lower) <= 2) and (clean_phone_key not in welcomed_guests):
        welcomed_guests.add(clean_phone_key)
        welcome_reply = (
            f"Welcome to Hotel Ganga View, {guest_info['name']} ji! 🏨✨\n\n"
            f"Aapka swagat hai Room {guest_info['room']} ({guest_info['category']}) me.\n"
            f"📶 *Wi-Fi Password:* Ganga@2026\n\n"
            f"Aap yahan se khana order kar sakte hain ya apna bill dekh sakte hain. Batayein mai kya seva kar sakta hoon? 🙏"
        )
        send_whatsapp_message(sender_phone, welcome_reply)
        return

    # 2. Block unauthorized outside orders
    service_keywords = ["order", "chai", "tea", "roti", "khana", "towel", "room service", "cleaning", "paani", "water"]
    if not guest_info and any(w in text_lower for w in service_keywords):
        send_whatsapp_message(
            sender_phone,
            "Namaste! 🙏 Hamari room service suvidha sirf hotel me stay kar rahe registered guests ke liye hai. Counter par apna number register karwayein."
        )
        return

    # 3. ACCURATE BILL INQUIRY
    bill_pattern = r"(bill|bil|total|hisaab|hisab|kharcha|baki|due)"
    if guest_info and re.search(bill_pattern, text_lower):
        total_kitchen, items = get_guest_kitchen_bill_total(guest_info['room'])
        room_rent_base = guest_info.get('price', '0')
        rent_per_night = int(re.sub(r'\D', '', str(room_rent_base))) if re.sub(r'\D', '', str(room_rent_base)) else 0
        nights = calculate_stay_nights(guest_info.get('check_in_date'))
        total_room_rent = rent_per_night * nights

        is_only_kitchen = any(k in text_lower for k in ["kichen", "kitchen", "khana", "khane", "food", "nashta", "chai"])
        is_only_room = any(k in text_lower for k in ["room", "kamra", "kamre", "stay", "rent", "tariff"])

        if is_only_kitchen and not is_only_room:
            items_str = "\n".join(items) if items else "Koi orders nahi hain."
            send_whatsapp_message(sender_phone, f"🍳 *Kitchen Orders Bill:*\n{items_str}\n\n💰 *Total Kitchen:* ₹{total_kitchen}")
            return

        if is_only_room and not is_only_kitchen:
            send_whatsapp_message(sender_phone, f"🏨 *Room Rent Details:*\nStay: {nights} Nights (₹{rent_per_night}/night)\n💰 *Total Room Tariff:* ₹{total_room_rent}")
            return

        grand_total = total_kitchen + total_room_rent
        items_str = "\n".join(items) if items else "• Koi kitchen order nahi"
        bill_reply = (
            f"🧾 *Room {guest_info['room']} - Bill Summary*\n"
            f"Guest: {guest_info['name']} ji ({nights} Nights)\n\n"
            f"*Kitchen Orders:*\n{items_str}\n\n"
            f"🍳 Kitchen: ₹{total_kitchen}\n🏨 Room Rent: ₹{total_room_rent}\n"
            f"-----------------------------------\n💳 *Grand Total:* ₹{grand_total}"
        )
        send_whatsapp_message(sender_phone, bill_reply)
        return

    # 4. Cohere AI Process
    print("[PROCESS] Querying Cohere AI...", flush=True)
    room_summary = get_room_inventory_summary()
    prompt_input = f"[IN-HOUSE GUEST Room {guest_info['room']}]\n{user_text}" if guest_info else f"[INVENTORY: {room_summary}]\n{user_text}"
    bot_reply = ask_cohere(prompt_input, sender_phone)

    # 5. Handle Alerts
    if "[KITCHEN_ALERT:" in bot_reply:
        match = re.search(r"\[KITCHEN_ALERT:\s*(.*?)(?:\s*\|\s*RATE:\s*(\d+))?\]", bot_reply)
        order_details = match.group(1).strip() if match and match.group(1) else "Food Order"
        parsed_rate = match.group(2).strip() if match and match.group(2) else "0"
        final_rate = int(parsed_rate) if int(parsed_rate) > 0 else resolve_item_price(order_details)
        bot_reply = re.sub(r"\[KITCHEN_ALERT:\s*.*?\]", "", bot_reply).strip()

        room_tag = f"Room {guest_info['room']} ({guest_info['name']})" if guest_info else "Unverified Room"
        kitchen_msg = f"🍳 *NEW FOOD ORDER*\n📌 {room_tag}\n📋 {order_details}\n💰 Bill: ₹{final_rate}\n📞 +{sender_phone}"
        send_whatsapp_message(KITCHEN_PHONE, kitchen_msg)
        threading.Thread(
            target=append_kitchen_order_to_sheet,
            args=(guest_info['room'] if guest_info else "N/A", guest_info['name'] if guest_info else "N/A", order_details, final_rate),
            daemon=True
        ).start()
        if not bot_reply:
            bot_reply = f"Ji, aapka order note ho gaya hai."

    if "[STAFF_ALERT:" in bot_reply:
        match = re.search(r"\[STAFF_ALERT:\s*(.*?)\]", bot_reply)
        details = match.group(1) if match else "Assistance"
        bot_reply = re.sub(r"\[STAFF_ALERT:\s*.*?\]", "", bot_reply).strip()
        room_tag = f"Room {guest_info['room']} ({guest_info['name']})" if guest_info else "Unverified"
        send_whatsapp_message(STAFF_PHONE, f"🛎️ *STAFF ALERT*\n📌 {room_tag}\n📋 {details}\n📞 +{sender_phone}")
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
    except Exception as e:
        print(f"[ASYNC WORKER ERROR]: {e}", flush=True)

# ==========================================
# 5. LIFECYCLE MONITOR
# ==========================================
def monitor_guest_status_lifecycle():
    print("[LIFECYCLE MONITOR]: Started.", flush=True)
    while True:
        try:
            records = fetch_sheet_records()
            for row in records:
                phone_val = row.get("Phone") or row.get("Phone (E)") or ""
                status_val = row.get("Status") or row.get("Status (F)") or ""
                name_val = row.get("Guest Name") or row.get("Guest Name (D)") or ""
                room_val = row.get("Room") or row.get("Room (A)") or ""

                phone = re.sub(r"\D", "", str(phone_val))[-10:]
                status = str(status_val).strip().upper()
                name = str(name_val).strip()
                room = str(room_val).strip()

                if not phone:
                    continue

                if status == "CHECKED_IN" and (phone not in welcomed_guests):
                    welcome_msg = (
                        f"Welcome to Hotel Ganga View, {name} ji! 🏨✨\n\n"
                        f"Aapka check-in Room {room} me complete ho gaya hai.\n"
                        f"Wi-Fi Password: *Ganga@2026*\n"
                        f"Room service ke liye yahan message karein. Namaste! 🙏"
                    )
                    send_whatsapp_message(phone, welcome_msg)
                    welcomed_guests.add(phone)

                elif status in ["CHECKED_OUT", "CHECKOUT"] and (phone not in checked_out_guests):
                    checkout_farewell = (
                        f"Namaste {name} ji! 🙏\n\n"
                        f"Room {room} ka check-out complete ho gaya hai aur bill settle ho gaya hai.\n\n"
                        f"Hotel Ganga View me rukne ke liye dhanyawad! Shubh Yatra! 🚩🌸"
                    )
                    send_whatsapp_message(phone, checkout_farewell)
                    checked_out_guests.add(phone)
        except Exception as e:
            print(f"[LIFECYCLE MONITOR ERROR]: {e}", flush=True)
        time.sleep(25)

# ==========================================
# 6. WEBHOOK ROUTES
# ==========================================
@app.route("/", methods=["GET"])
def index():
    return "Hotel Ganga View Bot is Live!", 200

@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "active"}), 200

@app.route("/webhook", methods=["GET"], strict_slashes=False)
def verify_webhook():
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge"), 200
    return "Forbidden", 403

@app.route("/webhook", methods=["POST"], strict_slashes=False)
def handle_webhook():
    data = request.get_json()
    try:
        messages = data.get("entry", [])[0].get("changes", [])[0].get("value", {}).get("messages", [])
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
# 7. WORKER ENTRY POINT
# ==========================================
def start_background_threads():
    threading.Thread(target=keep_awake_ping, daemon=True).start()
    threading.Thread(target=monitor_guest_status_lifecycle, daemon=True).start()
    print("[SYSTEM]: Background threads initialized safely.", flush=True)

start_background_threads()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
