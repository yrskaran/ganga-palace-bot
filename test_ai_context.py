import os
os.environ['BOT_AUTOSTART']='0'
import json
import unittest
from unittest.mock import Mock, patch
import app
import ai_receptionist

class ProductionContextTests(unittest.TestCase):
    def test_workflow_contract_does_not_reclassify_english_prompt_as_guest_language(self):
        import ai_context
        token=ai_receptionist.current.set({'contract_request':True,'plan_review':True})
        try:
            messages=ai_context.messages(app,'CURRENT MESSAGE: Padhni ni aundi menu; script=roman',
                {'room':'450','is_inhouse':True},history=[])
        finally: ai_receptionist.current.reset(token)
        self.assertNotIn('Infer the guest language from the CURRENT sentence',messages[0]['content'])
        self.assertIn('contract',messages[0]['content'].lower())
        self.assertIn('450',messages[0]['content'])

    def test_cohere_contract_reserves_final_output_without_thinking(self):
        response=Mock(status_code=200,json=Mock(return_value={
            'choices':[{'message':{'content':'{"supported":true}'},'finish_reason':'stop'}]}))
        with patch.object(app,'COHERE_API_KEY','test'),patch.object(app,'COHERE_MODEL','command-a-plus-05-2026'), \
                patch.object(app,'_cohere_circuit_open',return_value=False),patch.object(app.requests,'post',return_value=response) as post:
            self.assertEqual(app.ask_cohere_chat('Return JSON only',structured=True),'{"supported":true}')
        payload=post.call_args.kwargs['json']
        self.assertEqual(payload.get('reasoning_effort'),'none')
        self.assertGreaterEqual(payload['max_tokens'],2048)

    def test_full_profile_preserves_followup_at_groq_transport(self):
        phone='919555550001'
        history=[{'role':'user','content':'Standard veg thali bhi hai?'},
                 {'role':'assistant','content':'Standard Veg Thali menu mein hai.'}]
        response=Mock(status_code=200)
        response.json.return_value={'choices':[{'message':{'content':'{}'},'finish_reason':'stop'}]}
        tasks={f'S-{i:06X}':{'request_id':f'S-{i:06X}','guest_phone':phone,'status':'COMPLETED','details':'x'*450} for i in range(8)}
        with patch.object(app,'service_tasks_by_id',tasks),patch.object(app,'conversation_memory',{phone:history}), patch.object(app,'_groq_circuit_open',return_value=False), patch.object(app,'get_active_groq_model',return_value='qwen/qwen3.8-27b'), patch.object(app.requests,'post',return_value=response) as post:
            app.ask_groq_chat(app._ai_understanding_prompt('Kitne ki hai?',None,phone),sender_phone=phone,structured=True)
        messages=post.call_args.kwargs['json']['messages']
        self.assertIn(history[0],messages)
        self.assertIn(history[1],messages)
        self.assertLessEqual(sum(len(m['content'].encode()) for m in messages),12400)

    def test_openai_review_contract_accepts_review_fields(self):
        response=Mock(status_code=200)
        response.json.return_value={'choices':[{'message':{'content':'{}'},'finish_reason':'stop'}]}
        token=ai_receptionist.current.set({'plan_review':True})
        try:
            with patch.object(app,'OPENAI_API_KEY','test'),patch.object(app,'_openai_circuit_open',return_value=False),patch.object(app.requests,'post',return_value=response) as post:
                app.ask_openai_chat('Review JSON',structured=True)
            self.assertEqual(post.call_args.kwargs['json']['response_format'],{'type':'json_object'})
        finally: ai_receptionist.current.reset(token)

    def test_openai_schema_compliant_transport_completes_independent_review(self):
        candidate=dict(understood_as='thali price',action='MENU_ITEM_INFO',category='NONE',photo_target='',menu_section='',show_prices=True,generic='',items=[{'name':'Standard Veg Thali','qty':1}],service='',needs_reception=False,reception_followup=False,reception_request='',language='hinglish',operation_text='',task_id='',reply='',confidence=.95)
        review={'menu_related':True,'language':'hinglish','request_kind':'price','action':'MENU_ITEM_INFO','menu_section':'','items':candidate['items'],'excluded_items':[],'show_prices':True,'needs_reception':False,'reception_request':'','reply':''}
        contracts=[]
        def transport(url,**kwargs):
            contract=kwargs['json']['response_format'];contracts.append(contract['type'])
            obj=candidate if contract['type']=='json_schema' else review
            return Mock(status_code=200,json=Mock(return_value={'choices':[{'message':{'content':json.dumps(obj)},'finish_reason':'stop'}]}))
        with patch.object(app,'OPENAI_API_KEY','test'),patch.object(app,'_openai_circuit_open',return_value=False),patch.object(app,'_ai_provider_functions',return_value=[('openai',app.ask_openai_chat)]),patch.object(app.requests,'post',side_effect=transport):
            plan=app.understand_guest_request('Standard veg thali kitne ki hai?',None,'919555550001')
        self.assertEqual(contracts,['json_schema','json_object'])
        self.assertEqual(plan['action'],'MENU_ITEM_INFO')
        self.assertTrue(plan['show_prices'])

    def test_verified_sender_stay_reaches_review_without_private_fields(self):
        token=ai_receptionist.current.set({'plan_review':True})
        try:
            messages=app._openai_messages('Review JSON',{'name':'Synthetic','room':'240','is_inhouse':True,'id_link':'SECRET'},'919555550001',True)
        finally:ai_receptionist.current.reset(token)
        system=messages[0]['content']
        self.assertIn('240',system)
        self.assertNotIn('SECRET',system)
