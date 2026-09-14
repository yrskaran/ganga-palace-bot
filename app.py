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
SHEET_ID = "1E7iI0vSkRlwpiog-GUjN7Gfh35REAhfY_yVG0t63wqY"

RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "https://ganga-palace-bot.onrender.com")

HOTEL_IMAGES = {
    "front": "https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=1200&q=80",
    "deluxe": "https://images.unsplash.com/photo-1618773928121-c32242e63f39?auto=format&fit=crop&w=1200&q=80",
    "standard": "https://images.unsplash.com/photo-1590490360182-c33d57733427?auto=format&fit=crop&w=1200&q=80"
}

chat_histories = {}
processed_msg_ids = set()

shared_store = {
    "rooms": [
        {"Room": "101", "Category": "Deluxe (Budget)", "Price": "1800", "Guest Name": "Karan Gilhotra", "Phone": "7500058655", "Status": "CHECKED_IN", "Check_In_Date": "12-09-2026"},
        {"Room": "203", "Category": "DELUCE (Budget)", "Price": "1800", "Guest Name": "monika batra", "Phone": "919058514478", "Status": "CHECKED_IN", "Check_In_Date": "13-09-2026"}
    ],
    "kitchen_orders": [],
    "last_synced": 0
}

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
            # 1. Rooms Tab
            csv_url_rooms = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=Rooms"
            synced_rooms = False
            try:
                res_r = requests.get(csv_url_rooms, timeout=5)
                if res_r.status_code == 200 and len(res_r.content) > 15:
                    records = list(csv.DictReader(io.StringIO(res_r.content.decode("utf-8"))))
                    if records:
                        shared_store["rooms"] = records
                        synced_rooms = True
            except Exception:
                pass

            if not synced_rooms:
                client = get_gspread_client()
                if client:
                    try:
                        sh = client.open_by_key(SHEET_ID)
                        ws_rooms = sh.worksheet("Rooms")
                        raw_data = ws_rooms.get_all_records()
                        if raw_data:
                            shared_store["rooms"] = raw_data
                    except Exception:
                        pass

            # 2. Kitchen Orders Tab
            csv_url_kitch = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=Kitchen_Orders"
            synced_kitch = False
            try:
                res_k = requests.get(csv_url_kitch, timeout=5)
                if res_k.status_code == 200 and len(res_k.content) > 15:
                    k_records = list(csv.DictReader(io.StringIO(res_k.content.decode("utf-8"))))
                    if k_records:
                        shared_store["kitchen_orders"] = k_records
                        synced_kitch = True
            except Exception:
                pass

            if not synced_kitch:
                client = get_gspread_client()
                if client:
                    try:
                        sh = client.open_by_key(SHEET_ID)
                        ws_k = sh.worksheet("Kitchen_Orders")
                        raw_k = ws_k.get_all_records()
                        if raw_k:
                            shared_store["kitchen_orders"] = raw_k
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
        print(f"[SHEET WRITE OK] Added order for Room {room}", flush=True)
    except Exception as e:
        print(f"[SHEET WRITE ERROR]: {e}", flush=True)

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
        if isinstance(row, dict):
            vals = list(row.values())
        else:
            vals = list(row)

        vals_str = [str(v).strip() for v in vals]
        phone_matched = any(clean_sender == re.sub(r"\D", "", v)[-10:] for v in vals_str if len(re.sub(r"\D", "", v)) >= 10)
        status_matched = any("IN" in v.upper() for v in vals_str)

        if phone_matched and status_matched:
            room = vals_str[0] if len(vals_str) > 0 and vals_str[0] else "101"
            category = vals_str[1] if len(vals_str) > 1 and vals_str[1] else "Deluxe"
            price_digits = re.sub(r"\D", "", vals_str[2]) if len(vals_str) > 2 else "1800"
            price = price_digits if price_digits and int(price_digits) < 50000 else "1800"
            name = vals_str[3] if len(vals_str) > 3 and vals_str[3] else "Guest"
            check_in = vals_str[6] if len(vals_str) > 6 and vals_str[6] else "12-09-2026"

            return {
                "is_inhouse": True,
                "room": room,
                "name": name,
                "category": category,
                "price": price,
                "check_in_date": check_in
            }
    return None

