# Production hotel receptionist

The active profile uses the real receptionist flow. There are no guest-facing demo orders or demo check-in requirements.

AI interprets the message with recent conversation and pending operations. A focused AI review checks menu scope, language, privacy and payment integrity. Python validates the resulting fields and runs existing operational handlers. AI writes the final reply from the verified outcome; menu information alone never proves an order exists.

Copy `customer_config.json.example` for another hotel and select it with `CUSTOMER_CONFIG_FILE`. Configure hotel identity, room categories/rates, menu items/prices, FAQs, policies, local guide and media. No Python changes are required for these hotel facts. The example's facts/prices must be replaced with that hotel's approved information.

Each hotel requires its own WhatsApp API credentials and authorized Google service account. Set `integrations.sheet_id` to its operational Sheet and `contacts.reception_phone`, `contacts.kitchen_phone`, `contacts.staff_phone`, and `contacts.owner_phone` to its assigned numbers. Configured hotel deployments take these connections from their JSON profile, so changing hotel identity cannot silently reuse old environment Sheet/staff/owner connections. An empty connection is unavailable, never simulated success.

The active Shreya profile temporarily uses the existing Ganga Palace operational Sheet at the owner's explicit request. Guest records, check-in, order writes and bills therefore use that shared Sheet. Replace this temporary binding with the destination hotel's own operational Sheet when onboarding that hotel.

Keep the established Rooms, Kitchen_Orders, Staff_Roster and lifecycle schemas. Real room service requires a verified active stay; cart revisions require fresh explicit confirmation. Kitchen notification, delivery, payment and order persistence are separate outcomes.

`guest_checks.py` can run opt-in actual-provider synthetic conversations. It captures replies without WhatsApp sends or operational writes. Operational receipts in those tests are simulated fixtures and are not proof of a live staff/Sheet integration. Disable `AI_GUEST_CHECK_RUN` after a diagnostic run.

Commercial hosting must preserve the SQLite ledger across restarts. For a single Render instance, prepare a persistent disk mounted at `/var/data`, set `BOT_STORAGE_MODE=persistent` and `BOT_DB_PATH=/var/data/hotel-bot.sqlite3`, and verify a queued message, pending cart and deduplication record after a controlled restart. The current free deployment uses temporary storage and has not passed this gate. A paid resource has not been provisioned by this repair.

`hotel_eval.py` now runs the actual `process_and_reply` entry: interpretation, independent review, dispatch, final composition and accepted-message conversation memory. Its guest records are synthetic; outbound WhatsApp and Sheet access are isolated. Expectations are never passed to the model. Transport doubles, backend wording fallbacks and failed providers are labelled separately from fresh model acceptance. The optional Promptfoo configuration is in `evals/promptfooconfig.yaml`; cached results must not be used as fresh acceptance.

An opt-in Render comparison runs in a separate process with `AI_PRODUCTION_CHECK_RUN`, `AI_PRODUCTION_CHECK_MODEL` and `AI_PRODUCTION_CHECK_LIMIT`. The model override applies only to that process. Stop and clear these flags after collecting results. Public guest messages cannot activate the check. Generation calls stop at the configured limit or the first provider HTTP error.

Before selling a hotel installation, finish the diverse conversation suite and separately verify destination Sheet writes, real staff delivery receipts/replies, order confirmation/correction/cancellation, failed-send behaviour, billing privacy and restart recovery. Local regression tests and isolated model replies do not prove those integrations. Keep customer connections and guest records separate for every hotel.
