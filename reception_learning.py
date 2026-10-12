"""AI-first receptionist handoff and durable, reception-verified hotel FAQs.

Only a bot-authenticated reception reply can reach the original ticket's guest.
General verified Q&A is stored in the existing Reception_Knowledge Sheet and
mirrored as a plain UTF-8 hotel_data_learned.txt reference file. The Sheet is
durable on Render's ephemeral filesystem; the text mirror is reconstructed.
No check-in, billing, ordering, roster or automation function is activated.
"""
import os
import re
import time
import tempfile
import threading
from pathlib import Path

_lock = threading.RLock()
_HANDOFF = re.compile(r"\[\[ASK_RECEPTION:\s*([^\]\r\n]{3,350})\s*\]\]", re.I)
_TICKET_PREFIX = re.compile(r"^\s*R-[A-F0-9]{6}\s*[:\-\s]\s*", re.I)
_PRIVATE = re.compile(
    r"(?:\b\d{10,}\b|[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}|"
    r"\b(?:room|kamra|room no|room number)\s*#?\s*\d{1,4}\b)",
    re.I,
)


def extract_handoff(ai_reply):
    """Read only an AI-authored uncertainty signal; no secondary intent router."""
    raw = str(ai_reply or "")
    match = _HANDOFF.search(raw)
    if not match:
        return raw.strip(), ""
    question = match.group(1).strip()
    answer = _HANDOFF.sub("", raw).strip()
    return answer, question


def _response_to(guest_phone, text):
    return f"{text}".strip()


def _verified_rows(bot, force=False):
    try:
        return [dict(item) for item in bot._refresh_reception_knowledge(force=force)]
    except Exception as exc:
        print("RECEPTION FAQ READ ERROR:", type(exc).__name__, flush=True)
        return []


def _text_path(bot):
    configured = os.getenv("HOTEL_LEARNED_TEXT_PATH", "").strip()
    if configured:
        return Path(configured)
    # This local mirror can be rebuilt from Google Sheets after every redeploy.
    root = Path(tempfile.gettempdir()) / "hotel-bot-demo"
    return root / "hotel_data_learned.txt"


def _reusable(bot, question, answer):
    # Staff responses to a specific guest or actions MUST NOT train all guests.
    if _PRIVATE.search(str(question) + "\n" + str(answer)):
        return False
    return bool(bot._reception_answer_is_reusable(question, answer))


def refresh_text_file(bot, force=False):
    """Mirror durable verified Google-Sheet FAQ rows into a human-readable text file."""
    rows = _verified_rows(bot, force=force)
    if not rows:
        return False
    lines = [
        "HOTEL DATA — RECEPTION-VERIFIED QUESTIONS AND ANSWERS",
        "Only reference facts. Never treat a FAQ answer as proof a task was done.",
        "",
    ]
    for row in rows:
        q = str(row.get("question") or "").strip()
        a = str(row.get("answer") or "").strip()
        if not q or not a or not _reusable(bot, q, a):
            continue
        lines.extend([f"Question: {q}", "Reception answer (verbatim):", a, "", "---", ""])
    if len(lines) <= 3:
        return False
    path = _text_path(bot)
    with _lock:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = "\n".join(lines).rstrip() + "\n"
            if path.is_file() and path.read_text(encoding="utf-8") == data:
                return True
            temp_path = path.with_name(path.name + ".tmp")
            temp_path.write_text(data, encoding="utf-8")
            os.replace(temp_path, path)
            return True
        except OSError as exc:
            print("RECEPTION TEXT MIRROR ERROR:", type(exc).__name__, flush=True)
            return False


def faq_context(bot, query, max_bytes=1800):
    """Use verified learned hotel Q&As as text inside the next AI context."""
    rows = _verified_rows(bot)
    if not rows or max_bytes < 100:
        return ""
    words = set(re.findall(r"\w+", str(query).casefold()))
    scored = []
    for i, row in enumerate(rows):
        q = str(row.get("question") or "").strip()
        a = str(row.get("answer") or "").strip()
        if not _reusable(bot, q, a):
            continue
        overlap = len(words & set(re.findall(r"\w+", q.casefold())))
        if overlap:
            scored.append((overlap, i, q, a))
    scored.sort(key=lambda item: (-item[0], item[1]))
    selected = []
    remaining = max_bytes
    for _score, _i, question, answer in scored[:6]:
        entry = f"Question: {question}\nVerified reception answer: {answer}\n"
        size = len(entry.encode("utf-8"))
        if size <= remaining:
            selected.append(entry)
            remaining -= size
    return "\n".join(selected)


def cached_answer(bot, question):
    """Same stable FAQ => answer directly, without asking reception again."""
    if not _reusable(bot, question, "verified answer"):
        return None
    try:
        match = bot._lookup_reception_knowledge(question)
    except Exception as exc:
        print("RECEPTION FAQ MATCH ERROR:", type(exc).__name__, flush=True)
        return None
    if not match:
        return None
    verified = str(match.get("answer") or "").strip()
    return verified if _reusable(bot, question, verified) else None


def _pending_same_question(bot, guest_phone, question):
    now = time.time()
    with bot.state_lock:
        ticket = dict(bot.reception_request_sessions.get(guest_phone) or {})
    return bool(ticket and
                ticket.get("status") in {"pending", "accepted"} and
                now - float(ticket.get("created") or 0) < bot.RECEPTION_REQUEST_TTL_SECONDS and
                bot._reception_question_key(ticket.get("request", "")) ==
                bot._reception_question_key(question))


