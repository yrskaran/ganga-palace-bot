"""Reception handoff/learning: exact relay, auth, persistent FAQ and no-action tests."""
import os
os.environ["BOT_AUTOSTART"] = "0"
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import app
import ai_context
import knowledge_only
import reception_learning as learning


class ReceptionLearningUnitTests(unittest.TestCase):
    def setUp(self):
        self.guest = "919555556661"
        self.operator = "919555556662"
        self.ticket = {
            "request_id": "R-ABC123",
            "created": 1750000000,
            "guest_phone": self.guest,
            "reception_phone": self.operator,
            "request": "Mere bachche ke liye cow milk available hai?",
            "status": "pending",
        }
        self.persisted = []
        self.bot = SimpleNamespace(
            KNOWLEDGE_RECEPTION_LEARNING=True,
            RECEPTION_PHONE=self.operator,
            RECEPTION_REQUEST_TTL_SECONDS=21600,
            state_lock=threading.RLock(),
            reception_requests_by_id={"R-ABC123": self.ticket},
            reception_request_sessions={self.guest: self.ticket},
            format_whatsapp_number=lambda x: ''.join(i for i in str(x or '') if i.isdigit()),
            _reception_question_key=lambda x: ' '.join(str(x).lower().split()),
            _reception_answer_is_reusable=Mock(return_value=True),
            _lookup_reception_knowledge=Mock(return_value=None),
            _refresh_reception_knowledge=Mock(return_value=[]),
            _save_reception_knowledge=Mock(return_value=True),
            _persist_reception_request=Mock(side_effect=self._persist),
            _find_reception_request_by_alert_id=lambda x: (self.guest, self.ticket) if x == "wamid-alert" else (None,None),
            _find_reception_request_by_request_id=lambda x: (self.guest, self.ticket) if "R-ABC123" in x else (None,None),
            whatsapp_request=Mock(return_value=SimpleNamespace(status_code=200)),
            send_whatsapp_message=Mock(return_value=True),
            notify_reception_request=Mock(return_value=True),
            remember_conversation=Mock(),
        )

    def _persist(self, ticket):
        self.persisted.append(ticket.get("status"))
        return True

    def test_ai_marker_extracts_question_but_preserves_known_answer(self):
        answer, needed = learning.extract_handoff(
            "Roti Rs. 20 ki hai ji. [[ASK_RECEPTION: cow milk available hai?]]"
        )
        self.assertEqual(answer, "Roti Rs. 20 ki hai ji.")
        self.assertEqual(needed, "cow milk available hai?")

    def test_absent_marker_never_escalates(self):
        self.assertEqual(learning.extract_handoff("Ji, Rs. 50 hai."), ("Ji, Rs. 50 hai.", ""))

    def test_exact_reception_reply_is_forwarded_without_ai_prefix_or_edits(self):
        answer = "  Cow milk mil sakta hai ji.\nFridge se nikaal kar denge.  "
        msg = {"type":"text", "id":"wamid-reception-11", "context":{"id":"wamid-alert"},
               "text":{"body":answer}}
        with patch.object(learning, "refresh_text_file", return_value=True) as file_write:
            self.assertTrue(learning.handle_operator_message(self.bot, msg, self.operator, "text"))
        self.assertEqual(self.bot.whatsapp_request.call_count, 1)
        sent = self.bot.whatsapp_request.call_args.args[0]
        self.assertEqual(sent["text"]["body"], answer)
        self.assertEqual(sent["to"], self.guest)
        self.assertEqual(self.persisted, ["forwarding", "responded"])
        self.bot.remember_conversation.assert_called_once_with(self.guest, "assistant", answer)
        self.bot._save_reception_knowledge.assert_called_once()
        file_write.assert_called_once_with(self.bot, force=True)
        self.assertEqual(self.bot.reception_requests_by_id["R-ABC123"]["status"], "responded")

    def test_unauthorized_number_cannot_reply_to_ticket(self):
        msg={"id":"attack","context":{"id":"wamid-alert"},"text":{"body":"Rs. 1"}}
        self.assertFalse(learning.handle_operator_message(self.bot, msg, "919999999999", "text"))
        self.bot.whatsapp_request.assert_not_called()
        self.bot._save_reception_knowledge.assert_not_called()

    def test_wrong_context_is_not_forwarded_to_any_guest(self):
        msg={"id":"wrong","context":{"id":"unknown-alert"},"text":{"body":"Test"}}
        self.assertTrue(learning.handle_operator_message(self.bot, msg, self.operator, "text"))
        self.bot.whatsapp_request.assert_not_called()

    def test_duplicate_reception_reply_never_sends_twice(self):
        self.ticket["status"]="responded"
        msg={"id":"replay","context":{"id":"wamid-alert"},"text":{"body":"Milk hai"}}
        self.assertTrue(learning.handle_operator_message(self.bot, msg, self.operator, "text"))
        self.bot.whatsapp_request.assert_not_called()

    def test_fails_closed_when_ticket_save_fails(self):
        self.bot._persist_reception_request=Mock(return_value=False)
        msg={"id":"reply","context":{"id":"wamid-alert"},"text":{"body":"Milk hai"}}
        learning.handle_operator_message(self.bot,msg,self.operator,"text")
        self.bot.whatsapp_request.assert_not_called()
        self.bot._save_reception_knowledge.assert_not_called()

    def test_failed_meta_send_is_never_stored_as_success(self):
        self.bot.whatsapp_request=Mock(return_value=SimpleNamespace(status_code=400))
        msg={"id":"reply","context":{"id":"wamid-alert"},"text":{"body":"Milk hai"}}
        learning.handle_operator_message(self.bot,msg,self.operator,"text")
        self.assertEqual(self.ticket["status"],"guest_delivery_failed")
        self.bot._save_reception_knowledge.assert_not_called()

    def test_reception_knowledge_text_file_contains_only_general_facts(self):
        rows=[{"question":"Cow milk ka type kya hai?", "answer":"Sirf cow milk available hai ji.", "expires":1999999999},
              {"question":"Room 204 mein kaun guest hai?", "answer":"Private Guest Name", "expires":1999999999}]
        self.bot._refresh_reception_knowledge.return_value=rows
        self.bot._reception_answer_is_reusable.side_effect=lambda q,a: True
        with tempfile.TemporaryDirectory() as root:
            target=Path(root)/"hotel_data_learned.txt"
            with patch.dict(os.environ,{"HOTEL_LEARNED_TEXT_PATH":str(target)}):
                self.assertTrue(learning.refresh_text_file(self.bot, force=True))
            text=target.read_text(encoding="utf-8")
        self.assertIn("Cow milk ka type kya hai?",text)
        self.assertIn("Sirf cow milk available hai ji.",text)
        self.assertNotIn("Room 204",text)
        self.assertNotIn("Private Guest Name",text)

    def test_dynamic_or_private_facts_do_not_enter_shared_knowledge(self):
        self.bot._reception_answer_is_reusable.return_value=False
        self.assertFalse(learning._reusable(self.bot,"Aaj room available hai?","Haan"))
        self.bot._reception_answer_is_reusable.return_value=True
        self.assertFalse(learning._reusable(self.bot,"Guest room 204 ka bill?","Rs. 12000"))
        self.assertFalse(learning._reusable(self.bot,"Contact?", "Call +919555556661"))

    def test_same_pending_question_does_not_send_second_alert(self):
        self.ticket["created"]=learning.time.time()
        self.ticket["request"]="Cow milk available hai?\nReception clarification required: confirm milk source"
        result=learning.forward_unknown(self.bot,self.guest,"Cow milk available hai?","please check")
        self.assertEqual(result,"pending")
        self.bot.notify_reception_request.assert_not_called()

    def test_forwarded_request_has_persistent_ticket_and_reception_quote_id(self):
        self.bot._ensure_reception_sheet=Mock(return_value=object())
        self.bot.RECEPTION_REQUEST_HEADERS=["Request ID"]
        self.ticket["status"]="pending"
        self.ticket["created"]=learning.time.time()
        self.ticket["sheet_row"]=2
        self.ticket["source"]="ai_missing_hotel_knowledge"
        self.ticket["alert_message_id"]="wamid-new-alert"
        self.bot.notify_reception_request=Mock(return_value=True)
        result=learning.forward_unknown(
            self.bot,self.guest,"Cow milk ka type kya hai?","Cow milk source confirm karein"
        )
        self.assertEqual(result,"sent")
        self.bot._ensure_reception_sheet.assert_called_once()
        self.bot.notify_reception_request.assert_called_once()
        self.assertIn("Cow milk source confirm karein",
                      self.bot.notify_reception_request.call_args.args[2])

    def test_alert_without_persistent_row_never_promises_forwarded_reply(self):
        self.bot._ensure_reception_sheet=Mock(return_value=object())
        self.bot.RECEPTION_REQUEST_HEADERS=["Request ID"]
        self.ticket["status"]="pending"
        self.ticket["created"]=learning.time.time()
        self.ticket["source"]="ai_missing_hotel_knowledge"
        self.ticket["alert_message_id"]="wamid-new-alert"
        self.bot.notify_reception_request=Mock(return_value=True)
        self.assertEqual(learning.forward_unknown(self.bot,self.guest,"Room mein locker hai?"),"untracked")

    def test_knowledge_mode_only_records_mapped_reception_statuses(self):
        ticket={"source":"ai_missing_hotel_knowledge"}
        with patch.object(app,"KNOWLEDGE_ONLY_MODE",True), \
             patch.object(app,"KNOWLEDGE_RECEPTION_LEARNING",True), \
             patch.dict(app.reception_requests_by_alert,{"wamid-learn-alert":ticket}), \
             patch.object(app,"_update_reception_alert_delivery") as reception, \
             patch.object(app,"_update_service_alert_delivery",side_effect=AssertionError("Old service called")), \
             patch.object(app,"_update_lifecycle_delivery",side_effect=AssertionError("Old lifecycle called")):
            app.record_delivery_statuses([{"id":"wamid-learn-alert","status":"failed","errors":[{"code":131047}]}])
        reception.assert_called_once_with("wamid-learn-alert","failed",[131047])

    def test_forward_failure_does_not_claim_reception_notified(self):
        self.bot.notify_reception_request.return_value=False
        self.assertEqual(learning.forward_unknown(self.bot,self.guest,"Some missing hotel info"),"failed")


