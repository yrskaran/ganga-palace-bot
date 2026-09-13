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

IST = timezone(timedelta(hours=5, minutes=30))

# ==========================================
# 1. INITIALIZE APP & CONFIGURATION
# ==========================================
app = Flask(__name__)

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "").strip()
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "").strip()
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "").strip()
COHERE_API_KEY = os.getenv("COHERE_API_KEY", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")

KITCHEN_PHONE = os.getenv("KITCHEN_PHONE", "919058514478")
STAFF_PHONE = os.getenv("STAFF_PHONE", "919058514488")

HOTEL_LAT = "29.9530"
HOTEL_LON = "78.1700"
SHEET_ID = os.getenv("SHEET_ID", "1E7iI0vSkRlwpiog-GUjN7Gfh35REAhfY_yVG0t63wqY").strip()

RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "https://ganga-palace-bot.onrender.com")

HOTEL_IMAGES = {
    "front": "https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=1200&q=80",
    "deluxe": "https://images.unsplash.com/photo-1618773928121-c32242e63f39?auto=format&fit=crop&w=1200&q=80",
    "standard": "https://images.unsplash.com/photo-1590490360182-c33d57733427?auto=format&fit=crop&w=1200&q=80"
}

chat_histories = {}
processed_msg_ids = set()

shared_store = {
    "rooms": [],
    "kitchen_orders": [],
    "last_synced": 0
}

# State Tracking Sets
welcomed_guests = set()
checked_out_guests = set()
notified_paid_orders = set()
is_first_sync = True

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
        line_total += matched_rate * qty
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
# 2. BACKGROUND DATA SYNC
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
    except Exception:
        return None

def sync_sheets_in_background():
    while True:
        try:
            csv_url_rooms = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=Rooms"
            try:
                res_r = requests.get(csv_url_rooms, timeout=4)
                if res_r.status_code == 200:
                    records = list(csv.DictReader(io.StringIO(res_r.content.decode("utf-8"))))
                    if records:
                        shared_store["rooms"] = records
            except Exception:
                pass

            csv_url_kitch = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=Kitchen_Orders"
            try:
                res_k = requests.get(csv_url_kitch, timeout=4)
                if res_k.status_code == 200:
                    k_records = list(csv.DictReader(io.StringIO(res_k.content.decode("utf-8"))))
                    if k_records:
                        shared_store["kitchen_orders"] = k_records
            except Exception:
                pass

            shared_store["last_synced"] = time.time()
        except Exception:
            pass

        time.sleep(10)

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
    except Exception:
        pass

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

def get_guest_stay_status(sender_phone):
    clean_sender = re.sub(r"\D", "", str(sender_phone))[-10:]
    records = shared_store.get("rooms", [])

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
    return None

def get_guest_comprehensive_financials(room_number, sender_phone=""):
    clean_sender = re.sub(r"\D", "", str(sender_phone))[-10:] if sender_phone else ""
    total_kitchen = 0
    paid_kitchen = 0
    kitchen_items_pending = []

    k_records = shared_store.get("kitchen_orders", [])
    for r in k_records:
        r_room = str(r.get("Room") or r.get("Room (B)") or "").strip()
        r_status = str(r.get("Payment_Status") or r.get("Payment_Status (F)") or "").strip().upper()

        if r_room == str(room_number).strip():
            item_name = r.get("Order Details") or r.get("Order Details (D)") or "Item"
            raw_amt = str(r.get("Amount") or r.get("Amount (E)") or "0")
            amt_digits = re.sub(r"\D", "", raw_amt)
            amt = int(amt_digits) if amt_digits else 0
            if amt <= 0:
                amt = resolve_item_price(item_name)

            total_kitchen += amt
            if r_status == "PAID":
                paid_kitchen += amt
            else:
                kitchen_items_pending.append(f"• {item_name} - ₹{amt}")

    records_rooms = shared_store.get("rooms", [])
    room_rate_per_night = 0
    nights = 1
    room_advance_paid = 0
    guest_name = "Guest"

    for r in records_rooms:
        r_phone = re.sub(r"\D", "", str(r.get("Phone") or r.get("Phone (E)") or ""))[-10:]
        r_room = str(r.get("Room") or r.get("Room (A)") or "").strip()

        if r_room == str(room_number).strip() or (clean_sender and r_phone == clean_sender):
            guest_name = str(r.get("Guest Name") or r.get("Guest Name (D)") or "Guest").strip()
            price_val = str(r.get("Price") or r.get("Price (C)") or "0")
            price_digits = re.sub(r"\D", "", price_val)
            room_rate_per_night = int(price_digits) if price_digits else 0

            check_in_str = r.get("Check_In_Date") or r.get("Check_In_Date (G)") or ""
            nights = calculate_stay_nights(check_in_str)

            adv_val = str(r.get("Advance_Paid") or r.get("Paid") or r.get("Advance") or "0")
            adv_digits = re.sub(r"\D", "", adv_val)
            room_advance_paid = int(adv_digits) if adv_digits else 0
            break

    total_room_rent = room_rate_per_night * nights
    pending_kitchen = total_kitchen - paid_kitchen
    grand_total = total_kitchen + total_room_rent
    total_paid = paid_kitchen + room_advance_paid
    balance_due = max(0, grand_total - total_paid)

    return {
        "guest_name": guest_name,
        "nights": nights,
        "room_rate": room_rate_per_night,
        "total_room_rent": total_room_rent,
        "room_advance_paid": room_advance_paid,
        "total_kitchen": total_kitchen,
        "paid_kitchen": paid_kitchen,
        "pending_kitchen": pending_kitchen,
        "kitchen_pending_items": kitchen_items_pending,
        "grand_total": grand_total,
        "total_paid": total_paid,
        "balance_due": balance_due
    }

