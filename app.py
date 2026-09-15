import os
import re
import csv
import io
import json
import base64
import time
import random
import threading
import traceback
from datetime import datetime, timezone, timedelta
import requests
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from flask import Flask, request, jsonify

IST = timezone(timedelta(hours=5, minutes=30))

# ==========================================
# 1. INITIALIZE APP & CONFIGURATION
# ==========================================
app = Flask(__name__)

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "").strip()
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "").strip()
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip() 
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")

# 🔥 HARDCODED NUMBERS
KITCHEN_PHONE = "919058929796"
STAFF_PHONE = "917668426524"
SHEET_ID = "1E7iI0vSkRlwpiog-GUjN7Gfh35REAhfY_yVG0t63wqY"

RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "https://ganga-palace-bot.onrender.com")

shared_store = {
    "rooms": [],
    "kitchen_orders": [],
    "last_synced": 0
}

chat_histories = {}
processed_msg_ids = set()

# STATE MEMORY
checkin_sessions = {}
order_sessions = {}  
active_orders = {}   

# LIFECYCLE MEMORY
notified_paid_orders = set()
welcomed_guests = set()
checked_out_guests = set()
guest_first_seen = {}
notified_30min = set()
breakfast_prompted = set()
lunch_prompted = set()
aarti_prompted = set()
dinner_prompted = set()

# SMART AUTO-CORRECT MENU MAPPING
MENU_MAPPING = {
    "chai": ("Chai", 30), "tea": ("Chai", 30), "coffee": ("Coffee", 50),
    "aloo paratha": ("Aloo Paratha", 90), "paratha": ("Aloo Paratha", 90),
    "poha": ("Poha", 70), "chole bhature": ("Chole Bhature", 120), "bhature": ("Chole Bhature", 120),
    "dahi": ("Dahi", 70), "green salad": ("Green Salad", 50), "salad": ("Green Salad", 50),
    "butter roti": ("Butter Roti", 20), "tawa roti": ("Tawa Roti", 15), "roti": ("Tawa Roti", 15),
    "chapati": ("Tawa Roti", 15), "bread": ("Tawa Roti", 15),
    "dal tadka": ("Dal Fry", 160), "dal fry": ("Dal Fry", 160),
    "dal makhani": ("Dal Makhani", 190), "dal makhni": ("Dal Makhani", 190),
    "dal": ("Dal Fry", 160), 
    "kadai paneer": ("Kadhai Paneer", 240), "shahi paneer": ("Shahi Paneer", 240),
    "paneer": ("Kadhai Paneer", 220),
    "jeera rice": ("Jeera Rice", 120), "plain rice": ("Plain Rice", 100), "rice": ("Plain Rice", 100),
    "mineral water": ("Mineral Water", 20), "water": ("Mineral Water", 20), "pani": ("Mineral Water", 20),
    "jalebi": ("Jalebi", 30), "thali": ("Special Thali", 250)
}

def normalize_transcription(text):
    if not text: return ""
    text = text.lower()
    mapping = {
        "रोटी": "roti", "दाल": "dal", "चाय": "chai", "पानी": "water",
        "चावल": "rice", "पनीर": "paneer", "पराठा": "paratha", "दही": "dahi",
        "पोहा": "poha", "भटूरे": "bhature", "सलाद": "salad", "कॉफ़ी": "coffee", "कॉफी": "coffee",
        "थाली": "thali", "जलेबी": "jalebi", "खाना": "khana",
        "तौलिया": "towel", "साबुन": "sabun", "कंबल": "kambal", "सफाई": "safai",
        "कचरा": "kachra", "चूहा": "mouse", "मदद": "help", "बिल": "bill", "चेकआउट": "checkout",
        "तवा": "tawa", "तवा रोटी": "tawa roti", "बटर रोटी": "butter roti",
        "एक": "1", "दो": "2", "तीन": "3", "चार": "4", "पांच": "5", "पाँच": "5",
        "छह": "6", "सात": "7", "आठ": "8", "नौ": "9", "दस": "10",
        "१": "1", "२": "2", "३": "3", "४": "4", "५": "5", "६": "6", "७": "7", "८": "8", "९": "9", "०": "0"
    }
    for k, v in mapping.items():
        text = text.replace(k, v)
    return text

def resolve_item_price_and_name(order_text):
    text = str(order_text).lower()
    text = re.sub(r'\bek\b|\bone\b', '1', text)
    text = re.sub(r'\bdo\b|\btwo\b', '2', text)
    text = re.sub(r'\bteen\b|\bthree\b', '3', text)
    text = re.sub(r'\bchar\b|\bchaar\b|\bfour\b', '4', text)
    text = re.sub(r'\bpaanch\b|\bpanch\b|\bfive\b', '5', text)
    text = re.sub(r'[,.\n&]', ' ', text)
    
    total = 0
    ordered_items = []
    found_any = False
    
    sorted_keys = sorted(MENU_MAPPING.keys(), key=len, reverse=True)
    for key in sorted_keys:
        if key in text:
            qty = 1
            pattern_before = r'(\d+)\s*(?:plate|cup|bowl|portion|glass|piece|aur|and)?\s*' + re.escape(key)
            matches_before = re.findall(pattern_before, text)
            if matches_before:
                qty = sum(int(m) for m in matches_before)
            else:
                pattern_after = re.escape(key) + r'\s*(?:plate|cup|bowl|portion|glass|piece|aur|and|kar|do|dedo|de)?\s*(\d+)'
                matches_after = re.findall(pattern_after, text)
                if matches_after:
                    qty = sum(int(m) for m in matches_after)
            
            std_name, price = MENU_MAPPING[key]
            total += (price * qty)
            ordered_items.append(f"{qty} x {std_name}")
            found_any = True
            text = text.replace(key, "")
            
    if not found_any: return 30, order_text.strip()
    return total, ", ".join(ordered_items)

