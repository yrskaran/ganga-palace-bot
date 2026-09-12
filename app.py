def get_guest_stay_status(sender_phone):
    """
    Checks real-time check-in status from Google Sheets CSV export.
    Matches last 10 digits to allow simple 10-digit phone entries.
    """
    csv_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"
    
    # Strip everything except digits and take last 10 digits
    clean_sender = re.sub(r"\D", "", str(sender_phone))[-10:]
    
    try:
        response = requests.get(csv_url, timeout=10)
        if response.status_code != 200:
            print(f"[SHEET ACCESS FAIL]: HTTP {response.status_code}", flush=True)
            return None

        content = response.content.decode("utf-8")
        reader = csv.DictReader(io.StringIO(content))
        
        for row in reader:
            # Strip everything from sheet entry and take last 10 digits
            sheet_phone = re.sub(r"\D", "", str(row.get("Phone", "")))[-10:]
            status = str(row.get("Status", "")).strip().upper()
            
            # Match only the core 10-digit mobile number
            if sheet_phone and sheet_phone == clean_sender and status == "CHECKED_IN":
                return {
                    "is_inhouse": True,
                    "room": str(row.get("Room", "")).strip(),
                    "name": str(row.get("Guest Name", "")).strip()
                }
        return None
    except Exception as e:
        print(f"[SHEET READ EXCEPTION]: {e}", flush=True)
        return None
