"""White-label customer configuration loader.

New hotel deployments may use one JSON file instead of editing Python or the
legacy hotel_data.txt. Existing deployments remain unchanged unless a customer
config file is present (or CUSTOMER_CONFIG_FILE explicitly points to one).
"""
import json
import os
from pathlib import Path


DEFAULT_CONFIG_NAME = "customer_config.json"


class CustomerConfigError(ValueError):
    pass


def _text(value):
    return str(value or "").strip()


def _list(value):
    return value if isinstance(value, list) else []


def _dict(value):
    return value if isinstance(value, dict) else {}


def customer_config_path(base_dir):
    explicit = _text(os.getenv("CUSTOMER_CONFIG_FILE"))
    if explicit:
        return Path(explicit)
    candidate = Path(base_dir) / DEFAULT_CONFIG_NAME
    return candidate if candidate.exists() else None


def load_customer_config(base_dir):
    path = customer_config_path(base_dir)
    if not path:
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CustomerConfigError(f"Customer config not found: {path}")
    except json.JSONDecodeError as exc:
        raise CustomerConfigError(
            f"Invalid JSON in {path.name}: line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(data, dict):
        raise CustomerConfigError("Customer config root must be a JSON object.")
    validate_customer_config(data)
    return data, path


def validate_customer_config(data):
    hotel = _dict(data.get("hotel"))
    if not _text(hotel.get("name")):
        raise CustomerConfigError("hotel.name is required.")
    if not _text(hotel.get("location")):
        raise CustomerConfigError("hotel.location is required.")

    rooms = _list(data.get("rooms"))
    for i, room in enumerate(rooms, start=1):
        if not isinstance(room, dict):
            raise CustomerConfigError(f"rooms[{i}] must be an object.")
        if not _text(room.get("name")):
            raise CustomerConfigError(f"rooms[{i}].name is required.")
        try:
            price = int(room.get("price"))
        except (TypeError, ValueError):
            raise CustomerConfigError(f"rooms[{i}].price must be a whole number.")
        if price < 0:
            raise CustomerConfigError(f"rooms[{i}].price cannot be negative.")

    menu = _list(data.get("menu"))
    seen = set()
    for i, item in enumerate(menu, start=1):
        if not isinstance(item, dict):
            raise CustomerConfigError(f"menu[{i}] must be an object.")
        name = _text(item.get("name"))
        if not name:
            raise CustomerConfigError(f"menu[{i}].name is required.")
        key = name.casefold()
        if key in seen:
            raise CustomerConfigError(f"Duplicate menu item: {name}")
        seen.add(key)
        try:
            price = int(item.get("price"))
        except (TypeError, ValueError):
            raise CustomerConfigError(f"menu[{i}].price must be a whole number.")
        if price < 0:
            raise CustomerConfigError(f"menu[{i}].price cannot be negative.")

    contacts = _dict(data.get("contacts"))
    for key in ("reception_phone", "kitchen_phone", "staff_phone"):
        value = _text(contacts.get(key))
        if value and not value.replace("+", "").replace(" ", "").isdigit():
            raise CustomerConfigError(f"contacts.{key} should contain a phone number.")

    return True


def env_defaults_from_config(data):
    contacts = _dict(data.get("contacts"))
    defaults = {}
    mapping = {
        "reception_phone": "RECEPTION_PHONE",
        "kitchen_phone": "KITCHEN_PHONE",
        "staff_phone": "STAFF_PHONE",
    }
    for source, env_name in mapping.items():
        value = _text(contacts.get(source))
        if value:
            defaults[env_name] = value
    return defaults


def render_hotel_data(data):
    """Render structured JSON into the legacy hotel_data text contract."""
    hotel = _dict(data.get("hotel"))
    policies = _dict(data.get("policies"))
    lifecycle = _dict(data.get("lifecycle"))
    media = _dict(data.get("media"))
    maps = _dict(data.get("maps"))
    rooms = _list(data.get("rooms"))
    menu = _list(data.get("menu"))
    guide = _list(data.get("local_guide"))
    custom_rules = _list(data.get("custom_rules"))
    faq = _list(data.get("faq"))

    lines = [
        f"HOTEL DATA — {_text(hotel.get('name')).upper()}",
        "",
        "==================================================",
        "1. HOTEL IDENTITY & BASIC INFORMATION",
        "==================================================",
        f"- Name: {_text(hotel.get('name'))}",
        f"- Location: {_text(hotel.get('location'))}",
    ]
    simple_hotel_fields = [
        ("Check-in", hotel.get("check_in")),
        ("Check-out", hotel.get("check_out")),
        ("Reception / Front Desk", hotel.get("reception_hours")),
        ("Amenities", hotel.get("amenities")),
        ("Parking", hotel.get("parking")),
        ("Wi-Fi", hotel.get("wifi")),
        ("Address", hotel.get("address")),
    ]
    for label, value in simple_hotel_fields:
        if _text(value):
            lines.append(f"- {label}: {_text(value)}")

    lines += [
        "",
        "==================================================",
        "2. ROOM CATEGORIES & TARIFFS",
        "==================================================",
    ]
    if rooms:
        for room in rooms:
            suffix = _text(room.get("details"))
            label = _text(room.get("name")) + (f" ({suffix})" if suffix else "")
            lines.append(f"- {label}: Rs. {int(room.get('price'))} per night")
    else:
        lines.append("- No room tariff has been configured. Reception must confirm rates.")

    room_rules = _list(data.get("room_rules"))
    if room_rules:
        lines += ["", "RULES:"]
        lines += [f"- {_text(rule)}" for rule in room_rules if _text(rule)]

    lines += [
        "",
        "==================================================",
        "3. HOTEL FOOD MENU & RATES — AUTHORITATIVE MENU",
        "==================================================",
    ]
    if menu:
        intro = _text(data.get("menu_intro")) or "Only listed items may be ordered."
        lines.append(intro)
        lines.append("")
        for item in menu:
            lines.append(f"- {_text(item.get('name'))}: Rs. {int(item.get('price'))}")
    else:
        lines.append("No room-service menu is configured. Do not create food orders.")

    food_rules = _list(data.get("food_rules"))
    if food_rules:
        lines += ["", "FOOD RULES:"]
        lines += [f"- {_text(rule)}" for rule in food_rules if _text(rule)]

    lines += [
        "",
        "==================================================",
        "4. LOCAL GUIDE — AI MAY REASON FROM THIS DATA",
        "==================================================",
    ]
    if guide:
        for place in guide:
            if not isinstance(place, dict) or not _text(place.get("name")):
                continue
            parts = [_text(place.get("name"))]
            field_map = [
                ("Category", place.get("category")),
                ("Distance", place.get("distance")),
                ("Best time", place.get("best_time")),
                ("Opening reference", place.get("opening_reference")),
                ("Maps", place.get("maps_query") or place.get("name")),
            ]
            parts.extend(f"{k}: {_text(v)}" for k, v in field_map if _text(v))
            lines.append("- " + " | ".join(parts))
    else:
        lines.append("- No local guide entries configured.")

    lines += [
        "",
        "==================================================",
        "5. GUEST POLICIES",
        "==================================================",
    ]
    if policies:
        for key, value in policies.items():
            if isinstance(value, bool):
                rendered = "Yes" if value else "No"
            elif isinstance(value, (str, int, float)):
                rendered = _text(value)
            else:
                continue
            if rendered:
                label = str(key).replace("_", " ").title()
                lines.append(f"- {label}: {rendered}")
    else:
        lines.append("- Policies not listed here require reception confirmation.")

    lines += [
        "",
        "==================================================",
        "6. GUEST LIFECYCLE AUTOMATIONS",
        "==================================================",
    ]
    if lifecycle:
        for key, value in lifecycle.items():
            if _text(value):
                lines.append(f"- {str(key).replace('_', ' ').title()}: {_text(value)}")
    else:
        lines.append("- Use the bot's default lifecycle automation windows.")

    lines += [
        "",
        "==================================================",
        "7. CHECK-IN & ID VERIFICATION",
        "==================================================",
        "- Ask for ID only for check-in/document submission.",
        "- A received ID photo is not automatically verified.",
        "- Room allocation and identity verification require hotel staff confirmation.",
        "",
        "==================================================",
        "8. HOUSEKEEPING / STAFF REQUESTS",
        "==================================================",
        "- In-house service requests may be routed to configured staff/reception.",
        "- Do not claim completion until staff confirms it.",
        "",
        "==================================================",
        "9. BILLING & PAYMENTS",
        "==================================================",
        "- Bills and payment status come from the configured hotel records, not AI guesses.",
        "",
        "==================================================",
        "10. AI RECEPTIONIST BEHAVIOUR",
        "==================================================",
        "- Understand natural Hindi, Hinglish and English.",
        "- Use this customer configuration as hotel-specific source of truth.",
        "- Never invent live availability, payment status, bookings, discounts, delivery or unsupported hotel facts.",
        "- If a fact is missing, ask reception to confirm it.",
        "- Keep normal replies short, natural and useful.",
    ]

    if faq:
        lines += ["", "==================================================", "FAQ / HOTEL-SPECIFIC ANSWERS", "=================================================="]
        for item in faq:
            if isinstance(item, dict):
                q, a = _text(item.get("question")), _text(item.get("answer"))
                if q and a:
                    lines += [f"- Question: {q}", f"  Answer: {a}"]

    if custom_rules:
        lines += ["", "==================================================", "CUSTOM HOTEL RULES", "=================================================="]
        lines += [f"- {_text(rule)}" for rule in custom_rules if _text(rule)]

    lines += ["", "==================================================", "PHOTOS & MEDIA", "=================================================="]
    photos = _dict(media.get("photos"))
    if photos:
        for name, url in photos.items():
            if _text(url):
                lines.append(f"{_text(name)}: {_text(url)}")
    else:
        lines.append("# No public photo URLs configured.")

    lines += ["", "==================================================", "GOOGLE MAPS", "=================================================="]
    for name, url in maps.items():
        if _text(url):
            lines.append(f"{_text(name)}: {_text(url)}")

    return "\n".join(lines).strip() + "\n"