# ==========================================
# 3. DISPATCH ENGINE (GREEN TICK + SEND)
# ==========================================
def keep_awake_ping():
    time.sleep(15)
    while True:
        try:
            target_url = f"{RENDER_EXTERNAL_URL.rstrip('/')}/health"
            requests.get(target_url, timeout=5)
        except Exception:
            pass
        time.sleep(8 * 60)

def mark_message_as_read(message_id):
    pid = (PHONE_NUMBER_ID or "").strip()
    if not pid or not WHATSAPP_TOKEN:
        return
    url = f"https://graph.facebook.com/v20.0/{pid}/messages"
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
        res = requests.post(url, json=payload, headers=headers, timeout=5)
        print(f"[META GREEN TICK] Status: {res.status_code} | Msg: {message_id}", flush=True)
    except Exception as e:
        print(f"[META GREEN TICK FAIL]: {e}", flush=True)

def send_whatsapp_message(to_number, text):
    def _do():
        clean_number = format_whatsapp_number(to_number)
        if not clean_number:
            return

        pid = (PHONE_NUMBER_ID or "").strip()
        if not pid or not WHATSAPP_TOKEN:
            return

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
            res = requests.post(url, json=payload, headers=headers, timeout=10)
            print(f"[META DISPATCH] Status: {res.status_code} | Target: {clean_number}", flush=True)
        except Exception as e:
            print(f"[DISPATCH EXCEPTION]: {e}", flush=True)
    threading.Thread(target=_do, daemon=True).start()

def send_whatsapp_image(to_number, image_url, caption=""):
    def _do_img():
        clean_number = format_whatsapp_number(to_number)
        if not clean_number:
            return

        pid = (PHONE_NUMBER_ID or "").strip()
        if not pid or not WHATSAPP_TOKEN:
            return

        url = f"https://graph.facebook.com/v20.0/{pid}/messages"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": clean_number,
            "type": "image",
            "image": {
                "link": image_url.strip(),
                "caption": caption
            }
        }
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=12)
            print(f"[META IMAGE] Status: {res.status_code} | Target: {clean_number}", flush=True)
            if res.status_code != 200:
                send_whatsapp_message(clean_number, f"{caption}\n\n🖼️ Link: {image_url}")
        except Exception:
            send_whatsapp_message(clean_number, f"{caption}\n\n🖼️ Link: {image_url}")
    threading.Thread(target=_do_img, daemon=True).start()

