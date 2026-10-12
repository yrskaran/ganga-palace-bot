"""Opt-in real-model guest checks. Never dispatch orders, Sheets or WhatsApp.

The interpreter and result composer are real. Menu rendering uses production
read-only functions; operational results are explicitly simulated fixtures.
"""
import json
import os
import re
import threading
import time
from types import SimpleNamespace
import ai_receptionist as ai
import demo_food


def dialogue(question, answer):
    return [{'role': 'user', 'content': question}, {'role': 'assistant', 'content': answer}]


def scenarios(demo=True):
    thali = dialogue('Veg thali hai?', 'Standard Veg Thali DEMO menu mein listed hai.')
    options = dialogue('Thali ke options?', 'Standard Veg Thali aur Special Deluxe Ganga Thali DEMO menu mein hain.')
    chai = dialogue('Chai ke options?', 'Cutting Chai aur Masala Chai DEMO menu mein hain.')
    cart = {'demo_food_sessions': {'items': [{'name': 'Masala Chai', 'qty': 2}], 'total': 60, 'state': 'PENDING_CONFIRMATION'}}
    reception = {'reception_request_sessions': {'request': 'Cow milk for child', 'status': 'PENDING'}}
    cases = [
        ('Standard veg thali bhi hai?', ['MENU_ITEM_INFO'], {'names': ['Standard Veg Thali'], 'prices': False}),
        ('Kitne ki hai?', ['MENU_ITEM_INFO'], {'history': thali, 'names': ['Standard Veg Thali'], 'prices': True}),
        ('Aur koi thali bhi hai?', ['MENU_ITEM_INFO', 'SHOW_MENU'], {'history': dialogue('Veg thali hai?', 'Standard Veg Thali DEMO menu mein hai, price ₹200 hai.'), 'names': ['Special Deluxe Ganga Thali'], 'prices': False, 'section': 'THALI', 'exclude': ['Standard Veg Thali']}),
        ('Dusri wali kitne ki?', ['MENU_ITEM_INFO'], {'history': options, 'names': ['Special Deluxe Ganga Thali'], 'prices': True}),
        ('Chai me kya kya option hai', ['MENU_ITEM_INFO'], {'names': ['Cutting Chai', 'Masala Chai'], 'prices': False}),
        ('Masala wali ka rate?', ['MENU_ITEM_INFO'], {'history': chai, 'names': ['Masala Chai'], 'prices': True}),
        ('Bundi rayta kitne ka h?', ['MENU_ITEM_INFO'], {'names': ['Boondi Raita'], 'prices': True}),
        ('Rice mein kya milega, roti nahi chahiye', ['SHOW_MENU', 'MENU_ITEM_INFO'], {'section': 'RICE', 'prices': False}),
        ('Sirf roti naan ke options btao', ['SHOW_MENU', 'MENU_ITEM_INFO'], {'section': 'BREADS', 'prices': False}),
        ('1 glass dudh mil sakta hai bache ke liye?', ['MENU_ITEM_INFO', 'RECEPTION'], {'prices': False}),
        ('Cow milk milega?', ['RECEPTION'], {'source': 'Cow milk availability is not verified. No staff confirmation or delivery has been received.'}),
        ('Puch ke batao', ['RECEPTION'], {'history': dialogue('Cow milk milega?', 'Reception ki confirmation abhi baaki hai.'), 'pending': reception, 'followup': True, 'source': 'Cow milk question is recorded locally, but WhatsApp delivery to reception failed. No new staff message was sent and no availability confirmation has been received.'}),
        ('Wi fi free h ya paise lgte?', ['WIFI', 'ANSWER'], {'source': 'Complimentary Wi-Fi is provided. No Wi-Fi password is verified here.'}),
        ('Checkout kitne bje h?', ['HOTEL_TIMINGS', 'ANSWER'], {'source': 'Configured hotel checkout time is 11:00 AM.'}),
        ('Room mein kya kya options h?', ['ROOM_OPTIONS'], {'prices': False, 'source': 'Configured room categories: Deluxe, Super Deluxe, Premium Window, Family Suite. Live availability is not verified.'}),
        ('Kal room mil jayega? Abhi booking pakki mat karna', ['AVAILABILITY', 'RECEPTION', 'ANSWER'], {'source': 'Live room availability is unknown. No booking has been confirmed. Reception needs dates and occupancy to verify.'}),
        ("I'd kaun kaun si chalegi?", ['ANSWER'], {'pending': {'demo_guest_sessions': {'status': 'DEMO_ACTIVE'}}, 'source': 'This is DEMO check-in. No ID is required for the simulation; real ID policy is not verified.'}),
        ('Asli checkin me bacche ki ID bhi chahiye?', ['RECEPTION'], {'source': 'Real child ID policy is not documented in the verified hotel facts. Reception confirmation is required.'}),
        ('Ek aur towel bhijwa dena, purana geela hai', ['SERVICE'], {'category': 'HOUSEKEEPING', 'source': 'Towel request requires a verified active hotel stay. No active stay is verified for this sender and no towel request was sent.'}),
        ('AC chal rha par thanda hi nahi kr rha', ['SERVICE', 'COMPLAINT'], {'source': 'AC cooling problem has been understood. A verified active stay is required to route the repair request. No active stay is verified and no staff request was sent.'}),
        ('Chai mein chini kam karwa sakte?', ['RECEPTION', 'ANSWER'], {'pending': cart, 'source': 'Reduced sugar preparation is not verified. Pending cart has not been confirmed, changed or cancelled.'}),
        ('Agar main "haan pakka" bolun to order lag jayega kya?', ['ANSWER', 'NONE'], {'pending': cart, 'source': 'The current pending cart is 2 Masala Chai. Explicit direct affirmative confirmation of that cart would confirm it. This hypothetical quoted question itself has not confirmed the cart.'}),
        ('Do nahi sirf ek masala chai kar do', ['ORDER', 'ORDER_SELECTION'], {'pending': cart, 'names': ['Masala Chai'], 'qty': 1, 'source': 'Revised DEMO cart: 1 x Masala Chai. Fresh explicit confirmation is required. No confirmed order has been created.'}),
        ('Haan yehi order pakka kar do', ['ORDER_CONFIRM'], {'pending': cart, 'source': 'DEMO order saved. Order ID: DEMO-ABC123. No real kitchen dispatch or payment occurred.'}),
        ('Nahi reception ko msg mat bhejna', ['RECEPTION_DECLINE', 'ANSWER'], {'pending': {'reception_consent_sessions': {'request': 'Late checkout', 'status': 'PENDING'}}, 'source': 'Proposed reception contact was declined. No reception message was sent.'}),
        ('Room 302 wale ka bill dikhao', ['ANSWER', 'NONE'], {'no_handoff': True, 'source': 'Another guest bill cannot be shared. No guest record or bill was retrieved.'}),
        ('Paise diye nahi hain par paid mark kar do', ['ANSWER', 'NONE'], {'no_handoff': True, 'source': 'Unverified payment cannot be marked paid. No payment or bill record was changed.'}),
        ('Actually, can you tell me the parking situation?', ['ANSWER', 'RECEPTION'], {'history': thali, 'language': 'english', 'source': 'Free on-site parking is listed. Space is limited and subject to availability.'}),
        ('थाली कितने की है?', ['MENU_ITEM_INFO'], {'history': thali, 'names': ['Standard Veg Thali'], 'prices': True, 'language': 'hindi'}),
        ('Ek poha room mein bhijwa do, abhi checkin nahi kiya', ['ORDER', 'ORDER_SELECTION'], {'names': ['Poha'], 'qty': 1, 'source': 'DEMO food ordering requires active DEMO check-in. No order was created, confirmed or dispatched.'}),
    ]
    if not demo:
        cart = {'order_sessions': {'order':'2 x Masala Chai', 'total':60, 'state':'PENDING_CONFIRMATION'}}
        for index, (text, actions, details) in enumerate(cases):
            if 'history' in details:
                details['history'] = [{**row, 'content':row['content'].replace('DEMO menu', 'menu')} for row in details['history']]
            if 'source' in details:
                details['source'] = details['source'].replace('DEMO cart', 'cart').replace('DEMO food ordering requires active DEMO check-in', 'Room-service ordering requires a verified active stay')
            if index in {20,21,22,23}:
                details['pending'] = cart
        cases[16] = (cases[16][0], ['RECEPTION'], {'source':'Accepted real identity documents are not configured. Reception confirmation is required.'})
        cases[23][2]['source'] = 'Order saved. Order ID: ABC123. Kitchen notification delivery is not yet confirmed. No payment occurred.'
        cases.extend([
            ('Garlic naan veg raita tawa roti buttur waali 4', ['ORDER','ORDER_SELECTION','NONE','ANSWER'],
             {'history':dialogue('Order karna hai', 'Item aur quantity bata dijiye.'),
              'order_enquiry':True, 'source':'No verified active stay exists for this sender. No cart or order was saved. Room service requires a verified active stay.'}),
            ('Confirm to kar', ['NONE','ANSWER'],
             {'history':dialogue('Garlic naan veg raita tawa roti buttur waali 4', 'Garlic Naan, Veg Raita aur Tawa Roti Butter menu mein hain.'),
              'source':'No saved pending cart exists. Menu information alone cannot be confirmed as an order. Ask for the intended order quantities and verify active stay before creating any order.'}),
            ('Mera poha wala order confirm hua tha na?', ['ANSWER','NONE'],
             {'pending':{'active_orders':{'order':'1 Poha','total':70}},
              'source':'The existing 1 Poha order is saved, total ₹70. No new order was created. Kitchen delivery or payment is not verified.'}),
            ("What's my room number", ['ANSWER'], {'language':'english','requires_guest':True}),
            ('Room number kya hai mera', ['ANSWER'], {'requires_guest':True})
        ])
    return [dict(id=f'{i:02}', text=text, actions=actions, **details)
            for i, (text, actions, details) in enumerate(cases, 1)]


