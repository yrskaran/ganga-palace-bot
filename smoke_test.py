import os

os.environ.setdefault("BOT_AUTOSTART", "0")
os.environ.setdefault("BOT_STORAGE_MODE", "demo")

import app


def check(condition, message):
    if not condition:
        raise AssertionError(message)


# Keep this test offline and deterministic.
app.refresh_staff_roster = lambda force=False: False

headers = [
    "Staff Name", "Role", "WhatsApp", "Status", "Duty Date", "Assigned Rooms"
]
rows = [
    ["Priya", "Reception", "919111111111", "ON DUTY", "Daily", "All"],
    ["Ravi", "Housekeeping", "919222222222", "ON DUTY", "Daily", "201,202,203,205"],
    ["Mohan", "Housekeeping", "919333333333", "LEAVE", "Daily", "204,206"],
    ["Amit", "Housekeeping", "919444444444", "ON DUTY", "Daily", "All"],
]
with app.state_lock:
    app.shared_store["staff_headers"] = headers
    app.shared_store["staff_roster"] = rows

check(app._room_in_assignment("203", "201,202,203,205"), "comma-separated room assignment failed")
check(app._room_in_assignment("205", "201/205/209"), "slash-separated room assignment failed")
check(app._room_in_assignment("207", "201-210"), "room range assignment failed")
check(app._room_in_assignment("207", "201 to 210"), "'to' room range assignment failed")
check(not app._room_in_assignment("211", "201-210"), "room range leaked outside assignment")

staff = app.find_on_duty_staff("203", "Housekeeping")
check(staff and staff["name"] == "Ravi", "exact assigned housekeeping staff not selected")

staff = app.find_on_duty_staff("204", "Housekeeping")
check(staff and staff["name"] == "Amit", "leave staff was not skipped / role-wide backup not selected")

staff = app.find_on_duty_staff("205", "Housekeeping")
check(staff and staff["name"] == "Ravi", "multi-room assignment did not win over role-wide backup")

staff = app.find_on_duty_staff("999", "Reception")
check(staff and staff["name"] == "Priya", "on-duty reception role not selected")
check(app.is_on_duty_staff_phone("919111111111", "Reception"), "reception phone authorization failed")

# Changing the Sheet role must immediately revoke reception authorization in the cached roster.
with app.state_lock:
    app.shared_store["staff_roster"][0][1] = "Housekeeping"
check(not app.is_on_duty_staff_phone("919111111111", "Reception"), "role change did not revoke reception authorization")
with app.state_lock:
    app.shared_store["staff_roster"][0][1] = "Reception"

# When AI providers are unavailable, a mild wellbeing message should still sound human.
captured = []
app.send_whatsapp_message = lambda phone, text: captured.append(str(text)) or True
app.remember_conversation = lambda *args, **kwargs: None
app.get_guest_response_language = lambda *args, **kwargs: "hinglish"
handled = app._local_conversation_fallback(
    "919555555555",
    "sir me dard hai",
    {"name": "Guest", "room": "203", "is_inhouse": True},
)
check(handled, "wellbeing fallback did not handle a simple headache message")
check(captured and ("medical help" in captured[-1].lower() or "paani" in captured[-1].lower()),
      "wellbeing fallback reply is not useful/natural")

check(app.is_yes("👍"), "thumbs-up should confirm a pending yes/no action")
check(app.is_yes("👍🏻"), "skin-tone thumbs-up should confirm a pending yes/no action")
check(app.is_no("👎"), "thumbs-down should decline a pending yes/no action")
check(app.is_no("❌"), "cross mark should decline a pending yes/no action")

captured.clear()
handled = app._local_conversation_fallback(
    "919555555555",
    "😍",
    {"name": "Guest", "room": "203", "is_inhouse": True},
)
check(handled, "heart-eyes emoji should be handled conversationally")
check(captured and "khushi" in captured[-1].lower(), "heart-eyes emoji response was not natural")

check(app._respectful_guest_reply("Hello Kitty!", {"name": "Kitty"}) == "Hello Kitty ji!",
      "bare guest name was not made respectful")
check(app._respectful_guest_reply("Thank you, Kitty.", {"name": "Kitty"}) == "Thank you, Kitty ji.",
      "direct-address guest name was not made respectful")
check(app._is_symbolic_only_message("😆"), "emoji-only message was not recognized as symbolic")
check(app._is_symbolic_only_message("???"), "punctuation-only message was not recognized as symbolic")
check(not app._is_symbolic_only_message("help 😆"), "real text was incorrectly treated as symbolic-only")

check(app._service_done_intent("done"), "staff done intent not recognized")
check(app._service_done_intent("S-ABC123 done"), "task-id staff done intent not recognized")
check(app._service_guest_result("haan ho gaya") == "yes", "guest resolved confirmation not recognized")
check(app._service_guest_result("abhi nahi hua") == "no", "guest unresolved confirmation not recognized")
check(app.SERVICE_CONFIRM_TIMEOUT_MINUTES == 20, "service auto-resolve default must be 20 minutes")
check(len(app._service_task_row({"request_id": "S-ABC123"})) == len(app.SERVICE_REQUEST_HEADERS),
      "Service_Requests row/header shape mismatch")

b0, b1 = app._lifecycle_time_window("Breakfast Reminder Window", 0, 0)
a0, a1 = app._lifecycle_time_window("Ganga Aarti Reminder Window", 0, 0)
check((b0, b1) == (8 * 60, 10 * 60), "Good Morning/Breakfast window config not loaded")
check((a0, a1) == (17 * 60, 18 * 60), "Ganga Aarti window config not loaded")

today_iso = app.now_ist().strftime("%Y-%m-%d")
check(app._lifecycle_sent_today([today_iso], 0, today_iso), "today's lifecycle marker not recognized")
check(not app._lifecycle_sent_today(["2020-01-01"], 0, today_iso), "old lifecycle marker incorrectly blocks today's reminder")

print("SMOKE TESTS PASSED")
