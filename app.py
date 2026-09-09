import os
import requests
from flask import Flask, request, jsonify
from google import genai

app = Flask(__name__)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "ganga_bot_secret_123")
ACCESS_TOKEN = os.environ.get("WHATSAPP_TOKEN") or os.environ.get("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "1357005434155447")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")

# Hotel ka AI Knowledge Base
HOTEL_CONTEXT = """
Aap Hotel Ganga Palace, Haridwar ke polite aur helpful virtual assistant hain.
Customer se polite, natural aur warm Hinglish/Hindi me baat karein.
Bohot lambe paragraphs mat likhein; WhatsApp ke hisaab se seedha aur clear reply karein.

Hotel Details:
- Location: Haridwar, near Har Ki Pauri (walking distance ~10 mins).
- Aarti Timing: Subah 6:00 AM, Shaam 6:30 PM (Ganga Aarti Har Ki Pauri).
- Room Categories: Deluxe AC Room (Rs. 2000/night), Super Deluxe (Rs. 2800/night).
- Facilities: Free Wi-Fi, 24/7 Hot Water, Elevator, In-house Pure Veg Restaurant.
- Parking: Available (Free private parking).
- Check-in: 12:00 PM | Check-out: 11:00 AM.
- Booking/Advance: Booking ke liye date aur kitne guests hain poochhein, fir reception number 7500058655 par connect karne ko kahein.

Agar koi aisi cheez pooche jo details me nahi hai, toh politely kahein ki wo hotel front desk (7500058655) par call karke confirm kar sakte hain.
"""

ai_client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None

def ask_ai(user_msg):
    if not ai_client:
        return "Namaste! Front desk se connect karne ke liye kripya 7500058655 par sampark karein."
    try:
        response = ai_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=f"{HOTEL_CONTEXT}\n\nUser Message: {user_msg}\nAssistant Reply:"
        )
        return response.text.strip()
    except Exception as e:
        print("Gemini API Error:", e)
        return "Namaste! Kripya humare reception number par call karein: 7500058655."

@app.route('/', methods=['GET'])
def home():
    return "Ganga Palace WhatsApp Bot is Live!", 200

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')
        if mode == 'subscribe' and token == VERIFY_TOKEN:
            return challenge, 200
        return 'Verification failed', 403

    if request.method == 'POST':
        data = request.get_json()
        try:
            for entry in data.get('entry', []):
                for change in entry.get('changes', []):
                    messages = change.get('value', {}).get('messages', [])
                    for msg in messages:
                        sender_id = msg.get('from')
                        user_text = msg.get('text', {}).get('body', '')
                        if user_text:
                            reply_text = ask_ai(user_text)
                            send_whatsapp_message(sender_id, reply_text)
        except Exception as e:
            print(f"Error: {e}")
        return jsonify({"status": "success"}), 200

def send_whatsapp_message(to_number, text):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": text}
    }
    requests.post(url, headers=headers, json=payload)