def ask_cohere(user_message, sender_phone):
    if not COHERE_API_KEY:
        return None
    url = "https://api.cohere.ai/v1/chat"
    headers = {"Authorization": f"Bearer {COHERE_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "message": user_message,
        "preamble": (
            "You are the WhatsApp AI Receptionist for Hotel Ganga View, Haridwar. "
            "Help guests with room types, rates (Standard: ₹1,800, Deluxe: ₹2,500), "
            "location (Near Har Ki Pauri) and answer questions politely in 1-2 lines Hinglish."
        ),
        "temperature": 0.1
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=4)
        if res.status_code == 200:
            reply_text = res.json().get("text", "").strip()
            if reply_text:
                return reply_text
    except Exception:
        pass
    return None

# ==========================================
# 4. MESSAGE PROCESS PIPELINE
# ==========================================
def process_and_reply(user_text, sender_phone):
    print(f"[PROCESS START] '{user_text}' from {sender_phone}", flush=True)
    text_lower = user_text.lower().strip()

    guest_info = get_guest_stay_status(sender_phone)
    print(f"[PROCESS] In-house guest: {bool(guest_info)}", flush=True)

    # 1. LOCATION HANDLER
    loc_words = ["location", "map", "address", "kahan hai", "pauri", "reach", "direction", "rasta", "kahan sthit", "kaha pe"]
    if any(lw in text_lower for lw in loc_words):
        loc_msg = (
            "📍 *Hotel Ganga View, Haridwar*\n"
            "Har Ki Pauri se sirf 2 minute ki walking distance par sthit hai!\n\n"
            "🗺️ *Google Maps Direction:*\n"
            "https://maps.google.com/?q=29.9530,78.1700\n\n"
            "Koi bhi sahayata ke liye aap direct call kar sakte hain! 🙏"
        )
        send_whatsapp_message(sender_phone, loc_msg)
        return

    # 2. PHOTO HANDLER
    photo_words = ["photo", "photos", "pic", "pics", "image", "tasveer", "dekhna", "dikhao", "dede", "kamra"]
    if any(pw in text_lower for pw in photo_words):
        send_whatsapp_image(
            sender_phone,
            "https://raw.githubusercontent.com/yrskaran/ganga-palace-bot/main/images/main.jpg",
            caption="🏨 *Hotel Ganga View, Haridwar* (Near Har Ki Pauri)"
        )
        fallback_showcase = (
            "🏨 *Hotel Ganga View, Haridwar* 🌸\n"
            "📍 *Location:* Near Har Ki Pauri (2 mins walking)\n\n"
            "📸 *Direct Photo:*\n"
            "https://raw.githubusercontent.com/yrskaran/ganga-palace-bot/main/images/main.jpg\n\n"
            "💰 *Rates:*\n"
            "• *Standard Non-AC:* ₹1,800 / night\n"
            "• *Deluxe AC Room:* ₹2,500 / night\n\n"
            "Booking ke liye apni dates batayein! 🙏"
        )
        send_whatsapp_message(sender_phone, fallback_showcase)
        return

    # 3. IN-HOUSE BILL HANDLER (Sirf Checked-in Guest ke liye)
    bill_pattern = r"(bill|bil|total|hisaab|hisab|kharcha|baki|due|paid|kitna hua|balance)"
    if guest_info and re.search(bill_pattern, text_lower):
        fin = get_guest_comprehensive_financials(guest_info['room'], sender_phone)
        is_only_kitchen = any(k in text_lower for k in ["kichen", "kitchen", "khana", "khane", "food", "nashta", "chai"])
        is_only_room = any(k in text_lower for k in ["room", "kamra", "kamre", "stay", "rent", "tariff"])

        if is_only_kitchen and not is_only_room:
            pending_items = "\n".join(fin["kitchen_pending_items"]) if fin["kitchen_pending_items"] else "• Koi order pending nahi"
            paid_str = f"✅ *Paid Amount:* ₹{fin['paid_kitchen']}\n" if fin['paid_kitchen'] > 0 else ""
            bill_reply = (
                f"🍳 *Room {guest_info['room']} - Kitchen Orders*\n"
                f"Guest: {fin['guest_name']} ji\n\n"
                f"*Pending Orders:*\n{pending_items}\n\n"
                f"💰 *Total Kitchen:* ₹{fin['total_kitchen']}\n"
                f"{paid_str}"
                f"⚠️ *Kitchen Balance:* ₹{fin['pending_kitchen']}"
            )
            send_whatsapp_message(sender_phone, bill_reply)
            return

        bill_reply = (
            f"🧾 *Room {guest_info['room']} - Bill Statement*\n"
            f"Guest Name: {fin['guest_name']} ji\n\n"
            f"🏨 *Room Rent:* ₹{fin['total_room_rent']}\n"
            f"🍳 *Kitchen Orders:* ₹{fin['total_kitchen']}\n"
            f"💵 *Grand Total:* ₹{fin['grand_total']}\n\n"
            f"✅ *Paid:* ₹{fin['total_paid']}\n"
            f"💳 *Balance Due:* ₹{fin['balance_due']}"
        )
        send_whatsapp_message(sender_phone, bill_reply)
        return

    # 4. GREETINGS
    greetings = ["hi", "hello", "namaste", "hey", "start", "hlo", "helo", "good", "bol", "bolo"]
    if text_lower in greetings or len(text_lower) <= 3:
        if guest_info:
            reply_msg = (
                f"Namaste {guest_info['name']} ji! 🙏\n"
                f"Aapka swagat hai Room {guest_info['room']}.\n"
                f"📶 *Wi-Fi Password:* Ganga@2026\n\n"
                f"Batayein, mai aapke liye khana mangwaun ya housekeeping bhejun?"
            )
        else:
            reply_msg = (
                "Namaste! 🙏 Welcome to *Hotel Ganga View, Haridwar* (Near Har Ki Pauri).\n\n"
                "Aap yahan se room rates dekh sakte hain ya photos mangwa sakte hain. "
                "Batayein mai aapki kya sahayata kar sakta hoon?"
            )
        send_whatsapp_message(sender_phone, reply_msg)
        return

    # 5. FALLBACK / AI RESOLVER
    prompt_input = (
        f"[IN-HOUSE GUEST: Room {guest_info['room']}]\n{user_text}" 
        if guest_info 
        else f"[PROSPECTIVE CUSTOMER INQUIRY]\n{user_text}"
    )
    bot_reply = ask_cohere(prompt_input, sender_phone)
    if not bot_reply:
        bot_reply = "Hamare paas Standard (₹1,800) aur Deluxe AC Rooms (₹2,500) uplabdh hain. Photos dekhne ke liye 'Room photo' likhein ya dates batayein!"

    send_whatsapp_message(sender_phone, bot_reply)