def format_whatsapp_number(raw_phone):
    digits = re.sub(r"\D", "", str(raw_phone))
    if len(digits) == 10: return f"91{digits}"
    elif len(digits) == 12 and digits.startswith("91"): return digits
    elif len(digits) > 10: return f"91{digits[-10:]}"
    return None

# ==========================================
# 2. GOOGLE DRIVE & GSPREAD ENGINE
# ==========================================
def get_credentials():
    if not GOOGLE_SERVICE_ACCOUNT_JSON: return None
    try:
        creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        return Credentials.from_service_account_info(creds_dict, scopes=scopes)
    except Exception: return None

def get_gspread_client():
    creds = get_credentials()
    return gspread.authorize(creds) if creds else None

def upload_image_to_google_drive(image_bytes, file_name):
    try:
        creds = get_credentials()
        if not creds: return "No_Credentials"
        service = build('drive', 'v3', credentials=creds)
        query = "mimeType = 'application/vnd.google-apps.folder' and name = 'Guest_IDs' and trashed = false"
        results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        folders = results.get('files', [])
        folder_id = folders[0]['id'] if folders else service.files().create(body={'name': 'Guest_IDs', 'mimeType': 'application/vnd.google-apps.folder'}, fields='id').execute().get('id')
        file_metadata = {'name': file_name, 'parents': [folder_id]}
        media = MediaIoBaseUpload(io.BytesIO(image_bytes), mimetype='image/jpeg', resumable=True)
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        service.permissions().create(fileId=file.get('id'), body={'role': 'reader', 'type': 'anyone'}).execute()
        return file.get('webViewLink', 'Uploaded')
    except Exception as e: 
        print(f"❌ [DRIVE UPLOAD ERROR]: {e}", flush=True)
        return "Upload_Failed"

def download_whatsapp_media(media_id):
    try:
        token = (WHATSAPP_TOKEN or "").strip()
        meta_res = requests.get(f"https://graph.facebook.com/v20.0/{media_id}", headers={"Authorization": f"Bearer {token}"}, timeout=10)
        if meta_res.status_code == 200 and meta_res.json().get("url"):
            img_res = requests.get(meta_res.json().get("url"), headers={"Authorization": f"Bearer {token}"}, timeout=15)
            if img_res.status_code == 200: return img_res.content
    except Exception as e: 
        print(f"❌ [MEDIA DOWNLOAD ERROR]: {e}", flush=True)
    return None

def fetch_sheet_data_sync():
    client = get_gspread_client()
    now_ist = datetime.now(IST)
    today_str = now_ist.strftime("%Y-%m-%d")

    if client:
        try:
            sh = client.open_by_key(SHEET_ID)
            r_data = sh.get_worksheet(0).get_all_values()
            if len(r_data) > 1: 
                shared_store["rooms"] = r_data[1:]
                for row in shared_store["rooms"]:
                    if len(row) >= 6:
                        r_num = re.sub(r"\D", "", str(row[0]))
                        r_phone = re.sub(r"\D", "", str(row[4]))[-10:] if len(row)>4 else ""
                        r_status = str(row[5]).upper()
                        if r_phone:
                            if "IN" in r_status and "OUT" not in r_status:
                                welcomed_guests.add(f"{r_phone}_{r_num}")
                                notified_30min.add(f"{r_phone}_{r_num}")
                                if now_ist.hour >= 10: breakfast_prompted.add(f"{r_phone}_{r_num}_{today_str}")
                                if now_ist.hour >= 15: lunch_prompted.add(f"{r_phone}_{r_num}_{today_str}")
                                if now_ist.hour >= 18: aarti_prompted.add(f"{r_phone}_{r_num}_{today_str}")
                                if now_ist.hour >= 21: dinner_prompted.add(f"{r_phone}_{r_num}_{today_str}")
                            elif "OUT" in r_status:
                                checked_out_guests.add(f"{r_phone}_{r_num}_out")

            k_data = sh.worksheet("Kitchen_Orders").get_all_values()
            if len(k_data) > 1: 
                shared_store["kitchen_orders"] = k_data[1:]
                for idx, k_row in enumerate(shared_store["kitchen_orders"], start=2):
                    if len(k_row) >= 6:
                        k_room = re.sub(r"\D", "", str(k_row[1]))
                        k_amt = re.sub(r"\D", "", str(k_row[4])) or "0"
                        k_status = str(k_row[5]).upper()
                        if "PAID" in k_status:
                            notified_paid_orders.add(f"{k_room}_{idx}_{k_amt}")
            
            shared_store["last_synced"] = time.time()
        except Exception as e: 
            print(f"❌ [SHEET FETCH ERROR]: {e}", flush=True)

def sync_sheets_in_background():
    while True:
        try:
            client = get_gspread_client()
            if client:
                sh = client.open_by_key(SHEET_ID)
                try: shared_store["rooms"] = sh.get_worksheet(0).get_all_values()[1:]
                except Exception: pass
                try: shared_store["kitchen_orders"] = sh.worksheet("Kitchen_Orders").get_all_values()[1:]
                except Exception: pass
                shared_store["last_synced"] = time.time()
        except Exception: pass
        time.sleep(15)

def append_kitchen_order_to_sheet(room, guest_name, order_details, amount):
    client = get_gspread_client()
    if not client: return
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("Kitchen_Orders")
        sheet.append_row([datetime.now(IST).strftime("%d-%b %I:%M %p"), str(room), str(guest_name), str(order_details), int(amount), "PENDING"])
        print(f"✅ [ORDER APPENDED] Room {room}: {order_details}", flush=True)
    except Exception as e: 
        print(f"❌ [ORDER APPEND ERROR]: {e}", flush=True)

def cancel_kitchen_order_in_sheet(room, order_details):
    client = get_gspread_client()
    if not client: return
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("Kitchen_Orders")
        records = sheet.get_all_values()
        for i in range(len(records)-1, 0, -1):
            row = records[i]
            if len(row) >= 6:
                if str(room) in str(row[1]) and str(order_details) in str(row[3]) and "PENDING" in str(row[5]).upper():
                    sheet.update_cell(i + 1, 6, "CANCELLED")
                    print(f"✅ [ORDER CANCELLED IN SHEET] Room {room}: {order_details}", flush=True)
                    break
    except Exception as e: 
        print(f"❌ [SHEET CANCEL ERROR]: {e}", flush=True)

