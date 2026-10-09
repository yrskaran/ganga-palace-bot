"""Demo food flow uses fake Sheets and temporary SQLite; no real notifications."""
import importlib
import os
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

os.environ['BOT_AUTOSTART'] = '0'
import app
from reliability import Store


class Sheet:
    def __init__(self, headers):
        self.rows = [headers.copy()]
        self.append_count = 0
        self.timeout = False

    def get_all_values(self):
        return [r.copy() for r in self.rows]

    def update(self, range_name=None, values=None, **kwargs):
        self.rows = [[str(cell) for cell in values[0]]]

    def append_row(self, row, **kwargs):
        self.append_count += 1
        if self.timeout:
            raise TimeoutError('fake timeout')
        self.rows.append([str(v) for v in row])


class DemoFoodTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('demo_food'), 'demo food flow is not implemented')
        self.demo = importlib.import_module('demo_food')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name + '/demo.db')
        self.sheet = Sheet(self.demo.HEADERS)
        self.book = Mock()
        self.book.worksheet.return_value = self.sheet
        client = Mock()
        client.open_by_key.return_value = self.book
        config = {'demo_mode':True, 'demo_food_enabled':True, 'demo_require_checkin': True,
                  'menu':[{'name':'Masala Chai','price':30},{'name':'Poha','price':70}, {'name':'Butter Naan','price':40}]}
        self.sent = Mock(return_value=True)
        self.kitchen = Mock(side_effect=AssertionError('Real kitchen must not be alerted'))
        values = {'CUSTOMER_DEMO_MODE':True, 'CUSTOMER_CONFIG':config,
                  'HOTEL_CONFIG_CACHE':{'signature':None,'data':None},
                  'demo_food_sessions':{},
                  'demo_guest_sessions':{'919111111111':{'status':'DEMO_ACTIVE','created':time.time()}},
                  'durable_store':self.store,
                  'get_gspread_client':Mock(return_value=client),
                  'send_whatsapp_message':self.sent, 'send_staff_alert':self.kitchen}
        for name, value in values.items():
            p = patch.object(app, name, value, create=True)
            p.start(); self.addCleanup(p.stop)
        self.phone = '919111111111'

    def turn(self, text, phone=None):
        return self.demo.handle(app, phone or self.phone, text)

    def reply(self):
        return self.sent.call_args.args[1]

    def test_demo_reminders_require_clear_opt_in_and_demo_checkin(self):
        config = dict(app.CUSTOMER_CONFIG, demo_reminders_enabled=True)
        with patch.object(app, 'CUSTOMER_CONFIG', config):
            app.demo_guest_sessions.clear()
            self.turn('DEMO REMINDERS ON')
            self.assertIn('DEMO CHECKIN', self.reply())
            self.assertEqual(app.demo_guest_sessions, {})
            self.turn('DEMO CHECKIN')
            self.assertFalse(app.demo_guest_sessions[self.phone].get('reminders_enabled', False))
            self.turn('DEMO REMINDERS ON')
            self.assertIn('Demo reminders ON', self.reply())
            self.assertTrue(app.demo_guest_sessions[self.phone]['reminders_enabled'])
            self.assertEqual(app.demo_guest_sessions[self.phone]['reminder_instance'],
                             self.demo.DEMO_REMINDER_INSTANCE)
        self.kitchen.assert_not_called()

    def test_automatic_demo_breakfast_lunch_aarti_dinner_each_once(self):
        config = dict(app.CUSTOMER_CONFIG, demo_reminders_enabled=True)
        with patch.object(app, 'CUSTOMER_CONFIG', config):
            self.turn('DEMO REMINDERS ON')
            self.sent.reset_mock()
            self.addCleanup(patch.stopall)
            patch.object(app, 'get_guest_response_language', return_value='english').start()
            for hour, expected in [(8, 'breakfast'), (13, 'lunch'),
                                   (17, 'Ganga Aarti'), (19, 'dinner')]:
                with self.subTest(hour=hour):
                    when = app.now_ist().replace(hour=hour, minute=15)
                    self.assertEqual(self.demo.run_demo_reminders(app, when), 1)
                    msg = self.reply()
                    self.assertIn('DEMO ONLY', msg)
                    self.assertIn(expected.lower(), msg.lower())
                    self.assertEqual(self.demo.run_demo_reminders(app, when), 0)
            self.assertEqual(self.sent.call_count, 4)
            self.assertEqual(self.sheet.append_count, 0)
        self.kitchen.assert_not_called()

    def test_demo_reminder_opt_out_checkout_and_expiry(self):
        config = dict(app.CUSTOMER_CONFIG, demo_reminders_enabled=True)
        at = app.now_ist().replace(hour=8, minute=30)
        with patch.object(app, 'CUSTOMER_CONFIG', config):
            self.turn('DEMO REMINDERS ON')
            self.turn('DEMO REMINDERS OFF')
            self.sent.reset_mock()
            self.assertEqual(self.demo.run_demo_reminders(app, at), 0)
            self.sent.assert_not_called()
            self.turn('DEMO REMINDERS ON')
            app.demo_guest_sessions[self.phone]['last_inbound_at'] -= 24 * 3600
            self.sent.reset_mock()
            self.assertEqual(self.demo.run_demo_reminders(app, at), 0)
            self.sent.assert_not_called()
            self.turn('DEMO REMINDERS ON')
            app.demo_guest_sessions[self.phone]['created'] -= self.demo.DEMO_STAY_TTL_SECONDS + 10
            self.sent.reset_mock()
            self.assertEqual(self.demo.run_demo_reminders(app, at), 0)
            self.sent.assert_not_called()
            self.turn('DEMO CHECKOUT')
            self.assertNotIn(self.phone, app.demo_guest_sessions)
        self.kitchen.assert_not_called()

    def test_demo_opt_in_never_reused_after_server_restart(self):
        config = dict(app.CUSTOMER_CONFIG, demo_reminders_enabled=True)
        with patch.object(app, 'CUSTOMER_CONFIG', config):
            self.turn('DEMO REMINDERS ON')
            self.sent.reset_mock()
            with patch.object(self.demo, 'DEMO_REMINDER_INSTANCE', 'new-server'):
                at = app.now_ist().replace(hour=8, minute=30)
                self.assertEqual(self.demo.run_demo_reminders(app, at), 0)
                self.sent.assert_not_called()
        self.kitchen.assert_not_called()

    def test_demo_reminder_failure_not_retried_and_isolated_from_real_hotel(self):
        config = dict(app.CUSTOMER_CONFIG, demo_reminders_enabled=True)
        when = app.now_ist().replace(hour=8, minute=30)
        with patch.object(app, 'CUSTOMER_CONFIG', config):
            self.turn('DEMO REMINDERS ON')
            self.sent.reset_mock()
            self.sent.return_value = False
            self.assertEqual(self.demo.run_demo_reminders(app, when), 1)
            self.assertEqual(self.demo.run_demo_reminders(app, when), 0)
            self.assertEqual(self.sent.call_count, 1)
            with patch.object(app, 'CUSTOMER_DEMO_MODE', False):
                self.assertEqual(self.demo.run_demo_reminders(app, when), 0)
            self.assertEqual(self.sheet.append_count, 0)
        self.kitchen.assert_not_called()

    def test_demo_order_requires_explicit_prior_checkin(self):
        app.demo_guest_sessions.clear()
        self.assertTrue(self.turn('menu'))
        self.assertIn('DEMO', self.reply())
        self.assertTrue(self.demo.handle(app, self.phone, 'Veg Pulao leke aa', semantic={
            'action': 'ORDER', 'confidence': .95,
            'items': [{'name': 'Veg Pulao', 'qty': 1}]
        }))
        self.assertIn('check-in active', self.reply())
        self.assertNotIn(self.phone, app.demo_food_sessions)
        self.assertEqual(self.sheet.append_count, 0)
        self.kitchen.assert_not_called()

    def test_self_checkin_is_not_fake_hotel_checkin(self):
        app.demo_guest_sessions.clear()
        self.assertTrue(self.turn('Self checkin'))
        self.assertIn('real guest record', self.reply())
        self.assertIn('DEMO CHECKIN', self.reply())
        self.assertNotIn(self.phone, app.demo_guest_sessions)
        self.assertEqual(self.sheet.append_count, 0)
        self.kitchen.assert_not_called()

    def test_explicit_demo_checkin_allows_preview_then_confirm(self):
        app.demo_guest_sessions.clear()
        self.turn('DEMO CHECKIN')
        self.assertTrue(self.demo.demo_stay_active(app, self.phone))
        self.assertIn('real hotel check-in', self.reply())
        self.assertEqual(self.sheet.append_count, 0)
        self.turn('1 Poha')
        self.assertIn('Total:', self.reply())
        self.assertEqual(self.sheet.append_count, 0)
        self.turn('CONFIRM')
        self.assertEqual(self.sheet.append_count, 1)
        self.turn('bill')
        self.assertIn('Food total: Rs. 70', self.reply())
        self.kitchen.assert_not_called()

    def test_demo_checkout_blocks_new_order_but_menu_still_works(self):
        self.turn('DEMO CHECKOUT')
        self.assertNotIn(self.phone, app.demo_guest_sessions)
        self.assertTrue(self.turn('menu'))
        self.assertIn('DEMO', self.reply())
        self.turn('2 Masala Chai')
        self.assertIn('check-in active', self.reply())
        self.assertEqual(self.sheet.append_count, 0)
        self.kitchen.assert_not_called()

    def test_prepared_cart_cannot_be_confirmed_after_demo_checkin_expires(self):
        self.turn('1 Poha')
        self.assertIn(self.phone, app.demo_food_sessions)
        app.demo_guest_sessions[self.phone]['created'] -= self.demo.DEMO_STAY_TTL_SECONDS + 10
        self.turn('CONFIRM')
        self.assertIn('check-in active nahi', self.reply())
        self.assertNotIn(self.phone, app.demo_food_sessions)
        self.assertEqual(self.sheet.append_count, 0)
        self.kitchen.assert_not_called()

    def test_simulated_stay_survives_session_snapshot_for_restart(self):
        self.turn('DEMO CHECKIN')
        snapshot = app.session_snapshot(self.phone)
        self.assertEqual(snapshot['demo_guest_sessions']['status'], 'DEMO_ACTIVE')
        self.assertIsNotNone(snapshot['demo_guest_sessions']['created'])
        self.kitchen.assert_not_called()

    def test_real_hotel_guest_order_route_remains_separate(self):
        with patch.object(app, 'CUSTOMER_DEMO_MODE', False):
            self.assertFalse(self.turn('1 Poha'))
            self.assertFalse(self.turn('DEMO CHECKIN'))
        self.kitchen.assert_not_called()

    def test_confirm_without_eligible_stay_cannot_replay_uncertain_sheet_write(self):
        self.turn('1 Poha')
        pending = app.demo_food_sessions[self.phone].copy()
        self.sheet.timeout = True
        self.turn('CONFIRM')
        self.assertEqual(self.sheet.append_count, 1)
        app.demo_guest_sessions.clear()
        self.sheet.timeout = False
        self.turn('CONFIRM')
        self.assertEqual(self.sheet.append_count, 1)
        self.assertIn('check-in active nahi', self.reply())
        self.assertEqual(app.demo_food_sessions[self.phone]['id'], pending['id'])
        self.kitchen.assert_not_called()

    def test_menu_is_sample_and_no_entry_before_confirmation(self):
        self.assertTrue(self.turn('menu'))
        self.assertIn('DEMO', self.reply())
        self.assertIn('Masala Chai', self.reply())
        self.assertTrue(self.turn('2 Masala Chai aur 1 Poha'))
        self.assertIn('130', self.reply())
        self.assertEqual(self.sheet.append_count, 0)
        self.assertIn('CONFIRM', self.reply())

    def test_confirm_sheet_entry_and_food_only_itemized_bill(self):
        self.turn('2 Masala Chai aur 1 Poha')
        self.turn('confirm')
        self.assertEqual(self.sheet.append_count, 1)
        self.book.worksheet.assert_called_with('Demo_Orders')
        self.assertIn('130', self.sheet.rows[1])
        self.turn('bill')
        self.assertIn('2 x Masala Chai', self.reply())
        self.assertIn('130', self.reply())
        self.assertNotIn('1999', self.reply())
        self.assertNotIn('Room rent', self.reply())
        self.kitchen.assert_not_called()

    def test_repeated_confirmation_does_not_duplicate(self):
        self.turn('2 Masala Chai')
        self.turn('confirm'); self.turn('confirm')
        self.assertEqual(self.sheet.append_count, 1)

    def test_timeout_preserves_cart_and_never_replays_uncertain_write(self):
        self.turn('2 Masala Chai')
        self.sheet.timeout = True
        self.turn('confirm')
        self.assertIn(self.phone, app.demo_food_sessions)
        self.assertNotIn('save ho gaya', self.reply())
        self.sheet.timeout = False
        self.turn('confirm')
        self.assertEqual(self.sheet.append_count, 1)

    def test_bill_does_not_expose_another_phone_or_unconfirmed_cart(self):
        self.turn('2 Masala Chai'); self.turn('confirm')
        self.turn('bill', '919222222222')
        self.assertIn('Rs. 0', self.reply())
        self.turn('3 Poha')
        self.turn('bill')
        self.assertIn('Rs. 60', self.reply())
        self.assertNotIn('210', self.reply())

    def test_cancel_drops_pending_cart_only(self):
        self.turn('2 Masala Chai'); self.turn('cancel'); self.turn('confirm')
        self.assertEqual(self.sheet.append_count, 0)

    def test_unknown_items_and_negation_never_make_partial_orders(self):
        for text in ['2 Masala Chai aur pizza', 'Masala Chai nahi chahiye', '-2 Masala Chai', '1.5 Masala Chai']:
            self.turn(text)
            self.assertNotIn(self.phone, app.demo_food_sessions, text)

    def test_bill_failure_is_not_a_zero_bill(self):
        self.book.worksheet.side_effect = RuntimeError('Sheets unavailable')
        self.turn('bill')
        self.assertNotIn('Rs. 0', self.reply())
        self.assertIn('verify', self.reply())

    def test_non_demo_profile_uses_normal_flow(self):
        with patch.object(app,'CUSTOMER_DEMO_MODE',False):
            self.assertFalse(self.turn('menu'))
        self.book.worksheet.assert_not_called()

    def test_missing_sample_menu_does_not_offer_nonexistent_dishes(self):
        with patch.object(app,'CUSTOMER_CONFIG',{'demo_mode':True,'demo_food_enabled':True,'menu':[]}):
            self.assertTrue(self.turn('menu'))
            self.assertIn('configure nahi',self.reply())
            self.assertNotIn('Masala Chai',self.reply())

    def test_generic_yes_without_cart_stays_with_concierge(self):
        self.assertFalse(self.turn('haan'))
        self.assertFalse(self.turn('ji'))
        self.assertTrue(self.turn('confirm'))
        self.assertIn('pending nahi',self.reply())

    def test_config_gate_disables_demo_food_and_keeps_it_opt_in(self):
        with patch.object(app,'CUSTOMER_CONFIG',{'demo_mode':True}):
            self.assertFalse(self.turn('menu'))

    def test_actual_text_router_uses_demo_before_guest_lookup_and_ai(self):
        with patch.object(app,'get_guest_stay_status',side_effect=AssertionError('No real guest lookup')), patch.object(app,'understand_guest_request',side_effect=AssertionError('No model needed')):
            app._process_and_reply({'text':{'body':'menu'}},self.phone,'text')
            self.assertIn('DEMO menu',self.reply())
            app._process_and_reply({'text':{'body':'2 Masala Chai aur 1 Poha'}},self.phone,'text')
            app._process_and_reply({'text':{'body':'confirm'}},self.phone,'text')
            app._process_and_reply({'text':{'body':'bill'}},self.phone,'text')
            self.assertIn('Food total: Rs. 130',self.reply())

    def test_menu_question_preserves_pending_cart_and_price_is_not_an_order(self):
        self.turn('2 Masala Chai')
        cart=app.demo_food_sessions[self.phone].copy()
        self.turn('menu'); self.turn('Poha price kya hai')
        self.assertEqual(app.demo_food_sessions[self.phone],cart)
        self.assertEqual(self.sheet.append_count,0)

    def test_uncertain_cart_cannot_be_replaced_or_cancelled(self):
        self.turn('2 Masala Chai')
        cart=app.demo_food_sessions[self.phone].copy()
        self.sheet.timeout=True
        self.turn('confirm'); self.turn('cancel'); self.turn('1 Poha')
        self.assertEqual(app.demo_food_sessions[self.phone],cart)
        self.assertEqual(self.sheet.append_count,1)

    def test_success_after_timeout_is_reconciled_without_second_append(self):
        self.turn('2 Masala Chai')
        cart=app.demo_food_sessions[self.phone].copy()
        self.sheet.timeout=True
        self.turn('confirm')
        self.sheet.rows.append([cart['id'],'time',self.phone,'DEMO',self.demo.lines(cart['items']),'60','DEMO_CONFIRMED'])
        self.sheet.timeout=False
        self.turn('confirm')
        self.assertNotIn(self.phone,app.demo_food_sessions)
        self.assertEqual(self.sheet.append_count,1)

    def test_cart_is_in_session_snapshot_for_restart_restore(self):
        self.turn('1 Poha')
        snapshot=app.session_snapshot(self.phone)
        self.assertEqual(snapshot['demo_food_sessions']['total'],70)

    def test_empty_demo_orders_sheet_is_initialized_before_save(self):
        self.sheet.rows = []
        self.turn('1 Poha')
        self.turn('confirm')
        self.assertEqual(self.sheet.rows[0], self.demo.HEADERS)
        self.assertEqual(self.sheet.append_count, 1)
        self.turn('bill')
        self.assertIn('Food total: Rs. 70', self.reply())
        self.kitchen.assert_not_called()

    def test_empty_demo_orders_sheet_can_show_zero_bill(self):
        self.sheet.rows = []
        self.turn('bill')
        self.assertIn('Food total: Rs. 0', self.reply())

    def test_full_legacy_menu_prices_match_demo_bill(self):
        import json
        from pathlib import Path
        config = json.loads(Path(__file__).with_name('customer_config.json').read_text(encoding='utf-8'))
        prices = {row['name']: row['price'] for row in config['menu']}
        self.assertEqual(len(prices), 45)
        self.assertEqual(prices['Butter Naan'], 60)
        self.assertEqual(prices['Special Deluxe Ganga Thali'], 290)
        with patch.object(app, 'CUSTOMER_CONFIG', config):
            self.turn('menu')
            self.assertIn('Special Deluxe Ganga Thali', self.reply())
            self.turn('2 Butter Naan aur 1 Paneer Butter Masala')
            self.assertIn('₹380', self.reply())
            self.turn('confirm')
            self.turn('bill')
            self.assertIn('Food total: Rs. 380', self.reply())
        self.kitchen.assert_not_called()

    def test_conflicting_headers_preserve_sheet_and_report_failure(self):
        self.sheet.rows[0][0]='Unrelated data'
        self.turn('1 Poha'); self.turn('confirm')
        self.assertEqual(self.sheet.append_count,0)
        self.assertIn('confirm nahi',self.reply())


    def test_breakfast_lunch_dinner_only_show_relevant_items(self):
        import json
        from pathlib import Path
        config = json.loads(Path(__file__).with_name('customer_config.json').read_text(encoding='utf-8'))
        with patch.object(app, 'CUSTOMER_CONFIG', config):
            self.sent.reset_mock()
            self.turn('breakfast')
            breakfast_cards = [c.args[1] for c in self.sent.call_args_list]
            self.assertEqual(len(breakfast_cards), 1)
            breakfast = '\n'.join(breakfast_cards)
            self.assertIn('Poha', breakfast)
            self.assertIn('Masala Chai', breakfast)
            self.assertIn('☕ *Tea & Drinks*', breakfast)
            self.assertNotIn('Shahi Paneer', breakfast)

            self.sent.reset_mock()
            self.turn('Lunch mein kya kya hai?')
            lunch_cards = [c.args[1] for c in self.sent.call_args_list]
            self.assertEqual(len(lunch_cards), 2)
            lunch = '\n'.join(lunch_cards)
            self.assertIn('Dal Tadka', lunch)
            self.assertIn('Butter Naan', lunch)
            self.assertIn('🍲 *Sabzi & Dal*', lunch_cards[0])
            self.assertIn('🫓 *Roti & Naan*', lunch_cards[1])
            self.assertNotIn('Poha', lunch)
            self.assertNotIn('Masala Chai', lunch)

            self.sent.reset_mock()
            self.turn('Dinner me kya kya hai')
            dinner_cards = [c.args[1] for c in self.sent.call_args_list]
            self.assertEqual(len(dinner_cards), 2)
            dinner = '\n'.join(dinner_cards)
            self.assertIn('Shahi Paneer', dinner)
            self.assertIn('Butter Naan', dinner)
            self.assertIn('Mix Veg Paratha', dinner)
            self.assertNotIn('Masala Chai', dinner)
            self.assertIn('📝 *Kuch order karna hai?*', dinner_cards[-1])
            self.assertNotIn('Kuch order karna hai?', dinner_cards[0])
            self.assertEqual(dinner.count('• Shahi Paneer'), 1)
            self.assertEqual(dinner.count('• Butter Naan'), 1)
            self.assertIn('_DEMO • sample menu_', dinner_cards[0])
            self.assertIn('Demo order only', dinner_cards[-1])

        self.book.worksheet.assert_not_called()

    def _assert_aligned_price_columns(self, text, names, group_separately=False):
        import re
        rows = [
            line for block in re.findall(r'\x60\x60\x60\n(.*?)\n\x60\x60\x60', text, re.S)
            for line in block.splitlines()
        ]
        self.assertTrue(rows, 'Expected WhatsApp triple-backtick monospaced menu')
        self.assertFalse(any(line.startswith('•') for line in rows))
        if group_separately:
            for name in names:
                self.assertTrue(any(x.startswith(name + ' ') and '₹' in x for x in rows), name)
            return
        selected = [next(x for x in rows if x.startswith(name + ' ')) for name in names]
        self.assertEqual(len({x.index('₹') for x in selected}), 1)

    def test_aligned_price_formatter_preserves_real_menu_prices(self):
        import re
        sample = [
            ('Dal Fry', 130),
            ('Paneer Butter Masala', 260),
            ('Shahi Paneer', 240),
        ]
        block = app._whatsapp_price_block(sample)
        self.assertEqual(block.count('\x60\x60\x60'), 2)
        lines = block.splitlines()[1:-1]
        self.assertEqual([line.strip().split()[-1] for line in lines],
                         ['₹130', '₹260', '₹240'])
        self.assertEqual(len({line.index('₹') for line in lines}), 1)
        self.assertEqual(len(lines), 3)
        self.assertNotIn('\x60\x60\x60text', block)  # WhatsApp does not use Markdown language tags

    def test_full_menu_with_prices_uses_aligned_blocks(self):
        import json
        import re
        from pathlib import Path
        config = json.loads(Path(__file__).with_name('customer_config.json').read_text(encoding='utf-8'))
        with patch.object(app, 'CUSTOMER_CONFIG', config):
            self.turn('menu with prices')
            text = '\n'.join(c.args[1] for c in self.sent.call_args_list)
            self.assertIn('Paneer Butter Masala', text)
            self.assertIn('Special Deluxe Ganga Thali', text)
            self.assertIn('₹290', text)
            self.assertIn('₹260', text)
            self._assert_aligned_price_columns(text,
                                               ['Paneer Butter Masala', 'Shahi Paneer'])
            self.assertLessEqual(
                max(len(row) for block in re.findall(r'\x60\x60\x60\n(.*?)\n\x60\x60\x60', text, re.S)
                    for row in block.splitlines()), 34)
        self.kitchen.assert_not_called()
        self.assertEqual(self.sheet.append_count, 0)

    def test_legacy_full_menu_price_alignment_preserves_duplicates_filter(self):
        source = {
            'coffee': ('Hot Coffee', 40),
            'naan': ('Butter Naan', 60),
            'paneer': ('Paneer Butter Masala', 260),
            'rice': ('Jeera Rice', 140),
        }
        with patch.object(app, 'get_hotel_data', return_value=''), \
                patch.object(app, 'get_hotel_menu', return_value=source), \
                patch.object(app, 'get_hotel_name', return_value='Demo Hotel'):
            cards = app._full_menu_presentation_messages(include_prices=True)
            content = '\n'.join(cards)
            self.assertIn('\x60\x60\x60', content)
            self.assertIn('₹60', content)
            self.assertIn('₹260', content)
            self.assertNotIn('• Butter Naan — ₹60', content)

    def test_semantic_first_receives_contextual_price_followup_once(self):
        import json
        from pathlib import Path
        config = json.loads(Path(__file__).with_name('customer_config.json').read_text(encoding='utf-8'))
        self.assertTrue(config['demo_semantic_first'])
        with patch.object(app, 'CUSTOMER_CONFIG', config):
            with patch.object(app, 'understand_guest_request') as brain:
                brain.return_value = {
                    'action': 'SHOW_MENU', 'menu_section': 'BREAKFAST',
                    'show_prices': False, 'confidence': 0.93,
                }
                app._process_and_reply({'text': {'body': 'Subah nashta kya milega?'}},
                                       self.phone, 'text')
                self.assertEqual(brain.call_count, 1)
                self.assertIn('Poha', self.reply())
                self.assertNotIn('₹70', self.reply())
                self.assertTrue(any(
                    x.get('role') == 'assistant' and 'BREAKFAST' in x.get('content', '')
                    for x in app.get_conversation_history(self.phone)
                ))
                self.sent.reset_mock()
                brain.return_value = {
                    'action': 'SHOW_MENU', 'menu_section': 'BREAKFAST',
                    'show_prices': True, 'confidence': 0.93,
                }
                app._process_and_reply({'text': {'body': 'Aur unke paise bhi?'}},
                                       self.phone, 'text')
                self.assertEqual(brain.call_count, 2)
                self.assertIn('₹70', self.reply())
                self.assertIn('\x60\x60\x60', self.reply())
                self.assertEqual(self.sheet.append_count, 0)
        self.kitchen.assert_not_called()

    def test_semantic_answer_is_not_hijacked_by_food_word(self):
        semantic = {'action': 'ANSWER', 'confidence': 0.95,
                    'reply': 'Ji, dinner options bata sakti hoon. Kya jaana chahenge?'}
        self.assertFalse(self.demo.handle(app, self.phone,
                                          'Food delivery me jobs kya hoti hain?', semantic=semantic))
        self.sent.assert_not_called()
        self.book.worksheet.assert_not_called()

    def test_ai_one_veg_pulao_leke_aa_gets_safe_cart_and_itemized_bill(self):
        import json
        from pathlib import Path
        config = json.loads(Path(__file__).with_name('customer_config.json').read_text(encoding='utf-8'))
        with patch.object(app, 'CUSTOMER_CONFIG', config):
            interpretation = {
                'action': 'ORDER', 'confidence': 0.95,
                'items': [{'name': 'Veg Pulao', 'qty': 1}],
            }
            self.assertTrue(self.demo.handle(app, self.phone, 'Veg pulao leke aa', semantic=interpretation))
            reply = self.reply()
            self.assertIn('1 x Veg Pulao', reply)
            self.assertIn('₹170', reply)
            self.assertIn('CONFIRM', reply)
            self.assertEqual(self.sheet.append_count, 0)
            self.kitchen.assert_not_called()
            self.assertTrue(self.turn('confirm'))
            self.assertEqual(self.sheet.append_count, 1)
            self.turn('bill')
            self.assertIn('Food total: Rs. 170', self.reply())

    def test_ai_recovers_followup_likha_to_hua_veg_pulao(self):
        import json
        from pathlib import Path
        config = json.loads(Path(__file__).with_name('customer_config.json').read_text(encoding='utf-8'))
        with patch.object(app, 'CUSTOMER_CONFIG', config):
            interpretation = {
                'action': 'ORDER_SELECTION', 'confidence': 0.95,
                'items': [{'name': 'Veg Pulao', 'qty': 1}],
            }
            self.assertTrue(self.demo.handle(app, self.phone, 'Likha to hua veg pulao', semantic=interpretation))
            self.assertIn('1 x Veg Pulao', self.reply())
            self.assertEqual(self.sheet.append_count, 0)
        self.kitchen.assert_not_called()

    def test_verified_ai_typo_matches_menu_but_guest_must_confirm(self):
        import json
        from pathlib import Path
        config = json.loads(Path(__file__).with_name('customer_config.json').read_text(encoding='utf-8'))
        with patch.object(app, 'CUSTOMER_CONFIG', config):
            semantic = {
                'action': 'ORDER', 'confidence': 0.92,
                'items': [{'name': 'Veg Pulaav', 'qty': 1}],
            }
            self.assertTrue(self.demo.handle(app, self.phone, 'Veg pulaav le aao', semantic=semantic))
            self.assertIn('Veg Pulao', self.reply())
            self.assertIn('samjha', self.reply())
            self.assertIn('CONFIRM', self.reply())
            self.assertEqual(self.sheet.append_count, 0)
        self.kitchen.assert_not_called()

    def test_uncertain_similar_dishes_request_clarification_no_cart(self):
        import json
        from pathlib import Path
        config = json.loads(Path(__file__).with_name('customer_config.json').read_text(encoding='utf-8'))
        with patch.object(app, 'CUSTOMER_CONFIG', config):
            semantic = {
                'action': 'ORDER', 'confidence': 0.93,
                'items': [{'name': 'Paneer', 'qty': 1}],
            }
            self.assertTrue(self.demo.handle(app, self.phone, 'Paneer bhejo', semantic=semantic))
            self.assertIn('clear nahi', self.reply())
            self.assertNotIn(self.phone, app.demo_food_sessions)
            self.assertEqual(self.sheet.append_count, 0)
        self.kitchen.assert_not_called()

    def test_ai_never_partially_accepts_unsupported_dishes_or_bad_quantity(self):
        import json
        from pathlib import Path
        config = json.loads(Path(__file__).with_name('customer_config.json').read_text(encoding='utf-8'))
        with patch.object(app, 'CUSTOMER_CONFIG', config):
            for interpretation in [
                {'action': 'ORDER', 'confidence': .96, 'items': [
                    {'name': 'Veg Pulao', 'qty': 1}, {'name': 'Pizza', 'qty': 1}]},
                {'action': 'ORDER', 'confidence': .96, 'items': [
                    {'name': 'Veg Pulao', 'qty': 0}]},
                {'action': 'ORDER', 'confidence': .96, 'items': [
                    {'name': 'Veg Pulao', 'qty': 1.5}]},
                {'action': 'ORDER', 'confidence': .96, 'items': [
                    {'name': 'Veg Pulao', 'qty': 60}]},
            ]:
                with self.subTest(interpretation=interpretation):
                    self.assertTrue(self.demo.handle(
                        app, self.phone, 'food items bhejo', semantic=interpretation))
                    self.assertNotIn(self.phone, app.demo_food_sessions)
                    self.assertEqual(self.sheet.append_count, 0)
        self.kitchen.assert_not_called()

    def test_fallback_known_dish_leke_aa_without_explicit_quantity(self):
        import json
        from pathlib import Path
        config = json.loads(Path(__file__).with_name('customer_config.json').read_text(encoding='utf-8'))
        with patch.object(app, 'CUSTOMER_CONFIG', config):
            self.assertTrue(self.turn('Veg Pulao leke aa'))
            self.assertIn('1 x Veg Pulao', self.reply())
            self.assertEqual(self.sheet.append_count, 0)
        self.kitchen.assert_not_called()

    def test_real_text_router_uses_ai_order_once_not_second_old_parser(self):
        import json
        from pathlib import Path
        config = json.loads(Path(__file__).with_name('customer_config.json').read_text(encoding='utf-8'))
        with patch.object(app, 'CUSTOMER_CONFIG', config):
            with patch.object(app, 'understand_guest_request', return_value={
                'action': 'ORDER', 'confidence': .95,
                'items': [{'name': 'Veg Pulao', 'qty': 1}]
            }) as brain:
                app._process_and_reply({'text': {'body': 'Veg pulao leke aa'}},
                                       self.phone, 'text')
                brain.assert_called_once()
                self.assertIn('1 x Veg Pulao', self.reply())
                self.assertEqual(self.sheet.append_count, 0)
        self.kitchen.assert_not_called()

    def test_semantic_hallucinated_item_cannot_create_demo_order(self):
        semantic = {
            'action': 'ORDER', 'confidence': 0.96,
            'items': [{'name': 'Pizza', 'qty': 99}],
        }
        self.assertTrue(self.demo.handle(app, self.phone,
                                         'Ek pizza order karo', semantic=semantic))
        self.assertIn('clear nahi', self.reply())
        self.assertEqual(self.sheet.append_count, 0)
        self.assertNotIn(self.phone, app.demo_food_sessions)
        self.kitchen.assert_not_called()

    def test_ai_unavailable_demo_menu_uses_local_fallback_no_retry(self):
        config = dict(app.CUSTOMER_CONFIG)
        config['demo_semantic_first'] = True
        with patch.object(app, 'CUSTOMER_CONFIG', config):
            with patch.object(app, 'understand_guest_request', return_value=None) as brain:
                app._process_and_reply({'text': {'body': 'menu'}}, self.phone, 'text')
                brain.assert_called_once()
                self.assertIn('menu', self.reply().lower())
        self.kitchen.assert_not_called()

    def test_pending_confirm_remains_deterministic_and_single_sheet_append(self):
        config = dict(app.CUSTOMER_CONFIG)
        config['demo_semantic_first'] = True
        with patch.object(app, 'CUSTOMER_CONFIG', config):
            self.turn('2 Masala Chai')
            with patch.object(app, 'understand_guest_request') as brain:
                app._process_and_reply({'text': {'body': 'confirm'}}, self.phone, 'text')
                brain.assert_not_called()
                self.assertEqual(self.sheet.append_count, 1)
                self.assertIn('save ho gaya', self.reply())
                app._process_and_reply({'text': {'body': 'confirm'}}, self.phone, 'text')
                self.assertEqual(self.sheet.append_count, 1)
        self.kitchen.assert_not_called()

    def test_semantic_json_schema_preserves_show_prices_boolean(self):
        schema = app._openai_semantic_schema()
        self.assertEqual(schema['properties']['show_prices']['type'], 'boolean')
        self.assertIn('show_prices', schema['required'])
        with patch.object(app, '_ai_provider_functions', return_value=[
            ('mock', lambda *args, **kwargs:
             '{"action":"SHOW_MENU","menu_section":"BREAKFAST","show_prices":true,"confidence":0.9}')
        ]):
            result = app.understand_guest_request('Breakfast ke paise batao', None, self.phone)
            self.assertTrue(result['show_prices'])
            self.assertEqual(result['menu_section'], 'BREAKFAST')

    def test_hinglish_paise_ke_sath_always_shows_breakfast_prices(self):
        import json
        from pathlib import Path
        config = json.loads(Path(__file__).with_name('customer_config.json').read_text(encoding='utf-8'))
        with patch.object(app, 'CUSTOMER_CONFIG', config):
            cases = [
                ('Breakfast ke options paise ke sath batao', 'Poha', '₹70'),
                ('Breakfast ke rates batao', 'Masala Chai', '₹30'),
                ('Nashta rupaye ke saath dikhao', 'Paneer Paratha', '₹130'),
                ('Breakfast के दाम बताओ', 'Poha', '₹70'),
                ('Lunch ki kimat batao', 'Butter Naan', '₹60'),
                ('Dinner menu with prices', 'Shahi Paneer', '₹240'),
            ]
            for prompt, dish, cost in cases:
                with self.subTest(prompt=prompt):
                    self.sent.reset_mock()
                    self.assertTrue(self.turn(prompt))
                    reply = '\n'.join(call.args[1] for call in self.sent.call_args_list)
                    self.assertIn(dish, reply)
                    self.assertIn(cost, reply)
                    self.assertIn('\x60\x60\x60', reply)
            self.sent.reset_mock()
            self.assertTrue(self.turn('Breakfast ke options batao'))
            without = '\n'.join(call.args[1] for call in self.sent.call_args_list)
            self.assertIn('Poha', without)
            self.assertNotIn('₹70', without)
            self.assertNotIn('\x60\x60\x60', without)
        self.assertEqual(self.sheet.append_count, 0)
        self.kitchen.assert_not_called()

    def test_shared_price_intent_uses_whole_words_not_timing_questions(self):
        for phrase in [
            'paise ke sath', 'paisa kitna', 'paiso ke sath', 'rupaye me batao',
            'dinner ka daam', 'kitni ki', 'rate', 'cost', '₹', 'पैसे', 'दाम', 'कीमत',
        ]:
            with self.subTest(phrase=phrase):
                self.assertTrue(app.explicitly_asks_price(phrase))
        for phrase in [
            'Breakfast ke options batao', 'Dinner me kya hai',
            'breakfast kitne baje hota hai', 'lunch timing',
        ]:
            with self.subTest(phrase=phrase):
                self.assertFalse(app.explicitly_asks_price(phrase))

    def test_meal_price_menu_keeps_original_configured_rates(self):
        import json
        from pathlib import Path
        config = json.loads(Path(__file__).with_name('customer_config.json').read_text(encoding='utf-8'))
        with patch.object(app, 'CUSTOMER_CONFIG', config):
            self.turn('dinner menu with prices')
            text = '\n'.join(c.args[1] for c in self.sent.call_args_list)
            self.assertIn('Butter Naan', text)
            self.assertIn('Shahi Paneer', text)
            self.assertIn('₹60', text)
            self.assertIn('₹240', text)
            self.assertIn('```', text)
            self._assert_aligned_price_columns(text, ['Butter Naan', 'Plain Naan', 'Garlic Naan'])
            self.assertNotIn('• Poha', text)
        self.assertEqual(self.sheet.append_count, 0)
        self.kitchen.assert_not_called()

    def test_legacy_fallback_meal_card_is_grouped_too(self):
        sample = {
            'dal': ('Dal Tadka', 160),
            'naan': ('Butter Naan', 60),
            'rice': ('Jeera Rice', 140),
            'raita': ('Boondi Raita', 70),
            'poha': ('Poha', 70),
        }
        with patch.object(app, 'get_hotel_data', return_value=''), \
                patch.object(app, 'get_hotel_menu', return_value=sample), \
                patch.object(app, 'get_hotel_name', return_value='Hotel Shreya Galaxy'):
            result = app._menu_section_message('DINNER', include_prices=True, sender_phone=self.phone)
            self.assertIn('🌙 *Hotel Shreya Galaxy*', result)
            self.assertIn('🍲 *Sabzi & Dal*', result)
            self.assertIn('🫓 *Roti & Naan*', result)
            self.assertIn('🍚 *Rice*', result)
            self.assertIn('🥗 *Raita & Sides*', result)
            self.assertIn('Butter Naan', result)
            self.assertIn('₹60', result)
            self.assertIn('```', result)
            self._assert_aligned_price_columns(result, ['Butter Naan', 'Jeera Rice', 'Dal Tadka'], group_separately=True)
            self.assertNotIn('• Poha', result)
            self.assertIn('Jaise: 2 Butter Naan + 1 Dal Tadka', result)
        self.kitchen.assert_not_called()

    def test_full_menu_is_pretty_grouped_and_complete_once(self):
        import json
        from pathlib import Path
        config = json.loads(Path(__file__).with_name('customer_config.json').read_text(encoding='utf-8'))
        with patch.object(app, 'CUSTOMER_CONFIG', config):
            self.turn('menu')
            bubbles = [call.args[1] for call in self.sent.call_args_list]
            self.assertGreaterEqual(len(bubbles), 4)
            combined = '\n'.join(bubbles)
            for item in config['menu']:
                self.assertEqual(combined.count('• ' + item['name'] + '\n'), 1, item['name'])
            self.assertIn('━━━━━━━━', combined)
            self.assertIn('DEMO menu', combined)
            self.assertNotIn('₹60', combined)  # only show prices when requested
            self.assertEqual(self.sheet.append_count, 0)
            self.sent.reset_mock()
            self.turn('menu with prices')
            self.assertIn('₹60', '\n'.join(c.args[1] for c in self.sent.call_args_list))

    def test_pretty_food_only_bill_from_verified_sheet_rows(self):
        self.turn('2 Masala Chai aur 1 Poha')
        self.turn('confirm')
        self.turn('bill')
        bill = self.reply()
        self.assertIn('🧾', bill)
        self.assertIn('🍽️', bill)
        self.assertIn('GRAND TOTAL (FOOD ONLY)', bill)
        self.assertIn('₹130', bill)
        self.assertIn('2 x Masala Chai', bill)
        self.assertIn('1 x Poha', bill)
        self.assertNotIn('Room: ', bill)
        self.assertNotIn('BALANCE DUE', bill)
        self.kitchen.assert_not_called()

    def test_dinner_time_query_is_left_to_normal_hotel_reception(self):
        self.assertFalse(self.turn('dinner ka time kya hai'))
        self.assertFalse(self.turn('breakfast kab milega'))
        self.book.worksheet.assert_not_called()

    def test_tampered_saved_food_amount_never_generates_false_bill(self):
        self.turn('1 Poha')
        self.turn('confirm')
        self.sheet.rows[1][5] = '999'
        self.turn('bill')
        self.assertIn('verify nahi', self.reply())
        self.assertNotIn('₹999', self.reply())



if __name__ == '__main__':
    unittest.main()
