"""Knowledge-only factual prompt, professional language and safety regressions."""
import os
os.environ["BOT_AUTOSTART"] = "0"
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
import app
import ai_context
import knowledge_only


class KnowledgeOnlyQualityTests(unittest.TestCase):
    def test_public_facts_keep_full_menu_and_hotel_location(self):
        source, name = knowledge_only.read_hotel_file(app)
        public = knowledge_only.public_knowledge(source)
        self.assertEqual(name, "Hotel Ganga View")
        self.assertIn("Tawa Roti Butter: Rs. 20", public)
        self.assertIn("Hot Milk: Rs. 50", public)
        self.assertIn("Approx. 1.5 km", public)
        self.assertIn("Mansa Devi Temple", public)
        self.assertNotIn("Every staff service request gets", public)
        self.assertNotIn("Send staff alerts for confirmed service requests", public)
        self.assertNotIn("Breakfast Reminder Window", public)
        self.assertNotIn("Do not create an order for items outside", public)
        self.assertNotIn("Send an explicit request to arrange", public)

    def test_ai_system_uses_professional_context_and_no_false_milk_facts(self):
        with patch.object(app, "KNOWLEDGE_ONLY_MODE", True):
            msgs = ai_context.messages(app, "Mere bache ko cow milk chahiye", phone="919555590001",
                history=[{"role":"user","content":"Mere bache ko cow milk chahiye"}])
        prompt = msgs[0]["content"]
        self.assertIn("animal source", prompt)
        self.assertIn("Hot Milk", prompt)
        self.assertIn("Typing 'Help' DOES NOT", prompt)
        self.assertIn("NEVER mirror that disrespectful tone", prompt)
        self.assertIn("Tawa Roti Butter: Rs. 20", prompt)
        self.assertNotIn("Every staff service request gets", prompt)

    def test_never_turns_into_old_order_workflow(self):
        msg = {"text": {"body": "Do roti aur milk bhej do"}}
        with patch.object(app, "KNOWLEDGE_ONLY_MODE", True), \
             patch.object(app, "ask_ai_chat", return_value="Ji, main abhi order place nahi kar sakti.") as ai, \
             patch.object(app, "send_whatsapp_message", return_value=True), \
             patch.object(app, "_process_and_reply", side_effect=AssertionError("Old handler called")), \
             patch.object(app, "fetch_sheet_data_sync", side_effect=AssertionError("Sheet touched")):
            self.assertTrue(app.process_and_reply(msg, "919555590001", "text"))
        ai.assert_called_once()

    def test_block_false_staff_completion_claim(self):
        self.assertTrue(knowledge_only.unverified_promise(
            "Aapki request staff tak pahunch jaayegi."))
        self.assertTrue(knowledge_only.unverified_promise(
            "Reception wale milk bhej denge."))
        self.assertFalse(knowledge_only.unverified_promise(
            "Main order confirm nahi kar sakti; reception se pooch sakte hain."))
        self.assertFalse(knowledge_only.unverified_promise(
            "Butter roti Rs. 20 ki hai."))

    def test_preserve_information_reply(self):
        msg = {"text": {"body": "Butter roti kitne ki hai"}}
        with patch.object(app, "KNOWLEDGE_ONLY_MODE", True), \
             patch.object(app, "ask_ai_chat", return_value="Butter roti Rs. 20 ki hai ji."), \
             patch.object(app, "send_whatsapp_message", return_value=True) as send:
            app.process_and_reply(msg, "919555590001", "text")
        self.assertEqual(send.call_args.args[1], "Butter roti Rs. 20 ki hai ji.")

    def test_block_unverified_staff_reply(self):
        msg = {"text": {"body": "Help"}}
        with patch.object(app, "KNOWLEDGE_ONLY_MODE", True), \
             patch.object(app, "ask_ai_chat", return_value="Aapki request staff tak pahunch jaayegi."), \
             patch.object(app, "send_whatsapp_message", return_value=True) as send:
            app.process_and_reply(msg, "919555590001", "text")
        self.assertIn("test chat se staff ko koi request forward nahi hoti",send.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
