import os
os.environ['BOT_AUTOSTART']='0'
import json
import unittest
from unittest.mock import patch,Mock
import app
import ai_receptionist as ai

class ComplaintIdentityTests(unittest.TestCase):
    def rows(self):
        headers=['Complaint ID','Phone','Status','Complaint']
        return {'complaint_headers':headers,'complaint_rows':[['C-ONE','919555550001','WAITING FEEDBACK','noise'],['C-TWO','919555550001','WAITING FEEDBACK','cleaning'],['C-OTHER','919555550002','WAITING FEEDBACK','private']]}
    def test_explicit_identity_updates_only_selected_sender_record(self):
        with patch.object(app,'shared_store',self.rows()),patch.object(app,'_update_complaint',return_value=True) as update,patch.object(app,'send_whatsapp_message'),patch.object(app,'fetch_sheet_data_sync'):
            app._handle_complaint_feedback('919555550001','yes',complaint_id='C-ONE')
        self.assertEqual(update.call_args.args[0],2)
    def test_ambiguous_feedback_writes_nothing(self):
        with patch.object(app,'shared_store',self.rows()),patch.object(app,'_update_complaint') as update,patch.object(app,'send_whatsapp_message') as send:
            app._handle_complaint_feedback('919555550001','yes')
        update.assert_not_called()
        self.assertTrue(send.called)
    def test_nonfeedback_question_is_not_intercepted(self):
        with patch.object(app,'shared_store',self.rows()),patch.object(app,'send_whatsapp_message') as send:
            self.assertFalse(app._handle_complaint_feedback('919555550001','Wi-Fi free hai?'))
        send.assert_not_called()
    def test_foreign_identity_writes_nothing(self):
        with patch.object(app,'shared_store',self.rows()),patch.object(app,'_update_complaint') as update:
            self.assertFalse(app._handle_complaint_feedback('919555550001','yes',complaint_id='C-OTHER'))
        update.assert_not_called()
    def test_failed_reopen_does_not_claim_staff_notified(self):
        data=self.rows();data['complaint_rows']=data['complaint_rows'][:1]
        with patch.object(app,'shared_store',data),patch.object(app,'_update_complaint',return_value=False),patch.object(app,'send_staff_alert',return_value=False),patch.object(app,'send_whatsapp_message') as send,patch.object(app,'get_guest_stay_status',return_value=None),patch.object(app,'fetch_sheet_data_sync'):
            app._handle_complaint_feedback('919555550001','no')
        self.assertNotIn('bhej di',send.call_args.args[1])

class CheckinReviewTests(unittest.TestCase):
    def test_unreviewed_start_authorization_changes_no_state(self):
        result={'action':'CHECKIN','language':'hinglish','confidence':.95,'submission_intent':False}
        with patch.object(app,'start_checkin') as start,patch.object(app,'send_whatsapp_message') as send:
            ai.handle(app,'919555550001','Checkin kaise karna hai?',None,semantic=result)
        start.assert_not_called()
        self.assertIn('not started',send.call_args.args[1])

    def test_reviewed_explicit_start_reaches_executor(self):
        result={'action':'CHECKIN','language':'hinglish','confidence':.95,'submission_intent':True}
        with patch.object(app,'CUSTOMER_DEMO_MODE',False),patch.object(app,'start_checkin') as start:
            ai.handle(app,'919555550001','Mera check-in abhi shuru kar do',None,semantic=result)
        start.assert_called_once()

    def test_side_question_candidate_is_independently_reviewed(self):
        candidate={'action':'CHECKIN_DETAILS','operation_text':'Room ka rate kya hai?','language':'hinglish'}
        review={'operational':True,'action':'ANSWER','items':[],'category':'NONE','operation_text':'','language':'hinglish','confidence':.95,'reply':'Kaunsa room chahiye?'}
        provider=Mock(return_value=json.dumps(review))
        result=ai.review_plan(app,'Room ka rate kya hai?',candidate,[],provider=provider,pending={'checkin_sessions':{'step':'NAME'}})
        self.assertEqual(result['action'],'ANSWER')
        provider.assert_called_once()
    def test_details_require_current_turn_submission(self):
        candidate={'action':'CHECKIN_DETAILS','operation_text':'Old name','language':'english'}
        review={'operational':True,'action':'CHECKIN_DETAILS','items':[],'category':'NONE','operation_text':'Old name','language':'english','confidence':.95,'reply':'','submission_intent':False}
        self.assertIsNone(ai.review_plan(app,'What is the price?',candidate,[],provider=Mock(return_value=json.dumps(review)),pending={'checkin_sessions':{'step':'NAME'}}))

