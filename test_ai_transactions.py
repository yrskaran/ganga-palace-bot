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
