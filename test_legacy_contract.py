"""Prevent silent loss of the original Ganga hotel bot's features.

This catches deleted or renamed historical top-level functions. It does NOT
prove their behavior works: integration tests and live external checks remain
mandatory before deploying changes.
"""
import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASELINE = json.loads((ROOT / "legacy_function_baseline.json").read_text(encoding="utf-8"))
SOURCE = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))


class LegacyHotelContract(unittest.TestCase):
    def test_no_original_ganga_top_level_function_removed(self):
        present = {
            node.name for node in SOURCE.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        missing = sorted(set(BASELINE["functions"]) - present)
        self.assertEqual(
            missing, [],
            "Historical hotel functions disappeared. Check their replacement "
            "and explicitly review preservation before deleting/renaming."
        )

    def test_original_function_baseline_is_complete(self):
        self.assertEqual(BASELINE["expected_original_top_level_functions"], 272)
        self.assertEqual(len(BASELINE["functions"]), 272)
        self.assertEqual(len(set(BASELINE["functions"])), 272)

    def test_lifecycle_dispatcher_still_wires_all_five_guest_reminders(self):
        worker = next(
            node for node in SOURCE.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "monitor_guest_status_lifecycle"
        )
        events = {
            node.value for node in ast.walk(worker)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        required = {
            "WELCOME", "30_MINUTE", "GOOD_MORNING_BREAKFAST",
            "LUNCH", "GANGA_AARTI", "DINNER", "CHECKOUT"
        }
        self.assertFalse(
            required - events,
            "Missing lifecycle event dispatch: " + ", ".join(sorted(required - events)),
        )

    def test_startup_keeps_the_lifecycle_worker(self):
        worker = next(
            node for node in SOURCE.body
            if isinstance(node, ast.FunctionDef) and node.name == "startup"
        )
        named = {
            node.id for node in ast.walk(worker) if isinstance(node, ast.Name)
        }
        self.assertIn("monitor_guest_status_lifecycle", named)

    def test_hotel_data_contains_all_four_reminder_windows(self):
        data = (ROOT / "hotel_data.txt").read_text(encoding="utf-8")
        for name in ("Breakfast", "Lunch", "Ganga Aarti", "Dinner"):
            with self.subTest(name=name):
                self.assertIn(name + " Reminder Window:", data)

    def test_demo_and_real_hotel_modes_do_not_share_proactive_guest_data(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("if CUSTOMER_DEMO_MODE:", source)
        self.assertIn("def fetch_sheet_data_sync(", source)
        # Reminder paths remain in the file, but demo guests cannot trigger
        # real hotel's proactive messaging from someone else's Rooms sheet.
        snapshot = source.split("def fetch_sheet_data_sync(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("if CUSTOMER_DEMO_MODE:", snapshot)
        self.assertIn("return False", snapshot)


if __name__ == "__main__":
    unittest.main()
