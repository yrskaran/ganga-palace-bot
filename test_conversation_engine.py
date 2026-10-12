import unittest
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

try:
    import conversation_engine as engine
except ImportError:
    engine = None

class EngineTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(engine, 'The multi-intent engine is missing')
        self.bot = SimpleNamespace(CUSTOMER_CONFIG={'menu':[{'name':'Chole Bhature'}]},
            CUSTOMER_DEMO_MODE=False, format_whatsapp_number=lambda x:str(x))

    def plan(self, **kw):
        return dict({'understood_as':'order and timing question','language':'punjabi',
            'script':'roman','questions':['Kab tak mil juga?'],'operations':[
                {'action':'ORDER','items':[{'name':'Chole Bhature','qty':1}],
                 'category':'KITCHEN','operation_text':'','confidence':0.95}]}, **kw)

    def test_order_and_question_are_preserved(self):
        result=engine.validate_plan(self.bot,self.plan())
        self.assertEqual(result['questions'],['Kab tak mil juga?'])
        self.assertEqual(result['operations'][0]['items'][0]['qty'],1)

    def test_order_and_service_are_both_preserved(self):
        value=self.plan()
        value['operations'].append({'action':'SERVICE','category':'HOUSEKEEPING',
            'operation_text':'Bring one towel','confidence':0.95})
        self.assertEqual(len(engine.validate_plan(self.bot,value)['operations']),2)

    def test_invalid_quantity_rejects_entire_plan(self):
        for qty in [True,0,1.5,'1',51]:
            value=self.plan(); value['operations'][0]['items'][0]['qty']=qty
            self.assertIsNone(engine.validate_plan(self.bot,value))

    def test_unknown_item_rejects_before_any_tools(self):
        value=self.plan();value['operations'][0]['items'][0]['name']='imaginary'
        self.assertIsNone(engine.validate_plan(self.bot,value))

    def test_same_turn_cart_and_confirmation_are_rejected(self):
        value=self.plan();value['operations'].append({'action':'ORDER_CONFIRM','confidence':0.95})
        self.assertIsNone(engine.validate_plan(self.bot,value))

    def test_readability_correction_can_have_no_tools(self):
        result=engine.validate_plan(self.bot,self.plan(operations=[],questions=['Restate readable last reply']))
        self.assertEqual(result['operations'],[])

    def test_receipts_capture_only_current_guest(self):
        with engine.collect(self.bot,'guest') as receipts:
            self.assertTrue(engine.capture_text(self.bot,'guest','Saved cart'))
            self.assertFalse(engine.capture_text(self.bot,'staff','Staff request'))
        self.assertEqual(receipts,['Saved cart'])
        self.assertFalse(engine.capture_text(self.bot,'guest','After turn'))

    def test_receipts_are_not_shared_between_threads(self):
        with engine.collect(self.bot,'guest') as receipts:
            result=[]
            thread=threading.Thread(target=lambda:result.append(engine.capture_text(self.bot,'guest','Other thread')))
            thread.start();thread.join()
        self.assertEqual(result,[False]);self.assertEqual(receipts,[])

    def test_roman_script_rejects_gurmukhi(self):
        self.assertFalse(engine.script_supported('ਹਿਤੇਸ਼ ਜੀ','roman'))
        self.assertTrue(engine.script_supported('Hitesh ji, order note ho gaya.','roman'))

