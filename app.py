import os
import re
import time
import json
import threading
from datetime import datetime, timezone, timedelta
import requests
import gspread
from google.oauth2.service_account import Credentials
from flask import Flask, request, jsonify

IST = timezone(timedelta(hours=5, minutes=30))

# ==========================================
# 1. INITIALIZE APP & CONFIGURATION
# ==========================================
app = Flask(__name__)

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "").strip()
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "").strip()
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "").strip()
COHERE_API_KEY = os.getenv("COHERE_API_KEY", "").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")

KITCHEN_PHONE = os.getenv("KITCHEN_PHONE", "919058514478")
STAFF_PHONE = os.getenv("STAFF_PHONE", "919058514488")
SHEET_ID = "1E7iI0vSkRlwpiog-GUjN7Gfh35REAhfY_yVG0t63wqY"

RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "https://ganga-palace-bot.onrender.com")

shared_store = {
    "rooms": [],
    "kitchen_orders": [],
    "last_synced": 0
}

chat_histories = {}
processed_msg_ids = set()
welcomed_guests = set()
checked_out_guests = set()
notified_paid_orders = set()

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
# 2. CORE GSPREAD DATA ENGINE (LIVE & SYNC)
# ==========================================
def get_gspread_client():
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        return None
    try:
        creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(creds)
    except Exception:
        return None

def fetch_sheet_data_sync():
    client = get_gspread_client()
    if client:
        try:
            sh = client.open_by_key(SHEET_ID)
            
            # Rooms Sync
            r_data = sh.get_worksheet(0).get_all_values()
            if len(r_data) > 1:
                shared_store["rooms"] = r_data[1:]
                
            # Kitchen Sync
            k_data = sh.worksheet("Kitchen_Orders").get_all_values()
            if len(k_data) > 1:
                shared_store["kitchen_orders"] = k_data[1:]
                
            # Pre-fill Paid Notifiers
            for idx, k_row in enumerate(shared_store.get("kitchen_orders", []), start=2):
                if len(k_row) >= 6:
                    k_room = re.sub(r"\D", "", k_row[1])
                    k_amt = re.sub(r"\D", "", k_row[4]) or "0"
                    k_status = k_row[5].upper()
                    if "PAID" in k_status and int(k_amt) > 0:
                        notified_paid_orders.add(f"{k_room}_{idx}_{k_amt}")
                        
            shared_store["last_synced"] = time.time()
            print(f"[BOOT] Loaded {len(shared_store['rooms'])} Rooms and {len(shared_store['kitchen_orders'])} Orders.", flush=True)
        except Exception as e:
            print(f"[BOOT FETCH ERROR]: {e}", flush=True)

def sync_sheets_in_background():
    client = get_gspread_client()
    while True:
        try:
            if not client:
                client = get_gspread_client()
            if client:
                sh = client.open_by_key(SHEET_ID)
                
                try:
                    r_data = sh.get_worksheet(0).get_all_values()
                    if len(r_data) > 1:
                        shared_store["rooms"] = r_data[1:]
                except Exception: pass
                
                try:
                    k_data = sh.worksheet("Kitchen_Orders").get_all_values()
                    if len(k_data) > 1:
                        shared_store["kitchen_orders"] = k_data[1:]
                except Exception: pass
                
                shared_store["last_synced"] = time.time()
        except Exception:
            client = None
        time.sleep(10)

def append_kitchen_order_to_sheet(room, guest_name, order_details, amount):
    client = get_gspread_client()
    if not client: return
    try:
        clean_amount = int(re.sub(r"\D", "", str(amount))) if re.sub(r"\D", "", str(amount)) else 0
        if clean_amount <= 0:
            clean_amount = resolve_item_price(order_details)

        sheet = client.open_by_key(SHEET_ID).worksheet("Kitchen_Orders")
        now_str = datetime.now(IST).strftime("%d-%b %I:%M %p")
        row_data = [now_str, str(room), str(guest_name), str(order_details), int(clean_amount), "PENDING"]
        sheet.append_row(row_data)
        print(f"[SHEET WRITE OK] Added order: {row_data}", flush=True)
    except Exception as e:
        print(f"[SHEET WRITE FAIL]: {e}", flush=True)

