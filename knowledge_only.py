"""Temporary knowledge-only WhatsApp conversation, with no hotel tool execution.

This module intentionally does not import service, check-in, order, reception,
bill, spreadsheet, or notification handlers. The normal transport, deduplication
and per-sender conversation history remain available.
"""
import json
import os
import re
import reception_learning
from pathlib import Path


def read_hotel_file(bot):
    """Read hotel_data.txt explicitly; do not silently use another hotel's JSON."""
    configured = os.getenv("KNOWLEDGE_ONLY_FILE", "").strip()
    path = Path(configured) if configured else Path(__file__).resolve().with_name("hotel_data.txt")
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        print(f"KNOWLEDGE ONLY FILE UNAVAILABLE: {type(exc).__name__}", flush=True)
        return "", "Hotel"
    name_match = re.search(r"(?im)^\s*-\s*Name\s*:\s*(.+?)\s*$", raw)
    hotel_name = name_match.group(1).strip() if name_match else "Hotel"
    return raw, hotel_name


def public_knowledge(raw):
    """Return guest-facing hotel facts; exclude instructions for paused operations."""
    output = []
    included = False
    rules = False
    for line in str(raw or "").splitlines():
        heading = line.strip()
        numbered = re.match(r"^(\d{1,2})\.\s+[A-Z]", heading)
        if numbered:
            included = int(numbered.group(1)) in (1, 2, 3, 4, 5)
            rules = False
        elif heading in ("PHOTOS & MEDIA", "GOOGLE MAPS"):
            included = True
            rules = False
        elif heading in ("LOCAL GUIDE RULES", "HARIDWAR CONCIERGE PLANNING",
                         "HUMAN TOUR GUIDE REQUESTS") or heading.startswith("GUIDE SOURCES"):
            included = False
            rules = False
        if not included:
            continue
        if heading in ("RULES:", "FOOD RULES:", "LOCAL GUIDE BEHAVIOUR:"):
            rules = True
            continue
        if rules or heading.startswith("Use this as the guest-facing Haridwar guide."):
            continue
        if heading.startswith("# Replace these") or heading.startswith("# Do not change"):
            continue
        if heading.startswith("The following is the hotel kitchen's current pure-vegetarian room-service menu."):
            output.append("Published pure-vegetarian room-service food menu (information only):")
            continue
        output.append(line)
    # Lightweight callers/tests may provide just a flat hotel fact snippet,
    # without the numbered sections found in production hotel_data.txt.
    if not re.search(r"(?m)^\d{1,2}\.\s+[A-Z]", str(raw or "")):
        return str(raw or "").strip()
    return "\n".join(output).strip()


def facts_for_conversation(bot, public_text, conversation_query="", max_bytes=9300):
    """Keep all core hotel facts with each AI turn, regardless of guest wording.

    Guest-facing identity, complete room tariffs, the full published food menu,
    Aarti facts and Maps links form the stable base. Relevant long local-guide
    excerpts fit in the remaining budget; actions remain fully disabled.
    """
    text = str(public_text or "").strip()
    section_matches = list(re.finditer(r"(?m)^(\d{1,2})\.\s+[A-Z].*$", text))
    if not section_matches:
        # Existing callers can supply an unsectioned knowledge excerpt.
        if len(text.encode("utf-8")) <= max_bytes:
            return text
        return bot._ai_knowledge_snapshot(max_bytes, conversation_query, raw_override=text)
    sections = {}
    for idx, match in enumerate(section_matches):
        end = section_matches[idx + 1].start() if idx + 1 < len(section_matches) else len(text)
        sections[int(match.group(1))] = text[match.start():end].strip()
    essential = "\n\n".join(sections.get(n, "") for n in (1, 2, 3, 5) if sections.get(n))
    remaining = max_bytes - len(essential.encode("utf-8")) - 100
    guide = sections.get(4, "")
    if guide and remaining > 450:
        excerpts = bot._ai_knowledge_snapshot(
            min(remaining, 5000), conversation_query, raw_override=guide
        ).strip()
        if excerpts:
            essential += "\n\nADDITIONAL LOCAL GUIDE FACTS:\n" + excerpts
    return essential.strip()


# A final boundary for false operational-success claims. This does NOT decide
# intent or run a workflow: the conversational AI is still the only responder.
_UNVERIFIED_PROMISE = [
    r"\brequest\b.{0,95}\bstaff tak pahunch",
    r"\b(?:request|order|booking)\b.{0,90}\b(?:confirm ho gay|staff ko notify|forward kar di|register ho gay)",
    r"\b(?:maine|humne|we have|i have)\b.{0,90}\b(?:staff|order|booking|request|notified|confirmed)",
    r"\b(?:woh|ve|staff|reception|front.desk)\b.{0,95}\b(?:bhej denge|arrange kar denge|turant action lenge)",
]


