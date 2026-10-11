import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ['BOT_AUTOSTART'] = '0'
import app


class ProductionProfileTests(unittest.TestCase):
    def test_configured_real_menu_scopes_are_narrow_and_have_no_demo(self):
        config = json.loads(Path('customer_config.json').read_text())
        with patch.object(app, 'CUSTOMER_CONFIG', config), patch.object(app, 'CUSTOMER_DEMO_MODE', False), patch.object(app, 'HOTEL_CONFIG_CACHE', {'signature':None,'data':None}):
            for section, expected, excluded in [('DRINKS','Masala Chai','Poha'),('SNACKS','Veg Sandwich','Dal Tadka'),('MAIN_COURSE','Dal Tadka','Masala Chai'),('RAITA','Boondi Raita','Green Salad'),('SALAD','Green Salad','Boondi Raita')]:
                with self.subTest(section=section):
                    reply = app._menu_section_message(section, include_cta=False)
                    self.assertIsNotNone(reply)
                    self.assertIn(expected, reply)
                    self.assertNotIn(excluded, reply)
                    self.assertNotIn('DEMO', reply.upper())

    def test_new_hotel_cannot_inherit_old_hotel_sheet_or_staff_connections(self):
        config = {'hotel':{'name':'New Hotel','location':'New City'},'demo_mode':False,
                  'contacts':{'reception_phone':'919111111111'},'integrations':{'sheet_id':'NEW_HOTEL_SHEET'}}
        with tempfile.TemporaryDirectory() as folder:
            filename = Path(folder) / 'hotel.json'
            filename.write_text(json.dumps(config))
            env = dict(os.environ, CUSTOMER_CONFIG_FILE=str(filename), BOT_AUTOSTART='0',
                       SHEET_ID='OLD_HOTEL_SHEET', KITCHEN_PHONE='919222222222',
                       STAFF_PHONE='919333333333', OWNER_PHONE='919444444444')
            output = subprocess.check_output([sys.executable,'-c',
                'import app,json; print(json.dumps([app.SHEET_ID,app.KITCHEN_PHONE,app.STAFF_PHONE,app.OWNER_PHONE,app.RECEPTION_PHONE]))'], env=env, text=True)
        self.assertEqual(json.loads(output.strip().splitlines()[-1]),
                         ['NEW_HOTEL_SHEET','','','','919111111111'])

    def test_active_and_example_profiles_use_production_ai_flow(self):
        for filename in ['customer_config.json','customer_config.shreya_galaxy.json','customer_config.json.example']:
            config = json.loads(Path(filename).read_text())
            self.assertIs(config.get('demo_mode'), False)
            self.assertIs(config.get('ai_receptionist_flow'), True)


if __name__ == '__main__':
    unittest.main()
