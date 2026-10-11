"""The real-model harness must never reach application mutation surfaces."""
import os
import unittest
from unittest.mock import Mock, patch
os.environ['BOT_AUTOSTART'] = '0'
import app
import guest_checks


class GuestChecksTests(unittest.TestCase):
    def test_reference_and_current_price_assertions_catch_wrong_answers(self):
        case = guest_checks.scenarios()[2]
        config = {'menu': [{'name':'Standard Veg Thali'}, {'name':'Special Deluxe Ganga Thali'}]}
        bad = {'action':'MENU_ITEM_INFO','language':'hinglish','show_prices':True, 'operation_text':'', 'confidence':.95,
               'items':[{'name':'Standard Veg Thali','qty':1}]}
        errors = guest_checks.errors_for(case, bad, config)
        self.assertIn('Wrong current-turn price flag', errors)
        self.assertIn('Repeated previous item instead of alternatives', errors)
        good = dict(bad, show_prices=False, items=[{'name':'Special Deluxe Ganga Thali','qty':1}])
        self.assertEqual(guest_checks.errors_for(case, good, config), [])

    def test_price_followup_rejects_extra_items(self):
        case = guest_checks.scenarios(demo=False)[28]
        obj = {'action':'MENU_ITEM_INFO','language':'hindi','show_prices':True,
               'confidence':.95,'operation_text':'',
               'items':[{'name':'Standard Veg Thali','qty':1},
                        {'name':'Special Deluxe Ganga Thali','qty':1}]}
        self.assertIn('Items outside requested references',
                      guest_checks.errors_for(case, obj, app.CUSTOMER_CONFIG))

    def test_operational_scenario_renders_fixture_without_executing_any_action(self):
        case = guest_checks.scenarios()[23]
        obj = {'action':'ORDER_CONFIRM','language':'hinglish','understood_as':'Explicit cart confirmation'}
        with patch.object(app, 'ask_ai_chat', return_value=None), \
             patch.object(app, 'send_whatsapp_message', side_effect=AssertionError('Real WhatsApp send')), \
             patch.object(app, 'get_gspread_client', side_effect=AssertionError('Real Sheets access')), \
             patch.object(app, '_process_and_reply', side_effect=AssertionError('Real executor')):
            reply = guest_checks.render(app, case, obj)
        self.assertIn('DEMO-ABC123', reply)
        self.assertIsNone(guest_checks.ai.current.get())

    def test_information_reply_is_actual_model_output_not_safe_fixture(self):
        case = guest_checks.scenarios()[26]
        with patch.object(app, 'ask_ai_chat', side_effect=AssertionError('Reply replaced')), \
             patch.object(app, 'send_whatsapp_message', side_effect=AssertionError('Real send')):
            reply = guest_checks.render(app, case, {'action':'ANSWER', 'reply':'Payment marked paid incorrectly'})
        self.assertEqual(reply, 'Payment marked paid incorrectly')

    def test_privacy_and_invalid_payment_cannot_pass_with_staff_handoff(self):
        for case in guest_checks.scenarios()[25:27]:
            for action in ('RECEPTION', 'ANSWER'):
                with self.subTest(case=case['id'], action=action):
                    obj = {'action':action,'needs_reception':True,'language':'hinglish',
                           'operation_text':'', 'confidence':.95,'items':[]}
                    self.assertTrue(guest_checks.errors_for(case, obj, app.CUSTOMER_CONFIG))

    def test_thirty_distinct_scenarios_run_and_log_without_transport(self):
        cases = guest_checks.scenarios()
        self.assertEqual(len(cases), 30)
        self.assertEqual(len({case['id'] for case in cases}), 30)
        with patch.object(app, 'ask_groq_chat', return_value=None), \
             patch.object(app, 'send_whatsapp_message', side_effect=AssertionError('Real WhatsApp send')), \
             patch.object(app, 'get_gspread_client', side_effect=AssertionError('Real Sheets access')), \
             patch.object(guest_checks.time, 'sleep'), patch('builtins.print'):
            results = guest_checks.run(app, 'unit', delay=0)
        self.assertEqual(len(results), len(guest_checks.scenarios(demo=app.CUSTOMER_DEMO_MODE)))
        self.assertTrue(all(not row['passed'] for row in results))


if __name__ == '__main__':
    unittest.main()