def calculate_stay_nights(check_in_str):
    if not check_in_str: return 1
    for fmt in ["%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y"]:
        try: return max(1, (datetime.now(IST).date() - datetime.strptime(str(check_in_str).strip(), fmt).date()).days)
        except ValueError: continue
    return 1

def get_guest_stay_status(sender_phone):
    clean_sender = re.sub(r"\D", "", str(sender_phone))[-10:]
    for row in reversed(shared_store.get("rooms", [])):
        if len(row) >= 6:
            phone_col = re.sub(r"\D", "", str(row[4]))[-10:]
            if clean_sender == phone_col:
                status_str = str(row[5]).upper()
                if "OUT" in status_str:
                    return {"is_inhouse": False, "status": "CHECKED_OUT", "name": str(row[3]).strip() if len(row)>3 else "Guest", "room": str(row[0])}
                elif "IN" in status_str:
                    return {"is_inhouse": True, "room": re.sub(r"\D", "", str(row[0])) or "101", "name": str(row[3]).strip() if len(row)>3 else "Guest", "price": re.sub(r"\D", "", str(row[2])) or "1800"}
    return None

def get_guest_comprehensive_financials(room_number, sender_phone=""):
    clean_sender = re.sub(r"\D", "", str(sender_phone))[-10:] if sender_phone else ""
    target_room_digits = re.sub(r"\D", "", str(room_number))
    total_kitchen = paid_kitchen = 0
    kitchen_items_pending, kitchen_items_paid = [], []

    for vals in shared_store.get("kitchen_orders", []):
        if len(vals) < 5 or re.sub(r"\D", "", str(vals[1])) != target_room_digits: continue
        item_name = str(vals[3]).strip() if len(vals) > 3 and str(vals[3]).strip() else "Food Order"
        status_str = str(vals[5]).strip().upper() if len(vals) > 5 else "PENDING"
        amt = int(re.sub(r"\D", "", str(vals[4])) or 0)
        
        total_kitchen += amt
        if "PAID" in status_str:
            paid_kitchen += amt
            kitchen_items_paid.append(f"• {item_name} - ₹{amt} (PAID)")
        else:
            kitchen_items_pending.append(f"• {item_name} - ₹{amt}")

    room_rate_per_night, nights, room_advance_paid, guest_name = 1800, 1, 0, "Guest"
    for vals in shared_store.get("rooms", []):
        if len(vals) >= 5:
            r_phone = re.sub(r"\D", "", str(vals[4]))[-10:] if len(vals) > 4 else ""
            if re.sub(r"\D", "", str(vals[0])) == target_room_digits or (clean_sender and r_phone == clean_sender):
                p_digits = re.sub(r"\D", "", str(vals[2])) if len(vals) > 2 else "1800"
                if p_digits and int(p_digits) < 50000: room_rate_per_night = int(p_digits)
                guest_name = str(vals[3]).strip() if len(vals) > 3 and str(vals[3]).strip() else "Guest"
                if len(vals) > 6: nights = calculate_stay_nights(str(vals[6]))
                break

    return {
        "guest_name": guest_name, "nights": nights, "room_rate": room_rate_per_night,
        "total_room_rent": room_rate_per_night * nights, "room_advance_paid": room_advance_paid,
        "total_kitchen": total_kitchen, "paid_kitchen": paid_kitchen,
        "pending_kitchen": max(0, total_kitchen - paid_kitchen),
        "kitchen_pending_items": kitchen_items_pending, "kitchen_paid_items": kitchen_items_paid,
        "grand_total": total_kitchen + (room_rate_per_night * nights),
        "total_paid": paid_kitchen + room_advance_paid,
        "balance_due": max(0, (total_kitchen + (room_rate_per_night * nights)) - (paid_kitchen + room_advance_paid))
    }

# ==========================================
# 3. DISPATCH & AI ENGINES
# ==========================================
def send_whatsapp_message(to_number, text):
    clean_number = format_whatsapp_number(to_number)
    if not clean_number or not PHONE_NUMBER_ID or not WHATSAPP_TOKEN: 
        return
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": clean_number, "type": "text", "text": {"body": text}}
    try: requests.post(url, json=payload, headers=headers, timeout=10)
    except Exception: pass

def send_whatsapp_image(to_number, image_url, caption=""):
    clean_number = format_whatsapp_number(to_number)
    if not clean_number or not PHONE_NUMBER_ID or not WHATSAPP_TOKEN: return
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": clean_number, "type": "image", "image": {"link": image_url.strip(), "caption": caption}}
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=12)
        if res.status_code not in [200, 201]: 
            send_whatsapp_message(clean_number, f"{caption}\n\n🖼️ Link: {image_url}")
    except Exception: 
        send_whatsapp_message(clean_number, f"{caption}\n\n🖼️ Link: {image_url}")

def mark_message_as_read(message_id):
    if not PHONE_NUMBER_ID or not WHATSAPP_TOKEN: return
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    try: requests.post(url, json={"messaging_product": "whatsapp", "status": "read", "message_id": message_id}, headers=headers, timeout=5)
    except Exception: pass

def transcribe_audio_groq(audio_bytes):
    if not GROQ_API_KEY: return None
    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
    files = {"file": ("voice_note.ogg", audio_bytes, "audio/ogg")}
    data = {
        "model": "whisper-large-v3", 
        "response_format": "json",
        "prompt": "Hindi and Hinglish hotel food order: roti, tawa roti, dal fry, chai, pani, 1, 2, 3, 4, char, ek, do, teen, sabun, towel, bhej do, room service"
    }
    try:
        res = requests.post(url, headers=headers, files=files, data=data, timeout=15)
        if res.status_code == 200: 
            return res.json().get("text", "").strip()
    except Exception: pass
    return None

