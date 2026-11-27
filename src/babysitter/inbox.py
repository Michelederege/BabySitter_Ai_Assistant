"""One read of every linked account, shared by everything that shows it.

The Tools list, the spoken summary ("check my mail"), and the 15-minute
check for new mail all come from this one read: personal Google, school
Google, and Blackboard. An account that fails becomes one line, such as
"School Google: the sign-in expired", and the rest still show. Alerts
while the AI is off can use the same read later.

Each account's token is fetched through a function, on the thread doing
the read, so refreshing an expired sign-in never makes the window wait.
Only reads are made. Nothing is sent, changed, or deleted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from babysitter.blackboard import FeedError, blackboard_rows, blackboard_speech, events_from_ics, fetch_feed
from babysitter.plugins.tools.google_account import GoogleError, GoogleReader, http_get_json, read_account
from babysitter.secrets import SecretsError


@dataclass(frozen=True)
class Account:
    name: str  # "Google" or "School Google", for a problem line
    mail: str  # row prefixes
    calendar: str
    drive: str
    token: Callable[[], str | None]
    # A service other than Google brings its own read: token -> (rows, speeches, problems),
    # and its own index for "what is new": token -> (ids, titles).
    reader: Optional[Callable] = None
    indexer: Optional[Callable] = None


@dataclass
class Inbox:
    rows: list[str] = field(default_factory=list)
    speeches: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    # For "what is new": item ids and their titles, mail and events.
    fresh_ids: list[str] = field(default_factory=list)
    fresh_titles: list[str] = field(default_factory=list)
    secrets: list[str] = field(default_factory=list)

    def safe(self) -> "Inbox":
        """Never show a token or the feed link, even if a service echoed one back."""
        def clean(line: str, fallback: str) -> str:
            return fallback if any(secret and secret in line for secret in self.secrets) else line

        hidden = "A linked account answered with something BabySitter will not show."
        return Inbox(
            rows=[clean(row, hidden) for row in self.rows],
            speeches=[clean(line, hidden) for line in self.speeches],
            problems=[clean(line, hidden) for line in self.problems],
            fresh_ids=list(self.fresh_ids),
            fresh_titles=[clean(title, "New item") for title in self.fresh_titles],
        )


# Which spoken lines lead for "check my mail", "what's on my calendar", and so on.
LEADS = {
    "mail": ("Unread mail", "No unread mail", "Unread school", "No unread school", "Unread Outlook", "No unread Outlook"),
    "calendar": ("Coming up", "Nothing coming up", "School calendar", "Blackboard", "Outlook calendar"),
    "drive": ("Drive:", "No files in Drive", "School Drive"),
    "school_mail": ("Unread school", "No unread school"),
    "blackboard": ("Blackboard",),
}
# For a spoken answer about one thing, only those lines are said.
ONLY = {
    "mail": ("Unread mail", "No unread mail", "Unread school", "No unread school", "Unread Outlook", "No unread Outlook"),
    "calendar": ("Coming up", "Nothing coming up", "School calendar", "Nothing coming up on School", "Blackboard", "Nothing coming up on Blackboard", "Outlook calendar", "Nothing coming up on the Outlook"),
}


def _problem(account: str, exc: Exception) -> str:
    text = str(exc) or "it could not be read"
    if "expired" in text.lower() or "sign in again" in text.lower():
        return f"{account}: the sign-in expired. Sign in again on Tools."
    return f"{account}: {text}"


def gather(
    accounts: list[Account],
    feed: Callable[[], str | None] | None = None,
    *,
    want_fresh: bool = False,
    fetch=http_get_json,
    fetch_ics=fetch_feed,
) -> Inbox:
    """Read every account. One failure is one line; it never hides the rest."""
    inbox = Inbox()
    for account in accounts:
        try:
            token = account.token() or ""
        except Exception as exc:  # a sign-in that cannot refresh is one line, never a crash
            inbox.problems.append(_problem(account.name, exc))
            inbox.rows.append(f"{account.name} · could not be read")
            continue
        if not token:
            continue
        inbox.secrets.append(token)
        try:
            if account.reader is not None:
                rows, speeches, problems = account.reader(token)
                problems = [line.split(": ", 1)[-1] for line in problems]
            else:
                rows, speeches, problems = read_account(
                    token,
                    mail_prefix=account.mail,
                    calendar_prefix=account.calendar,
                    drive_prefix=account.drive,
                    fetch=fetch,
                )
        except Exception as exc:  # noqa: BLE001 - a reply of an unexpected shape is this account's line only
            inbox.problems.append(_problem(account.name, exc))
            inbox.rows.append(f"{account.name} · could not be read")
            continue
        inbox.rows.extend(rows)
        inbox.speeches.extend(speeches)
        inbox.problems.extend(f"{account.name}: {line}" for line in problems)
        if want_fresh and account.indexer is not None:
            try:
                ids, titles = account.indexer(token)
            except Exception:  # noqa: BLE001 - nothing new is reported for this account this time
                ids, titles = [], []
            inbox.fresh_ids.extend(f"{account.name}:{item}" for item in ids)
            inbox.fresh_titles.extend(titles)
        elif want_fresh:
            reader = GoogleReader(token, fetch)
            for read in (reader.mail_index, reader.event_index):
                try:
                    ids, titles = read()
                except GoogleError:
                    continue
                inbox.fresh_ids.extend(f"{account.name}:{item}" for item in ids)
                inbox.fresh_titles.extend(titles)
    if feed is not None:
        try:
            url = feed() or ""
        except (FeedError, SecretsError) as exc:
            url = ""
            inbox.problems.append(f"Blackboard: {exc}")
            inbox.rows.append("Blackboard · could not be read")
        except Exception:  # noqa: BLE001 - the saved link could not be opened on this PC
            url = ""
            inbox.problems.append("Blackboard: the saved link could not be opened.")
            inbox.rows.append("Blackboard · could not be read")
        if url:
            inbox.secrets.append(url)
            try:
                events = events_from_ics(fetch_ics(url))
                inbox.rows.extend(blackboard_rows(events))
                inbox.speeches.append(blackboard_speech(events))
            except FeedError as exc:
                inbox.problems.append(f"Blackboard: {exc}")
                inbox.rows.append("Blackboard · could not be read")
            except Exception:  # noqa: BLE001 - a calendar file it cannot parse is one line too
                inbox.problems.append("Blackboard: the calendar could not be read.")
                inbox.rows.append("Blackboard · could not be read")
    return inbox.safe()


def spoken(inbox: Inbox, lead: str = "", only: str = "") -> str:
    """The spoken summary. `lead` goes first; `only` keeps just that kind."""
    lines = list(inbox.speeches)
    if only in ONLY:
        lines = [line for line in lines if any(line.startswith(bit) or bit in line for bit in ONLY[only])]
    preferred = LEADS.get(lead, ())
    if preferred:
        lines.sort(key=lambda line: 0 if any(bit in line for bit in preferred) else 1)
    speech = " ".join(lines[:4]).strip()
    if inbox.problems and not speech:
        return " ".join(inbox.problems[:2])
    if inbox.problems:
        return f"{speech} {inbox.problems[0]}"
    return speech