class EngineFlowTests(unittest.TestCase):
    def setUp(self):
        import os
        os.environ['BOT_AUTOSTART']='0'
        import app
        from unittest.mock import patch
        self.app=app;self.patch=patch;self.phone='919555555555';self.patches=[]
        for name,value in {'CUSTOMER_CONFIG':{'ai_receptionist_flow':True,'conversation_tool_engine':True,
                'menu':[{'name':'Chole Bhature','price':150}]},'CUSTOMER_DEMO_MODE':False,
            'conversation_memory':{},'guest_language_cache':{},'order_sessions':{},
            'duplicate_order_sessions':{},'active_orders':{},'checkin_sessions':{},
            'demo_food_sessions':{},'demo_guest_sessions':{},'service_guest_pending':{},
            'service_tasks_by_id':{},'reception_request_sessions':{},'photo_sessions':{}}.items():
            p=patch.object(app,name,value);p.start();self.patches.append(p)
        p=patch.object(app,'_ai_knowledge_snapshot',return_value='Hotel name: Shreya. Kitchen ETA: unverified.');p.start();self.patches.append(p)
        self.guest={'name':'Hitesh','room':'450','is_inhouse':True}
        self.sent=[]
        def transport(payload):
            self.sent.append(payload)
            return SimpleNamespace(status_code=200)
        p=patch.object(app,'whatsapp_request',side_effect=transport);p.start();self.patches.append(p)

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.app.turn_capture.current=None

    def plan(self,operations=None,questions=None):
        return {'understood_as':'order plus timing','language':'punjabi','script':'roman',
            'questions':questions if questions is not None else ['When will it arrive?'],
            'operations':operations if operations is not None else [
                {'action':'ORDER','category':'KITCHEN','items':[{'name':'Chole Bhature','qty':1}],
                 'operation_text':'','confidence':.95}]}

    def review(self,operation):
        return dict({'items':[]},**operation,operational=True,language='punjabi',reply='',reception_followup=False)

    def provider(self,values):
        # API boundary fixtures; production planner/reviewer/executor/composer run.
        return self.patch.object(self.app,'ask_ai_chat',side_effect=[json.dumps(v) for v in values])

    def test_order_eta_uses_actual_tool_result_in_one_guest_reply(self):
        value=self.plan();op=value['operations'][0]
        def executor(*args,**kw):
            self.app.order_sessions[self.phone]={'order':'1 Chole Bhature'}
            self.app.send_whatsapp_message(self.phone,'Room 450: 1 x Chole Bhature. Confirmation required.')
        final='Room 450: 1 x Chole Bhature. Confirm kar deo ji. Delivery time abhi confirm nahi hai.'
        with self.provider([value,self.review(op),{'reply':final,'answered_questions':[0]},{'supported':True}]), self.patch.object(self.app,'_process_and_reply',side_effect=executor):
            engine.handle(self.app,self.phone,'Chole bhature di 1, kab tak mil juga?',self.guest)
        self.assertEqual(len(self.sent),1)
        self.assertEqual(self.sent[0]['text']['body'],final)
        self.assertIn('order',self.app.order_sessions[self.phone])
        self.assertEqual(self.app.get_conversation_history(self.phone)[-2]['content'],'Chole bhature di 1, kab tak mil juga?')

    def test_all_reviews_finish_before_any_write(self):
        value=self.plan();value['operations'].append({'action':'SERVICE','category':'HOUSEKEEPING','operation_text':'Bring towel','confidence':.95})
        with self.provider([value,self.review(value['operations'][0]),{}]), self.patch.object(self.app,'_process_and_reply') as executor:
            engine.handle(self.app,self.phone,'Food aur towel bhejo',self.guest)
        executor.assert_not_called();self.assertFalse(self.app.order_sessions)

    def test_executor_exception_stops_following_action_without_replay(self):
        value=self.plan();value['operations'].append({'action':'SERVICE','category':'HOUSEKEEPING','operation_text':'Bring towel','confidence':.95})
        attempts=[]
        def executor(*args,**kw):
            attempts.append('order');self.app.active_orders[self.phone]={'order':'1 Chole Bhature'}
            self.app.send_whatsapp_message(self.phone,'Room 450: 1 x Chole Bhature saved.')
            raise RuntimeError('after write')
        with self.provider([value,self.review(value['operations'][0]),self.review(value['operations'][1]),{}]), self.patch.object(self.app,'_process_and_reply',side_effect=executor), self.patch.object(self.app,'_handle_ai_service_route') as service:
            engine.handle(self.app,self.phone,'Food aur towel bhejo',self.guest)
        self.assertEqual(attempts,['order']);service.assert_not_called()
        self.assertIn('uncertain',self.sent[0]['text']['body'])
        self.assertIn('1 x Chole Bhature saved',self.sent[0]['text']['body'])

    def test_readability_feedback_does_not_execute_menu(self):
        value=self.plan(operations=[],questions=['Restate previous reply readably'])
        self.app.conversation_memory[self.phone]=[{'role':'assistant','content':'ਹਿਤੇਸ਼ ਜੀ'}]
        final='Ji, Roman Punjabi vich samjha dindi haan.'
        with self.provider([value,{'reply':final,'answered_questions':[0]},{'supported':True}]), self.patch.object(self.app,'_menu_section_message') as menu:
            engine.handle(self.app,self.phone,'Padhni ni aundi menu',self.guest)
        menu.assert_not_called();self.assertEqual(self.sent[0]['text']['body'],final)

    def test_neutral_confirmation_rejects_wrong_final_script(self):
        value=self.plan(operations=[],questions=[])
        with self.provider([value,{'reply':'ਹਿਤੇਸ਼ ਜੀ','answered_questions':[]} ]):
            engine.handle(self.app,self.phone,'Confirm',self.guest)
        self.assertFalse(any(0x0a00<=ord(c)<=0x0a7f for c in self.sent[0]['text']['body']))

    def test_unsupported_final_reply_never_replays_saved_tool(self):
        value=self.plan();attempts=[]
        def executor(*args,**kw):
            attempts.append(1);self.app.send_whatsapp_message(self.phone,'Room 450: 1 x Chole Bhature saved.')
        with self.provider([value,self.review(value['operations'][0]),
            {'reply':'Room 450: 1 x Chole Bhature delivered.','answered_questions':[0]}, {'supported':False}]), self.patch.object(self.app,'_process_and_reply',side_effect=executor):
            engine.handle(self.app,self.phone,'Chole bhature bhejo',self.guest)
        self.assertEqual(attempts,[1]);self.assertNotIn('delivered.',self.sent[0]['text']['body'])

    def test_missing_side_answer_rejects_incomplete_reply(self):
        value=self.plan(operations=[],questions=['Wi-Fi?','Checkout?'])
        with self.provider([value,{'reply':'Wi-Fi ke liye reception se poochhein.','answered_questions':[0]}]):
            engine.handle(self.app,self.phone,'Wi-Fi aur checkout?',self.guest)
        self.assertIn('poore sawaal',self.sent[0]['text']['body'])

    def test_protected_price_binding_cannot_be_swapped(self):
        self.assertFalse(engine.protected_reply(['A — ₹150\nB — ₹200'],'', 'A — ₹200\nB — ₹150'))
        self.assertTrue(engine.protected_reply(['A — ₹150\nB — ₹200'],'', 'Ji:\nA — ₹150\nB — ₹200'))

    def test_canonical_executor_cannot_replace_outer_guest_message(self):
        value=self.plan();op=value['operations'][0]
        original='Chole bhature di 1, kab tak mil juga?'
        self.app.turn_capture.current={'phone':self.phone,'user':original,'replies':[]}
        def executor(*args,**kw):
            self.app.turn_capture.current['user']='1 Chole Bhature'
            self.app.send_whatsapp_message(self.phone,'Room 450: 1 x Chole Bhature. Confirmation required.')
        final='Room 450: 1 x Chole Bhature. Confirm kar deo. Time abhi confirm nahi hai.'
        with self.provider([value,self.review(op),{'reply':final,'answered_questions':[0]},{'supported':True}]), self.patch.object(self.app,'_process_and_reply',side_effect=executor):
            engine.handle(self.app,self.phone,original,self.guest)
        self.assertEqual(self.app.turn_capture.current['user'],original)