def calculate_stay_nights(check_in_str):
    if not check_in_str: return 1
    clean_date = str(check_in_str).strip()
    for fmt in ["%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y"]:
        try:
            return max(1, (datetime.now(IST).date() - datetime.strptime(clean_date, fmt).date()).days)
        except ValueError:
            continue
    return 1

def get_guest_stay_status(sender_phone):
    clean_sender = re.sub(r"\D", "", str(sender_phone))[-10:]
    for row in shared_store.get("rooms", []):
        vals_str = [str(v).strip() for v in row]
        if any(clean_sender == re.sub(r"\D", "", v)[-10:] for v in vals_str if len(re.sub(r"\D", "", v)) >= 10) and any("IN" in v.upper() for v in vals_str):
            return {
                "is_inhouse": True,
                "room": re.sub(r"\D", "", vals_str[0]) or "101",
                "category": vals_str[1] if len(vals_str) > 1 else "Deluxe",
                "price": re.sub(r"\D", "", vals_str[2]) or "1800",
                "name": vals_str[3] if len(vals_str) > 3 else "Guest",
                "check_in_date": vals_str[6] if len(vals_str) > 6 else "12-09-2026"
            }
    return None

def get_guest_comprehensive_financials(room_number, sender_phone=""):
    clean_sender = re.sub(r"\D", "", str(sender_phone))[-10:] if sender_phone else ""
    target_room_digits = re.sub(r"\D", "", str(room_number))

    total_kitchen = 0
    paid_kitchen = 0
    kitchen_items_pending = []
    kitchen_items_paid = []

    for vals in shared_store.get("kitchen_orders", []):
        if len(vals) < 5: continue
        if re.sub(r"\D", "", str(vals[1])) != target_room_digits: continue

        item_name = vals[3].strip() if len(vals) > 3 and vals[3].strip() else "Food Order"
        raw_amt_str = str(vals[4]).strip() if len(vals) > 4 else "0"
        status_str = str(vals[5]).strip().upper() if len(vals) > 5 else "PENDING"

        raw_digits = re.sub(r"\D", "", raw_amt_str)
        amt = int(raw_digits) if raw_digits else 0
        if amt <= 0: amt = resolve_item_price(item_name)

        total_kitchen += amt
        if "PAID" in status_str:
            paid_kitchen += amt
            kitchen_items_paid.append(f"• {item_name} - ₹{amt} (PAID)")
        else:
            kitchen_items_pending.append(f"• {item_name} - ₹{amt}")

    room_rate_per_night, nights, room_advance_paid, guest_name = 1800, 1, 0, "Guest"
    for vals in shared_store.get("rooms", []):
        if len(vals) >= 5:
            r_phone = re.sub(r"\D", "", vals[4])[-10:] if len(vals) > 4 else ""
            if re.sub(r"\D", "", str(vals[0])) == target_room_digits or (clean_sender and r_phone == clean_sender):
                p_digits = re.sub(r"\D", "", vals[2]) if len(vals) > 2 else "1800"
                if p_digits and int(p_digits) < 50000: room_rate_per_night = int(p_digits)
                guest_name = vals[3] if len(vals) > 3 and vals[3] else "Guest"
                if len(vals) > 6: nights = calculate_stay_nights(vals[6])
                break

    return {
        "guest_name": guest_name,
        "nights": nights,
        "room_rate": room_rate_per_night,
        "total_room_rent": room_rate_per_night * nights,
        "room_advance_paid": room_advance_paid,
        "total_kitchen": total_kitchen,
        "paid_kitchen": paid_kitchen,
        "pending_kitchen": max(0, total_kitchen - paid_kitchen),
        "kitchen_pending_items": kitchen_items_pending,
        "kitchen_paid_items": kitchen_items_paid,
        "grand_total": total_kitchen + (room_rate_per_night * nights),
        "total_paid": paid_kitchen + room_advance_paid,
        "balance_due": max(0, (total_kitchen + (room_rate_per_night * nights)) - (paid_kitchen + room_advance_paid))
    }

