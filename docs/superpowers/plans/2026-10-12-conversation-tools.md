# Conversation Tool Engine Implementation Plan

Goal: AI plans multiple hotel tools and writes a complete grounded reply.
Architecture: dedicated planner and validator; existing verified executors; per-turn collected receipts; one final composer.
Spec: docs/superpowers/specs/2026-10-12-conversation-tools.md
Execution: inline, authorized by the user's request to implement and resolve the architecture now.

Global constraints: preserve current hotel operations; no guessed stock, prices, ETA or success; no demo switch; no action retries on reply failures.
Review focus: combined transactions; script correction; malformed AI output; partial tool failure; cross-guest transport isolation.

1. Write failing tests for multi-tool validation, script handling, receipt isolation and side-effect failures; run them.
2. Implement conversation_engine.py with plan(bot, phone, text, guest), validate_plan(bot, value), handle(bot, phone, text, guest, message), and ContextVar text collection.
3. Integrate guest routing and send collection with no changes to staff/webhook paths. In tool mode the legacy adapter uses AI language and bypasses guest keyword language/correction routing.
4. Verify targeted tests and complete unittest discovery; review diff and fix important findings before publishing.
5. Publish a reviewable PR; merge/deploy only after passing checks under existing authorization. Verify actual deployment if accessible; otherwise state the precise unverified boundary.
