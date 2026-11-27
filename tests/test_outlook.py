"""Outlook and Microsoft 365: read-only, through the one shared inbox."""

import json
import urllib.parse

import pytest

from babysitter.inbox import Account, gather, spoken
from babysitter.plugins.tools import microsoft_account as ms

CLIENT = "0a1b2c3d-1234-5678-9abc-def012345678"
TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOi.payload-part.signature-part"


def fake_graph(url, token):
    assert token == TOKEN
    ms.require_microsoft_url(url)
    if "messages" in url:
        return {"value": [{"id": "m1", "subject": "Lab moved to 3", "from": {"emailAddress": {"name": "Prof. Lee"}}}]}
    if "calendarView" in url:
        return {"value": [{"id": "e1", "subject": "Studio crit", "start": {"dateTime": "2026-11-27T15:00:00"}}]}
    return {"value": [{"name": "Essay draft.docx"}]}


def test_only_read_addresses_are_allowed():
    for good in (ms.MAIL_URL, ms.FILES_URL, ms.TOKEN_ENDPOINT):
        ms.require_microsoft_url(good)
    for bad in (
        "https://graph.microsoft.com/v1.0/me/sendMail",
        "https://graph.microsoft.com/v1.0/me/messages/m1/move",
        "https://graph.microsoft.com/v1.0/users/someone/messages",
        "http://graph.microsoft.com/v1.0/me/drive/recent",
    ):
        with pytest.raises(ms.MicrosoftError):
            ms.require_microsoft_url(bad)


def test_outlook_joins_the_one_inbox_and_says_its_mail():
    accounts = [Account("Outlook", "Outlook", "Outlook calendar", "OneDrive", lambda: TOKEN,
                        reader=lambda token: ms.read_outlook(token, fetch=fake_graph),
                        indexer=lambda token: ms.outlook_index(token, fetch=fake_graph))]
    inbox = gather(accounts, want_fresh=True)
    assert "Outlook · Prof. Lee · Lab moved to 3" in inbox.rows
    assert any(row.startswith("Outlook calendar · Studio crit") for row in inbox.rows)
    assert "OneDrive · Essay draft.docx" in inbox.rows
    assert "Lab moved to 3" in spoken(inbox, lead="mail", only="mail")
    assert "Outlook:m1" in inbox.fresh_ids
    assert TOKEN not in " ".join(inbox.rows + inbox.speeches)


def test_a_failed_outlook_read_is_one_line():
    def expired(url, token):
        raise ms.MicrosoftError("The Microsoft sign-in expired. Sign in again on Accounts and home.")

    accounts = [Account("Outlook", "Outlook", "Outlook calendar", "OneDrive", lambda: TOKEN,
                        reader=lambda token: ms.read_outlook(token, fetch=expired))]
    inbox = gather(accounts)
    assert "Outlook · could not be read" in inbox.rows
    assert any("sign-in expired" in line for line in inbox.problems)


def test_sign_in_uses_pkce_without_a_secret():
    verifier, challenge = ms.pkce_pair()
    url = ms.authorization_url(CLIENT, "state1", challenge)
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    assert query["code_challenge_method"] == "S256" and "Mail.Read" in query["scope"]
    assert "Mail.Send" not in query["scope"] and "ReadWrite" not in query["scope"]
    sent: list[dict] = []

    class Response:
        def read(self, _n):
            return json.dumps({"access_token": TOKEN, "refresh_token": "M.R3_refresh-token-value", "expires_in": 3600}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def opener(request, timeout=0):
        sent.append(dict(urllib.parse.parse_qsl(request.data.decode())))
        return Response()

    bundle = ms.exchange_code(CLIENT, "code1", verifier, opener=opener)
    assert bundle["access_token"] == TOKEN and "client_secret" not in sent[0]
    assert sent[0]["code_verifier"] == verifier


def test_a_school_that_must_approve_says_so():
    with pytest.raises(ms.MicrosoftError, match="school has to approve"):
        ms.parse_token_payload({"error": "consent_required", "error_description": "AADSTS65001: The user or administrator has not consented"})