class StructuredGatewayTests(unittest.TestCase):
    def test_invalid_json_falls_through_to_next_provider(self):
        import os
        os.environ['BOT_AUTOSTART']='0'
        import app
        from unittest.mock import patch
        bad=Mock(return_value='I should return JSON but did not.')
        good=Mock(return_value='{"operations":[],"questions":[]}')
        with patch.object(app,'_ai_provider_functions',return_value=[('bad',bad),('good',good)]):
            reply=app.ask_ai_chat('Return JSON',structured=True)
        self.assertEqual(json.loads(reply)['operations'],[])
        self.assertTrue(good.call_args.kwargs['structured'])

class PhotoReceiptTests(unittest.TestCase):
    def test_actual_image_acceptance_produces_a_tool_receipt(self):
        import os
        os.environ['BOT_AUTOSTART']='0'
        import app
        from unittest.mock import patch
        with engine.collect(app,'919555555555') as receipts, patch.object(app,'upload_image_to_whatsapp',return_value='media'), patch.object(app,'whatsapp_request',return_value=SimpleNamespace(status_code=200)):
            app.send_whatsapp_image('919555555555','https://example.com/photo.jpg','Deluxe')
        self.assertTrue(any('accepted' in receipt and 'Deluxe' in receipt for receipt in receipts))

