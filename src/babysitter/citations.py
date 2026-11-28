"""Citations for the web page he's looking at, in the style he names.

"Cite this in MLA" reads the address from the browser (screenwatch), asks
before fetching that one page, reads the details the page states about
itself (title, authors, dates, site, DOI), and writes the citation. It's
put on the clipboard twice: as rich text, so titles stay in italics when
pasted into Word or Google Docs, and as plain text.

Everything here is formatting; the only network call is fetch_page, one
GET of the address he is looking at, after his yes.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urlsplit

I0, I1 = "\x01", "\x02"  # italics start / end, turned into <i> or removed


def _it(text: str) -> str:
    return f"{I0}{text}{I1}" if text else ""


def plain(text: str) -> str:
    return text.replace(I0, "").replace(I1, "")


def rich(text: str) -> str:
    return html.escape(text).replace(I0, "<i>").replace(I1, "</i>")


# ---------- the source ----------

@dataclass(frozen=True)
class Source:
    title: str = ""
    authors: tuple[str, ...] = ()
    site: str = ""
    publisher: str = ""
    published: tuple[int, int | None, int | None] | None = None  # (year, month, day)
    url: str = ""
    accessed: date = field(default_factory=date.today)
    doi: str = ""
    journal: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""


# ---------- styles ----------

STYLES = {
    "mla": "MLA 9",
    "apa": "APA 7",
    "chicago": "Chicago 17 (bibliography)",
    "chicago_note": "Chicago 17 (footnote)",
    "chicago_ad": "Chicago 17 (author-date)",
    "harvard": "Harvard",
    "ieee": "IEEE",
    "ama": "AMA 11",
    "vancouver": "Vancouver",
    "asa": "ASA",
    "turabian": "Turabian",
    "bibtex": "BibTeX",
}
_STYLE_WORDS = [
    (r"\bchicago\b.*\b(?:foot ?note|note)s?\b|\b(?:foot ?note|note)s?\b.*\bchicago\b", "chicago_note"),
    (r"\bchicago\b.*\bauthor[- ]date\b|\bauthor[- ]date\b", "chicago_ad"),
    (r"\bm\.? ?l\.? ?a\b|\bmla\b|\bem el a\b|\bm l a\b", "mla"),
    (r"\ba\.? ?p\.? ?a\b|\bapa\b|\bay pee ay\b|\ba p a\b", "apa"),
    (r"\bchicago\b", "chicago"),
    (r"\bharvard\b", "harvard"),
    (r"\bi\.? ?e\.? ?e\.? ?e\b|\bieee\b|\bi triple e\b|\beye triple e\b", "ieee"),
    (r"\ba\.? ?m\.? ?a\b|\bama\b|\bmedical\b", "ama"),
    (r"\bvancouver\b", "vancouver"),
    (r"\ba\.? ?s\.? ?a\b|\basa\b|\bsociolog", "asa"),
    (r"\bturabian\b", "turabian"),
    (r"\bbib ?tex\b|\bbibtex\b|\blatex\b", "bibtex"),
    (r"\b(?:all|every|each)\b.*\b(?:styles?|formats?|ways?|versions?|kinds?|types?)\b|\ball of them\b", "all"),
]


def style_in(words: str) -> str:
    """The style named in what he said, "" for none, "all" for every style."""
    text = " ".join((words or "").lower().split())
    for pattern, key in _STYLE_WORDS:
        if re.search(pattern, text):
            return key
    return ""


_CITE = re.compile(
    r"^(?:(?:give me|make|write|get me|i need|create|do|generate)\s+)?(?:an?\s+|the\s+)?"
    r"(?:(?P<pre>[\w.\- ]{2,24}?)\s+)?(?:citation|cite|reference|works cited(?: entry)?|bibliography(?: entry)?|footnote|in[- ]text citation)"
    r"(?:\s+(?:for|of|to))?(?:\s+(?:this|that|the|my))?(?:\s+(?:page|website|site|article|web ?page|link|source|tab))?"
    r"(?:\s+(?:in|as|using)\s+(?P<post>[\w.\- ]{2,30}))?(?:\s+(?:format|style|form))?$"
)
_CITE_ALSO = re.compile(
    r"^(?:cite|reference)\s+(?:this|that|the|my)?\s*(?:page|website|site|article|web ?page|link|source|tab|it)?"
    r"(?:\s+(?:in|as|using)\s+(?P<style>[\w.\- ]{2,30}?))?(?:\s+(?:format|style|form))?$"
)
_RESTYLE = re.compile(
    r"^(?:(?:now|and|ok|okay|also)\s+)*(?:(?:give me|do|make it|put it|change it to|switch to|show me)\s+)?"
    r"(?:that|it|the citation|the same)?\s*(?:in|as|to)?\s*(?P<style>[\w.\- ]{2,30}?)(?:\s+(?:format|style|form|citation|too|instead|please))*$"
)


_STYLE_ONLY = re.compile(
    r"^(?:(?:give me|do|put (?:this|it|that) in|format (?:this|it|that) (?:in|as)|in)\s+)?(?:the\s+|an?\s+)?"
    r"(?P<style>mla|apa|chicago|harvard|ieee|ama|vancouver|asa|turabian|bibtex|bib tex)"
    r"(?:\s+(?:format|style|entry|footnote|note|author date))?"
    r"(?:\s+(?:for|of)\s+(?:this|that|the|my)\s+(?:page|website|site|article|web ?page|link|source|tab))?$"
)


def cite_command(phrase: str) -> str | None:
    """The style asked for ("" for his usual), or None when it isn't a citation request."""
    for pattern in (_CITE_ALSO, _CITE):
        found = pattern.match(phrase)
        if not found:
            continue
        if pattern is _CITE:
            pre = (found.group("pre") or "").strip()
            if pre and not style_in(pre) and pre not in {"a", "an", "the", "web", "website", "page", "full", "proper"}:
                return None  # "give me a quick reference" is not a citation
        return style_in(phrase)
    if _STYLE_ONLY.match(phrase):
        return style_in(phrase)
    return None


