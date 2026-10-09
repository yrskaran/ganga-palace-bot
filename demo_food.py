"""Opt-in demo menu, confirmed food orders and per-phone bills in Demo_Orders.

No Rooms/Kitchen_Orders writes, staff notifications, payment or real fulfilment.
"""
import re
from difflib import SequenceMatcher
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



def menu_category(name):
    """Categories are presentation only: order prices always come from config."""
    name = str(name or '').lower().strip()
    if any(word in name for word in ('chai', 'coffee', 'lassi', 'milk', 'water')):
        return 'Drinks'
    if any(word in name for word in ('toast', 'poha', 'chilla', 'paratha', 'puri bhaji', 'chole bhature')):
        return 'Breakfast'
    if any(word in name for word in ('pakoda', 'fries', 'sandwich', 'maggi')):
        return 'Snacks'
    if any(word in name for word in ('roti', 'naan')):
        return 'Breads'
    if any(word in name for word in ('rice', 'pulao')):
        return 'Rice'
    if any(word in name for word in ('raita', 'salad', 'thali')):
        return 'Sides & Thali'
    return 'Main Course'


MENU_GROUPS = [
    ('Breakfast', '☀️', 'Breakfast'),
    ('Drinks', '☕', 'Beverages'),
    ('Snacks', '🥪', 'Snacks & Light Bites'),
    ('Main Course', '🍲', 'Main Course'),
    ('Breads', '🫓', 'Breads'),
    ('Rice', '🍚', 'Rice'),
    ('Sides & Thali', '🥗', 'Sides & Thali'),
]


def meal_request(text):
    """Handle meal recommendations, but do not misroute timing or food orders."""
    t = str(text or '').lower().strip()
    if re.search(r'\b(?:time|timing|kab|baje|hours|open|close)\b|कब|समय|बजे', t):
        return None
    # A quantity + meal name is more likely an order than a menu request.
    if re.search(r'\d', t) and not re.search(r'\bmenu\b|मेन्यू|मेनू', t):
        return None
    matchers = (
        ('BREAKFAST', r'\b(?:breakfast|nashta|nasta|naashta)\b|नाश्ता|नास्ता'),
        ('LUNCH', r'\b(?:lunch|dopahar ka khana)\b|दोपहर का खाना|लंच'),
        ('DINNER', r'\b(?:dinner|raat ka khana)\b|रात का खाना|डिनर'),
    )
    for key, pattern in matchers:
        if re.search(pattern, t, re.I):
            return key
    return None


