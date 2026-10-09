# V66: Safe demo reminders (Hotel Shreya Galaxy)

The existing real hotel lifecycle remains unchanged and requires its own verified guest `Rooms` / `Lifecycle_Automation` spreadsheet and approved Meta templates for messages outside the WhatsApp 24-hour service window.

## Testing the live demo using your own WhatsApp number

1. Send **DEMO CHECKIN**. This is only a simulated guest status.
2. Send **DEMO REMINDERS ON**. This is explicit permission to send sample reminders to the same test chat.
3. While the demo check-in and chat session are active, the scheduler attempts up to **one** test reminder per event that day: breakfast (08:00–10:59 IST), lunch (13:00–15:59 IST), Ganga Aarti (17:00–17:59 IST), and dinner (19:00–21:59 IST). Windows use `hotel_data.txt` when set.
4. Send **DEMO REMINDERS OFF** at any point or **DEMO CHECKOUT** to stop.

A demo stay lasts 12 hours. Opt-in does not survive a service restart; send **DEMO REMINDERS ON** again afterwards. Each attempt is marked before sending so a failed/uncertain network response cannot trigger repeat delivery attempts that day. A send attempt is **not** verified delivery: Meta status callbacks and approved templates are still needed for full reliability.

Safety:
- Never read the old Ganga Palace real guests when the Shreya demo profile is active.
- Never send to anyone who has not explicitly opted in on their own WhatsApp conversation.
- No real check-in, room assignment, payment, kitchen orders, or external hotel guest notifications are created.
- Text reminders are attempted only when the user messaged in the past 23 hours. After that, a Meta-approved template is required.
- The server retains original real-hotel lifecycle functions and its complete old-function regression baseline.

**Remaining:** To activate actual hotel guests' proactive reminders, use a dedicated live hotel profile, correct Sheet ID, legitimate guest data, approved WhatsApp templates, and verify delivery callbacks end to end. Do not disable demo isolation or reuse another hotel's sheet.
