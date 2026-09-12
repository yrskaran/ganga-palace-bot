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
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
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
CACHE_TTL_SECONDS = 15

welcomed_guests = set()
alerts_sent_today = {
    "breakfast": None,
    "tourism": None,
    "aarti": None,
    "dinner": None
}

# ==========================================
# 2. GOOGLE SHEET CLIENT & WRITE ENGINES
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
        print(f"[GSPREAD CLIENT ERROR]: {e}", flush=True)
        return None

def fetch_sheet_records():
    """Directly reads the 'Rooms' tab using Google Service Account"""
    now = time.time()
    if sheet_cache["data"] and (now - sheet_cache["last_fetched"] < CACHE_TTL_SECONDS):
        return sheet_cache["data"]

    client = get_gspread_client()
    if client:
        try:
            sheet = client.open_by_key(SHEET_ID).worksheet("Rooms")
            records = sheet.get_all_records()
            sheet_cache["data"] = records
            sheet_cache["last_fetched"] = now
            return records
        except Exception as e:
            print(f"[API ROOMS FETCH ERROR]: {e}", flush=True)

    # Fallback to direct sheet query CSV if API fails
    csv_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=Rooms"
    try:
        response = requests.get(csv_url, timeout=6)
        if response.status_code == 200:
            content = response.content.decode("utf-8")
            reader = list(csv.DictReader(io.StringIO(content)))
            sheet_cache["data"] = reader
            sheet_cache["last_fetched"] = now
            return reader
    except Exception as e:
        print(f"[FALLBACK CSV ERROR]: {e}", flush=True)

    return sheet_cache.get("data", [])

def append_kitchen_order_to_sheet(room, guest_name, order_details, amount):
    """Directly logs food order with Amount into the Kitchen_Orders tab"""
    client = get_gspread_client()
    if not client:
        print("[SHEET WRITE ERROR]: Missing GSpread credentials", flush=True)
        return

    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("Kitchen_Orders")
        now_str = datetime.now(IST).strftime("%d-%b %I:%M %p")
        
        # Columns: Date_Time, Room, Guest Name, Order Details, Amount, Payment_Status
        row_data = [now_str, str(room), str(guest_name), str(order_details), str(amount), "PENDING"]
        sheet.append_row(row_data)
        print(f"[SHEET WRITE SUCCESS]: Kitchen order logged for Room {room} (Amount: Rs. {amount})", flush=True)
    except Exception as e:
        print(f"[SHEET WRITE EXCEPTION]: {e}", flush=True)

def get_guest_kitchen_bill_total(room_number):
    """Calculates all unpaid/pending orders for this room from Kitchen_Orders tab"""
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
                raw_amt = str(r.get("Amount") or r.get("Amount (E)") or "0")
                amt_digits = re.sub(r"\D", "", raw_amt)
                amt = int(amt_digits) if amt_digits else 0
                total_amount += amt
                item_name = r.get("Order Details") or r.get("Order Details (D)") or "Item"
                itemized_list.append(f"• {item_name} - ₹{amt}")
        return total_amount, itemized_list
    except Exception as e:
        print(f"[BILL CALCULATION ERROR]: {e}", flush=True)
        return 0, []

# ==========================================
# 3. PROMPT & HELPER DISPATCH
# ==========================================
def get_system_prompt():
    file_path = os.path.join(os.path.dirname(__file__), "hotel_data.txt")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"[PROMPT ERROR]: {e}", flush=True)
        return "You are the WhatsApp AI Receptionist for Hotel Ganga View in Haridwar. Reply politely in 1-2 lines."

def keep_awake_ping():
    time.sleep(15)
    while True:
        try:
            target_url = f"{RENDER_EXTERNAL_URL.rstrip('/')}/health"
            res = requests.get(target_url, timeout=15)
            print(f"[KEEP-ALIVE PING]: Status {res.status_code}", flush=True)
        except Exception as e:
            print(f"[KEEP-ALIVE FAIL]: {e}", flush=True)
        time.sleep(8 * 60)

def mark_message_as_read(message_id):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
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
        requests.post(url, json=payload, headers=headers, timeout=5)
    except Exception as e:
        print(f"[READ TICK ERROR]: {e}", flush=True)

def send_whatsapp_message(to_number, text):
    clean_number = re.sub(r"\D", "", str(to_number))
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
        res = requests.post(url, json=payload, headers=headers, timeout=12)
        res_json = res.json()
        if res.status_code != 200:
            print(f"[WHATSAPP DISPATCH ERROR] Target: {clean_number} | Body: {res_json}", flush=True)
        return res_json
    except Exception as e:
        print(f"[SEND MSG EXCEPTION]: {e}", flush=True)
        return None

