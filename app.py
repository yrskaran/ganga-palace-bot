import os
import requests
from flask import Flask, request, jsonify
from groq import Groq

app = Flask(__name__)

# Environment variables
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "hotel_secret_token")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Stable Groq Client
groq_client = Groq(api_key=GROQ_API_KEY)

# 1. AI Response Function (Fixed Model)
def get_ai_reply(user_message):
    try:
        system_prompt = (
            "Aap Hotel Ganga Palace Haridwar ke helpful aur polite Digital Concierge hain. "
            "Guests ke sawalon ka jawab short, professional aur helpful Hinglish me dein. "
            "Deluxe AC room ka price 2000 INR/night hai aur Super Deluxe ka 2800 INR/night. "
            "Khane ya safayi ke sawalon par respectful confirm karein."
        )
        
        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            model="llama-3.1-8b-instant",  # Fixed stable production model
            temperature=0.4,
            max_tokens=250
        )
        return chat_completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"Groq API Error: {e}")
        return "Namaste! Aapka message mil gaya hai. Front desk executive turant aapse sampark karenge."

# 2. Meta WhatsApp Send Function
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
        print(f"Meta Send Status: {response.status_code} | Meta Response: {response.text}")
    except Exception as e:
        print(f"Meta Send Error: {e}")

# 3. Webhook Verification (Meta setup ke liye)
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge, 200
        return "Forbidden", 403
    return "Webhook endpoint active", 200

# 4. Message Receiver Endpoint
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

                        # Handle text messages
                        if message.get("type") == "text":
                            incoming_text = message["text"]["body"]
                            print(f"--- INCOMING: '{incoming_text}' from {sender_phone} ---")

                            # Get Groq response
                            reply_text = get_ai_reply(incoming_text)
                            print(f"--- BOT REPLY: '{reply_text}' ---")

                            # Send via WhatsApp
                            send_whatsapp_message(sender_phone, reply_text)
    except Exception as err:
        print(f"Webhook processing error: {err}")

    return jsonify({"status": "success"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