def unverified_promise(reply):
    msg = " ".join(str(reply or "").lower().split())
    for rule in _UNVERIFIED_PROMISE:
        match = re.search(rule, msg)
        if not match:
            continue
        around = msg[max(0, match.start()-30):match.end()+20]
        # Do not reject truthful negative statements about disabled actions.
        if re.search(r"\b(?:nahi|nahin|nhi|not|never|cannot|can't|disabled)\b", around):
            continue
        return True
    return False


def _message_text(bot, message, msg_type):
    if msg_type == "text":
        return str((message.get("text") or {}).get("body") or "").strip()
    if msg_type == "interactive":
        choice = message.get("interactive") or {}
        selected = choice.get("button_reply") or choice.get("list_reply") or {}
        return str(selected.get("title") or "").strip()
    if msg_type == "button":
        return str((message.get("button") or {}).get("text") or "").strip()
    if msg_type == "reaction":
        return str((message.get("reaction") or {}).get("emoji") or "").strip()
    if msg_type == "audio":
        media_id = str((message.get("audio") or {}).get("id") or "").strip()
        mime = str((message.get("audio") or {}).get("mime_type") or "audio/ogg")
        if not media_id:
            return ""
        audio = bot.download_whatsapp_media(media_id)
        if not audio:
            return ""
        return str(bot.transcribe_audio_gemini(audio, mime) or
                   bot.transcribe_audio_groq(audio, mime) or "").strip()
    return ""


def process(bot, message, sender_phone, msg_type):
    """Call one plain language AI gateway; never invoke hotel operations."""
    message = message if isinstance(message, dict) else {}
    # Reception messages are never processed as new guest prompts.
    if reception_learning.handle_operator_message(bot, message, sender_phone, msg_type):
        return True
    if msg_type == "image":
        return bot.send_whatsapp_message(
            sender_phone,
            "Photo mil gayi ji, lekin is test mein main image dekh nahi sakti. "
            "Aap apna sawaal text mein bata dein."
        )

    text = _message_text(bot, message, msg_type)
    if not text:
        return bot.send_whatsapp_message(
            sender_phone,
            "Aap apna sawaal text ya clear voice note mein bhej sakte hain ji."
        )

    # A previously verified generic hotel fact should not be asked again.
    known = reception_learning.cached_answer(bot, text)
    if known:
        sent = bot.send_whatsapp_message(sender_phone, known)
        if sent:
            bot.remember_conversation(sender_phone, "user", text)
            bot.remember_conversation(sender_phone, "assistant", known)
        return sent

    # One natural AI response; Python only transports the optional escalation.
    raw = bot.ask_ai_chat(text, None, sender_phone, structured=False)
    reply = bot._ai_content_is_usable(raw, "Knowledge only") if raw else ""
    reply = str(reply or "").strip()
    # Some fallback providers may disregard free-text instructions and return
    # the old one-field JSON reply envelope. Only unwrap, never execute it.
    if reply.startswith("{") and reply.endswith("}"):
        try:
            parsed = json.loads(reply)
            reply = str(parsed.get("reply") or "").strip() if isinstance(parsed, dict) else ""
        except ValueError:
            reply = ""
    if not reply:
        reply = ("Abhi AI se sahi jawab nahi mil pa raha ji. "
                 "Is chat mein koi hotel request ya action nahi kiya gaya.")

    reply, uncertainty = reception_learning.extract_handoff(reply)
    if uncertainty:
        result = reception_learning.forward_unknown(bot, sender_phone, text, uncertainty)
        acknowledgement = {
            "sent": "Ji, ye sawaal reception ko bhej diya hai. Unka jawab aane par yahin forward kar dungi.",
            "pending": "Ji, ye sawaal pehle se reception ke paas hai. Unka jawab milne par yahin forward kar dungi.",
            "failed": "Ji, abhi reception ko WhatsApp par message nahi pahunch paaya. Kripya front desk se seedha sampark karein.",
        }[result]
        outgoing = (reply + "\n\n" + acknowledgement).strip() if reply else acknowledgement
        sent = bot.send_whatsapp_message(sender_phone, outgoing)
        if sent:
            bot.remember_conversation(sender_phone, "user", text)
            bot.remember_conversation(sender_phone, "assistant", outgoing)
        return sent

    if unverified_promise(reply):
        print("KNOWLEDGE ONLY: unverified real-world action promise blocked", flush=True)
        reply = ("Ji, is test chat se staff ko koi request forward nahi hoti aur "
                 "koi order ya booking confirm nahi hoti. Zaroorat ho toh "
                 "hotel reception se seedha sampark karein.")

    sent = bot.send_whatsapp_message(sender_phone, reply)
    if sent:
        bot.remember_conversation(sender_phone, "user", text)
        bot.remember_conversation(sender_phone, "assistant", reply)
    return sent
