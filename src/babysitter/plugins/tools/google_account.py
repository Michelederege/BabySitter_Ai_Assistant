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
GMAIL_VIEW_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages?q=is%3Aunread&maxResults=8"
GMAIL_GET_PREFIX = "https://gmail.googleapis.com/gmail/v1/users/me/messages/"
GMAIL_META = "?format=metadata&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date"
CALENDAR_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
DRIVE_LIST_URL = (
    "https://www.googleapis.com/drive/v3/files"
    "?pageSize=8&orderBy=modifiedTime%20desc&q=trashed%3Dfalse"
    "&fields=files(id,name,modifiedTime)"
)
DOCS_LIST_URL = "https://www.googleapis.com/drive/v3/files"
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


def header_of(message: dict, name: str, fallback: str = "") -> str:
    payload = message.get("payload") if isinstance(message, dict) else None
    headers = payload.get("headers") if isinstance(payload, dict) else None
    wanted = name.lower()
    for header in headers or []:
        if not isinstance(header, dict):
            continue
        if str(header.get("name") or "").lower() == wanted:
            return str(header.get("value") or fallback)[:120]
    return fallback


def subject_of(message: dict) -> str:
    return header_of(message, "Subject", "(no subject)") or "(no subject)"


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


def docs_list_url() -> str:
    """Recent Google Docs only. Names and times, not the document body."""
    query = urllib.parse.urlencode(
        {
            "pageSize": "10",
            "orderBy": "modifiedTime desc",
            "q": "mimeType='application/vnd.google-apps.document' and trashed=false",
            "fields": "files(id,name,modifiedTime,mimeType)",
        }
    )
    return DOCS_LIST_URL + "?" + query


def doc_export_url(file_id: str) -> str:
    """Plain text of one Google Doc. Other formats are refused."""
    if not _safe_id(file_id):
        raise GoogleError("That Google Doc could not be read.")
    # /export is the plain text of the document. Without it, Drive answers
    # with the file's details (its id, name, and type) as JSON instead.
    return "https://www.googleapis.com/drive/v3/files/" + file_id + "/export?mimeType=text/plain"