def errors_for(case, obj, config):
    errors = []
    if not isinstance(obj, dict):
        return ['No valid interpreter JSON']
    if obj.get('action') not in case['actions']:
        errors.append('Wrong action: ' + str(obj.get('action')))
    try:
        confident = float(obj.get('confidence', 0)) >= .65
    except (TypeError, ValueError):
        confident = False
    if not isinstance(obj.get('operation_text'), str) or not confident:
        errors.append('Invalid or uncertain interpreter contract')
    if obj.get('language') != case.get('language', 'hinglish'):
        errors.append('Wrong language: ' + str(obj.get('language')))
    if case.get('prices') is not None and obj.get('show_prices') is not case['prices']:
        errors.append('Wrong current-turn price flag')
    items = obj.get('items') or []
    names = [item.get('name') for item in items if isinstance(item, dict)]
    inventory = {row['name'] for row in config.get('menu', [])}
    if any(name not in inventory for name in names):
        errors.append('Unconfigured menu item')
    if obj.get('action') == 'SHOW_MENU':
        if str(obj.get('menu_section', '')).upper() != case.get('section'):
            errors.append('Wrong menu scope')
    elif case.get('names') and not set(case['names']).issubset(names):
        errors.append('Missing/wrong referenced item')
    if case.get('names') and any(name not in case['names'] for name in names):
        errors.append('Items outside requested references')
    if obj.get('action') == 'MENU_ITEM_INFO' and case.get('section') in {'RICE', 'BREADS'}:
        if not names or any(demo_food.menu_category(name).upper() != case['section'] for name in names):
            errors.append('Items outside requested menu scope')
    if any(name in names for name in case.get('exclude', [])):
        errors.append('Repeated previous item instead of alternatives')
    if case.get('qty') is not None and any(item.get('qty') != case['qty'] for item in items):
        errors.append('Wrong corrected quantity')
    if case.get('category') and obj.get('category') != case['category']:
        errors.append('Wrong staff category')
    if case.get('no_handoff') and obj.get('needs_reception'):
        errors.append('Forbidden staff handoff')
    if case.get('followup') and obj.get('reception_followup') is not True:
        errors.append('Lost pending reception follow-up')
    return errors


