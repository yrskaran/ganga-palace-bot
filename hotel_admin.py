"""Read-only chat monitor and authorized room cleaning; no model calls."""
import csv
import hmac
import io
import json
import os
import re
import threading
from datetime import datetime, timezone
from functools import wraps

from flask import Response, jsonify, request, render_template

cleaning_lock = threading.Lock()


def handle_cleaning(bot, message, sender, msg_type):
    if msg_type != 'text':
        return False
    text = str((message.get('text') or {}).get('body', '')).strip()
    match = re.fullmatch(r'(?:room\s+)?([0-9]{1,5}[A-Za-z]?)\s+clean', text, re.I)
    if not match:
        return False
    room = bot.clean_room(match[1])
    # Require a fresh roster: stale/off-duty staff cannot change hotel records.
    if not bot.refresh_staff_roster(force=True):
        bot.send_whatsapp_message(sender, 'Staff list abhi verify nahi ho rahi. Thodi der mein dobara bhejein; room status update nahi hua.')
        return True
    staff = bot.find_on_duty_staff(room, 'Housekeeping')
    reception = bot.is_on_duty_staff_phone(sender, 'Reception')
    if not reception and (not staff or bot.format_whatsapp_number(staff['phone']) != bot.format_whatsapp_number(sender)):
        bot.send_whatsapp_message(sender, 'Is room ka cleaning status sirf assigned on-duty housekeeping ya reception update kar sakta hai.')
        return True
    actor = staff['name'] if staff and bot.format_whatsapp_number(staff['phone']) == bot.format_whatsapp_number(sender) else 'Reception'
    try:
        with cleaning_lock:
            sheet = bot.get_gspread_client().open_by_key(bot.SHEET_ID).get_worksheet(0)
            rows = sheet.get_all_values()
            if not rows:
                raise ValueError('Rooms sheet is empty')
            headers = list(rows[0])
            columns = bot.room_columns(headers)
            room_col = columns.get('room')
            if room_col is None or room_col < 0:
                raise ValueError('Room header missing')
            matches = [i + 1 for i, row in enumerate(rows[1:], start=1)
                       if len(row) > room_col and bot.clean_room(row[room_col]) == room]
            if len(matches) != 1:
                bot.send_whatsapp_message(sender, f'Room {room} ka unique record nahi mila. Reception se room number check kar lein; status update nahi hua.')
                return True
            target = matches[0]
            updates = []
            # Append named fields after all existing data, preserving booking/payment columns.
            next_col = max(map(len, rows))
            for name, value in [('Cleaning Status', 'CLEAN'), ('Cleaned By', actor),
                                ('Cleaned At', bot.now_ist().isoformat()), ('Cleaning Message ID', str(message.get('id', '')))]:
                found = [i for i, header in enumerate(headers) if bot.normalize_text(header) == bot.normalize_text(name)]
                if len(found) > 1:
                    raise ValueError('Duplicate cleaning header')
                if found:
                    col = found[0]
                else:
                    col = next_col
                    next_col += 1
                    updates.append({'range': f'{column_name(col)}1', 'values': [[name]]})
                if name == 'Cleaning Message ID' and value and len(rows[target-1]) > col and rows[target-1][col] == value:
                    bot.send_whatsapp_message(sender, f'Room {room} ka clean update pehle hi save ho chuka hai.')
                    return True
                updates.append({'range': f'{column_name(col)}{target}', 'values': [[value]]})
            if next_col > sheet.col_count:
                sheet.add_cols(next_col - sheet.col_count)
            sheet.batch_update(updates, value_input_option='RAW')
    except Exception as exc:
        # A timed-out write may have succeeded remotely; never automatically replay it.
        print('ROOM CLEANING CHECK REQUIRED:', type(exc).__name__, flush=True)
        bot.send_whatsapp_message(sender, f'Room {room} ka update confirm nahi ho paaya. Dobara bhejne se pehle Sheet mein status check kar lein.')
        return True
    bot.send_whatsapp_message(sender, f'Room {room} clean mark kar diya hai. Sheet update ho gayi.')
    return True


def column_name(index):
    result = ''
    index += 1
    while index:
        index, digit = divmod(index - 1, 26)
        result = chr(65 + digit) + result
    return result


def message_text(payload):
    kind = payload.get('type', '')
    if kind == 'text':
        return (payload.get('text') or {}).get('body', '')
    if kind == 'interactive':
        data = payload.get('interactive') or {}
        choice = data.get('button_reply') or data.get('list_reply') or {}
        return choice.get('title', '[interactive message]')
    if kind == 'button':
        return (payload.get('button') or {}).get('text', '[button]')
    # Never expose media access tokens/URLs or downloaded identity documents.
    return '[' + (kind or 'message') + ']'


