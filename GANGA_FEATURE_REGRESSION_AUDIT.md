# Ganga hotel bot → V65: preservation and operational audit (2026-10-09)

**Historical baseline:** [Original Ganga hotel code at commit `1754f9a`](https://github.com/yrskaran/ganga-palace-bot/tree/1754f9ae9f780978261712f480d3fb0d1e3e0e29).  
**Audited current release:** V65, commit `4b7d83705653ca7b8e1db422ef5dba4e700c128a`.  
**Production policy:** This file is a preservation **checklist**, not permission to send messages or change guests' records.

## What the comparison establishes

- All **272 original top-level Python functions** still exist by name in V65 (`app.py` now has 285). This detects removals, **not behavioral regressions**.
- Older hotel knowledge (`hotel_data.txt`) is labelled *Hotel Ganga View*, while the active `customer_config.json` is a **Hotel Shreya Galaxy demo profile**. Do not combine the old hotel's real guest records with the new demo.
- The old proactive reminder functions remain in V65: welcome, 30-minute onboarding, breakfast/good morning, lunch, Ganga Aarti, dinner, checkout and owner reports.
- **BLOCKER:** `CUSTOMER_DEMO_MODE=true` means `fetch_sheet_data_sync()` deliberately returns `False` before reading real `Rooms`, `Kitchen_Orders`, `Lifecycle_Automation` and related hotel state. The V65 demo can show menus and simulated food orders, but **cannot correctly run the old hotel's in-house lifecycle automation**.
- **BLOCKER:** Render V65 startup logs: `LIFECYCLE TEMPLATE CONFIG: generic=False breakfast=False aarti=False`. Proactive messages outside the 24-hour WhatsApp service window need approved templates; code fallback to plain text is not sufficient for such deliveries.
- **BLOCKER:** Render logs repeatedly show `LIFECYCLE MARKER TAB UNAVAILABLE`. The connected Sheet has the `Lifecycle_Automation` tab and a historical checked-in row, but the demo cache doesn't load it; its breakfast, lunch, Aarti and dinner markers are older dates, not current proof of delivery.
- **SAFETY:** Do NOT disable the demo isolation or copy a real guest number into the demo to make these notifications fire. Do not bulk resend missing reminders.

## Feature audit matrix

| Feature | Legacy implementation | V65 source | Actual V65 Shreya demo state |
| --- | --- | --- | --- |
| Room types, rates, photographs | Yes | Present | WhatsApp feature tested; actual booking availability not verified |
| Meal-wise menus (breakfast/lunch/dinner), full menu | Yes | Present | Works interactively; menus use demo sample prices |
| Food cart / order confirmation | Yes | Real and demo paths present | Simulated `Demo_Orders`; not a real kitchen order |
| Verified real kitchen order | Yes | Present, restricted to in-house guests | In-house data sync is blocked in demo |
| Demo check-in before demo order | Not a real hotel check-in | Added in V65 | Simulated-only; no OTP, ID or room allocation |
| Real self check-in and staff verification | Yes | Present | Unavailable in demo because real guest record isn't synced |
| Welcome & 30-minute guest onboarding | Yes | Present | Cannot send on real checked-in lifecycle in demo |
| Good morning + breakfast reminder | Yes | Present | Blocked by guest sync and missing proactive template |
| Lunch reminder | Yes | Present | Blocked by guest sync and missing proactive template |
| Har Ki Pauri Ganga Aarti reminder | Yes | Present | Blocked by guest sync and missing proactive template |
| Dinner reminder | Yes | Present | Blocked by guest sync and missing proactive template |
| Checkout follow-up | Yes | Present | Requires real guest status, not active in demo |
| Housekeeping & staff done/guest confirmation | Yes | Present | No fresh end-to-end staff/guest WhatsApp verification |
| Complaints, escalation and reception contact | Yes | Present | Tests cover several paths; staff real-world delivery unverified |
| Full room/food bill, payments and owner report | Yes | Present | Real billing and payment records not loaded in demo |
| Hotel guide, Aarti timing questions, Ganga facts | Yes | Present | Informational features available; current timings must not be invented |

**Important:** Present in source ≠ working in production. Mocked tests ≠ Meta WhatsApp delivery or correct hotel-specific guest data.

## Required gate for *every* future change

1. Review diff against current `main` **and** `legacy_function_baseline.json`; explain any intentionally removed/replaced function.
2. Run the complete GitHub CI suite, including `test_legacy_contract.py` and `test_guest_flows.py`; no cherry-picking passing tests.
3. Verify at least one successful, no-duplicate flow for menu, check-in eligibility, real and demo orders, Google Sheet write, cancellation, guest bill, checkout, housekeeping staff done, and reception permission.
4. For reminders, separately test breakfast, lunch, Ganga Aarti and dinner **from the scheduler** with checked-in, checked-out, stale-marker, same-day duplicate and new-day conditions.
5. Confirm correct hotel profile, WhatsApp number, approved notification templates, `SHEET_ID`, `Rooms`/lifecycle headers and active stay state. Avoid sending test messages to real third-party guests.
6. Compare Render environment and run final deploy + health + startup + error-log checks. Check actual delivery status (accepted/failed/delivered), not just a `send()` return value.
7. Only then declare production-ready; record the verification results and rollback commit.

## Pending operational actions (not performed in this PR)

- Restore reminders only on a **separate verified live hotel deployment** with hotel-specific Sheets, WhatsApp credentials, approved templates and an in-house guest; or build an isolated opt-in test-guest simulation for demonstration.
- Investigate `LIFECYCLE MARKER TAB UNAVAILABLE` with the correct production hotel profile before enabling any notification loop.
- Validate the self-check-in OTP → ID → reception approval → room allocation path against appropriate real hotel records.
- Complete a guest-to-kitchen-to-payment-to-checkout smoke test on a dedicated test room/number, not against existing guest data.

This audit and test-only PR makes **no changes** to messaging, hotel data, Render settings or existing Sheet rows.
