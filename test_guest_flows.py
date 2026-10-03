"""Offline regressions: no guest/staff messages or live Sheet writes."""
import hashlib
import hmac
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

os.environ['BOT_AUTOSTART'] = '0'
import app
from reliability import Store

ORIGINAL_APPEND=app._append_service_task_sheet
ORIGINAL_UPDATE=app._update_service_task_sheet
ORIGINAL_ENSURE=app._ensure_service_requests_sheet

GUEST = '919555555555'
STAFF = '919222222222'
NOW = datetime(2026, 10, 3, 8, 0, 45, tzinfo=app.IST)

class GuestFlows(unittest.TestCase):
    def setUp(self):
        self.patches = []
        self.sent = self.mock('send_whatsapp_message', return_value=True)
        self.notify = self.mock('send_notification_with_id', return_value=(True, 'remote-1'))
        self.sheet = self.mock('_update_service_task_sheet', return_value=True)
        self.mock('_append_service_task_sheet', return_value=True)
        self.mock('now_ist', return_value=NOW)
        self.mock('refresh_staff_roster', return_value=False)
        self.mock('fetch_sheet_data_sync', return_value=False)
        self.mock('get_guest_stay_status', return_value={'name':'Kitty', 'room':'203', 'is_inhouse':True, 'status':'IN'})
        self.mock('get_guest_response_language', return_value='hinglish')
        self.mock('notify_reception_request', return_value=True)
        self.mock('_resolve_staff_recipient', return_value={'name':'Ravi','phone':STAFF,'role':'Housekeeping'})
        self.mock('_reroute_service_task', return_value=True)
        for name in ('service_tasks_by_id','service_tasks_by_alert','service_guest_pending',
                     'guide_service_sessions','conversation_memory','order_sessions',
                     'duplicate_order_sessions','checkin_sessions','reception_request_sessions',
                     'service_sessions','lifecycle_pending_by_message_id','lifecycle_pending_keys',
                     'lifecycle_retry_after'):
            self.mock(name, {})
        self.mock('durable_store', None)
        self.mock('AI_READINESS', {"status":"not_checked", "checked_at":None})
        self.mock('guest_language_cache', {})
        self.mock('shared_store', {'last_synced':__import__('time').time(), 'rooms':[], 'lifecycle_headers':[], 'lifecycle_rows':[]})

    def mock(self, name, *args, **kwargs):
        p = patch.object(app, name, *args, **kwargs)
        self.patches.append(p)
        return p.start()

    def tearDown(self):
        for p in reversed(self.patches): p.stop()

    def turn(self, text, context=None):
        message = {'type':'text','text':{'body':text}}
        if context: message['context']={'id':context}
        app._process_and_reply(message, GUEST, 'text')

    def task(self, rid='S-ABC123'):
        task = app.create_service_task(GUEST, {'name':'Kitty','room':'203'}, 'Housekeeping', 'Extra towel', 'Please bring a towel')
        old = task['request_id']
        app.service_tasks_by_id.pop(old)
        task['request_id'] = rid
        app.service_tasks_by_id[rid] = task
        return task

    def test_guide_enquiry_precedes_ai_and_places(self):
        ai = self.mock('understand_guest_request', side_effect=AssertionError('guide must be handled before AI'))
        places = self.mock('build_guide_fallback', side_effect=AssertionError('must not dump places'))
        self.turn('Local guide bhi hai?')
        text = self.sent.call_args.args[1]
        self.assertIn('availability', text)
        self.assertIn('charges', text)
        self.assertIn('check karwa doon', text)
        app.notify_reception_request.assert_not_called()
        ai.assert_not_called(); places.assert_not_called()

    def test_guide_yes_sends_actual_reception_request(self):
        self.turn('Local guide bhi hai?')
        self.turn('haan')
        self.assertEqual(app.notify_reception_request.call_count, 1)
        self.assertIn('availability and charges', app.notify_reception_request.call_args.args[2])
        self.assertIn('abhi confirm ya book nahi', self.sent.call_args.args[1])
        self.assertNotIn(GUEST, app.guide_service_sessions)

    def test_typo_multi_item_order_overrides_generic_ai(self):
        self.mock('understand_guest_request', return_value={"action":"ORDER_SELECTION", "confidence":0.9, "generic":"paneer", "reply":"Which paneer?"})
        self.mock('_recent_matching_kitchen_order', return_value=None)
        self.turn('Kadhayi paneer Butter naan 2 pcs with sptemed rice')
        pending = app.order_sessions[GUEST]
        self.assertEqual(pending['total'], 480)
        self.assertEqual(pending['order'], '1 x Kadhai Paneer, 2 x Butter Naan, 1 x Steamed Rice')
        reply = self.sent.call_args.args[1]
        self.assertIn('Rs. 480', reply)
        self.assertIn('CONFIRM', reply)
        self.assertNotIn('kaunsa', reply)

    def test_food_quantities_aliases_and_ambiguity(self):
        cases = [
            ('Kadhayi paneer Butter naan 2 pcs with sptemed rice', [1, 2, 1]),
            ('kadai paneer with 2 butter nan and steam rice', [1, 2, 1]),
            ('2 butter naan 3 steamed rice', [2, 3]),
            ('butter naan 2 pcs + butter nan 3 pcs', [5]),
            ('do butter naan aur ek steamed rice', [2, 1]),
        ]
        for text, quantities in cases:
            with self.subTest(text=text):
                parsed = app.find_menu_items(text)
                self.assertTrue(parsed['complete'])
                self.assertEqual([x['qty'] for x in parsed['items']], quantities)
        self.assertEqual(app.find_menu_items('paneer bhejo')['generic'], 'paneer')
        self.assertEqual(app.find_menu_items('kadhai paneer aur rice')['generic'], 'rice')
        self.assertTrue(app.find_menu_items('butter naan 51 pcs')['invalid'])
        self.assertFalse(app.find_menu_items('kadhai paneer nahi chahiye')['complete'])
        self.assertFalse(app.find_menu_items('kadhai paneer with pizza')['complete'])

    def test_guide_preserves_older_pending_food(self):
        pending={'order':'2 x Masala Chai','total':60,'created':__import__('time').time()}
        app.order_sessions[GUEST]=pending
        self.turn('Tour guide chahiye')
        self.assertEqual(app.order_sessions[GUEST], pending)
        self.assertEqual(app.notify_reception_request.call_count, 1)

    def test_guide_failure_is_honest(self):
        app.notify_reception_request.return_value=False
        self.turn('Local guide arrange karwa do')
        self.assertIn('nahi bhej paaya', self.sent.call_args.args[1])

    def test_guide_decline_does_not_route(self):
        for text in ('guide nahi chahiye','guide mat book karna',"don't arrange a local guide"):
            self.assertTrue(app.handle_human_guide_request(GUEST,text,{}))
        app.notify_reception_request.assert_not_called()

    def test_guide_vs_information_and_ambiguity(self):
        for text in ('Haridwar me kya dekh sakte hain?', 'nearby places?', 'guide me to the temple', 'travel guide to Haridwar', 'Haridwar guide'):
            self.assertEqual(app._human_guide_intent(text), '', text)
        for text in ('Local guide bhi hai?', 'tour guide available?', 'guide milega?', 'लोकल गाइड है?', 'guide charges?'):
            self.assertEqual(app._human_guide_intent(text), 'enquiry', text)
        self.assertEqual(app._human_guide_intent('guide'), 'clarify')

    def test_changed_topic_expires_guide_offer(self):
        self.turn('Local guide hai?')
        self.assertFalse(app.handle_human_guide_request(GUEST,'wifi password?',{}))
        self.assertFalse(app.handle_human_guide_request(GUEST,'haan',{}))
        app.notify_reception_request.assert_not_called()

    def test_onboarding_examples_in_all_supported_fallbacks(self):
        for lang, guide, wifi in [('english','tour guide','Wi-Fi'),('hinglish','tour guide','Wi-Fi'),('hindi','टूर गाइड','वाई-फाई')]:
            text=app.get_ai_lifecycle_message('30_MINUTE',lang,'Kitty','203')
            self.assertIn(guide,text); self.assertIn(wifi,text)
            self.assertEqual(text.count('😊'),1)
        self.assertIn('Room 203', app.get_ai_lifecycle_message('WELCOME','english','Kitty','203'))
        self.assertNotIn('Ji Kitty ji',app.get_ai_lifecycle_message('WELCOME','hinglish','Kitty','203'))

    def test_screenshot_help_questions_answer_before_ai(self):
        ai=self.mock('understand_guest_request', side_effect=AssertionError('capability must not depend on AI'))
        app.get_guest_response_language.side_effect=lambda phone,text=None: (
            app.remember_guest_language(phone,text) if text is not None else app.guest_language_cache.get(phone,'english'))
        self.turn('Hi')
        self.turn('How you assist me')
        english=self.sent.call_args.args[1]
        self.assertIn("I'm the hotel's WhatsApp assistant",english)
        self.assertIn('food orders',english)
        self.turn('Kaise assist kroge')
        hinglish=self.sent.call_args.args[1]
        self.assertIn('Main hotel ka WhatsApp assistant',hinglish)
        self.assertIn('towel',hinglish)
        self.assertNotIn('trouble understanding',hinglish)
        ai.assert_not_called()
        app.notify_reception_request.assert_not_called()

    def test_help_variants_preserve_pending_orders(self):
        pending={'order':'2 x Masala Chai','total':60,'created':__import__('time').time()}
        app.order_sessions[GUEST]=pending
        ai=self.mock('understand_guest_request',side_effect=AssertionError('no AI quota for basic help'))
        for text in ('How can you assist me?', 'What can you do for me?', 'Help',
                     'Aap meri help kaise kar sakte ho?', 'Kaise madad karoge?',
                     'आप मेरी मदद कैसे कर सकते हैं?', 'क्या कर सकते हो?'):
            with self.subTest(text=text):
                self.turn(text)
                self.assertEqual(app.order_sessions[GUEST],pending)
                self.assertIn('WhatsApp',self.sent.call_args.args[1])
        ai.assert_not_called()
        app.notify_reception_request.assert_not_called()

    def test_specific_requests_are_not_capability_questions(self):
        for text in ('Can you help me with wifi?', 'How can you help with my bill?',
                     'meri help karo towel bhej do', 'Kaise Har Ki Pauri jaun?',
                     'help nahi chahiye', 'mujhe doctor ki help chahiye', 'what can you do for my AC?'):
            self.assertFalse(app._is_capability_question(text),text)

    def test_hindi_capability_reply_uses_guest_script(self):
        app.get_guest_response_language.return_value='hindi'
        self.turn('आप मेरी मदद कैसे कर सकते हैं?')
        self.assertIn('मैं होटल का',self.sent.call_args.args[1])

    def test_knowledge_budget_keeps_relevant_whole_facts(self):
        raw=('1. HOTEL IDENTITY\n- Name: Test Hotel\n- Wi-Fi: Free\n- Check-out: 11 AM\n\n'
             + '\n\n'.join(f'Place: Other {i}\nAbout: '+('old guide text '*100) for i in range(60))
             + '\n\nPlace: Mansa Devi\nAbout: On Bilwa Parvat\nLive note: Confirm current ropeway operation.')
        self.mock('get_hotel_data',return_value=raw)
        packet=app._ai_knowledge_snapshot(1500,'Mansa Devi ropeway')
        self.assertLessEqual(len(packet.encode('utf-8')),1500)
        self.assertIn('On Bilwa Parvat',packet)
        self.assertIn('Confirm current ropeway operation.',packet)
        self.assertIn('Wi-Fi: Free',packet)
        # A long non-ASCII line cannot be cut into an incomplete fact or price.
        app.get_hotel_data.return_value='1. FOOD MENU\n- '+('चाय '*1000)+': Rs. 200\n- Coffee: Rs. 40'
        packet=app._ai_knowledge_snapshot(500,'coffee')
        self.assertLessEqual(len(packet.encode('utf-8')),500)
        self.assertIn('- Coffee: Rs. 40',packet)
        self.assertNotIn('चाय',packet)

    def test_groq_input_bounded_with_long_history(self):
        self.mock('GROQ_UNAVAILABLE_UNTIL',0)
        self.mock('get_active_groq_model',return_value='qwen/qwen3.8-27b')
        app.conversation_memory[GUEST]=[{'role':'assistant','content':'old menu '*5000},
                                         {'role':'user','content':'Mansa Devi ropeway?'}]
        response=Mock(status_code=200)
        response.json.return_value={'choices':[{'message':{'content':'{"action":"ANSWER","reply":"Confirm current ropeway operation."}'},'finish_reason':'stop'}],
                                    'usage':{'prompt_tokens':2200,'completion_tokens':40}}
        with patch.object(app.requests,'post',return_value=response) as post:
            prompt=app._ai_understanding_prompt('What about Mansa Devi?',{'name':'Kitty','room':'203'},GUEST)
            self.assertTrue(app.ask_groq_chat(prompt,sender_phone=GUEST,structured=True))
            messages=post.call_args.kwargs['json']['messages']
        self.assertLess(sum(len(m['content'].encode('utf-8')) for m in messages),12500)
        self.assertIn('Bilwa Parvat',messages[0]['content'])
        self.assertEqual(messages[-2]['content'],'Mansa Devi ropeway?')
        self.assertIn('What about Mansa Devi?',messages[-1]['content'])

    def test_readiness_probe_has_no_guest_or_sheet_actions(self):
        self.mock('GROQ_API_KEY','test-placeholder')
        self.mock('ask_groq_chat',return_value=json.dumps({'action':'ANSWER','reply':'Wi-Fi and parking are complimentary; check-out is 11 AM.'}))
        app.check_ai_readiness()
        self.assertEqual(app.AI_READINESS['status'],'available')
        self.sent.assert_not_called()
        app.notify_reception_request.assert_not_called()
        self.sheet.assert_not_called()
        app.ask_groq_chat.return_value=None
        app.check_ai_readiness()
        self.assertEqual(app.AI_READINESS['status'],'unavailable')
        self.assertEqual(app.app.test_client().get('/health').json['ai']['status'],'unavailable')

    def test_groq_413_opens_circuit_and_truncated_json_is_rejected(self):
        self.mock('GROQ_UNAVAILABLE_UNTIL',0)
        self.mock('get_active_groq_model',return_value='qwen/qwen3.8-27b')
        breaker=self.mock('_groq_set_circuit_breaker')
        response=Mock(status_code=413,text='Request too large on input tokens per minute')
        with patch.object(app.requests,'post',return_value=response):
            self.assertIsNone(app.ask_groq_chat('test',structured=True))
            self.assertEqual(breaker.call_args.args[0],120)
            response.status_code=200
            response.json.return_value={'choices':[{'message':{'content':'{"action":"ANSWER"'},'finish_reason':'length'}]}
            self.assertIsNone(app.ask_groq_chat('test',structured=True))

    def test_onboarding_survives_ai_wording_enabled(self):
        self.mock('AI_LIFECYCLE_WORDING',True)
        ai=self.mock('ask_ai_chat',side_effect=AssertionError('onboarding examples must be deterministic'))
        self.assertIn('local tour guide',app.get_ai_lifecycle_message('30_MINUTE','hinglish','Kitty','203'))
        ai.assert_not_called()

    def test_arrival_no_double_dispatch_on_late_sync(self):
        checkin=NOW-timedelta(minutes=60)
        self.assertEqual(app._arrival_notification_plan(checkin,'',NOW),('send',None))
        self.assertEqual(app._arrival_notification_plan(checkin,NOW.isoformat(),NOW),(None,None))
        self.assertEqual(app._arrival_notification_plan(checkin,NOW.isoformat(),NOW+timedelta(minutes=29,seconds=59)),(None,None))
        self.assertEqual(app._arrival_notification_plan(checkin,NOW.isoformat(),NOW+timedelta(minutes=30)),(None,'send'))

    def test_arrival_invalid_future_and_old(self):
        self.assertEqual(app._arrival_notification_plan(None,'',NOW),(None,None))
        self.assertEqual(app._arrival_notification_plan(NOW+timedelta(seconds=1),'',NOW),(None,None))
        self.assertEqual(app._arrival_notification_plan(NOW-timedelta(days=1),'',NOW),('skip',None))
        self.assertEqual(app._arrival_notification_plan(NOW-timedelta(days=1),'YES',NOW),(None,'skip'))

    def test_arrival_30_minutes_from_checkin(self):
        checkin=NOW-timedelta(minutes=30)
        self.assertEqual(app._arrival_notification_plan(checkin,checkin.isoformat(),NOW),(None,'send'))
        self.assertEqual(app._arrival_notification_plan(NOW-timedelta(minutes=29),'YES',NOW),(None,None))

    def test_no_irrelevant_timing_disclaimer(self):
        text=app.build_guide_fallback('nearby places?',GUEST)
        self.assertNotIn('ticket', text.lower()); self.assertNotIn('timing', text.lower())
        text=app.build_guide_fallback('Mansa Devi ropeway ticket timing?',GUEST)
        self.assertIn('timing', text.lower())

    def test_staff_done_guest_yes_updates_sheet(self):
        task=self.task()
        self.assertTrue(app.handle_service_staff_message({'text':{'body':'S-ABC123 done'}},STAFF,'text'))
        self.assertEqual(task['status'],'STAFF_COMPLETED')
        self.assertTrue(app.handle_service_guest_confirmation(GUEST,'haan ho gaya'))
        self.assertEqual(task['status'],'COMPLETED')
        self.assertTrue(task['guest_confirmed_at']); self.assertTrue(task['closed_at'])
        self.assertGreaterEqual(self.sheet.call_count,2)

    def test_unauthorized_staff_cannot_complete(self):
        task=self.task()
        self.assertFalse(app.handle_service_staff_message({'text':{'body':'S-ABC123 done'}},GUEST,'text'))
        self.assertEqual(task['status'],'OPEN')

    def test_guest_no_reopens_and_reroutes(self):
        task=self.task(); app._mark_service_staff_done(task)
        self.assertTrue(app.handle_service_guest_confirmation(GUEST,'abhi nahi hua'))
        self.assertEqual(task['status'],'REOPENED')
        app._reroute_service_task.assert_called_once_with(task)

    def test_exact_twenty_minute_timeout_and_no_extra_message(self):
        task=self.task(); app._mark_service_staff_done(task)
        done=app._parse_sheet_datetime(task['staff_done_at'])
        self.sent.reset_mock()
        with patch.object(app,'now_ist',return_value=done+timedelta(minutes=19,seconds=59)):
            app.process_service_auto_resolve()
        self.assertEqual(task['status'],'STAFF_COMPLETED')
        with patch.object(app,'now_ist',return_value=done+timedelta(minutes=20)):
            app.process_service_auto_resolve()
        self.assertEqual(task['status'],'AUTO_RESOLVED')
        self.assertTrue(task['auto_resolved_at']); self.sent.assert_not_called()

    def test_failed_confirmation_never_auto_closes(self):
        task=self.task(); self.notify.return_value=(False,None)
        app._mark_service_staff_done(task)
        self.assertEqual(task['status'],'CONFIRMATION_FAILED')
        with patch.object(app,'now_ist',return_value=NOW+timedelta(hours=2)):
            app.process_service_auto_resolve()
        self.assertEqual(task['status'],'CONFIRMATION_FAILED')

    def test_failed_delivery_stops_auto_close(self):
        task=self.task(); app._mark_service_staff_done(task)
        app._update_service_alert_delivery('remote-1','failed',[131047])
        self.assertEqual(task['status'],'CONFIRMATION_FAILED')
        self.assertEqual(task['confirmation_sent_at'],'')
        self.assertTrue(task['staff_done_at'])

    def test_repeat_staff_done_keeps_original_timer(self):
        task=self.task(); app._mark_service_staff_done(task)
        self.notify.reset_mock(); stamp=task['staff_done_at']
        app._mark_service_staff_done(task)
        self.notify.assert_not_called(); self.assertEqual(task['staff_done_at'],stamp)

    def test_multiple_requests_require_id_or_reply_context(self):
        one=self.task(); app._mark_service_staff_done(one)
        self.notify.return_value=(True,'remote-2')
        two=self.task('S-DEF456'); app._mark_service_staff_done(two)
        self.assertTrue(app.handle_service_guest_confirmation(GUEST,'haan'))
        self.assertEqual(one['status'],'STAFF_COMPLETED'); self.assertEqual(two['status'],'STAFF_COMPLETED')
        self.assertTrue(app.handle_service_guest_confirmation(GUEST,'haan',{'context':{'id':'remote-1'}}))
        self.assertEqual(one['status'],'COMPLETED'); self.assertEqual(two['status'],'STAFF_COMPLETED')
        self.assertTrue(app.handle_service_guest_confirmation(GUEST,'S-DEF456 nahi'))
        self.assertEqual(two['status'],'REOPENED')

    def test_restart_rebuild_restores_awaiting_confirmation(self):
        task=self.task(); app._mark_service_staff_done(task)
        app.shared_store['service_request_headers']=app.SERVICE_REQUEST_HEADERS
        app.shared_store['service_request_rows']=[app._service_task_row(task)]
        app.service_tasks_by_id.clear(); app.service_tasks_by_alert.clear(); app.service_guest_pending.clear()
        app._rebuild_service_task_cache()
        self.assertEqual(app.service_guest_pending[GUEST],'S-ABC123')
        self.assertTrue(app.handle_service_guest_confirmation(GUEST,'haan'))
        self.assertEqual(app.service_tasks_by_id['S-ABC123']['status'],'COMPLETED')

    def test_negatives_cannot_be_positive_substrings(self):
        for text in ('not resolved','not done',"it isn't fixed",'nahi ho gaya','अभी नहीं हुआ'):
            self.assertEqual(app._service_guest_result(text),'no',text)
        self.assertEqual(app._service_guest_result('हाँ हो गया'),'yes')

    def lifecycle_fixture(self):
        headers=['Room','Guest Name','Phone','Status','WELCOME SENT','30 MIN SENT','BREAKFAST SENT','STAY KEY']
        row=['203','Kitty',GUEST,'IN','','','','stay-kitty']
        app.shared_store['lifecycle_headers']=headers
        app.shared_store['lifecycle_rows']=[row]
        return headers,row

    def test_lifecycle_pending_deduplicates_after_row_movement(self):
        headers,row=self.lifecycle_fixture()
        self.assertTrue(app.send_lifecycle_notification(GUEST,'welcome','WELCOME',2,4,NOW.isoformat(),'WELCOME'))
        app.shared_store['lifecycle_rows'].insert(0,['204','Other','919666666666','IN','','','','stay-other'])
        self.assertFalse(app.send_lifecycle_notification(GUEST,'welcome','WELCOME',3,4,NOW.isoformat(),'WELCOME'))
        self.assertEqual(self.notify.call_count,1)

    def test_delivery_marker_follows_stay_not_row(self):
        headers,row=self.lifecycle_fixture()
        app.send_lifecycle_notification(GUEST,'welcome','WELCOME',2,4,NOW.isoformat(),'WELCOME')
        meta=app.lifecycle_pending_by_message_id['remote-1']
        other=['204','Other','919666666666','IN','','','','stay-other']
        self.assertEqual(app._lifecycle_delivery_cell(meta,[headers,other,row]),(3,4))
        self.assertIsNone(app._lifecycle_delivery_cell(meta,[headers,other]))
        new_stay=list(row); new_stay[-1]='new-stay-kitty'
        self.assertIsNone(app._lifecycle_delivery_cell(meta,[headers,new_stay]))

    def test_lifecycle_failed_send_does_not_mark_sheet(self):
        self.lifecycle_fixture(); self.notify.return_value=(False,None)
        self.assertFalse(app.send_lifecycle_notification(GUEST,'welcome','WELCOME',2,4,NOW.isoformat(),'WELCOME'))
        self.assertFalse(app.lifecycle_pending_by_message_id)
        self.assertEqual(app.shared_store['lifecycle_rows'][0][4],'')

    def test_daily_markers_reset(self):
        self.assertTrue(app._lifecycle_sent_today(['2026-10-03'],0,'2026-10-03'))
        self.assertFalse(app._lifecycle_sent_today(['2026-10-02'],0,'2026-10-03'))
        self.assertFalse(app._lifecycle_sent_today([],0,'2026-10-03'))
        for label, start, end in [('Breakfast',8,10),('Lunch',13,15),('Ganga Aarti',17,18),('Dinner',19,21)]:
            self.assertEqual(app._lifecycle_time_window(label+' Reminder Window',0,0),(start*60,end*60))

    def test_webhook_signatures_and_health(self):
        self.mock('APP_SECRET','test-secret'); self.mock('VERIFY_TOKEN','test-verify')
        with app.app.test_client() as client:
            app.app.testing=True
            self.assertEqual(client.get('/health').status_code,200)
            self.assertEqual(client.get('/webhook?hub.mode=subscribe&hub.verify_token=test-verify&hub.challenge=123').data,b'123')
            payload=json.dumps({'entry':[]}).encode()
            self.assertEqual(client.post('/webhook',data=payload,content_type='application/json').status_code,403)
            sig='sha256='+hmac.new(b'test-secret',payload,hashlib.sha256).hexdigest()
            self.assertEqual(client.post('/webhook',data=payload,content_type='application/json',headers={'X-Hub-Signature-256':sig}).status_code,200)
        app.app.testing=False

    def test_durable_inbox_deduplication(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp+'/test.db')
            message={'id':'test-message','from':GUEST,'type':'text','text':{'body':'hello'}}
            self.assertTrue(store.enqueue(message)); self.assertFalse(store.enqueue(message))
            self.assertEqual(store.next_message(),message)
            store.finish('test-message',GUEST,{},True)
            self.assertIsNone(store.next_message())