def download_media(media_id):
    try:
        meta_url = f"https://graph.facebook.com/v20.0/{media_id}"
        res = requests.get(meta_url, headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}, timeout=10)
        media_url = res.json().get("url")
        if not media_url:
            return None
        
        file_res = requests.get(
            media_url,
            headers={
                "Authorization": f"Bearer {WHATSAPP_TOKEN}",
                "User-Agent": "curl/7.68.0"
            },
            timeout=20
        )
        if file_res.status_code == 200:
            return file_res.content
        return None
    except Exception as e:
        print(f"[MEDIA DOWNLOAD EXCEPTION]: {e}", flush=True)
        return None

def transcribe_audio_groq(audio_id):
    try:
        audio_content = download_media(audio_id)
        if not audio_content:
            return None

        files = {"file": ("audio.ogg", audio_content, "audio/ogg")}
        data = {"model": "whisper-large-v3", "response_format": "text"}
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
        
        whisper_res = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers=headers,
            files=files,
            data=data,
            timeout=20
        )
        return whisper_res.text.strip()
    except Exception as e:
        print(f"[WHISPER ERROR]: {e}", flush=True)
        return None

def verify_document_groq(image_id):
    try:
        image_content = download_media(image_id)
        if not image_content:
            return None

        base64_image = base64.b64encode(image_content).decode("utf-8")
        prompt = (
            "You are a Hotel Document Verification Assistant. "
            "Determine if this image is a valid Indian Government ID Proof "
            "(Aadhaar Card, PAN Card, Voter ID, Driving License, or Passport). "
            "Never output identification numbers. "
            "If valid Govt ID, reply strictly: VALID | ID_TYPE: <type> | NAME: <guest name or Not Visible> "
            "If invalid, blurry, or not Govt ID, reply strictly: INVALID | REASON: <blurry or not_govt_id>"
        )

        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama-3.2-11b-vision-preview",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }
            ],
            "temperature": 0.1,
            "max_tokens": 100
        }

        res = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        if res.status_code != 200:
            return None

        return res.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[GROQ VISION EXCEPTION]: {e}", flush=True)
        return None

# ==========================================
# 4. GUEST & INVENTORY ENGINE
# ==========================================
def get_guest_stay_status(sender_phone):
    """Matches 10-digit number against cached Rooms records"""
    clean_sender = re.sub(r"\D", "", str(sender_phone))[-10:]
    records = fetch_sheet_records()
    
    for row in records:
        sheet_phone_val = row.get("Phone") or row.get("Phone (E)") or ""
        status_val = row.get("Status") or row.get("Status (F)") or ""
        sheet_phone = re.sub(r"\D", "", str(sheet_phone_val))[-10:]
        status = str(status_val).strip().upper()
        
        if sheet_phone and sheet_phone == clean_sender and status == "CHECKED_IN":
            room_no = row.get("Room") or row.get("Room (A)") or ""
            guest_name = row.get("Guest Name") or row.get("Guest Name (D)") or ""
            cat_name = row.get("Category") or row.get("Category (B)") or "Standard"
            price_val = row.get("Price") or row.get("Price (C)") or ""

            return {
                "is_inhouse": True,
                "room": str(room_no).strip(),
                "name": str(guest_name).strip(),
                "category": str(cat_name).strip(),
                "price": str(price_val).strip()
            }
    return None

def get_room_inventory_summary():
    """Calculates live free rooms and cheap vs premium options"""
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
            available_rooms.append({
                "room": room_no,
                "category": category,
                "price": num_price
            })
            
    if not available_rooms:
        return "All rooms are currently BOOKED. No rooms available right now."
        
    available_rooms.sort(key=lambda x: x["price"])
    cheapest = available_rooms[0]
    premium = available_rooms[-1]
    
    return (
        f"Available Free Rooms Count: {len(available_rooms)}.\n"
        f"Budget/Sasta Option: {cheapest['category']} (Room {cheapest['room']}) at Rs. {cheapest['price']}/night.\n"
        f"Premium Option: {premium['category']} (Room {premium['room']}) at Rs. {premium['price']}/night."
    )

