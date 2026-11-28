"""0.33.0: watch a monitor, cite the page in the browser, keep the requests it can't do yet."""

from __future__ import annotations

from datetime import date

import pytest

from babysitter import citations as c
from babysitter import screenwatch as sw
from babysitter import wishlist as wl
from babysitter.commands import match_quick_command


# ---------- which monitor ----------

@pytest.mark.parametrize("line, kind, spec", [
    ("look at monitor one", "watch", "1"),
    ("watch monitor 2", "watch", "2"),
    ("can you look at my second monitor", "watch", "2"),
    ("watch the left screen", "watch", "left"),
    ("keep an eye on my main monitor", "watch", "primary"),
    ("look at the vertical monitor", "watch", "portrait"),
    ("watch both screens", "watch", "all"),
    ("look at screen two", "watch", "2"),
    ("watch my screen", "watch", "cursor"),
    ("stop watching", "unwatch", ""),
    ("which monitor are you watching", "watch_status", ""),
    ("how many monitors do I have", "monitors", ""),
    ("read my screen", "screen_read", ""),
    ("read monitor two", "screen_read", "2"),
    ("read me the text on monitor one", "screen_read", "1"),
    ("what does this say", "screen_read", ""),
    ("copy the text on my screen", "screen_copy", ""),
    ("copy the text from monitor 2", "screen_copy", "2"),
])
def test_monitor_commands(line, kind, spec):
    said = match_quick_command(line)
    assert said is not None and (said.kind, said.detail) == (kind, spec), line


def test_look_at_my_screen_is_still_the_one_look():
    assert match_quick_command("look at my screen").kind == "screen"
    assert match_quick_command("what's on my monitor").kind == "screen"


HIS_PC = [(1, 0, 0, 2560, 1440, True), (2, -1440, -630, 1440, 2560, False)]


def test_windows_numbers_go_on_the_right_qt_screens():
    # Qt lists the portrait one first here; the numbers still follow Windows.
    monitors = sw.number_monitors(HIS_PC, [(-1440, -630, 1440, 2560), (0, 0, 2560, 1440)])
    assert [(m.number, m.qt_index, m.primary) for m in monitors] == [(1, 1, True), (2, 0, False)]
    # Scaled by 150%, the order is the same.
    scaled = sw.number_monitors(HIS_PC, [(0, 0, 1707, 960), (-960, -420, 960, 1707)])
    assert [m.qt_index for m in scaled] == [0, 1]


def test_picking_by_number_place_and_shape():
    monitors = sw.number_monitors(HIS_PC, [(0, 0, 2560, 1440), (-1440, -630, 1440, 2560)])
    assert sw.pick("2", monitors)[0][0].number == 2
    assert sw.pick("left", monitors)[0][0].number == 2
    assert sw.pick("right", monitors)[0][0].number == 1
    assert sw.pick("portrait", monitors)[0][0].number == 2
    assert sw.pick("primary", monitors)[0][0].number == 1
    assert len(sw.pick("all", monitors)[0]) == 2
    chosen, problem = sw.pick("3", monitors)
    assert chosen == [] and problem == "I only see 2 monitors, numbered 1, 2."
    assert "portrait" in sw.spoken_monitors(monitors)


def test_the_lines_that_matter_are_kept_in_screen_order():
    lines = [f"filler line {i} about nothing much at all here" for i in range(200)]
    lines[120] = "Invoice total: $482.17 due December 3"
    kept = sw.relevant_text(lines, "what's the invoice total?", limit=600)
    assert "Invoice total: $482.17" in kept and len(kept) <= 600
    assert kept.index("filler line 118") < kept.index("Invoice total")
    assert sw.relevant_text(["short", "screen"], "anything") == "short\nscreen"
    top = sw.relevant_text(lines, "what is this", limit=300)
    assert top.startswith("filler line 0") and top.endswith("…")


def test_the_model_is_told_the_words_are_exact():
    note = sw.screen_note("monitor 1 (2560 by 1440, landscape, main)", "Total: 5")
    assert "monitor 1" in note and "Total: 5" in note and "quote it exactly" in note
    assert "no readable text" in sw.screen_note("monitor 2", "")


def test_browser_address_and_title():
    assert sw.clean_address("en.wikipedia.org/wiki/Climate") == "https://en.wikipedia.org/wiki/Climate"
    assert sw.clean_address("https://example.com/a?b=1") == "https://example.com/a?b=1"
    assert sw.clean_address("search for cats") == ""
    assert sw.clean_address("file:///C:/x.pdf") == ""
    assert sw.page_title("Climate - Wikipedia - Google Chrome") == "Climate - Wikipedia"
    assert sw.page_title("Climate - Wikipedia - DuckDuckGo") == "Climate - Wikipedia"
    assert "duckduckgo.exe" in sw.BROWSERS


