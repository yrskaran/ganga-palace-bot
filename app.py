from datetime import datetime
import pytz

# Track karein ki aaj ka alert ja chuka hai ya nahi (taaki duplicate messages na jayein)
alerts_sent_today = {
    "breakfast": None,
    "tourism": None,
    "aarti": None,
    "dinner": None
}

def broadcast_to_inhouse_guests(message_template_fn):
    """Google Sheet ke sirf CHECKED_IN guests ko message bhejta hai"""
    records = fetch_sheet_records()
    for row in records:
        phone = re.sub(r"\D", "", str(row.get("Phone", "")))[-10:]
        status = str(row.get("Status", "")).strip().upper()
        name = str(row.get("Guest Name", "")).strip()
        room = str(row.get("Room", "")).strip()

        if status == "CHECKED_IN" and phone:
            msg = message_template_fn(name, room)
            send_whatsapp_message(phone, msg)
            time.sleep(1) # Meta rate limit protection

def daily_concierge_scheduler():
    """Har 30 second me IST time check karke automated alert trigger karta hai"""
    ist = pytz.timezone("Asia/Kolkata")
    
    while True:
        try:
            now = datetime.now(ist)
            today_str = now.strftime("%Y-%m-%d")
            current_time_str = now.strftime("%H:%M")

            # 1. 08:00 AM - Breakfast Alert
            if current_time_str == "08:00" and alerts_sent_today["breakfast"] != today_str:
                broadcast_to_inhouse_guests(lambda name, room: (
                    f"Shubh Prabhat {name} ji! ☀️\n\n"
                    f"Aapka fresh breakfast buffet dining hall me taiyar hai.\n"
                    f"⏰ *Timings:* 8:30 AM se 10:30 AM\n\n"
                    f"Agar aap room me breakfast chahte hain, toh yahan reply karein. Have a great morning! 🍳"
                ))
                alerts_sent_today["breakfast"] = today_str

            # 2. 10:30 AM - Tourist Guide Alert
            elif current_time_str == "10:30" and alerts_sent_today["tourism"] != today_str:
                broadcast_to_inhouse_guests(lambda name, room: (
                    f"Har Har Gange {name} ji! 🚩\n\n"
                    f"Agar aap aaj Haridwar darshan ka plan bana rahe hain:\n"
                    f"🚠 *Mansa Devi & Chandi Devi:* Ropeway (Udan Khatola) 11:00 AM se 4:00 PM tak best rehta hai.\n"
                    f"🛕 *Daksha Mahadev Temple (Kankhal):* Shanti se darshan ke liye dopahar ka samay best hai.\n\n"
                    f"Taxi booking ya auto guidance ke liye reception se sampark karein ya yahan batayein!"
                ))
                alerts_sent_today["tourism"] = today_str

            # 3. 05:00 PM - Har Ki Pauri Ganga Aarti Alert
            elif current_time_str == "17:00" and alerts_sent_today["aarti"] != today_str:
                broadcast_to_inhouse_guests(lambda name, room: (
                    f"Har Har Gange {name} ji! 🪔✨\n\n"
                    f"Har Ki Pauri par *Sandhya Ganga Aarti* shaam 6:15 PM se shuru hoti hai.\n\n"
                    f"📌 *Helpful Tip:* Achhi jagah aur darshan ke liye kripya 5:30 PM tak ghat par pahunch jayein, kyunki shaam ko kaafi bheed rehti hai.\n\n"
                    f"Aapke hotel se Har Ki Pauri lagbhag 10-15 minute ki doori par hai. Shubh Darshan! 🙏"
                ))
                alerts_sent_today["aarti"] = today_str

            # 4. 08:00 PM - Dinner Reminder Alert
            elif current_time_str == "20:00" and alerts_sent_today["dinner"] != today_str:
                broadcast_to_inhouse_guests(lambda name, room: (
                    f"Namaste {name} ji! 🌙\n\n"
                    f"Hotel Ganga View me dinner serve hona shuru ho gaya hai.\n"
                    f"⏰ *Restaurant Timings:* 8:00 PM se 10:30 PM\n\n"
                    f"Agar aap Room {room} me khana mangwana chahte hain, toh bas yahan apna order likhkar bhej dein!"
                ))
                alerts_sent_today["dinner"] = today_str

        except Exception as e:
            print(f"[CONCIERGE ENGINE ERROR]: {e}", flush=True)

        time.sleep(30)