def menu_messages(bot, meal=None, include_prices=False):
    """Pretty WhatsApp menus from the *same* configured price list used by orders."""
    config = bot.CUSTOMER_CONFIG or {}
    menu = config.get('menu') or []
    if not menu:
        return ['DEMO food menu abhi configure nahi hua hai. Is waqt koi sample item ya price available nahi hai.']

    grouped = {key: [] for key, _, _ in MENU_GROUPS}
    for item in menu:
        if not isinstance(item, dict) or not item.get('name'):
            continue
        group = menu_category(item['name'])
        grouped[group].append(item)

    hotel = (config.get('hotel') or {}).get('name') or 'Hotel'
    headings = {
        'BREAKFAST': ('☀️', 'Breakfast', ['Breakfast', 'Drinks']),
        'LUNCH': ('🍛', 'Lunch', ['Main Course', 'Breads', 'Rice', 'Sides & Thali']),
        'DINNER': ('🌙', 'Dinner', ['Main Course', 'Breads', 'Rice', 'Sides & Thali']),
    }
    if meal in headings:
        icon, title, keys = headings[meal]
        intro = f'{icon} *{hotel}*\n*{title} Menu*'
        intro += '\n_DEMO • sample menu_'
        compact_divider = '──────────────'
        groups_for_meal = []
        if meal == 'DINNER':
            # Keep the familiar vegetarian paratha option in dinner.
            extras = [x for x in grouped['Breakfast']
                      if 'mix veg paratha' in x['name'].lower()]
            if extras:
                groups_for_meal.append(('🫓', 'Special Paratha', extras))
        for key, symbol, group_title in MENU_GROUPS:
            if key in keys and grouped[key]:
                clean_title = {
                    'Main Course': 'Sabzi & Dal',
                    'Breads': 'Roti & Naan',
                    'Rice': 'Rice',
                    'Sides & Thali': 'Raita, Salad & Thali',
                    'Breakfast': 'Breakfast',
                    'Drinks': 'Tea & Drinks',
                }.get(key, group_title)
                groups_for_meal.append((symbol, clean_title, grouped[key]))

        def card_body(groups):
            return '\n\n'.join(
                f'{symbol} *{name}*\n' +
                (bot._whatsapp_price_block([(x['name'], x['price']) for x in entries])
                 if include_prices else
                 '\n'.join(_menu_item(x, False) for x in entries))
                for symbol, name, entries in groups
            )

        example = '2 Poha + 1 Masala Chai' if meal == 'BREAKFAST' else '2 Butter Naan + 1 Dal Tadka'
        invitation = (
            '📝 *Kuch order karna hai?* 😊\n'
            'Item aur quantity likh dijiye.\n'
            f'Jaise: {example}\n'
            '_Demo order only • kitchen mein nahi jayega._'
        )

        if meal == 'BREAKFAST':
            # Breakfast fits naturally in one tidy card.
            return [intro + '\n' + compact_divider + '\n\n'
                    + card_body(groups_for_meal) + '\n\n'
                    + compact_divider + '\n' + invitation]

        # Keep lunch and dinner scannable on a phone: two small cards
        # rather than a wall of 20+ dishes. Same items, no duplicates.
        mains = [g for g in groups_for_meal
                 if g[1] in {'Special Paratha', 'Sabzi & Dal'}]
        sides = [g for g in groups_for_meal
                 if g[1] not in {'Special Paratha', 'Sabzi & Dal'}]
        cards = []
        if mains:
            cards.append(intro + '\n' + compact_divider + '\n\n'
                         + card_body(mains))
        if sides:
            subtitle = f'{icon} *{title} • Roti & Sides*'
            cards.append(subtitle + '\n' + compact_divider + '\n\n'
                         + card_body(sides) + '\n\n'
                         + compact_divider + '\n' + invitation)
        elif cards:
            cards[-1] += '\n\n' + compact_divider + '\n' + invitation
        return cards

    # Entire menu: short, scannable cards rather than one giant 45-item bubble.
    batches = [
        ('☀️', 'Breakfast & Drinks', ['Breakfast', 'Drinks']),
        ('🥪', 'Snacks', ['Snacks']),
        ('🍲', 'Main Course', ['Main Course']),
        ('🫓', 'Breads & Rice', ['Breads', 'Rice']),
        ('🥗', 'Sides & Thali', ['Sides & Thali']),
    ]
    result = []
    for icon, title, groups in batches:
        sections = []
        for key in groups:
            if grouped[key]:
                sections += [f'*{next(g[2] for g in MENU_GROUPS if g[0] == key)}*']
                if include_prices:
                    sections.append(bot._whatsapp_price_block(
                        [(x['name'], x['price']) for x in grouped[key]]
                    ))
                else:
                    sections += [_menu_item(item, False) for item in grouped[key]]
                sections.append('')
        if not sections:
            continue
        header = f'{icon} *{hotel} — {title}*' if not result else f'{icon} *{title}*'
        result.append((header + '\n━━━━━━━━━━━━━━━━━━━━\n' + '\n'.join(sections)).strip())
    if result:
        result[0] += '\n\n_DEMO menu • sample items, real hotel rates nahi._'
        result[-1] += '\n\n📝 *Order karna ho?* Naam + quantity bhej dein.\nExample: 2 Poha + 1 Masala Chai\n_DEMO menu only: no real kitchen dispatch._'
    return result