def read_messages(store, phone='', limit=200, offset=0):
    with store.db() as db:
        rows = db.execute('''SELECT * FROM (
            SELECT 'in:' || id AS id, sender AS phone, body, state AS status,
                   created AS timestamp, 'incoming' AS direction, 0 AS estimated_time FROM inbox
            UNION ALL
            SELECT 'out:' || id, json_extract(body, '$.to'), body, state,
                   COALESCE(created, updated), 'outgoing', created IS NULL FROM outbox
            WHERE json_extract(body, '$.status') IS NULL
        ) WHERE (? = '' OR phone = ?) ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?''',
                          (phone, phone, limit, offset)).fetchall()
    return [{'id': row['id'], 'phone': row['phone'], 'direction': row['direction'],
             'status': row['status'], 'time': datetime.fromtimestamp(row['timestamp'], timezone.utc).isoformat(),
             'estimated_time': bool(row['estimated_time']),
             'text': message_text(json.loads(row['body']))} for row in rows]


def csv_safe(value):
    value = str(value or '')
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else value


def register(bot):
    def authorized(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            password = os.getenv('HOTEL_ADMIN_PASSWORD', '')
            if not password:
                response = jsonify(error='Chat monitor disabled: set HOTEL_ADMIN_PASSWORD.')
                response.status_code = 503
            else:
                auth = request.authorization
                if not auth or not hmac.compare_digest((auth.username or '').encode(), os.getenv('HOTEL_ADMIN_USER', 'admin').encode()) or not hmac.compare_digest((auth.password or '').encode(), password.encode()):
                    response = Response('Admin login required', 401, {'WWW-Authenticate':'Basic realm="Hotel chat monitor"'})
                else:
                    response = bot.app.make_response(fn(*args, **kwargs))
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['X-Frame-Options'] = 'DENY'
            response.headers['Referrer-Policy'] = 'no-referrer'
            return response
        return wrapped

    @bot.app.get('/admin')
    @authorized
    def hotel_dashboard():
        return render_template('chat_monitor.html', hotel=bot.get_hotel_name())

    @bot.app.get('/admin/chats')
    @authorized
    def hotel_chats():
        if not bot.durable_store:
            return jsonify(error='Chat storage is not started. Run python serve.py.'), 503
        phone = request.args.get('phone', '').strip()
        try:
            offset = max(0, int(request.args.get('offset', 0)))
        except ValueError:
            return jsonify(error='Invalid offset'), 400
        return jsonify(messages=read_messages(bot.durable_store, phone, 200, offset),
                       storage_mode=os.getenv('BOT_STORAGE_MODE', 'demo'),
                       warning='Demo storage may reset on restart. Download chats before redeploying.' if os.getenv('BOT_STORAGE_MODE', 'demo') == 'demo' else '')

    @bot.app.get('/admin/chats.csv')
    @authorized
    def hotel_chat_download():
        if not bot.durable_store:
            return jsonify(error='Chat storage unavailable'), 503
        phone = request.args.get('phone', '').strip()
        # Consistent snapshot: export includes every stored message, not just the dashboard page.
        with bot.durable_store.db() as db:
            db.execute('BEGIN')
            rows = db.execute('''SELECT * FROM (
                SELECT sender phone, body, state status, created stamp, 'incoming' direction, 0 estimated_time FROM inbox
                UNION ALL SELECT json_extract(body,'$.to'), body, state, COALESCE(created,updated), 'outgoing', created IS NULL FROM outbox
                WHERE json_extract(body,'$.status') IS NULL
            ) WHERE (?='' OR phone=?) ORDER BY stamp''', (phone, phone)).fetchall()
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(['Time (UTC)', 'Phone', 'Direction', 'Status', 'Message', 'Time source'])
        for row in rows:
            writer.writerow([datetime.fromtimestamp(row['stamp'], timezone.utc).isoformat(),
                             csv_safe(row['phone']), row['direction'], row['status'],
                             csv_safe(message_text(json.loads(row['body']))),
                             'Legacy last activity' if row['estimated_time'] else 'Recorded creation'])
        return Response('\ufeff' + output.getvalue(), mimetype='text/csv; charset=utf-8',
                        headers={'Content-Disposition': 'attachment; filename="hotel-chats.csv"'})