# ==========================================
# 5. LIFECYCLE MONITOR (CHECKIN & CHECKOUT MSG ON, RESTART SPAM OFF)
# ==========================================
def monitor_guest_status_lifecycle():
    global is_first_sync
    while True:
        try:
            records = shared_store.get("rooms", [])
            active_rooms = {}        # Room -> phone (Sirf CHECKED_IN)
            checked_out_rooms = set() # Check-out hue rooms

            # 1. Pehle current sheet ka state build karo
            current_checked_in = {}
            current_checked_out = {}

            for row in records:
                phone_val = row.get("Phone") or row.get("Phone (E)") or ""
                status_val = row.get("Status") or row.get("Status (F)") or ""
                name_val = row.get("Guest Name") or row.get("Guest Name (D)") or ""
                room_val = row.get("Room") or row.get("Room (A)") or ""

                phone = re.sub(r"\D", "", str(phone_val))[-10:]
                status = str(status_val).strip().upper()
                name = str(name_val).strip()
                room = str(room_val).strip()

                if not phone or not room:
                    continue

                if status in ["CHECKED_OUT", "CHECKOUT"]:
                    checked_out_rooms.add(room)
                    current_checked_out[phone] = {"name": name, "room": room}

                elif status == "CHECKED_IN":
                    active_rooms[room] = phone
                    current_checked_in[phone] = {"name": name, "room": room}

            # First sync boot grace: Purane data ko baseline banao taaki server start hote hi 5 msg na feke
            if is_first_sync:
                welcomed_guests.update(current_checked_in.keys())
                checked_out_guests.update(current_checked_out.keys())
                
                # Saare purane paid orders ko memoize karo
                k_records = shared_store.get("kitchen_orders", [])
                for idx, k_row in enumerate(k_records, start=2):
                    k_room = str(k_row.get("Room") or k_row.get("Room (B)") or "").strip()
                    k_amt = str(k_row.get("Amount") or k_row.get("Amount (E)") or "0")
                    k_status = str(k_row.get("Payment_Status") or k_row.get("Payment_Status (F)") or "").strip().upper()
                    if k_status == "PAID":
                        notified_paid_orders.add(f"{k_room}_{idx}_{k_amt}")
                
                is_first_sync = False
                time.sleep(8)
                continue

            # CHECK-IN MESSAGE (Jab koi naya guest CHECKED_IN ho)
            for phone, gdata in current_checked_in.items():
                if phone not in welcomed_guests:
                    welcome_msg = (
                        f"Welcome to Hotel Ganga View, {gdata['name']} ji! 🏨✨\n\n"
                        f"Aapka check-in Room {gdata['room']} me successfully complete ho gaya hai.\n"
                        f"📶 *Wi-Fi Password:* Ganga@2026\n"
                        f"Room service ya order ke liye bas yahan message karein. Namaste! 🙏"
                    )
                    send_whatsapp_message(phone, welcome_msg)
                    welcomed_guests.add(phone)

            # CHECK-OUT MESSAGE (Jab koi guest CHECKED_OUT ho)
            for phone, gdata in current_checked_out.items():
                if phone not in checked_out_guests:
                    checkout_farewell = (
                        f"Namaste {gdata['name']} ji! 🙏\n\n"
                        f"Room {gdata['room']} ka check-out complete ho gaya hai aur account settle ho gaya hai.\n\n"
                        f"Hotel Ganga View, Haridwar me rukne ke liye bahut dhanyawad! Shubh Yatra! 🚩🌸"
                    )
                    send_whatsapp_message(phone, checkout_farewell)
                    checked_out_guests.add(phone)

            # KITCHEN PAYMENT NOTIFICATIONS (SIRF IN-HOUSE KE LIYE - CHECKOUT KO BLOCK)
            k_records = shared_store.get("kitchen_orders", [])
            for idx, k_row in enumerate(k_records, start=2):
                k_room = str(k_row.get("Room") or k_row.get("Room (B)") or "").strip()
                k_status = str(k_row.get("Payment_Status") or k_row.get("Payment_Status (F)") or "").strip().upper()
                k_amt = str(k_row.get("Amount") or k_row.get("Amount (E)") or "0")
                k_item = str(k_row.get("Order Details") or k_row.get("Order Details (D)") or "Order")

                unique_order_key = f"{k_room}_{idx}_{k_amt}"

                # Checkout hue rooms ko kitchen order message bilkul nahi bhejna
                if k_room in checked_out_rooms or k_room not in active_rooms:
                    continue

                if k_status == "PAID" and (unique_order_key not in notified_paid_orders):
                    guest_ph = active_rooms.get(k_room)
                    if guest_ph:
                        receipt_msg = (
                            f"✅ *Payment Received Confirmation*\n\n"
                            f"Room {k_room} ke liye ₹{k_amt} ({k_item}) payment receive ho gayi hai. Dhanyawad! 🙏"
                        )
                        send_whatsapp_message(guest_ph, receipt_msg)
                    notified_paid_orders.add(unique_order_key)

        except Exception:
            pass

        time.sleep(12)

