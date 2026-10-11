"""Offline tests for reception replies, restart-safe ticket mapping, and verified FAQ memory."""
import os
import time
import unittest
from unittest.mock import Mock, patch

os.environ["BOT_AUTOSTART"] = "0"
import app


class ReceptionMemoryTests(unittest.TestCase):
    def setUp(self):
        app.reception_requests_by_id.clear()
        app.reception_requests_by_alert.clear()
        app.reception_request_sessions.clear()
        app.reception_knowledge_cache.clear()
        app.reception_knowledge_loaded_at = 0.0

    def test_mixed_milk_question_keeps_hinglish(self):
        phone = 'language-test'
        with patch.object(app, 'guest_language_cache', {}):
            app.remember_guest_language(phone, 'Dudh milega?')
            self.assertEqual(app.remember_guest_language(phone, 'Cow milk milega?'), 'hinglish')

    def test_accepted_reception_alert_does_not_claim_delivery(self):
        phone = '919555555555'
        def notify(*args):
            app.reception_request_sessions[phone] = {
                'request': 'Cow milk milega?', 'status': 'pending',
                'delivery_status': 'accepted', 'created': time.time()}
            return True
        with patch.object(app, 'notify_reception_request', side_effect=notify), \
             patch.object(app, 'get_guest_response_language', return_value='hinglish'), \
             patch.object(app, 'send_whatsapp_message', return_value=True) as send:
            app.reply_to_reception_request(phone, None, 'Cow milk milega?')
        reply = send.call_args.args[1]
        self.assertIn('Cow milk', reply)
        self.assertIn('delivery', reply.lower())
        self.assertNotIn('request bhej di', reply)

    def test_semantic_followup_preserves_request_and_does_not_resend(self):
        phone = '919555555555'
        app.reception_request_sessions[phone] = {
            'request': 'Cow milk milega?', 'status': 'pending',
            'delivery_status': 'delivered', 'created': time.time()}
        with patch.object(app, 'notify_reception_request') as notify, \
             patch.object(app, 'get_guest_response_language', return_value='hinglish'), \
             patch.object(app, 'send_whatsapp_message', return_value=True) as send:
            handled = app.handle_reception_request_followup(phone, 'Puch ke batao', semantic={
                'action': 'RECEPTION', 'reception_followup': True, 'confidence': 0.95})
        self.assertTrue(handled)
        self.assertIn('Cow milk', send.call_args.args[1])
        notify.assert_not_called()

    def test_semantic_new_question_is_not_hijacked_by_old_ticket(self):
        phone = '919555555555'
        app.reception_request_sessions[phone] = {
            'request': 'Cow milk milega?', 'status': 'pending', 'created': time.time()}
        with patch.object(app, 'send_whatsapp_message') as send:
            handled = app.handle_reception_request_followup(phone, 'Reception ka number kya hai?', semantic={
                'action': 'ANSWER', 'reception_followup': False, 'confidence': 0.95})
        self.assertFalse(handled)
        send.assert_not_called()

    def test_only_stable_confirmed_facts_are_reusable(self):
        self.assertTrue(app._reception_answer_is_reusable(
            "Swimming pool ke timings kya hain", "Pool is open from 6 AM to 8 PM."
        ))
        self.assertFalse(app._reception_answer_is_reusable(
            "Aaj room available hai?", "Yes, one room is available today."
        ))
        self.assertFalse(app._reception_answer_is_reusable(
            "Room service bhej do", "Staff has been informed."
        ))

    def test_cached_faq_matches_a_close_paraphrase(self):
        app.reception_knowledge_cache[:] = [{
            "question": "Swimming pool ke timings kya hain",
            "question_key": app._reception_question_key("Swimming pool ke timings kya hain"),
            "answer": "Pool is open from 6 AM to 8 PM.",
            "expires": time.time() + 86400,
        }]
        app.reception_knowledge_loaded_at = time.time()
        match = app._lookup_reception_knowledge("Swimming pool ka time kya hai?")
        self.assertIsNotNone(match)
        self.assertEqual(match["answer"], "Pool is open from 6 AM to 8 PM.")

    def test_reception_reply_forwards_and_saves_verified_answer(self):
        request_id = "R-ABC123"
        app.reception_requests_by_id[request_id] = {
            "request_id": request_id, "guest_phone": "919555555555",
            "request": "Swimming pool ke timings kya hain",
            "room": "203", "reception_phone": "919222222222",
            "created": time.time(), "status": "pending",
        }
        message = {
            "id": "staff-reply-1",
            "context": {"id": "alert-1"},
            "text": {"body": "Pool 6 AM se 8 PM tak open hai."},
        }
        with patch.object(app, "_find_reception_request_by_alert_id",
                          return_value=("919555555555", dict(app.reception_requests_by_id[request_id]))), \
             patch.object(app, "get_guest_response_language", return_value="hinglish"), \
             patch.object(app, "send_whatsapp_message", return_value=True) as send, \
             patch.object(app, "_persist_reception_request", return_value=True) as persist, \
             patch.object(app, "_save_reception_knowledge", return_value=True) as learn:
            handled = app.handle_reception_operator_message(
                message, "919222222222", "text"
            )
        self.assertTrue(handled)
        self.assertIn("Pool 6 AM se 8 PM tak open hai.", send.call_args_list[0].args[1])
        persist.assert_called_once()
        learn.assert_called_once_with(
            "Swimming pool ke timings kya hain",
            "Pool 6 AM se 8 PM tak open hai.", request_id,
        )


    def test_demo_checkin_id_question_is_not_a_room_options_intent(self):
        with patch.object(app, "CUSTOMER_DEMO_MODE", True), \
             patch.object(app, "CUSTOMER_CONFIG", {"demo_semantic_first": True}):
            prompt = app._ai_understanding_prompt(
                "I'd kaun kaun se chalengi?", None, "919555555555"
            )
        self.assertIn("ID/identity-proof questions", prompt)
        self.assertIn("never room options", prompt)
        self.assertIn("demo check-in needs no ID", prompt)
        self.assertIn("use RECEPTION with needs_reception=true", prompt)

    def test_delivery_callback_does_not_lookup_sheet_for_unmapped_messages(self):
        with patch.object(app, "_find_reception_request_by_alert_id") as lookup, \
             patch.object(app, "_persist_reception_request") as persist:
            app._update_reception_alert_delivery("wamid-unrelated", "delivered", [])
        lookup.assert_not_called()
        persist.assert_not_called()


if __name__ == "__main__":
    unittest.main()