_STYLE_VOCAB = {
    "mla", "apa", "chicago", "harvard", "ieee", "ama", "vancouver", "asa", "turabian", "bibtex", "bib", "tex",
    "latex", "footnote", "footnotes", "note", "notes", "author", "date", "author-date", "all", "every", "each",
    "style", "styles", "format", "formats", "of", "them", "the", "m", "l", "a", "p", "i", "e", "s", "triple",
    "eye", "em", "el", "ay", "pee", "versions", "ways", "kinds", "types",
}


def restyle_command(phrase: str) -> str:
    """"Now in APA" or "give me that in Chicago" right after a citation: the style, or "".

    Only when the words name a style and nothing else: "is MLA better than APA"
    is a question, not a request to switch.
    """
    found = _RESTYLE.match(phrase)
    if not found:
        return ""
    words = re.findall(r"[a-z\-]+", found.group("style").lower().replace(".", ""))
    if not words or any(word not in _STYLE_VOCAB for word in words):
        return ""
    return style_in(found.group("style"))


# ---------- names and dates ----------

_ORG_WORDS = re.compile(
    r"\b(?:inc|llc|ltd|corp|company|university|college|institute|association|society|council|department|"
    r"ministry|agency|organization|organisation|foundation|news|press|staff|team|editors|editorial|board|"
    r"group|center|centre|office|service|services|government|bureau|committee|museum|library|wikipedia|bbc|cnn)\b",
    re.IGNORECASE,
)
_PARTICLES = {"van", "von", "de", "der", "da", "di", "del", "la", "le", "du", "st.", "bin", "al"}
_SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}


def _is_org(name: str) -> bool:
    return bool(_ORG_WORDS.search(name)) or len(name.split()) == 1


def split_name(name: str) -> tuple[str, str, str]:
    """(given, family, suffix). "Last, First" is understood. An organisation is all family."""
    name = " ".join((name or "").split()).strip(" ,")
    if not name:
        return "", "", ""
    if "," in name:
        family, _, given = name.partition(",")
        given = given.strip()
        suffix = ""
        if given.lower() in _SUFFIXES:
            return "", family.strip(), ""
        return given, family.strip(), suffix
    if _is_org(name):
        return "", name, ""
    parts = name.split()
    suffix = ""
    if parts[-1].lower().strip(",") in _SUFFIXES and len(parts) > 2:
        suffix = parts.pop().strip(",")
    family = [parts.pop()]
    while len(parts) > 1 and parts[-1].lower() in _PARTICLES:
        family.insert(0, parts.pop())
    return " ".join(parts), " ".join(family), suffix


def initials(given: str, *, dots: bool = True, space: bool = True) -> str:
    pieces = []
    for part in given.replace(".", ". ").split():
        if "-" in part:
            joined = "-".join(p[0].upper() + ("." if dots else "") for p in part.split("-") if p)
            pieces.append(joined)
        elif part:
            pieces.append(part[0].upper() + ("." if dots else ""))
    return (" " if space else "").join(pieces)


MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
_MLA_MONTHS = ["Jan.", "Feb.", "Mar.", "Apr.", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."]
_IEEE_MONTHS = ["Jan.", "Feb.", "Mar.", "Apr.", "May", "Jun.", "Jul.", "Aug.", "Sep.", "Oct.", "Nov.", "Dec."]
_SHORT_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def parse_date(value: str) -> tuple[int, int | None, int | None] | None:
    """"2023-05-04T10:00Z", "2023-05", "May 4, 2023", "4 May 2023", "2023" as (year, month, day)."""
    text = (value or "").strip()
    if not text:
        return None
    found = re.match(r"^(\d{4})(?:[-/](\d{1,2})(?:[-/](\d{1,2}))?)?", text)
    if found:
        year = int(found.group(1))
        month = int(found.group(2)) if found.group(2) else None
        day = int(found.group(3)) if found.group(3) else None
        if 1000 < year < 2200 and (month is None or 1 <= month <= 12) and (day is None or 1 <= day <= 31):
            return year, month, day
    lowered = text.lower()
    month = next((i + 1 for i, name in enumerate(MONTHS) if re.search(rf"\b{name[:3].lower()}[a-z]*\.?\b", lowered)), None)
    year_match = re.search(r"\b(1[89]\d\d|2[01]\d\d)\b", text)
    if not year_match:
        return None
    day_match = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\b(?!\d)", text.replace(year_match.group(1), ""))
    day = int(day_match.group(1)) if day_match and month and 1 <= int(day_match.group(1)) <= 31 else None
    return int(year_match.group(1)), month, day


def _year(source: Source) -> str:
    return str(source.published[0]) if source.published else ""


def _day_month_year(parts, months=MONTHS) -> str:
    """"4 May 2023" (MLA, Harvard). Missing parts are left out."""
    if not parts:
        return ""
    year, month, day = parts
    bits = []
    if day and month:
        bits.append(str(day))
    if month:
        bits.append(months[month - 1])
    bits.append(str(year))
    return " ".join(bits)


def _month_day_year(parts, months=MONTHS) -> str:
    """"May 4, 2023" (Chicago, AMA, IEEE)."""
    if not parts:
        return ""
    year, month, day = parts
    if month and day:
        return f"{months[month - 1]} {day}, {year}"
    if month:
        return f"{months[month - 1]} {year}"
    return str(year)


def _as_parts(day: date) -> tuple[int, int, int]:
    return day.year, day.month, day.day


def _no_scheme(url: str) -> str:
    return re.sub(r"^https?://", "", url or "").rstrip("/")


def _end(text: str, mark: str = ".") -> str:
    """Add the closing mark unless the text already ends in one."""
    bare = plain(text).rstrip()
    if not bare:
        return text
    if bare[-1] in ".?!":
        return text
    return text + mark


def _site_differs(source: Source) -> bool:
    if not source.site:
        return False
    names = [plain(name).lower() for name in source.authors]
    return source.site.lower() not in names


def _publisher(source: Source) -> str:
    if source.publisher and source.publisher.lower() not in {source.site.lower(), *[a.lower() for a in source.authors]}:
        return source.publisher
    return ""


# ---------- each style ----------

def _mla_names(authors) -> str:
    if not authors:
        return ""
    given, family, suffix = split_name(authors[0])
    first = f"{family}, {given}" if given else family
    if suffix:
        first += f", {suffix}"
    if len(authors) == 1:
        return first
    if len(authors) == 2:
        given2, family2, _ = split_name(authors[1])
        return f"{first}, and {' '.join(p for p in (given2, family2) if p)}"
    return f"{first}, et al"


def mla(source: Source) -> str:
    parts = []
    names = _mla_names(source.authors)
    if names:
        parts.append(_end(names))
    title = source.title or _no_scheme(source.url)
    if source.journal:
        parts.append(f"“{_end(title)}”")
        container = _it(source.journal)
        bits = [container]
        if source.volume:
            bits.append(f"vol. {source.volume}")
        if source.issue:
            bits.append(f"no. {source.issue}")
        if source.published:
            bits.append(_day_month_year(source.published, _MLA_MONTHS))
        if source.pages:
            bits.append(f"pp. {source.pages}")
        if source.doi:
            bits.append(f"https://doi.org/{source.doi}")
        elif source.url:
            bits.append(_no_scheme(source.url))
        parts.append(_end(", ".join(bits)))
        return " ".join(parts)
    if source.site and source.site.lower() != title.lower():
        parts.append(f"“{_end(title)}”")
        bits = [_it(source.site)]
    else:
        parts.append(_end(_it(title)))
        bits = []
    publisher = _publisher(source)
    if publisher:
        bits.append(publisher)
    if source.published:
        bits.append(_day_month_year(source.published, _MLA_MONTHS))
    if source.url:
        bits.append(_no_scheme(source.url))
    if bits:
        parts.append(_end(", ".join(bits)))
    if not source.published:
        parts.append(f"Accessed {_day_month_year(_as_parts(source.accessed), _MLA_MONTHS)}.")
    return " ".join(parts)


def _short_title(source: Source) -> str:
    """The first few words of the title, cut at a colon or dash, for an in-text citation."""
    short = re.split(r":|\s[-–—|]\s", source.title or source.site)[0]
    return " ".join(short.split()[:4]).strip(" ,.;-–—")


def mla_in_text(source: Source) -> str:
    families = [split_name(a)[1] for a in source.authors]
    if not families:
        short = _short_title(source)
        return f"(“{short}”)" if source.site and source.site != source.title else f"({_it(short)})"
    if len(families) == 1:
        return f"({families[0]})"
    if len(families) == 2:
        return f"({families[0]} and {families[1]})"
    return f"({families[0]} et al.)"


def _apa_name(name: str) -> str:
    given, family, suffix = split_name(name)
    if not given:
        return family
    text = f"{family}, {initials(given)}"
    return text + (f", {suffix}" if suffix else "")


def _apa_names(authors) -> str:
    names = [_apa_name(a) for a in authors]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) <= 20:
        return ", ".join(names[:-1]) + ", & " + names[-1]
    return ", ".join(names[:19]) + ", . . . " + names[-1]


