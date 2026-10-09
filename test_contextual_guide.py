import os
import unittest
from unittest.mock import patch

os.environ['BOT_AUTOSTART'] = '0'
import app

PHONE = '919555555555'

class ContextualGuideTests(unittest.TestCase):
    def setUp(self):
        app.guide_service_sessions.pop(PHONE, None)
        app.conversation_memory.pop(PHONE, None)

    def tearDown(self):
        app.guide_service_sessions.pop(PHONE, None)
        app.conversation_memory.pop(PHONE, None)

    def test_matlab_is_explanation_not_decline_or_booking(self):
        self.assertEqual(app._human_guide_intent('Local guide matlab?'), 'explain')
        self.assertEqual(app._human_guide_intent('guide mat arrange karna'), 'decline')
        with patch.object(app, 'send_whatsapp_message') as send, \
             patch.object(app, 'notify_reception_request') as notify, \
             patch.object(app, 'get_guest_response_language', return_value='hinglish'):
            app.guide_service_sessions[PHONE] = {'text':'older enquiry','created':__import__('time').time()}
            self.assertTrue(app.handle_human_guide_request(PHONE, 'Local guide matlab?', None))
            self.assertIn('guide se mera matlab', send.call_args.args[1].lower())
            notify.assert_not_called()
            self.assertNotIn(PHONE, app.guide_service_sessions)

    def test_short_options_question_continues_local_guide_topic(self):
        app.conversation_memory[PHONE] = [{
            'role':'assistant',
            'content':'Local guide ka matlab hai Haridwar ke mandir aur ghoomne ki jagahen dikhane wala guide.'
        }]
        with patch.object(app, 'build_guide_fallback', return_value='Ghoomne ke options: Har Ki Pauri') as build, \
             patch.object(app, 'attach_google_maps_links', side_effect=lambda x:x), \
             patch.object(app, 'send_whatsapp_message') as send, \
             patch.object(app, 'remember_conversation'):
            self.assertTrue(app._contextual_local_guide_options_reply(PHONE, 'Kya kya option hai?'))
            build.assert_called_once_with('more options', PHONE)
            self.assertIn('Har Ki Pauri', send.call_args.args[1])

if __name__ == '__main__':
    unittest.main()
