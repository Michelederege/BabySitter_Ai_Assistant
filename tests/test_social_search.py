import io
import json
import urllib.error

import pytest

from babysitter.plugins.tools.social import (
    SocialSearchError,
    SocialSearchTool,
    perform,
    prepare,
    redact,
    summarize,
)
from babysitter.secrets import DpapiKeyVault, MemoryVault, SecretsError
from babysitter.security import require_scrapecreators_url


class _Body:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, _limit: int) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> bool:
        return False


def test_prepare_sends_only_the_cleaned_query():
    prepared = prepare("tiktok-posts", "  funny cats  ")
    assert prepared.url == (
        "https://api.scrapecreators.com/v1/tiktok/search/keyword?query=funny+cats"
    )
    assert "funny cats" in prepared.ask
    assert "api key" in prepared.ask.lower()


def test_prepare_strips_at_and_hash():
    profile = prepare("tiktok-profile", "@SomeName")
    assert profile.url.endswith("handle=SomeName")
    tag = prepare("tiktok-hashtag", "#fyp")
    assert tag.url.endswith("hashtag=fyp")


def test_prepare_rejects_a_login_inside_a_link():
    with pytest.raises(SocialSearchError):
        prepare("youtube-transcript", "https://user:secret@youtube.com/watch?v=abc")


def test_prepare_rejects_unknown_and_empty():
    with pytest.raises(SocialSearchError):
        prepare("followers", "someone")
    with pytest.raises(SocialSearchError):
        prepare("reddit", "   ")


def test_other_hosts_are_refused():
    with pytest.raises(ValueError):
        require_scrapecreators_url("https://example.com/v1/tiktok/search/keyword")
    with pytest.raises(ValueError):
        require_scrapecreators_url("http://api.scrapecreators.com/v1/credit/balance")


def test_perform_puts_the_key_in_the_header_only():
    seen = {}

    def opener(request, timeout=0):
        seen["url"] = request.full_url
        seen["header"] = request.get_header("X-api-key")
        seen["timeout"] = timeout
        body = json.dumps(
            {
                "items": [
                    {
                        "desc": "a public clip",
                        "url": "https://www.tiktok.com/@a/video/1",
                        "author": {"unique_id": "a"},
                    }
                ]
            }
        ).encode()
        return _Body(body)

    prepared = prepare("tiktok-posts", "cats")
    outcome = perform(prepared, "test-key-1234", opener)
    assert seen["header"] == "test-key-1234"
    assert "test-key-1234" not in seen["url"]
    assert "a public clip" in outcome.detail
    assert "https://www.tiktok.com/@a/video/1" in outcome.detail
    assert "test-key-1234" not in outcome.detail


def test_rejected_key_does_not_echo_the_secret():
    def opener(request, timeout=0):
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "no",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"bad test-key-1234"}'),
        )

    prepared = prepare("credits", "")
    with pytest.raises(SocialSearchError) as caught:
        perform(prepared, "test-key-1234", opener)
    assert "test-key-1234" not in str(caught.value)
    assert "rejected" in str(caught.value).lower()


def test_summarize_and_redact():
    lines = summarize(
        {"posts": [{"title": "hello", "permalink": "https://reddit.com/r/x"}]}
    )
    assert lines == ["hello — https://reddit.com/r/x"]
    assert redact("key is abcdefgh", "abcdefgh") == "key is [key hidden]"


def test_tool_describes_without_calling_out(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("describe must not open the network")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    tool = SocialSearchTool(MemoryVault())
    text = tool.describe({"action": "reddit", "text": "sourdough"})
    assert "sourdough" in text
    assert "Send this search" in text


def test_memory_vault_round_trip_and_rejects_spaces():
    vault = MemoryVault()
    assert vault.has_key() is False
    vault.save("abcdefgh")
    assert vault.load() == "abcdefgh"
    vault.delete()
    assert vault.load() is None
    with pytest.raises(SecretsError):
        vault.save("has spaces")


def test_non_windows_vault_does_not_write_the_key(tmp_path, monkeypatch):
    monkeypatch.setattr("babysitter.secrets.sys.platform", "linux")
    path = tmp_path / "scrapecreators.dpapi"
    vault = DpapiKeyVault(path)
    assert vault.available is False
    with pytest.raises(SecretsError):
        vault.save("abcdefgh")
    assert not path.exists()
    assert "abcdefgh" not in " ".join(item.name for item in tmp_path.iterdir())