def get_guest_comprehensive_financials(room_number, sender_phone=""):
    clean_sender = re.sub(r"\D", "", str(sender_phone))[-10:] if sender_phone else ""
    total_kitchen = 0
    paid_kitchen = 0
    kitchen_items_pending = []
    kitchen_items_paid = []

    k_records = shared_store.get("kitchen_orders", [])
    for r in k_records:
        r_room = ""
        r_status = ""
        r_details = ""
        r_amt = "0"

        if isinstance(r, dict):
            # Try key-based access first
            for k, v in r.items():
                kc = re.sub(r"[^a-zA-Z]", "", str(k)).lower()
                if "room" in kc:
                    r_room = str(v).strip()
                elif "detail" in kc or "order" in kc:
                    r_details = str(v).strip()
                elif "amount" in kc or "price" in kc:
                    r_amt = str(v).strip()
                elif "status" in kc or "payment" in kc:
                    r_status = str(v).strip().upper()
            
            # Fallback to values order if keys are unhelpful
            if not r_room:
                vals = [str(v).strip() for v in r.values()]
                if len(vals) >= 6:
                    r_room = vals[1]
                    r_details = vals[3]
                    r_amt = vals[4]
                    r_status = vals[5].upper()
        else:
            vals = [str(v).strip() for v in r]
            if len(vals) >= 6:
                r_room = vals[1]
                r_details = vals[3]
                r_amt = vals[4]
                r_status = vals[5].upper()

        if r_room == str(room_number).strip():
            raw_digits = re.sub(r"\D", "", str(r_amt))
            amt = int(raw_digits) if raw_digits else resolve_item_price(r_details)

            total_kitchen += amt
            if "PAID" in r_status:
                paid_kitchen += amt
                kitchen_items_paid.append(f"• {r_details} - ₹{amt} (PAID)")
            else:
                kitchen_items_pending.append(f"• {r_details} - ₹{amt}")

    records_rooms = shared_store.get("rooms", [])
    room_rate_per_night = 1800
    nights = 1
    room_advance_paid = 0
    guest_name = "Guest"

    for r in records_rooms:
        if isinstance(r, dict):
            vals = [str(v).strip() for v in r.values()]
        else:
            vals = [str(v).strip() for v in r]

        if len(vals) >= 5:
            r_room = vals[0]
            r_phone = re.sub(r"\D", "", vals[4])[-10:] if len(vals) > 4 else ""

            if r_room == str(room_number).strip() or (clean_sender and r_phone == clean_sender):
                p_digits = re.sub(r"\D", "", vals[2]) if len(vals) > 2 else "1800"
                if p_digits and int(p_digits) < 50000:
                    room_rate_per_night = int(p_digits)
                guest_name = vals[3] if len(vals) > 3 and vals[3] else "Guest"
                if len(vals) > 6:
                    nights = calculate_stay_nights(vals[6])
                break

    total_room_rent = room_rate_per_night * nights
    pending_kitchen = max(0, total_kitchen - paid_kitchen)
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
        "kitchen_paid_items": kitchen_items_paid,
        "grand_total": grand_total,
        "total_paid": total_paid,
        "balance_due": balance_due
    }

# ==========================================
# 3. DISPATCH ENGINE (TEXT & ASYNC IMAGES)
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
    def _mark():
        pid = (PHONE_NUMBER_ID or "").strip()
        if not pid or not WHATSAPP_TOKEN:
            return
        url = f"https://graph.facebook.com/v20.0/{pid}/messages"
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
        payload = {"messaging_product": "whatsapp", "status": "read", "message_id": message_id}
        try:
            requests.post(url, json=payload, headers=headers, timeout=5)
        except Exception:
            pass
    threading.Thread(target=_mark, daemon=True).start()