class IndependentServiceTests(EngineTests):
    def test_two_different_services_are_not_collapsed_into_one_action(self):
        value=self.plan(operations=[{'action':'SERVICE','category':'HOUSEKEEPING','operation_text':'Bring towel','confidence':.95},
            {'action':'SERVICE','category':'MAINTENANCE','operation_text':'AC is not cooling','confidence':.95}])
        self.assertIsNotNone(engine.validate_plan(self.bot,value))

    def test_duplicate_service_is_rejected(self):
        op={'action':'SERVICE','category':'HOUSEKEEPING','operation_text':'Bring towel','confidence':.95}
        self.assertIsNone(engine.validate_plan(self.bot,self.plan(operations=[op,dict(op)])))

class SenderStateReplyTests(EngineFlowTests):
    def test_zero_tool_room_question_uses_sender_owned_room_number(self):
        value=self.plan(operations=[],questions=['What is my room?']);value['language']='english'
        with self.provider([value,{'reply':'Your room number is 450.','answered_questions':[0]},{'supported':True}]):
            engine.handle(self.app,self.phone,"What's my room number?",self.guest)
        self.assertEqual(self.sent[0]['text']['body'],'Your room number is 450.')

class ReadableFallbackTests(EngineFlowTests):
    def test_native_tool_receipt_is_not_sent_as_roman_fallback(self):
        value=self.plan()
        def executor(*args,**kw):
            self.app.send_whatsapp_message(self.phone,'ਰੂਮ 450 ਲਈ ਆਰਡਰ ਦਰਜ ਹੋ ਗਿਆ।')
        with self.provider([value,self.review(value['operations'][0]),{}]), self.patch.object(self.app,'_process_and_reply',side_effect=executor):
            engine.handle(self.app,self.phone,'Chole bhature di 1',self.guest)
        self.assertTrue(engine.script_supported(self.sent[0]['text']['body'],'roman'))
        self.assertIn('reception',self.sent[0]['text']['body'].lower())

    def test_readability_restatement_can_use_saved_cart_substance(self):
        value=self.plan(operations=[],questions=['Restate previous saved cart'])
        self.app.order_sessions[self.phone]={'order':'1 Chole Bhature','items':[{'name':'Chole Bhature','qty':1}]}
        self.app.conversation_memory[self.phone]=[{'role':'assistant','content':'ਰੂਮ 450 ਲਈ ਆਰਡਰ ਦੀ ਪੁਸ਼ਟੀ ਕਰੋ।'}]
        final='Room 450 lai 1 Chole Bhature cart vich hai; order confirm nahi hoya. Confirm karna hai?'
        with self.provider([value,{'reply':final,'answered_questions':[0]},{'supported':True}]), self.patch.object(self.app,'_process_and_reply') as executor:
            engine.handle(self.app,self.phone,'Padhni ni aundi menu',self.guest)
        executor.assert_not_called()
        self.assertEqual(self.sent[0]['text']['body'],final)

class ServiceReceiptTruthTests(unittest.TestCase):
    def test_failed_sheet_save_is_not_claimed_as_noted_request(self):
        import os
        os.environ['BOT_AUTOSTART']='0'
        import app
        from unittest.mock import patch
        guest={'name':'Hitesh','room':'450','is_inhouse':True}
        with patch.object(app,'create_service_task',return_value=None),patch.object(app,'send_whatsapp_message') as send,patch.object(app,'get_guest_response_language',return_value='english'):
            app._handle_ai_service_route('919555555555',guest,{'category':'HOUSEKEEPING','service':'Towel'},'Bring towel',True)
        self.assertNotIn("I've noted",send.call_args.args[1])
        self.assertIn("save",send.call_args.args[1])