class AvailabilityAuthorityTests(unittest.TestCase):
    def test_review_cannot_treat_room_categories_as_live_availability(self):
        candidate={'action':'AVAILABILITY','understood_as':'Room for two tomorrow','language':'hinglish','reply':'Kal kamra mil sakta hai.'}
        review={'menu_related':False,'action':'AVAILABILITY','language':'hinglish','reply':'Ji haan, kal kamra mil sakta hai.'}
        result=ai.review_plan(app,'Kal 2 logo ke liye kamra milega?',candidate,[],provider=Mock(return_value=json.dumps(review)),pending={})
        self.assertEqual(result['action'],'AVAILABILITY')
        self.assertFalse(result['needs_reception'])
        self.assertEqual(result['reply'],'')

class RoomSelectionTests(unittest.TestCase):
    def test_rejected_room_fact_never_becomes_category_card(self):
        result={'action':'ROOM_OPTIONS','generic':'Premium Window','language':'hinglish','confidence':.95,'reply':'Twin beds milenge.'}
        with patch.object(ai,'supported_result',return_value=False),patch.object(app,'_send_verified_room_categories') as cards,patch.object(app,'send_whatsapp_message') as send:
            ai.handle(app,'919555550001','2 alag bed milenge ya double bed?',None,semantic=result)
        cards.assert_not_called()
        self.assertIn('not verified',send.call_args.args[1])

    def test_specific_category_does_not_send_whole_category_list(self):
        with patch.object(app,'get_room_categories',return_value={'deluxe':{'name':'Deluxe','rate':1999},'family':{'name':'Family Suite','rate':3499}}),patch.object(app,'send_whatsapp_message') as send:
            app._send_verified_room_categories('919555550001','',show_prices=True,category='Deluxe')
        self.assertIn('Deluxe',send.call_args.args[1])
        self.assertNotIn('Family Suite',send.call_args.args[1])
    def test_unknown_category_is_not_broadened(self):
        with patch.object(app,'get_room_categories',return_value={'deluxe':{'name':'Deluxe','rate':1999}}),patch.object(app,'send_whatsapp_message') as send:
            app._send_verified_room_categories('919555550001','',category='Foreign Room')
        self.assertNotIn('• Deluxe',send.call_args.args[1])

    def test_reviewed_handoff_does_not_trust_candidate_followup(self):
        candidate={'action':'RECEPTION','language':'hinglish','reception_followup':True}
        review={'operational':True,'action':'RECEPTION','items':[],'category':'RECEPTION','operation_text':'A new towel request','reception_followup':False,'language':'hinglish','confidence':.95,'reply':''}
        result=ai.review_plan(app,'Towel bhi bhejo',candidate,[],provider=Mock(return_value=json.dumps(review)),pending={'reception_request_sessions':{'request':'Milk','status':'pending'}})
        self.assertFalse(result['reception_followup'])
        self.assertEqual(result['reception_request'],'A new towel request')

class PreconditionsAreNotUnderstandingFailures(unittest.TestCase):
    def test_information_only_operational_reply_can_omit_empty_items(self):
        review={'operational':True,'action':'ANSWER','category':'NONE','operation_text':'','language':'hinglish','confidence':.95,'reply':'Theek hai ji, koi order nahi lagaya.'}
        result=ai.review_plan(app,'Price hi poochha, order mat laga dena',{'action':'ANSWER','language':'hinglish'},[],provider=Mock(return_value=json.dumps(review)),pending={})
        self.assertIsNotNone(result)
        self.assertEqual(result['action'],'ANSWER')
        self.assertEqual(result['items'],[])

    def test_understood_confirmation_without_cart_cannot_enter_executor(self):
        result={'action':'ORDER_CONFIRM','language':'hinglish','confidence':.95,'reply':'','operation_text':''}
        with patch.object(app,'order_sessions',{}),patch.object(app,'duplicate_order_sessions',{}),patch.object(app,'demo_food_sessions',{}),patch.object(app,'send_whatsapp_message') as send,patch.object(app,'_process_and_reply') as execute:
            ai.handle(app,'919555550001','Confirm to kar',None,semantic=result)
        execute.assert_not_called()
        self.assertIn('pending cart',send.call_args.args[1])
    def test_ambiguous_feedback_reaches_identity_guard_without_mutation(self):
        candidate={'action':'SERVICE_FEEDBACK','language':'hinglish'}
        review={'operational':True,'action':'SERVICE_FEEDBACK','items':[],'category':'NONE','operation_text':'yes','task_id':'','language':'hinglish','confidence':.95,'reply':''}
        state={'service_tasks':[{'request_id':'S-ABCDEF','status':'STAFF_COMPLETED'},{'request_id':'S-123ABC','status':'STAFF_COMPLETED'}]}
        result=ai.review_plan(app,'Haan mil gaya',candidate,[],provider=Mock(return_value=json.dumps(review)),pending=state)
        self.assertIsNotNone(result)
        self.assertEqual(result['task_id'],'')
