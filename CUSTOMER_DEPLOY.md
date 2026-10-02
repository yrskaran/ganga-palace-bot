# New Hotel Deployment — simple white-label workflow

For a new customer, **do not edit app.py, durable_runtime.py, reliability.py, bot.py, or admin.py**.

## What changes per hotel

You only need:

1. `customer_config.json` — hotel name, timings, rooms, menu, policies, photos, local guide.
2. Render environment variables — WhatsApp credentials, Sheet ID, reception/kitchen/staff numbers, and AI key.
3. The hotel's Google Sheet using the existing Rooms / Kitchen_Orders / Staff_Roster structure.

Everything else is the reusable bot engine.

## Fast onboarding

1. Duplicate this repository for the hotel. You can keep all hotel repos in the **same GitHub account**; a new GitHub account is not required.
2. Copy `customer_config.json.example` to `customer_config.json`.
3. Edit only `customer_config.json`. Do not put API tokens or service-account secrets in this file.
4. Optional preflight: run `python validate_customer.py`. GitHub Actions also checks Python syntax on every push.
5. In Render, create a service from the repo (or use `render.yaml`) and enter the required secret environment variables.
6. In Meta WhatsApp, set callback URL to `https://YOUR-RENDER-SERVICE.onrender.com/webhook` and use that hotel's `VERIFY_TOKEN`.
7. Test:
   - `/health`
   - guest greeting
   - room/menu question
   - food confirmation
   - reception request
   - reception quoted reply back to the guest

## One-file hotel customization

The bot automatically prefers `customer_config.json` when it exists. Existing legacy deployments without that file keep using `hotel_data.txt`.

Phone values in `customer_config.json` are convenience defaults only. For production, Render environment variables win and should be used for staff numbers.

## Safe rule

Never copy these between hotels: WhatsApp token, Phone Number ID, App Secret, Google service-account secret, Sheet ID, or real guest data.

## Recommended repo naming

- `hotel-ai-template` — master reusable code
- `hotel-ai-ganga-view`
- `hotel-ai-customer-name`

When the core engine improves, apply the same tested core changes to customer repos; hotel-specific data stays isolated in `customer_config.json`.