def ask_cohere(user_message, sender_phone):
    history = chat_histories.get(sender_phone, [])
    
    url = "https://api.cohere.ai/v1/chat"
    headers = {
        "Authorization": f"Bearer {COHERE_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "message": user_message,
        "preamble": get_system_prompt(),
        "chat_history": history,
        "temperature": 0.1
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=25)
        if response.status_code != 200:
            return "Namaste! Batayein mai aapki kya madad kar sakta hoon?"

        reply_text = response.json().get("text", "").strip()
        if not reply_text:
            return "Namaste! Batayein mai aapki kya madad kar sakta hoon?"
        
        history.append({"role": "USER", "message": user_message})
        history.append({"role": "CHATBOT", "message": reply_text})
        chat_histories[sender_phone] = history[-6:]
        return reply_text
    except Exception as e:
        print(f"[COHERE EXCEPTION]: {e}", flush=True)
        return "Namaste! Kripya batayein aapko kya chahiye?"

def process_and_reply(user_text, sender_phone):
    guest_info = get_guest_stay_status(sender_phone)
    
    # 1. Block unauthorized outside orders
    service_keywords = ["order", "chai", "tea", "roti", "khana", "towel", "room service", "cleaning", "paani", "water"]
    is_service_query = any(w in user_text.lower() for w in service_keywords)
    
    if not guest_info and is_service_query:
        reject_reply = (
            "Namaste! 🙏 Hamari room service aur housekeeping suvidha sirf hotel me "
            "stay kar rahe registered guests ke liye hai.\n\n"
            "Agar aap hamare hotel me ruke hain, toh kripya reception counter par contact karke apna number register karwayein."
        )
        send_whatsapp_message(sender_phone, reject_reply)
        return

    # 2. Dynamic Kitchen Bill Inquiry Handler
    bill_keywords = ["bill", "hisaab", "hisab", "total kitna", "amount kitna", "kitne paise bane", "checkout bill", "total bill"]
    if guest_info and any(k in user_text.lower() for k in bill_keywords):
        total_due, items = get_guest_kitchen_bill_total(guest_info['room'])
        room_rent = guest_info.get('price', 'N/A')
        
        if items:
            items_str = "\n".join(items)
            bill_reply = (
                f"🧾 *Room {guest_info['room']} - Live Bill Summary*\n"
                f"Guest Name: {guest_info['name']} ji\n\n"
                f"*Kitchen Orders:*\n{items_str}\n\n"
                f"🍳 *Total Kitchen Bill:* ₹{total_due}\n"
                f"🏨 *Room Tariff:* ₹{room_rent}\n"
                f"-----------------------------------\n"
                f"💳 *Status:* Pending (Check-out par settle karein)"
            )
        else:
            bill_reply = (
                f"Namaste {guest_info['name']} ji! 🙏\n\n"
                f"Aapke Room {guest_info['room']} me abhi tak koi pending kitchen order nahi hai.\n"
                f"🏨 *Room Tariff:* ₹{room_rent}."
            )
        send_whatsapp_message(sender_phone, bill_reply)
        return

    # 3. Normal AI Processing with Context
    room_summary = get_room_inventory_summary()
    
    if guest_info:
        prompt_input = (
            f"[IN-HOUSE GUEST: Room {guest_info['room']} | Name: {guest_info['name']} | Category: {guest_info['category']}]\n"
            f"{user_text}"
        )
    else:
        prompt_input = (
            f"[HOTEL LIVE INVENTORY & PRICING CONTEXT]:\n{room_summary}\n"
            f"[CUSTOMER INQUIRY]: {user_text}"
        )

    bot_reply = ask_cohere(prompt_input, sender_phone)
    print(f"[COHERE REPLY for {sender_phone}]: {bot_reply}", flush=True)

    # 4. Handle Kitchen Alert Tag & Auto-Sheet Write with Rates
    if "[KITCHEN_ALERT:" in bot_reply:
        match = re.search(r"\[KITCHEN_ALERT:\s*(.*?)(?:\s*\|\s*RATE:\s*(\d+))?\]", bot_reply)
        order_details = match.group(1).strip() if match and match.group(1) else "Food Order"
        order_rate = match.group(2).strip() if match and match.group(2) else "0"
        
        bot_reply = re.sub(r"\[KITCHEN_ALERT:\s*.*?\]", "", bot_reply).strip()
        
        room_tag = f"Room {guest_info['room']} ({guest_info['name']})" if guest_info else "Unverified Room"
        rate_display = f"₹{order_rate}" if order_rate != "0" else "Standard Rates"
        kitchen_msg = (
            f"🍳 *NEW ROOM SERVICE ORDER*\n\n"
            f"📌 *Location:* {room_tag}\n"
            f"📋 *Order:* {order_details}\n"
            f"💰 *Bill Amount:* {rate_display}\n"
            f"📞 *Contact:* +{sender_phone}\n\n"
            f"⚡ Order deliver karein!"
        )
        send_whatsapp_message(KITCHEN_PHONE, kitchen_msg)
        
        # Async sheet write with Rate into Kitchen_Orders tab
        threading.Thread(
            target=append_kitchen_order_to_sheet,
            args=(
                guest_info['room'] if guest_info else "N/A",
                guest_info['name'] if guest_info else "N/A",
                order_details,
                order_rate
            ),
            daemon=True
        ).start()

        if not bot_reply:
            bot_reply = f"Ji, aapka order note ho gaya hai aur jald {room_tag} me deliver kar diya jayega."

    # 5. Handle Staff Alert Tag
    if "[STAFF_ALERT:" in bot_reply:
        match = re.search(r"\[STAFF_ALERT:\s*(.*?)\]", bot_reply)
        service_details = match.group(1) if match else "Staff Assistance Requested"
        bot_reply = re.sub(r"\[STAFF_ALERT:\s*.*?\]", "", bot_reply).strip()
        
        room_tag = f"Room {guest_info['room']} ({guest_info['name']})" if guest_info else "Unverified Room"
        staff_msg = (
            f"🛎️ *STAFF ALERT*\n\n"
            f"📌 *Location:* {room_tag}\n"
            f"📋 *Details:* {service_details}\n"
            f"📞 *Contact:* +{sender_phone}\n\n"
            f"⚡ Turant attend karein!"
        )
        send_whatsapp_message(STAFF_PHONE, staff_msg)
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

        elif msg_type in ["audio", "voice"]:
            audio_id = message.get("audio", {}).get("id") or message.get("voice", {}).get("id")
            transcribed_text = transcribe_audio_groq(audio_id)
            if transcribed_text:
                process_and_reply(transcribed_text, sender_phone)
            else:
                send_whatsapp_message(sender_phone, "Voice note clear nahi tha, kripya dobara bhejiyega.")

        elif msg_type == "image":
            image_id = message.get("image", {}).get("id")
            verification_result = verify_document_groq(image_id)

            if verification_result and verification_result.startswith("VALID"):
                send_whatsapp_message(
                    sender_phone,
                    "Thank you! 🙏 Aapka ID document verify ho gaya hai. Pre-check-in register update kar diya gaya hai."
                )
                staff_doc_msg = (
                    f"🪪 *NEW GUEST ID VERIFIED*\n\n"
                    f"📋 *Doc Details:* {verification_result}\n"
                    f"📞 *Guest Contact:* +{sender_phone}\n\n"
                    f"✅ Pre-check-in verified."
                )
                send_whatsapp_message(STAFF_PHONE, staff_doc_msg)

            elif verification_result and verification_result.startswith("INVALID"):
                reason = verification_result.split("REASON:")[1].strip().lower() if "REASON:" in verification_result else ""
                if any(k in reason for k in ["blur", "unreadable", "clear", "quality", "dark", "upside"]):
                    reply_msg = "Aapki bheji gayi photo clear nahi hai ya text padha nahi ja raha. Kripya saaf photo dobara bhejein."
                else:
                    reply_msg = "Yeh valid Government ID proof nahi lag raha hai. Kripya Aadhaar, PAN Card, Driving License ya Passport share karein."
                send_whatsapp_message(sender_phone, reply_msg)
            else:
                send_whatsapp_message(sender_phone, "Photo process karne me samasya aayi. Kripya document ki saaf photo dobara send karein.")

        elif msg_type == "location":
            loc_data = message.get("location", {})
            user_lat = loc_data.get("latitude")
            user_lon = loc_data.get("longitude")
            maps_route_url = f"https://www.google.com/maps/dir/?api=1&origin={user_lat},{user_lon}&destination={HOTEL_LAT},{HOTEL_LON}"
            nav_reply = f"📍 *Hotel Navigation Route:*\n{maps_route_url}\n\nIs link par click karke aap direct hotel route dekh sakte hain."
            send_whatsapp_message(sender_phone, nav_reply)

    except Exception as e:
        print(f"[ASYNC WORKER ERROR]: {e}", flush=True)

