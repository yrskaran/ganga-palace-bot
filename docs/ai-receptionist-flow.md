# Hotel conversation flow

The active production profiles enable `ai_receptionist_flow` and `conversation_tool_engine`. Guest text, transcribed voice, buttons, reactions and attached-image context enter `conversation_engine.handle` before the legacy guest router. Staff/operator command bridges and proactive jobs remain separate.

## AI and tool boundary

The AI receives current guest text, role-separated dialogue, selected verified hotel facts and sender-owned operation state. It returns language, readable script, every question/correction and up to four independent tool operations. Ordinary conversation and readability/language feedback can have no tools. Multiple operations may share a type if their verified arguments differ; exact duplicate operations are rejected. Cart creation/revision and confirmation cannot be combined in the same turn.

Python validates the entire plan before any tool executes: allowed operations, canonical menu items, explicit integer quantities, field types and incompatible transactions. Every operation is independently reviewed against current message, dialogue, its whole-turn scope and saved sender state. Photo intent has a separate independent review; its target must be configured, unspecified, exterior or explicitly all room photos.

Canonical arguments enter existing verified executors. Stay permissions, OTP equality, ID verification, fresh cart confirmation, sender-bound bills, Sheet-write checks and duplicate protection remain there. Guest result text is collected in a ContextVar rather than transported separately. Staff transport continues normally. Images use real transport and add actual acceptance/failure receipts; API acceptance does not prove guest delivery.

The AI then writes one reply using static facts, fresh sender state and collected results, answering every question in the requested language/script. Numeric values, identifiers, URLs, menu quantities and price rows are protected. An independent support/coverage check rejects invented facts and claimed action success unsupported by receipts. Readability correction rephrases existing facts without creating a new order or showing a menu. Original guest text and actual delivered reply become conversation history; canonical executor commands do not replace the guest's message.

## Failure handling

Malformed/invalid plans or failed operation review execute no new tools. A tool exception stops remaining operations, discloses uncertain outcome and never retries a possibly completed write. Final wording failures do not replay actions. Verified readable receipts are retained, with a request to verify remaining status at reception. Native-script receipts are withheld when Roman script was requested; no guessed translation is sent.

The existing single-action gateway remains available for legacy profiles and isolated demo regression fixtures. It is not the active production engine. Provider ordering is unchanged. Structured JSON requests use the flexible JSON envelope and provider failover rather than the old single-action schema.

## Verification for this change

384 automated tests pass, including the existing regression suite, isolated provider/transport fixtures, native production-entry evaluation, combined order/ETA, independent services, script corrections, invalid quantities, sender-state replies, failed writes and no transaction replay after final-response failure. An independent review identified missing final-state evidence and unreadable failure fallback; both have regression coverage. The read-only startup probe exercises actual whole-turn planning without executing tools or writing guest/staff/Sheet data.

Offline fixture tests are not fresh-model or real WhatsApp acceptance. Live deployment, startup probe results and real guest/staff conversation retesting remain unverified until the tested branch can be published.