# ==========================================
# 3. DISPATCH ENGINE
# ==========================================
def mark_message_as_read(message_id):
    def _mark():
        pid = (PHONE_NUMBER_ID or "").strip()
        if not pid or not WHATSAPP_TOKEN: return
        url = f"https://graph.facebook.com/v20.0/{pid}/messages"
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
        requests.post(url, json={"messaging_product": "whatsapp", "status": "read", "message_id": message_id}, headers=headers, timeout=5)
    threading.Thread(target=_mark, daemon=True).start()

def send_whatsapp_message(to_number, text):
    def _do():
        clean_number = format_whatsapp_number(to_number)
        if not clean_number or not PHONE_NUMBER_ID or not WHATSAPP_TOKEN: return
        url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
        requests.post(url, json={"messaging_product": "whatsapp", "to": clean_number, "type": "text", "text": {"body": text}}, headers=headers, timeout=10)
    threading.Thread(target=_do, daemon=True).start()

def send_whatsapp_image(to_number, image_url, caption=""):
    def _do_img():
        clean_number = format_whatsapp_number(to_number)
        if not clean_number or not PHONE_NUMBER_ID or not WHATSAPP_TOKEN: return
        url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
        payload = {"messaging_product": "whatsapp", "to": clean_number, "type": "image", "image": {"link": image_url.strip(), "caption": caption}}
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=12)
            if res.status_code != 200: send_whatsapp_message(clean_number, f"{caption}\n\n🖼️ Link: {image_url}")
        except Exception:
            send_whatsapp_message(clean_number, f"{caption}\n\n🖼️ Link: {image_url}")
    threading.Thread(target=_do_img, daemon=True).start()

def ask_cohere(user_message):
    if not COHERE_API_KEY: return None
    url = "https://api.cohere.ai/v1/chat"
    headers = {"Authorization": f"Bearer {COHERE_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "command-r",
        "message": user_message,
        "preamble": "You are WhatsApp AI Receptionist for Hotel Ganga View, Haridwar. Reply politely in 1-2 lines Hinglish.",
        "temperature": 0.2
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=5)
        if res.status_code == 200: return res.json().get("text", "").strip()
    except Exception: pass
    return None