def send_whatsapp_message(to_number, text):
    def _do():
        clean_number = format_whatsapp_number(to_number)
        if not clean_number:
            print(f"[DISPATCH ERROR]: Invalid phone number format: {to_number}", flush=True)
            return

        pid = (PHONE_NUMBER_ID or "").strip()
        if not pid or not WHATSAPP_TOKEN:
            print("[DISPATCH ERROR]: Missing WhatsApp credentials!", flush=True)
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
            print(f"[META DISPATCH] Status: {res.status_code} | Target: {clean_number} | Body: {res.text}", flush=True)
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
            print(f"[META IMAGE] Status: {res.status_code} | Target: {clean_number} | Body: {res.text}", flush=True)
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
        "model": "command-r",
        "message": user_message,
        "preamble": (
            "You are the WhatsApp AI Receptionist for Hotel Ganga View, Haridwar. "
            "Help guests with room types, rates (Standard: ₹1,800, Deluxe: ₹2,500), "
            "location (Near Har Ki Pauri) and answer questions politely in 1-2 lines Hinglish."
        ),
        "temperature": 0.2
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=5)
        if res.status_code == 200:
            reply_text = res.json().get("text", "").strip()
            if reply_text:
                return reply_text
    except Exception as e:
        print(f"[COHERE FAIL]: {e}", flush=True)
    return None

