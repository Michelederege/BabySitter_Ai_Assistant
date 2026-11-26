"""Read a Blackboard calendar feed and show the events.

Blackboard does not give a desktop app one address that works at every
school. The feed each student can copy from Blackboard's calendar is a
normal https link. BabySitter only reads it. It does not sign in to
Blackboard and it does not change courses.
"""

from __future__ import annotations

import ipaddress
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from babysitter.paths import blackboard_feed_path
from babysitter.secrets import SecretsError, protect_blob, unprotect_blob


class FeedError(Exception):
    """The Blackboard feed could not be read."""


def require_feed_url(url: str) -> str:
    """Https only, a public host name, and a calendar-shaped path."""
    parsed = urllib.parse.urlsplit((url or "").strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    path = (parsed.path or "").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise FeedError("The Blackboard link has to be an https address from your school.")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local") or host.endswith(".internal"):
        raise FeedError("That Blackboard link points at this computer. Nothing was fetched.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise FeedError("Use the school's web name, not a numeric address. Nothing was fetched.")
    if not any(character.isalpha() for character in host):
        raise FeedError("Use the school's web name, not a numeric address. Nothing was fetched.")
    calendar_shaped = path.endswith(".ics") or "calendar" in path or "webapps" in path or "/learn/" in path
    if not calendar_shaped:
        raise FeedError(
            "That link does not look like a Blackboard calendar feed. "
            "In Blackboard, open the calendar and copy the external calendar link."
        )
    return urllib.parse.urlunsplit(parsed)


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _stamp(value: str) -> str:
    """The event's day on this PC's calendar, as YYYYMMDD.

    A time that ends in Z is in UTC, so 02:00Z on the 27th is still the
    evening of the 26th in New York. Any other time is already local.
    """
    raw = (value or "").rsplit(":", 1)[-1].strip()
    if raw.upper().endswith("Z"):
        try:
            moment = datetime.strptime(raw.upper(), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            moment = None
        if moment is not None:
            return moment.astimezone().strftime("%Y%m%d")
    digits = "".join(character for character in raw if character.isdigit())
    return digits[:8]


def events_from_ics(text: str, today: datetime | None = None, limit: int = 8) -> list[tuple[str, str]]:
    """Upcoming events as (summary, when). A feed with no events is an empty list."""
    moment = today or datetime.now(timezone.utc)
    # Today on this PC's calendar. In UTC, the evening is already
    # tomorrow, and that hid the rest of today's events.
    floor = moment.astimezone().strftime("%Y%m%d")
    found: list[tuple[str, str, str]] = []
    summary = ""
    when = ""
    inside = False
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            inside = True
            summary = ""
            when = ""
            continue
        if line == "END:VEVENT":
            if inside and summary.strip():
                found.append((_stamp(when), summary.strip()[:80], when.strip()[:40]))
            inside = False
            continue
        if not inside:
            continue
        if line.startswith("SUMMARY"):
            summary = line.split(":", 1)[-1].replace("\\,", ",").replace("\\n", " ")
        elif line.startswith("DTSTART"):
            when = line.split(":", 1)[-1]
    upcoming = [item for item in found if not item[0] or item[0] >= floor]
    upcoming.sort(key=lambda item: item[0] or "99999999")
    return [(summary, when) for _stamp_value, summary, when in upcoming[:limit]]


def blackboard_speech(events: list[tuple[str, str]]) -> str:
    if not events:
        return "Nothing coming up on Blackboard."
    names = [summary for summary, _when in events[:3]]
    return "Blackboard: " + ", ".join(names) + "."


def blackboard_rows(events: list[tuple[str, str]]) -> list[str]:
    rows: list[str] = []
    for summary, when in events:
        rows.append(f"Blackboard · {summary}" + (f" · {when}" if when else ""))
    return rows


def fetch_feed(url: str, opener=None, limit: int = 1_000_000) -> str:
    """GET one checked https feed. Redirects are checked again."""
    checked = require_feed_url(url)

    class _Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            require_feed_url(newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    open_url = opener
    if open_url is None:
        open_url = urllib.request.build_opener(_Redirect).open
    request = urllib.request.Request(checked, method="GET", headers={"User-Agent": "BabySitter", "Accept": "text/calendar"})
    try:
        with open_url(request, timeout=12) as response:
            raw = response.read(limit + 1)
    except FeedError:
        raise
    except Exception as exc:
        raise FeedError("Blackboard did not answer. Nothing was changed.") from exc
    if len(raw) > limit:
        raise FeedError("That Blackboard feed was larger than expected. Nothing was kept.")
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception as exc:
        raise FeedError("Blackboard sent something BabySitter could not read.") from exc


class MemoryFeedVault:
    """In-memory stand-in. The feed link is not a Google token."""

    def __init__(self) -> None:
        self._url = ""

    @property
    def available(self) -> bool:
        return True

    def has_feed(self) -> bool:
        return bool(self._url)

    def save(self, url: str) -> None:
        self._url = require_feed_url(url)

    def load(self) -> str | None:
        return self._url or None

    def delete(self) -> None:
        self._url = ""


class DpapiFeedVault:
    """The calendar link can contain a secret, so it stays out of settings.json."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or blackboard_feed_path()

    @property
    def available(self) -> bool:
        return sys.platform == "win32"

    def has_feed(self) -> bool:
        return self.path.is_file() and self.path.stat().st_size > 0

    def save(self, url: str) -> None:
        checked = require_feed_url(url)
        if not self.available:
            raise SecretsError("Saving the Blackboard link needs Windows.")
        blob = protect_blob(checked.encode("utf-8"), "BabySitter Blackboard feed")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".dpapi.tmp")
        temporary.write_bytes(blob)
        temporary.replace(self.path)

    def load(self) -> str | None:
        if not self.has_feed():
            return None
        if not self.available:
            raise SecretsError("This computer cannot read a Windows-encrypted Blackboard link.")
        try:
            raw = unprotect_blob(self.path.read_bytes()).decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise SecretsError("The saved Blackboard link could not be read. Save it again.") from exc
        return require_feed_url(raw)

    def delete(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise SecretsError("The Blackboard link could not be deleted.") from exc


def default_feed_vault() -> DpapiFeedVault:
    return DpapiFeedVault()