def http_get_text(url: str, token: str, opener=None, limit: int = 80_000) -> str:
    """GET one allowlisted Google Doc as text. The token stays in the header."""
    require_google_url(url)
    if not token or any(character.isspace() for character in token):
        raise GoogleError("There is no Google token saved.")
    request = urllib.request.Request(url, method="GET")
    request.add_header("Authorization", "Bearer " + token)
    request.add_header("Accept", "text/plain")
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=12) as response:
            raw = response.read(limit + 1)
            status = getattr(response, "status", 200)
    except GoogleError:
        raise
    except Exception as exc:
        raise GoogleError("The Google Doc could not be read. Nothing was changed.") from exc
    if int(status) >= 400:
        raise GoogleError("Google refused the document. Nothing was changed.")
    text = raw[:limit].decode("utf-8", errors="replace")
    if token in text:
        raise GoogleError("The Google Doc could not be shown.")
    return text


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

    def mail_index(self) -> tuple[list[str], list[str]]:
        listing = self._fetch(GMAIL_LIST_URL, self._token)
        messages = listing.get("messages") if isinstance(listing, dict) else None
        ids: list[str] = []
        subjects: list[str] = []
        for item in (messages or [])[:5]:
            if not isinstance(item, dict):
                continue
            message_id = str(item.get("id") or "")
            if not _safe_id(message_id):
                continue
            detail = self._fetch(
                GMAIL_GET_PREFIX + message_id + "?format=metadata&metadataHeaders=Subject",
                self._token,
            )
            ids.append(message_id)
            subjects.append(subject_of(detail))
        return ids, subjects

    def mail_view(self, prefix: str = "Mail") -> tuple[list[str], str]:
        listing = self._fetch(GMAIL_VIEW_URL, self._token)
        messages = listing.get("messages") if isinstance(listing, dict) else None
        if not isinstance(messages, list) or not messages:
            return [], "No unread mail." if prefix == "Mail" else f"No unread {prefix.lower()}."
        rows: list[str] = []
        subjects: list[str] = []
        for item in messages[:8]:
            if not isinstance(item, dict):
                continue
            message_id = str(item.get("id") or "")
            if not _safe_id(message_id):
                continue
            detail = self._fetch(GMAIL_GET_PREFIX + message_id + GMAIL_META, self._token)
            subject = subject_of(detail)
            sender = header_of(detail, "From", "Unknown")
            when = header_of(detail, "Date", "")
            subjects.append(subject)
            shown = f"{prefix} · {sender} · {subject}"
            if when:
                shown += f" · {when[:32]}"
            rows.append(shown)
        extra = max(0, len(messages) - len(subjects))
        label = "Unread mail" if prefix == "Mail" else f"Unread {prefix.lower()}"
        speech = unread_speech(subjects, extra).replace("Unread mail", label, 1)
        return rows, speech

    def calendar_view(self, prefix: str = "Calendar") -> tuple[list[str], str]:
        payload = self._fetch(calendar_request_url(self._now), self._token)
        items = payload.get("items") if isinstance(payload, dict) else None
        rows: list[str] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            summary = str(item.get("summary") or "Busy")[:80]
            start = item.get("start") if isinstance(item.get("start"), dict) else {}
            when = str(start.get("dateTime") or start.get("date") or "")
            where = str(item.get("location") or "")[:60]
            shown = f"{prefix} · {summary}"
            if when:
                shown += f" · {when}"
            if where:
                shown += f" · {where}"
            rows.append(shown)
            if len(rows) == 8:
                break
        speech = calendar_speech(event_lines(payload))
        if prefix != "Calendar":
            speech = speech.replace("Coming up", prefix, 1).replace("Nothing coming up on the calendar.", f"Nothing coming up on {prefix}.")
        return rows, speech

    def drive_view(self, prefix: str = "Drive") -> tuple[list[str], str]:
        payload = self._fetch(DRIVE_LIST_URL, self._token)
        files = payload.get("files") if isinstance(payload, dict) else None
        rows: list[str] = []
        names: list[str] = []
        for item in files or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "Untitled")[:80]
            when = str(item.get("modifiedTime") or "")[:16].replace("T", " ")
            names.append(name)
            rows.append(f"{prefix} · {name}" + (f" · {when}" if when else ""))
            if len(rows) == 8:
                break
        if not names:
            return [], f"No files in {prefix}."
        return rows, f"{prefix}: " + ", ".join(names[:3]) + "."

    def event_index(self) -> tuple[list[str], list[str]]:
        payload = self._fetch(calendar_request_url(self._now), self._token)
        items = payload.get("items") if isinstance(payload, dict) else None
        ids: list[str] = []
        titles: list[str] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            title = str(item.get("summary") or "Busy")[:80]
            item_id = str(item.get("id") or title)
            if not item_id or any(character.isspace() for character in item_id):
                continue
            ids.append(item_id[:200])
            titles.append(title)
            if len(ids) == 5:
                break
        return ids, titles


def read_account(
    token: str,
    *,
    mail_prefix: str,
    calendar_prefix: str,
    drive_prefix: str,
    fetch=http_get_json,
) -> tuple[list[str], list[str], list[str]]:
    """Rows, short speeches, and problems. One failed read does not hide the others."""
    reader = GoogleReader(token, fetch)
    rows: list[str] = []
    speeches: list[str] = []
    problems: list[str] = []
    calls = (
        (mail_prefix, lambda: reader.mail_view(mail_prefix)),
        (calendar_prefix, lambda: reader.calendar_view(calendar_prefix)),
        (drive_prefix, lambda: reader.drive_view(drive_prefix)),
    )
    for label, call in calls:
        try:
            found, speech = call()
        except GoogleError as exc:
            problems.append(f"{label}: {exc}")
            rows.append(f"{label} · could not be read")
            continue
        rows.extend(found)
        if speech:
            speeches.append(speech)
    return rows, speeches, problems


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
        bundle = self.load_bundle()
        if bundle is None:
            return None
        return bundle.get("access_token") or None

    def load_bundle(self) -> dict | None:
        if not self._token:
            return None
        return bundle_from_saved(self._token)

    def save_bundle(self, bundle: dict) -> None:
        self._token = bundle_text(bundle)

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
        bundle = self.load_bundle()
        if bundle is None:
            return None
        return bundle.get("access_token") or None

    def load_bundle(self) -> dict | None:
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
            return bundle_from_saved(raw.decode("utf-8"))
        except (UnicodeError, SecretsError, json.JSONDecodeError) as exc:
            raise SecretsError(
                "The saved token was unreadable. Delete it and save it again."
            ) from exc

    def save_bundle(self, bundle: dict) -> None:
        text = bundle_text(bundle)
        if not self.available:
            raise SecretsError(
                "Saving the Google token needs Windows. On your PC it is encrypted "
                "for your Windows user only, with DPAPI."
            )
        blob = protect_blob(text.encode("utf-8"), _TOKEN_DESCRIPTION)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".dpapi.tmp")
        temporary.write_bytes(blob)
        temporary.replace(self.path)

    def delete(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise SecretsError("The saved token could not be deleted.") from exc


def default_google_vault() -> DpapiGoogleVault:
    return DpapiGoogleVault()


AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REDIRECT_URI = "http://127.0.0.1:8765/babysitter"
READONLY_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly "
    "https://www.googleapis.com/auth/calendar.readonly "
    "https://www.googleapis.com/auth/drive.readonly"
)


