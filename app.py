import os
import re
import requests
from flask import Flask, request, jsonify
from groq import Groq

app = Flask(__name__)

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "hotel_secret_token")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

groq_client = Groq(api_key=GROQ_API_KEY)
PROCESSED_MESSAGES = set()

ACTIVE_MODEL = "qwen/qwen3.6-27b"
HOTEL_PHONE = "+91-7500058655"

def load_hotel_data():
    try:
        with open("hotel_data.txt", "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"Error loading hotel_data.txt: {e}")
        return f"Hotel Ganga Palace Haridwar. Rooms: Deluxe AC ₹1,800, Super Deluxe ₹2,600. Contact: {HOTEL_PHONE}"

HOTEL_CONTEXT = load_hotel_data()

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
        requests.post(url, headers=headers, json=payload, timeout=2)
    except Exception as e:
        print(f"Read receipt error: {e}")

def sanitize_qwen_output(raw_text):
    if not raw_text:
        return ""

    raw = raw_text.strip()

    # 1. Think tags nikalna
    if "</think>" in raw:
        raw = raw.split("</think>")[-1].strip()

    # 2. Agar quote ke andar clean answer ho
    quotes = re.findall(r'"([^"\n\r]{10,})"', raw)
    if quotes:
        candidate = quotes[-1].strip()
        if not any(k in candidate.lower() for k in ["agar details", "system", "instruction", "prompt"]):
            return candidate

    # 3. Line by line filter (Prompt echo aur meta phrases hatana)
    lines = [l.strip() for l in raw.split("\n") if l.strip()]
    cleaned_lines = []
    banned_keywords = [
        "agar details", "hotel data", "system prompt", "here's a thinking",
        "final output", "thinking process", "instruction", "rule 1", "rule 2"
    ]

    for line in lines:
        if any(banned in line.lower() for banned in banned_keywords):
            continue
        if re.match(r'^(\d+\.|\*|\-|\#)', line):
            continue
        cleaned_lines.append(line)

    if cleaned_lines:
        final_text = cleaned_lines[-1].strip("`'\" ")
        return final_text

    return f"Ji namaste! Is baare me confirm karne ke liye kripya reception par call kar lijiye: {HOTEL_PHONE}"

def get_ai_reply(user_message):
    system_prompt = f"""
Aap Hotel Ganga Palace Haridwar ke manager 'Aman' hain. Aap WhatsApp par guest se baat kar rahe hain.

Aapko sirf aur sirf guest ko bhejne wala 1 short polite Hinglish sentence likhna hai. Kabhi bhi instructions ya rules ko repeat mat kijiye.

- Agar guest room, rate, timings, ya restaurant dishes (Chinese, Parotta, Shakes, Falooda etc.) puche, toh data dekhkar seedha jawab dein.
- Agar aisi cheez puche jo data me nahi hai (jaise Dal Makhni ya swimming pool), toh politely kahein ki yeh available nahi hai aur call karne ko kahein: {HOTEL_PHONE}.

DATA:
{HOTEL_CONTEXT}
"""
    try:
        completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            model=ACTIVE_MODEL,
            temperature=0.2,
            max_tokens=450
        )
        raw_text = completion.choices[0].message.content
        print(f"--- RAW OUTPUT: '{raw_text}' ---")

        reply = sanitize_qwen_output(raw_text)
        print(f"--- FINAL CLEAN: '{reply}' ---")
        return reply
    except Exception as e:
        print(f"--- GROQ ERROR: {e} ---")
        return f"Namaste ji! Reception par call kar lijiye: {HOTEL_PHONE}"

def send_whatsapp_message(to_number, message_text):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": message_text}
    }
    try:
        requests.post(url, headers=headers, json=payload, timeout=5)
    except Exception as e:
        print(f"Send Error: {e}")

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    try:
        if data.get("entry"):
            for entry in data["entry"]:
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    if "messages" in value:
                        message = value["messages"][0]
                        msg_id = message.get("id")
                        sender_phone = message.get("from")

                        if msg_id in PROCESSED_MESSAGES:
                            return jsonify({"status": "already_processed"}), 200
                        PROCESSED_MESSAGES.add(msg_id)

                        if len(PROCESSED_MESSAGES) > 500:
                            PROCESSED_MESSAGES.clear()

                        if message.get("type") == "text":
                            incoming_text = message["text"]["body"]
                            print(f"--- INCOMING: '{incoming_text}' from {sender_phone} ---")

                            mark_message_as_read(msg_id)
                            reply_text = get_ai_reply(incoming_text)

                            send_whatsapp_message(sender_phone, reply_text)
    except Exception as err:
        print(f"Webhook Error: {err}")

    return jsonify({"status": "success"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