def _apa_date(parts) -> str:
    if not parts:
        return "n.d."
    year, month, day = parts
    if month and day:
        return f"{year}, {MONTHS[month - 1]} {day}"
    if month:
        return f"{year}, {MONTHS[month - 1]}"
    return str(year)


def apa(source: Source) -> str:
    title = source.title or _no_scheme(source.url)
    names = _apa_names(source.authors)
    when = f"({_apa_date(source.published)})."
    if source.journal:
        head = f"{_end(names)} {when}" if names else f"{_end(title)} {when}"
        bits = [_it(source.journal)]
        if source.volume:
            bits[0] += ", " + _it(source.volume) + (f"({source.issue})" if source.issue else "")
        if source.pages:
            bits[0] += f", {source.pages}"
        tail = _end(bits[0])
        link = f"https://doi.org/{source.doi}" if source.doi else source.url
        body = f"{_end(title)} " if names else ""
        return f"{head} {body}{tail} {link}".strip()
    retrieved = ""
    if not source.published and "wiki" in (source.site or "").lower():
        accessed = source.accessed
        retrieved = f"Retrieved {MONTHS[accessed.month - 1]} {accessed.day}, {accessed.year}, from "
    site = f" {_end(source.site)}" if source.site and _site_differs(source) else ""
    if names:
        return f"{_end(names)} {when} {_end(_it(title))}{site} {retrieved}{source.url}".strip()
    return f"{_end(_it(title))} {when}{site} {retrieved}{source.url}".strip()


def apa_in_text(source: Source) -> str:
    families = [split_name(a)[1] for a in source.authors]
    year = _year(source) or "n.d."
    if not families:
        return f"({_it(_short_title(source))}, {year})"
    if len(families) == 1:
        return f"({families[0]}, {year})"
    if len(families) == 2:
        return f"({families[0]} & {families[1]}, {year})"
    return f"({families[0]} et al., {year})"


def _chicago_names(authors) -> str:
    if not authors:
        return ""
    given, family, suffix = split_name(authors[0])
    first = f"{family}, {given}" if given else family
    if suffix:
        first += f", {suffix}"
    rest = [" ".join(p for p in (split_name(a)[0], split_name(a)[1]) if p) for a in authors[1:]]
    if len(authors) > 10:
        return ", ".join([first] + rest[:6]) + ", et al"
    if not rest:
        return first
    if len(rest) == 1:
        return f"{first}, and {rest[0]}"
    return ", ".join([first] + rest[:-1]) + f", and {rest[-1]}"


def chicago(source: Source) -> str:
    title = source.title or _no_scheme(source.url)
    parts = []
    names = _chicago_names(source.authors)
    if names:
        parts.append(_end(names))
    if source.journal:
        parts.append(f"“{_end(title)}”")
        bit = _it(source.journal)
        if source.volume:
            bit += f" {source.volume}"
        if source.issue:
            bit += f", no. {source.issue}"
        if source.published:
            bit += f" ({_month_day_year(source.published) if source.published[2] else _year(source)})"
        if source.pages:
            bit += f": {source.pages}"
        parts.append(_end(bit))
        parts.append(_end(f"https://doi.org/{source.doi}" if source.doi else source.url))
        return " ".join(parts)
    parts.append(f"“{_end(title)}”")
    if source.site and _site_differs(source):
        parts.append(_end(source.site))
    publisher = _publisher(source)
    if publisher:
        parts.append(_end(publisher))
    if source.published:
        parts.append(_end(_month_day_year(source.published)))
    else:
        parts.append(f"Accessed {_month_day_year(_as_parts(source.accessed))}.")
    if source.url:
        parts.append(_end(source.url))
    return " ".join(parts)


def _journal_bits(source: Source, *, chicago_style: bool = True) -> str:
    """"Nature 12, no. 3 (2020): 45–67" (Chicago) or "Nature 12(3):45–67" (ASA)."""
    text = _it(source.journal)
    if chicago_style:
        if source.volume:
            text += f" {source.volume}"
        if source.issue:
            text += f", no. {source.issue}"
        if source.published:
            text += f" ({_year(source)})"
        if source.pages:
            text += f": {source.pages}"
        return text
    if source.volume:
        text += f" {source.volume}"
        if source.issue:
            text += f"({source.issue})"
    if source.pages:
        text += f":{source.pages}"
    return text


def chicago_note(source: Source) -> str:
    title = source.title or _no_scheme(source.url)
    names = [" ".join(p for p in split_name(a)[:2] if p) for a in source.authors]
    if len(names) > 3:
        who = f"{names[0]} et al."
    elif len(names) == 3:
        who = f"{names[0]}, {names[1]}, and {names[2]}"
    else:
        who = " and ".join(names)
    bits = [who] if who else []
    bits.append(f"“{title},”")
    if source.journal:
        head = (", ".join(bits[:-1]) + ", " if len(bits) > 1 else "") + bits[-1]
        link = f"https://doi.org/{source.doi}" if source.doi else source.url
        return f"1. {head} {_journal_bits(source)}" + (f", {link}." if link else ".")
    tail = []
    if source.site and _site_differs(source):
        tail.append(source.site)
    tail.append(_month_day_year(source.published) if source.published else f"accessed {_month_day_year(_as_parts(source.accessed))}")
    if source.url:
        tail.append(source.url)
    head = (", ".join(bits[:-1]) + ", " if len(bits) > 1 else "") + bits[-1]
    return f"1. {head} {', '.join(tail)}."