# ==========================================
# 6. WEBHOOK ROUTES
# ==========================================
@app.route("/", methods=["GET"])
def index():
    return "Hotel Ganga View Bot is Live!", 200

@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "active"}), 200

@app.route('/webhook', methods=['POST'])
def webhook_post():
    data = request.get_json()
    print("[DEBUG PAYLOAD]", json.dumps(data), flush=True)
    # Baaki code yahan se continue hoga...

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
            
            # TURANT READ TICK (GREEN DOUBLE TICK) MARK KAREIN
            mark_message_as_read(message_id)

        if msg_type == "text":
            user_text = message.get("text", {}).get("body", "")
            threading.Thread(
                target=process_and_reply,
                args=(user_text, sender_phone),
                daemon=True
            ).start()

    except Exception as e:
        print(f"[WEBHOOK ERROR]: {e}", flush=True)

    return jsonify({"status": "success"}), 200

# ==========================================
# 7. WORKER START
# ==========================================
def start_background_threads():
    threading.Thread(target=keep_awake_ping, daemon=True).start()
    threading.Thread(target=sync_sheets_in_background, daemon=True).start()
    threading.Thread(target=monitor_guest_status_lifecycle, daemon=True).start()
    print("[SYSTEM]: Background workers ready.", flush=True)

start_background_threads()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