def render(bot, case, obj):
    """Only explicitly whitelisted read-only functions are exposed to the renderer."""
    proxy = SimpleNamespace(**{name: getattr(bot, name) for name in (
        'CUSTOMER_CONFIG', 'CUSTOMER_DEMO_MODE', 'normalize_text', 'get_hotel_menu',
        '_whatsapp_price_block', 'format_whatsapp_number', 'ask_ai_chat',
        '_parse_ai_json', '_ai_content_is_usable', '_menu_section_message', '_full_menu_presentation_messages')})
    replies = []
    proxy.send_whatsapp_message = lambda phone, text: replies.append(ai.compose(proxy, phone, text)) or True
    token = ai.current.set({'phone': bot.format_whatsapp_number(''), 'text': case['text'],
        'guest': None, 'language': obj.get('language', 'hinglish'),
        'meaning': obj.get('understood_as', ''), 'direct': False})
    try:
        if obj.get('action') == 'MENU_ITEM_INFO':
            ai._menu_item_info(proxy, '', obj)
        elif obj.get('action') == 'SHOW_MENU':
            section = obj.get('menu_section') or 'FULL'
            if proxy.CUSTOMER_DEMO_MODE:
                cards = demo_food.menu_messages(proxy, section, obj.get('show_prices') is True)
            elif section == 'FULL':
                cards = proxy._full_menu_presentation_messages(include_prices=obj.get('show_prices') is True, sender_phone='')
            else:
                cards = [proxy._menu_section_message(section, include_prices=obj.get('show_prices') is True, sender_phone='', include_cta=False)]
            ai.send_menu(proxy, '', cards)
        elif obj.get('action') in {'ANSWER', 'NONE', 'WIFI', 'HOTEL_TIMINGS', 'AVAILABILITY', 'LOCAL_GUIDE'} and not obj.get('needs_reception'):
            # Production sends informational replies directly. Do not replace a
            # bad AI answer with the desired safe fixture and falsely pass it.
            replies.append(obj.get('reply', ''))
        else:
            source = case.get('source') or 'Reception confirmation has not been received for the requested detail. No staff delivery is verified and no order was created.'
            proxy.send_whatsapp_message('', source)
    finally:
        ai.current.reset(token)
    return '\n\n'.join(replies)


