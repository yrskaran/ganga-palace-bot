"""Opt-in demo menu, confirmed food orders and per-phone bills in Demo_Orders.

No Rooms/Kitchen_Orders writes, staff notifications, payment or real fulfilment.
"""
import re
import threading
import time
from uuid import uuid4

from gspread.exceptions import WorksheetNotFound

HEADERS = ['Demo Order ID', 'Created At', 'Phone', 'Room', 'Items', 'Food Total', 'Status']
lock = threading.RLock()


def worksheet(bot, create=False):
    client = bot.get_gspread_client()
    if client is None:
        raise RuntimeError('Google Sheets is not connected')
    book = client.open_by_key(bot.SHEET_ID)
    try:
        sheet = book.worksheet('Demo_Orders')
    except WorksheetNotFound:
        if not create:
            return None
        sheet = book.add_worksheet(title='Demo_Orders', rows=1000, cols=len(HEADERS))
    rows = sheet.get_all_values()
    if not rows:
        if not create:
            # An untouched demo tab has no confirmed orders to bill yet.
            return None
        # Verify newly initialized headers before writing the first order.
        sheet.update(range_name='A1', values=[HEADERS], value_input_option='RAW')
        rows = sheet.get_all_values()
        if not rows or rows[0][:len(HEADERS)] != HEADERS:
            raise RuntimeError('Demo_Orders header setup could not be verified')
    elif rows[0][:len(HEADERS)] != HEADERS:
        # Leave unexpected existing tab contents untouched.
        raise ValueError('Demo_Orders headers do not match; existing data preserved')
    return sheet


def lines(items):
    return '\n'.join(f"{x['qty']} x {x['name']} @ Rs. {x['unit_price']} = Rs. {x['amount']}" for x in items)


def pending_state(bot, pending):
    if bot.durable_store is None:
        raise RuntimeError('Start with python serve.py for durable confirmations')
    return bot.durable_store.order(pending['id'], pending)


def save(bot, phone, pending):
    state = pending_state(bot, pending)
    sheet = worksheet(bot, create=True)
    rows = sheet.get_all_values()[1:]
    matches = [row for row in rows if row and row[0] == pending['id']]
    if matches:
        if len(matches) != 1 or len(matches[0]) < len(HEADERS) or matches[0][2] != phone or matches[0][4] != lines(pending['items']) or matches[0][5] != str(pending['total']) or matches[0][6] != 'DEMO_CONFIRMED':
            raise ValueError('Demo order needs reconciliation')
        bot.durable_store.order_state(pending['id'], 'saved')
        return
    if state in {'saved', 'sending', 'unknown'} or not bot.durable_store.claim_order(pending['id']):
        raise RuntimeError('Uncertain Sheet write; do not append again')
    row = [pending['id'], bot.now_ist().isoformat(), phone, 'DEMO',
           lines(pending['items']), pending['total'], 'DEMO_CONFIRMED']
    try:
        sheet.append_row(row, value_input_option='RAW')
    except Exception:
        bot.durable_store.order_state(pending['id'], 'unknown')
        raise
    bot.durable_store.order_state(pending['id'], 'saved')


def bill(bot, phone):
    sheet = worksheet(bot)
    rows = sheet.get_all_values()[1:] if sheet is not None else []
    total = 0
    details = []
    ids = set()
    for row in rows:
        if len(row) < 3 or row[2] != phone:
            continue
        if len(row) < len(HEADERS) or row[6] != 'DEMO_CONFIRMED' or row[0] in ids:
            raise ValueError('Demo order rows need review')
        ids.add(row[0])
        amount = int(row[5])
        if amount < 0:
            raise ValueError('Invalid demo amount')
        total += amount
        details.append(row[4])
    text = 'DEMO food bill\n' + ('\n\n'.join(details) if details else 'No confirmed food orders yet.')
    return text + f'\n\nFood total: Rs. {total}\nSample bill only — no payment required.'