def _menu_item(item, include_prices=False):
    name = str(item['name']).strip()
    return f"• {name} — ₹{int(item['price']):,}" if include_prices else f'• {name}'


def pretty_order_lines(items):
    return '\n'.join(
        f"• {x['qty']} x {x['name']} — ₹{x['amount']:,}"
        for x in items
    )


def pretty_total(total):
    return f'₹{int(total):,}'


def formatted_demo_bill(hotel, details, total, count):
    lines_out = [
        f'🧾 *{hotel.upper()} — DEMO FOOD BILL*',
        '━━━━━━━━━━━━━━━━━━━━',
        '🍽️ *FOOD*',
    ]
    lines_out += details or ['No confirmed food orders yet.']
    lines_out += [
        '',
        f'Food total: Rs. {total}',
        '━━━━━━━━━━━━━━━━━━━━',
        f'💰 *GRAND TOTAL (FOOD ONLY)  {pretty_total(total)}*',
        f'✅ *Confirmed demo orders:* {count}',
        '━━━━━━━━━━━━━━━━━━━━',
        '_Sample bill only • no room rent or payment included._',
        '🙏 Dhanyavaad!',
    ]
    return '\n'.join(lines_out)


def verified_bill_lines(raw):
    """Parse saved item lines; refuse inconsistent rows instead of guessing."""
    parsed, subtotal = [], 0
    for line in str(raw or '').splitlines():
        match = re.fullmatch(
            r'\s*(\d+)\s*x\s*(.+?)\s*@\s*Rs\.\s*(\d+)\s*=\s*Rs\.\s*(\d+)\s*',
            line, re.I
        )
        if not match:
            raise ValueError('Unexpected demo order item format')
        qty, name, unit_price, amount = match.groups()
        q, price, value = int(qty), int(unit_price), int(amount)
        if q <= 0 or price < 0 or value != q * price:
            raise ValueError('Demo order row total mismatch')
        subtotal += value
        parsed.append(f'• {q} x {name} — ₹{value:,}')
    if not parsed:
        raise ValueError('Demo order has no items')
    return parsed, subtotal



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
    total, details, ids = 0, [], set()
    for row in rows:
        if len(row) < 3 or row[2] != phone:
            continue
        if len(row) < len(HEADERS) or row[6] != 'DEMO_CONFIRMED' or not row[0] or row[0] in ids:
            raise ValueError('Demo order rows need review')
        ids.add(row[0])
        item_lines, subtotal = verified_bill_lines(row[4])
        amount = int(row[5])
        if amount < 0 or amount != subtotal:
            raise ValueError('Invalid demo order amount')
        details.extend(item_lines)
        total += amount
    hotel = ((bot.CUSTOMER_CONFIG or {}).get('hotel') or {}).get('name') or 'Hotel'
    return formatted_demo_bill(hotel, details, total, len(ids))


