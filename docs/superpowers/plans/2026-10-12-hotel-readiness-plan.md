# Hotel Receptionist Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Repair reproduced production conversation and transaction defects, then make commercial acceptance verifiable.
**Architecture:** Preserve current Flask executors. Consolidate context assembly, separate provider response contracts, join authoritative sender state, scope feedback identities, and test the actual entry point with isolated external I/O.
**Tech Stack:** Python3.12, Flask, unittest, existing REST adapters, optional Promptfoo Python provider.
**Spec:** docs/superpowers/plans/2026-10-12-hotel-readiness-spec.md

## Global Constraints
- No paid-service purchase, no real guest/order/payment/staff mutation during evaluation.
- AI owns semantic interpretation and guest wording; no new customer keyword routers.
- Preserve existing features and legacy compatibility.
- Ordinary Groq request budget12,400 UTF-8 bytes; actual model responses are not inferred from local tests.

## Review Focus
- Full production menu/facts must not erase short follow-up history.
- A compliant OpenAI review output must pass Python validation rather than conflict with its HTTP schema.
- Multiple complaints/other guests must never cause a wrong-row update.
- Check-in side questions must not be stored as a name/address.
- A dry-run, cached result, API error or verified-data fallback must not be reported as fresh model acceptance.

### Task1: Provider context and response contracts
Files: app.py, ai_receptionist.py, new ai_context.py, test_ai_context.py.
Interfaces: compact provider context builder consumes bot/config/guest/history and returns system plus role-separated messages; existing public provider signatures remain unchanged.
- [ ] Write failing full-profile Groq/OpenAI history and schema-stage tests; observe failures.
- [ ] Compact shared interpretation instructions and provider wrapper facts; keep current message and recent context together.
- [ ] Give OpenAI plan-review calls JSON-object response contracts, with existing strict Python branch validation; increase complete-plan output allowance.
- [ ] Run targeted tests and full repository suite; commit verified changes.

### Task2: Sender-scoped authoritative operation state
Files: ai_receptionist.py, app.py, test_ai_state.py.
Interfaces: snapshot(bot,phone) returns compact, redacted sender-owned records; complaint records have stable complaint_id and row identity; service records retain request_id/details/status.
- [ ] Reproduce missing reception/service/complaint state and privacy/redaction failures.
- [ ] Join existing cached records without external reads, pass identical snapshots into interpretation/review, and keep ambiguous identities unresolved.
- [ ] Test multiple requests, foreign senders and secret redaction; run full suite; commit.

### Task3: Intent review and complaint feedback integrity
Files: ai_receptionist.py, app.py, test_ai_transactions.py.
Interfaces: review_plan covers check-in and feedback actions; _handle_complaint_feedback(phone,text,complaint_id=None) preserves old call compatibility while resolving exactly one eligible sender record.
- [ ] Reproduce side-question step advancement, ignored complaint identity and ambiguous wrong-row closure.
- [ ] Extend reviewed operation schema with task_id and check-in/feedback actions, validate step/identity prerequisites, and pass complaint identity to the real executor.
- [ ] Ensure failed update/reopen/send does not become a success claim; verify old single-complaint behavior remains.
- [ ] Run targeted tests and full suite; commit.

### Task4: Production-flow evaluation and readiness evidence
Files: new hotel_eval.py, evals/promptfooconfig.yaml, test_hotel_eval.py, readiness report.
Interfaces: call_api(prompt,options,context) returns actual guest output plus provenance/operation metadata; isolated worker invokes production process_and_reply with mocked external I/O and bounded real model calls.
- [ ] Reproduce incomplete test-path bypass and operational network escape with failing harness tests.
- [ ] Implement actual production-entry evaluation; feed expectations only to assertions, never to model input. Add Promptfoo configuration and explicit no-fresh-acceptance markers for cache/fallback/provider failure.
- [ ] Run offline full-flow regressions, then at most a bounded small live comparison when a provider responds; stop on external blockers.
- [ ] Save exact replies/failures, check runtime health/storage/deployment requirements, publish honest readiness report.

## Execution ledger
Baseline75bf53d:264 tests pass. Reproduced actual Groq payload13,435 bytes with zero retained dialogue; OpenAI strict schema forbids review flags. User's explicit delegation authorizes inline decisions and deployment; no repeated confirmation needed. External worktree avoids changing the production checkout while implementing.