# ==========================================
# 4. MAIN MESSAGE PROCESSING PIPELINE
# ==========================================
def process_and_reply(user_text, sender_phone):
    print(f"[PROCESS START] '{user_text}' from {sender_phone}", flush=True)
    text_lower = user_text.lower().strip()

    guest_info = get_guest_stay_status(sender_phone)
    print(f"[PROCESS] In-house guest: {bool(guest_info)}", flush=True)

    # 1. LOCATION / MAP HANDLER
    loc_words = ["location", "map", "address", "kahan hai", "pauri", "reach", "direction", "rasta", "kahan sthit", "kaha par hai"]
    if any(lw in text_lower for lw in loc_words):
        print(f"[LOCATION DISPATCH] For {sender_phone}", flush=True)
        loc_msg = (
            "📍 *Hotel Ganga View, Haridwar*\n"
            "Har Ki Pauri se sirf 2 minute ki walking distance par sthit hai!\n\n"
            "🗺️ *Google Maps Direction:*\n"
            "https://maps.google.com/?q=29.9530,78.1700\n\n"
            "Koi bhi samasya ho toh aap humein direct call kar sakte hain! 🙏"
        )
        send_whatsapp_message(sender_phone, loc_msg)
        return

    # 2. PHOTO HANDLER WITH GUARANTEED TEXT FALLBACK
    photo_words = ["photo", "photos", "pic", "pics", "image", "tasveer", "dekhna", "dikhao", "dede"]
    if any(pw in text_lower for pw in photo_words):
        print(f"[PHOTO DISPATCH] Executing for {sender_phone}", flush=True)
        send_whatsapp_image(
            sender_phone,
            "https://raw.githubusercontent.com/yrskaran/ganga-palace-bot/main/images/main.jpg",
            caption="🏨 *Hotel Ganga View, Haridwar* (Near Har Ki Pauri)"
        )
        fallback_showcase = (
            "🏨 *Hotel Ganga View, Haridwar* 🌸\n"
            "📍 *Location:* Near Har Ki Pauri (2 mins walking)\n\n"
            "📸 *Direct Photo Link:*\n"
            "https://raw.githubusercontent.com/yrskaran/ganga-palace-bot/main/images/main.jpg\n\n"
            "💰 *Tariff & Rates:*\n"
            "• *Standard Non-AC:* ₹1,800 / night\n"
            "• *Deluxe AC Room:* ₹2,500 / night\n\n"
            "Booking ke liye apni dates batayein! 🙏"
        )
        send_whatsapp_message(sender_phone, fallback_showcase)
        return

    # 3. BILL HANDLER (DEFAULT = KITCHEN BILL, EXPLICIT = ROOM / TOTAL)
    bill_pattern = r"(bill|bil|total|hisaab|hisab|kharcha|baki|due|paid|kitna hua|balance)"
    if guest_info and re.search(bill_pattern, text_lower):
        print(f"[BILL ENGINE RUNNING]: Room {guest_info['room']}", flush=True)
        fin = get_guest_comprehensive_financials(guest_info['room'], sender_phone)

        # Check if user specifically asks for Room Rent or Complete Stay Bill
        asks_room_specifically = any(k in text_lower for k in ["kamre ka", "room ka", "room rent", "stay ka", "rent kitna", "tariff"])
        asks_complete_specifically = any(k in text_lower for k in ["pura bill", "complete bill", "grand total", "pura hisab", "sab milakar", "checkout bill"])

        # Case A: Only Room Rent requested
        if asks_room_specifically and not asks_complete_specifically:
            adv_str = f"✅ *Advance Paid:* ₹{fin['room_advance_paid']}\n" if fin['room_advance_paid'] > 0 else ""
            room_due = max(0, fin['total_room_rent'] - fin['room_advance_paid'])
            bill_reply = (
                f"🏨 *Room {guest_info['room']} - Room Rent Details*\n"
                f"Guest Name: {fin['guest_name']} ji\n\n"
                f"Stay Duration: {fin['nights']} Night{'s' if fin['nights'] > 1 else ''}\n"
                f"Per Night Rate: ₹{fin['room_rate']}\n\n"
                f"💰 *Total Room Tariff:* ₹{fin['total_room_rent']}\n"
                f"{adv_str}"
                f"⚠️ *Room Tariff Due:* ₹{room_due}"
            )
            send_whatsapp_message(sender_phone, bill_reply)
            return

        # Case B: Complete Combined Statement requested
        if asks_complete_specifically:
            bill_reply = (
                f"🧾 *Room {guest_info['room']} - Complete Bill Statement*\n"
                f"Guest Name: {fin['guest_name']} ji ({fin['nights']} Night{'s' if fin['nights'] > 1 else ''})\n\n"
                f"🏨 *Room Rent ({fin['nights']}N @ ₹{fin['room_rate']}):* ₹{fin['total_room_rent']}\n"
                f"🍳 *Kitchen Orders Total:* ₹{fin['total_kitchen']}\n"
                f"-----------------------------------\n"
                f"💵 *Grand Total Bill:* ₹{fin['grand_total']}\n\n"
                f"✅ *Aapne Jamah Kiya (Paid):* ₹{fin['total_paid']}\n"
                f"-----------------------------------\n"
                f"💳 *Abhi Bacha Hua (Balance Due):* ₹{fin['balance_due']}\n"
                f"*(Aap balance amount check-out counter par settle kar sakte hain)*"
            )
            send_whatsapp_message(sender_phone, bill_reply)
            return

        # Case C: DEFAULT = Kitchen / Food Bill (With Paid & Pending Deductions)
        pending_list = "\n".join(fin["kitchen_pending_items"]) if fin["kitchen_pending_items"] else "• Koi pending item nahi hai"
        paid_info = f"✅ *Aapne Jamah Kar Diya (PAID):* ₹{fin['paid_kitchen']}\n" if fin['paid_kitchen'] > 0 else "✅ *Paid Amount:* ₹0\n"

        bill_reply = (
            f"🍳 *Room {guest_info['room']} - Kitchen Orders Bill*\n"
            f"Guest: {fin['guest_name']} ji\n\n"
            f"📋 *Pending Items:*\n{pending_list}\n\n"
            f"-----------------------------------\n"
            f"💰 *Total Kitchen Orders:* ₹{fin['total_kitchen']}\n"
            f"{paid_info}"
            f"-----------------------------------\n"
            f"⚠️ *Bacha Hua (Kitchen Balance Due):* ₹{fin['pending_kitchen']}\n\n"
            f"*(Chai/Khane ka payment aap staff ko cash/UPI de sakte hain ya check-out par settle kar sakte hain)*"
        )
        send_whatsapp_message(sender_phone, bill_reply)
        return

    # 4. GREETINGS
    greetings = ["hi", "hello", "namaste", "hey", "start", "hlo", "helo"]
    if text_lower in greetings or len(text_lower) <= 2:
        if guest_info:
            reply_msg = (
                f"Namaste {guest_info['name']} ji! 🙏\n\n"
                f"Aapka swagat hai Room {guest_info['room']} ({guest_info['category']}) me.\n"
                f"📶 *Wi-Fi Password:* Ganga@2026\n\n"
                f"Batayein, mai aapke liye khana mangwaun ya housekeeping ki zaroorat hai?"
            )
        else:
            reply_msg = (
                "Namaste! 🙏 Welcome to *Hotel Ganga View, Haridwar* (Near Har Ki Pauri).\n\n"
                "Aap yahan se room rates dekh sakte hain ya photos mangwa sakte hain. "
                "Batayein mai aapki kya sahayata kar sakta hoon?"
            )
        send_whatsapp_message(sender_phone, reply_msg)
        return

    # 5. COMPLAINT INTERCEPTOR
    complaint_words = ["thandi", "kharab", "thanda", "bekar", "nahi chal", "not working", "badbu", "late", "problem", "shikayat"]
    is_complaint = any(cw in text_lower for cw in complaint_words)

    # 6. IN-HOUSE FOOD ORDER INTERCEPTOR
    is_food_msg = any(w in text_lower for w in ["chai", "tea", "roti", "khana", "paratha", "poha", "bhature", "order", "coffee", "dahi"])
    if guest_info and is_food_msg and not is_complaint:
        total_price = resolve_item_price(user_text)
        threading.Thread(
            target=append_kitchen_order_to_sheet,
            args=(guest_info['room'], guest_info['name'], user_text, total_price),
            daemon=True
        ).start()

        kitchen_msg = (
            f"🍳 *NEW ROOM SERVICE ORDER*\n\n"
            f"📌 *Location:* Room {guest_info['room']} ({guest_info['name']})\n"
            f"📋 *Order:* {user_text}\n"
            f"💰 *Bill Amount:* ₹{total_price}\n"
            f"📞 *Contact:* +{sender_phone}\n\n"
            f"⚡ Order deliver karein!"
        )
        send_whatsapp_message(KITCHEN_PHONE, kitchen_msg)

        guest_ack = (
            f"Ji {guest_info['name']} ji! Aapka order note ho gaya hai:\n\n"
            f"🍽️ *Item:* {user_text}\n"
            f"💰 *Bill:* ₹{total_price}\n"
            f"📍 *Room:* {guest_info['room']}\n\n"
            f"Agli 15-20 minutes me aapke room me deliver kar diya jayega. Dhanyawad! 🙏"
        )
        send_whatsapp_message(sender_phone, guest_ack)
        return

    # 7. COHERE INTENT RESOLVER
    prompt_input = (
        f"[IN-HOUSE GUEST: Room {guest_info['room']}]\n{user_text}" 
        if guest_info 
        else f"[PROSPECTIVE CUSTOMER INQUIRY]\n{user_text}"
    )
    bot_reply = ask_cohere(prompt_input, sender_phone)

    if not bot_reply:
        if not guest_info:
            bot_reply = "Hamare paas Standard (₹1,800) aur Deluxe AC Rooms (₹2,500) uplabdh hain. Photos dekhne ke liye 'Room photo' likhein ya booking details batayein!"
        elif is_complaint:
            bot_reply = f"[STAFF_ALERT: {user_text}] Ji, aapki samasya note kar li gayi hai. Staff turant attend karega."
        else:
            bot_reply = "Ji batayein, mai aapke stay ya room service me kya sahayata kar sakta hoon?"

    if "[STAFF_ALERT:" in bot_reply or is_complaint:
        service_details = user_text
        bot_reply = re.sub(r"\[STAFF_ALERT:\s*.*?\]", "", bot_reply).strip()
        room_tag = f"Room {guest_info['room']} ({guest_info['name']})" if guest_info else "Customer Query"
        staff_msg = (
            f"🛎️ *STAFF ALERT*\n\n"
            f"📌 *Location:* {room_tag}\n"
            f"📋 *Details:* {service_details}\n"
            f"📞 *Contact:* +{sender_phone}\n\n"
            f"⚡ Turant attend karein!"
        )
        send_whatsapp_message(STAFF_PHONE, staff_msg)

    bot_reply = re.sub(r"\[.*?\]", "", bot_reply).strip()
    if bot_reply:
        print(f"[DISPATCHING REPLY TO {sender_phone}]: {bot_reply}", flush=True)
        send_whatsapp_message(sender_phone, bot_reply)