# ==========================================
# 5. CONCIERGE & CHECK-IN AUTOMATIONS
# ==========================================
def send_checkin_feedback(phone, name, room):
    time.sleep(30 * 60)
    guest = get_guest_stay_status(phone)
    if guest and guest["is_inhouse"]:
        feedback_msg = (
            f"Namaste {name} ji! 🙏\n\n"
            f"Aapko Room {room} kaisa laga? Sab theek aur comfortable hai na?\n\n"
            f"Agar aapko extra towel, paani, chai ya kisi bhi cheez ki zaroorat ho, "
            f"toh aap mujhe yahan WhatsApp par bata sakte hain. Have a wonderful stay! 🌸"
        )
        send_whatsapp_message(phone, feedback_msg)

def monitor_new_checkins():
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

                if status == "CHECKED_IN" and phone and (phone not in welcomed_guests):
                    welcome_msg = (
                        f"Welcome to Hotel Ganga View, {name} ji! 🏨✨\n\n"
                        f"Aapka check-in Room {room} me complete ho gaya hai.\n"
                        f"Wi-Fi Password: *Ganga@2026*\n"
                        f"Room service ya kisi bhi sahayata ke liye bas yahan message karein. Namaste! 🙏"
                    )
                    send_whatsapp_message(phone, welcome_msg)
                    welcomed_guests.add(phone)

                    threading.Thread(
                        target=send_checkin_feedback,
                        args=(phone, name, room),
                        daemon=True
                    ).start()
        except Exception as e:
            print(f"[CHECKIN MONITOR ERROR]: {e}", flush=True)
            
        time.sleep(60)