# ---------- citations ----------

ARTICLE = """<html><head><title>Is the Global Gag Rule Stifling Women's Health Research? - Scientific American</title>
<meta property="og:site_name" content="Scientific American">
<meta name="author" content="Kate Clancy">
<meta property="article:published_time" content="2017-02-02T10:00:00Z">
</head><body></body></html>"""
URL = "https://blogs.scientificamerican.com/context-and-variation/gag-rule/"
DAY = date(2026, 11, 27)


def _article():
    return c.source_from_html(ARTICLE, URL, DAY)


def test_the_page_says_who_wrote_it_and_when():
    source = _article()
    assert source.title == "Is the Global Gag Rule Stifling Women's Health Research?"
    assert source.authors == ("Kate Clancy",) and source.site == "Scientific American"
    assert source.published == (2017, 2, 2)


def test_mla_apa_chicago_follow_their_guides():
    source = _article()
    assert c.plain(c.cite(source, "mla")) == (
        "Clancy, Kate. \u201cIs the Global Gag Rule Stifling Women's Health Research?\u201d "
        "Scientific American, 2 Feb. 2017, blogs.scientificamerican.com/context-and-variation/gag-rule."
    )
    assert c.plain(c.cite(source, "apa")) == (
        "Clancy, K. (2017, February 2). Is the Global Gag Rule Stifling Women's Health Research? "
        "Scientific American. " + URL
    )
    assert c.plain(c.cite(source, "chicago")).startswith("Clancy, Kate. \u201cIs the Global")
    assert c.plain(c.in_text(source, "mla")) == "(Clancy)"
    assert c.plain(c.in_text(source, "apa")) == "(Clancy, 2017)"
    # The site's name is in italics in MLA: rich text keeps it for Word.
    assert "<i>Scientific American</i>" in c.rich(c.cite(source, "mla"))


def test_no_date_means_accessed_and_nd():
    source = c.Source(title="How to Make Vegetarian Chili", site="eHow", authors=("Susan Lundman",),
                      url="https://www.ehow.com/how_10727_make-vegetarian-chili.html", accessed=date(2015, 7, 6))
    assert c.plain(c.mla(source)).endswith("www.ehow.com/how_10727_make-vegetarian-chili.html. Accessed 6 July 2015.")
    assert "(n.d.)" in c.plain(c.apa(source))
    assert c.missing_note(source) == "The page lists no date, so the citation leaves it out."


def test_every_style_and_a_journal_article():
    journal = c.Source(title="Dimensions of Aging", authors=("Jane A. Smith", "Bob Jones", "Carl Lee"), journal="Nature",
                       site="Nature", volume="12", issue="3", pages="45\u201367", doi="10.1038/abc123",
                       published=(2020, 5, None), accessed=DAY)
    assert c.plain(c.cite(journal, "mla")).startswith("Smith, Jane A., et al.")
    assert "Smith, J. A., Jones, B., & Lee, C. (2020, May)." in c.plain(c.cite(journal, "apa"))
    assert "pages = {45--67}" in c.cite(journal, "bibtex")
    everything = c.plain(c.every_style(journal))
    for label in ("MLA 9:", "APA 7:", "Chicago 17 (footnote):", "Harvard:", "IEEE:", "AMA 11:", "Vancouver:", "ASA:", "BibTeX:"):
        assert label in everything


@pytest.mark.parametrize("line, style", [
    ("cite this in MLA", "mla"), ("MLA citation", "mla"), ("give me an APA citation", "apa"),
    ("cite this page", ""), ("cite this website in Chicago", "chicago"), ("Chicago footnote for this page", "chicago_note"),
    ("give me a Harvard reference", "harvard"), ("cite this in all formats", "all"), ("BibTeX for this page", "bibtex"),
    ("make a citation for this article in IEEE", "ieee"),
])
def test_citation_words(line, style):
    said = match_quick_command(line)
    assert said is not None and said.kind == "cite" and said.detail == style, line


def test_not_a_citation():
    assert c.cite_command("give me a quick reference") is None
    assert match_quick_command("what is mla format") is None or match_quick_command("what is mla format").kind != "cite"
    assert c.restyle_command("now in apa") == "apa"
    assert c.restyle_command("give me that in chicago") == "chicago"
    assert c.restyle_command("how are you") == ""


def test_names_and_dates():
    assert c.split_name("Ludwig van Beethoven") == ("Ludwig", "van Beethoven", "")
    assert c.split_name("Smith, Jane") == ("Jane", "Smith", "")
    assert c.split_name("World Health Organization") == ("", "World Health Organization", "")
    assert c.parse_date("May 4, 2023") == (2023, 5, 4)
    assert c.parse_date("2023-05") == (2023, 5, None)
    assert c.parse_date("") is None