def chicago_author_date(source: Source) -> str:
    title = source.title or _no_scheme(source.url)
    names = _chicago_names(source.authors)
    year = _year(source) or "n.d."
    parts = [_end(names) if names else _end(source.site or title), f"{year}."]
    parts.append(f"“{_end(title)}”")
    if source.journal:
        bit = _it(source.journal) + (f" {source.volume}" if source.volume else "")
        bit += f" ({source.issue})" if source.issue else ""
        bit += f": {source.pages}" if source.pages else ""
        parts.append(_end(bit))
        link = f"https://doi.org/{source.doi}" if source.doi else source.url
        if link:
            parts.append(_end(link))
        return " ".join(parts)
    if source.site and _site_differs(source) and names:
        parts.append(_end(source.site))
    if source.published and source.published[1]:
        parts.append(_end(_month_day_year(source.published).replace(f", {year}", "").replace(f" {year}", "")))
    elif not source.published:
        parts.append(f"Accessed {_month_day_year(_as_parts(source.accessed))}.")
    if source.url:
        parts.append(_end(source.url))
    return " ".join(parts)


def _harvard_names(authors) -> str:
    names = []
    for author in authors:
        given, family, _ = split_name(author)
        names.append(f"{family}, {initials(given, space=False)}" if given else family)
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) > 3:
        return f"{names[0]} et al."
    return ", ".join(names[:-1]) + " and " + names[-1]


def harvard(source: Source) -> str:
    title = source.title or _no_scheme(source.url)
    names = _harvard_names(source.authors) or source.site or title
    year = _year(source) or "no date"
    site = f" {_end(source.site)}" if source.site and source.site != names else ""
    accessed = _day_month_year(_as_parts(source.accessed))
    if source.journal:
        vol = f", {source.volume}" + (f"({source.issue})" if source.issue else "") if source.volume else ""
        pages = f", pp. {source.pages}" if source.pages else ""
        link = f" doi:{source.doi}" if source.doi else f" Available at: {source.url} (Accessed: {accessed})" if source.url else ""
        return f"{names} ({year}) ‘{title}’, {_it(source.journal)}{vol}{pages}.{link}".rstrip() + ("." if source.doi else "")
    named_title = _end(_it(title)) if names != title else ""
    return f"{names} ({year}) {named_title}{site} Available at: {source.url} (Accessed: {accessed}).".replace("  ", " ")


def harvard_in_text(source: Source) -> str:
    families = [split_name(a)[1] for a in source.authors]
    year = _year(source) or "no date"
    if not families:
        return f"({source.site or source.title}, {year})"
    if len(families) == 1:
        return f"({families[0]}, {year})"
    if len(families) == 2:
        return f"({families[0]} and {families[1]}, {year})"
    return f"({families[0]} et al., {year})"


def ieee(source: Source) -> str:
    names = []
    for author in source.authors:
        given, family, _ = split_name(author)
        names.append(f"{initials(given)} {family}".strip())
    if len(names) > 6:
        who = f"{names[0]} et al."
    elif len(names) > 2:
        who = ", ".join(names[:-1]) + ", and " + names[-1]
    else:
        who = " and ".join(names)
    title = source.title or _no_scheme(source.url)
    accessed = _month_day_year(_as_parts(source.accessed), _IEEE_MONTHS)
    lead = f"[1] {who}, " if who else "[1] "
    if source.journal:
        bits = [f"“{title},” {_it(source.journal)}"]
        if source.volume:
            bits.append(f"vol. {source.volume}")
        if source.issue:
            bits.append(f"no. {source.issue}")
        if source.pages:
            bits.append(f"pp. {source.pages}")
        if source.published:
            bits.append(_month_day_year(source.published, _IEEE_MONTHS))
        tail = f", doi: {source.doi}." if source.doi else "."
        return lead + ", ".join(bits) + tail
    site = f" {_it(source.site)}." if source.site else ""
    published = f" {_month_day_year(source.published, _IEEE_MONTHS)}." if source.published else ""
    return f"{lead}“{title},”{site}{published} Accessed: {accessed}. [Online]. Available: {source.url}"


def _ama_names(authors) -> str:
    names = []
    for author in authors:
        given, family, _ = split_name(author)
        names.append(f"{family} {initials(given, dots=False, space=False)}".strip())
    if len(names) > 6:
        return ", ".join(names[:3]) + ", et al"
    return ", ".join(names)