class IntegrationFlows(unittest.TestCase):
    setUp = GuestFlows.setUp
    tearDown = GuestFlows.tearDown
    mock = GuestFlows.mock
    task = GuestFlows.task
    # These tests exercise the worker/Sheet call sites, not only intent helpers.
    def monitor_once(self, current, status='IN', welcome='', thirty=''):
        app.shared_store['room_headers']=['ROOM (A)','TYPE','PRICE (C)','GUEST NAME (D)','PHONE (E)','STATUS (F)','CHECK IN TIME','CHECK OUT TIME','CHECKOUT MSG SENT']
        app.shared_store['rooms']=[['203','Deluxe','1000','Kitty',GUEST,status,(current-timedelta(minutes=60)).isoformat(),'','']]
        app.shared_store['lifecycle_headers']=['Room','Guest Name','Phone','Status','WELCOME SENT','30 MIN SENT','BREAKFAST SENT','LUNCH SENT','AARTI SENT','DINNER SENT','CHECKOUT SENT','STAY KEY']
        app.shared_store['lifecycle_rows']=[['203','Kitty',GUEST,status,welcome,thirty,'','','','','','stay-kitty']]
        dispatch=Mock(return_value=True)
        with patch.object(app,'now_ist',return_value=current), \
             patch.object(app,'reconcile_lifecycle_from_room_sheet',return_value=False), \
             patch.object(app,'process_complaint_followups'), \
             patch.object(app,'process_full_bill_paid_notifications'), \
             patch.object(app,'maybe_send_owner_report'), \
             patch.object(app,'send_lifecycle_notification',dispatch), \
             patch.object(app.time,'sleep',side_effect=StopIteration):
            with self.assertRaises(StopIteration): app.monitor_guest_status_lifecycle()
        return [call.args[6] for call in dispatch.call_args_list]

    def test_worker_late_sync_only_welcomes(self):
        self.assertEqual(self.monitor_once(NOW.replace(hour=2)),['WELCOME'])

    def test_worker_30_minute_then_no_night_meals(self):
        current=NOW.replace(hour=2)
        welcome=(current-timedelta(minutes=30)).isoformat()
        self.assertEqual(self.monitor_once(current,welcome=welcome),['30_MINUTE'])

    def test_worker_morning_and_aarti_windows(self):
        self.assertEqual(self.monitor_once(NOW,welcome='YES',thirty='YES'),['GOOD_MORNING_BREAKFAST'])
        self.assertEqual(self.monitor_once(NOW.replace(hour=17),welcome='YES',thirty='YES'),['GANGA_AARTI'])

    def test_worker_checked_out_guest_no_reminders(self):
        self.assertEqual(self.monitor_once(NOW,status='OUT'),[])

    def test_actual_sheet_status_updates_use_existing_columns(self):
        task=self.task()
        sheet=Mock()
        sheet.append_row.return_value={'updates':{'updatedRange':'Service_Requests!A2:Q2'}}
        with patch.object(app,'_ensure_service_requests_sheet',return_value=sheet):
            self.assertTrue(ORIGINAL_APPEND(task))
            self.assertEqual(task['sheet_row'],2)
            task['status']='COMPLETED'
            self.assertTrue(ORIGINAL_UPDATE(task))
        self.assertEqual(sheet.update.call_args.args[0],'A2:S2')
        self.assertEqual(sheet.update.call_args.args[1][0][10],'COMPLETED')
        self.assertEqual(len(sheet.update.call_args.args[1][0]),len(app.SERVICE_REQUEST_HEADERS))


    def test_service_schema_migration_preserves_existing_rows(self):
        sheet=Mock(); sheet.col_count=17
        sheet.row_values.return_value=app.SERVICE_REQUEST_HEADERS[:17]
        client=Mock(); client.open_by_key.return_value.worksheet.return_value=sheet
        with patch.object(app,'get_gspread_client',return_value=client):
            self.assertIs(ORIGINAL_ENSURE(),sheet)
        sheet.add_cols.assert_called_once_with(2)
        sheet.update.assert_called_once_with('R1:S1',[app.SERVICE_REQUEST_HEADERS[17:]],value_input_option='RAW')
        sheet.clear.assert_not_called(); sheet.delete_rows.assert_not_called()

    def test_service_schema_conflict_never_overwrites(self):
        sheet=Mock(); sheet.col_count=19
        sheet.row_values.return_value=app.SERVICE_REQUEST_HEADERS[:17]+['Unrelated custom column','Another column']
        client=Mock(); client.open_by_key.return_value.worksheet.return_value=sheet
        with patch.object(app,'get_gspread_client',return_value=client):
            with self.assertRaises(RuntimeError): ORIGINAL_ENSURE()
        sheet.update.assert_not_called()

    def test_restart_preserves_confirmation_reply_context_and_failure(self):
        one=self.task(); app._mark_service_staff_done(one)
        self.notify.return_value=(True,'remote-2')
        two=self.task('S-DEF456'); app._mark_service_staff_done(two)
        app.shared_store['service_request_headers']=app.SERVICE_REQUEST_HEADERS
        app.shared_store['service_request_rows']=[app._service_task_row(one),app._service_task_row(two)]
        app.service_tasks_by_id.clear(); app.service_tasks_by_alert.clear(); app.service_guest_pending.clear()
        app._rebuild_service_task_cache()
        self.assertTrue(app.handle_service_guest_confirmation(GUEST,'haan',{'context':{'id':'remote-1'}}))
        self.assertEqual(app.service_tasks_by_id['S-ABC123']['status'],'COMPLETED')
        app._update_service_alert_delivery('remote-2','failed',[131047])
        self.assertEqual(app.service_tasks_by_id['S-DEF456']['status'],'CONFIRMATION_FAILED')

    def test_unique_question_from_screenshot_uses_fact_bank(self):
        self.assertTrue(app._is_haridwar_fact_request('Koi unique btao haridwar kr baare me',GUEST))
        reply=app.build_unique_haridwar_fact(GUEST,'Koi unique btao haridwar kr baare me')
        self.assertIn('Haridwar ka fact',reply)

    def test_delivery_callback_writes_correct_moved_row(self):
        headers,row=GuestFlows.lifecycle_fixture(self)
        app.send_lifecycle_notification(GUEST,'welcome','WELCOME',2,4,NOW.isoformat(),'WELCOME')
        other=['204','Other','919666666666','IN','','','','stay-other']
        client=Mock(); client.open_by_key.return_value.worksheet.return_value.get_all_values.return_value=[headers,other,row]
        marker=Mock(return_value=True)
        with patch.object(app,'get_gspread_client',return_value=client),patch.object(app,'_mark_named_sheet_cell',marker):
            app._update_lifecycle_delivery('remote-1','delivered',[])
        marker.assert_called_once_with('Lifecycle_Automation',3,4,NOW.isoformat())
        self.assertFalse(app.lifecycle_pending_keys)

    def test_stale_delivery_callback_never_writes_other_guest(self):
        headers,row=GuestFlows.lifecycle_fixture(self)
        app.send_lifecycle_notification(GUEST,'welcome','WELCOME',2,4,NOW.isoformat(),'WELCOME')
        other=['204','Other','919666666666','IN','','','','stay-other']
        client=Mock(); client.open_by_key.return_value.worksheet.return_value.get_all_values.return_value=[headers,other]
        marker=Mock(return_value=True)
        with patch.object(app,'get_gspread_client',return_value=client),patch.object(app,'_mark_named_sheet_cell',marker):
            app._update_lifecycle_delivery('remote-1','delivered',[])
        marker.assert_not_called()
        self.assertFalse(app.lifecycle_pending_keys)

if __name__=='__main__':
    unittest.main()
