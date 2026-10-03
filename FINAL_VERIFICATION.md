# Guest concierge V51

## AI outage and assistance questions

The 3 October 11:29–11:30 IST failures came from Groq rejecting roughly 9,400 input tokens against the account's 7,000 ITPM allowance. Gemini returned 503, OpenRouter was rate-limited, Cohere's monthly trial calls were exhausted, and Cerebras/OpenAI reported payment/credit exhaustion. An active HTTP server did not establish a working semantic AI provider.

Hotel knowledge now obeys a UTF-8 budget and ranks complete source paragraphs/lines by the question. Groq uses 3,800 bytes of hotel facts, up to 1,600 bytes of recent role-separated history, and a shorter concierge contract. A 413 opens a short circuit; truncated JSON is rejected. The full hotel knowledge remains unchanged for backend decisions.

Capability questions including “How you assist me” and “Kaise assist kroge” answer before external AI. English, Roman Hinglish and Devanagari replies are verified, and pending food orders are preserved. Actual service/medical requests do not match this route. During a genuine AI outage the message identifies a temporary chat failure rather than blaming the guest's understandable question.

`AI_STARTUP_CHECK=1` enables one asynchronous Groq semantic probe on startup. It does not send WhatsApp messages or create Sheet/staff records. `/health` now includes the last semantic AI check status and timestamp separately from HTTP and Sheet readiness. This status describes the last observed check, not guaranteed future availability.

48 offline regressions, smoke tests, compilation, dependency consistency and the example customer configuration passed.

The 30-minute WhatsApp message now introduces useful hotel assistance in natural language. It waits for the welcome marker and cannot send before 30 minutes have passed since both check-in and welcome. Old arrivals are skipped instead of receiving a backlog of messages after deployment.

A human tour-guide enquiry takes priority over sightseeing, price and AI routes. The bot offers to check availability and charges; an explicit guest request is sent through the existing reception handoff. Guide availability, charges and booking are never invented. A pending food order is preserved while this conversation happens. Local recommendations no longer append the same timing/ticket disclaimer to every answer. The screenshot's “unique ... Haridwar” wording uses the existing fact bank.

Staff completion asks the guest whether the request is complete. Yes records COMPLETED; No records REOPENED and reroutes it. No reply for 20 minutes after a successfully submitted confirmation records AUTO_RESOLVED. A failed confirmation records CONFIRMATION_FAILED and does not auto-close. Multiple pending requests are matched by quoted reply or request ID; otherwise the bot asks which request is being confirmed.

## Records and deployment

- The existing Service_Requests A:Q fields are preserved. R:S are appended automatically as Confirmation Message ID and Confirmation Sent At. Conflicting custom headers are rejected rather than overwritten.
- Confirmation message IDs survive a Sheet-cache rebuild/restart. Staff-done time remains visible even when guest confirmation fails.
- Lifecycle delivery callbacks identify the stay rather than the original row position; a deleted/replaced stay cannot receive another guest's marker.
- Morning, lunch, Aarti and dinner windows retain their existing configured schedules. Checked-out guests receive no in-house reminders.
- Run the service with `python serve.py` or the compatible `python bot.py`. Procfile.txt now uses the same installed Waitress entry point. The obsolete console sample and its embedded API key/license check were removed.
- The old embedded API key was present in public repository history. Revoke/rotate it with the provider if it is still active; deleting it from current code does not invalidate it.

## Verification

On Python 3.12, the pinned requirements installed successfully and `pip check` passed. Python compilation, the existing `smoke_test.py`, the sample customer config validator, and 40 offline regression/integration tests passed. GitHub Actions runs these checks on future pushes and pull requests.

Tests mock WhatsApp and Sheets. They cover human-guide routing and failure, real worker event scheduling, daily markers, moved-row callbacks, staff authorization, guest Yes/No, multiple requests, exact 20-minute boundaries, failed send/delivery, restart recovery, safe header migration, Sheet write shapes, webhook signatures and durable inbox deduplication. They do not send real WhatsApp messages or create dummy guest/payment rows.

Live read-only inspection confirmed the Rooms, Lifecycle_Automation and original Service_Requests headers match the contracts used by this bot. Live `/health` checks establish deployed version and Sheet-sync status. They do not prove end-to-end WhatsApp delivery, guide availability, or staff responses. Meta templates are still required where the recipient's messaging window has expired; a configured template must actually be approved by Meta.