def get_hotel_data():
    try:
        if os.path.exists("hotel_data.txt"):
            with open("hotel_data.txt", "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception: pass
    return "Standard Non-AC Room is ₹1800/night. Deluxe AC Room is ₹2500/night. We have safe Parking available."

# 🔥 THE UNKILLABLE GROQ CHAT (MULTI-MODEL AUTO FALLBACK) 🔥
def ask_groq_chat(prompt_input):
    if not GROQ_API_KEY: return None
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    
    hotel_context = get_hotel_data()
    
    system_prompt = f"""You are a highly professional, polite human Receptionist working at Hotel Ganga View, Haridwar. 
CRITICAL RULE 1: NEVER mention that you are an AI, bot, or virtual assistant. Act exactly like a real human staff member.
CRITICAL RULE 2: Match the user's language EXACTLY! English for English, Hinglish for Hindi/Hinglish.
CRITICAL RULE 3 (COMMON SENSE): If a Checked-Out guest asks about room quality or issues (e.g., 'koi dikkat to nahi hai'), treat it as a general inquiry for a FUTURE booking. Say our rooms are perfectly clean and well-maintained. DO NOT say "you checked out so we can't take complaints."
HOTEL DATA START:
{hotel_context}
HOTEL DATA END:
If they mention a current problem (mouse, dirty, help), say: '[STAFF_ALERT: complaint] Ji, maine staff ko bhej diya hai.'
Keep replies to 1 or 2 short lines. Be warm and welcoming."""

    # 🔥 Fallback loop: If one model is deprecated, it instantly tries the next one!
    models_to_try = ["llama-3.1-70b-versatile", "mixtral-8x7b-32768", "llama3-8b-8192"]
    
    for model in models_to_try:
        payload = {
            "model": model, 
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt_input}
            ],
            "temperature": 0.3
        }
        
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=10)
            if res.status_code == 200: 
                return res.json()["choices"][0]["message"]["content"].strip()
            else:
                print(f"⚠️ [GROQ API WARNING - {model} FAILED] {res.status_code} - {res.text}. Trying next model...", flush=True)
        except Exception as e: 
            print(f"❌ [GROQ CHAT EXCEPTION - {model}]: {e}", flush=True)
            
    return None

