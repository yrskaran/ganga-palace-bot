"""Temporary knowledge-only WhatsApp conversation, with no hotel tool execution.

This module intentionally does not import service, check-in, order, reception,
bill, spreadsheet, or notification handlers. The normal transport, deduplication
and per-sender conversation history remain available.
"""
import json
import os
import re
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
    name_match = re.search(r"(?im)^\\s*-\\s*Name\\s*:\\s*(.+?)\\s*$", raw)
    hotel_name = name_match.group(1).strip() if name_match else "Hotel"
    return raw, hotel_name


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

    # No JSON plan, reviewer, tool dispatcher or sheet/guest-state lookup.
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

    sent = bot.send_whatsapp_message(sender_phone, reply)
    if sent:
        bot.remember_conversation(sender_phone, "user", text)
        bot.remember_conversation(sender_phone, "assistant", reply)
    return sent
