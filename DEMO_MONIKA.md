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

### Food-order demo (V57)

The active demo profile enables `demo_food_enabled: true` and includes a clearly labelled sample menu (Masala Chai Rs.30, Poha Rs.70 and Butter Naan Rs.40). This remains opt-in: both `demo_mode` and `demo_food_enabled` must be enabled. These are illustrative prices, not an assertion about the hotel's actual menu.

Send `menu`, then `2 Masala Chai aur 1 Poha`. Unconfigured menus are reported as unavailable rather than inventing items. A casual `haan` without a pending demo order stays with the normal concierge. Monika shows Rs.130 and asks for confirmation. `CONFIRM` writes one order to the separate `Demo_Orders` tab in the configured Google spreadsheet. `CANCEL` drops an unsaved cart. `bill` reads this WhatsApp sender's confirmed demo food orders and shows item quantities, unit prices and food total only. No room rent, tax, payment request, real kitchen notification or delivery promise is included. Menu/price/bill questions preserve a pending cart. Ordinary hotel questions continue through the existing concierge.

The service account needs permission to create/read/write `Demo_Orders`; the tab and its headers are created on the first confirmed demo order. Existing unrelated headers are rejected. Timeouts are treated as uncertain: the same order ID is checked before another confirmation, and an unresolved write is never blindly appended again. A new order cannot replace an uncertain cart. Confirmed Sheet entries survive hosting restart; pending carts still depend on the configured SQLite storage.

Demo bills include all confirmed demo rows for the current sender in `Demo_Orders`. For a fresh showcase, use a new test sender or deliberately clear only its test rows in that tab after saving any needed demonstration evidence. This flow never writes `Rooms` or `Kitchen_Orders`.

The repository's existing `customer_config.json` selects the Hotel Shreya Galaxy demo profile. Real guest stay lookup and operational booking/order paths remain restricted. The isolated sample food flow above is available for a demo. Configure a hotel's approved menu and choose the appropriate profile before actual guest ordering/billing. Do not blindly disable demo mode against real guests.

`BOT_STORAGE_MODE=demo` uses temporary SQLite storage. Chats and pending state can disappear on restart/redeploy. Download before redeploying. Retaining chats requires `BOT_STORAGE_MODE=persistent` and `BOT_DB_PATH` on a mounted durable volume. This change does not provision hosting or change accounts.

The dashboard is observational; it does not provide human reply/takeover controls. Cleaning updates do not automatically complete guest service requests or reset themselves on checkout.

## Offline checks

```text
python -m unittest discover -q
python smoke_test.py
python -m compileall -q .
```

Regression fixtures use the legacy hotel data explicitly instead of depending on the deployed customer profile. Separate tests retain the active demo profile and exercise Monika, monitor authorization, CSV export and cleaning behavior with mocked external services.