# ==========================================
# 4. MESSAGE PROCESSING ROUTER
# ==========================================
def process_and_reply(user_text, sender_phone):
    text_lower = user_text.lower().strip()
    guest_info = get_guest_stay_status(sender_phone)

    # 1. LOCATION
    if any(lw in text_lower for lw in ["location", "map", "address", "kahan hai", "pauri", "direction"]):
        send_whatsapp_message(sender_phone, "📍 *Hotel Ganga View, Haridwar*\nHar Ki Pauri se sirf 2 minute ki walking distance par!\n🗺️ *Map:* https://maps.google.com/?q=29.9530,78.1700")
        return

    # 2. PHOTOS
    if any(pw in text_lower for pw in ["photo", "photos", "pic", "image", "tasveer"]):
        send_whatsapp_image(sender_phone, "https://raw.githubusercontent.com/yrskaran/ganga-palace-bot/main/images/main.jpg", "🏨 *Hotel Ganga View, Haridwar* (Near Har Ki Pauri)\n• Standard Non-AC: ₹1,800/night\n• Deluxe AC Room: ₹2,500/night")
        return

    # 3. BILL HANDLER (WITH LIVE FORCE FETCH)
    if guest_info and re.search(r"(bill|bil|total|hisaab|hisab|kharcha|baki|due|paid|kitna hua|balance|bta)", text_lower):
        
        # LIVE FETCH GUARANTEE: Force fetch from sheet microseconds before calculating
        client = get_gspread_client()
        if client:
            try:
                live_k = client.open_by_key(SHEET_ID).worksheet("Kitchen_Orders").get_all_values()
                if len(live_k) > 1: shared_store["kitchen_orders"] = live_k[1:]
            except Exception: pass
            
        fin = get_guest_comprehensive_financials(guest_info['room'], sender_phone)
        asks_room = any(k in text_lower for k in ["kamre ka", "room ka", "room rent", "stay ka", "rent", "tariff"])
        asks_complete = any(k in text_lower for k in ["pura bill", "complete bill", "grand total", "pura hisab", "checkout"])

        if asks_room and not asks_complete:
            adv_str = f"✅ *Advance Paid:* ₹{fin['room_advance_paid']}\n" if fin['room_advance_paid'] > 0 else ""
            send_whatsapp_message(sender_phone, f"🏨 *Room {guest_info['room']} - Room Rent Details*\nGuest Name: {fin['guest_name']} ji\nStay Duration: {fin['nights']} Night\nPer Night Rate: ₹{fin['room_rate']}\n\n💰 *Total Room Tariff:* ₹{fin['total_room_rent']}\n{adv_str}⚠️ *Room Tariff Due:* ₹{max(0, fin['total_room_rent'] - fin['room_advance_paid'])}")
            return

        if asks_complete:
            send_whatsapp_message(sender_phone, f"🧾 *Room {guest_info['room']} - Complete Bill*\nGuest: {fin['guest_name']} ji ({fin['nights']} Night)\n\n🏨 *Room Rent:* ₹{fin['total_room_rent']}\n🍳 *Kitchen Total:* ₹{fin['total_kitchen']}\n------------------------\n💵 *Grand Total:* ₹{fin['grand_total']}\n✅ *Paid:* ₹{fin['total_paid']}\n------------------------\n💳 *Balance Due:* ₹{fin['balance_due']}")
            return

        # Default Kitchen Bill
        pending_list = "\n".join(fin["kitchen_pending_items"]) if fin["kitchen_pending_items"] else "• Koi pending order nahi hai"
        paid_section = f"\n\n*Already Paid Orders:*\n" + "\n".join(fin["kitchen_paid_items"]) if fin["kitchen_paid_items"] else ""
        send_whatsapp_message(sender_phone, f"🍳 *Room {guest_info['room']} - Kitchen Orders Bill*\nGuest: {fin['guest_name']} ji\n\n📋 *Pending Orders:*\n{pending_list}{paid_section}\n\n------------------------\n💰 *Total Kitchen Orders:* ₹{fin['total_kitchen']}\n✅ *Aapne Jamah Kar Diya (PAID):* ₹{fin['paid_kitchen']}\n------------------------\n⚠️ *Bacha Hua (Balance Due):* ₹{fin['pending_kitchen']}")
        return

    # 4. GREETINGS
    if text_lower in ["hi", "hello", "namaste", "hey", "start", "hlo"] or len(text_lower) <= 2:
        if guest_info:
            send_whatsapp_message(sender_phone, f"Namaste {guest_info['name']} ji! 🙏\nRoom {guest_info['room']} me aapka swagat hai. Wi-Fi: Ganga@2026\nBatayein kya khana order karna hai?")
        else:
            send_whatsapp_message(sender_phone, "Namaste! 🙏 Welcome to *Hotel Ganga View, Haridwar*.\nRoom rates dekhne ya book karne ke liye reply karein.")
        return

    # 5. ORDER & COMPLAINTS
    is_complaint = any(cw in text_lower for cw in ["thandi", "kharab", "bekar", "nahi chal", "not working", "badbu", "late", "problem", "shikayat"])
    if guest_info and any(w in text_lower for w in ["chai", "tea", "roti", "khana", "paratha", "poha", "bhature", "order", "coffee", "dahi", "dal", "paneer"]) and not is_complaint:
        total_price = resolve_item_price(user_text)
        threading.Thread(target=append_kitchen_order_to_sheet, args=(guest_info['room'], guest_info['name'], user_text, total_price), daemon=True).start()
        send_whatsapp_message(KITCHEN_PHONE, f"🍳 *NEW ORDER*\n📌 Room: {guest_info['room']} ({guest_info['name']})\n📋 Order: {user_text}\n💰 Amount: ₹{total_price}\n📞 Contact: +{sender_phone}")
        send_whatsapp_message(sender_phone, f"Ji {guest_info['name']} ji! Aapka order note ho gaya hai:\n🍽️ Item: {user_text}\n💰 Bill: ₹{total_price}\nAgli 15-20 minutes me deliver ho jayega. 🙏")
        return

    # 6. COHERE FALLBACK
    bot_reply = ask_cohere(f"[IN-HOUSE GUEST: Room {guest_info['room']}]\n{user_text}" if guest_info else f"[INQUIRY]\n{user_text}")
    if not bot_reply:
        bot_reply = f"[STAFF_ALERT: {user_text}] Ji, shikayat note kar li gayi hai." if is_complaint else "Ji batayein, mai kya sahayata kar sakta hoon?"

    if "[STAFF_ALERT:" in bot_reply or is_complaint:
        bot_reply = re.sub(r"\[STAFF_ALERT:\s*.*?\]", "", bot_reply).strip()
        send_whatsapp_message(STAFF_PHONE, f"🛎️ *STAFF ALERT*\n📌 Location: Room {guest_info['room']} ({guest_info['name']})\n📋 Details: {user_text}\n📞 Contact: +{sender_phone}")

    if bot_reply:
        send_whatsapp_message(sender_phone, bot_reply.strip())