def handle_incoming_async(message, sender_phone, msg_type):
    try:
        if msg_type == "text":
            user_text = message.get("text", {}).get("body", "")
            process_and_reply(user_text, sender_phone)
    except Exception as e:
        print(f"[ASYNC WORKER ERROR]: {e}", flush=True)

# ==========================================
# 5. LIFECYCLE & PAYMENT MONITOR
# ==========================================
def monitor_guest_status_lifecycle():
    while True:
        try:
            records = shared_store.get("rooms", [])
            room_phone_map = {}

            for row in records:
                if isinstance(row, dict):
                    values = [str(v).strip() for v in row.values()]
                else:
                    values = [str(v).strip() for v in row]

                if len(values) >= 6:
                    room = values[0]
                    name = values[3]
                    phone = re.sub(r"\D", "", values[4])[-10:]
                    status = values[5].upper()

                    if not phone:
                        continue

                    room_phone_map[room] = phone

                    if "CHECKED_IN" in status and (phone not in welcomed_guests):
                        welcome_msg = (
                            f"Welcome to Hotel Ganga View, {name} ji! 🏨✨\n\n"
                            f"Aapka check-in Room {room} me complete ho gaya hai.\n"
                            f"📶 *Wi-Fi Password:* Ganga@2026\n\n"
                            f"Room service ya kisi bhi sahayata ke liye bas yahan message karein. Namaste! 🙏"
                        )
                        send_whatsapp_message(phone, welcome_msg)
                        welcomed_guests.add(phone)

                    elif ("CHECKED_OUT" in status or "CHECKOUT" in status) and (phone not in checked_out_guests):
                        checkout_farewell = (
                            f"Namaste {name} ji! 🙏\n\n"
                            f"Room {room} ka check-out complete ho gaya hai aur aapka bill account settle kar diya gaya hai.\n\n"
                            f"Hotel Ganga View, Haridwar me rukne ke liye bahut dhanyawad! Shubh Yatra! 🚩🌸"
                        )
                        send_whatsapp_message(phone, checkout_farewell)
                        checked_out_guests.add(phone)

            k_records = shared_store.get("kitchen_orders", [])
            for idx, k_row in enumerate(k_records, start=2):
                r_room = ""
                r_item = "Order"
                r_amt = "0"
                r_status = ""

                if isinstance(k_row, dict):
                    vals = [str(v).strip() for v in k_row.values()]
                else:
                    vals = [str(v).strip() for v in k_row]

                if len(vals) >= 6:
                    r_room = vals[1]
                    r_item = vals[3]
                    r_amt = re.sub(r"\D", "", vals[4]) or "0"
                    r_status = vals[5].upper()

                unique_order_key = f"{r_room}_{idx}_{r_amt}"
                if "PAID" in r_status and (unique_order_key not in notified_paid_orders):
                    guest_ph = room_phone_map.get(r_room)
                    if guest_ph:
                        receipt_msg = (
                            f"✅ *Payment Received Confirmation*\n\n"
                            f"Namaste ji! Room {r_room} ke liye ₹{r_amt} ({r_item}) "
                            f"ki payment successfully receive ho gayi hai.\n"
                            f"Dhanyawad! 🙏"
                        )
                        send_whatsapp_message(guest_ph, receipt_msg)
                        notified_paid_orders.add(unique_order_key)

        except Exception as e:
            print(f"[LIFECYCLE MONITOR ERROR]: {e}", flush=True)

        time.sleep(15)

# ==========================================
# 6. WEBHOOK ROUTES
# ==========================================
@app.route("/", methods=["GET"])
def index():
    return "Hotel Ganga View Enterprise Bot is Live!", 200

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
        print(f"[WEBHOOK ERROR]: {e}", flush=True)

    return jsonify({"status": "success"}), 200

# ==========================================
# 7. WORKER START
# ==========================================
def start_background_threads():
    threading.Thread(target=keep_awake_ping, daemon=True).start()
    threading.Thread(target=sync_sheets_in_background, daemon=True).start()
    threading.Thread(target=monitor_guest_status_lifecycle, daemon=True).start()
    print("[SYSTEM]: Background workers initialized.", flush=True)

start_background_threads()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
