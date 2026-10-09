"""Demo food flow uses fake Sheets and temporary SQLite; no real notifications."""
import importlib
import os
import tempfile
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
        config = {'demo_mode':True, 'demo_food_enabled':True,
                  'menu':[{'name':'Masala Chai','price':30},{'name':'Poha','price':70}, {'name':'Butter Naan','price':40}]}
        self.sent = Mock(return_value=True)
        self.kitchen = Mock(side_effect=AssertionError('Real kitchen must not be alerted'))
        values = {'CUSTOMER_DEMO_MODE':True, 'CUSTOMER_CONFIG':config,
                  'HOTEL_CONFIG_CACHE':{'signature':None,'data':None},
                  'demo_food_sessions':{}, 'durable_store':self.store,
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

    def test_conflicting_headers_preserve_sheet_and_report_failure(self):
        self.sheet.rows[0][0]='Unrelated data'
        self.turn('1 Poha'); self.turn('confirm')
        self.assertEqual(self.sheet.append_count,0)
        self.assertIn('confirm nahi',self.reply())


if __name__ == '__main__':
    unittest.main()
