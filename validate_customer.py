"""Validate a white-label hotel config before deploying."""
import os
from pathlib import Path

from customer_config import (
    CustomerConfigError,
    env_defaults_from_config,
    load_customer_config,
    render_hotel_data,
)


def main():
    base = Path(__file__).resolve().parent
    try:
        data, path = load_customer_config(base)
    except CustomerConfigError as exc:
        raise SystemExit("CONFIG ERROR: " + str(exc))

    if not data:
        raise SystemExit(
            "No customer_config.json found. Copy customer_config.json.example "
            "to customer_config.json and fill the hotel's details."
        )

    rendered = render_hotel_data(data)
    if "- Name:" not in rendered:
        raise SystemExit("CONFIG ERROR: rendered hotel name missing.")

    print(f"OK: {path.name}")
    print(f"Hotel: {data['hotel']['name']}")
    print(f"Rooms: {len(data.get('rooms', []))}")
    print(f"Menu items: {len(data.get('menu', []))}")
    print(f"Local guide entries: {len(data.get('local_guide', []))}")

    defaults = env_defaults_from_config(data)
    if defaults:
        print("Phone defaults available from config: " + ", ".join(sorted(defaults)))

    required = [
        "WHATSAPP_TOKEN",
        "PHONE_NUMBER_ID",
        "VERIFY_TOKEN",
        "WHATSAPP_APP_SECRET",
        "GOOGLE_SERVICE_ACCOUNT_JSON",
        "SHEET_ID",
    ]
    missing = [name for name in required if not os.getenv(name, "").strip()]
    if missing:
        print("Render secrets still required: " + ", ".join(missing))
    else:
        print("Required Render secrets: present")


if __name__ == "__main__":
    main()
