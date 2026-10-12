# Hotel automation reliability

The guest must receive a complete, readable reply with the actual action result, correct prices and every side question. Existing sender ownership, confirmation, billing and write deduplication remain authoritative.

Official references recommend simple composable tool workflows, bounded context and evaluation of real conversations:
- https://www.anthropic.com/engineering/building-effective-agents
- https://console.groq.com/docs/structured-outputs
- https://docs.cohere.com/docs/compatibility-api
- https://docs.cohere.com/docs/reasoning

Observed failures: Cohere reasoning consumes its tiny output budget; shared adapter instructions classify English workflow prompts instead of the original guest; literal presentation checks reject correct price paraphrases; redundant read-only reviews consume tokens without improving transaction protection.

Implement sequentially: correct Cohere reasoning/output settings; isolate explicit workflow contracts from generic chat language instructions; reduce read-only tool overhead only after real-provider evidence; bind numbers and prices to tool data without requiring unchanged surrounding prose. Use native JSON schemas where supported, existing Python business validators for writes, actual receipts for final response and provider fallback only for inference, never for action replay.

Acceptance: full offline suite and isolated real-provider guest cases, including readability, contextual price, compound service, cart revision, billing/privacy and ETA. Model tests deny WhatsApp/Sheets writes; they do not prove real staff delivery. No sale-ready claim without that evidence.

Authorization: user explicitly asked to find working automation approaches anywhere, implement them and do the necessary changes; publication and deployment were authorized earlier in this conversation. Execute without another approval loop.
