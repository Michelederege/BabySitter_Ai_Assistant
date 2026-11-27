"""Read Outlook mail, the Outlook calendar, and OneDrive file names.

Works for a personal Outlook.com / Hotmail account and for a work or
school Microsoft 365 account (a school may have to approve the app).
BabySitter only sends GET requests to Microsoft Graph: it never sends,
moves, or deletes mail, and never changes the calendar or a file.

Sign-in is Microsoft's own page in your browser, with PKCE and no client
secret, which Microsoft allows for a desktop app. The token is encrypted
with Windows' DPAPI in its own file, never in settings.json or the log.
You register the app once, for free, in your own Microsoft account; the
steps are in Settings, Accounts and home.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets as _secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from babysitter.secrets import SecretsError, protect_blob, unprotect_blob

AUTH_ENDPOINT = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
TOKEN_ENDPOINT = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
# Register "http://localhost" as a "Mobile and desktop applications" redirect.
# Microsoft ignores the port for localhost, so this one listener works.
REDIRECT_URI = "http://localhost:8765/babysitter"
SCOPES = "offline_access User.Read Mail.Read Calendars.Read Files.Read"
GRAPH = "https://graph.microsoft.com/v1.0/me/"


class MicrosoftError(Exception):
    """Microsoft could not be read. The message never includes the token."""


def clean_client_id(value: str) -> str:
    """An Application (client) ID is a GUID like 0a1b2c3d-…."""
    text = (value or "").strip().lower()
    parts = text.split("-")
    if len(text) != 36 or [len(part) for part in parts] != [8, 4, 4, 4, 12] or any(
        character not in "0123456789abcdef-" for character in text
    ):
        raise SecretsError("Paste the Application (client) ID from your app registration. It looks like 0a1b2c3d-1234-….")
    return text


def _clean_token(raw: str) -> str:
    token = (raw or "").strip()
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~+/=*!$")
    if not 20 <= len(token) <= 16384 or any(character not in allowed for character in token):
        raise SecretsError("Microsoft sent a token BabySitter will not keep.")
    return token


def require_microsoft_url(url: str) -> None:
    """Graph reads of your own mail, calendar, and files, and the sign-in pages. Nothing else."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise MicrosoftError("That Microsoft address is not allowed.")
    host, path = (parsed.hostname or "").lower(), parsed.path or ""
    if host == "graph.microsoft.com" and path.startswith("/v1.0/me/"):
        reads = ("/v1.0/me/mailFolders/inbox/messages", "/v1.0/me/calendarView", "/v1.0/me/drive/recent")
        if any(path.startswith(prefix) for prefix in reads):
            return
    if host == "login.microsoftonline.com" and path in {"/common/oauth2/v2.0/authorize", "/common/oauth2/v2.0/token"}:
        return
    raise MicrosoftError("Outlook, the calendar, and OneDrive only use the read-only addresses.")


def pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(_secrets.token_bytes(48)).decode("ascii").rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    return verifier, challenge


def authorization_url(client_id: str, state: str, challenge: str) -> str:
    query = urllib.parse.urlencode({
        "client_id": clean_client_id(client_id),
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "response_mode": "query",
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    })
    url = AUTH_ENDPOINT + "?" + query
    require_microsoft_url(url)
    return url


def parse_token_payload(payload: dict, now: float | None = None) -> dict:
    if not isinstance(payload, dict) or payload.get("error"):
        detail = str(payload.get("error_description") or "") if isinstance(payload, dict) else ""
        if "AADSTS65001" in detail or "consent" in detail.lower():
            raise MicrosoftError("Your school has to approve BabySitter before it can read this account. Nothing was saved.")
        raise MicrosoftError("Microsoft refused the sign-in. Nothing was saved.")
    try:
        access = _clean_token(str(payload.get("access_token") or ""))
        refresh = str(payload.get("refresh_token") or "")
        refresh = _clean_token(refresh) if refresh else ""
    except SecretsError as exc:
        raise MicrosoftError(str(exc)) from None
    try:
        expires = int(payload.get("expires_in") or 3600)
    except (TypeError, ValueError):
        expires = 3600
    moment = time.time() if now is None else now
    return {"access_token": access, "refresh_token": refresh, "expires_at": int(moment) + max(60, expires)}


def _post_token(fields: dict, opener=None) -> dict:
    require_microsoft_url(TOKEN_ENDPOINT)
    body = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(TOKEN_ENDPOINT, data=body, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=12) as response:
            raw = response.read(200_000)
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read(200_000)
        except Exception:
            raise MicrosoftError("Microsoft did not finish sign-in. Nothing was saved.") from None
    except Exception as exc:
        raise MicrosoftError("Microsoft did not finish sign-in. Nothing was saved.") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise MicrosoftError("Microsoft sent something BabySitter could not read. Nothing was saved.") from exc
    return parse_token_payload(payload)


def exchange_code(client_id: str, code: str, verifier: str, opener=None) -> dict:
    return _post_token({
        "client_id": clean_client_id(client_id),
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
        "scope": SCOPES,
    }, opener)


def refresh_access(client_id: str, refresh_token: str, opener=None) -> dict:
    kept = _clean_token(refresh_token)
    parsed = _post_token({
        "client_id": clean_client_id(client_id),
        "grant_type": "refresh_token",
        "refresh_token": kept,
        "scope": SCOPES,
    }, opener)
    if not parsed.get("refresh_token"):
        parsed["refresh_token"] = kept
    return parsed


