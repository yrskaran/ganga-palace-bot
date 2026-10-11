"""AI boundary regressions use fake transports/providers, real dispatch logic."""
import os
import time
import unittest
from unittest.mock import patch, Mock
os.environ['BOT_AUTOSTART'] = '0'
import app
import ai_receptionist as gateway


class ReceptionistBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.real_send = app.send_whatsapp_message
        self.patches = []
        for name, value in {
            'CUSTOMER_CONFIG': {'ai_receptionist_flow': True},
            'CUSTOMER_DEMO_MODE': True, 'guest_language_cache': {},
            'reception_request_sessions': {}, 'checkin_sessions': {},
            'order_sessions': {}, 'duplicate_order_sessions': {},
            'service_tasks_by_id': {}, 'service_guest_pending': {},
            'demo_food_sessions': {}, 'demo_guest_sessions': {},
            'conversation_memory': {}, 'get_guest_stay_status': Mock(return_value=None),
            'refresh_staff_roster': Mock(), 'fetch_sheet_data_sync': Mock(return_value=False),
            'send_whatsapp_message': Mock(return_value=True),
            'ask_ai_chat': Mock(return_value='AI result'),
        }.items():
            p = patch.object(app, name, value)
            p.start(); self.patches.append(p)
        self.phone = '919555555555'

    def tearDown(self):
        for p in reversed(self.patches): p.stop()

    def understanding(self, **values):
        return dict({'action': 'ANSWER', 'reply': 'AI ne poori baat samjhi.',
                     'language': 'hinglish', 'confidence': 0.95}, **values)

    def test_live_readiness_uses_one_read_only_contract_probe(self):
        import json
        with patch.object(app, 'GROQ_API_KEY', 'test'), patch.object(app, 'ask_groq_chat',
            return_value=json.dumps(self.understanding(action='RECEPTION', operation_text=''))) as provider:
            app.check_ai_readiness()
        provider.assert_called_once()
        self.assertEqual(app.AI_READINESS['status'], 'available')
        app.send_whatsapp_message.assert_not_called()

    def test_enabled_router_bypasses_keyword_and_language_shortcuts(self):
        result = self.understanding()
        with patch.object(app, 'understand_guest_request', return_value=result) as brain, \
             patch.object(app, 'find_menu_items', side_effect=AssertionError('raw question parsed by Python')), \
             patch.object(app, 'remember_guest_language', side_effect=AssertionError('language guessed by Python')):
            app._process_and_reply({'text': {'body': 'Dudh manga, dish nahi'}}, self.phone, 'text')
        brain.assert_called_once()
        self.assertEqual(app.send_whatsapp_message.call_args.args[1], result['reply'])

    def test_ai_answer_bypasses_pending_cart(self):
        app.order_sessions[self.phone] = {'order': '1 Poha', 'total': 70}
        gateway.handle(app, self.phone, 'Pehle wifi batao', None, semantic=self.understanding())
        self.assertEqual(app.order_sessions[self.phone]['total'], 70)
        self.assertEqual(app.send_whatsapp_message.call_args.args[1], 'AI ne poori baat samjhi.')

    def test_identity_also_goes_through_ai(self):
        with patch.object(app, 'handle_room_cleaning_message', return_value=False), \
             patch.object(app, 'handle_service_staff_message', return_value=False), \
             patch.object(app, 'handle_reception_operator_message', return_value=False), \
             patch.object(app, 'maybe_react_to_guest_message'), \
             patch.object(app, 'understand_guest_request', return_value=self.understanding(reply='Main Monika hoon.')) as brain:
            app.process_and_reply({'text': {'body': 'aapka naam kya hai'}}, self.phone, 'text')
        brain.assert_called_once()
        self.assertEqual(app.send_whatsapp_message.call_args.args[1], 'Main Monika hoon.')

    def test_composer_cannot_swap_menu_item_prices(self):
        source = 'Menu\nPoha Rs. 70\nChai Rs. 30'
        self.assertFalse(gateway.faithful_numbers_and_links(source, 'Menu\nPoha Rs. 30\nChai Rs. 70'))
        self.assertTrue(gateway.faithful_numbers_and_links(source, 'Ji, yeh menu hai:\nPoha Rs. 70\nChai Rs. 30'))

    def test_guest_transport_uses_ai_composed_result(self):
        # Restore the real send boundary while keeping the network fake.
        from unittest.mock import patch
        real_send = self.real_send
        token = gateway.current.set({'phone': self.phone, 'text': 'hisaab',
            'language': 'hinglish', 'meaning': 'asks for bill'})
        response = Mock(status_code=200)
        try:
            app.ask_ai_chat.return_value = 'Ji, Rs. 70 hai.'
            app.ask_ai_chat.side_effect = ['Ji, Rs. 70 hai.', '{"supported":true}']
            with patch.object(app, 'whatsapp_request', return_value=response) as transport:
                self.assertTrue(real_send(self.phone, 'Total Rs. 70'))
            self.assertEqual(transport.call_args.args[0]['text']['body'], 'Ji, Rs. 70 hai.')
        finally: gateway.current.reset(token)

    def test_ai_unavailable_never_runs_legacy_actions(self):
        with patch.object(app, 'understand_guest_request', return_value=None), \
             patch.object(app, '_process_and_reply') as executor:
            gateway.handle(app, self.phone, '2 Poha bhejo', None)
        executor.assert_not_called()

    def test_order_executor_receives_canonical_items_not_guest_utterance(self):
        with patch.object(app, '_process_and_reply') as executor:
            gateway.handle(app, self.phone, 'do pohe laana', None, semantic=self.understanding(
                action='ORDER', items=[{'name': 'Poha', 'qty': 2}]))
        self.assertEqual(executor.call_args.args[0]['text']['body'], '2 Poha')
        self.assertTrue(executor.call_args.kwargs['_executor'])

    def test_side_question_cannot_become_checkin_name(self):
        app.checkin_sessions[self.phone] = {'step': 'NAME', 'created': time.time()}
        gateway.handle(app, self.phone, 'Room ka rate kya hai?', None, semantic=self.understanding())
        self.assertNotIn('name', app.checkin_sessions[self.phone])

    def test_checkin_details_only_accept_verified_otp(self):
        app.checkin_sessions[self.phone] = {'step': 'OTP', 'otp': '1234', 'created': time.time()}
        gateway.handle(app, self.phone, 'mera code 9999', None, semantic=self.understanding(
            action='CHECKIN_DETAILS', operation_text='9999'))
        self.assertEqual(app.checkin_sessions[self.phone]['step'], 'OTP')
        gateway.handle(app, self.phone, '1234', None, semantic=self.understanding(
            action='CHECKIN_DETAILS', operation_text='1234'))
        self.assertEqual(app.checkin_sessions[self.phone]['step'], 'NAME')

    def test_composer_preserves_backend_price_and_rejects_invented_price(self):
        token = gateway.current.set({'phone': self.phone, 'text': 'hisaab batao',
            'language': 'hinglish', 'meaning': 'asks for verified bill'})
        try:
            app.ask_ai_chat.return_value = 'Ji, total Rs. 80 hai.'
            self.assertEqual(gateway.compose(app, self.phone, 'Total Rs. 70'), 'Total Rs. 70')
            app.ask_ai_chat.return_value = 'Ji, total Rs. 70 hai.'
            app.ask_ai_chat.side_effect = ['Ji, total Rs. 70 hai.', '{"supported":true}']
            self.assertEqual(gateway.compose(app, self.phone, 'Total Rs. 70'), 'Ji, total Rs. 70 hai.')
        finally:
            gateway.current.reset(token)

    def test_composer_rejects_failed_write_becoming_confirmed(self):
        token = gateway.current.set({'phone': self.phone, 'text': 'confirm',
            'language': 'english', 'meaning': 'confirm order'})
        try:
            source = 'Order save failed. No order was created.'
            app.ask_ai_chat.side_effect = ['Your order was saved and confirmed.', '{"supported":false}']
            self.assertEqual(gateway.compose(app, self.phone, source), source)
        finally: gateway.current.reset(token)

    def test_provider_language_instructions_do_not_force_old_cache(self):
        app.guest_language_cache[self.phone] = 'english'
        messages = app._openai_messages(app._ai_understanding_prompt('Cow milk milega?', None, self.phone), sender_phone=self.phone, structured=True)
        high_priority = '\n'.join(m['content'] for m in messages if m['role'] in {'system', 'developer'})
        self.assertNotIn('Reply naturally and politely in English.', high_priority)
        self.assertIn('Infer the guest language', high_priority)

    def test_service_feedback_retains_explicit_ticket_id(self):
        app.service_tasks_by_id.clear()
        for ticket in ('S-ABCDEF', 'S-123ABC'):
            app.service_tasks_by_id[ticket] = {'request_id':ticket, 'guest_phone':self.phone, 'status':'STAFF_COMPLETED'}
        with patch.object(app, '_update_service_task_sheet', return_value=True):
            gateway.handle(app, self.phone, 'S-ABCDEF ho gaya', None, semantic=self.understanding(
                action='SERVICE_FEEDBACK', operation_text='yes', task_id='S-ABCDEF'))
        self.assertEqual(app.service_tasks_by_id['S-ABCDEF']['status'], 'COMPLETED')
        self.assertEqual(app.service_tasks_by_id['S-123ABC']['status'], 'STAFF_COMPLETED')

    def test_interpreter_receives_pending_checkin_without_secret_otp(self):
        app.checkin_sessions[self.phone] = {'step': 'OTP', 'otp': '1234', 'created': time.time()}
        state = gateway.snapshot(app, self.phone)
        self.assertEqual(state['checkin_sessions']['step'], 'OTP')
        self.assertNotIn('otp', state['checkin_sessions'])


if __name__ == '__main__': unittest.main()