def clean_client_id(value: str) -> str:
    text = (value or "").strip()
    if not text or any(character.isspace() for character in text) or len(text) < 10 or len(text) > 200:
        raise SecretsError("Paste the OAuth client id from your own Google Cloud desktop client.")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-")
    if any(character not in allowed for character in text):
        raise SecretsError("That does not look like a Google OAuth client id.")
    return text


def clean_client_secret(value: str) -> str:
    text = (value or "").strip()
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    if not 10 <= len(text) <= 200 or any(character not in allowed for character in text):
        raise SecretsError("That does not look like a Google client secret.")
    return text


def client_from_file(path) -> tuple[str, str]:
    """The id and secret from the client file Google downloads for a Desktop app."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise SecretsError("That file could not be read. Choose the client_secret_….json file Google gave you.") from exc
    block = raw.get("installed") if isinstance(raw, dict) else None
    if not isinstance(block, dict):
        if isinstance(raw, dict) and isinstance(raw.get("web"), dict):
            raise SecretsError("That is a Web client. In Google Cloud, create a client of type Desktop app instead.")
        raise SecretsError("That is not a Google client file. Choose the client_secret_….json file for a Desktop app.")
    return clean_client_id(str(block.get("client_id") or "")), clean_client_secret(str(block.get("client_secret") or ""))


class ClientSecretStore:
    """The Desktop client's secret, encrypted with Windows' DPAPI, out of settings.json."""

    def __init__(self, path: Path | None = None) -> None:
        from babysitter.paths import google_client_secret_path

        self.path = path or google_client_secret_path()

    def save(self, secret: str) -> None:
        cleaned = clean_client_secret(secret)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = protect_blob(cleaned.encode("utf-8"), "BabySitter Google client") if sys.platform == "win32" else cleaned.encode("utf-8")
        temporary = self.path.with_suffix(".tmp")
        temporary.write_bytes(data)
        temporary.replace(self.path)

    def load(self) -> str:
        try:
            data = self.path.read_bytes()
        except OSError:
            return ""
        try:
            raw = unprotect_blob(data) if sys.platform == "win32" else data
            return clean_client_secret(raw.decode("utf-8"))
        except (OSError, UnicodeError, SecretsError):
            return ""


def bundle_text(bundle: dict) -> str:
    access = normalize_google_token(str(bundle.get("access_token") or ""))
    refresh = str(bundle.get("refresh_token") or "")
    if refresh:
        refresh = normalize_google_token(refresh)
    payload = {
        "access_token": access,
        "refresh_token": refresh,
        "expires_at": int(bundle.get("expires_at") or 0),
    }
    return json.dumps(payload, separators=(",", ":"))


def bundle_from_saved(text: str) -> dict:
    raw = (text or "").strip()
    if raw.startswith("{"):
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise SecretsError("The saved token was unreadable.")
        return {
            "access_token": normalize_google_token(str(payload.get("access_token") or "")),
            "refresh_token": normalize_google_token(str(payload["refresh_token"])) if payload.get("refresh_token") else "",
            "expires_at": int(payload.get("expires_at") or 0),
        }
    return {"access_token": normalize_google_token(raw), "refresh_token": "", "expires_at": 0}


def pkce_pair() -> tuple[str, str]:
    import base64
    import hashlib
    import secrets as secret_source

    verifier = secret_source.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def authorization_url(client_id: str, state: str, challenge: str, prompt: str = "consent") -> str:
    from babysitter.security import require_google_oauth_url

    require_google_oauth_url(AUTH_ENDPOINT)
    query = urllib.parse.urlencode(
        {
            "client_id": clean_client_id(client_id),
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": READONLY_SCOPES,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": prompt or "consent",
        }
    )
    return AUTH_ENDPOINT + "?" + query


def code_from_redirect(path: str, expected_state: str) -> str:
    parsed = urllib.parse.urlsplit(path if "://" in path else "http://127.0.0.1" + path)
    query = urllib.parse.parse_qs(parsed.query)
    if (query.get("state") or [""])[0] != expected_state:
        raise GoogleError("Google sign-in did not match. Nothing was saved.")
    if query.get("error"):
        raise GoogleError("Google sign-in was cancelled. Nothing was saved.")
    code = (query.get("code") or [""])[0]
    if not code or len(code) > 512 or any(character.isspace() for character in code):
        raise GoogleError("Google did not return a sign-in code. Nothing was saved.")
    return code


def parse_token_payload(payload: dict, now: float | None = None) -> dict:
    import time

    if not isinstance(payload, dict) or payload.get("error"):
        raise GoogleError("Google refused the sign-in. Nothing was saved.")
    moment = time.time() if now is None else now
    access = normalize_google_token(str(payload.get("access_token") or ""))
    refresh = str(payload.get("refresh_token") or "")
    if refresh:
        refresh = normalize_google_token(refresh)
    try:
        expires = int(payload.get("expires_in") or 3600)
    except (TypeError, ValueError):
        expires = 3600
    return {"access_token": access, "refresh_token": refresh, "expires_at": int(moment) + max(60, expires)}


def _post_token(body: bytes, opener=None) -> dict:
    from babysitter.security import require_google_oauth_url

    require_google_oauth_url(TOKEN_ENDPOINT)
    request = urllib.request.Request(TOKEN_ENDPOINT, data=body, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    request.add_header("Accept", "application/json")
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=8) as response:
            raw = response.read(100_000)
    except Exception as exc:
        raise GoogleError("Google did not finish sign-in. Nothing was saved.") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GoogleError("Google sent something BabySitter could not read. Nothing was saved.") from exc
    return parse_token_payload(payload)


def exchange_code(client_id: str, code: str, verifier: str, opener=None, client_secret: str = "") -> dict:
    fields = {
        "client_id": clean_client_id(client_id),
        "code": code,
        "code_verifier": verifier,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }
    # A Google "Desktop app" client needs its secret here, or Google answers
    # "client_secret is missing". Google says a desktop client's secret is
    # not confidential; it is still kept encrypted on this PC.
    if client_secret:
        fields["client_secret"] = clean_client_secret(client_secret)
    return _post_token(urllib.parse.urlencode(fields).encode("utf-8"), opener)


def refresh_access(client_id: str, refresh_token: str, opener=None, client_secret: str = "") -> dict:
    kept = normalize_google_token(refresh_token)
    fields = {
        "client_id": clean_client_id(client_id),
        "refresh_token": kept,
        "grant_type": "refresh_token",
    }
    if client_secret:
        fields["client_secret"] = clean_client_secret(client_secret)
    body = urllib.parse.urlencode(fields).encode("utf-8")
    parsed = _post_token(body, opener)
    if not parsed.get("refresh_token"):
        parsed["refresh_token"] = kept
    return parsed


def fresh_lines(ids: list[str], titles: list[str], seen: set[str]) -> tuple[str, set[str]]:
    """Speech for items that were not announced yet, plus the updated set."""
    newcomers: list[str] = []
    updated = set(seen)
    for item_id, title in zip(ids, titles):
        if not item_id or item_id in updated:
            continue
        newcomers.append(title)
        updated.add(item_id)
    if not newcomers:
        return "", updated
    return "New from Google: " + "; ".join(newcomers[:3]) + ".", updated


def listen_for_code(expected_state: str, timeout: float = 180, on_ready=None) -> str:
    """One local page on 127.0.0.1:8765. The code is not written to the log."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    box: dict[str, str] = {}

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            try:
                box["code"] = code_from_redirect(self.path, expected_state)
                body = b"You can close this window and go back to BabySitter."
            except GoogleError as exc:
                box["error"] = str(exc)
                body = b"BabySitter could not finish sign-in. You can close this window."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args) -> None:
            return

    try:
        server = HTTPServer(("127.0.0.1", 8765), _Handler)
    except OSError as exc:
        raise GoogleError("Sign-in could not listen on this PC. Nothing was saved.") from exc
    server.timeout = timeout
    if on_ready is not None:
        on_ready()
    try:
        server.handle_request()
    finally:
        server.server_close()
    if box.get("error"):
        raise GoogleError(box["error"])
    if "code" not in box:
        raise GoogleError("Sign-in timed out. Nothing was saved.")
    return box["code"]
