import os
os.environ['BOT_AUTOSTART']='0'
import unittest
from unittest.mock import patch, Mock
import app


class GeminiAdapterTests(unittest.TestCase):
    def call(self, data, structured=True):
        response=Mock(status_code=200)
        response.json.return_value=data
        with patch.object(app,'GEMINI_API_KEY','test-only'), patch.object(app,'GEMINI_MODEL','gemini-3.8-flash'), patch.object(app,'_gemini_circuit_open',return_value=False), patch.object(app.requests,'post',return_value=response) as post:
            result=app.ask_gemini_chat('Return a complete receptionist plan',structured=structured)
        return result,post.call_args.kwargs['json']

    def test_full_plan_has_reasoning_and_output_budget_without_deprecated_sampling(self):
        result,payload=self.call({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"action":"ANSWER"}'}]}}]})
        config=payload['generationConfig']
        self.assertNotIn('temperature',config)
        self.assertEqual(config['thinkingConfig']['thinkingLevel'],'low')
        self.assertGreaterEqual(config['maxOutputTokens'],2048)

    def test_truncated_response_is_not_accepted_even_if_fragment_is_json(self):
        result,_=self.call({'candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':[{'text':'{"action":"ANSWER"}'}]}}]})
        self.assertIsNone(result)

    def test_thought_part_never_becomes_guest_answer(self):
        result,_=self.call({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'Internal reasoning','thought':True},{'text':'Ji, bataiye.'}]}}]},False)
        self.assertEqual(result,'Ji, bataiye.')


if __name__=='__main__':
    unittest.main()