def verified_semantic_basket(bot, semantic):
    """Resolve AI-understood dishes against configured menu, never AI prices.

    A near spelling-match still requires the guest to CONFIRM the preview.
    Uncertain matches ask for clarification; partial/unsupported AI baskets
    cannot reach a Sheet write.
    """
    config = bot.CUSTOMER_CONFIG or {}
    catalog = {}
    for row in config.get('menu') or []:
        if isinstance(row, dict) and row.get('name'):
            try:
                price = int(row['price'])
            except (ValueError, TypeError, KeyError):
                continue
            if price >= 0:
                catalog[bot.normalize_text(row['name'])] = (str(row['name']), price)
    requested = semantic.get('items') or []
    if not isinstance(requested, list) or not requested or len(requested) > 20 or not catalog:
        return {'invalid': True}
    found, corrected = {}, []
    for item in requested:
        if not isinstance(item, dict):
            return {'invalid': True}
        name = str(item.get('name') or '').strip()
        normalized = bot.normalize_text(name)
        if not normalized:
            return {'invalid': True}
        try:
            qty = bot.validated_quantity(item.get('qty', 1))
        except (ValueError, TypeError):
            return {'invalid': True}
        if normalized in catalog:
            actual = catalog[normalized]
        else:
            candidates = sorted(
                ((SequenceMatcher(None, normalized, key).ratio(), key)
                 for key in catalog),
                reverse=True
            )
            top_score, top_key = candidates[0]
            runner_score = candidates[1][0] if len(candidates) > 1 else 0.0
            # Conservative typo threshold and separation from the runner-up:
            # never silently turn two similar dishes into one choice.
            threshold = 0.88 if len(normalized) <= 5 else 0.83
            if top_score < threshold or top_score - runner_score < 0.10:
                suggestions = [catalog[key][0] for score, key in candidates[:2]
                               if score >= 0.68]
                return {'invalid': True, 'suggestions': suggestions}
            actual = catalog[top_key]
            corrected.append((name, actual[0]))
        canonical, price = actual
        old = found.get(canonical, {}).get('qty', 0)
        try:
            quantity = bot.validated_quantity(old + qty)
        except (ValueError, TypeError):
            return {'invalid': True}
        found[canonical] = {'name': canonical, 'qty': quantity,
                            'unit_price': price, 'amount': quantity * price}
    items = list(found.values())
    return {'generic': None, 'items': items, 'total': sum(x['amount'] for x in items),
            'complete': True, 'corrections': corrected}


# This is a simulated guest for the sales demo, NEVER a verified hotel stay.
DEMO_STAY_TTL_SECONDS = 12 * 60 * 60


def demo_stay_active(bot, phone):
    with bot.state_lock:
        data = bot.demo_guest_sessions.get(phone)
        if not isinstance(data, dict):
            return False
        created = float(data.get('created') or 0)
        if data.get('status') != 'DEMO_ACTIVE' or not created:
            return False
        if time.time() - created > DEMO_STAY_TTL_SECONDS:
            bot.demo_guest_sessions.pop(phone, None)
            return False
    return True


