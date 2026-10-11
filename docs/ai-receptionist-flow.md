# AI receptionist guest flow

Approved intent: AI understands every guest turn with conversation state and chooses the language and response. Python retrieves configured facts and performs validated operational actions.

## Boundaries

The active customer profile enables `ai_receptionist_flow`. Typed text, transcribed voice, button replies, reactions and image-submission context enter the interpreter before any guest keyword router. Identity questions use the same gateway. Staff/operator command bridges stay separate and retain authorization and mapped-ticket checks.

The interpreter returns one structured action, confidence, language, resolved operation arguments and a conversational reply. Context includes the sender’s pending check-in, cart, demo stay, staff confirmation and reception ticket. OTP secrets and ID links are excluded. Side questions do not enter pending order/check-in executors. Ambiguity asks a clarification; AI unavailability performs no guessed action. Multiple operational requests must be clarified or coordinated through reception.

Canonical action arguments invoke existing operational handlers. Orders retain verified menu matching, integer quantities, check-in permissions, fresh confirmation, duplicate-write protection and uncertain-write handling. Bills use sender-bound verified records and fresh refreshes. Check-in step changes and OTP equality remain Python checks. ID upload does not bypass reception verification.

Backend guest messages are result data for an AI response composer. Staff messages are not rewritten. The composer receives the original guest utterance, AI meaning, selected language and actual operation result. It cannot request further actions. Numeric values, links, identifiers and item-price breakdown rows are validated; invalid generation or provider failure retains the verified result rather than losing a completed operation or inventing a price. Pure informational replies already authored by the interpreter are sent directly. Existing proactive lifecycle AI wording and opt-in reminder schedules remain preserved.

## Implementation and verification

1. Add a dedicated gateway and structured interpretation fields.
2. Route guest messages before legacy language/keyword shortcuts.
3. Adapt existing operations to canonical arguments and intercept guest replies.
4. Enable both Shreya profiles and use a distinct health version.
5. Run legacy regressions and new gateway, transport, check-in and complete demo-order regressions.
6. Deploy the tested commit, check startup’s read-only availability/language probe, then check health and deployed commit.

## Limits

The model still can misunderstand an utterance; no model can guarantee human understanding of every phrase. Interpreter tests use deterministic provider fixtures; the live startup probe checks actual provider behavior without sending any guest/staff messages or writing Sheets. Full real WhatsApp conversations still require guest input and staff responses. If AI is unavailable, operational results may use the verified backend fallback.