# ==========================================
# 4. MESSAGE ROUTER & LOGIC
# ==========================================
def process_and_reply(message, sender_phone, msg_type):
    user_text = ""
    print(f"\n🚀 [INCOMING MSG] Type: {msg_type} from {sender_phone}", flush=True)
    
    if msg_type == "audio":
        media_id = message.get("audio", {}).get("id")
        audio_bytes = download_whatsapp_media(media_id)
        if audio_bytes and GROQ_API_KEY:
            raw_text = transcribe_audio_groq(audio_bytes)
            user_text = normalize_transcription(raw_text)
        if not user_text:
            send_whatsapp_message(sender_phone, "Kshama karein, aapki aawaz theek se sunai nahi di. Kripya apna message likh kar bhejein. 🙏")
            return

    elif msg_type == "text":
        user_text = message.get("text", {}).get("body", "")

    text_lower = str(user_text).lower().strip()
    
    guest_info = get_guest_stay_status(sender_phone)
    is_inhouse = guest_info and guest_info.get("is_inhouse")
    is_checkout = guest_info and guest_info.get("status") == "CHECKED_OUT"
    guest_name = guest_info["name"] if guest_info else "Guest"

    # --- 5-MINUTE ORDER CANCELLATION CHECK ---
    if "cancel" in text_lower and any(w in text_lower for w in ["order", "khana", "food", "kardo"]):
        if sender_phone in active_orders:
            order_data = active_orders[sender_phone]
            if time.time() - order_data["time"] <= 300:
                threading.Thread(target=cancel_kitchen_order_in_sheet, args=(guest_info['room'], order_data['order']), daemon=True).start()
                send_whatsapp_message(KITCHEN_PHONE, f"🚨 *ORDER CANCELLED*\n📌 Room: {guest_info['room']} ({guest_info['name']})\n📋 Cancelled Item: {order_data['order']}")
                send_whatsapp_message(sender_phone, f"✅ Aapka order ({order_data['order']}) successfully cancel kar diya gaya hai. 🙏")
                del active_orders[sender_phone]
                return
            else:
                send_whatsapp_message(sender_phone, "⚠️ Maaf kijiye, order kiye hue 5 minute se zyada ho chuke hain isliye bot se cancel nahi ho sakta. Kripya reception par call karein.")
                del active_orders[sender_phone]
                return
        else:
            send_whatsapp_message(sender_phone, "Aapka koi recent active order nahi hai jise cancel kiya ja sake.")
            return

    # --- ORDER CONFIRMATION STATE MACHINE ---
    if sender_phone in order_sessions:
        session = order_sessions[sender_phone]
        if session["step"] == "AWAITING_CONFIRMATION":
            if any(w in text_lower for w in ["haan", "yes", "y", "confirm", "ha", "thik", "theek", "ok", "kardo", "bhej"]):
                corrected_order = session["order"]
                total_price = session["total"]
                
                threading.Thread(target=append_kitchen_order_to_sheet, args=(guest_info['room'], guest_info['name'], corrected_order, total_price), daemon=True).start()
                send_whatsapp_message(KITCHEN_PHONE, f"🍳 *NEW ROOM SERVICE ORDER*\n📌 Room: {guest_info['room']} ({guest_info['name']})\n📋 Order: {corrected_order}\n💰 Amount: ₹{total_price}\n📞 Contact: +{sender_phone}")
                
                send_whatsapp_message(sender_phone, f"✅ Aapka order confirm ho gaya hai!\n🍽️ Item: {corrected_order}\n💰 Bill: ₹{total_price}\n\nAgli 15-20 minutes me deliver ho jayega. 🙏\n*(Note: Agar aap galti se order kar baithe hain, toh agle 5 minute tak 'Cancel order' likh kar ise cancel kar sakte hain)*")
                
                active_orders[sender_phone] = {"order": corrected_order, "total": total_price, "time": time.time()}
                del order_sessions[sender_phone]
                return
            
            elif any(w in text_lower for w in ["nahi", "no", "n", "mat", "cancel", "rehne"]):
                send_whatsapp_message(sender_phone, "❌ Theek hai, order cancel kar diya gaya hai. Kuch aur chahiye toh batayein.")
                del order_sessions[sender_phone]
                return
            else:
                send_whatsapp_message(sender_phone, "Kripya 'Haan' (Yes) ya 'Nahi' (No) likh kar bataein ki kya aap order confirm karna chahte hain?")
                return

    # --- SELF CHECK-IN STATE MACHINE WITH ESCAPE LOOP ---
    if sender_phone in checkin_sessions:
        session = checkin_sessions[sender_phone]
        step = session["step"]
        
        exit_words = ["cancel", "nahi", "no", "stop", "exit", "rehne", "chodo", "hi", "hello", "hey"]
        if any(w == text_lower for w in exit_words) or any(w in text_lower for w in ["cancel", "nahi", "no"]):
            del checkin_sessions[sender_phone]
            send_whatsapp_message(sender_phone, "✅ Koi baat nahi. Aap hotel pohoch kar reception par jaake bhi check-in kar sakte hain. 🙏\n\nKisi aur jankari (rooms, parking, location) ke liye mujhe message karein.")
            return

        if step == "AWAITING_OTP":
            if msg_type in ["text", "audio"] and text_lower == session["otp"]:
                session["step"] = "AWAITING_NAME"
                send_whatsapp_message(sender_phone, "✅ *OTP Verified!*\n\nKripya verification ke liye apna *Poora Naam* batayein.")
            else: send_whatsapp_message(sender_phone, "❌ Galat OTP. Kripya reception staff se sahi 4-digit OTP lekar type karein.")
            return
        
        if step == "AWAITING_NAME":
            if msg_type in ["text", "audio"] and len(user_text) > 2:
                session["name"] = user_text.strip()
                session["step"] = "AWAITING_ADDRESS"
                send_whatsapp_message(sender_phone, f"Dhanyawad {session['name']} ji!\n\nKripya ID verification ke liye apna *Poora Address* (Shahar aur Rajya) likhein.")
            else: send_whatsapp_message(sender_phone, "Kripya apna sahi naam text me likhein.")
            return
            
        if step == "AWAITING_ADDRESS":
            if msg_type in ["text", "audio"] and len(user_text) > 3:
                session["address"] = user_text.strip()
                session["step"] = "AWAITING_ID"
                send_whatsapp_message(sender_phone, "Ab kripya room allot hone ke liye apni *ID (Aadhar Card / Voter ID)* ki saaf photo click karke yahan bhejein. 📸")
            else: send_whatsapp_message(sender_phone, "Kripya apna sahi address likhein.")
            return

        if step == "AWAITING_ID":
            if msg_type == "image":
                send_whatsapp_message(sender_phone, "🔄 ID scan ki ja rahi hai aur address match kiya ja raha hai... Kripya pratiksha karein.")
                
                img_bytes = download_whatsapp_media(message.get("image", {}).get("id"))
                drive_link = upload_image_to_google_drive(img_bytes, f"ID_{session['name'].replace(' ', '_')}_{sender_phone}.jpg") if img_bytes else "No_Image"
                
                time.sleep(2)
                
                assigned_room = "105"
                for row in shared_store.get("rooms", []):
                    if len(row) >= 6 and "OUT" in str(row[5]).upper():
                        assigned_room = str(re.sub(r"\D", "", row[0]))
                        break
                        
                client = get_gspread_client()
                if client:
                    try: 
                        client.open_by_key(SHEET_ID).get_worksheet(0).append_row([assigned_room, "Deluxe", "1800", session["name"], sender_phone, "CHECKED_IN", datetime.now(IST).strftime("%d-%m-%Y"), drive_link, session["address"]])
                    except Exception: pass
                
                send_whatsapp_message(sender_phone, f"✅ *ID Verified & Address Matched!*\n\n🎉 *Check-in Successful!*\nAapka room *{assigned_room}* assign ho gaya hai.\nWelcome to Hotel Ganga View! 🏨✨\n\nAb aap directly room service order kar sakte hain. Menu ke liye 'menu' type karein.")
                send_whatsapp_message(STAFF_PHONE, f"✅ *GUEST SELF CHECK-IN COMPLETE*\nName: {session['name']}\nRoom: {assigned_room}\nPhone: +{sender_phone}\n📍 Address: {session['address']}\n📂 ID Link: {drive_link}")
                
                del checkin_sessions[sender_phone]
            else: send_whatsapp_message(sender_phone, "⚠️ Kripya verification ke liye ID proof ki saaf *Photo (Image)* bhejein.")
            return

    if msg_type not in ["text", "audio"] or not user_text: return

    # 1. GREETINGS
    if text_lower in ["hi", "hello", "namaste", "hey", "start", "hlo"] or len(text_lower) <= 2:
        if is_inhouse: 
            send_whatsapp_message(sender_phone, f"Namaste {guest_name} ji! 🙏\nRoom {guest_info['room']} se sampark karne ke liye dhanyawad.\nMain aapki kya sahayata kar sakta hoon?")
        else: 
            send_whatsapp_message(sender_phone, "Namaste! 🙏 Welcome to *Hotel Ganga View, Haridwar*.\nMain aapki kaise sahayata kar sakta hoon? Aap rooms, tariff, parking ya location ke baare me pooch sakte hain.\n\n*(Agar aap hotel me hain aur Self Check-in karna chahte hain, toh 'check in' type karein)*")
        return

    # 2. WI-FI ON DEMAND
    if any(w in text_lower for w in ["wifi", "wi-fi", "password", "internet", "net"]):
        send_whatsapp_message(sender_phone, "📶 *Hotel Wi-Fi Details:*\nNetwork Name: Ganga@2026\nPassword: Ganga@2026")
        return

    # Trigger Self Check-in
    if any(cw in text_lower for cw in ["check in", "checkin", "book room", "room book", "book karna hai"]):
        if is_inhouse:
            send_whatsapp_message(sender_phone, f"Aapka Check-In pehle hi Room {guest_info['room']} me ho chuka hai! 🙏")
            return
        otp = str(random.randint(1000, 9999))
        checkin_sessions[sender_phone] = {"step": "AWAITING_OTP", "otp": otp}
        send_whatsapp_message(STAFF_PHONE, f"🚨 *SELF CHECK-IN ALERT*\n📞 Phone: +{sender_phone}\n🔑 *OTP for Guest: {otp}*\n(Guest ko ye OTP bata dein check-in approve karne ke liye)")
        send_whatsapp_message(sender_phone, "🏨 *Self Check-In Process*\n\nKripya reception staff se milkar apna *4-digit OTP* yahan type karein:")
        return

    # 3. MENU
    if any(mw in text_lower for mw in ["menu", "kya khane", "food items", "list", "bhookh"]):
        menu_text = "🍔 *Hotel Ganga View - Kitchen Menu*\n\n☕ *Beverages & Breakfast*\n• Chai / Coffee - ₹30 / ₹50\n• Aloo Paratha - ₹90\n• Poha / Dahi - ₹70\n• Chole Bhature - ₹120\n\n🍛 *Lunch & Dinner*\n• Dal Fry / Makhani - ₹160 / ₹190\n• Kadhai / Shahi Paneer - ₹240\n• Jeera / Plain Rice - ₹120 / ₹100\n• Tawa / Butter Roti - ₹15 / ₹20\n• Green Salad - ₹50\n\n👉 *Order karne ke liye item aur quantity likhein!*"
        if not is_inhouse: menu_text += "\n\n*(Note: Room service sirf In-House guests ke liye hai. Booking ke liye 'check in' type karein!)*"
        send_whatsapp_message(sender_phone, menu_text)
        return

    # 4. DUAL PHOTOS & LOCAL GUIDE
    if any(gw in text_lower for gw in ["guide", "ghoomne", "aarti", "places", "visit"]):
        send_whatsapp_message(sender_phone, "🗺️ *Haridwar Local Guide*\n\n🙏 *Ganga Aarti Timings:*\n• Subah: 5:30 AM - 6:30 AM\n• Shaam: 6:00 PM - 7:00 PM\n\n🛕 *Places:*\n1. Mansa Devi Temple\n2. Chandi Devi Temple\n3. Kankhal")
        return
    if any(lw in text_lower for lw in ["location", "map", "address"]):
        send_whatsapp_message(sender_phone, "📍 *Hotel Ganga View, Haridwar*\n🗺️ *Map:* https://maps.google.com/?q=29.9530,78.1700")
        return
    if any(pw in text_lower for pw in ["photo", "photos", "pic", "image", "tasveer", "room dikhao", "room ki", "andar ki"]):
        send_whatsapp_image(sender_phone, "https://raw.githubusercontent.com/yrskaran/ganga-palace-bot/main/images/main.jpg", "🏨 *Hotel Ganga View, Haridwar* (Exterior)")
        send_whatsapp_image(sender_phone, "https://raw.githubusercontent.com/yrskaran/ganga-palace-bot/main/images/room1.jpg", "🛏️ *Standard Non-AC Room* - ₹1,800/night")
        send_whatsapp_image(sender_phone, "https://raw.githubusercontent.com/yrskaran/ganga-palace-bot/main/images/deluxe.jpg", "🛏️ *Deluxe AC Room* - ₹2,500/night")
        send_whatsapp_image(sender_phone, "https://raw.githubusercontent.com/yrskaran/ganga-palace-bot/main/images/4bed.jpg", "🛏️ *4-Bed Family Room*")
        return

    # 5. BILL HANDLER
    if re.search(r"(bill|bil|total|hisaab|hisab|kharcha|baki|due|paid|kitna hua|balance|bta)", text_lower):
        if is_inhouse:
            client = get_gspread_client()
            if client:
                try:
                    live_k = client.open_by_key(SHEET_ID).worksheet("Kitchen_Orders").get_all_values()
                    if len(live_k) > 1: shared_store["kitchen_orders"] = live_k[1:]
                except Exception: pass

            fin = get_guest_comprehensive_financials(guest_info['room'], sender_phone)
            payment_footer = f"\n\n💳 *Payment Options:*\n• UPI ID: `gangaview@upi`\n• Ya hotel counter par cash/card de sakte hain."

            if any(k in text_lower for k in ["kamre ka", "room ka", "room rent"]):
                send_whatsapp_message(sender_phone, f"🏨 *Room {guest_info['room']} - Room Rent Details*\nGuest Name: {fin['guest_name']} ji\nStay: {fin['nights']} Night\nPer Night: ₹{fin['room_rate']}\n\n💰 *Total Room Tariff:* ₹{fin['total_room_rent']}\n⚠️ *Room Tariff Due:* ₹{max(0, fin['total_room_rent'] - fin['room_advance_paid'])}{payment_footer}")
                return
            if any(k in text_lower for k in ["pura bill", "complete bill", "grand total", "checkout"]):
                send_whatsapp_message(sender_phone, f"🧾 *Room {guest_info['room']} - Complete Bill Statement*\nGuest Name: {fin['guest_name']} ji ({fin['nights']} Night)\n\n🏨 *Room Rent:* ₹{fin['total_room_rent']}\n🍳 *Kitchen Total:* ₹{fin['total_kitchen']}\n------------------------\n💵 *Grand Total:* ₹{fin['grand_total']}\n✅ *Paid:* ₹{fin['total_paid']}\n------------------------\n💳 *Balance Due:* ₹{fin['balance_due']}{payment_footer}")
                return

            pending_list = "\n".join(fin["kitchen_pending_items"]) if fin["kitchen_pending_items"] else "• Koi pending order nahi hai"
            send_whatsapp_message(sender_phone, f"🍳 *Room {guest_info['room']} - Kitchen Orders Bill*\n\n📋 *Pending Orders:*\n{pending_list}\n\n💰 *Total Kitchen Orders:* ₹{fin['total_kitchen']}\n✅ *Aapne Jamah Kar Diya (PAID):* ₹{fin['paid_kitchen']}\n------------------------\n⚠️ *Bacha Hua (Balance Due):* ₹{fin['pending_kitchen']}{payment_footer}")
            return
        elif is_checkout:
            send_whatsapp_message(sender_phone, f"Namaste {guest_name} ji! 🙏\nAapka check-out ho chuka hai. Purani payment details ke liye kripya reception par call karein.")
            return

    # 6. SMART INQUIRY FILTER
    food_words = ["chai", "tea", "roti", "khana", "paratha", "poha", "bhature", "order", "coffee", "dahi", "dal", "paneer", "rice", "salad", "jalebi", "water", "pani", "thali", "chapati", "bread"]
    inquiry_words = ["available", "?", "price", "rate", "kitne ka", "kya hai"]
    
    is_food = any(w in text_lower for w in food_words)
    is_inquiry = any(iw in text_lower for iw in inquiry_words)
    
    if is_food:
        if is_inquiry:
            pass 
        elif is_inhouse:
            total_price, corrected_order = resolve_item_price_and_name(user_text)
            order_sessions[sender_phone] = {
                "step": "AWAITING_CONFIRMATION",
                "order": corrected_order,
                "total": total_price
            }
            reply_msg = f"Aapka order: *{corrected_order}* (Bill: ₹{total_price}).\nKya main ise confirm karke kitchen me bhej doon? (Haan / Nahi)"
            send_whatsapp_message(sender_phone, reply_msg)
            return
        elif is_checkout:
            send_whatsapp_message(sender_phone, f"Namaste {guest_name} ji! 🙏 Aapka check-out ho chuka hai. Agar aapko dobara booking karni hai toh 'check in' likhein.")
            return
        else:
            send_whatsapp_message(sender_phone, "🙏 Maaf kijiye, Room Service sirf In-House guests ke liye hai. Nayi booking ke liye 'check in' likhein!")
            return

    # 🔥 7. DYNAMIC AI (GROQ LLAMA-3 WITH MULTI-MODEL FALLBACK) 🔥
    if is_inhouse:
        prompt_input = f"[IN-HOUSE GUEST: Room {guest_info['room']} | Name: {guest_info['name']}]\nGuest says: {user_text}"
    elif is_checkout:
        prompt_input = f"[CHECKED-OUT GUEST | Name: {guest_info['name']}]\nGuest says: {user_text}"
    else:
        prompt_input = f"[NEW INQUIRY]\nUser says: {user_text}"
        
    bot_reply = ask_groq_chat(prompt_input)

    if bot_reply: 
        if "[STAFF_ALERT:" in bot_reply:
            bot_reply = re.sub(r"\[STAFF_ALERT:\s*.*?\]", "", bot_reply).strip()
            room_tag = f"Room {guest_info['room']} ({guest_info['name']})" if is_inhouse else "New Customer Query"
            send_whatsapp_message(STAFF_PHONE, f"🛎️ *STAFF ALERT*\n📌 Location: {room_tag}\n📋 Details: {user_text}\n📞 Contact: +{sender_phone}")
            
        if "[KITCHEN_ALERT:" in bot_reply:
            bot_reply = re.sub(r"\[KITCHEN_ALERT:\s*.*?\]", "", bot_reply).strip()
            
        send_whatsapp_message(sender_phone, bot_reply)
    else:
        is_eng_query = not any(hw in text_lower for hw in ["hai", "kya", "kaise", "karo", "do", "nahi", "haan", "ji"])
        if len(text_lower) < 15 and any(w in text_lower for w in ["no", "nahi", "na", "ok", "okay", "thanks", "dhanyawad", "theek", "achha", "kya"]):
            send_whatsapp_message(sender_phone, "Ji theek hai. Agar koi sahayata chahiye ho toh kripya batayein. 🙏" if not is_eng_query else "Alright. Please let us know if you need any assistance. 🙏")
        elif not is_inhouse and not is_checkout:
            send_whatsapp_message(sender_phone, "Hamare paas Standard (₹1,800) aur Deluxe AC Rooms (₹2,500) uplabdh hain. Photos dekhne ke liye 'Room photo' likhein!")
        else:
            send_whatsapp_message(sender_phone, "Kshama karein, abhi yeh suvidha uplabdh nahi hai. Kisi bhi sahayata ke liye kripya reception par sampark karein. 🙏")

