"""Public social search through ScrapeCreators.

The recipes in
https://github.com/ScrapeCreators/social-media-research-skills
are research steps on top of one public API. This tool runs the search
step: public posts, public profiles, public comments, and a transcript
of one short public video.

It does not pull follower lists, and it does not guess age or gender.
The caller must already have shown the user the exact words that will
be sent, and waited for a yes. The API key is passed in and never logged.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from babysitter.plugins.tools.base import ToolResult
from babysitter.secrets import KeyVault, SecretsError
from babysitter.security import require_scrapecreators_url


API_ROOT = "https://api.scrapecreators.com"

_TEXT_KEYS = (
    "desc",
    "text",
    "title",
    "caption",
    "description",
    "full_name",
    "name",
    "nickname",
)
_URL_KEYS = ("url", "share_url", "link", "permalink", "video_url", "tweet_url")
_WHO_KEYS = ("unique_id", "username", "handle", "nickname")


class SocialSearchError(Exception):
    """A search did not run, or ScrapeCreators refused it."""


@dataclass(frozen=True)
class SearchAction:
    id: str
    label: str
    summary: str
    path: str
    kind: str
    param: str
    placeholder: str
    note: str
    timeout: int = 45


@dataclass(frozen=True)
class PreparedSearch:
    action_id: str
    label: str
    value: str
    url: str
    ask: str


@dataclass(frozen=True)
class SearchOutcome:
    spoken: str
    detail: str


SEARCH_ACTIONS: tuple[SearchAction, ...] = (
    SearchAction(
        "tiktok-posts",
        "TikTok — search posts",
        "search public TikTok posts",
        "/v1/tiktok/search/keyword",
        "query",
        "query",
        "Words to look for, such as pasta recipe",
        "Public TikTok posts that match those words. About 1 credit.",
    ),
    SearchAction(
        "tiktok-hashtag",
        "TikTok — search a hashtag",
        "search a public TikTok hashtag",
        "/v1/tiktok/search/hashtag",
        "hashtag",
        "hashtag",
        "Hashtag without the #, such as fyp",
        "Public posts under that hashtag. About 1 credit.",
    ),
    SearchAction(
        "instagram-reels",
        "Instagram — search reels",
        "search public Instagram reels",
        "/v2/instagram/reels/search",
        "query",
        "query",
        "Words to look for",
        "Public reels. About 1 credit.",
    ),
    SearchAction(
        "youtube",
        "YouTube — search videos",
        "search public YouTube videos",
        "/v1/youtube/search",
        "query",
        "query",
        "Words to look for",
        "Public videos. About 1 credit.",
    ),
    SearchAction(
        "reddit",
        "Reddit — search posts",
        "search public Reddit posts",
        "/v1/reddit/search",
        "query",
        "query",
        "Words to look for",
        "Public posts. About 1 credit.",
    ),
    SearchAction(
        "threads",
        "Threads — search posts",
        "search public Threads posts",
        "/v1/threads/search",
        "query",
        "query",
        "Words to look for",
        "Public posts. About 1 credit.",
    ),
    SearchAction(
        "pinterest",
        "Pinterest — search pins",
        "search public Pinterest pins",
        "/v1/pinterest/search",
        "query",
        "query",
        "Words to look for",
        "Public pins. About 1 credit.",
    ),
    SearchAction(
        "tiktok-profile",
        "TikTok — look up a public profile",
        "look up one public TikTok profile",
        "/v1/tiktok/profile",
        "handle",
        "handle",
        "Public name, without @",
        "That profile's public page. About 1 credit.",
    ),
    SearchAction(
        "instagram-profile",
        "Instagram — look up a public profile",
        "look up one public Instagram profile",
        "/v1/instagram/profile",
        "handle",
        "handle",
        "Public name, without @",
        "That profile's public page. About 1 credit.",
    ),
    SearchAction(
        "youtube-channel",
        "YouTube — look up a channel",
        "look up one public YouTube channel",
        "/v1/youtube/channel",
        "handle",
        "handle",
        "Channel name, without @",
        "That channel's public page. About 1 credit.",
    ),
    SearchAction(
        "twitter-profile",
        "X — look up a public profile",
        "look up one public X profile",
        "/v1/twitter/profile",
        "handle",
        "handle",
        "Public name, without @",
        "That profile's public page. About 1 credit.",
    ),
    SearchAction(
        "youtube-transcript",
        "YouTube — transcript of one video",
        "fetch the transcript of one public YouTube video",
        "/v1/youtube/video/transcript",
        "url",
        "url",
        "A public youtube.com/watch link",
        "The words spoken in that public video. About 1 credit. Long videos may be refused.",
        60,
    ),
    SearchAction(
        "tiktok-comments",
        "TikTok — comments on one video",
        "fetch public comments on one TikTok video",
        "/v1/tiktok/video/comments",
        "url",
        "url",
        "A public tiktok.com video link",
        "Public comments on that video. About 1 credit.",
    ),
    SearchAction(
        "reddit-comments",
        "Reddit — comments on one post",
        "fetch public comments on one Reddit post",
        "/v1/reddit/post/comments",
        "url",
        "url",
        "A public reddit.com post link",
        "Public comments. About 1 credit.",
    ),
    SearchAction(
        "credits",
        "Check credits left",
        "ask how many ScrapeCreators credits are left",
        "/v1/credit/balance",
        "none",
        "",
        "",
        "Only your key is sent. No search words.",
        20,
    ),
)

_BY_ID = {action.id: action for action in SEARCH_ACTIONS}

# Spoken research recipes wired through intents.py (each asks for a yes before
# sending the cleaned query, then summarizes with the local model). Ad library
# lookups stay intentionally refused.
LATER_RECIPES: tuple[tuple[str, str], ...] = (
    ("Outlier posts", "Say “outlier posts about <topic>” to spot public posts beating usual numbers."),
    ("Comment themes", "Say “comment themes <public TikTok or Reddit link>” to group what people are saying."),
    ("Competitor look", "Say “compare the public profile <handle>” to review a public profile."),
    ("Ad library (off)", "Ad library lookups stay refused — BabySitter only searches organic public posts."),
    ("Trends", "Say “trends about <topic>” to see which public angles are getting attention."),
    ("Listening brief", "Say “listening brief for <topic>” to follow one topic across public posts."),
    ("Product demand", "Say “product demand for <topic>” to check whether people are asking for it."),
    ("Creator notes", "Say “creator notes for <handle>” to summarize one public creator's page."),
    ("Repurposing ideas", "Say “repurpose this post <YouTube link or topic>” to draft fresh post angles."),
)


def action_by_id(action_id: str) -> SearchAction:
    try:
        return _BY_ID[action_id]
    except KeyError as exc:
        raise SocialSearchError("That search is not one BabySitter offers.") from exc


def prepare(action_id: str, raw: str) -> PreparedSearch:
    action = action_by_id(action_id)
    value = _clean(action.kind, raw)
    params = {action.param: value} if action.param else {}
    query = urllib.parse.urlencode(params)
    url = API_ROOT + action.path + (("?" + query) if query else "")
    require_scrapecreators_url(url)
    if not action.path.startswith("/v1/") and not action.path.startswith("/v2/"):
        raise SocialSearchError("That search address is not allowed.")
    shown = value if value else "(nothing else)"
    ask = (
        f"BabySitter will ask ScrapeCreators to {action.summary}.\n\n"
        f"It will send this, and nothing else from your PC:\n{shown}\n\n"
        f"Address: {url}\n"
        "Your API key goes with the request. It is not shown here.\n"
        f"{action.note}\n\n"
        "ScrapeCreators is a separate company. This is public data only. "
        "Nothing is sent until you press Send this search."
    )
    return PreparedSearch(action.id, action.label, value, url, ask)


def perform(prepared: PreparedSearch, api_key: str, opener=urllib.request.urlopen) -> SearchOutcome:
    action = action_by_id(prepared.action_id)
    key = api_key.strip()
    if not key:
        raise SocialSearchError("Save an API key on the Tools tab first.")
    require_scrapecreators_url(prepared.url)
    if not prepared.url.startswith(API_ROOT + action.path):
        raise SocialSearchError("That search address is not allowed.")
    request = urllib.request.Request(prepared.url, method="GET")
    request.add_header("x-api-key", key)
    request.add_header("Accept", "application/json")
    try:
        with opener(request, timeout=action.timeout) as response:
            body = response.read(2_000_000)
    except urllib.error.HTTPError as exc:
        raw = exc.read(8000).decode("utf-8", "replace")
        raise SocialSearchError(_http_message(exc.code, raw, key)) from None
    except urllib.error.URLError:
        raise SocialSearchError(
            "ScrapeCreators could not be reached. Check your internet connection."
        ) from None
    except TimeoutError:
        raise SocialSearchError("ScrapeCreators took too long to answer.") from None
    text = redact(body.decode("utf-8", "replace"), key)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SocialSearchError(
            "ScrapeCreators sent something that was not a result."
        ) from exc
    if isinstance(payload, dict) and payload.get("success") is False:
        message = str(payload.get("message") or payload.get("error") or "The search was refused.")
        raise SocialSearchError(redact(message, key)[:400])
    if action.id == "credits":
        line = _credits_line(payload)
        return SearchOutcome(line, line)
    lines = summarize(payload)
    if not lines:
        snippet = text.strip().replace("\n", " ")[:600]
        lines = [
            "ScrapeCreators answered, but there was no public post to list.",
            snippet,
        ] if snippet else ["ScrapeCreators answered with nothing to show."]
    extra = ""
    if len(lines) >= 12:
        extra = "\nShowing the first 12."
    detail = "\n".join(lines) + extra
    spoken = f"Found {min(len(lines), 12)} public results for {action.label}."
    return SearchOutcome(spoken, detail)


def summarize(payload: object, limit: int = 12) -> list[str]:
    found: list[str] = []
    _walk(payload, found, 0)
    lines: list[str] = []
    seen: set[str] = set()
    for line in found:
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
        if len(lines) >= limit:
            break
    return lines


def redact(text: str, secret: str) -> str:
    if secret and secret in text:
        return text.replace(secret, "[key hidden]")
    return text


class SocialSearchTool:
    """Plugin shape the later voice brain can call. `run` is only after a yes."""

    id = "social-search"
    label = "Social search"

    def __init__(self, vault: KeyVault) -> None:
        self.vault = vault

    def describe(self, arguments: dict) -> str:
        prepared = prepare(str(arguments.get("action") or ""), str(arguments.get("text") or ""))
        return prepared.ask

    def run(self, arguments: dict) -> ToolResult:
        prepared = prepare(str(arguments.get("action") or ""), str(arguments.get("text") or ""))
        try:
            key = self.vault.load() or ""
        except SecretsError as exc:
            raise SocialSearchError(str(exc)) from exc
        outcome = perform(prepared, key)
        return ToolResult(spoken=outcome.spoken, detail=outcome.detail)


def _clean(kind: str, raw: str) -> str:
    text = (raw or "").strip()
    if kind == "none":
        return ""
    if not text:
        raise SocialSearchError("Type something to search for.")
    if len(text) > 300:
        raise SocialSearchError("That is too long. Shorten it and try again.")
    if kind == "handle":
        text = text[1:] if text.startswith("@") else text
        if not text or any(character in text for character in " /\\?#@"):
            raise SocialSearchError("Use the public name only, without @ or a web address.")
    elif kind == "hashtag":
        text = text[1:] if text.startswith("#") else text
        text = text.strip()
        if not text or any(character.isspace() for character in text):
            raise SocialSearchError("Use one hashtag, without the # and without spaces.")
    elif kind == "url":
        parsed = urllib.parse.urlsplit(text)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise SocialSearchError("Paste a full public link. It must start with https.")
        if parsed.username or parsed.password:
            raise SocialSearchError("Remove any login from that link before searching.")
    elif kind != "query":
        raise SocialSearchError("That search is not one BabySitter offers.")
    return text


def _http_message(code: int, body: str, key: str) -> str:
    if code in (401, 403):
        return "ScrapeCreators rejected the API key. Check the key on the Tools tab."
    if code == 402:
        return "ScrapeCreators says this account is out of credits."
    if code == 429:
        return "ScrapeCreators asked you to wait. Try again in a minute."
    cleaned = redact(body, key).replace("\n", " ").strip()[:240]
    if cleaned:
        return f"ScrapeCreators returned an error ({code}). {cleaned}"
    return f"ScrapeCreators returned an error ({code})."


def _credits_line(payload: object) -> str:
    found = _find_credit(payload, 0)
    if found is None:
        return "ScrapeCreators answered, but the credit number was not in the usual place."
    return f"Credits left: {found}"


def _find_credit(node: object, depth: int) -> str | None:
    if depth > 4 or not isinstance(node, dict):
        return None
    for key in ("credits", "credit", "balance", "creditCount", "credit_count", "remaining"):
        value = node.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(int(value)) if float(value).is_integer() else str(value)
        if isinstance(value, str) and value.strip():
            return value.strip()[:40]
    for value in node.values():
        if isinstance(value, dict):
            found = _find_credit(value, depth + 1)
            if found is not None:
                return found
    return None


def _walk(node: object, found: list[str], depth: int) -> None:
    if depth > 5 or len(found) > 40:
        return
    if isinstance(node, dict):
        line = _line_from(node)
        if line:
            found.append(line)
        for value in node.values():
            if isinstance(value, (dict, list)):
                _walk(value, found, depth + 1)
    elif isinstance(node, list):
        for item in node[:30]:
            _walk(item, found, depth + 1)


def _line_from(node: dict) -> str | None:
    text = _first_str(node, _TEXT_KEYS)
    url = _first_str(node, _URL_KEYS)
    who = _first_str(node, _WHO_KEYS)
    author = node.get("author")
    if who is None and isinstance(author, dict):
        who = _first_str(author, _WHO_KEYS + ("name",))
    if text is None and (url is None or not url.startswith("http")):
        return None
    parts: list[str] = []
    if who:
        parts.append(who[:80])
    if text:
        parts.append(" ".join(text.split())[:180])
    if url and url.startswith("http"):
        parts.append(url[:300])
    if not parts:
        return None
    return " — ".join(parts)


def _first_str(node: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = node.get(key)
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                return cleaned
    return None
