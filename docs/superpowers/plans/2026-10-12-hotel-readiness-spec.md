# Hotel receptionist reliability

The user delegates technical choices and deployments to make the existing hotel bot suitable for sale. AI must interpret natural conversations and write replies; Python validates and executes actions. Preserve existing room, order, bill, check-in, service, complaint, reminder and staff functionality. Do not invent model acceptance evidence or buy/provision paid services.

## Required behavior
- Normal follow-ups retain the latest guest/assistant pair in real provider payloads with the full production hotel configuration. Remove duplicate instruction/knowledge packets before sacrificing dialogue. Groq request budget remains12,400 UTF-8 bytes for normal requests.
- OpenAI interpretation uses its strict plan schema; independent plan review has its own compatible JSON contract. Truncated outputs and thought text never count as valid replies.
- Interpreter and reviewer receive the same compact sender-scoped operation state: pending carts, active orders, reception ticket/delivery/reply, photo choices, check-in step, and service/complaint identities and status. Never expose OTP, ID images/links, credentials or another guest's records in snapshots.
- Check-in start/submissions and service/complaint feedback receive independent intent review. Side questions cannot advance NAME/ADDRESS steps. Complaint feedback selects a sender-owned complaint identity; when multiple eligible records exist and no identity is resolved, clarify without updating a row. Failed reopen/update/notification is not reported successful.
- Regression evaluation invokes actual production process_and_reply, interpretation, review, dispatch and composition. Replace external messaging/Sheet I/O with explicit isolated test boundaries; never replace a bad answer with an expected fixture. Use Promptfoo's Python interface for model comparison, deterministic checks for backend state and private-data protection, and explicit call limits. Cached answers are historical evidence, not a fresh acceptance run.
- Readiness report distinguishes local code regressions, actual model acceptance, operational delivery and deployment/storage capacity. A blocked provider is not a passed test. Commercial readiness requires demonstrated model answers, correct backend transitions, confirmed delivery behavior and restart durability.

## Boundaries
Keep Flask and existing executors. Repair proven defects before considering a Pydantic AI production migration; a library swap alone would not resolve the reproduced context/schema/identity problems. API/model identity and reply origin must be recorded for actual runs. Each live attempt is bounded; stop on missing credentials, quota exhaustion or repeated provider unavailability.
