# Automation Reliability Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, then independent whole-change review.

**Goal:** Complete real guest replies using the configured three-provider chain and existing verified hotel tools.
**Architecture:** Explicit workflow contracts carry their own original guest context. Provider adapters return complete JSON; deterministic execution remains isolated from inference retries.
**Tech Stack:** Python, unittest, REST model adapters, Render.
**Spec:** docs/superpowers/specs/2026-10-12-automation-reliability.md

## Global Constraints
- Preserve sender ownership, fresh order confirmation and write deduplication.
- Never repeat a tool write when a provider or final response fails.
- Actual provider tests deny WhatsApp and Sheets mutations.

## Review Focus
- English workflow prompts must not override a Roman Punjabi guest.
- Cohere must return final content without private thinking leaking to guests.
- Price wording may change, while item/amount bindings must not.
- Read-only retrieval must not consume unnecessary operation review calls.
- Failed save/alert must remain explicitly failed in the final reply.

## Task 1: Complete contract inference
- [ ] Add failing transport tests for Cohere reasoning mode/output and contract instruction isolation.
- [ ] Implement explicit contract envelopes in ai_context.py and conversation_engine.py; correct Cohere payload in app.py.
- [ ] Run targeted and full unittest suites; commit.

## Task 2: Grounded efficient tools
- [ ] Reproduce remaining real-provider failures with isolated hotel_eval.py.
- [ ] Add failing regression tests for the observed failures; implement minimal contract/retrieval changes.
- [ ] Run targeted and full suites; commit.

## Task 3: Publish and evaluate
- [ ] Independent review of complete diff; address consequential findings with regression tests.
- [ ] Publish tested tree, deploy and run 20 distinct isolated real-provider cases with the configured fallback chain.
- [ ] Record actual replies, acceptance, token usage and blocked cases; stop automatic evaluation after completion.