def ama(source: Source) -> str:
    title = source.title or _no_scheme(source.url)
    names = _ama_names(source.authors)
    parts = [_end(names)] if names else []
    if source.journal:
        parts.append(_end(title))
        bit = _it(source.journal) + "."
        if source.published:
            bit += f" {_year(source)}"
        if source.volume:
            bit += f";{source.volume}"
        if source.issue:
            bit += f"({source.issue})"
        if source.pages:
            bit += f":{source.pages}"
        parts.append(_end(bit))
        if source.doi:
            parts.append(f"doi:{source.doi}")
        return " ".join(parts)
    parts.append(_end(title))
    if source.site:
        parts.append(_end(_it(source.site)))
    if source.published:
        parts.append(f"Published {_month_day_year(source.published)}.")
    parts.append(f"Accessed {_month_day_year(_as_parts(source.accessed))}.")
    parts.append(source.url)
    return " ".join(parts)


def vancouver(source: Source) -> str:
    names = _ama_names(source.authors)
    title = source.title or _no_scheme(source.url)
    accessed = source.accessed
    cited = f"{accessed.year} {_SHORT_MONTHS[accessed.month - 1]} {accessed.day}"
    year = _year(source)
    if source.journal:
        bit = f"{source.journal}. {year}"
        if source.volume:
            bit += f";{source.volume}"
        if source.issue:
            bit += f"({source.issue})"
        if source.pages:
            bit += f":{source.pages}"
        doi = f" doi:{source.doi}" if source.doi else ""
        return f"{_end(names) + ' ' if names else ''}{_end(title)} {bit}.{doi}"
    where = source.site or _no_scheme(urlsplit(source.url).netloc)
    when = f"; {year}" if year else ""
    lead = f"{_end(names)} " if names else ""
    return f"{lead}{title} [Internet]. {where}{when} [cited {cited}]. Available from: {source.url}"


def asa(source: Source) -> str:
    names = _chicago_names(source.authors)
    year = _year(source) or "N.d."
    title = source.title or _no_scheme(source.url)
    accessed = _month_day_year(_as_parts(source.accessed))
    lead = f"{_end(names)} {year}." if names else f"{_end(source.site or title)} {year}."
    if source.journal:
        doi = f" doi:{source.doi}." if source.doi else (f" Retrieved {accessed} ({source.url})." if source.url else "")
        return f"{lead} “{_end(title)}” {_end(_journal_bits(source, chicago_style=False))}{doi}"
    site =f" {_it(source.site)}" if source.site else ""
    month_day = ""
    if source.published and source.published[1]:
        month_day = ", " + _month_day_year(source.published).replace(f", {year}", "").replace(f" {year}", "")
    return f"{lead} “{_end(title)}”{site}{month_day}. Retrieved {accessed} ({source.url})."


def bibtex(source: Source) -> str:
    families = [split_name(a)[1] for a in source.authors]
    word = re.sub(r"[^a-z]", "", ((source.title or "page").split() or ["page"])[0].lower()) or "page"
    key = (re.sub(r"[^a-z]", "", (families[0] if families else source.site or "web").lower()) or "web") + (_year(source) or "nd") + word
    names = " and ".join(
        f"{split_name(a)[1]}, {split_name(a)[0]}" if split_name(a)[0] else "{" + split_name(a)[1] + "}"
        for a in source.authors
    )
    fields = []
    kind = "article" if source.journal else "misc"
    if names:
        fields.append(f"  author = {{{names}}}")
    fields.append(f"  title = {{{{{source.title or _no_scheme(source.url)}}}}}")
    if source.journal:
        fields.append(f"  journal = {{{source.journal}}}")
        for name, value in (("volume", source.volume), ("number", source.issue), ("pages", re.sub(r"\s*[-–—]+\s*", "--", source.pages))):
            if value:
                fields.append(f"  {name} = {{{value}}}")
        if source.doi:
            fields.append(f"  doi = {{{source.doi}}}")
    elif source.site:
        fields.append(f"  howpublished = {{{source.site}}}")
    if source.published:
        fields.append(f"  year = {{{source.published[0]}}}")
        if source.published[1]:
            fields.append(f"  month = {{{_SHORT_MONTHS[source.published[1] - 1].lower()}}}")
    if source.url:
        fields.append(f"  url = {{{source.url}}}")
    fields.append(f"  urldate = {{{source.accessed.isoformat()}}}")
    return f"@{kind}{{{key},\n" + ",\n".join(fields) + "\n}"


_FORMATTERS = {
    "mla": mla, "apa": apa, "chicago": chicago, "chicago_note": chicago_note, "chicago_ad": chicago_author_date,
    "harvard": harvard, "ieee": ieee, "ama": ama, "vancouver": vancouver, "asa": asa, "turabian": chicago,
    "bibtex": bibtex,
}
_IN_TEXT = {"mla": mla_in_text, "apa": apa_in_text, "harvard": harvard_in_text, "chicago_ad": apa_in_text}


def cite(source: Source, style: str) -> str:
    return _FORMATTERS.get(style, mla)(source)


def in_text(source: Source, style: str) -> str:
    making = _IN_TEXT.get(style)
    if making is None:
        return ""
    made = making(source)
    if style == "chicago_ad":
        made = made.replace(", ", " ").replace(" & ", " and ")
    return made