# ==========================================
# 5. LIFECYCLE MONITOR
# ==========================================
def monitor_guest_status_lifecycle():
    while True:
        try:
            room_phone_map = {}
            for row in shared_store.get("rooms", []):
                if len(row) >= 5:
                    room, name, phone, status = re.sub(r"\D", "", row[0]), row[3], re.sub(r"\D", "", row[4])[-10:] if len(row)>4 else "", row[5].upper() if len(row)>5 else ""
                    if not phone: continue
                    room_phone_map[room] = phone

                    if "CHECKED_IN" in status and phone not in welcomed_guests:
                        send_whatsapp_message(phone, f"Welcome to Hotel Ganga View, {name} ji! 🏨✨\nRoom {room} check-in complete. Wi-Fi: Ganga@2026")
                        welcomed_guests.add(phone)
                    elif "CHECKOUT" in status and phone not in checked_out_guests:
                        send_whatsapp_message(phone, f"Namaste {name} ji! 🙏\nRoom {room} check-out complete. Hotel Ganga View me rukne ke liye dhanyawad! Shubh Yatra! 🚩")
                        checked_out_guests.add(phone)

            for idx, k_row in enumerate(shared_store.get("kitchen_orders", []), start=2):
                if len(k_row) >= 6:
                    k_room, k_item, k_amt, k_status = re.sub(r"\D", "", k_row[1]), k_row[3], re.sub(r"\D", "", k_row[4]) or "0", k_row[5].upper()
                    if int(k_amt) <= 0: continue
                    
                    unique_order_key = f"{k_room}_{idx}_{k_amt}"
                    if "PAID" in k_status and unique_order_key not in notified_paid_orders:
                        guest_ph = room_phone_map.get(k_room)
                        if guest_ph:
                            send_whatsapp_message(guest_ph, f"✅ *Payment Received Confirmation*\n\nNamaste ji! Room {k_room} ke liye ₹{k_amt} ({k_item}) ki payment successfully receive ho gayi hai. 🙏")
                            notified_paid_orders.add(unique_order_key)
        except Exception: pass
        time.sleep(15)

# ==========================================
# 6. SERVER ROUTES
# ==========================================
@app.route("/", methods=["GET"])
def index(): return "Enterprise Bot Active", 200

@app.route("/health", methods=["GET"])
def health(): return jsonify({"status": "active"}), 200

@app.route("/webhook", methods=["GET", "POST"], strict_slashes=False)
def webhook():
    if request.method == "GET":
        return request.args.get("hub.challenge") if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == VERIFY_TOKEN else ("Forbidden", 403)
    
    try:
        msg = request.get_json().get("entry", [])[0].get("changes", [])[0].get("value", {}).get("messages", [])[0]
        msg_id, sender = msg.get("id"), msg.get("from")
        if msg_id in processed_msg_ids: return jsonify({"status": "duplicate"}), 200
        processed_msg_ids.add(msg_id)
        mark_message_as_read(message_id)

        if msg.get("type") == "text":
            threading.Thread(target=process_and_reply, args=(msg.get("text", {}).get("body", ""), sender), daemon=True).start()
    except Exception: pass
    return jsonify({"status": "success"}), 200

def keep_awake_ping():
    time.sleep(15)
    while True:
        try: requests.get(f"{RENDER_EXTERNAL_URL.rstrip('/')}/health", timeout=5)
        except Exception: pass
        time.sleep(8 * 60)

print("[SYSTEM] Booting Application...", flush=True)
fetch_sheet_data_sync()
threading.Thread(target=sync_sheets_in_background, daemon=True).start()
threading.Thread(target=monitor_guest_status_lifecycle, daemon=True).start()
threading.Thread(target=keep_awake_ping, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
