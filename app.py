import os
import re
import requests
from flask import Flask, request, jsonify
from groq import Groq

app = Flask(__name__)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "ganga_bot_secret_123")
ACCESS_TOKEN = os.environ.get("WHATSAPP_TOKEN") or os.environ.get("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "1357005434155447")
GROQ_KEY = os.environ.get("GROQ_API_KEY")

processed_msg_ids = set()
chat_histories = {}
ACTIVE_MODEL = None

try:
    with open("hotel_data.txt", "r", encoding="utf-8") as f:
        HOTEL_INFO = f.read()
except Exception:
    HOTEL_INFO = "Hotel Ganga Palace, Haridwar. Contact: 7500058655."

groq_client = Groq(api_key=GROQ_KEY) if GROQ_KEY else None

SYSTEM_INSTRUCTION = f"""
Aap Hotel Ganga Palace (Haridwar) ke front desk manager hain.
Guests se seedhi, polite aur natural Hinglish me baat karein.

RULES:
1. Har reply sirf 1 ya 2 lines ka clean WhatsApp message hona chahiye.
2. Step-by-Step Flow:
   - Pehli baar guest room puche: Date aur kitne log hain wo poochein (e.g. 'Ji bilkul sir! Kis date ke liye plan hai aur kitne log hain?').
   - Specific rate poochein tabhi batao: Deluxe AC Rs 2000, Super Deluxe AC Rs 2800.
   - Advance booking ke liye 7500058655 par sampark karne ko kahein.
3. Stars (*), hash (#), ya bullet points na lagayein.
4. Kabhi bhi internal thinking ya step-by-step reasoning print mat karein, seedha guest ko final message bhejien.

HOTEL DATA:
{HOTEL_INFO}
"""

def get_live_groq_model():
    global ACTIVE_MODEL
    if ACTIVE_MODEL:
        return ACTIVE_MODEL
    
    if not groq_client:
        return None

    try:
        models_data = groq_client.models.list().data
        # Reasoning, deepseek, audio, guard aur vision models exclude karke clean chat model select karega
        for m in models_data:
            m_id = m.id.lower()
            if not any(skip in m_id for skip in ["whisper", "guard", "embed", "r1", "deepseek", "qwq", "vision"]):
                ACTIVE_MODEL = m.id
                print(f"--> LIVE STANDARD CHAT MODEL: {ACTIVE_MODEL}", flush=True)
                return ACTIVE_MODEL
    except Exception as err:
        print(f"Model list error: {err}", flush=True)
    
    # Fallback to first available model if filter is strict
    return "llama-3.3-70b-versatile"

def clean_reply(text):
    # Agar kisi model ne <think> tag bheja toh use poori tarah remove karega
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    cleaned = cleaned.replace("*", "").replace("#", "").strip()
    return cleaned

def ask_ai(sender_id, user_msg):
    if not groq_client:
        return "Namaste! Front desk se connect karne ke liye 7500058655 par sampark karein."

    if sender_id not in chat_histories:
        chat_histories[sender_id] = []

    chat_histories[sender_id].append({"role": "user", "content": user_msg})
    recent_history = chat_histories[sender_id][-10:]

    payload = [{"role": "system", "content": SYSTEM_INSTRUCTION}]
    payload.extend(recent_history)

    current_model = get_live_groq_model()

    try:
        completion = groq_client.chat.completions.create(
            model=current_model,
            messages=payload,
            temperature=0.3,
            max_tokens=120
        )
        raw_reply = completion.choices[0].message.content or ""
        reply = clean_reply(raw_reply)
        chat_histories[sender_id].append({"role": "assistant", "content": reply})
        return reply
    except Exception as e:
        print(f"Groq API Error: {e}", flush=True)
        return "Namaste! Front desk se connect karne ke liye kripya 7500058655 par sampark karein."

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
    resp = requests.post(url, headers=headers, json=payload)
    print(f"Meta Send Status: {resp.status_code} | Meta Response: {resp.text}", flush=True)

@app.route('/', methods=['GET'])
def home():
    model_name = get_live_groq_model()
    return f"Ganga Palace Bot running! Active Model: {model_name}", 200

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
                    value = change.get('value', {})
                    for msg in value.get('messages', []):
                        msg_id = msg.get('id')
                        if msg_id in processed_msg_ids:
                            continue
                        processed_msg_ids.add(msg_id)
                        if len(processed_msg_ids) > 1000:
                            processed_msg_ids.clear()

                        sender_id = msg.get('from')
                        if msg.get('type') == 'text':
                            user_text = msg.get('text', {}).get('body', '').strip()
                            print(f"\n--- INCOMING: '{user_text}' from {sender_id} ---", flush=True)
                            if user_text:
                                reply = ask_ai(sender_id, user_text)
                                print(f"--- BOT REPLY: '{reply}' ---", flush=True)
                                send_whatsapp_message(sender_id, reply)
        except Exception as e:
            print(f"Webhook processing error: {e}", flush=True)
        return jsonify({"status": "success"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
