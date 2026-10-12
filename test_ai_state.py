import os
os.environ['BOT_AUTOSTART']='0'
import unittest
from unittest.mock import patch
import app
import ai_receptionist as ai

class AuthoritativeStateTests(unittest.TestCase):
    def test_joined_state_is_sender_owned_and_redacted(self):
        phone='919555550001'
        with patch.object(app,'service_guest_pending',{phone:'S-ABCDEF'}),patch.object(app,'service_tasks_by_id',{'S-ABCDEF':{'request_id':'S-ABCDEF','guest_phone':phone,'details':'Two towels','status':'STAFF_COMPLETED','staff_phone':'secret'},'S-123ABC':{'guest_phone':'919555550002','details':'FOREIGN'}}),patch.object(app,'reception_request_sessions',{phone:{'request_id':'R-ABCDEF','request':'Cow milk','status':'answered','staff_reply':'Cow milk unavailable','reception_phone':'secret'}}),patch.object(app,'checkin_sessions',{phone:{'step':'ID','otp':'1234','id_link':'secret','nested':{'otp':'secret'}}}):
            state=ai.snapshot(app,phone)
        self.assertEqual(state['service_tasks'][0]['details'],'Two towels')
        self.assertEqual(state['reception_request_sessions']['staff_reply'],'Cow milk unavailable')
        self.assertNotIn('secret',str(state))
        self.assertNotIn('FOREIGN',str(state))

    def test_old_pending_and_explicit_tasks_survive_completed_history(self):
        phone='919555550001'
        tasks={'S-ABCDEF':{'request_id':'S-ABCDEF','guest_phone':phone,'status':'STAFF_COMPLETED'}}
        tasks.update({f'S-{i:06X}':{'request_id':f'S-{i:06X}','guest_phone':phone,'status':'COMPLETED'} for i in range(10)})
        with patch.object(app,'service_tasks_by_id',tasks):
            state=ai.snapshot(app,phone)
        self.assertEqual(state['service_tasks'][0]['request_id'],'S-ABCDEF')

    def test_large_prose_never_erases_confirmed_order(self):
        import json
        phone='919555550001'
        with patch.object(app,'active_orders',{phone:{'order':'1 Poha','total':70}}),patch.object(app,'checkin_sessions',{phone:{'step':'ID','address':'x'*1000}}),patch.object(app,'reception_request_sessions',{phone:{'request':'x'*1000,'last_reply':'x'*1000}}),patch.object(app,'reception_consent_sessions',{phone:{'request':'x'*1000}}):
            state=ai.snapshot(app,phone)
        self.assertEqual(state['active_orders']['order'],'1 Poha')
        self.assertEqual(state['active_orders']['total'],70)
        self.assertLessEqual(len(json.dumps(state).encode()),3500)
