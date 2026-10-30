"""The Sarvam wrapper with the network faked: failures must become LLMError, never a crash."""
import httpx
import pytest

from app import llm
from app.llm import chat as real_chat

GOOD_BODY = {"choices": [{"message": {"content": "Hello"}}]}


@pytest.fixture
def post(monkeypatch):
    """Replaces the network with a list of responses, and records what was sent."""
    monkeypatch.setenv("SARVAM_API_KEY", "test-key-value")

    def install(*responses):
        sent = []
        queue = list(responses)

        def fake_post(url, headers, json, timeout):
            sent.append({"url": url, "headers": headers, "json": json})
            answer = queue.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        monkeypatch.setattr(llm.httpx, "post", fake_post)
        return sent

    return install


def test_returns_the_assistant_message_and_sends_the_key_and_tools(post):
    sent = post(httpx.Response(200, json=GOOD_BODY))
    assert real_chat([{"role": "user", "content": "Hi"}], []) == {"content": "Hello"}
    assert sent[0]["headers"]["api-subscription-key"] == "test-key-value"
    assert sent[0]["json"]["model"] == llm.MODEL
    assert sent[0]["json"]["tool_choice"] == "auto"


@pytest.mark.parametrize("first", [httpx.Response(503), httpx.Response(429), httpx.ConnectTimeout("slow")])
def test_retries_once_on_temporary_failure(post, first):
    sent = post(first, httpx.Response(200, json=GOOD_BODY))
    assert real_chat([], [])["content"] == "Hello"
    assert len(sent) == 2


def test_gives_up_after_the_retry(post):
    sent = post(httpx.Response(503), httpx.Response(503))
    with pytest.raises(llm.LLMError):
        real_chat([], [])
    assert len(sent) == 2


@pytest.mark.parametrize("status", [400, 401, 402])
def test_permanent_failures_are_not_retried(post, status):
    sent = post(httpx.Response(status))
    with pytest.raises(llm.LLMError):
        real_chat([], [])
    assert len(sent) == 1


@pytest.mark.parametrize("body", [{}, {"choices": []}, {"choices": [{}]}])
def test_unexpected_response_is_an_llm_error(post, body):
    post(httpx.Response(200, json=body))
    with pytest.raises(llm.LLMError):
        real_chat([], [])


def test_missing_key_is_an_llm_error(monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    with pytest.raises(llm.LLMError):
        real_chat([], [])


def test_errors_never_contain_the_key(post):
    post(httpx.ConnectError("failed"), httpx.ConnectError("failed"))
    with pytest.raises(llm.LLMError) as error:
        real_chat([], [])
    assert "test-key-value" not in str(error.value)
