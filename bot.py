"""Compatibility entry point for the hotel WhatsApp service."""
import os
os.environ["BOT_AUTOSTART"] = "0"
from app import app

if __name__ == "__main__":
    import runpy
    runpy.run_module("serve", run_name="__main__")
