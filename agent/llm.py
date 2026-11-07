"""A small client for chat APIs that follow the OpenAI "chat completions" format.

NVIDIA NIM, Groq, OpenRouter and others all speak this format, so the provider is chosen only
by three environment variables: LLM_BASE_URL, LLM_MODEL and LLM_API_KEY. Standard library only.
"""

import json
import os
import time
import urllib.error
import urllib.request

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_WAIT_SECONDS = 60
MAX_ERROR_TEXT = 300  # how much of a server's error message we show


class LLMError(Exception):
    """The language model could not be reached or gave an unusable answer."""


class ChatClient:
    def __init__(self, base_url, api_key, model, retries=3, sleep=time.sleep):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.retries = retries
        self.sleep = sleep  # a parameter so tests do not really wait
        self.total_tokens = 0  # added up over all calls, for the evaluation's cost report

    def chat(self, messages, tools):
        """Sends the conversation and returns the assistant's message (a dict)."""
        body = {"model": self.model, "messages": messages, "temperature": 0}
        if tools:
            body["tools"] = tools
        answer = self._post_with_retries(json.dumps(body).encode("utf-8"))

        try:
            message = answer["choices"][0]["message"]
            usage = answer.get("usage") or {}
        except (KeyError, IndexError, TypeError, AttributeError):
            raise LLMError("unexpected answer from the LLM: " + json.dumps(answer)[:MAX_ERROR_TEXT])
        self.total_tokens += usage.get("total_tokens", 0)
        return message

    def _post_with_retries(self, data):
        for attempt in range(self.retries + 1):
            try:
                return self._post(data)
            except urllib.error.HTTPError as error:
                text = error.read().decode("utf-8", errors="replace")[:MAX_ERROR_TEXT]
                retryable = error.code == 429 or error.code >= 500
                if not retryable or attempt == self.retries:
                    raise LLMError("the LLM returned HTTP %d: %s" % (error.code, text))
                self.sleep(self._wait_seconds(error, attempt))
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                raise LLMError("could not reach the LLM at %s: %s" % (self.base_url, error))
            except ValueError:  # the answer was not JSON
                raise LLMError("unexpected answer from the LLM (it is not JSON)")

    def _post(self, data):
        request = urllib.request.Request(
            self.base_url + "/chat/completions", data=data, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.api_key})
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _wait_seconds(error, attempt):
        """The server's Retry-After if it sent a number, else 1, 2, 4... seconds."""
        try:
            return min(float(error.headers.get("Retry-After")), MAX_RETRY_WAIT_SECONDS)
        except (TypeError, ValueError):
            return 2 ** attempt


def tool_schemas(definitions):
    """Converts the tool definitions of agent/tools.py (Anthropic style, with "input_schema")
    to the OpenAI style that the chat API expects."""
    return [{"type": "function",
             "function": {"name": d["name"], "description": d["description"],
                          "parameters": d["input_schema"]}}
            for d in definitions]


def client_from_environment(environment=None):
    environment = os.environ if environment is None else environment
    names = ["LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY"]
    missing = [name for name in names if not environment.get(name)]
    if missing:
        raise LLMError("missing environment variable(s): " + ", ".join(missing))
    return ChatClient(environment["LLM_BASE_URL"], environment["LLM_API_KEY"],
                      environment["LLM_MODEL"])