def broadcast_to_inhouse_guests(message_template_fn):
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

        if status == "CHECKED_IN" and phone:
            msg = message_template_fn(name, room)
            send_whatsapp_message(phone, msg)
            time.sleep(1)

def daily_concierge_scheduler():
    while True:
        try:
            now = datetime.now(IST)
            today_str = now.strftime("%Y-%m-%d")
            current_time_str = now.strftime("%H:%M")

            # 08:00 AM - Breakfast
            if current_time_str == "08:00" and alerts_sent_today["breakfast"] != today_str:
                broadcast_to_inhouse_guests(lambda name, room: (
                    f"Shubh Prabhat {name} ji! ☀️\n\n"
                    f"Aapka fresh breakfast buffet dining hall me taiyar hai.\n"
                    f"⏰ *Timings:* 8:30 AM se 10:30 AM\n\n"
                    f"Agar aap room me mangwana chahte hain, toh yahan reply karein. 🍳"
                ))
                alerts_sent_today["breakfast"] = today_str

            # 10:30 AM - Sightseeing
            elif current_time_str == "10:30" and alerts_today["tourism"] != today_str:
                broadcast_to_inhouse_guests(lambda name, room: (
                    f"Har Har Gange {name} ji! 🚩\n\n"
                    f"Haridwar Darshan Updates:\n"
                    f"🚠 Mansa Devi & Chandi Devi Ropeway timing 11:00 AM se 4:00 PM best hai.\n"
                    f"Taxi booking ya guidance ke liye reception se contact karein!"
                ))
                alerts_sent_today["tourism"] = today_str

            # 05:00 PM - Sandhya Ganga Aarti
            elif current_time_str == "17:00" and alerts_sent_today["aarti"] != today_str:
                broadcast_to_inhouse_guests(lambda name, room: (
                    f"Har Har Gange {name} ji! 🪔✨\n\n"
                    f"Har Ki Pauri par *Sandhya Ganga Aarti* shaam 6:15 PM par shuru hoti hai.\n"
                    f"📌 Achhe darshan ke liye kripya 5:30 PM tak ghat par pahunch jayein. Shubh Darshan! 🙏"
                ))
                alerts_sent_today["aarti"] = today_str

            # 08:00 PM - Dinner
            elif current_time_str == "20:00" and alerts_sent_today["dinner"] != today_str:
                broadcast_to_inhouse_guests(lambda name, room: (
                    f"Namaste {name} ji! 🌙\n\n"
                    f"Hotel Ganga View me dinner start ho gaya hai (8:00 PM - 10:30 PM).\n"
                    f"Room {room} me order mangwane ke liye yahan message karein!"
                ))
                alerts_sent_today["dinner"] = today_str

        except Exception as e:
            print(f"[CONCIERGE SCHEDULER ERROR]: {e}", flush=True)

        time.sleep(30)

# ==========================================
# 6. WEBHOOK & ENDPOINTS
# ==========================================
@app.route("/", methods=["GET"])
def index():
    return "Hotel Ganga View WhatsApp AI Receptionist is running live!", 200

@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "active", "service": "hotel-bot"}), 200

@app.route("/webhook", methods=["GET"], strict_slashes=False)
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

@app.route("/webhook", methods=["POST"], strict_slashes=False)
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
# 7. ENTRY POINT
# ==========================================
if __name__ == "__main__":
    threading.Thread(target=keep_awake_ping, daemon=True).start()
    threading.Thread(target=monitor_new_checkins, daemon=True).start()
    threading.Thread(target=daily_concierge_scheduler, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
