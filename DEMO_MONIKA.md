# Monika: housekeeping and chat demo

## Included

- Monika is the hotel's virtual receptionist. Her name/hello responses use no model call, and the AI contract asks for short, contextual replies, feminine Hindi/Hinglish self-reference and no repeated introductions. She does not pretend to be a human or invent completed actions.
- An assigned, on-duty housekeeping employee (or on-duty reception) can send `101 clean` or `Room 101 clean` on WhatsApp. The current Staff_Roster must be readable. Unknown/duplicate room numbers and unauthorized senders cannot update Rooms.
- The first worksheet remains the existing Rooms sheet. Four named columns are appended without changing existing columns: `Cleaning Status`, `Cleaned By`, `Cleaned At`, `Cleaning Message ID`. Cleaning updates never change occupancy, billing or booking status. The message ID prevents immediate duplicate replays; timestamps include the hotel's IST offset. This records staff-reported cleanliness, not guest acceptance of an unrelated service task.
- `/admin` is a read-only chat monitor. It refreshes every five seconds, supports a full phone-number filter, pause/resume and older messages. Incoming and outgoing messages show their processing/delivery status, including failed or uncertain sends.
- Download for Excel exports UTF-8 CSV with all currently stored messages (or the selected phone). Formula-like message text is neutralized. Media appear as type placeholders; ID documents, audio files and private media URLs are not exported. Times in CSV are UTC; the browser renders local time. New outgoing messages retain their creation time across delivery/read updates. Older records without a creation timestamp are explicitly labelled as legacy activity times.

## Deployment

1. Deploy the complete repository, including `hotel_admin.py` and `templates/chat_monitor.html`. Start with `python serve.py` as before.
2. Set `HOTEL_ADMIN_PASSWORD` to a long, unique password in the hosting environment. Optional `HOTEL_ADMIN_USER` defaults to `admin`. Missing password disables the monitor. Open the deployed HTTPS URL followed by `/admin`; the browser asks for credentials. Share them only with authorized hotel staff.
3. Keep the existing WhatsApp and Google service-account settings. Populate Staff_Roster with WhatsApp number, role, duty status, applicable date/shift and assigned rooms. Housekeeping uses the existing assignment priority; reception can update all rooms while on duty.
4. Use a test room and authorized staff phone: send `101 clean`, verify the four Sheet columns, then check the monitor and download CSV. Confirm a guest number cannot change cleaning status. A failed/timed-out Sheet write asks for manual verification rather than falsely claiming success.
5. Exchange a real guest message and reply, then inspect delivery status. Offline checks cannot prove live Meta delivery, Sheet permissions, AI provider availability or account configuration.

## Demo readiness limits

The repository's existing `customer_config.json` selects the Hotel Shreya Galaxy demo profile. This change preserves it. In demo mode, guest stay lookup and operational booking/order paths are restricted, and some legacy menu details are not configured. Configure a hotel's approved menu and choose the appropriate profile before demonstrating actual guest ordering/billing. Do not blindly disable demo mode against real guests.

`BOT_STORAGE_MODE=demo` uses temporary SQLite storage. Chats and pending state can disappear on restart/redeploy. Download before redeploying. Retaining chats requires `BOT_STORAGE_MODE=persistent` and `BOT_DB_PATH` on a mounted durable volume. This change does not provision hosting or change accounts.

The dashboard is observational; it does not provide human reply/takeover controls. Cleaning updates do not automatically complete guest service requests or reset themselves on checkout.

## Offline checks

```text
python -m unittest discover -q
python smoke_test.py
python -m compileall -q .
```

Regression fixtures use the legacy hotel data explicitly instead of depending on the deployed customer profile. Separate tests retain the active demo profile and exercise Monika, monitor authorization, CSV export and cleaning behavior with mocked external services.
