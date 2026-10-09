import base64
import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ['BOT_AUTOSTART'] = '0'
import app
import hotel_admin
from reliability import Store


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name + '/test.db')
        p = patch.object(app, 'durable_store', self.store)
        p.start(); self.addCleanup(p.stop)
        p = patch.dict(os.environ, {'HOTEL_ADMIN_PASSWORD': 'test-password', 'HOTEL_ADMIN_USER': 'admin'})
        p.start(); self.addCleanup(p.stop)
        self.client = app.app.test_client()
        self.auth = {'Authorization': 'Basic ' + base64.b64encode(b'admin:test-password').decode()}

    def test_monitor_requires_auth(self):
        self.assertEqual(self.client.get('/admin/chats').status_code, 401)
        self.assertEqual(self.client.get('/admin').status_code, 401)
        self.assertEqual(self.client.get('/admin/chats.csv').status_code, 401)

    def test_dashboard_renders_and_rejects_wrong_password(self):
        result = self.client.get('/admin', headers=self.auth)
        self.assertEqual(result.status_code, 200)
        self.assertIn('Download for Excel', result.get_data(as_text=True))
        self.assertIn("text.textContent=m.text", result.get_data(as_text=True))
        wrong = {'Authorization': 'Basic ' + base64.b64encode(b'admin:wrong').decode()}
        self.assertEqual(self.client.get('/admin/chats',headers=wrong).status_code,401)

    def test_legacy_outbox_migration_preserves_data(self):
        import sqlite3
        from contextlib import closing
        path = self.tmp.name + '/legacy.db'
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE outbox (id TEXT PRIMARY KEY, body TEXT NOT NULL, state TEXT, remote_id TEXT, attempts INTEGER, due REAL, code TEXT, updated REAL)')
            db.execute('INSERT INTO outbox VALUES (?,?,?,?,?,?,?,?)', ('old',json.dumps({'to':'919111111111','type':'text','text':{'body':'old message'}}),'sent',None,1,0,None,1700000000))
            db.commit()
        store = Store(path)
        messages = hotel_admin.read_messages(store)
        self.assertEqual(messages[0]['text'], 'old message')
        self.assertTrue(messages[0]['estimated_time'])
        store.enqueue_send('new', {'to':'919111111111','type':'text','text':{'body':'new message'}})
        self.assertFalse(hotel_admin.read_messages(store)[0]['estimated_time'])

    def test_monitor_disabled_without_password(self):
        with patch.dict(os.environ, {'HOTEL_ADMIN_PASSWORD': ''}):
            self.assertEqual(self.client.get('/admin/chats', headers=self.auth).status_code, 503)

    def test_live_messages_and_delivery_state(self):
        self.store.enqueue({'id':'m1','from':'919111111111','type':'text','text':{'body':'101 clean'}})
        self.store.enqueue_send('s1', {'to':'919111111111','type':'text','text':{'body':'Updated'}})
        result = self.client.get('/admin/chats?phone=919111111111', headers=self.auth)
        self.assertEqual(result.status_code, 200)
        messages = result.get_json()['messages']
        self.assertEqual({m['text'] for m in messages}, {'101 clean', 'Updated'})
        self.assertEqual({m['status'] for m in messages}, {'queued'})
        self.assertIn('no-store', result.headers['Cache-Control'])
        self.assertEqual(self.client.get('/admin/chats?phone=919222222222',headers=self.auth).get_json()['messages'], [])

    def test_csv_neutralizes_formulas_and_downloads_all_pages(self):
        for i in range(510):
            self.store.enqueue({'id':str(i),'from':'919111111111','type':'text','text':{'body':'=1+1'}})
        result = self.client.get('/admin/chats.csv', headers=self.auth)
        self.assertEqual(result.status_code, 200)
        self.assertIn("'=1+1", result.get_data(as_text=True))
        self.assertEqual(result.get_data(as_text=True).count("'=1+1"), 510)

    def test_delivery_callback_preserves_original_chat_time(self):
        self.store.enqueue_send('s1', {'to':'919111111111','type':'text','text':{'body':'Earlier reply'}})
        before = self.client.get('/admin/chats',headers=self.auth).get_json()['messages'][0]['time']
        with self.store.db() as db:
            db.execute("UPDATE outbox SET updated=updated+86400, state='read' WHERE id='s1'")
        after = self.client.get('/admin/chats',headers=self.auth).get_json()['messages'][0]
        self.assertEqual(after['time'], before)
        self.assertEqual(after['status'], 'read')

    def test_cleaning_command_routes_before_ai(self):
        with patch.object(app, 'handle_room_cleaning_message', create=True, return_value=True) as clean, patch.object(app, '_process_and_reply') as ai:
            app.process_and_reply({'type':'text','text':{'body':'101 clean'}}, '919111111111', 'text')
            clean.assert_called_once()
            ai.assert_not_called()

    def test_monika_identity_without_ai(self):
        with patch.object(app, 'send_whatsapp_message') as send, patch.object(app, 'get_guest_response_language', return_value='hinglish'), patch.object(app, 'understand_guest_request', side_effect=AssertionError('AI not needed')):
            app.process_and_reply({'type':'text','text':{'body':'aapka naam kya hai'}}, '919111111111', 'text')
            self.assertIn('Monika', send.call_args.args[1])

    def test_persona_is_present_even_without_override_file(self):
        with patch.object(app.Path, 'read_text', side_effect=OSError):
            self.assertIn('Monika', app.concierge_style())

    def test_guest_named_monika_does_not_trigger_bot_introduction(self):
        with patch.object(app, 'checkin_sessions', {'919111111111': {'step':'NAME'}}), patch.object(app, 'send_whatsapp_message') as send:
            self.assertFalse(app.handle_monika_identity({'text':{'body':'Monika'}}, '919111111111', 'text'))
            send.assert_not_called()


