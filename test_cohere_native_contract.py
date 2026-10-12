"""Regression test for native Cohere JSON contracts."""
import os
import unittest
from unittest.mock import Mock, patch
os.environ["BOT_AUTOSTART"] = "0"
import app
import ai_receptionist as gateway


class CohereContractTest(unittest.TestCase):
    def test_v2_json_schema_contract(self):
        schema = {"type": "object", "properties": {"reply": {"type": "string"}}, "required": ["reply"]}
        response = Mock(status_code=200)
        response.json.return_value = {
            "message": {"content": [{"type": "text", "text": '{"reply":"Ji."}'}]},
            "finish_reason": "COMPLETE",
        }
        token = gateway.current.set({"contract_request": True, "json_schema": schema})
        try:
            with patch.object(app, "COHERE_API_KEY", "test"), patch.object(app, "_cohere_circuit_open", return_value=False), patch.object(app.requests, "post", return_value=response) as request:
                output = app.ask_cohere_chat("Return a JSON reply.", structured=True)
        finally:
            gateway.current.reset(token)
        self.assertEqual(output, '{"reply":"Ji."}')
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.kwargs["json"]["response_format"], {"type": "json_object", "schema": schema})
        self.assertEqual(request.call_args.args[0], "https://api.cohere.ai/v2/chat")


if __name__ == "__main__":
    unittest.main()