def handle(bot, phone, text):
    if not bot.CUSTOMER_DEMO_MODE or not (bot.CUSTOMER_CONFIG or {}).get('demo_food_enabled'):
        return False
    phone = bot.format_whatsapp_number(phone)
    if not phone:
        return False
    normalized = bot.normalize_text(text)
    say = lambda message: bot.send_whatsapp_message(phone, message)
    with lock:
        pending = bot.demo_food_sessions.get(phone)
        if pending and time.time() - pending['created'] > 600:
            if pending_state(bot, pending) == 'prepared':
                bot.demo_food_sessions.pop(phone, None)
                pending = None
        if re.search(r'\b(?:bill|invoice|hisaab|hisab)\b|बिल|हिसाब', normalized) or normalized in {'total', 'kitna hua', 'total kitna hua', 'food total'}:
            try:
                say(bill(bot, phone))
            except Exception as exc:
                print('DEMO BILL UNAVAILABLE:', type(exc).__name__, flush=True)
                say('Demo bill abhi Sheet se verify nahi ho pa raha. Thodi der mein dobara poochhein; main total guess nahi karungi.')
            return True
        if re.search(r'\bmenu\b|मेन्यू|मेनू', normalized):
            menu = (bot.CUSTOMER_CONFIG or {}).get('menu', [])
            if not menu:
                say('DEMO food menu abhi configure nahi hua hai. Is waqt koi sample item ya price available nahi hai.')
                return True
            say('Ji, ye raha poora DEMO menu 🙂 (sample rates, hotel ke actual rates nahi):\n\n' +
                '\n'.join(f"• {x['name']} — ₹{x['price']}" for x in menu) +
                '\n\nJo pasand ho, quantity ke saath likh dijiye, jaise 2 Masala Chai aur 1 Poha. Confirm karne ke baad sirf demo Sheet mein entry hogi, kitchen ko order nahi jayega.')
            return True
        if pending and bot.is_yes(text):
            try:
                save(bot, phone, pending)
            except Exception as exc:
                print('DEMO ORDER CHECK REQUIRED:', type(exc).__name__, flush=True)
                say('Demo order ka Sheet update confirm nahi ho paaya. Cart rakha hai; Sheet verify hone tak naya order mat banayein. CONFIRM dobara bhejne par pehle usi entry ko check karungi.')
                return True
            bot.demo_food_sessions.pop(phone, None)
            say(f"Demo order save ho gaya — Rs. {pending['total']}. Demo_Orders Sheet mein entry hai. 'Bill' likhein toh item-wise total bata doon. Yeh test order hai, real delivery nahi hogi.")
            return True
        if pending and bot.is_no(text):
            if pending_state(bot, pending) in {'sending', 'unknown', 'saved'}:
                say('Is demo entry ka Sheet status pehle verify karna hoga; abhi cancellation confirm nahi kar sakti.')
            else:
                bot.demo_food_sessions.pop(phone, None)
                say('Theek hai, pending demo order hata diya. Is cart ki Sheet entry nahi bani.')
            return True
        # A generic 'haan', 'ji' or 'okay' without a demo cart belongs to the
        # normal concierge conversation, not the food-order handler.
        if normalized in {'confirm', 'confirmed', 'yes confirm', 'haan confirm'}:
            say('Abhi koi demo order confirmation pending nahi hai. Menu se items aur quantity bhej dein.')
            return True
        parsed = bot.find_menu_items(text)
        foodish = bool(parsed.get('items') or parsed.get('generic') or parsed.get('invalid')) or bool(re.search(r'\b(?:order|food|khana|cancel)\b', normalized))
        if not foodish:
            return False
        # No silent partial basket, fractional/negative quantities or negated order.
        if re.search(r'\b(?:nahi|nahin|not|dont|don.t|cancel|mat)\b|नहीं|मत|(?<!\w)-\s*\d|\d+\.\d+', normalized):
            say('Naya demo order nahi banaya. Items badalne hain toh poora order quantity ke saath bhejein; pending cart hatane ke liye CANCEL likhein.')
            return True
        if bot.explicitly_asks_price(text):
            if parsed.get('items'):
                say('DEMO prices\n' + lines(parsed['items']) + f"\nSample total: Rs. {parsed['total']}\nOrder banana ho toh items aur quantity bhejein.")
            else:
                say('Sample prices ke liye MENU bhejein.')
            return True
        # Reuse the exact configured-menu parser, stripping only order-request phrasing.
        basket = re.sub(r"\b(?:i would like|i want|can i get|bhej do|bhijwa do|bhejna|bhijwao?|send|bring|mangwao?|de do|la do|kar do)\b", ' ', normalized)
        parsed = bot.find_menu_items(basket)
        if not parsed.get('complete') or parsed.get('invalid') or parsed.get('generic'):
            say('Demo order clear nahi hua. MENU mein listed exact items aur quantity bhejein, jaise 2 Masala Chai aur 1 Poha. Abhi koi entry nahi bani.')
            return True
        if pending and pending_state(bot, pending) in {'sending', 'unknown', 'saved'}:
            say('Pichhle demo order ki Sheet entry pehle verify karni hai. CONFIRM bhejein; abhi naya cart nahi banaungi.')
            return True
        pending = {'id':'DEMO-' + uuid4().hex, 'created':time.time(),
                   'items':parsed['items'], 'total':parsed['total'], 'phone':phone}
        bot.demo_food_sessions[phone] = pending
        say('Demo order note kiya:\n' + lines(pending['items']) +
            f"\nFood total: Rs. {pending['total']}\nCONFIRM kar dein toh Demo_Orders Sheet mein save kar doon; CANCEL se hata sakte hain. Real kitchen order nahi jayega.")
        return True
