import os
os.environ['BOT_AUTOSTART']='0'
import unittest
from unittest.mock import Mock
import gemini_checks as checks


class GeminiCheckBudgetTests(unittest.TestCase):
    def test_budget_stops_before_extra_billable_request(self):
        response=Mock(status_code=200)
        response.json.return_value={'usageMetadata':{'totalTokenCount':10}}
        post=Mock(return_value=response)
        budget=checks.Budget(post,limit=1,interval=0)
        budget.post('https://generativelanguage.googleapis.com/v1beta/models/x:generateContent')
        with self.assertRaises(checks.CheckStopped):
            budget.post('https://generativelanguage.googleapis.com/v1beta/models/x:generateContent')
        self.assertEqual(post.call_count,1)
        self.assertEqual(budget.tokens,10)

    def test_first_provider_error_stops_further_tests(self):
        post=Mock(return_value=Mock(status_code=429))
        budget=checks.Budget(post,limit=20,interval=0)
        budget.post('https://generativelanguage.googleapis.com/v1beta/models/x:generateContent')
        with self.assertRaises(checks.CheckStopped):
            budget.post('https://generativelanguage.googleapis.com/v1beta/models/x:generateContent')
        self.assertEqual(post.call_count,1)

    def test_operational_network_is_not_allowed(self):
        post=Mock()
        with self.assertRaises(checks.CheckStopped):
            checks.Budget(post,interval=0).post('https://graph.facebook.com/messages')
        post.assert_not_called()
