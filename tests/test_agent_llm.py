"""Tests for agent/llm.py (the client for OpenAI-compatible chat APIs). No internet needed:
a tiny HTTP server on this computer plays the part of the API."""

import http.server
import json
import os
import sys
import threading
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from agent import llm  # noqa: E402

GOOD_ANSWER = {"choices": [{"message": {"role": "assistant", "content": "hi"}}],
               "usage": {"total_tokens": 42}}
MESSAGES = [{"role": "user", "content": "hello"}]
TOOLS = [{"type": "function", "function": {"name": "t", "description": "d", "parameters": {}}}]


class FakeServer:
    """Answers POST requests with the scripted responses, one after the other, and records
    what it received. Each response is (status, body, headers)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                outer.requests.append({"path": self.path, "headers": dict(self.headers),
                                       "body": json.loads(self.rfile.read(length))})
                status, body, headers = (outer.responses.pop(0) if outer.responses
                                         else (500, "nothing scripted", {}))
                data = (body if isinstance(body, str) else json.dumps(body)).encode()
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):  # keep the test output quiet
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d/v1" % self.server.server_address[1]
        # poll_interval is how often the server checks for "stop"; the default 0.5 s would make
        # every test wait for it when closing.
        threading.Thread(target=self.server.serve_forever, args=(0.01,), daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class ChatClientTest(unittest.TestCase):
    def serve(self, *responses):
        server = FakeServer(responses)
        self.addCleanup(server.close)
        return server

    def make_client(self, server, **kwargs):
        kwargs.setdefault("sleep", lambda seconds: None)  # never really wait in tests
        return llm.ChatClient(server.url, "secret-key", "test-model", **kwargs)

    # ---- the request ----

    def test_posts_the_conversation_to_chat_completions(self):
        server = self.serve((200, GOOD_ANSWER, {}))
        self.make_client(server).chat(MESSAGES, TOOLS)

        request = server.requests[0]
        self.assertEqual(request["path"], "/v1/chat/completions")
        self.assertEqual(request["headers"]["Authorization"], "Bearer secret-key")
        self.assertEqual(request["headers"]["Content-Type"], "application/json")
        self.assertEqual(request["body"], {"model": "test-model", "messages": MESSAGES,
                                           "tools": TOOLS, "temperature": 0})

    def test_no_tools_field_when_there_are_no_tools(self):
        server = self.serve((200, GOOD_ANSWER, {}))
        self.make_client(server).chat(MESSAGES, [])
        self.assertNotIn("tools", server.requests[0]["body"])

    def test_a_trailing_slash_in_the_base_url_is_fine(self):
        server = self.serve((200, GOOD_ANSWER, {}))
        llm.ChatClient(server.url + "/", "k", "m").chat(MESSAGES, TOOLS)
        self.assertEqual(server.requests[0]["path"], "/v1/chat/completions")

    # ---- the answer ----

    def test_returns_the_assistant_message(self):
        server = self.serve((200, GOOD_ANSWER, {}))
        self.assertEqual(self.make_client(server).chat(MESSAGES, TOOLS),
                         {"role": "assistant", "content": "hi"})

    def test_adds_up_the_tokens_used(self):
        server = self.serve((200, GOOD_ANSWER, {}), (200, GOOD_ANSWER, {}))
        client = self.make_client(server)
        client.chat(MESSAGES, TOOLS)
        client.chat(MESSAGES, TOOLS)
        self.assertEqual(client.total_tokens, 84)

    def test_a_missing_usage_field_is_fine(self):
        server = self.serve((200, {"choices": GOOD_ANSWER["choices"]}, {}))
        client = self.make_client(server)
        client.chat(MESSAGES, TOOLS)
        self.assertEqual(client.total_tokens, 0)

    def test_an_answer_that_is_not_json(self):
        server = self.serve((200, "this is not json", {}))
        with self.assertRaisesRegex(llm.LLMError, "unexpected answer"):
            self.make_client(server).chat(MESSAGES, TOOLS)

    def test_an_answer_without_choices(self):
        server = self.serve((200, {"id": "x"}, {}))
        with self.assertRaisesRegex(llm.LLMError, "unexpected answer"):
            self.make_client(server).chat(MESSAGES, TOOLS)

    # ---- errors and retries ----

    def test_an_http_error_is_reported_with_its_message_but_not_the_key(self):
        server = self.serve((401, "invalid api key", {}))
        with self.assertRaises(llm.LLMError) as caught:
            self.make_client(server).chat(MESSAGES, TOOLS)
        self.assertIn("401", str(caught.exception))
        self.assertIn("invalid api key", str(caught.exception))
        self.assertNotIn("secret-key", str(caught.exception))
        self.assertEqual(len(server.requests), 1)  # a 401 is not retried

    def test_a_rate_limit_is_retried_using_retry_after(self):
        server = self.serve((429, "slow down", {"Retry-After": "3"}), (200, GOOD_ANSWER, {}))
        sleeps = []
        client = self.make_client(server, sleep=sleeps.append)
        self.assertEqual(client.chat(MESSAGES, TOOLS)["content"], "hi")
        self.assertEqual(len(server.requests), 2)
        self.assertEqual(sleeps, [3])

    def test_server_errors_are_retried_with_growing_waits(self):
        server = self.serve((500, "oops", {}), (503, "oops", {}), (200, GOOD_ANSWER, {}))
        sleeps = []
        client = self.make_client(server, sleep=sleeps.append)
        client.chat(MESSAGES, TOOLS)
        self.assertEqual(sleeps, [1, 2])

    def test_gives_up_after_the_retries_are_used_up(self):
        server = self.serve(*[(429, "slow down", {})] * 5)
        client = self.make_client(server, retries=2)
        with self.assertRaisesRegex(llm.LLMError, "429"):
            client.chat(MESSAGES, TOOLS)
        self.assertEqual(len(server.requests), 3)  # the first try and two retries

    def test_an_unreachable_server(self):
        server = FakeServer([])
        url = server.url
        server.close()  # nothing is listening on that port any more
        with self.assertRaisesRegex(llm.LLMError, "could not reach"):
            llm.ChatClient(url, "k", "m", sleep=lambda s: None).chat(MESSAGES, TOOLS)


class ToolSchemasTest(unittest.TestCase):
    def test_converts_tool_definitions_to_the_openai_format(self):
        definitions = [{"name": "check_min_width", "description": "Finds narrow shapes.",
                        "input_schema": {"type": "object", "properties": {"min_width": {"type": "integer"}},
                                         "required": ["min_width"]}}]
        self.assertEqual(llm.tool_schemas(definitions), [{
            "type": "function",
            "function": {"name": "check_min_width", "description": "Finds narrow shapes.",
                         "parameters": definitions[0]["input_schema"]},
        }])


class ClientFromEnvironmentTest(unittest.TestCase):
    ENVIRONMENT = {"LLM_BASE_URL": "https://example.test/v1/", "LLM_MODEL": "some-model",
                   "LLM_API_KEY": "secret"}

    def test_builds_a_client_from_the_three_variables(self):
        client = llm.client_from_environment(self.ENVIRONMENT)
        self.assertEqual(client.base_url, "https://example.test/v1")
        self.assertEqual(client.model, "some-model")
        self.assertEqual(client.api_key, "secret")

    def test_names_every_missing_variable(self):
        with self.assertRaises(llm.LLMError) as caught:
            llm.client_from_environment({"LLM_MODEL": "m"})
        self.assertIn("LLM_BASE_URL", str(caught.exception))
        self.assertIn("LLM_API_KEY", str(caught.exception))
        self.assertNotIn("LLM_MODEL", str(caught.exception))

    def test_an_empty_variable_counts_as_missing(self):
        with self.assertRaisesRegex(llm.LLMError, "LLM_API_KEY"):
            llm.client_from_environment(dict(self.ENVIRONMENT, LLM_API_KEY=""))


if __name__ == "__main__":
    unittest.main()
