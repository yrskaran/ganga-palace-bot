"""AI boundary regressions use fake transports/providers, real dispatch logic."""
import os
import time
import unittest
from unittest.mock import patch, Mock
os.environ['BOT_AUTOSTART'] = '0'
import app
import ai_receptionist as gateway


class ReceptionistBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.real_send = app.send_whatsapp_message
        self.real_ask = app.ask_ai_chat
        self.patches = []
        for name, value in {
            'CUSTOMER_CONFIG': {'ai_receptionist_flow': True},
            'CUSTOMER_DEMO_MODE': True, 'guest_language_cache': {},
            'reception_request_sessions': {}, 'checkin_sessions': {},
            'order_sessions': {}, 'duplicate_order_sessions': {},
            'service_tasks_by_id': {}, 'service_guest_pending': {},
            'demo_food_sessions': {}, 'demo_guest_sessions': {},
            'conversation_memory': {}, 'get_guest_stay_status': Mock(return_value=None),
            'refresh_staff_roster': Mock(), 'fetch_sheet_data_sync': Mock(return_value=False),
            'send_whatsapp_message': Mock(return_value=True),
            'ask_ai_chat': Mock(return_value='AI result'),
        }.items():
            p = patch.object(app, name, value)
            p.start(); self.patches.append(p)
        self.phone = '919555555555'

    def tearDown(self):
        for p in reversed(self.patches): p.stop()

    def understanding(self, **values):
        return dict({'action': 'ANSWER', 'reply': 'AI ne poori baat samjhi.',
                     'language': 'hinglish', 'confidence': 0.95}, **values)

    def test_language_capability_question_answers_punjabi_without_switching(self):
        app.guest_language_cache[self.phone] = 'hinglish'
        gateway.handle(app, self.phone, 'Punjabi bhi aati hai?', None,
            semantic=self.understanding(action='ANSWER',language='english',
                reply='I can mainly speak Hindi and English.'))
        reply=app.send_whatsapp_message.call_args.args[1]
        self.assertIn('Punjabi vich',reply)
        self.assertNotIn('mainly',reply)
        self.assertEqual(app.guest_language_cache[self.phone],'hinglish')

    def test_language_preference_roman_hindi_stays_casual(self):
        gateway.handle(app,self.phone,
            'Hindi me samjha yaar.. English ni aati ya punjabi me samjha',
            None,semantic=self.understanding(action='ANSWER',language='punjabi',
                reply='कृपया सहायता हेतु बताइए।'))
        reply=app.send_whatsapp_message.call_args.args[1]
        self.assertIn('simple Hindi',reply)
        self.assertNotIn('कृपया',reply)
        self.assertEqual(app.guest_language_cache[self.phone],'hinglish')

    def test_explicit_punjabi_switch_uses_roman_and_keeps_preference(self):
        gateway.handle(app,self.phone,'Punjabi vich gal karo',None,
            semantic=self.understanding(action='ANSWER',language='hinglish'))
        self.assertIn('Punjabi vich gall',app.send_whatsapp_message.call_args.args[1])
        self.assertEqual(app.guest_language_cache[self.phone],'punjabi')
        gateway.handle(app,self.phone,'wifi?',None,
            semantic=self.understanding(action='ANSWER',reply='Wi-Fi ki details reception se milengi.',
                language='english'))
        self.assertEqual(app.guest_language_cache[self.phone],'punjabi')

    def test_language_capability_list_does_not_limit_to_two_languages(self):
        gateway.handle(app,self.phone,'What languages can you speak?',None,
            semantic=self.understanding(action='ANSWER',language='english',
                reply='Only English and Hindi.'))
        reply=app.send_whatsapp_message.call_args.args[1]
        self.assertIn('Punjabi',reply)
        self.assertIn('English',reply)
        self.assertNotIn('Only English',reply)

    def test_regular_hotel_question_never_faked_as_language_switch(self):
        self.assertIsNone(gateway._language_meta(app,self.phone,
            'Room ka rate aur photo batao'))
        self.assertIsNone(gateway._language_meta(app,self.phone,
            'Punjabi guest ka bill batao'))

    def test_literacy_complaint_recovers_previous_reply_without_menu_action(self):
        # Real WhatsApp regression: "Padhni ni aundi menu" = cannot read
        # previous Gurmukhi message; "menu" means "to me", not hotel menu.
        self.assertEqual(app.guest_language('Padhni ni aundi menu'), 'hinglish')
        app.conversation_memory[self.phone] = [
            {'role':'user','content':'Confirm'},
            {'role':'assistant','content':'ਹਿਤੇਸ਼ ਜੀ, ਰੂਮ 450 ਲਈ 1 x ਛੋਲੇ ਭਟੂਰੇ ਦਾ ਆਰਡਰ ਨੋਟ ਕੀਤਾ ਗਿਆ ਹੈ।'}]
        app.ask_ai_chat.return_value = (
            '{"reply":"Room 450 ke liye 1 x Chole Bhature ka order note kiya gaya hai."}')
        with patch.object(app, '_process_and_reply') as executor:
            gateway.handle(app, self.phone, 'Padhni ni aundi menu', None,
                semantic=self.understanding(action='SHOW_MENU', language='punjabi',
                    menu_section='BREAKFAST'))
        executor.assert_not_called()
        reply=app.send_whatsapp_message.call_args.args[1]
        self.assertIn('Roman Hindi',reply)
        self.assertIn('Room 450',reply)
        self.assertNotIn('Breakfast Menu',reply)
        self.assertFalse(any(0x0a00 <= ord(ch) <= 0x0a7f for ch in reply))
        self.assertEqual(app.guest_language_cache[self.phone], 'hinglish')

    def test_real_food_menu_request_is_not_a_literacy_correction(self):
        app.conversation_memory[self.phone] = [
            {'role':'assistant','content':'ਇੱਥੇ ਹੋਟਲ ਦੇ ਨਾਸ਼ਤੇ ਦੀ ਸੂਚੀ ਹੈ।'}]
        self.assertIsNone(gateway._reading_correction(
            app,self.phone,'Breakfast menu dikhao'))
        self.assertIsNone(gateway._reading_correction(
            app,self.phone,'Menu ka price padh ke batao'))

    def test_ai_reviewer_can_repair_menu_into_conversational_answer(self):
        import json
        candidate=self.understanding(action='SHOW_MENU',language='punjabi',
            menu_section='BREAKFAST')
        review={'menu_related':False,'blocked':False,'language':'hinglish',
            'action':'ANSWER','operation_text':'','show_prices':False,
            'reply':'Sorry ji, pichhla message Roman Hindi mein samjha deti hoon.'}
        result=gateway.review_plan(app,'Padhni ni aundi menu',candidate,
            [{'role':'assistant','content':'ਪੰਜਾਬੀ ਵਿਚ ਜਵਾਬ'}],
            provider=Mock(return_value=json.dumps(review)),pending={})
        self.assertEqual(result['action'],'ANSWER')
        self.assertEqual(result['language'],'hinglish')
        self.assertNotEqual(result['action'],'SHOW_MENU')
        self.assertFalse(result['needs_reception'])

    def test_failed_qa_hinglish_menu_question_keeps_script_and_verified_item(self):
        app.CUSTOMER_CONFIG['menu'] = [{'name':'Standard Veg Thali','price':200}]
        gateway.handle(app,self.phone,'Standard veg thali bhi hai?',None,
            semantic=self.understanding(action='MENU_ITEM_INFO',language='english',
                items=[{'name':'Standard Veg Thali','qty':1}],show_prices=False))
        reply=app.send_whatsapp_message.call_args.args[1]
        self.assertIn('menu mein',reply)
        self.assertIn('Standard Veg Thali',reply)
        self.assertNotIn('₹',reply)
        self.assertEqual(app.guest_language_cache[self.phone],'hinglish')

    def test_failed_qa_hindi_price_question_has_devanagari_intro(self):
        app.CUSTOMER_CONFIG['menu'] = [{'name':'Standard Veg Thali','price':200}]
        gateway.handle(app,self.phone,'थाली कितने की है?',None,
            semantic=self.understanding(action='MENU_ITEM_INFO',language='hinglish',
                items=[{'name':'Standard Veg Thali','qty':1}],show_prices=True))
        reply=app.send_whatsapp_message.call_args.args[1]
        self.assertIn('कीमत',reply)
        self.assertIn('Standard Veg Thali — ₹200',reply)
        self.assertEqual(app.guest_language_cache[self.phone],'hindi')

    def test_failed_qa_bed_enquiry_keeps_room_context_and_requires_verification(self):
        app.CUSTOMER_CONFIG['rooms'] = [{'name':'Premium Window'}]
        app.conversation_memory[self.phone] = [
            {'role':'assistant','content':'Premium Window room ki photo available hai.'}]
        with patch.object(app,'reply_to_reception_request',return_value=False) as handoff:
            gateway.handle(app,self.phone,'2 alag bed milenge ya double bed?',None,
                semantic=self.understanding(action='ROOM_OPTIONS',
                    reply='Available room categories are Deluxe and Premium Window.'))
        handoff.assert_called_once()
        request=handoff.call_args.args[2]
        self.assertIn('Premium Window',request)
        self.assertIn('2 alag bed',request)
        self.assertNotIn('categories',request)

    def test_failed_qa_group_count_does_not_turn_into_room_category_list(self):
        app.CUSTOMER_CONFIG['rooms'] = [{'name':'Family Suite'}]
        with patch.object(app,'reply_to_reception_request',return_value=False) as handoff:
            gateway.handle(app,self.phone,'Hum 2 adults aur ek 6 saal ka baccha hain',None,
                semantic=self.understanding(action='ROOM_OPTIONS',
                    reply='Ji, Family Suite available hai.'))
        self.assertIn('6 saal',handoff.call_args.args[2])
        self.assertEqual(app.guest_language_cache[self.phone],'hinglish')

    def test_failed_qa_photo_receives_current_message_not_only_model_target(self):
        with patch.object(app,'_handle_ai_photo_route') as photos:
            gateway.handle(app,self.phone,'Ab hotel bahar se kaisa hai wo photo bhejo',None,
                semantic=self.understanding(action='SHOW_PHOTO',photo_target='Hotel Exterior'))
        photos.assert_called_once()
        self.assertEqual(photos.call_args.args[3],
                         'Ab hotel bahar se kaisa hai wo photo bhejo')

    def test_failed_qa_checkin_process_decline_is_not_claimed_as_cancellation(self):
        gateway.handle(app,self.phone,'Main bas process pooch raha tha, start mat karo',None,
            semantic=self.understanding(action='CHECKIN_CANCEL'))
        reply=app.send_whatsapp_message.call_args.args[1]
        self.assertIn('koi self check-in chal nahi raha',reply)
        self.assertFalse(app.checkin_sessions)

    def test_enabled_interpreter_keeps_recent_context_within_input_budget(self):
        app.conversation_memory[self.phone] = [
            {'role':'user','content':'Standard veg thali bhi hai?'},
            {'role':'assistant','content':'Standard Veg Thali demo menu mein listed hai.'}]
        response = Mock(status_code=200)
        response.json.return_value = {'choices':[{'message':{'content':'{"action":"MENU_ITEM_INFO"}'},'finish_reason':'stop'}]}
        with patch.object(app,'get_active_groq_model',return_value='qwen/qwen3.8-27b'), \
             patch.object(app,'_groq_circuit_open',return_value=False), \
             patch.object(app.requests,'post',return_value=response) as post:
            app.ask_groq_chat(app._ai_understanding_prompt('Kitne ki hai?', None, self.phone),sender_phone=self.phone,structured=True)
        messages = post.call_args.kwargs['json']['messages']
        self.assertTrue(any(m['role']=='user' and m['content']=='Standard veg thali bhi hai?' for m in messages))
        self.assertTrue(any(m['role']=='assistant' and 'Standard Veg Thali' in m['content'] for m in messages))
        self.assertLess(sum(len(m['content'].encode()) for m in messages),12400)

    def test_review_repairs_menu_misclassification_into_two_item_order(self):
        import json
        app.CUSTOMER_CONFIG['menu']=[{'name':'Masala Chai','price':30}]
        candidate=self.understanding(action='MENU_ITEM_INFO',items=[{'name':'Masala Chai','qty':1}])
        review={'operational':True,'action':'ORDER','items':[{'name':'Masala Chai','qty':2}],
                'category':'KITCHEN','operation_text':'','reply':'','language':'hinglish','confidence':0.97}
        provider=Mock(return_value=json.dumps(review))
        result=gateway.review_plan(app,'2 masala chai room mein bhej do',candidate,[],provider=provider,pending={})
        self.assertIn('operational',provider.call_args.args[0])
        self.assertIn('Revisions return the complete resulting cart',provider.call_args.args[0])
        self.assertEqual(result['action'],'ORDER')
        self.assertEqual(result['items'],[{'name':'Masala Chai','qty':2}])
        self.assertFalse(result['needs_reception'])

    def test_every_review_branch_explicitly_requests_current_language(self):
        import json,re
        provider=Mock(return_value=json.dumps({'menu_related':False,'blocked':False,'language':'hinglish','reply':'Ji.'}))
        gateway.review_plan(app,'Standard veg thali bhi hai?',self.understanding(),[],provider=provider,pending={})
        prompt=provider.call_args.args[0]
        schemas=re.findall(r'return (\{.*?\})',prompt,re.I)
        self.assertTrue(schemas)
        self.assertTrue(all('language' in schema for schema in schemas))

    def test_wifi_factual_reply_is_reviewed_and_corrected_without_tv_password_claim(self):
        import json
        provider=Mock(return_value=json.dumps({'menu_related':False,'blocked':False,'language':'hinglish',
             'action':'ANSWER','operation_text':'','reply':'Wi-Fi password verified nahi hai; reception se confirm karna hoga.'}))
        original=self.understanding(action='WIFI',reply='Password TV screen par hai.')
        with patch.object(app,'_ai_knowledge_snapshot',return_value='Complimentary Wi-Fi; no password is configured.'):
            result=gateway.review_plan(app,'Wifi password batao',original,[],provider=provider,pending={})
        provider.assert_called_once()
        self.assertEqual(result['action'],'ANSWER')
        self.assertNotIn('TV',result['reply'])
        self.assertIn('no password is configured',provider.call_args.args[0])

    def test_room_tariff_misclassification_can_be_repaired_to_own_room_bill_scope(self):
        import json
        review={'menu_related':False,'blocked':False,'language':'hinglish','action':'BILL',
                'operation_text':'room','reply':''}
        result=gateway.review_plan(app,'Room ka rent alag batao',self.understanding(action='ROOM_RATE'),
             [{'role':'user','content':'Mera bill dikhao'}],guest={'room':'240','is_inhouse':True},
             provider=Mock(return_value=json.dumps(review)),pending={})
        self.assertEqual(result['action'],'BILL')
        self.assertEqual(result['operation_text'],'room')
        self.assertEqual(result['reply'],'')

    def test_review_cannot_create_unknown_bill_scope_or_invent_an_action(self):
        import json
        for review in ({'action':'BILL','operation_text':'other_guest'}, {'action':'MARK_PAID','operation_text':'full'}):
            with self.subTest(review=review):
                review=dict(review,menu_related=False,blocked=False,language='hinglish',reply='')
                self.assertIsNone(gateway.review_plan(app,'Mera bill',self.understanding(action='BILL'),[],
                      provider=Mock(return_value=json.dumps(review)),pending={}))

    def test_factual_room_options_review_keeps_requested_price_flag(self):
        import json
        review={'menu_related':False,'blocked':False,'language':'hinglish','action':'ROOM_OPTIONS',
                'operation_text':'','show_prices':True,'reply':'Room categories ke starting rates dikhati hoon.'}
        result=gateway.review_plan(app,'Room options aur unke rates dikhao',
                self.understanding(action='ROOM_OPTIONS',show_prices=True),[],
                provider=Mock(return_value=json.dumps(review)),pending={})
        self.assertTrue(result['show_prices'])

    def test_result_verifier_receives_original_urgent_guest_question_as_context(self):
        import json
        question='Mujhe saans lene mein dikkat hai doctor bulao'
        reply='Reception tak message nahi pahunch paaya. Abhi onsite/emergency help lein; chat par intezar na karein.'
        app.ask_ai_chat.side_effect=[json.dumps({'reply':reply}),json.dumps({'supported':True})]
        token=gateway.current.set({'phone':app.format_whatsapp_number(self.phone),'text':question,
                  'language':'hinglish','meaning':'Urgent medical help requested','guest':None,'direct':False})
        try:
            self.assertEqual(gateway.compose(app,self.phone,'Doctor help requested. Reception notification failed. No doctor arrival verified.'),reply)
        finally:
            gateway.current.reset(token)
        self.assertIn(question,app.ask_ai_chat.call_args.args[0])

    def test_observed_operational_reception_review_routes_task_without_claiming_stock(self):
        import json
        review={'operational':True,'action':'RECEPTION','items':[],'category':'NONE',
                'operation_text':'Check room availability for 2 guests tomorrow','language':'hinglish',
                'confidence':0.95,'reply':'Room available hai, booking kar lo.'}
        result=gateway.review_plan(app,'Kal 2 logo ke liye kamra milega?',self.understanding(action='RECEPTION'),[],
                   provider=Mock(return_value=json.dumps(review)),pending={})
        self.assertIsNotNone(result)
        self.assertEqual(result['action'],'RECEPTION')
        self.assertTrue(result['needs_reception'])
        self.assertEqual(result['reception_request'],review['operation_text'])
        self.assertEqual(result['reply'],'')

    def test_operational_review_validates_inventory_and_confirmation_state(self):
        import json
        app.CUSTOMER_CONFIG['menu']=[{'name':'Masala Chai','price':30}]
        candidate=self.understanding(action='ORDER')
        review={'operational':True,'action':'ORDER','items':[{'name':'Invented Tea','qty':2}],
                'category':'KITCHEN','operation_text':'','reply':'','language':'hinglish','confidence':0.97}
        self.assertIsNone(gateway.review_plan(app,'2 chai bhejo',candidate,[],provider=Mock(return_value=json.dumps(review)),pending={}))
        review.update(action='ORDER_CONFIRM',items=[])
        result=gateway.review_plan(app,'Haan confirm',candidate,[],provider=Mock(return_value=json.dumps(review)),pending={})
        self.assertEqual(result['action'],'ORDER_CONFIRM')  # Executor reports missing cart; understanding remains valid.

    def test_duplicate_cart_confirmation_survives_operational_review(self):
        import json
        app.CUSTOMER_CONFIG['menu']=[{'name':'Masala Chai','price':30}]
        review={'operational':True,'action':'ORDER_CONFIRM','items':[],'category':'KITCHEN',
                'operation_text':'','reply':'','language':'hinglish','confidence':0.97}
        result=gateway.review_plan(app,'Haan wahi confirm',self.understanding(action='ORDER_CONFIRM'),[],
                    provider=Mock(return_value=json.dumps(review)),pending={'duplicate_order_sessions':{'order':'2 Masala Chai','total':60}})
        self.assertEqual(result['action'],'ORDER_CONFIRM')

    def test_order_candidate_can_be_repaired_to_price_enquiry_without_execution(self):
        import json
        app.CUSTOMER_CONFIG['menu']=[{'name':'Masala Chai','price':30}]
        review={'menu_related':True,'action':'MENU_ITEM_INFO','request_kind':'price','items':[{'name':'Masala Chai','qty':1}],
                'excluded_items':[],'show_prices':True,'needs_reception':False,'reception_request':'','menu_section':''}
        result=gateway.review_plan(app,'Chai ka rate poocha bhejna nahi',self.understanding(action='ORDER'),[],
                    provider=Mock(return_value=json.dumps(review)),pending={})
        self.assertEqual(result['action'],'MENU_ITEM_INFO')
        self.assertTrue(result['show_prices'])

    def test_typo_interpretation_receives_complete_canonical_inventory(self):
        app.CUSTOMER_CONFIG['menu'] = [{'name':'Boondi Raita','price':70},{'name':'Jeera Rice','price':140}]
        response = Mock(status_code=200)
        response.json.return_value = {'choices':[{'message':{'content':'{"action":"MENU_ITEM_INFO"}'},'finish_reason':'stop'}]}
        with patch.object(app, '_ai_knowledge_snapshot', return_value='Free parking'), \
             patch.object(app, 'get_active_groq_model', return_value='qwen/qwen3.8-27b'), \
             patch.object(app, '_groq_circuit_open', return_value=False), \
             patch.object(app.requests, 'post', return_value=response) as provider:
            app.ask_groq_chat(app._ai_understanding_prompt('Bundi rayta kitne ka h?', None, self.phone), structured=True)
        context = '\n'.join(row['content'] for row in provider.call_args.kwargs['json']['messages'])
        self.assertIn('Boondi Raita', context)
        self.assertIn('Jeera Rice', context)

    def test_plan_review_replaces_broad_menu_selection_without_dispatch(self):
        import json
        app.CUSTOMER_CONFIG['menu'] = [{'name':'Masala Chai'},{'name':'Hot Coffee'}]
        original = self.understanding(action='SHOW_MENU', menu_section='DRINKS', operation_text='')
        review = {'menu_related':True,'action':'MENU_ITEM_INFO','items':[{'name':'Masala Chai','qty':1}],
                  'excluded_items':['Hot Coffee'],'show_prices':False,'needs_reception':False,
                  'request_kind':'listed_options','understood_as':'Only chai options'}
        provider = Mock(return_value=json.dumps(review))
        result = gateway.review_plan(app, 'Chai ke options?', original, [], provider=provider)
        self.assertEqual(result['action'], 'MENU_ITEM_INFO')
        self.assertEqual(result['items'], review['items'])
        self.assertEqual(result['reply'], '')
        app.send_whatsapp_message.assert_not_called()

    def test_plan_review_rejects_invented_or_excluded_selection(self):
        import json
        app.CUSTOMER_CONFIG['menu'] = [{'name':'Masala Chai'}]
        for name, excluded in [('Invented Chai', []), ('Masala Chai', ['Masala Chai'])]:
            provider = Mock(return_value=json.dumps({'menu_related':True,'action':'MENU_ITEM_INFO',
                'items':[{'name':name,'qty':1}], 'excluded_items':excluded,'show_prices':False,
                'needs_reception':False,'request_kind':'listed_options'}))
            self.assertIsNone(gateway.review_plan(app, 'Chai?', self.understanding(action='SHOW_MENU'), [], provider=provider))

    def test_excluded_item_objects_are_losslessly_normalized(self):
        import json
        app.CUSTOMER_CONFIG['menu']=[{'name':'Standard Veg Thali'},{'name':'Special Deluxe Ganga Thali'}]
        review={'menu_related':True,'action':'MENU_ITEM_INFO','language':'hinglish','request_kind':'listed_options','items':[{'name':'Special Deluxe Ganga Thali','qty':1}],'excluded_items':[{'name':'Standard Veg Thali','qty':1}],'show_prices':False,'needs_reception':False}
        result=gateway.review_plan(app,'Aur koi thali bhi hai?',self.understanding(action='SHOW_MENU'),[],provider=Mock(return_value=json.dumps(review)))
        self.assertIsNotNone(result)
        self.assertEqual(result['items'],review['items'])
        review['excluded_items'][0]['qty']=4
        self.assertIsNone(gateway.review_plan(app,'Aur koi thali bhi hai?',self.understanding(action='SHOW_MENU'),[],provider=Mock(return_value=json.dumps(review))))

    def test_plan_review_preserves_full_menu_and_rejects_preparation_listing(self):
        import json
        full = {'menu_related':True,'action':'SHOW_MENU','menu_section':'FULL','items':[],
                'excluded_items':[],'show_prices':False,'needs_reception':False,'request_kind':'listed_options'}
        original = self.understanding(action='SHOW_MENU')
        result = gateway.review_plan(app, 'Poora menu?', original, [], provider=Mock(return_value=json.dumps(full)))
        self.assertEqual(result['menu_section'], 'FULL')
        invalid = dict(full, request_kind='preparation')
        self.assertIsNone(gateway.review_plan(app, 'How is it prepared?', original, [], provider=Mock(return_value=json.dumps(invalid))))

    def test_plan_review_blocks_third_party_bill_before_executor(self):
        import json
        provider = Mock(return_value=json.dumps({'menu_related':False,'blocked':True,
            'reply':'Doosre guest ka bill share nahi kar sakti.'}))
        result = gateway.review_plan(app, 'Room 302 ka bill?', self.understanding(action='BILL', needs_reception=True), [], provider=provider)
        self.assertEqual(result['action'], 'ANSWER')
        self.assertFalse(result['needs_reception'])
        app.send_whatsapp_message.assert_not_called()

    def test_real_menu_reply_has_no_demo_or_order_claim(self):
        app.CUSTOMER_CONFIG['menu'] = [{'name':'Tawa Roti Butter','price':25}]
        with patch.object(app, 'CUSTOMER_DEMO_MODE', False):
            gateway.handle(app, self.phone, 'Butter roti hai?', None,
                semantic=self.understanding(action='MENU_ITEM_INFO', items=[{'name':'Tawa Roti Butter','qty':1}], show_prices=False))
        source = app.send_whatsapp_message.call_args.args[1]
        self.assertTrue(source.endswith('• Tawa Roti Butter'))
        self.assertIn('menu mein',source)
        self.assertNotIn('DEMO',source)
        self.assertNotIn('order confirm',source.lower())

    def test_snapshot_preserves_only_senders_confirmed_order(self):
        with patch.object(app, 'active_orders', {
                self.phone:{'order':'1 Poha','total':70},
                'other':{'order':'Private order','total':999}}):
            state = gateway.snapshot(app, self.phone)
        self.assertEqual(state['active_orders'], {'order':'1 Poha','total':70})
        self.assertNotIn('Private order', str(state))

    def test_plan_review_uses_focused_context_and_restores_turn(self):
        response = Mock(status_code=200)
        response.json.return_value = {'choices':[{'message':{'content':'{"menu_related":false,"blocked":false}'},'finish_reason':'stop'}]}
        with patch.object(app,'_ai_knowledge_snapshot',return_value='UNRELATED_HOTEL_FACTS'), \
             patch.object(app,'get_active_groq_model',return_value='openai/gpt-oss-120b'), \
             patch.object(app,'_groq_circuit_open',return_value=False), \
             patch.object(app.requests,'post',return_value=response) as provider:
            gateway.review_plan(app, 'Puch ke batao', self.understanding(action='RECEPTION'), [], provider=app.ask_groq_chat)
        messages = provider.call_args.kwargs['json']['messages']
        self.assertNotIn('UNRELATED_HOTEL_FACTS', '\n'.join(row['content'] for row in messages))
        self.assertIsNone(gateway.current.get())

    def test_provider_allows_one_six_second_inference_reset(self):
        limited = Mock(status_code=429,text='input tokens per minute',headers={'retry-after':'6'})
        success = Mock(status_code=200)
        success.json.return_value = {'choices':[{'message':{'content':'{"action":"ANSWER","reply":"Ji"}'},'finish_reason':'stop'}]}
        with patch.object(app,'get_active_groq_model',return_value='openai/gpt-oss-120b'), \
             patch.object(app,'_groq_circuit_open',return_value=False), \
             patch.object(app.requests,'post',side_effect=[limited,success]) as post, \
             patch.object(app.time,'sleep') as wait:
            self.assertIsNotNone(app.ask_groq_chat('hello',structured=True))
        self.assertEqual(post.call_count,2)
        wait.assert_called_once_with(6)
        app.send_whatsapp_message.assert_not_called()

    def test_short_provider_rate_limit_retries_once_before_fallback(self):
        limited = Mock(status_code=429,text='input tokens per minute',headers={'retry-after':'1'})
        success = Mock(status_code=200)
        success.json.return_value = {'choices':[{'message':{'content':'{"action":"ANSWER","reply":"Ji"}'},'finish_reason':'stop'}]}
        with patch.object(app,'get_active_groq_model',return_value='qwen/qwen3.8-27b'), \
             patch.object(app,'_groq_circuit_open',return_value=False), \
             patch.object(app.requests,'post',side_effect=[limited,success]) as post, \
             patch.object(app.time,'sleep') as wait:
            self.assertIsNotNone(app.ask_groq_chat('hello',structured=True))
        self.assertEqual(post.call_count,2)
        wait.assert_called_once_with(1)
        app.send_whatsapp_message.assert_not_called()

    def test_live_readiness_uses_one_read_only_contract_probe(self):
        import json
        with patch.object(app, 'GROQ_API_KEY', 'test'), patch.object(app, 'ask_groq_chat',
            return_value=json.dumps(self.understanding(action='RECEPTION', operation_text=''))) as provider:
            app.check_ai_readiness()
        provider.assert_called_once()
        self.assertEqual(app.AI_READINESS['status'], 'available')
        app.send_whatsapp_message.assert_not_called()

    def test_live_item_result_probe_actually_runs_composer_without_transport(self):
        import json
        app.CUSTOMER_CONFIG['menu'] = [{'name':'Standard Veg Thali','price':70}, {'name':'Special Deluxe Ganga Thali','price':290}]
        app.ask_ai_chat.side_effect = ['{"reply":"Ji, Special Deluxe Ganga Thali bhi DEMO menu mein listed hai. Kitchen availability confirm nahi hai."}', '{"supported":true}']
        with patch.object(app, 'GROQ_API_KEY','test'), patch.object(app,'ask_groq_chat',
            return_value=json.dumps(self.understanding(action='MENU_ITEM_INFO', operation_text='',
                show_prices=False,items=[{'name':'Special Deluxe Ganga Thali','qty':1}]))):
            app.check_ai_readiness()
        self.assertEqual(app.ask_ai_chat.call_count, 2)
        self.assertEqual(app.AI_READINESS['status'], 'available')
        app.send_whatsapp_message.assert_not_called()
        self.assertIsNone(gateway.current.get())

    def test_composer_rejects_drafting_even_when_fact_checker_accepts(self):
        token = gateway.current.set({'phone':self.phone, 'text':'menu',
            'language':'hinglish', 'meaning':'asks menu'})
        try:
            source = 'Breads & Rice: Plain Naan, Jeera Rice'
            app.ask_ai_chat.side_effect = [
                'We have a verified backend result. We need to produce a natural Hinglish reply. '+source,
                '{"supported":true}']
            self.assertEqual(gateway.compose(app, self.phone, source), source)
        finally: gateway.current.reset(token)

    def test_composer_rejects_drafting_inside_reply_envelope(self):
        token = gateway.current.set({'phone':self.phone, 'text':'menu',
            'language':'hinglish', 'meaning':'asks menu'})
        try:
            source = 'Breads & Rice: Plain Naan, Jeera Rice'
            app.ask_ai_chat.side_effect = [
                '{"reply":"We need to produce a natural Hinglish reply. Breads & Rice: Plain Naan, Jeera Rice"}',
                '{"supported":true}']
            self.assertEqual(gateway.compose(app, self.phone, source), source)
        finally: gateway.current.reset(token)

    def test_result_provider_uses_only_verified_result_without_hotel_database(self):
        token = gateway.current.set({'phone':self.phone,'text':'price', 'language':'hinglish', 'meaning':'asks price'})
        try:
            with patch.object(app, 'get_hotel_data',return_value='EXTRA HOTEL FACTS SHOULD NOT ENTER RESULT REPLY'):
                messages = app._openai_messages('VERIFIED RESULT: Boondi Raita ₹80', structured=False)
            self.assertNotIn('EXTRA HOTEL FACTS', str(messages))
        finally: gateway.current.reset(token)

    def test_provider_gateway_rejects_draft_and_uses_next_provider(self):
        with patch.object(app, '_ai_provider_functions', return_value=[
            ('bad', lambda *args: 'We have a verified backend result. We need to produce a reply.'),
            ('good', lambda *args: 'Ji, yeh raha menu.')]):
            result = self.real_ask('Menu')
        self.assertEqual(result, 'Ji, yeh raha menu.')

    def test_single_price_may_be_worded_naturally_without_changing_item_or_amount(self):
        source = 'Boondi Raita — ₹70\nDEMO menu price; kitchen availability unconfirmed.'
        self.assertTrue(gateway.faithful_numbers_and_links(source, 'Boondi Raita ka DEMO rate ₹70 hai.'))
        self.assertFalse(gateway.faithful_numbers_and_links(source, 'Poha ka DEMO rate ₹70 hai.'))
        self.assertFalse(gateway.faithful_numbers_and_links(source, 'Boondi Raita ka DEMO rate ₹80 hai.'))

    def test_two_item_price_rows_cannot_swap_amounts(self):
        self.assertFalse(gateway.faithful_numbers_and_links(
            '• Poha — ₹70\n• Chai — ₹30', '• Poha — ₹30\n• Chai — ₹70'))
        self.assertFalse(gateway.faithful_numbers_and_links(
            'Poha — ₹70\nChai — ₹30', 'Poha — ₹30\nChai — ₹70'))

    def test_item_price_enquiry_returns_only_verified_item_without_order(self):
        app.CUSTOMER_CONFIG['menu'] = [{'name':'Boondi Raita','price':80},{'name':'Poha','price':70}]
        with patch.object(app, '_process_and_reply', side_effect=AssertionError('enquiry executed as order')):
            gateway.handle(app, self.phone, 'Boondi raita kitne ka', None,
                semantic=self.understanding(action='MENU_ITEM_INFO', show_prices=True,
                    items=[{'name':'Boondi Raita','qty':1}]))
        output = app.send_whatsapp_message.call_args.args[1]
        self.assertIn('Boondi Raita', output)
        self.assertIn('80', output)
        self.assertNotIn('Poha', output)
        self.assertEqual(app.demo_food_sessions, {})

    def test_multiple_item_availability_is_one_natural_reply_without_raw_appendix(self):
        app.CUSTOMER_CONFIG['menu'] = [{'name':'Cutting Chai','price':20},{'name':'Masala Chai','price':30}]
        app.ask_ai_chat.side_effect = ['{"reply":"Chai mein Cutting Chai aur Masala Chai DEMO menu mein listed hain. Kitchen availability confirm nahi hai."}', '{"supported":true}']
        with patch.object(app, 'send_whatsapp_message', wraps=self.real_send), \
             patch.object(app, 'whatsapp_request', return_value=Mock(status_code=200)) as transport:
            gateway.handle(app, self.phone, 'Chai me kya kya option hai', None,
                semantic=self.understanding(action='MENU_ITEM_INFO', show_prices=False,
                    items=[{'name':'Cutting Chai','qty':1},{'name':'Masala Chai','qty':1}]))
            output = transport.call_args.args[0]['text']['body']
        self.assertNotIn('is listed on the configured menu', output)
        self.assertEqual(output.count('Cutting Chai'), 1)
        self.assertEqual(output.count('Masala Chai'), 1)

    def test_menu_cards_preserve_data_without_composing_each_card(self):
        app.CUSTOMER_CONFIG.update(demo_food_enabled=True,
            menu=[{'name':'Poha','price':70},{'name':'Butter Naan','price':40},
                  {'name':'Boondi Raita','price':80},{'name':'Hot Coffee','price':40}])
        app.ask_ai_chat.side_effect = ['{"reply":"Ji, demo menu yeh raha."}', '{"supported":true}']
        gateway.handle(app, self.phone, 'Menu dikhao', None,
            semantic=self.understanding(action='SHOW_MENU',menu_section='FULL'))
        self.assertEqual(app.ask_ai_chat.call_count, 2)
        body = '\n'.join(call.args[1] for call in app.send_whatsapp_message.call_args_list)
        for item in ('Poha','Butter Naan','Boondi Raita','Hot Coffee'):
            self.assertIn(item, body)

    def test_cohere_length_output_is_not_a_final_reply(self):
        response = Mock(status_code=200)
        response.json.return_value = {'choices':[{'message':{'content':'We need to produce a natural Hinglish reply'},'finish_reason':'length'}]}
        with patch.object(app, 'COHERE_API_KEY','test'), patch.object(app, '_cohere_circuit_open',return_value=False), \
             patch.object(app.requests, 'post', return_value=response):
            self.assertIsNone(app.ask_cohere_chat('Menu reply'))

    def test_enabled_router_bypasses_keyword_and_language_shortcuts(self):
        result = self.understanding()
        with patch.object(app, 'understand_guest_request', return_value=result) as brain, \
             patch.object(app, 'find_menu_items', side_effect=AssertionError('raw question parsed by Python')), \
             patch.object(app, 'remember_guest_language', side_effect=AssertionError('language guessed by Python')):
            app._process_and_reply({'text': {'body': 'Dudh manga, dish nahi'}}, self.phone, 'text')
        brain.assert_called_once()
        self.assertEqual(app.send_whatsapp_message.call_args.args[1], result['reply'])

    def test_ai_answer_bypasses_pending_cart(self):
        app.order_sessions[self.phone] = {'order': '1 Poha', 'total': 70}
        gateway.handle(app, self.phone, 'Pehle wifi batao', None, semantic=self.understanding())
        self.assertEqual(app.order_sessions[self.phone]['total'], 70)
        self.assertEqual(app.send_whatsapp_message.call_args.args[1], 'AI ne poori baat samjhi.')

    def test_identity_also_goes_through_ai(self):
        with patch.object(app, 'handle_room_cleaning_message', return_value=False), \
             patch.object(app, 'handle_service_staff_message', return_value=False), \
             patch.object(app, 'handle_reception_operator_message', return_value=False), \
             patch.object(app, 'maybe_react_to_guest_message'), \
             patch.object(app, 'understand_guest_request', return_value=self.understanding(reply='Main Monika hoon.')) as brain:
            app.process_and_reply({'text': {'body': 'aapka naam kya hai'}}, self.phone, 'text')
        brain.assert_called_once()
        self.assertEqual(app.send_whatsapp_message.call_args.args[1], 'Main Monika hoon.')

    def test_composer_cannot_swap_menu_item_prices(self):
        source = 'Menu\nPoha Rs. 70\nChai Rs. 30'
        self.assertFalse(gateway.faithful_numbers_and_links(source, 'Menu\nPoha Rs. 30\nChai Rs. 70'))
        self.assertTrue(gateway.faithful_numbers_and_links(source, 'Ji, yeh menu hai:\nPoha Rs. 70\nChai Rs. 30'))

    def test_guest_transport_uses_ai_composed_result(self):
        # Restore the real send boundary while keeping the network fake.
        from unittest.mock import patch
        real_send = self.real_send
        token = gateway.current.set({'phone': self.phone, 'text': 'hisaab',
            'language': 'hinglish', 'meaning': 'asks for bill'})
        response = Mock(status_code=200)
        try:
            app.ask_ai_chat.return_value = 'Ji, Rs. 70 hai.'
            app.ask_ai_chat.side_effect = ['{"reply":"Ji, Rs. 70 hai."}', '{"supported":true}']
            with patch.object(app, 'whatsapp_request', return_value=response) as transport:
                self.assertTrue(real_send(self.phone, 'Total Rs. 70'))
            self.assertEqual(transport.call_args.args[0]['text']['body'], 'Ji, Rs. 70 hai.')
        finally: gateway.current.reset(token)

    def test_ai_unavailable_never_runs_legacy_actions(self):
        with patch.object(app, 'understand_guest_request', return_value=None), \
             patch.object(app, '_process_and_reply') as executor:
            gateway.handle(app, self.phone, '2 Poha bhejo', None)
        executor.assert_not_called()

    def test_order_executor_receives_canonical_items_not_guest_utterance(self):
        with patch.object(app, '_process_and_reply') as executor:
            gateway.handle(app, self.phone, 'do pohe laana', None, semantic=self.understanding(
                action='ORDER', items=[{'name': 'Poha', 'qty': 2}]))
        self.assertEqual(executor.call_args.args[0]['text']['body'], '2 Poha')
        self.assertTrue(executor.call_args.kwargs['_executor'])

    def test_side_question_cannot_become_checkin_name(self):
        app.checkin_sessions[self.phone] = {'step': 'NAME', 'created': time.time()}
        gateway.handle(app, self.phone, 'Room ka rate kya hai?', None, semantic=self.understanding())
        self.assertNotIn('name', app.checkin_sessions[self.phone])

    def test_checkin_details_only_accept_verified_otp(self):
        app.checkin_sessions[self.phone] = {'step': 'OTP', 'otp': '1234', 'created': time.time()}
        gateway.handle(app, self.phone, 'mera code 9999', None, semantic=self.understanding(
            action='CHECKIN_DETAILS', operation_text='9999'))
        self.assertEqual(app.checkin_sessions[self.phone]['step'], 'OTP')
        gateway.handle(app, self.phone, '1234', None, semantic=self.understanding(
            action='CHECKIN_DETAILS', operation_text='1234'))
        self.assertEqual(app.checkin_sessions[self.phone]['step'], 'NAME')

    def test_composer_preserves_backend_price_and_rejects_invented_price(self):
        token = gateway.current.set({'phone': self.phone, 'text': 'hisaab batao',
            'language': 'hinglish', 'meaning': 'asks for verified bill'})
        try:
            app.ask_ai_chat.return_value = '{"reply":"Ji, total Rs. 80 hai."}'
            self.assertEqual(gateway.compose(app, self.phone, 'Total Rs. 70'), 'Total Rs. 70')
            app.ask_ai_chat.return_value = 'Ji, total Rs. 70 hai.'
            app.ask_ai_chat.side_effect = ['{"reply":"Ji, total Rs. 70 hai."}', '{"supported":true}']
            self.assertEqual(gateway.compose(app, self.phone, 'Total Rs. 70'), 'Ji, total Rs. 70 hai.')
        finally:
            gateway.current.reset(token)

    def test_composer_rejects_failed_write_becoming_confirmed(self):
        token = gateway.current.set({'phone': self.phone, 'text': 'confirm',
            'language': 'english', 'meaning': 'confirm order'})
        try:
            source = 'Order save failed. No order was created.'
            app.ask_ai_chat.side_effect = ['{"reply":"Your order was saved and confirmed."}', '{"supported":false}']
            self.assertEqual(gateway.compose(app, self.phone, source), source)
        finally: gateway.current.reset(token)

    def test_provider_language_instructions_do_not_force_old_cache(self):
        app.guest_language_cache[self.phone] = 'english'
        messages = app._openai_messages(app._ai_understanding_prompt('Cow milk milega?', None, self.phone), sender_phone=self.phone, structured=True)
        high_priority = '\n'.join(m['content'] for m in messages if m['role'] in {'system', 'developer'})
        self.assertNotIn('Reply naturally and politely in English.', high_priority)
        self.assertIn('Infer the guest language', high_priority)

    def test_service_feedback_retains_explicit_ticket_id(self):
        app.service_tasks_by_id.clear()
        for ticket in ('S-ABCDEF', 'S-123ABC'):
            app.service_tasks_by_id[ticket] = {'request_id':ticket, 'guest_phone':self.phone, 'status':'STAFF_COMPLETED'}
        with patch.object(app, '_update_service_task_sheet', return_value=True):
            gateway.handle(app, self.phone, 'S-ABCDEF ho gaya', None, semantic=self.understanding(
                action='SERVICE_FEEDBACK', operation_text='yes', task_id='S-ABCDEF'))
        self.assertEqual(app.service_tasks_by_id['S-ABCDEF']['status'], 'COMPLETED')
        self.assertEqual(app.service_tasks_by_id['S-123ABC']['status'], 'STAFF_COMPLETED')

    def test_interpreter_receives_pending_checkin_without_secret_otp(self):
        app.checkin_sessions[self.phone] = {'step': 'OTP', 'otp': '1234', 'created': time.time()}
        state = gateway.snapshot(app, self.phone)
        self.assertEqual(state['checkin_sessions']['step'], 'OTP')
        self.assertNotIn('otp', state['checkin_sessions'])


if __name__ == '__main__': unittest.main()
