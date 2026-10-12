import os
os.environ['BOT_AUTOSTART']='0'
import json
import unittest
from unittest.mock import Mock,patch
import app
import hotel_eval

class ProductionEntryEvaluationTests(unittest.TestCase):
    def test_media_wire_response_is_retained_as_guest_output(self):
        plan={'action':'SHOW_PHOTO','photo_target':'Family Suite','language':'hinglish','confidence':.95}
        def process(*args):
            app.understand_guest_request('Uski photo bhejna',None,hotel_eval.PHONE)
            app.whatsapp_request({'to':hotel_eval.PHONE,'type':'image','image':{'link':'https://example.test/family.jpg','caption':'Family Suite'}})
        with patch.object(app,'understand_guest_request',return_value=plan),patch.object(app,'process_and_reply',side_effect=process),patch.object(app,'get_room_photo_categories',return_value=[('Family Suite','https://example.test/family.jpg')]):
            row=hotel_eval.evaluate(app,{'id':'photo','question':'Uski photo bhejna','actions':['SHOW_PHOTO'],'photo':'Family Suite'})
        self.assertNotIn('No guest output',row['errors'])
        self.assertNotIn('Final reply does not match Hinglish script/wording',row['errors'])
        self.assertEqual(row['guest_payloads'][0]['image']['link'],'https://example.test/family.jpg')

    def test_actual_entry_review_compose_and_wire_memory(self):
        answers=[{'action':'MENU_ITEM_INFO','items':[{'name':'Standard Veg Thali','qty':1}],'language':'hinglish','operation_text':'','confidence':.96},
            {'menu_related':True,'language':'hinglish','request_kind':'price','action':'MENU_ITEM_INFO','menu_section':'','items':[{'name':'Standard Veg Thali','qty':1}],'excluded_items':[],'show_prices':True,'needs_reception':False,'reception_request':'','reply':''},
            {'reply':'Standard Veg Thali ki price ₹200 hai.'},{'supported':True}]
        prompts=[]
        def transport(url,**kwargs):
            prompts.append(json.dumps(kwargs['json']))
            return Mock(status_code=200,json=Mock(return_value={'candidates':[{'content':{'parts':[{'text':json.dumps(answers.pop(0))}]},'finishReason':'STOP'}]}))
        with patch.object(app,'GEMINI_API_KEY','test'):
            row=hotel_eval.evaluate(app,hotel_eval.CASES[0],transport=transport)
        self.assertFalse(row['errors'],row)
        self.assertEqual(len(prompts),4)
        self.assertEqual(row['memory'][-1]['content'],row['output'])
        self.assertFalse(row['fresh_model_acceptance'])
        self.assertNotIn('expected_action',''.join(prompts))
    def test_network_failure_never_counts_as_acceptance(self):
        transport=Mock(return_value=Mock(status_code=503,text='Unavailable',json=Mock(return_value={'error':{'message':'Unavailable'}})))
        with patch.object(app,'GEMINI_API_KEY','test'):
            row=hotel_eval.evaluate(app,hotel_eval.CASES[0],transport=transport)
        self.assertFalse(row['fresh_model_acceptance'])
        self.assertIn('No completed interpreter/review plan',row['errors'])
        self.assertEqual(transport.call_count,1)

    def test_reviewed_name_submission_advances_actual_checkin(self):
        answers=[{'action':'CHECKIN_DETAILS','operation_text':'Aman Sharma','language':'english','confidence':.96},
            {'operational':True,'action':'CHECKIN_DETAILS','items':[],'category':'NONE','operation_text':'Aman Sharma','submission_intent':True,'language':'english','confidence':.96,'reply':''},
            {'reply':'Full name recorded. Please send your full address with city and state.'},{'supported':True}]
        def transport(url,**kwargs):
            return Mock(status_code=200,json=Mock(return_value={'candidates':[{'content':{'parts':[{'text':json.dumps(answers.pop(0))}]},'finishReason':'STOP'}]}))
        case={'id':'name','question':'Aman Sharma','pending':{'checkin_sessions':{'step':'NAME'}}}
        with patch.object(app,'GEMINI_API_KEY','test'):
            row=hotel_eval.evaluate(app,case,transport=transport)
        self.assertFalse(row['errors'],row)
        self.assertEqual(row['state_after']['checkin_sessions']['step'],'ADDRESS')
        self.assertEqual(row['state_after']['checkin_sessions']['name'],'Aman Sharma')

    def test_own_room_answer_uses_verified_sender_stay_in_actual_flow(self):
        answers=[{'action':'ANSWER','reply':'Your room number is 240.','operation_text':'','language':'english','confidence':.96},
                 {'menu_related':False,'action':'ANSWER','reply':'Your room number is 240.','language':'english'}]
        prompts=[]
        def transport(url,**kwargs):
            prompts.append(json.dumps(kwargs['json']))
            return Mock(status_code=200,json=Mock(return_value={'candidates':[{'content':{'parts':[{'text':json.dumps(answers.pop(0))}]},'finishReason':'STOP'}]}))
        with patch.object(app,'GEMINI_API_KEY','test'):
            row=hotel_eval.evaluate(app,hotel_eval.CASES[2],transport=transport)
        self.assertFalse(row['errors'],row)
        self.assertEqual(row['output'],'Your room number is 240.')
        self.assertIn('Verified sender stay',prompts[1])
        self.assertEqual(len(prompts),2)

    def test_acceptance_checks_bill_scope_photo_target_and_default_script(self):
        self.assertIn('Wrong bill scope',hotel_eval.contract_errors({'actions':['BILL'],'scope':'food'},{'action':'BILL','operation_text':'full','language':'hinglish'},'Ji, bill hai.'))
        self.assertIn('Wrong photo target',hotel_eval.contract_errors({'actions':['SHOW_PHOTO'],'photo':'Family Suite'},{'action':'SHOW_PHOTO','photo_target':'Deluxe','language':'hinglish'},'Ji, photo hai.'))
        self.assertIn('Final reply does not match Hinglish script/wording',hotel_eval.contract_errors({'actions':['ANSWER']},{'action':'ANSWER','language':'hinglish'},'Your room number is 240.'))

    def test_reviewed_room_comparison_is_not_replaced_by_full_category_card(self):
        reply='Sabse sasta AC room Deluxe hai, starting rate ₹1,999 per night hai.'
        answers=[{'action':'ROOM_OPTIONS','generic':'','reply':reply,'operation_text':'','show_prices':True,'language':'hinglish','confidence':.96},
                 {'menu_related':False,'action':'ROOM_OPTIONS','generic':'','reply':reply,'show_prices':True,'language':'hinglish'},
                 {'supported':True}]
        def transport(url,**kwargs):
            return Mock(status_code=200,json=Mock(return_value={'candidates':[{'content':{'parts':[{'text':json.dumps(answers.pop(0))}]},'finishReason':'STOP'}]}))
        with patch.object(app,'GEMINI_API_KEY','test'):
            row=hotel_eval.evaluate(app,hotel_eval.REPAIR_CASES[1],transport=transport)
        self.assertFalse(row['errors'],row)
        self.assertEqual(row['output'],reply)
        self.assertEqual(len(row['model_calls']),3)
