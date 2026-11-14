"""Read the user's own Gmail and Calendar.

Off until they turn it on and save a token. BabySitter only sends GET.
It does not send mail and it does not delete mail. The token is not written
into settings.json and is not put in an error message.
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from babysitter.paths import google_token_path
from babysitter.secrets import SecretsError, protect_blob, unprotect_blob
from babysitter.security import require_google_url


GMAIL_LIST_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages?q=is%3Aunread&maxResults=5"
GMAIL_GET_PREFIX = "https://gmail.googleapis.com/gmail/v1/users/me/messages/"
CALENDAR_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
_TOKEN_DESCRIPTION = "BabySitter Google token"


class GoogleError(Exception):
    """Google could not be read. The message never includes the token."""


def normalize_google_token(raw: str) -> str:
    token = raw.strip()
    if not token or any(character in token for character in "\r\n\t "):
        raise SecretsError("Paste the token as one line, with no spaces.")
    if len(token) < 20 or len(token) > 4096:
        raise SecretsError("That does not look like a Google token.")
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~+/=")
    if any(character not in allowed for character in token):
        raise SecretsError("That does not look like a Google token.")
    return token


def _safe_id(value: str) -> bool:
    if not value or len(value) > 128:
        return False
    return all(character.isalnum() or character in "-_" for character in value)


def subject_of(message: dict) -> str:
    payload = message.get("payload") if isinstance(message, dict) else None
    headers = payload.get("headers") if isinstance(payload, dict) else None
    for header in headers or []:
        if not isinstance(header, dict):
            continue
        if str(header.get("name") or "").lower() == "subject":
            return str(header.get("value") or "(no subject)")[:120]
    return "(no subject)"


def unread_speech(subjects: list[str], extra: int = 0) -> str:
    clean = [subject.strip() for subject in subjects if subject and subject.strip()]
    if not clean:
        return "No unread mail."
    speech = "Unread mail: " + "; ".join(clean[:3]) + "."
    if extra > 0:
        speech += f" {extra} more unread."
    return speech


def event_lines(payload: dict) -> list[str]:
    items = payload.get("items") if isinstance(payload, dict) else None
    lines: list[str] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary") or "Busy")[:80]
        start = item.get("start") if isinstance(item.get("start"), dict) else {}
        when = str(start.get("dateTime") or start.get("date") or "")
        lines.append(f"{summary} at {when}" if when else summary)
        if len(lines) == 5:
            break
    return lines


def calendar_speech(lines: list[str]) -> str:
    if not lines:
        return "Nothing coming up on the calendar."
    return "Coming up: " + ". ".join(lines[:3]) + "."


def calendar_request_url(now: datetime) -> str:
    stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    query = urllib.parse.urlencode(
        {
            "maxResults": "5",
            "singleEvents": "true",
            "orderBy": "startTime",
            "timeMin": stamp,
        }
    )
    return CALENDAR_URL + "?" + query


def http_get_json(url: str, token: str, opener=None) -> dict:
    """GET one allowlisted Google URL. The token stays in the header."""
    require_google_url(url)
    if not token or any(character.isspace() for character in token):
        raise GoogleError("There is no Google token saved.")
    request = urllib.request.Request(url, method="GET")
    request.add_header("Authorization", "Bearer " + token)
    request.add_header("Accept", "application/json")
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=8) as response:
            raw = response.read(200_000)
            status = getattr(response, "status", 200)
    except GoogleError:
        raise
    except Exception:
        raise GoogleError("Google did not answer. Mail and the calendar were not changed.")
    if int(status) >= 400:
        raise GoogleError("Google refused the read. Mail and the calendar were not changed.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GoogleError("Google sent something BabySitter could not read. Nothing was changed.") from exc
    if not isinstance(payload, dict):
        raise GoogleError("Google sent something BabySitter could not read. Nothing was changed.")
    return payload


class GoogleReader:
    def __init__(self, token: str, fetch=http_get_json, now: datetime | None = None) -> None:
        self._token = token
        self._fetch = fetch
        self._now = now or datetime.now(timezone.utc)

    def unread(self) -> str:
        listing = self._fetch(GMAIL_LIST_URL, self._token)
        messages = listing.get("messages") if isinstance(listing, dict) else None
        if not isinstance(messages, list) or not messages:
            return "No unread mail."
        subjects: list[str] = []
        for item in messages[:3]:
            if not isinstance(item, dict):
                continue
            message_id = str(item.get("id") or "")
            if not _safe_id(message_id):
                continue
            detail = self._fetch(
                GMAIL_GET_PREFIX + message_id + "?format=metadata&metadataHeaders=Subject",
                self._token,
            )
            subjects.append(subject_of(detail))
        extra = max(0, len(messages) - len(subjects))
        return unread_speech(subjects, extra)

    def upcoming(self) -> str:
        payload = self._fetch(calendar_request_url(self._now), self._token)
        return calendar_speech(event_lines(payload))


class MemoryGoogleVault:
    """In-memory stand-in used by tests. It does not touch the disk."""

    def __init__(self) -> None:
        self._token: str | None = None

    @property
    def available(self) -> bool:
        return True

    def has_token(self) -> bool:
        return bool(self._token)

    def save(self, raw: str) -> None:
        self._token = normalize_google_token(raw)

    def load(self) -> str | None:
        return self._token

    def delete(self) -> None:
        self._token = None


class DpapiGoogleVault:
    """Windows DPAPI file, separate from the ScrapeCreators key."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or google_token_path()

    @property
    def available(self) -> bool:
        return sys.platform == "win32"

    def has_token(self) -> bool:
        return self.path.is_file() and self.path.stat().st_size > 0

    def save(self, raw: str) -> None:
        token = normalize_google_token(raw)
        if not self.available:
            raise SecretsError(
                "Saving the Google token needs Windows. On your PC it is encrypted "
                "for your Windows user only, with DPAPI."
            )
        blob = protect_blob(token.encode("utf-8"), _TOKEN_DESCRIPTION)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".dpapi.tmp")
        temporary.write_bytes(blob)
        temporary.replace(self.path)

    def load(self) -> str | None:
        if not self.has_token():
            return None
        if not self.available:
            raise SecretsError("This computer cannot read a Windows-encrypted token.")
        try:
            raw = unprotect_blob(self.path.read_bytes())
        except OSError as exc:
            raise SecretsError(
                "Windows could not read the saved token. Delete it and save it again."
            ) from exc
        try:
            return normalize_google_token(raw.decode("utf-8"))
        except (UnicodeError, SecretsError) as exc:
            raise SecretsError(
                "The saved token was unreadable. Delete it and save it again."
            ) from exc

    def delete(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise SecretsError("The saved token could not be deleted.") from exc


def default_google_vault() -> DpapiGoogleVault:
    return DpapiGoogleVault()
