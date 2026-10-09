import os
import unittest
from copy import deepcopy
from unittest.mock import patch

os.environ["BOT_AUTOSTART"] = "0"
import app


class RoomOccupancyRegressionTests(unittest.TestCase):
    def setUp(self):
        self.config = deepcopy(app.CUSTOMER_CONFIG)
        self.config["rooms"] = [
            {"name": "Deluxe", "price": 1999, "details": "Suitable for couples"},
            {"name": "Family Suite", "price": 3499, "details": "Spacious family category"},
        ]
        app.reception_consent_sessions.clear()
        self.phone = "919555555555"
        self.guest_info = {"name": "Guest", "room": "", "is_inhouse": False}
        self.stack = [
            patch.object(app, "CUSTOMER_CONFIG", self.config),
            patch.object(app, "send_whatsapp_message", return_value=True),
            patch.object(app, "remember_conversation"),
            patch.object(app, "get_guest_response_language", return_value="hinglish"),
            patch.object(app, "notify_reception_request", return_value=True),
        ]
        for item in self.stack:
            item.start()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for item in reversed(self.stack):
            item.stop()
        app.reception_consent_sessions.clear()

    def test_capacity_unknown_does_not_guess_family_suite_or_rate(self):
        handled = app._handle_room_occupancy_question(
            self.phone, "Hum 3 log hai...aisa room hai jisme teeno aa jaaye", self.guest_info
        )
        self.assertTrue(handled)
        reply = app.send_whatsapp_message.call_args.args[1]
        self.assertIn("3 logon ke liye", reply)
        self.assertIn("guess nahi karungi", reply)
        self.assertNotIn("Family Suite", reply)
        self.assertNotIn("3499", reply)
        self.assertEqual(app.reception_consent_sessions[self.phone]["guest_count"], 3)

    def test_confused_followup_keeps_topic_and_explicit_message_sends_handoff(self):
        app._handle_room_occupancy_question(
            self.phone, "Hum 3 log hai...aisa room hai jisme teeno aa jaaye", self.guest_info
        )
        self.assertFalse(app._handle_reception_consent(self.phone, "Samjh ni aa rha", self.guest_info))
        self.assertIn(self.phone, app.reception_consent_sessions)
        self.assertTrue(app._handle_room_occupancy_question(self.phone, "Samjh ni aa rha", self.guest_info))
        reply = app.send_whatsapp_message.call_args.args[1]
        self.assertIn("3 logon", reply)
        self.assertNotIn("Deluxe", reply)
        self.assertTrue(app._handle_reception_consent(
            self.phone, "Jawab ni aata to mna kar de..ya reception ko msg bhj de", self.guest_info
        ))
        app.notify_reception_request.assert_called_once()
        self.assertIn("3 guests", app.notify_reception_request.call_args.args[2])
        self.assertNotIn(self.phone, app.reception_consent_sessions)

    def test_only_explicit_configured_capacity_can_recommend_a_room(self):
        self.config["rooms"] = [
            {"name": "Family Suite", "price": 3499, "details": "Family room"},
            {"name": "Premium Window", "max_guests": 2},
            {"name": "Super Deluxe", "guest_capacity": 4},
        ]
        self.assertTrue(app._handle_room_occupancy_question(
            self.phone, "3 logo ke hisaab se kaunsa room hai", self.guest_info
        ))
        reply = app.send_whatsapp_message.call_args.args[1]
        self.assertIn("Super Deluxe", reply)
        self.assertNotIn("Family Suite", reply)
        self.assertNotIn("Premium Window", reply)
        self.assertNotIn("3499", reply)
        self.assertNotIn(self.phone, app.reception_consent_sessions)


if __name__ == "__main__":
    unittest.main()