def test_json_ld_and_scholar_tags():
    page = """<html><head><script type="application/ld+json">{"@type": "NewsArticle", "headline": "Rain Returns",
    "author": [{"@type": "Person", "name": "Ana Ruiz"}, {"@type": "Person", "name": "Li Wei"}],
    "datePublished": "2025-03-09", "publisher": {"@type": "Organization", "name": "The Daily"}}</script></head></html>"""
    source = c.source_from_html(page, "https://daily.example/rain", DAY)
    assert source.title == "Rain Returns" and source.authors == ("Ana Ruiz", "Li Wei") and source.published == (2025, 3, 9)
    assert source.site == "The Daily"
    scholar = """<meta name="citation_title" content="On Things"><meta name="citation_author" content="Doe, John">
    <meta name="citation_journal_title" content="Journal of Things"><meta name="citation_volume" content="4">
    <meta name="citation_doi" content="10.1000/xyz">"""
    paper = c.source_from_html(scholar, "https://journal.example/p", DAY)
    assert paper.journal == "Journal of Things" and paper.doi == "10.1000/xyz" and paper.authors == ("Doe, John",)


def test_a_record_round_trips():
    source = _article()
    assert c.from_record(c.as_record(source)) == source


# ---------- requests ----------

def test_a_request_it_cannot_do_is_recognised():
    assert wl.looks_like_request("can you order me a pizza")
    assert wl.looks_like_request("send a text to my mom")
    assert not wl.looks_like_request("what is the capital of France?")
    assert wl.reply_says_cannot("Ordering food isn't something I can do yet.")
    assert wl.reply_says_cannot("I can't send texts from here.")
    assert not wl.reply_says_cannot("Paris is the capital.")


def test_the_list_counts_repeats_and_numbers_its_lines():
    items, added = wl.add([], "order me a pizza", date(2026, 11, 27))
    assert added
    items, again = wl.add(items, "Order me a pizza!", date(2026, 11, 28))
    assert not again and items[0]["times"] == 2
    lines = wl.sheet_lines(items)
    assert lines[0] == wl.SHEET_HEADER and "taken off this list" in lines[0]
    assert lines[2] == "1. order me a pizza — asked 2026-11-27 (2 times)"
    kept, gone = wl.remove_number(items, 1)
    assert kept == [] and gone["text"] == "order me a pizza"


def test_built_requests_come_off():
    items = [{"text": "set a timer for 5 minutes"}, {"text": "order me a pizza"}]
    kept, built = wl.now_possible(items, lambda text: match_quick_command(text) is not None)
    assert [i["text"] for i in built] == ["set a timer for 5 minutes"]
    assert [i["text"] for i in kept] == ["order me a pizza"]


@pytest.mark.parametrize("line, kind", [
    ("show my requests", "requests"), ("what have I asked for", "requests"),
    ("remove request 2", "request_remove"), ("request two is done", "request_remove"),
    ("I wish you could order food", "request_add"), ("add to my requests: dim the lights", "request_add"),
    ("copy that", "copy"),
])
def test_request_commands(line, kind):
    said = match_quick_command(line)
    assert said is not None and said.kind == kind, line
    if kind == "request_remove":
        assert said.seconds == 2
    if kind == "request_add":
        assert said.detail in {"order food", "dim the lights"}


# ---------- in the window ----------

