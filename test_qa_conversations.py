import unittest
from unittest.mock import patch
from types import SimpleNamespace
import qa_conversations as cases
import qa_runner as qa

class ConversationQATests(unittest.TestCase):
    def test_qa_can_resume_after_daily_limits_using_previous_configured_model(self):
        import threading,json
        from unittest.mock import Mock
        limited=SimpleNamespace(status_code=429,text='tokens per day',headers={})
        good=SimpleNamespace(status_code=200,json=lambda:{'choices':[{'message':{'content':json.dumps({'results':[{'id':'a','reply':'Actual reply'}]})}}],'usage':{'total_tokens':0}})
        req=SimpleNamespace(post=Mock(side_effect=[limited,limited,good]),RequestException=RuntimeError)
        bot=SimpleNamespace(get_active_groq_model=lambda:'openai/gpt-oss-120b',GROQ_FALLBACK_CHAT_MODEL='qwen/qwen3.8-27b',GROQ_LOCK=threading.RLock(),GROQ_MODEL_UNAVAILABLE_UNTIL={},GROQ_API_KEY='test-only',requests=req,_parse_ai_json=json.loads)
        with patch('builtins.print'):
            result,model=qa.Transport(bot).call('QA',['a'],'interpret')
        self.assertEqual(model,'openai/gpt-oss-20b')
        self.assertEqual(result['a']['reply'],'Actual reply')

    def test_two_hundred_distinct_messages_cover_twenty_segments(self):
        chats=cases.conversations()
        self.assertEqual(len(chats),20)
        self.assertTrue(all(len(c['turns'])==10 for c in chats))
        messages=[t['text'] for c in chats for t in c['turns']]
        self.assertEqual(len(messages),200)
        self.assertEqual(len(set(messages)),200)
        self.assertTrue(all(t.get('actions') for c in chats for t in c['turns']))

    def test_missing_duplicate_or_unrequested_batch_rows_are_rejected(self):
        for rows in ([{'id':'a'}], [{'id':'a'},{'id':'a'}], [{'id':'a'},{'id':'c'}]):
            with self.subTest(rows=rows):
                self.assertIsNone(qa.batch_rows({'results':rows},['a','b']))
        self.assertEqual(set(qa.batch_rows({'results':[{'id':'a','reply':'A'},{'id':'b','reply':'B'}]},['a','b'])),{'a','b'})

    def test_history_uses_actual_reply_and_does_not_cross_chats(self):
        a=qa.ChatState({'id':'a','segment':'A','guest':None,'turns':[]})
        b=qa.ChatState({'id':'b','segment':'B','guest':None,'turns':[]})
        a.remember('Kitne ki?', 'Actual incorrect response retained')
        self.assertEqual(a.history[-1]['content'],'Actual incorrect response retained')
        self.assertEqual(b.history,[])

    def test_confirmation_without_cart_cannot_create_simulated_order(self):
        chat=qa.ChatState({'id':'a','segment':'A','guest':{'is_inhouse':True,'room':'TEST240'},'turns':[]})
        source=qa.execution_result(chat,{'action':'ORDER_CONFIRM'}, {'menu':[]})
        self.assertFalse(chat.pending.get('active_orders'))
        self.assertIn('No saved pending cart',source)

    def test_wrong_quantity_cannot_be_hidden_by_correct_expected_fixture(self):
        chat=qa.ChatState({'id':'a','segment':'A','guest':{'is_inhouse':True,'room':'TEST240'},'turns':[]})
        source=qa.execution_result(chat,{'action':'ORDER','items':[{'name':'Poha','qty':3}]}, {'menu':[{'name':'Poha','price':70}]})
        self.assertIn('3 x Poha',source)
        self.assertEqual(chat.pending['order_sessions']['total'],210)

    def test_malformed_rows_fail_individually_without_aborting_200_turns(self):
        bot=SimpleNamespace(CUSTOMER_CONFIG={'menu':[]},_ai_content_is_usable=lambda *a:True)
        fake=SimpleNamespace(usage=0)
        def call(prompt,ids,stage):
            if stage=='interpret':
                return {i:{'id':i,'action':'ORDER','items':['bad'],'confidence':0.9,'language':'hinglish','operation_text':''} for i in ids},'mock'
            return {i:{'id':i,'reply':{'bad':'not a string'}} for i in ids},'mock'
        fake.call=call
        with patch.object(qa,'Transport',return_value=fake),patch.object(qa.ai,'interpretation_prompt',return_value='policy'),patch('builtins.print'):
            rows=qa.run(bot,'isolated-unit-check',resume=False)
        self.assertEqual(len(rows),200)
        self.assertTrue(all(not row['passed'] for row in rows))
        self.assertTrue(all('Non-string model reply' in row['errors'] for row in rows))

if __name__=='__main__':unittest.main()
