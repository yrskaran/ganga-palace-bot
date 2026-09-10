import os
import requests
from flask import Flask, request, jsonify
from groq import Groq

app = Flask(__name__)

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "hotel_secret_token")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

groq_client = Groq(api_key=GROQ_API_KEY)

# Guaranteed Active Models (Auto-fallback list)
MODELS_TO_TRY = [
    "llama-3.3-70b-versatile",
    "llama3-8b-8192",
    "mixtral-8x7b-32768",
    "gemma2-9b-it"
]

def get_ai_reply(user_message):
    system_prompt = (
        "Aap Hotel Ganga Palace Haridwar ke digital concierge hain. "
        "Short, respectful aur clear Hinglish me reply karein. "
        "Deluxe AC: ₹2000/night, Super Deluxe: ₹2800/night. "
        "Services: 24/7 Room Service, Hot Water, Har Ki Pauri se 500m."
    )
    
    # Try models one by one taaki demo me crash hone ka 0% chance rahe
    for model_name in MODELS_TO_TRY:
        try:
            chat_completion = groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                model=model_name,
                temperature=0.4,
                max_tokens=200
            )
            print(f"--- SUCCESS WITH MODEL: {model_name} ---")
            return chat_completion.choices[0].message.content.strip()
        except Exception as e:
            print(f"Model {model_name} failed: {e}. Trying next...")
            continue
            
    return "Namaste! Hotel Ganga Palace me aapka swagat hai. Front desk manager turant aapse connect karenge."

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
        response = requests.post(url, headers=headers, json=payload)
        print(f"Meta Send Status: {response.status_code}")
    except Exception as e:
        print(f"Meta Send Error: {e}")

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode and token and mode == "subscribe" and token == VERIFY_TOKEN:
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
                        sender_phone = message["from"]

                        if message.get("type") == "text":
                            incoming_text = message["text"]["body"]
                            print(f"--- INCOMING: '{incoming_text}' from {sender_phone} ---")

                            reply_text = get_ai_reply(incoming_text)
                            print(f"--- BOT REPLY: '{reply_text}' ---")

                            send_whatsapp_message(sender_phone, reply_text)
    except Exception as err:
        print(f"Webhook processing error: {err}")

    return jsonify({"status": "success"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