class CleaningTests(unittest.TestCase):
    def setUp(self):
        self.bot = Mock(wraps=app)
        self.bot.SHEET_ID = 'test-sheet'
        self.bot.refresh_staff_roster.return_value = True
        self.bot.find_on_duty_staff.return_value = {'name':'Ravi','phone':'919222222222'}
        self.bot.is_on_duty_staff_phone.return_value = False
        self.bot.send_whatsapp_message = Mock(return_value=True)
        self.sheet = Mock(col_count=6)
        self.sheet.get_all_values.return_value = [
            ['Room','Category','Rate','Guest Name','Phone','Status'],
            ['101','Deluxe','1000','Guest','919333333333','IN']]
        self.bot.get_gspread_client = Mock()
        self.bot.get_gspread_client.return_value.open_by_key.return_value.get_worksheet.return_value = self.sheet

    def run_command(self, text='101 clean', sender='919222222222', mid='clean1'):
        return hotel_admin.handle_cleaning(self.bot, {'id':mid,'text':{'body':text}}, sender, 'text')

    def test_writes_cleaning_fields_without_changing_stay(self):
        self.assertTrue(self.run_command())
        changes = self.sheet.batch_update.call_args.args[0]
        self.assertIn({'range':'G2','values':[['CLEAN']]}, changes)
        self.assertIn({'range':'H2','values':[['Ravi']]}, changes)
        self.assertFalse(any(c['range'].startswith(('A','B','C','D','E','F')) for c in changes))
        self.assertEqual(self.sheet.batch_update.call_args.kwargs['value_input_option'], 'RAW')

    def test_guest_or_other_staff_cannot_update(self):
        self.run_command(sender='919333333333')
        self.bot.get_gspread_client.assert_not_called()

    def test_unavailable_roster_does_not_write(self):
        self.bot.refresh_staff_roster.return_value = False
        self.run_command()
        self.bot.get_gspread_client.assert_not_called()

    def test_unknown_or_duplicate_room_does_not_write(self):
        self.run_command('999 clean')
        self.sheet.batch_update.assert_not_called()
        self.sheet.get_all_values.return_value.append(self.sheet.get_all_values.return_value[1])
        self.run_command()
        self.sheet.batch_update.assert_not_called()

    def test_missing_room_header_does_not_use_last_column(self):
        self.sheet.get_all_values.return_value = [['Unknown','Status'], ['other','101']]
        self.run_command()
        self.sheet.batch_update.assert_not_called()

    def test_same_message_is_not_reapplied(self):
        self.sheet.get_all_values.return_value[0] += ['Cleaning Status','Cleaned By','Cleaned At','Cleaning Message ID']
        self.sheet.get_all_values.return_value[1] += ['CLEAN','Ravi','earlier','clean1']
        self.run_command()
        self.sheet.batch_update.assert_not_called()

    def test_timeout_never_claims_saved(self):
        self.sheet.batch_update.side_effect = TimeoutError
        self.run_command()
        self.assertIn('confirm nahi', self.bot.send_whatsapp_message.call_args.args[1])

    def test_negation_and_guest_request_are_not_commands(self):
        for text in ['101 not clean','101 clean nahi','please clean room 101','101 cleaning']:
            self.assertFalse(self.run_command(text))
        self.sheet.batch_update.assert_not_called()


if __name__ == '__main__':
    unittest.main()