class PlanContractFailoverTests(unittest.TestCase):
    def test_valid_json_with_wrong_plan_shape_uses_next_provider(self):
        import os
        os.environ['BOT_AUTOSTART']='0'
        import app
        from unittest.mock import patch
        old_shape=Mock(return_value='{"action":"ORDER","language":"hinglish"}')
        good=Mock(return_value=json.dumps({'understood_as':'Food and timing','language':'hinglish',
            'script':'roman','questions':['When?'],'operations':[{'action':'ORDER','category':'KITCHEN',
            'items':[{'name':'Chole Bhature','qty':1}],'operation_text':'','confidence':.95}]}))
        with patch.object(app,'CUSTOMER_CONFIG',{'menu':[{'name':'Chole Bhature'}]}),patch.object(app,'_ai_provider_functions',return_value=[('old',old_shape),('good',good)]):
            reply=app.ask_ai_chat('Return whole-turn plan',structured=True,
                json_validator=lambda value:engine.validate_plan(app,value) is not None)
        self.assertEqual(json.loads(reply)['script'],'roman')
        good.assert_called_once()

class SemanticFallbackRepairTests(unittest.TestCase):
    def test_natural_price_wording_keeps_item_price_binding(self):
        self.assertTrue(engine.protected_reply(['Masala Chai — ₹30'],'','Ji, Masala Chai ka rate ₹30 hai.'))
        self.assertFalse(engine.protected_reply(['A — ₹150\nB — ₹200'],'','A ka rate ₹200 hai, B ka ₹150.'))

    def test_service_items_are_not_validated_as_food_inventory(self):
        bot=SimpleNamespace(CUSTOMER_CONFIG={'menu':[{'name':'Masala Chai'}]})
        value={'understood_as':'towel plus AC','language':'hinglish','script':'roman','questions':[],
            'operations':[{'action':'SERVICE','category':'HOUSEKEEPING','items':[{'name':'Towel','qty':1}],
            'operation_text':'Ek towel bhejo','confidence':.95}]}
        result=engine.validate_plan(bot,value)
        self.assertIsNotNone(result)
        self.assertEqual(result['operations'][0]['items'],[])

    def test_final_reply_contract_validator_is_passed_into_provider_selection(self):
        import os
        os.environ['BOT_AUTOSTART']='0'
        import app
        from unittest.mock import patch
        value={'understood_as':'price question','language':'hinglish','script':'roman','questions':['Price?'],'operations':[]}
        with patch.object(app,'ask_ai_chat',return_value='{}') as ask,patch.object(app,'_ai_knowledge_snapshot',return_value=''):
            engine.finalize(app,'919555555555','Price?',None,value,[])
        self.assertTrue(callable(ask.call_args.kwargs.get('json_validator')))

class RealGatewayReplyFallbackTests(EngineFlowTests):
    def test_bad_finals_reach_cohere_without_replaying_order(self):
        value=self.plan();op=value['operations'][0];attempts=[]
        def executor(*args,**kwargs):
            attempts.append(1)
            self.app.send_whatsapp_message(self.phone,'Room 450: 1 x Chole Bhature. Confirmation required.')
        final='Room 450: 1 x Chole Bhature. Confirm kar deo; delivery time abhi confirm nahi hai.'
        bad={'reply':'Your order was delivered.','answered_questions':[0]}
        gemini=Mock(side_effect=[json.dumps(value),json.dumps(self.review(op)),json.dumps(bad),json.dumps({'supported':True})])
        groq=Mock(return_value=json.dumps(bad))
        cohere=Mock(return_value=json.dumps({'reply':final,'answered_questions':[0]}))
        with self.patch.object(self.app,'_ai_provider_functions',return_value=[('gemini',gemini),('groq',groq),('cohere',cohere)]),self.patch.object(self.app,'_process_and_reply',side_effect=executor):
            engine.handle(self.app,self.phone,'Chole bhature di 1, kab tak milega?',self.guest)
        self.assertEqual(attempts,[1])
        self.assertEqual(self.sent[0]['text']['body'],final)
        self.assertEqual(cohere.call_count,1)

class FinancialProtectionRepairTests(unittest.TestCase):
    def test_markdown_bill_rows_cannot_swap_amounts(self):
        self.assertFalse(engine.protected_reply(['*Room Rent:* Rs. 500\n*Food Total:* Rs. 150'],'',
            '*Room Rent:* Rs. 150\n*Food Total:* Rs. 500'))
