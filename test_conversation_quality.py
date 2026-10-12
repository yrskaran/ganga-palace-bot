"""Generic conversation-quality and provider reasoning regressions."""
import os
os.environ["BOT_AUTOSTART"] = "0"

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import app
import ai_context
import conversation_quality as quality


OLD_ANSWER = (
    "Mujhe aapke naam ka pata nahi hai. Main Hotel Ganga View ki "
    "reception assistant hoon. Aap apna naam batayen, main "
    "aapki madad karne ke liye yahan hoon."
)


def history(question, answer):
    return [
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer},
    ]


class GeneralReasoningChecks(unittest.TestCase):
    def setUp(self):
        self.phone = "919900000333"

    def test_changed_guest_message_and_repeat_requires_reconsideration(self):
        self.assertTrue(quality.should_reconsider(
            history("Naam kya hai tera", OLD_ANSWER),
            "Tera naam pucha, apna to mjhe pta hai", OLD_ANSWER))

    def test_exact_same_question_and_same_answer_not_retried(self):
        self.assertFalse(quality.should_reconsider(
            history("Tera naam batao", OLD_ANSWER),
            "Tera naam batao", OLD_ANSWER))

    def test_similar_paraphrase_does_not_spend_another_api_call(self):
        self.assertFalse(quality.should_reconsider(
            history("Room ka checkout time kya hai ji?", OLD_ANSWER),
            "Room ka checkout time batao ji", OLD_ANSWER))

    def test_short_acknowledgement_is_not_mistaken_for_loop(self):
        self.assertFalse(quality.should_reconsider(
            history("Thanks", "Ji, aapka swagat hai!"),
            "Ok", "Ji, aapka swagat hai!"))

    def test_new_topic_with_repeated_hotel_answer_is_rechecked(self):
        answer = (
            "Reception se sampark karein ji. Woh hi is information ko "
            "confirm kar sakte hain aur aapko sahi detail batayenge."
        )
        self.assertTrue(quality.should_reconsider(
            history("Cow milk hai?", answer),
            "Airport se kaise aana hai?", answer))

    def test_second_look_keeps_new_answer_and_does_not_execute_actions(self):
        msgs = [
            {"role":"system", "content":"Use verified Hotel Ganga View facts; no actions."},
            {"role":"user","content":"Naam kya hai tera"},
            {"role":"assistant","content":OLD_ANSWER},
            {"role":"user","content":"Tera naam pucha apna to pta hai"},
        ]
        bot = SimpleNamespace(
            COHERE_API_KEY="unit-test", COHERE_MODEL="command-a-plus-05-2026",
            get_conversation_history=lambda phone: history("Naam kya hai tera", OLD_ANSWER),
            _cohere_circuit_open=lambda:False,
            _ai_content_is_usable=lambda text, provider:text,
        )
        response = SimpleNamespace(
            status_code=200,
            json=lambda: {"choices":[{"message":{"content":"Mera naam Monika hai ji."},
                                       "finish_reason":"stop"}]})
        send=Mock(return_value=response)
        with patch.object(ai_context,"messages",return_value=msgs):
            result=quality.reconsider(bot,"Tera naam pucha apna to pta hai",self.phone,
                                      OLD_ANSWER,request_fn=send)
        self.assertEqual(result,"Mera naam Monika hai ji.")
        self.assertEqual(send.call_count,1)
        kwargs=send.call_args.kwargs
        self.assertEqual(kwargs["json"]["reasoning_effort"],"high")
        self.assertEqual(kwargs["json"]["messages"][-1]["role"],"user")
        self.assertNotIn("draft reply:",str(kwargs["json"]["messages"][-1]))

    def test_secondary_provider_error_preserves_original_and_does_not_retry(self):
        bot = SimpleNamespace(
            COHERE_API_KEY="unit-test", COHERE_MODEL="command-a-plus-05-2026",
            get_conversation_history=lambda phone: history("Naam kya hai tera", OLD_ANSWER),
            _cohere_circuit_open=lambda:False,
        )
        request=Mock(return_value=SimpleNamespace(status_code=429))
        with patch.object(ai_context,"messages",return_value=[
                {"role":"system","content":"Facts"}, {"role":"user","content":"Correction"}]):
            result=quality.reconsider(bot,"Tera naam pucha apna to pata hai",self.phone,
                                      OLD_ANSWER,request_fn=request)
        self.assertEqual(result,OLD_ANSWER)
        request.assert_called_once()

    def test_normal_guest_reply_does_not_call_second_provider(self):
        bot=SimpleNamespace(COHERE_API_KEY="unit-test",
            get_conversation_history=lambda phone:history("Room rate kya hai?", OLD_ANSWER))
        unused=Mock(side_effect=AssertionError("A second call must never run"))
        answer="Deluxe Non AC Rs. 1000 per night hai ji."
        self.assertEqual(quality.reconsider(bot,"Aur butter roti?",self.phone,answer,unused),answer)
        unused.assert_not_called()

    def test_guest_correction_instruction_available_to_all_model_gateways(self):
        with patch.object(app,"KNOWLEDGE_ONLY_MODE",True):
            msgs=ai_context.messages(app,"Tera naam pucha apna to pta hai",
                phone=self.phone,history=history("Naam kya hai tera",OLD_ANSWER))
        text=msgs[0]["content"]
        self.assertIn("LATEST guest message",text)
        self.assertIn("guest correction",text)
        self.assertIn("Virtual receptionist name: Monika",text)
        self.assertEqual(msgs[-1]["role"],"user")

    def test_cohere_thinking_only_for_plain_conversation(self):
        self.assertEqual(app.COHERE_CONVERSATION_REASONING,"high")
        with patch.object(app,"COHERE_API_KEY","unit-test"), \
             patch.object(app,"_cohere_circuit_open",return_value=False), \
             patch.object(app.requests,"post",return_value=SimpleNamespace(
                 status_code=200, json=lambda:{"choices":[{"message":{"content":"Ji"}}]},
                 text="")) as request:
            app.ask_cohere_chat("Hello",sender_phone=self.phone,structured=False)
        data=request.call_args.kwargs["json"]
        self.assertEqual(data["reasoning_effort"],"high")
        self.assertGreaterEqual(data["max_tokens"],1800)


if __name__=="__main__":
    unittest.main()
