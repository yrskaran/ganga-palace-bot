"""Regression checks for isolated hotel-knowledge-only AI mode."""
import os
os.environ["BOT_AUTOSTART"] = "0"

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import app
import ai_context
import durable_runtime


class KnowledgeOnlyModeTests(unittest.TestCase):
    phone = "919555556666"

    def test_staff_operators_and_legacy_executor_are_unreachable(self):
        message = {"type": "text", "text": {"body": "Room 201 mein towel bhejo"}}
        with patch.object(app, "KNOWLEDGE_ONLY_MODE", True), \
             patch.object(app.knowledge_only, "process", return_value=True) as chat, \
             patch.object(app, "handle_room_cleaning_message", side_effect=AssertionError("staff bridge called")), \
             patch.object(app, "handle_service_staff_message", side_effect=AssertionError("service called")), \
             patch.object(app, "handle_reception_operator_message", side_effect=AssertionError("reception called")), \
             patch.object(app, "_process_and_reply", side_effect=AssertionError("legacy executor called")), \
             patch.object(app, "fetch_sheet_data_sync", side_effect=AssertionError("Sheets called")):
            self.assertTrue(app.process_and_reply(message, self.phone, "text"))
        chat.assert_called_once_with(app, message, self.phone, "text")

    def test_simple_chat_only_calls_ai_and_sends_text(self):
        question = "Towel bhej do aur checkout time kya hai?"
        message = {"type": "text", "text": {"body": question}}
        with patch.object(app, "KNOWLEDGE_ONLY_MODE", True), \
             patch.object(app, "ask_ai_chat", return_value="Checkout 11 AM hai; towel request yahan se nahi bhej sakti.") as ask, \
             patch.object(app, "send_whatsapp_message", return_value=True) as send, \
             patch.object(app, "remember_conversation") as remember, \
             patch.object(app, "fetch_sheet_data_sync", side_effect=AssertionError("Sheets called")), \
             patch.object(app, "get_guest_stay_status", side_effect=AssertionError("Stay lookup called")), \
             patch.object(app, "reply_to_reception_request", side_effect=AssertionError("Task sent")):
            self.assertTrue(app.process_and_reply(message, self.phone, "text"))
        ask.assert_called_once_with(question, None, self.phone, structured=False)
        send.assert_called_once()
        self.assertIn("towel request yahan se nahi bhej sakti", send.call_args.args[1])
        self.assertEqual([call.args[1] for call in remember.call_args_list], ["user", "assistant"])

    def test_unavailable_model_never_implies_action_was_taken(self):
        message = {"text": {"body": "Mera order confirm kar do"}}
        with patch.object(app, "KNOWLEDGE_ONLY_MODE", True), \
             patch.object(app, "ask_ai_chat", return_value=None), \
             patch.object(app, "send_whatsapp_message", return_value=True) as send:
            app.process_and_reply(message, self.phone, "text")
        self.assertIn("koi hotel request ya action nahi kiya gaya", send.call_args.args[1])

    def test_image_does_not_trigger_checkin_or_ai_action(self):
        message = {"type": "image", "image": {"id": "demo"}}
        with patch.object(app, "KNOWLEDGE_ONLY_MODE", True), \
             patch.object(app, "ask_ai_chat", side_effect=AssertionError("image not supported")), \
             patch.object(app, "complete_checkin_with_id", side_effect=AssertionError("ID executor")), \
             patch.object(app, "send_whatsapp_message", return_value=True) as send:
            app.process_and_reply(message, self.phone, "image")
        self.assertIn("image dekh nahi sakti", send.call_args.args[1])

    def test_free_text_prompt_uses_hotel_file_and_real_history(self):
        history = [
            {"role": "user", "content": "Standard veg thali milegi?"},
            {"role": "assistant", "content": "Menu mein listed hai ji."}
        ]
        bot = SimpleNamespace(
            KNOWLEDGE_ONLY_MODE=True,
            get_hotel_data=Mock(return_value="HOTEL DATA: Test Palace\\nStandard Veg Thali: Rs. 200"),
            get_hotel_name=Mock(return_value="Test Palace"),
            get_conversation_history=Mock(return_value=history),
            _ai_knowledge_snapshot=Mock(side_effect=AssertionError("Full hotel file should fit"))
        )
        with patch.object(ai_context.knowledge_only, "read_hotel_file", return_value=("HOTEL DATA: Test Palace\\nStandard Veg Thali: Rs. 200", "Test Palace")):
            messages = ai_context.messages(bot, "Kitne ki hai?", phone=self.phone)
        self.assertEqual(messages[-1], {"role": "user", "content": "Kitne ki hai?"})
        self.assertIn("Standard Veg Thali: Rs. 200", messages[0]["content"])
        self.assertIn("all actions are DISABLED", messages[0]["content"])
        self.assertIn("Do not output JSON", messages[0]["content"])
        self.assertEqual(messages[1:3], history)

    def test_large_hotel_file_selects_relevant_facts(self):
        bot = SimpleNamespace(
            KNOWLEDGE_ONLY_MODE=True,
            get_hotel_data=lambda: "X" * 15000,
            get_hotel_name=lambda: "Test Palace",
            get_conversation_history=lambda _: [],
            _ai_knowledge_snapshot=Mock(return_value="WiFi: free; check-out: 11 AM")
        )
        with patch.object(ai_context.knowledge_only, "read_hotel_file", return_value=("X" * 15000, "Test Palace")):
            result = ai_context.messages(bot, "WiFi aur checkout?")
        self.assertIn("WiFi: free", result[0]["content"])
        self.assertNotIn("X" * 100, result[0]["content"])
        self.assertEqual(bot._ai_knowledge_snapshot.call_args.args[0], 9300)
        self.assertEqual(bot._ai_knowledge_snapshot.call_args.kwargs["raw_override"], "X" * 15000)

    def test_uses_real_hotel_data_not_conflicting_customer_profile(self):
        with patch.object(app, "KNOWLEDGE_ONLY_MODE", True):
            text, name = app.knowledge_only.read_hotel_file(app)
            self.assertEqual(name, "Hotel Ganga View")
            self.assertIn("Distance to Har Ki Pauri", text)
            self.assertNotIn("Hotel Shreya Galaxy", text)
            prompt = ai_context.messages(app, "Har Ki Pauri kitni door hai?", phone=self.phone)
            self.assertIn("Hotel Ganga View", prompt[0]["content"])
            self.assertNotIn("Hotel Shreya Galaxy", prompt[0]["content"])

    def test_admin_mutations_paused_but_health_available(self):
        with patch.object(app, "KNOWLEDGE_ONLY_MODE", True):
            client = app.app.test_client()
            self.assertEqual(client.post("/admin/do-anything").status_code, 503)
            health = client.get("/health")
            self.assertEqual(health.status_code, 200)
            self.assertEqual(health.get_json()["mode"], "knowledge-only")

    def test_startup_skips_sheets_and_all_scheduled_tasks(self):
        with patch.object(app, "KNOWLEDGE_ONLY_MODE", True), \
             patch.object(app, "startup_started", False), \
             patch.object(app, "init_durable") as init, \
             patch.object(app.threading, "Thread") as thread, \
             patch.object(app, "fetch_sheet_data_sync", side_effect=AssertionError("Sheets sync started")), \
             patch.object(app, "_ensure_service_requests_sheet", side_effect=AssertionError("Service sheet")):
            app.startup()
        init.assert_called_once()
        self.assertEqual(thread.call_count, 2)
        for args in thread.call_args_list:
            self.assertIn(args.kwargs["name"], {"durable-inbox", "durable-outbox"})


class KnowledgeOnlyOutboxTests(unittest.TestCase):
    def test_old_pending_outgoing_alerts_are_suppressed(self):
        old = {"id": "legacy-alert", "body": json.dumps({"type": "text"}), "created": 100}
        store = SimpleNamespace(due_sends=Mock(return_value=[old]),
                                send_result=Mock(), attention=Mock(return_value=[]))
        bot = SimpleNamespace(durable_store=store, KNOWLEDGE_ONLY_MODE=True,
                              KNOWLEDGE_ONLY_STARTED_AT=200)
        with patch.object(durable_runtime, "transmit", side_effect=AssertionError("Legacy alert sent")), \
             patch.object(durable_runtime.time, "sleep", side_effect=StopIteration):
            with self.assertRaises(StopIteration):
                durable_runtime.loop(bot)
        store.send_result.assert_called_once_with("legacy-alert", "suppressed")


if __name__ == "__main__":
    unittest.main()