def handle_incoming_async(message, sender_phone, msg_type):
    try: 
        process_and_reply(message, sender_phone, msg_type)
    except Exception as e: 
        print(f"❌ [PROCESS ERROR]: {e}", flush=True)

# ==========================================
# 5. FULL PROACTIVE LIFECYCLE MONITOR
# ==========================================
def monitor_guest_status_lifecycle():
    while True:
        try:
            now_ist = datetime.now(IST)
            today_str = now_ist.strftime("%Y-%m-%d")
            hour = now_ist.hour
            
            is_breakfast_time = 8 <= hour <= 10
            is_lunch_time = 13 <= hour <= 15
            is_aarti_time = 17 <= hour < 18
            is_dinner_time = 19 <= hour <= 21

            room_phone_map = {}

            for row in shared_store.get("rooms", []):
                vals = [str(v).strip() for v in row]
                if len(vals) >= 6:
                    room, name, phone, status = re.sub(r"\D", "", vals[0]), vals[3], re.sub(r"\D", "", vals[4])[-10:] if len(vals) > 4 else "", vals[5].upper() if len(vals) > 5 else ""
                    if not phone: continue
                    room_phone_map[room] = phone

                    if "IN" in status and "OUT" not in status:
                        welcome_key = f"{phone}_{room}"
                        if welcome_key not in welcomed_guests:
                            send_whatsapp_message(phone, f"Welcome to Hotel Ganga View, {name} ji! 🏨✨\nRoom {room} me aapka swagat hai.")
                            welcomed_guests.add(welcome_key)
                            guest_first_seen[welcome_key] = time.time()

                        if welcome_key in guest_first_seen and welcome_key not in notified_30min and (time.time() - guest_first_seen[welcome_key]) >= 1800:
                            send_whatsapp_message(phone, f"Namaste {name} ji! 🌸\nAapko check-in kiye hue aadha ghanta ho gaya hai. Ummid hai sab theek hoga.\nAgar towel, sabun, ya TV remote waghera chahiye ho, toh bejhijhak yahan message karein! 🙏")
                            notified_30min.add(welcome_key)

                        bkfst_key = f"{phone}_{room}_{today_str}"
                        if is_breakfast_time and bkfst_key not in breakfast_prompted:
                            send_whatsapp_message(phone, f"Good Morning {name} ji! ☀️\nBreakfast ka samay ho gaya hai. Chai, Coffee ya Aloo Paratha order karne ke liye 'menu' type karein! ☕")
                            breakfast_prompted.add(bkfst_key)
                            
                        lunch_key = f"{phone}_{room}_{today_str}"
                        if is_lunch_time and lunch_key not in lunch_prompted:
                            send_whatsapp_message(phone, f"Good Afternoon {name} ji! 🍛\nLunch ka samay ho gaya hai. Garma-garam khane ke liye 'menu' type karein!")
                            lunch_prompted.add(lunch_key)
                            
                        aarti_key = f"{phone}_{room}_{today_str}"
                        if is_aarti_time and aarti_key not in aarti_prompted:
                            send_whatsapp_message(phone, f"Har Har Gange {name} ji! 🙏\nShaam ki Ganga Aarti ka samay hone wala hai (6:00 PM). Ghat par jane ka plan bana lijiye! 🌺")
                            aarti_prompted.add(aarti_key)

                        dinner_key = f"{phone}_{room}_{today_str}"
                        if is_dinner_time and dinner_key not in dinner_prompted:
                            send_whatsapp_message(phone, f"Good Evening {name} ji! 🌙\nDinner ka samay ho gaya hai. Kya hum Garma-garam Khana room me bhej dein?\nMenu dekhne ke liye 'menu' type karein! 🍽️")
                            dinner_prompted.add(dinner_key)

                    elif "OUT" in status:
                        checkout_key = f"{phone}_{room}_out"
                        if checkout_key not in checked_out_guests:
                            send_whatsapp_message(phone, f"Namaste {name} ji! 🙏\nRoom {room} ka check-out complete ho gaya hai.\nHotel Ganga View me rukne ke liye dhanyawad! Shubh Yatra! 🚩🌸")
                            checked_out_guests.add(checkout_key)

            for idx, k_row in enumerate(shared_store.get("kitchen_orders", []), start=2):
                if len(k_row) >= 6:
                    k_room, k_item, k_amt, k_status = re.sub(r"\D", "", k_row[1]), k_row[3], re.sub(r"\D", "", k_row[4]) or "0", k_row[5].upper()
                    if int(k_amt) <= 0: continue
                    unique_order_key = f"{k_room}_{idx}_{k_amt}"
                    if "PAID" in k_status and unique_order_key not in notified_paid_orders:
                        guest_ph = room_phone_map.get(k_room)
                        if guest_ph:
                            send_whatsapp_message(guest_ph, f"✅ *Payment Received*\nNamaste ji! Room {k_room} ke liye ₹{k_amt} ({k_item}) ki payment receive ho gayi hai. 🙏")
                            notified_paid_orders.add(unique_order_key)
        except Exception: pass
        time.sleep(15)