class ReceptionLearningIntegrationTests(unittest.TestCase):
    phone="919555557770"

    def test_flag_off_preserves_normal_chat_without_sheet_lookup(self):
        message={"type":"text","text":{"body":"Dinner mein kya hai"}}
        with patch.object(app,"KNOWLEDGE_ONLY_MODE",True), \
             patch.object(app,"KNOWLEDGE_RECEPTION_LEARNING",False), \
             patch.object(app,"ask_ai_chat",return_value="Shahi paneer aur dal available hain."), \
             patch.object(app,"send_whatsapp_message",return_value=True) as send, \
             patch.object(app,"_lookup_reception_knowledge",side_effect=AssertionError("Sheet queried")):
            app.process_and_reply(message,self.phone,"text")
        self.assertIn("Shahi paneer", send.call_args.args[1])

    def test_unknown_hotel_fact_sends_one_ticket_after_ai_call(self):
        msg={"type":"text","text":{"body":"Cow milk hai?"}}
        with patch.object(app,"KNOWLEDGE_ONLY_MODE",True), \
             patch.object(app,"KNOWLEDGE_RECEPTION_LEARNING",True), \
             patch.object(learning,"cached_answer",return_value=None), \
             patch.object(app,"ask_ai_chat",return_value="[[ASK_RECEPTION: Is cow milk available?]]") as ai, \
             patch.object(learning,"forward_unknown",return_value="sent") as forward, \
             patch.object(app,"send_whatsapp_message",return_value=True) as send, \
             patch.object(app,"_process_and_reply",side_effect=AssertionError("Legacy engine")):
            app.process_and_reply(msg,self.phone,"text")
        ai.assert_called_once()
        forward.assert_called_once_with(app,self.phone,"Cow milk hai?","Is cow milk available?")
        self.assertNotIn("[[ASK_RECEPTION", send.call_args.args[1])
        self.assertIn("reception ko bhej diya",send.call_args.args[1])

    def test_cached_verified_hotel_answer_skips_ai_and_new_ticket(self):
        msg={"type":"text","text":{"body":"Cow milk available hai?"}}
        with patch.object(app,"KNOWLEDGE_ONLY_MODE",True), \
             patch.object(app,"KNOWLEDGE_RECEPTION_LEARNING",True), \
             patch.object(learning,"cached_answer",return_value="Ji, fresh cow milk available hai."), \
             patch.object(learning,"forward_unknown",side_effect=AssertionError("Duplicate reception alert")), \
             patch.object(app,"ask_ai_chat",side_effect=AssertionError("No need to ask AI")), \
             patch.object(app,"send_whatsapp_message",return_value=True) as send:
            app.process_and_reply(msg,self.phone,"text")
        self.assertEqual(send.call_args.args[1],"Ji, fresh cow milk available hai.")

    def test_reception_mode_prompt_includes_marker_and_saved_faq(self):
        with patch.object(app,"KNOWLEDGE_ONLY_MODE",True), \
             patch.object(app,"KNOWLEDGE_RECEPTION_LEARNING",True), \
             patch.object(learning,"faq_context",return_value="Question: Cow milk?\\nVerified reception answer: Yes"):
            prompt=ai_context.messages(app,"Cow milk hai?",phone=self.phone,history=[])[0]["content"]
        self.assertIn("[[ASK_RECEPTION:",prompt)
        self.assertIn("RECEPTION-VERIFIED HOTEL FAQ",prompt)
        self.assertIn("Shahi Paneer: Rs. 240",prompt)

    def test_disabled_mode_does_not_add_reception_marker(self):
        with patch.object(app,"KNOWLEDGE_ONLY_MODE",True), \
             patch.object(app,"KNOWLEDGE_RECEPTION_LEARNING",False), \
             patch.object(learning,"faq_context",side_effect=AssertionError("Read Sheet")):
            prompt=ai_context.messages(app,"Dinner?",phone=self.phone,history=[])[0]["content"]
        self.assertNotIn("[[ASK_RECEPTION:",prompt)


if __name__=="__main__":
    unittest.main()