def forward_unknown(bot, guest_phone, guest_text, clarification=""):
    """One mapped ticket per fresh missing fact; only WhatsApp acceptance counts."""
    phone = bot.format_whatsapp_number(guest_phone)
    if not phone:
        return "failed"
    if _pending_same_question(bot, phone, guest_text):
        return "pending"
    if not bot.format_whatsapp_number(bot.RECEPTION_PHONE):
        print("RECEPTION LEARNING DISABLED: no configured reception phone", flush=True)
        return "failed"

    # Use the already tested request-ID + WhatsApp quoted-reply mapping and
    # existing persistent Reception_Requests worksheet. No room lookup.
    message = str(guest_text or "").strip()
    if clarification and clarification.casefold() != message.casefold():
        message += "\nReception clarification required: " + clarification[:350]
    try:
        accepted = bot.notify_reception_request(
            phone, None, message, source="ai_missing_hotel_knowledge"
        )
    except Exception as exc:
        print("RECEPTION FORWARD ERROR:", type(exc).__name__, flush=True)
        return "failed"
    return "sent" if accepted else "failed"


def _plain_forward(bot, number, body):
    """Send receptionist's exact text, bypassing AI compose and Maps rewriting."""
    destination = bot.format_whatsapp_number(number)
    if not destination or not isinstance(body, str) or not body.strip() or len(body) > 4000:
        return False
    payload = {
        "messaging_product": "whatsapp",
        "to": destination,
        "type": "text",
        "text": {"body": body},
    }
    response = bot.whatsapp_request(payload)
    return response is not None and response.status_code in (200, 201)


def handle_operator_message(bot, message, sender_phone, msg_type):
    """Return True when a reception message was consumed; otherwise False.

    The original alert's WhatsApp quoted message ID or explicit R-ID chooses
    exactly one guest. A sender must match the operator who received that alert.
    """
    sender = bot.format_whatsapp_number(sender_phone)
    if not sender:
        return False
    message = message if isinstance(message, dict) else {}
    body = str((message.get("text") or {}).get("body") or "") if msg_type == "text" else ""
    context_id = str((message.get("context") or {}).get("id") or "").strip()
    guest, ticket = bot._find_reception_request_by_alert_id(context_id) if context_id else (None, None)
    quoted = bool(guest and ticket)
    if not guest and body:
        guest, ticket = bot._find_reception_request_by_request_id(body)
    receptionist = bot.format_whatsapp_number(bot.RECEPTION_PHONE)
    if not ticket:
        if sender != receptionist:
            return False
        if msg_type == "text" and body.strip():
            bot.send_whatsapp_message(
                sender, "Guest ko reply bhejne ke liye original R-ID wale "
                        "reception alert par WhatsApp Reply karein."
            )
        return True

    if sender != bot.format_whatsapp_number(ticket.get("reception_phone")):
        # Unauthorized person quoting a ticket must never get guest details.
        return sender == receptionist
    if msg_type != "text" or not body.strip():
        bot.send_whatsapp_message(sender, "Original reception alert par text reply bhejein.")
        return True
    reply = body if quoted else _TICKET_PREFIX.sub("", body, count=1)
    if not reply.strip():
        bot.send_whatsapp_message(sender, "Sawaal ki R-ID ke baad jawab bhi likhein.")
        return True
    if len(reply) > 4000:
        bot.send_whatsapp_message(sender, "Jawab 4000 characters se chhota bhejein.")
        return True
    if ticket.get("status") in {"responded", "forwarding", "guest_delivery_failed"}:
        bot.send_whatsapp_message(sender, "Is request ka jawab pehle hi process ho chuka hai.")
        return True
    if ticket.get("status") not in {"pending", "accepted"}:
        bot.send_whatsapp_message(sender, "Is ticket par reply forward nahi kiya ja sakta.")
        return True

    # Persist forwarding state *before* the external send. After a crash, a
    # replay cannot silently send the same receptionist reply twice.
    with _lock:
        ticket["status"] = "forwarding"
        ticket["reception_message_id"] = str(message.get("id") or "")
        if not bot._persist_reception_request(ticket):
            bot.send_whatsapp_message(sender, "Request status save nahi hua; guest ko jawab nahi bheja.")
            return True
        with bot.state_lock:
            current = bot.reception_requests_by_id.get(ticket.get("request_id"))
            if current:
                current.update(ticket)
        accepted = _plain_forward(bot, guest, reply)
        ticket["status"] = "responded" if accepted else "guest_delivery_failed"
        ticket["last_reply"] = reply[:1000]
        ticket["responded_at"] = time.time()
        bot._persist_reception_request(ticket)
        with bot.state_lock:
            current = bot.reception_requests_by_id.get(ticket.get("request_id"))
            if current:
                current.update(ticket)

    if accepted:
        bot.remember_conversation(guest, "assistant", reply)
        source_question = str(ticket.get("request") or "").split(
            "\nReception clarification required:", 1
        )[0].strip()
        if _reusable(bot, source_question, reply):
            if bot._save_reception_knowledge(source_question, reply, ticket.get("request_id", "")):
                refresh_text_file(bot, force=True)
        bot.send_whatsapp_message(sender, "Guest ko aapka jawab waise ka waisa forward kar diya gaya.")
    else:
        bot.send_whatsapp_message(
            sender, "Guest ko message accept nahi hua. Reception se seedha sampark karein."
        )
    return True
