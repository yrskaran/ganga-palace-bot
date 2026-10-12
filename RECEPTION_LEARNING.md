# Hotel knowledge → Reception → Guest → Learned hotel facts

This is an **opt-in addition to knowledge-only mode**. No order, billing, guest check-in, service roster, kitchen, or lifecycle workflows are enabled.

## Configuration and activation

- Keep `KNOWLEDGE_ONLY_MODE=true`.
- Set `KNOWLEDGE_RECEPTION_LEARNING=true` to enable the optional human-fact handoff.
- Existing `RECEPTION_PHONE` in `customer_config.json` is the fallback recipient. Confirm it points to the correct **test hotel reception** before enabling; the config currently names Hotel Shreya Galaxy while `hotel_data.txt` names Hotel Ganga View.
- Existing `GOOGLE_SERVICE_ACCOUNT_JSON` and `SHEET_ID` must permit writes to the hotel management Google Sheet.
- If WhatsApp's business-initiated 24-hour conversation window is closed for the receptionist, configure an approved `WA_RECEPTION_TEMPLATE`; ordinary text alerts may be rejected. The guest gets a truthful error if WhatsApp rejects the alert.
- The service sets no new AI API keys and does not duplicate the existing WhatsApp number.

## Conversation

1. The AI uses published facts from `hotel_data.txt`, recent conversation, and reception-verified FAQ. It answers naturally and doesn't call operational functions.
2. If a specific hotel fact is missing, the same AI response ends with `[[ASK_RECEPTION: exact clarification]]`. This marker is removed before guests see anything.
3. One mapped ticket goes to configured reception. The guest gets an acknowledgment only after WhatsApp accepts it and the ticket can be durably tracked in `Reception_Requests`.
4. The receptionist **replies to the original R-ID WhatsApp alert** (quoted reply). The bot verifies the sender number and request mapping, and sends the exact text body unchanged—without AI rewriting, greeting, prefixes or emojis.
5. A reusable general factual answer is stored in `Reception_Knowledge` with its question and validity, then mirrored to UTF-8 `hotel_data_learned.txt`. The AI also reads these verified FAQs directly from the durable Sheet, so the same question isn't escalated again.
6. Replies about a specific booking, current room availability, payments, guest identity, bill, or transient operational request are delivered to the original guest but aren't turned into shared hotel facts.

## Persistence on Render

Render's free filesystem is **ephemeral**. The running service writes a real UTF-8 file at `/tmp/hotel-bot-demo/hotel_data_learned.txt`, but that file isn't committed to GitHub. To avoid losing learned facts across deploys, the authoritative store is Google Sheets' `Reception_Knowledge`, and the text mirror is reconstructed from verified rows at startup. This does not rewrite the version-controlled base `hotel_data.txt`.

Do not assume this flow is production-proven merely because unit tests pass. Verify at least one real unknown guest message, reception WhatsApp alert, quoted staff reply, guest delivery, knowledge reuse, and Render restart. Check the reception phone and spreadsheet access first.