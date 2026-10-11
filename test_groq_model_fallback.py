import os
os.environ['BOT_AUTOSTART']='0'
import unittest
from unittest.mock import Mock,patch
import app

class GroqModelFallbackTests(unittest.TestCase):
    def setUp(self):
        self.state=patch.dict(app.GROQ_MODEL_UNAVAILABLE_UNTIL,clear=True)
        self.state.start();self.addCleanup(self.state.stop)
        self.config=patch.object(app,'GROQ_FALLBACK_CHAT_MODEL','openai/gpt-oss-20b')
        self.config.start();self.addCleanup(self.config.stop)

    def test_daily_limit_uses_other_model_without_retrying_exhausted_model(self):
        limited=Mock(status_code=429,text='tokens per day (TPD) limit',headers={'retry-after':'600'})
        success=Mock(status_code=200)
        success.json.return_value={'choices':[{'message':{'content':'{"reply":"Your room is 208."}'},'finish_reason':'stop'}]}
        with patch.object(app,'get_active_groq_model',return_value='openai/gpt-oss-120b'), \
             patch.object(app,'_groq_circuit_open',return_value=False), \
             patch.object(app.requests,'post',side_effect=[limited,success]) as post, \
             patch.object(app.time,'sleep') as wait:
            reply=app.ask_groq_chat('What is my room?',{'room':'208','is_inhouse':True},structured=True)
        self.assertIn('208',reply or '')
        self.assertEqual([call.kwargs['json']['model'] for call in post.call_args_list],
                         ['openai/gpt-oss-120b','openai/gpt-oss-20b'])
        wait.assert_not_called()

    def test_both_daily_quotas_are_bounded_and_cached(self):
        limited=Mock(status_code=429,text='tokens per day (TPD) limit',headers={'retry-after':'600'})
        with patch.object(app,'get_active_groq_model',return_value='openai/gpt-oss-120b'), \
             patch.object(app,'_groq_circuit_open',return_value=False), \
             patch.object(app.requests,'post',return_value=limited) as post:
            self.assertIsNone(app.ask_groq_chat('hello'))
            self.assertEqual(post.call_count,2)
            self.assertIsNone(app.ask_groq_chat('hello again'))
            self.assertEqual(post.call_count,2)

    def test_authentication_failure_does_not_try_another_model(self):
        denied=Mock(status_code=401,text='invalid API key',headers={})
        with patch.object(app,'get_active_groq_model',return_value='openai/gpt-oss-120b'), \
             patch.object(app,'_groq_circuit_open',return_value=False), \
             patch.object(app,'_groq_set_circuit_breaker'), \
             patch.object(app.requests,'post',return_value=denied) as post:
            self.assertIsNone(app.ask_groq_chat('hello'))
            self.assertEqual(post.call_count,1)

if __name__=='__main__':unittest.main()