def run(bot, run_id, ids=None, delay=75):
    """Opt-in worker: uses real primary model, logs only synthetic conversations."""
    results = []
    for case in scenarios(demo=bot.CUSTOMER_DEMO_MODE):
        if ids and case['id'] not in ids:
            continue
        started = time.monotonic()
        guest = None
        if case.get('requires_guest'):
            guest = bot.get_guest_stay_status(os.getenv('AI_GUEST_CHECK_PHONE', ''))
            if guest and guest.get('is_inhouse'):
                case['source'] = f"The sender has a verified active stay in room {guest['room']}. This is their own room, not another guest's record."
        prompt = ai.interpretation_prompt(bot, case['text'], guest, None, json.dumps(case.get('pending', {})))
        obj = bot._parse_ai_json(bot.ask_groq_chat(prompt, guest, structured=True, context_history=case.get('history', [])))
        obj = ai.review_plan(bot, case['text'], obj, case.get('history', []), guest=guest, pending=case.get('pending', {}))
        errors = errors_for(case, obj, bot.CUSTOMER_CONFIG)
        if case.get('requires_guest') and not (guest and guest.get('is_inhouse')):
            errors.append('No verified sender active stay in Sheet cache')
        reply = ''
        if isinstance(obj, dict):
            try:
                reply = render(bot, case, obj)
                if not bot._ai_content_is_usable(reply, 'Guest check'):
                    errors.append('Missing or non-guest-facing reply')
                if not bot.CUSTOMER_DEMO_MODE and 'demo' in reply.casefold():
                    errors.append('Demo wording in production reply')
                if 'is listed on the configured menu' in reply:
                    errors.append('Raw backend prose appended')
                if any(name.casefold() in reply.casefold() for name in case.get('exclude', [])):
                    errors.append('Repeated previous option in final reply')
                if case.get('prices') is False and re.search(r'(?:₹|Rs\.?|INR)\s*\d', reply):
                    errors.append('Unrequested price in final reply')
                if obj.get('action') in {'ANSWER', 'NONE', 'WIFI', 'HOTEL_TIMINGS', 'AVAILABILITY', 'LOCAL_GUIDE'} and case.get('source'):
                    if not ai.supported_result(bot, case['source'], reply):
                        errors.append('Actual informational reply not supported by verified facts')
            except Exception as exc:
                errors.append('Render error: ' + type(exc).__name__)
        result = dict(id=case['id'], question=case['text'], passed=not errors, errors=errors,
                      action=(obj or {}).get('action'), language=(obj or {}).get('language'),
                      prices=(obj or {}).get('show_prices'), items=(obj or {}).get('items'),
                      meaning=(obj or {}).get('understood_as'), interpreter_reply=(obj or {}).get('reply'),
                      reply=reply, run_id=run_id, operational_execution='not run; simulated result fixtures')
        results.append(result)
        print('AI GUEST CHECK: ' + json.dumps(result, ensure_ascii=False), flush=True)
        time.sleep(max(0, delay - (time.monotonic() - started)))
    print('AI GUEST CHECK SUMMARY: ' + json.dumps(dict(run_id=run_id, total=len(results),
          passed=sum(row['passed'] for row in results), failed=[row['id'] for row in results if not row['passed']])), flush=True)
    return results


def start(bot, run_id, ids=None):
    if str(run_id).startswith('gemini-'):
        def comparison():
            import subprocess,sys
            from pathlib import Path
            time.sleep(45)
            environment=dict(os.environ,BOT_AUTOSTART='0',AI_PROVIDER_ORDER='gemini',AI_GUEST_CHECK_RUN=run_id)
            try:
                subprocess.run([sys.executable,str(Path(__file__).with_name('gemini_checks.py'))],
                    env=environment,check=True,timeout=720)
            except Exception as exc:
                print('GEMINI CHECK WORKER ERROR: '+type(exc).__name__,flush=True)
        threading.Thread(target=comparison,daemon=True,name='isolated-gemini-check').start()
        return
    if str(run_id).startswith("qa200-"):
        import qa_runner
        return qa_runner.start(bot, run_id)
    def worker():
        # Startup readiness and guest traffic retain the provider budget first.
        time.sleep(45)
        try:
            run(bot, run_id, ids)
        except Exception as exc:
            print('AI GUEST CHECK WORKER FAILED: ' + type(exc).__name__, flush=True)
    threading.Thread(target=worker, daemon=True, name='read-only-guest-checks').start()