def http_get_json(url: str, token: str, opener=None) -> dict:
    """GET one allowlisted Graph URL. The token stays in the header."""
    require_microsoft_url(url)
    request = urllib.request.Request(url, method="GET")
    request.add_header("Authorization", "Bearer " + token)
    request.add_header("Accept", "application/json")
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=10) as response:
            raw = response.read(400_000)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise MicrosoftError("The Microsoft sign-in expired. Sign in again on Accounts and home.") from None
        raise MicrosoftError("Microsoft refused the read. Nothing was changed.") from None
    except Exception as exc:
        raise MicrosoftError("Microsoft did not answer. Nothing was changed.") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise MicrosoftError("Microsoft sent something BabySitter could not read. Nothing was changed.") from exc
    if not isinstance(payload, dict):
        raise MicrosoftError("Microsoft sent something BabySitter could not read. Nothing was changed.")
    return payload


MAIL_URL = GRAPH + "mailFolders/inbox/messages?" + urllib.parse.urlencode(
    {"$filter": "isRead eq false", "$top": "8", "$select": "id,subject,from,receivedDateTime"}
)
FILES_URL = GRAPH + "drive/recent?" + urllib.parse.urlencode({"$top": "8"})


def calendar_url(now: datetime) -> str:
    start = now.astimezone(timezone.utc)
    return GRAPH + "calendarView?" + urllib.parse.urlencode({
        "startDateTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endDateTime": (start + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "$top": "8",
        "$orderby": "start/dateTime",
        "$select": "id,subject,start,location",
    })


def _sender(message: dict) -> str:
    address = (message.get("from") or {}).get("emailAddress") or {}
    return str(address.get("name") or address.get("address") or "Unknown")[:60]


def read_outlook(token: str, fetch=http_get_json, now: datetime | None = None) -> tuple[list[str], list[str], list[str]]:
    """Rows, short speeches, and problems, like the Google read. One failed part does not hide the others."""
    rows: list[str] = []
    speeches: list[str] = []
    problems: list[str] = []
    moment = now or datetime.now(timezone.utc)
    try:
        mail = [item for item in fetch(MAIL_URL, token).get("value") or [] if isinstance(item, dict)]
        subjects = [str(item.get("subject") or "(no subject)")[:120] for item in mail]
        rows.extend(f"Outlook · {_sender(item)} · {subject}" for item, subject in zip(mail, subjects))
        speeches.append("Unread Outlook mail: " + "; ".join(subjects[:3]) + "." if subjects else "No unread Outlook mail.")
    except MicrosoftError as exc:
        problems.append(f"Outlook: {exc}")
        rows.append("Outlook · could not be read")
    try:
        events = [item for item in fetch(calendar_url(moment), token).get("value") or [] if isinstance(item, dict)]
        titles = [str(item.get("subject") or "Busy")[:80] for item in events]
        for item, title in zip(events, titles):
            when = str((item.get("start") or {}).get("dateTime") or "")[:16].replace("T", " ")
            rows.append(f"Outlook calendar · {title}" + (f" · {when}" if when else ""))
        speeches.append("Outlook calendar: " + ". ".join(titles[:3]) + "." if titles else "Nothing coming up on the Outlook calendar.")
    except MicrosoftError as exc:
        problems.append(f"Outlook calendar: {exc}")
        rows.append("Outlook calendar · could not be read")
    try:
        files = [item for item in fetch(FILES_URL, token).get("value") or [] if isinstance(item, dict)]
        names = [str(item.get("name") or "Untitled")[:80] for item in files]
        rows.extend(f"OneDrive · {name}" for name in names)
        if names:
            speeches.append("OneDrive: " + ", ".join(names[:3]) + ".")
    except MicrosoftError as exc:
        problems.append(f"OneDrive: {exc}")
        rows.append("OneDrive · could not be read")
    return rows, speeches, problems


def outlook_index(token: str, fetch=http_get_json, now: datetime | None = None) -> tuple[list[str], list[str]]:
    """Ids and titles of unread mail and coming events, for "what is new"."""
    ids: list[str] = []
    titles: list[str] = []
    for url in (MAIL_URL, calendar_url(now or datetime.now(timezone.utc))):
        try:
            items = [item for item in fetch(url, token).get("value") or [] if isinstance(item, dict)]
        except MicrosoftError:
            continue
        for item in items:
            if item.get("id"):
                ids.append(str(item["id"])[:200])
                titles.append(str(item.get("subject") or "Outlook item")[:80])
    return ids, titles


class MicrosoftVault:
    """The Microsoft token, encrypted with DPAPI, in its own file."""

    def __init__(self, path: Path | None = None) -> None:
        from babysitter.paths import secrets_dir

        self.path = path or secrets_dir() / "microsoft.dpapi"

    @property
    def available(self) -> bool:
        return sys.platform == "win32"

    def has_token(self) -> bool:
        return self.path.is_file() and self.path.stat().st_size > 0

    def save_bundle(self, bundle: dict) -> None:
        if not self.available:
            raise SecretsError("Saving the Microsoft sign-in needs Windows.")
        data = json.dumps({
            "access_token": _clean_token(str(bundle.get("access_token") or "")),
            "refresh_token": str(bundle.get("refresh_token") or ""),
            "expires_at": int(bundle.get("expires_at") or 0),
        }).encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_bytes(protect_blob(data, "BabySitter Microsoft sign-in"))
        temporary.replace(self.path)

    def load_bundle(self) -> dict | None:
        if not self.has_token():
            return None
        try:
            payload = json.loads(unprotect_blob(self.path.read_bytes()).decode("utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise SecretsError("The saved Microsoft sign-in could not be read. Sign in again.") from exc
        return payload if isinstance(payload, dict) else None

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)
