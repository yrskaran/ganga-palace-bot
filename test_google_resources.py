"""Offline checks for bounded Google client lifetime; no Google requests."""
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

os.environ['BOT_AUTOSTART'] = '0'
import app


class GoogleResources(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch.object(app, '_google_clients', threading.local()),
            patch.object(app, 'GOOGLE_SERVICE_ACCOUNT_JSON', '{"project_id":"test"}'),
            patch.object(app.Credentials, 'from_service_account_info', side_effect=lambda *a, **k: Mock()),
            patch.object(app.gspread, 'authorize', side_effect=lambda *a, **k: Mock()),
        ]
        self.values = [p.start() for p in self.patches]
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])

    def test_thousands_of_refreshes_reuse_one_transport_and_credentials(self):
        first = app.get_gspread_client()
        for _ in range(5000):
            self.assertIs(app.get_gspread_client(), first)
        self.values[2].assert_called_once()
        self.values[3].assert_called_once()
        first.set_timeout.assert_called_once_with((10, 30))

    def test_concurrent_workers_do_not_share_sessions(self):
        clients = []
        barrier = threading.Barrier(4)
        def worker():
            client = app.get_gspread_client()
            clients.append(client)
            barrier.wait(timeout=5)
            for _ in range(100):
                self.assertIs(app.get_gspread_client(), client)
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(worker) for _ in range(4)]
            for future in futures: future.result(timeout=10)
        self.assertEqual(len({id(client) for client in clients}), 4)
        self.assertEqual(self.values[3].call_count, 4)

    def test_config_change_closes_old_session_and_rebuilds(self):
        old = app.get_gspread_client()
        with patch.object(app, 'GOOGLE_SERVICE_ACCOUNT_JSON', '{"project_id":"changed"}'):
            new = app.get_gspread_client()
        self.assertIsNot(new, old)
        old.http_client.session.close.assert_called_once()
        with patch.object(app, 'GOOGLE_SERVICE_ACCOUNT_JSON', ''):
            self.assertIsNone(app.get_gspread_client())
        new.http_client.session.close.assert_called_once()

    def test_drive_transport_closed_on_failed_upload(self):
        service = Mock()
        service.files.return_value.list.return_value.execute.side_effect = RuntimeError('offline failure')
        with patch.object(app, 'build', return_value=service):
            self.assertIsNone(app.upload_image_to_google_drive(b'test', 'test.jpg'))
        service.close.assert_called_once()

if __name__ == '__main__':
    unittest.main()
