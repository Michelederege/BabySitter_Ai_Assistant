"""Word files and plain text files as plain text, on this PC.

The same cap as a Google Doc (80,000 characters). The file is read here and
never uploaded, attached to a search, or sent anywhere. A Word file is a zip
of XML; its words are taken from word/document.xml with the standard library,
so no new package is needed. Macros, pictures, and links are never run or opened.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

TEXT_LIMIT = 80_000  # the same cap as a Google Doc read
FILE_LIMIT = 25 * 1024 * 1024  # a larger file is not opened at all
PLAIN_SUFFIXES = {".txt", ".md", ".csv", ".log", ".json"}
WORD_SUFFIXES = {".docx", ".docm", ".dotx"}
READABLE_SUFFIXES = PLAIN_SUFFIXES | WORD_SUFFIXES

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class FileTextError(Exception):
    """The file could not be read as text. The message says why."""


def readable(name: str) -> bool:
    return Path(name).suffix.lower() in READABLE_SUFFIXES


def word_text(data: bytes, limit: int = TEXT_LIMIT) -> str:
    """The words of a .docx, one paragraph a line. Tables become tab-separated rows."""
    import io

    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        info = archive.getinfo("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise FileTextError("That Word file could not be read. It may be an old .doc, or damaged.") from exc
    if info.file_size > FILE_LIMIT * 4:
        raise FileTextError("That Word file is too large to read.")
    try:
        root = ElementTree.fromstring(archive.read(info))
    except ElementTree.ParseError as exc:
        raise FileTextError("That Word file could not be read.") from exc
    lines: list[str] = []
    size = 0
    for paragraph in root.iter(_W + "p"):
        parts: list[str] = []
        for node in paragraph.iter():
            if node.tag == _W + "t" and node.text:
                parts.append(node.text)
            elif node.tag == _W + "tab":
                parts.append("\t")
            elif node.tag in (_W + "br", _W + "cr"):
                parts.append("\n")
        line = "".join(parts).rstrip()
        if line:
            lines.append(line)
            size += len(line) + 1
            if size > limit:
                break
    return "\n".join(lines)[:limit]


def plain_text(data: bytes, name: str, limit: int = TEXT_LIMIT) -> str:
    """Text from the bytes of a file called name. Raises FileTextError for other kinds."""
    suffix = Path(name).suffix.lower()
    if len(data) > FILE_LIMIT:
        raise FileTextError("That file is larger than 25 MB, so it was not read.")
    if suffix in WORD_SUFFIXES:
        return word_text(data, limit)
    if suffix in PLAIN_SUFFIXES:
        for encoding in ("utf-8-sig", "utf-16"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeError:
                continue
        else:
            text = data.decode("latin-1")
        return re.sub(r"\r\n?", "\n", text)[:limit]
    raise FileTextError(
        "I can read Word files and plain text files. "
        f"A {suffix or 'file without an ending'} is not read; open it instead."
    )


def read_file_text(path: Path, limit: int = TEXT_LIMIT) -> str:
    path = Path(path)
    if not readable(path.name):
        return plain_text(b"", path.name, limit)  # raises the plain explanation
    try:
        if path.stat().st_size > FILE_LIMIT:
            raise FileTextError("That file is larger than 25 MB, so it was not read.")
        data = path.read_bytes()
    except OSError as exc:
        raise FileTextError("That file could not be opened.") from exc
    return plain_text(data, path.name, limit)