def handle(bot, phone, text, semantic=None):
    if not bot.CUSTOMER_DEMO_MODE or not (bot.CUSTOMER_CONFIG or {}).get('demo_food_enabled'):
        return False
    phone = bot.format_whatsapp_number(phone)
    if not phone:
        return False
    normalized = bot.normalize_text(text)
    remembered_user = False

    def say(message):
        nonlocal remembered_user
        if not remembered_user:
            bot.remember_conversation(phone, 'user', text)
            remembered_user = True
        result = bot.send_whatsapp_message(phone, message)
        # Short recall cue, not a second giant menu inside the semantic prompt.
        if result:
            bot.remember_conversation(phone, 'assistant', str(message)[:360])
        return result

    with lock:
        pending = bot.demo_food_sessions.get(phone)
        require_demo_checkin = bool((bot.CUSTOMER_CONFIG or {}).get('demo_require_checkin'))
        if require_demo_checkin:
            if normalized in {'demo checkin', 'demo check in', 'demo guest checkin',
                              'demo guest check in', 'test checkin', 'test check in'}:
                if pending and pending_state(bot, pending) in {'sending', 'unknown'}:
                    say('Pehle purane demo order ka Sheet status verify karna hoga. Abhi naya demo check-in start nahi karungi.')
                    return True
                if pending:
                    bot.demo_food_sessions.pop(phone, None)
                    pending = None
                with bot.state_lock:
                    bot.demo_guest_sessions[phone] = {
                        'status': 'DEMO_ACTIVE', 'created': time.time()
                    }
                say('✅ *Demo check-in active hai* 😊\n'
                    'Ye sirf test hai—real hotel check-in, room allotment ya ID verification nahi hua.\n'
                    'Ab aap menu se demo food order try kar sakte hain. Order save karne se pehle confirmation loongi.')
                return True
            if normalized in {'demo checkout', 'demo check out', 'test checkout', 'test check out'}:
                if pending and pending_state(bot, pending) in {'sending', 'unknown'}:
                    say('Ek demo order ka Sheet status uncertain hai. Check-out se pehle use verify karna hoga.')
                    return True
                bot.demo_food_sessions.pop(phone, None)
                with bot.state_lock:
                    bot.demo_guest_sessions.pop(phone, None)
                say('✅ Demo check-out ho gaya ji. Ab naya food order tabhi banega jab demo check-in dobara hoga.')
                return True
            if normalized in {'self checkin', 'self check in', 'checkin', 'check in',
                              'guest checkin', 'guest check in'}:
                say('Ji, real self check-in ke liye hotel reception ko booking aur ID verify karni hoti hai. '
                    'Is demo profile mein real guest record/room allotment verify nahi hai.\n'
                    'Sirf test ke liye *DEMO CHECKIN* likh sakte hain—isse asli check-in nahi hoga.')
                return True
        if pending and time.time() - pending['created'] > 600:
            if pending_state(bot, pending) == 'prepared':
                bot.demo_food_sessions.pop(phone, None)
                pending = None
        # AI supplies intent, not rates or authorization. The configured menu,
        # durable store and verified Sheet still own every number and write.
        semantic_action = ''
        if isinstance(semantic, dict):
            try:
                confidence = float(semantic.get('confidence') or 0)
            except (ValueError, TypeError):
                confidence = 0.0
            if confidence >= 0.65:
                semantic_action = str(semantic.get('action', '')).upper()

        wants_bill = semantic_action == 'BILL' or (
            not semantic_action and (
                re.search(r'\b(?:bill|invoice|hisaab|hisab)\b|बिल|हिसाब', normalized)
                or normalized in {'total', 'kitna hua', 'total kitna hua', 'food total'}
            )
        )
        if wants_bill:
            try:
                say(bill(bot, phone))
            except Exception as exc:
                print('DEMO BILL UNAVAILABLE:', type(exc).__name__, flush=True)
                say('Demo bill abhi Sheet se verify nahi ho pa raha. Thodi der mein dobara poochhein; main total guess nahi karungi.')
            return True

        wants_menu = semantic_action == 'SHOW_MENU' or (
            not semantic_action and bool(re.search(r'\bmenu\b|मेन्यू|मेनू', normalized)
                                         or meal_request(normalized))
        )
        if wants_menu:
            section = str((semantic or {}).get('menu_section') or '').strip().upper()
            meal = section if section in {'BREAKFAST', 'LUNCH', 'DINNER'} else meal_request(normalized)
            prices = ((semantic or {}).get('show_prices') is True
                      if semantic_action == 'SHOW_MENU' else bot.explicitly_asks_price(text))
            # If AI missed the price flag, explicit local detection is still a
            # safety net, not the primary language-understanding engine.
            prices = prices or bot.explicitly_asks_price(text)
            messages = menu_messages(bot, meal=meal, include_prices=prices)
            for message in messages:
                bot.send_whatsapp_message(phone, message)
            bot.remember_conversation(phone, 'user', text)
            bot.remember_conversation(
                phone, 'assistant',
                f"Showed {'DEMO ' + (meal or 'FULL') + ' menu'}; "
                f"{'prices included' if prices else 'prices not requested'}. "
                "Available for order selection or follow-up questions."
            )
            return True

        # If the AI understood a conversational, non-food turn, let the main
        # receptionist answer with its semantic reply. Do not hijack it just
        # because the guest mentioned 'food', 'order' or 'menu' in passing.
        if semantic_action and semantic_action not in {
            'ORDER', 'ORDER_SELECTION', 'ORDER_CANCEL'
        } and not pending:
            return False
        if pending and bot.is_yes(text):
            if require_demo_checkin and not demo_stay_active(bot, phone):
                if pending_state(bot, pending) == 'prepared':
                    bot.demo_food_sessions.pop(phone, None)
                say('Ji, demo check-in active nahi hai. Isliye order save nahi karungi. '
                    'Test karne ke liye pehle *DEMO CHECKIN* likh dijiye.')
                return True
            try:
                save(bot, phone, pending)
            except Exception as exc:
                print('DEMO ORDER CHECK REQUIRED:', type(exc).__name__, flush=True)
                say('Demo order ka Sheet update confirm nahi ho paaya. Cart rakha hai; Sheet verify hone tak naya order mat banayein. CONFIRM dobara bhejne par pehle usi entry ko check karungi.')
                return True
            bot.demo_food_sessions.pop(phone, None)
            say(
                f"✅ *Demo order save ho gaya!* {pretty_total(pending['total'])} ka order "
                "Demo_Orders Sheet mein record ho gaya.\n"
                "Aap *Bill* likh kar item-wise hisaab dekh sakte hain. 🙂\n"
                "_Ye demo hai; real kitchen delivery nahi hogi._"
            )
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
        foodish = (
            semantic_action in {'ORDER', 'ORDER_SELECTION', 'ORDER_CANCEL'}
            or bool(parsed.get('items') or parsed.get('generic') or parsed.get('invalid'))
            or bool(re.search(r'\b(?:order|food|khana|cancel)\b', normalized))
        )
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
        if require_demo_checkin and not demo_stay_active(bot, phone):
            say('Ji, Veg Pulao ho ya koi aur dish, menu aap dekh sakte hain 😊 '
                'Lekin room-service demo order se pehle check-in active hona zaroori hai.\n'
                'Test ke liye *DEMO CHECKIN* bhej dijiye. Ye sirf simulation hai, real hotel check-in nahi.')
            return True
        # Trust AI for language understanding (including implicit quantity=1 and
        # typos), NOT for prices or permission to save. Verify every extracted
        # item against the configured demo menu and ask for guest confirmation.
        if semantic_action in {'ORDER', 'ORDER_SELECTION'} and isinstance(semantic, dict) and semantic.get('items'):
            parsed = verified_semantic_basket(bot, semantic)
        else:
            # AI offline: conservative local parser remains a fallback.
            basket = re.sub(r"\b(?:i would like|i want|can i get|bhej do|bhijwa do|bhejna|bhijwao?|send|bring|mangwao?|de do|la do|kar do|leke aa|le aao)\b", ' ', normalized)
            parsed = bot.find_menu_items(basket)
        if not parsed.get('complete') or parsed.get('invalid') or parsed.get('generic'):
            suggestions = parsed.get('suggestions') or []
            if suggestions:
                options = ' ya '.join(suggestions)
                say(f"Ji, aap *{options}* keh rahe hain? 😊 Ek baar dish ka naam confirm kar dijiye, phir order bana dungi.")
            else:
                say('Sorry ji, dish clear nahi ho paayi. Menu se naam dobara bata dijiye, main order confirm karwa dungi. Abhi koi entry nahi bani.')
            return True
        if pending and pending_state(bot, pending) in {'sending', 'unknown', 'saved'}:
            say('Pichhle demo order ki Sheet entry pehle verify karni hai. CONFIRM bhejein; abhi naya cart nahi banaungi.')
            return True
        pending = {'id':'DEMO-' + uuid4().hex, 'created':time.time(),
                   'items':parsed['items'], 'total':parsed['total'], 'phone':phone}
        bot.demo_food_sessions[phone] = pending
        correction_note = ''
        if parsed.get('corrections'):
            correction_note = ("Ji, maine "
                               + ', '.join(f"*{correct}*" for _, correct in parsed['corrections'])
                               + " samjha hai 😊 Sahi hai na?\n\n")
        say(
            correction_note
            + "🍽️ *Aapka demo food order*\n━━━━━━━━━━━━━━━━━━━━\n"
            + pretty_order_lines(pending['items'])
            + f"\n━━━━━━━━━━━━━━━━━━━━\n💰 *Total: {pretty_total(pending['total'])}*\n\n"
            + "Ji, order sahi hai? *CONFIRM* ya *CANCEL* bhej dein.\n"
            + "_Sirf demo: kitchen mein order nahi jayega._"
        )
        return True