def block(source: Source, style: str) -> str:
    """One style, ready to paste: the entry, then its in-text form when the style has one."""
    entry = cite(source, style)
    short = in_text(source, style)
    label = STYLES.get(style, style)
    lines = [f"{label}:", entry]
    if short:
        lines.append(f"In text: {short}")
    return "\n".join(lines)


def every_style(source: Source) -> str:
    keys = ["mla", "apa", "chicago", "chicago_note", "chicago_ad", "harvard", "ieee", "ama", "vancouver", "asa", "bibtex"]
    return "\n\n".join(block(source, key) for key in keys)


def missing_note(source: Source) -> str:
    """What the page didn't say, so he can check before handing it in."""
    gaps = []
    if not source.authors:
        gaps.append("no author")
    if not source.published:
        gaps.append("no date")
    if not source.title:
        gaps.append("no title")
    if not gaps:
        return ""
    return "The page lists " + " and ".join(gaps) + ", so the citation leaves " + ("it" if len(gaps) == 1 else "them") + " out."


# ---------- reading the page ----------

class _MetaReader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, list[str]] = {}
        self.title = ""
        self.ld: list[str] = []
        self.canonical = ""
        self._in_title = False
        self._in_ld = False
        self._ld_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (values.get("name") or values.get("property") or values.get("itemprop") or "").strip().lower()
            content = " ".join(values.get("content", "").split())
            if key and content:
                self.meta.setdefault(key, []).append(content)
        elif tag == "title" and not self.title:
            self._in_title = True
        elif tag == "script" and values.get("type", "").lower() == "application/ld+json":
            self._in_ld = True
            self._ld_text = []
        elif tag == "link" and values.get("rel", "").lower() == "canonical" and not self.canonical:
            self.canonical = values.get("href", "")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "script" and self._in_ld:
            self._in_ld = False
            self.ld.append("".join(self._ld_text))

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._in_ld:
            self._ld_text.append(data)


def _ld_items(blobs: list[str]) -> list[dict]:
    items: list[dict] = []

    def walk(value):
        if isinstance(value, dict):
            items.append(value)
            for key in ("@graph", "mainEntity"):
                if key in value:
                    walk(value[key])
        elif isinstance(value, list):
            for entry in value:
                walk(entry)

    for blob in blobs:
        try:
            walk(json.loads(blob))
        except (ValueError, TypeError):
            continue
    return items


