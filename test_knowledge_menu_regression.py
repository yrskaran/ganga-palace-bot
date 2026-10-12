"""AI-first source-grounding tests for real October 13 guest conversation."""
import os
os.environ['BOT_AUTOSTART'] = '0'
import unittest
from unittest.mock import patch
import ai_context
import app
import knowledge_only


class MenuContextRegression(unittest.TestCase):
    phone = "919555590070"

    def prompt(self, text, history=None):
        with patch.object(app, "KNOWLEDGE_ONLY_MODE", True):
            return ai_context.messages(app, text, phone=self.phone, history=history or [])

    def test_dinner_prompt_has_named_actual_dishes_not_only_categories(self):
        messages = self.prompt("Raat ke khane me kya hai")
        system = messages[0]["content"]
        for dish in [
            "Dal Tadka: Rs. 160",
            "Shahi Paneer: Rs. 240",
            "Kadhai Paneer: Rs. 250",
            "Tawa Roti Butter: Rs. 20",
            "Jeera Rice: Rs. 140",
            "Standard Veg Thali: Rs. 200",
        ]:
            self.assertIn(dish, system, dish)
        self.assertIn("dinner question, name suitable specific dishes", system)
        self.assertNotIn("Every staff service request gets", system)

    def test_dinner_menu_survives_unrelated_conversation_history(self):
        history = [
            {"role": "user", "content": "Kamre me bhoot to nahi aate"},
            {"role": "assistant", "content": "Room ke bare mein kya doubt hai?"},
            {"role": "user", "content": "Cow milk chahiye tha?"},
            {"role": "assistant", "content": "Hot Milk available hai, source verify karein."},
        ]
        messages = self.prompt("Raat ke khane me kya hai", history)
        system = messages[0]["content"]
        self.assertIn("Kadhai Paneer: Rs. 250", system)
        self.assertIn("Hot Milk: Rs. 50", system)
        self.assertEqual(messages[1:5], history)
        self.assertEqual(messages[-1], {"role": "user", "content": "Raat ke khane me kya hai"})

    def test_full_published_food_list_is_preserved_by_selection(self):
        source, hotel = knowledge_only.read_hotel_file(app)
        public = knowledge_only.public_knowledge(source)
        facts = knowledge_only.facts_for_conversation(
            app, public, "bhoot, cow milk, raat ke khane me kya hai", 9300
        )
        items = [line for line in source.splitlines()
                 if line.startswith("- ") and ": Rs. " in line]
        # Room prices appear as Rs. x per night and use a different pattern.
        self.assertEqual(len(items), 49)
        for item in items:
            self.assertIn(item, facts, item)
        self.assertEqual(hotel, "Hotel Ganga View")
        self.assertLessEqual(len(facts.encode("utf-8")), 9300)

    def test_bhoot_reply_prompt_does_not_presuppose_safety_or_paranormal_facts(self):
        msg = self.prompt("Kamre me bhoot to nahi aate")
        self.assertIn("do not dismiss a concern", msg[0]["content"])
        self.assertIn("guest safety incidents", msg[0]["content"])
        self.assertIn("Do not output JSON", msg[0]["content"])
        self.assertNotIn("Every staff service request gets", msg[0]["content"])

    def test_cow_milk_still_not_verified_animal_source(self):
        msg = self.prompt("Cow milk chahiye tha?")
        self.assertIn("Hot Milk: Rs. 50", msg[0]["content"])
        self.assertIn("does NOT prove it is cow milk", msg[0]["content"])

    def test_long_history_keeps_provider_input_below_guard(self):
        history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": "dinner? " * 45}
            for i in range(10)
        ]
        msg = self.prompt("Raat ke khane me kya hai", history)
        self.assertLessEqual(sum(len(m["content"].encode("utf-8")) for m in msg), 18000)
        self.assertIn("Shahi Paneer: Rs. 240", msg[0]["content"])


if __name__ == "__main__":
    unittest.main()
