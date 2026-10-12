"""Regression test for native Cohere JSON contracts."""
import os
import unittest
from unittest.mock import Mock, patch
os.environ["BOT_AUTOSTART"] = "0"
import app
import ai_receptionist as gateway


class CohereContractTest(unittest.TestCase):
    def test_native_duplicate_json_uses_final_valid_contract_object(self):
        schema = {"type": "object", "properties": {"reply": {"type": "string"}}, "required": ["reply"], "additionalProperties": False}
        answer = '{"reply":"Ji, request samajh gayi."}'
        duplicate = '{"reply":"Draft","internal_review":"do not expose"}' + answer
        response = Mock(status_code=200)
        response.json.return_value = {
            "message": {"content": [{"type": "text", "text": duplicate}]},
            "finish_reason": "COMPLETE",
        }
        token = gateway.current.set({"contract_request": True, "json_schema": schema, "language": "english"})
        try:
            with patch.object(app, "COHERE_API_KEY", "test"), patch.object(app, "_cohere_circuit_open", return_value=False), patch.object(app.requests, "post", return_value=response) as request:
                output = app.ask_cohere_chat("Give final JSON.", structured=True)
        finally:
            gateway.current.reset(token)
        self.assertEqual(output, answer)
        self.assertEqual(request.call_count, 1)

    def test_never_extract_json_from_internal_reasoning_prose(self):
        schema = {"type": "object", "properties": {"reply": {"type": "string"}}, "required": ["reply"]}
        raw = 'We need to analyze the request. {"reply":"Looks okay."}'
        self.assertEqual(app._cohere_select_final_contract_json(raw, schema), raw)

    def test_invalid_native_reasoning_retries_compat_json_once(self):
        schema = {"type": "object", "properties": {"reply": {"type": "string"}}, "required": ["reply"]}
        native = Mock(status_code=200)
        native.json.return_value = {
            "message": {"content": [{"type": "text", "text": "We need to analyze this request before answering."}]},
            "finish_reason": "COMPLETE",
        }
        compat = Mock(status_code=200)
        compat.json.return_value = {
            "choices": [{"message": {"content": '{"reply":"Ji, bataiye."}'}, "finish_reason": "stop"}],
        }
        token = gateway.current.set({"contract_request": True, "json_schema": schema, "language": "english"})
        try:
            with patch.object(app, "COHERE_API_KEY", "test"), patch.object(app, "_cohere_circuit_open", return_value=False), patch.object(app.requests, "post", side_effect=[native, compat]) as request:
                output = app.ask_cohere_chat("Reply in JSON.", structured=True)
        finally:
            gateway.current.reset(token)
        self.assertEqual(output, '{"reply":"Ji, bataiye."}')
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[0].args[0], "https://api.cohere.ai/v2/chat")
        self.assertEqual(request.call_args_list[1].args[0], "https://api.cohere.ai/compatibility/v1/chat/completions")

    def test_v2_json_schema_contract(self):
        schema = {"type": "object", "properties": {"reply": {"type": "string"}}, "required": ["reply"]}
        response = Mock(status_code=200)
        response.json.return_value = {
            "message": {"content": [{"type": "text", "text": '{"reply":"Ji."}'}]},
            "finish_reason": "COMPLETE",
        }
        token = gateway.current.set({"contract_request": True, "json_schema": schema, "language": "english"})
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