# ==========================================
# 6. WEBHOOK ROUTES
# ==========================================
@app.route("/", methods=["GET"])
def index(): return "Hotel Ganga View Enterprise Bot is Live!", 200

@app.route("/health", methods=["GET"])
def health_check(): return jsonify({"status": "active"}), 200

@app.route("/webhook", methods=["GET", "POST"], strict_slashes=False)
def handle_webhook():
    if request.method == "GET": 
        return request.args.get("hub.challenge") if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == VERIFY_TOKEN else ("Forbidden", 403)
    
    try:
        data = request.get_json()
        if not data: return jsonify({"status": "ignored"}), 200
        entry = data.get("entry", [])
        if not entry: return jsonify({"status": "ignored"}), 200
        changes = entry[0].get("changes", [])
        if not changes: return jsonify({"status": "ignored"}), 200
        value = changes[0].get("value", {})
        
        if "statuses" in value: return jsonify({"status": "success"}), 200

        messages = value.get("messages", [])
        if not messages: return jsonify({"status": "ignored"}), 200
            
        msg = messages[0]
        msg_id = msg.get("id")
        sender = msg.get("from")
        msg_type = msg.get("type")
        
        if msg_id in processed_msg_ids: return jsonify({"status": "duplicate"}), 200
            
        processed_msg_ids.add(msg_id)
        if len(processed_msg_ids) > 1000: processed_msg_ids.clear()
        
        mark_message_as_read(msg_id)
        threading.Thread(target=handle_incoming_async, args=(msg, sender, msg_type), daemon=True).start()
        
    except Exception as e: 
        print(f"❌ [WEBHOOK PARSE ERROR]: {e}", flush=True)
        
    return jsonify({"status": "success"}), 200

def keep_awake_ping():
    time.sleep(15)
    while True:
        try: requests.get(f"{RENDER_EXTERNAL_URL.rstrip('/')}/health", timeout=5)
        except Exception: pass
        time.sleep(8 * 60)

fetch_sheet_data_sync()
threading.Thread(target=sync_sheets_in_background, daemon=True).start()
threading.Thread(target=monitor_guest_status_lifecycle, daemon=True).start()
threading.Thread(target=keep_awake_ping, daemon=True).start()

if __name__ == "__main__": 
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
