"""One read of every linked account, for the list, the summary, and the 15-minute check."""

from babysitter.inbox import Account, gather, spoken
from babysitter.plugins.tools.google_account import GoogleError

TOKEN = "ya29.personal-token-value-ok"
SCHOOL = "ya29.school-token-value-okay"


def fake_google(url, token):
    if "messages?" in url:
        return {"messages": [{"id": "m1" if token == TOKEN else "s1"}]}
    if "/messages/" in url:
        subject = "Lunch Friday" if token == TOKEN else "Essay graded"
        return {"payload": {"headers": [{"name": "Subject", "value": subject}, {"name": "From", "value": "a@b"}]}}
    if "calendar" in url:
        return {"items": [{"id": "e1", "summary": "Studio review", "start": {"dateTime": "2030-01-02T15:00:00Z"}}]}
    return {"files": [{"name": "Notes", "modifiedTime": "2030-01-01T10:00:00Z"}]}


def _accounts(school_token):
    return [
        Account("Google", "Mail", "Calendar", "Drive", lambda: TOKEN),
        Account("School Google", "School mail", "School calendar", "School Drive", school_token),
    ]


def test_every_account_is_read_together():
    inbox = gather(_accounts(lambda: SCHOOL), fetch=fake_google)
    assert any(row.startswith("Mail · ") for row in inbox.rows)
    assert any(row.startswith("School mail · ") for row in inbox.rows)
    said = spoken(inbox, lead="mail", only="mail")
    assert "Lunch Friday" in said and "Essay graded" in said
    assert "Studio review" not in said  # "check my mail" says mail only


def test_one_failed_account_is_one_line_and_the_rest_still_show():
    def expired():
        raise GoogleError("The Google sign-in expired. Sign in again on Tools.")

    inbox = gather(_accounts(expired), fetch=fake_google)
    assert "School Google · could not be read" in inbox.rows
    assert inbox.problems == ["School Google: the sign-in expired. Sign in again on Tools."]
    assert any(row.startswith("Mail · ") for row in inbox.rows)
    assert "Lunch Friday" in spoken(inbox)


def test_what_is_new_covers_the_school_account_too():
    inbox = gather(_accounts(lambda: SCHOOL), want_fresh=True, fetch=fake_google)
    assert "Google:m1" in inbox.fresh_ids and "School Google:s1" in inbox.fresh_ids
    assert "Essay graded" in inbox.fresh_titles


def test_a_token_echoed_back_is_never_shown():
    def leaky(url, token):
        payload = fake_google(url, token)
        if "/messages/" in url:
            payload["payload"]["headers"][0]["value"] = f"oops {token}"
        return payload

    inbox = gather(_accounts(lambda: SCHOOL), fetch=leaky)
    shown = " ".join(inbox.rows + inbox.speeches + inbox.problems)
    assert TOKEN not in shown and SCHOOL not in shown


def test_the_window_never_fetches_a_token_itself(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path / "data"))
    app = QApplication.instance() or QApplication([])
    from babysitter.controller import Controller
    from babysitter.ui import shell as shell_module

    controller = Controller()
    shell = shell_module.Shell(controller)
    try:
        controller.settings.google_enabled = True
        monkeypatch.setattr(shell.google_vault, "has_token", lambda: True)
        monkeypatch.setattr(shell.google_school_vault, "has_token", lambda: False)
        fetched: list = []
        monkeypatch.setattr(shell, "_token_for_google", lambda vault=None: fetched.append(vault) or None)
        started: list = []
        monkeypatch.setattr(shell_module._LinkedJob, "start", lambda job: started.append(job))
        shell._start_google("mail", speak_errors=True)
        shell._refresh_inbox("mail")
        assert len(started) == 2 and fetched == []  # tokens are fetched inside the job
        assert [account.name for account in started[0]._accounts] == ["Google"]
    finally:
        shell.registrar.clear()
        controller.shutdown_threads()
        app.processEvents()


def test_an_expired_account_is_one_notice_with_one_fix(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path / "data"))
    app = QApplication.instance() or QApplication([])
    from babysitter.controller import Controller
    from babysitter.inbox import Inbox
    from babysitter.ui.shell import Shell

    controller = Controller()
    shell = Shell(controller)
    monkeypatch.setattr(shell, "_speak", lambda *a, **k: None)  # no real voice in a test
    try:
        shell._inbox_ready(Inbox(rows=["Mail · a · Lunch"], problems=["School Google: the sign-in expired. Sign in again on Tools."]), "all")
        window = shell.window
        assert not window.notice_strip.isHidden()
        assert window.notice_text.text().startswith("School Google: sign-in expired.")
        window.notice_action.click()
        assert window.notice_strip.isHidden()
        assert window.show_page_key(window.current_page()) == "settings"
        assert window._section_keys[window.section_list.currentRow()] == "accounts"
    finally:
        shell.registrar.clear()
        controller.shutdown_threads()
        app.processEvents()
