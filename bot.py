import sys
import time
import urllib.request
from google import genai
from google.genai.errors import ServerError

API_KEY = "AQ.Ab8RN6Lfyc6wFfu5gYuOLLxAuRlW76yBZ5ykstfG-qVEjjFtYg"

# --- REMOTE CLOUD SWITCH (Aapka Control) ---
LICENSE_URL = "https://pastebin.com/raw/sKzQgHrG"

def verify_license():
    try:
        # Pastebin link se status padhega
        req = urllib.request.Request(
            LICENSE_URL, 
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        response = urllib.request.urlopen(req, timeout=5)
        status = response.read().decode('utf-8').strip()
        
        if status != "ACTIVE":
            print("\n" + "="*50)
            print(" [!] ACCESS SUSPENDED: Subscription Expired!")
            print(" Kripya agency admin se contact karein.")
            print("="*50 + "\n")
            sys.exit()
        else:
            print("[+] License Status: ACTIVE. Launching Bot...\n")
    except Exception as e:
        print(f"[!] License Check Failed: {e}")
        sys.exit()

# Script chalu hote hi pehle remote check karega
verify_license()

# --- AI HOTEL CONCIERGE ENGINE ---
client = genai.Client(api_key=API_KEY)

system_instruction = (
    "Aap Haridwar ke 'Hotel Ganga Palace' ke manager hain. "
    "Yatris ka namaste ke sath swagat karein. "
    "Short, polite aur Hinglish me baat karein. "
    "Check-in date aur guests count poochkar room availability batayein."
)

chat = client.chats.create(
    model="gemini-3.6-flash",
    config={"system_instruction": system_instruction}
)

customer_message = "Namaste, kal ke liye 2 room chahiye the. Kya rate hai?"
print(f"Customer: {customer_message}\n")

for attempt in range(3):
    try:
        response = chat.send_message(customer_message)
        print(f"Hotel AI Agent: {response.text}")
        break
    except ServerError:
        time.sleep(2)