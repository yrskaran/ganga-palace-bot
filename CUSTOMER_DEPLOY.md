# New Hotel Deployment — simple white-label workflow

For a new customer, **do not edit app.py, durable_runtime.py, reliability.py, bot.py, or admin.py**.

## What changes per hotel

You only need:

1. `customer_config.json` — hotel name, timings, rooms, menu, policies, photos, local guide.
2. Render environment variables — WhatsApp credentials, Sheet ID, AI key, and optional legacy fallback staff numbers.
3. The hotel's Google Sheet using the existing Rooms / Kitchen_Orders / Staff_Roster structure. In production, Staff_Roster is the live source of truth for staff role, duty status and room assignment.

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

Phone values in `customer_config.json` and Render are fallback values only. For production, `Staff_Roster` should be authoritative. Changing a staff member's Role, Status or Assigned Rooms in the Sheet changes future routing automatically (normally within about 10 seconds).

## Safe rule

Never copy these between hotels: WhatsApp token, Phone Number ID, App Secret, Google service-account secret, Sheet ID, or real guest data.

## Recommended repo naming

- `hotel-ai-template` — master reusable code
- `hotel-ai-ganga-view`
- `hotel-ai-customer-name`

When the core engine improves, apply the same tested core changes to customer repos; hotel-specific data stays isolated in `customer_config.json`.


## Staff_Roster — no code edits for staff changes

| Staff Name | Role | WhatsApp | Status | Duty Date | Assigned Rooms |
|---|---|---|---|---|---|
| Priya | Reception | 91XXXXXXXXXX | ON DUTY | Daily | All |
| Ravi | Housekeeping | 91XXXXXXXXXX | ON DUTY | Daily | 201,202,203,205 |
| Mohan | Housekeeping | 91XXXXXXXXXX | LEAVE | Daily | 204,206 |
| Amit | Maintenance | 91XXXXXXXXXX | ON DUTY | Daily | 201-210 |

Rules:
- `Role` may be Reception, Housekeeping, Maintenance, Kitchen, Room Service, etc.
- `Status` values such as ON DUTY / ACTIVE / AVAILABLE are eligible. LEAVE / OFF / HOLIDAY are skipped.
- `Date` / `Duty Date`: use `Daily` for recurring staff, or a real duty date such as `03-10-2026`. Old dated rows are ignored automatically.
- `Shift`: prefer explicit 24-hour ranges such as `08:00-16:00`, `16:00-00:00`, or `22:00-06:00`. `Morning`, `Evening`, `Night`, and `Full Day` are also supported.
- One staff member may have many rooms: `201,202,203`, `201/202/203`, or a range such as `201-210`.
- `All` or a blank Assigned Rooms cell means role-wide staff.
- Exact room assignment wins over role-wide staff.
- If a role exists in Staff_Roster but nobody eligible is on duty, the bot does not silently route to an old fallback number.
- Reception requests are sent to the current Sheet-assigned receptionist. Each ticket remembers who received it, so their quoted reply is mapped back to the correct guest.