def _ld_names(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        name = value.get("name")
        return [name] if isinstance(name, str) else []
    if isinstance(value, list):
        out: list[str] = []
        for entry in value:
            out.extend(_ld_names(entry))
        return out
    return []


_NOT_A_PERSON = re.compile(r"^(?:https?://|@|www\.)|^(?:admin|editor|staff|guest|unknown|anonymous)$", re.IGNORECASE)
_ARTICLE_TYPES = {"article", "newsarticle", "blogposting", "scholarlyarticle", "report", "webpage", "techarticle", "medicalwebpage"}


def _clean_authors(names: list[str]) -> tuple[str, ...]:
    out: list[str] = []
    for name in names:
        for piece in re.split(r"\s*(?:;|\band\b|&|\|)\s*", name or ""):
            piece = re.sub(r"^(?:by|written by)\s+", "", " ".join(piece.split()), flags=re.IGNORECASE).strip(" ,")
            if not piece or _NOT_A_PERSON.search(piece) or len(piece) > 80:
                continue
            if piece.lower() not in {existing.lower() for existing in out}:
                out.append(piece)
    return tuple(out[:25])


def site_from_host(url: str) -> str:
    """"en.wikipedia.org" is "Wikipedia", "www.nytimes.com" is "Nytimes"."""
    host = urlsplit(url or "").netloc.lower().split(":")[0]
    host = re.sub(r"^(?:www\d?|m|en|amp)\.", "", host)
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in {"co", "com", "org", "ac", "gov", "edu", "net"}:
        name = parts[-3]
    elif len(parts) >= 2:
        name = parts[-2]
    else:
        name = host
    return name.capitalize() if name else ""


def _strip_site_from_title(title: str, site: str) -> str:
    title = " ".join((title or "").split())
    if not site:
        return title
    for sep in (" | ", " - ", " — ", " – ", " :: ", " · "):
        if sep in title:
            head, _, tail = title.rpartition(sep)
            if site.lower() in tail.lower() or tail.lower() in site.lower():
                return head.strip()
    return title


def source_from_html(page: str, url: str, accessed: date | None = None) -> Source:
    reader = _MetaReader()
    try:
        reader.feed(page or "")
    except Exception:  # a broken page still has an address and a title
        pass
    meta = reader.meta

    def first(*keys: str) -> str:
        for key in keys:
            values = meta.get(key)
            if values:
                return values[0]
        return ""

    ld = _ld_items(reader.ld)
    article = next((item for item in ld if str(item.get("@type", "")).lower() in _ARTICLE_TYPES or
                    (isinstance(item.get("@type"), list) and any(str(t).lower() in _ARTICLE_TYPES for t in item["@type"]))), {})

    site = first("og:site_name", "citation_journal_title", "application-name", "al:android:app_name")
    if not site:
        publisher_ld = article.get("publisher") if article else None
        site = (_ld_names(publisher_ld) or [""])[0]
    host_site = site_from_host(url)
    site = site or host_site

    authors = list(meta.get("citation_author", []))
    if not authors:
        authors = list(meta.get("dc.creator", []) or meta.get("dcterms.creator", []))
    if not authors and article:
        authors = _ld_names(article.get("author"))
    if not authors:
        authors = [first("author", "article:author", "parsely-author", "sailthru.author", "byl")]
    clean = _clean_authors(authors)
    if clean and site and all(name.lower() == site.lower() for name in clean):
        clean = ()

    title = first("citation_title", "dc.title", "og:title", "twitter:title")
    if not title and article:
        title = str(article.get("headline") or article.get("name") or "")
    title = title or " ".join(reader.title.split())
    title = _strip_site_from_title(html.unescape(title), site)

    published_text = first("citation_publication_date", "citation_date", "citation_online_date", "article:published_time",
                           "dc.date", "dcterms.date", "date", "pubdate", "publish-date", "parsely-pub-date", "sailthru.date")
    if not published_text and article:
        published_text = str(article.get("datePublished") or "")
    if "wikipedia" in site.lower():
        # A wiki page has no one publication; style guides use its last edit.
        modified = (str(article.get("dateModified") or "") if article else "") or first("article:modified_time")
        published_text = modified or published_text
    if not published_text:
        published_text = first("article:modified_time", "og:updated_time") or (str(article.get("dateModified") or "") if article else "")
    published = parse_date(published_text)

    publisher = first("citation_publisher", "dc.publisher", "dcterms.publisher")
    if not publisher and article:
        publisher = (_ld_names(article.get("publisher")) or [""])[0]

    doi = first("citation_doi", "dc.identifier", "prism.doi")
    doi = re.sub(r"^(?:doi:|https?://(?:dx\.)?doi\.org/)", "", doi, flags=re.IGNORECASE)
    if not re.match(r"^10\.\d{4,}/\S+$", doi):
        doi = ""
    pages = ""
    start, stop = first("citation_firstpage"), first("citation_lastpage")
    if start:
        pages = f"{start}–{stop}" if stop and stop != start else start
    journal = first("citation_journal_title") if first("citation_journal_title") and (first("citation_volume") or doi) else ""
    return Source(
        title=title,
        authors=clean,
        site=site if not journal else journal,
        publisher=publisher,
        published=published,
        url=url,
        accessed=accessed or date.today(),
        doi=doi,
        journal=journal,
        volume=first("citation_volume", "prism.volume"),
        issue=first("citation_issue", "prism.number"),
        pages=pages,
    )


def source_from_title(window_title: str, url: str, accessed: date | None = None) -> Source:
    """Without fetching: the tab's title and the address are all there is."""
    site = site_from_host(url)
    return Source(title=_strip_site_from_title(window_title, site), site=site, url=url, accessed=accessed or date.today())


class CitationError(Exception):
    pass


def fetch_page(url: str, timeout: float = 12, limit: int = 3_000_000) -> str:
    """One GET of the page. Only http and https; no cookies, no sign-in."""
    from urllib.request import Request, urlopen
    from urllib.error import URLError

    if not re.match(r"^https?://", url or "", re.IGNORECASE):
        raise CitationError("That isn't a web address, so nothing was fetched.")
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) citation-reader",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en",
    })
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - http(s) only, checked above
            kind = response.headers.get_content_type() or ""
            if "html" not in kind and "xml" not in kind:
                raise CitationError("That address isn't a web page, so I used the tab's title.")
            body = response.read(limit)
            charset = response.headers.get_content_charset() or "utf-8"
    except CitationError:
        raise
    except (URLError, OSError, ValueError) as exc:
        raise CitationError("The page didn't load, so I used the tab's title.") from exc
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def as_record(source: Source) -> dict:
    return {
        "title": source.title, "authors": list(source.authors), "site": source.site, "publisher": source.publisher,
        "published": list(source.published) if source.published else None, "url": source.url,
        "accessed": source.accessed.isoformat(), "doi": source.doi, "journal": source.journal,
        "volume": source.volume, "issue": source.issue, "pages": source.pages,
    }


def from_record(record: dict) -> Source:
    published = record.get("published")
    try:
        accessed = date.fromisoformat(str(record.get("accessed") or ""))
    except ValueError:
        accessed = date.today()
    return Source(
        title=str(record.get("title") or ""), authors=tuple(str(a) for a in record.get("authors") or ()),
        site=str(record.get("site") or ""), publisher=str(record.get("publisher") or ""),
        published=tuple(published) if isinstance(published, list) and published else None,
        url=str(record.get("url") or ""), accessed=accessed, doi=str(record.get("doi") or ""),
        journal=str(record.get("journal") or ""), volume=str(record.get("volume") or ""),
        issue=str(record.get("issue") or ""), pages=str(record.get("pages") or ""),
    )