def _shell(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    QApplication.instance() or QApplication([])
    from babysitter.controller import Controller
    from babysitter.ui.shell import Shell

    shell = Shell(Controller())
    spoken = []
    monkeypatch.setattr(shell, "_speak", lambda text, *a, **k: spoken.append(text))
    return shell, spoken


def test_a_cannot_reply_saves_the_request(tmp_path, monkeypatch):
    from babysitter.deskstore import load_list

    shell, _spoken = _shell(tmp_path, monkeypatch)
    try:
        shell._pending_line = "can you order me a pizza"
        assert shell._maybe_save_request(shell._pending_line, "That isn't something I can do yet.") == "I've saved that to your requests."
        assert [i["text"] for i in load_list(wl.FILE)] == ["can you order me a pizza"]
        assert shell.window.requests_list.item(0).text().startswith("1. can you order me a pizza")
        shell._run_quick("remove request 1")
        assert load_list(wl.FILE) == [] and shell.window.requests_list.item(0).text().startswith("Nothing saved yet")
    finally:
        shell.window.close()


def test_a_new_version_takes_off_what_it_can_do(tmp_path, monkeypatch):
    from babysitter.deskstore import load_list, save_list

    shell, _spoken = _shell(tmp_path, monkeypatch)
    try:
        save_list("requests_checked.json", [{"version": "0.0.1"}])
        save_list(wl.FILE, [{"id": "a", "text": "look at monitor one"}, {"id": "b", "text": "order me a pizza"}])
        shell._check_requests_after_update()
        assert [i["text"] for i in load_list(wl.FILE)] == ["order me a pizza"]
        assert shell.window.has_notice() and "look at monitor one" in shell.window.notice_text.text()
    finally:
        shell.window.close()


def test_watching_and_stopping(tmp_path, monkeypatch):
    shell, spoken = _shell(tmp_path, monkeypatch)
    try:
        shell._run_quick("look at monitor one")
        assert shell._watching == [1] and spoken[-1].startswith("Watching monitor 1.")
        shell._run_quick("stop watching")
        assert shell._watching == [] and spoken[-1] == "Stopped watching. Nothing was kept."
    finally:
        shell.window.close()


def test_restyle_needs_no_new_fetch(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    shell, spoken = _shell(tmp_path, monkeypatch)
    try:
        shell._show_citation(_article(), "mla")
        assert "Clancy, Kate." in QApplication.clipboard().text()
        assert shell._run_quick("now in APA") is True
        assert QApplication.clipboard().text().startswith("Clancy, K. (2017, February 2).")
        assert spoken[-1].startswith("The APA 7 citation is on your clipboard")
    finally:
        if shell._citation_panel is not None:
            shell._citation_panel.close()
        shell.window.close()


def test_garbled_text_is_flagged_and_the_reading_stays_hidden():
    icons = "pyhn eal Mi&héle Stufffro harddr 2-23 measurme:.. P odcast recordin... ,resühéjöÖÄ014-010526f •0• obs- plÅlns Positi0H"
    assert sw.clean_share(icons) < 0.62
    assert sw.clean_share("Steam View Friends Games Help STORE LIBRARY COMMUNITY") > 0.9
    assert "never guess a name" in sw.screen_note("monitor 2", icons)
    note = sw.screen_note("monitor 1", "Steam View Friends Games Help")
    assert "never guess" not in note and "don't mention this text" in note


def test_no_author_in_text_uses_a_clean_short_title():
    source = c.Source(title="Gardien(ne) des étangs - Pond keeper", site="Example",
                      url="https://example.org/jobs/1", accessed=DAY)
    assert c.plain(c.in_text(source, "mla")) == "(\u201cGardien(ne) des étangs\u201d)"
    assert c.plain(c.in_text(source, "apa")) == "(Gardien(ne) des étangs, n.d.)"


# ---------- audit 1 regressions ----------

def test_only_a_refusal_to_act_is_a_missing_feature():
    for reply in ("I can't be sure, but it was probably 1912.", "I can't help but laugh at that.",
                  "Honestly, I can't wait for summer either.", "I cannot stress this enough: drink water."):
        assert not wl.reply_says_cannot(reply), reply
    for reply in ("I can't send texts from here.", "I can't place orders or handle money for you yet.",
                  "That isn't something I can do yet.", "I don't have access to your phone."):
        assert wl.reply_says_cannot(reply), reply


def test_a_style_word_in_a_question_is_not_a_restyle():
    for line in ("is mla better than apa", "what is apa", "explain chicago style to me", "tell me about harvard"):
        assert c.restyle_command(line) == "", line
    for line, style in (("now in apa", "apa"), ("give me that in chicago", "chicago"), ("in all formats", "all"),
                        ("apa please", "apa"), ("chicago footnote", "chicago_note")):
        assert c.restyle_command(line) == style, line


def test_copy_that_follows_the_newest_reply(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    shell, _spoken = _shell(tmp_path, monkeypatch)
    try:
        shell._show_citation(_article(), "mla")
        shell._pending_line = "what is 2 plus 2"
        shell._asked("It's 4.")
        shell._run_quick("copy that")
        assert QApplication.clipboard().text() == "It's 4."
    finally:
        if shell._citation_panel is not None:
            shell._citation_panel.close()
        shell.window.close()


def test_a_loose_match_doesnt_take_a_request_off(tmp_path, monkeypatch):
    from babysitter.deskstore import load_list, save_list

    shell, _spoken = _shell(tmp_path, monkeypatch)
    try:
        save_list("requests_checked.json", [{"version": "0.0.1"}])
        save_list(wl.FILE, [{"id": "a", "text": "remember to water my plants by texting me"},
                            {"id": "b", "text": "remind me with a text message"}])
        shell._check_requests_after_update()
        assert len(load_list(wl.FILE)) == 2
    finally:
        shell.window.close()
