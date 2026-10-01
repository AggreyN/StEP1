"""Job lists published as tables in a README, rather than as JSON.

Most lists on GitHub are a Markdown file with one big table, kept up to date
by a bot. The cells mix Markdown and HTML freely: `**[Acme](https://acme.com)**`,
`<a href="..."><strong>Acme</strong></a>`, an "Apply" button that is an image
inside a link, emoji that mean "closed" or "sponsors visas", and "↳" meaning
"same company as the row above". This module turns such a table into rows of
cells, each with its plain text and its links, and leaves what the columns
mean to each source.

Both pipe tables and HTML <table>s are read.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser

# [text](url), but not ![alt](src): an image is not where the row links to.
_MD_LINK = re.compile(r"(?<!!)\[((?:[^\[\]]|\[[^\]]*\])*)\]\((\s*<?[^)\s>]+>?)(?:\s+\"[^\"]*\")?\)")
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_HREF = re.compile(r"""<a\b[^>]*?\bhref\s*=\s*["']([^"']+)["']""", re.I)
_TAG = re.compile(r"<[^>]+>")
_EMPHASIS = re.compile(r"(\*\*|__|\*|_|~~|`)")
_WS = re.compile(r"\s+")
# Emoji and other pictographs: markers in these lists, never part of a name.
_PICTO = re.compile("[\U0001f000-\U0001faff☀-➿⬀-⯿️‍←-⇿]")

SAME_AS_ABOVE = ("↳", "&#8627;", "&rdsh;")
CLOSED = ("🔒", ":lock:")


@dataclass
class Cell:
    raw: str
    text: str = ""
    links: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.links = cell_links(self.raw)
        self.text = cell_text(self.raw)


def cell_links(raw: str) -> list[str]:
    found: list[str] = []
    for href in [m.group(2).strip().strip("<>") for m in _MD_LINK.finditer(raw)] + [
        m.group(1) for m in _HREF.finditer(raw)
    ]:
        href = html.unescape(href).strip()
        if href.startswith(("http://", "https://")) and href not in found:
            found.append(href)
    return found


def cell_text(raw: str) -> str:
    """What a reader sees in the cell, as plain text."""
    text = _MD_IMAGE.sub(" ", raw)
    text = _MD_LINK.sub(lambda m: m.group(1), text)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = _EMPHASIS.sub("", text)
    text = text.replace("\\|", "|")
    return _WS.sub(" ", text).strip()


def without_markers(text: str) -> str:
    """Text with emoji markers and ":lock:"-style shortcodes removed."""
    text = _PICTO.sub(" ", text)
    text = re.sub(r":[a-z0-9_+-]+:", " ", text)
    return _WS.sub(" ", text).strip(" -|·")


# --------------------------------------------------------------------------- #
# Pipe tables
# --------------------------------------------------------------------------- #

_SEPARATOR = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    # A pipe escaped as \| is part of a cell.
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)]


def pipe_tables(markdown: str) -> list[list[dict[str, Cell]]]:
    """Every pipe table: a list of rows, each {lowercased header: Cell}."""
    tables: list[list[dict[str, Cell]]] = []
    lines = markdown.splitlines()
    i = 0
    while i < len(lines) - 1:
        if lines[i].lstrip().startswith("|") and _SEPARATOR.match(lines[i + 1].strip()):
            headers = [cell_text(h).lower() for h in _split_row(lines[i])]
            rows = []
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                cells = _split_row(lines[i])
                if len(cells) >= len(headers):
                    rows.append({h: Cell(c) for h, c in zip(headers, cells, strict=False)})
                i += 1
            tables.append(rows)
        else:
            i += 1
    return tables


# --------------------------------------------------------------------------- #
# HTML tables
# --------------------------------------------------------------------------- #


class _Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.tables: list[list[list[str]]] = []
        self._cell: list[str] | None = None
        self._row: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif self._cell is not None:
            self._cell.append(self.get_starttag_text() or "")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.tables[-1].append(self._row)
            self._row = None
        elif self._cell is not None:
            self._cell.append(f"</{tag}>")

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_entityref(self, name):
        if self._cell is not None:
            self._cell.append(f"&{name};")

    def handle_charref(self, name):
        if self._cell is not None:
            self._cell.append(f"&#{name};")


def html_tables(markdown: str) -> list[list[dict[str, Cell]]]:
    parser = _Tables()
    parser.feed(markdown)
    out = []
    for table in parser.tables:
        if len(table) < 2:
            continue
        headers = [cell_text(h).lower() for h in table[0]]
        out.append(
            [
                {h: Cell(c) for h, c in zip(headers, row, strict=False)}
                for row in table[1:]
                if len(row) >= len(headers)
            ]
        )
    return out


def tables(markdown: str) -> list[list[dict[str, Cell]]]:
    return pipe_tables(markdown) + html_tables(markdown)


# --------------------------------------------------------------------------- #
# Values these lists write the same way
# --------------------------------------------------------------------------- #


def column(row: dict[str, Cell], *names: str) -> Cell | None:
    """The first cell whose header is, or starts with, one of `names`."""
    for name in names:
        if name in row:
            return row[name]
    for name in names:
        for header, cell in row.items():
            if header.startswith(name):
                return cell
    return None


def is_same_as_above(cell: Cell | None) -> bool:
    return cell is not None and any(m in cell.raw for m in SAME_AS_ABOVE)


def is_closed(row: dict[str, Cell]) -> bool:
    return any(m in cell.raw for cell in row.values() for m in CLOSED)


def split_locations(text: str) -> list[str]:
    """ "Austin, TX; Remote" / "NYC, NY +3" / "San Diego, California, United..." """
    text = re.sub(r"\s*\+\s*\d+\s*$", "", text)  # "+3 more"
    text = re.sub(r"\.{3}|…", "", text)  # truncated by the list
    parts = re.split(r"\s*(?:;|</?br\s*/?>|\s{2,}|\|)\s*", text)
    return [p.strip(" ,") for p in parts if p.strip(" ,")]


_AGE = re.compile(r"^\s*(\d+)\s*(mo|m|h|d|w|y)\b", re.I)


def age_to_date(age: str, today: date) -> datetime | None:
    """ "0d", "4d", "2w", "3mo", "18m" (minutes), "1h" -> the day it was posted.
    To the day, so that a row's content does not change between two fetches
    on the same day."""
    m = _AGE.match(age or "")
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    days = {"m": 0, "h": 0, "d": n, "w": 7 * n, "mo": 30 * n, "y": 365 * n}[unit]
    day = today - timedelta(days=days)
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def month_day_to_date(text: str, today: date) -> datetime | None:
    """ "Sep 30" with no year: the most recent such day, today or before."""
    for fmt in ("%b %d", "%B %d"):
        try:
            parsed = datetime.strptime(text.strip(), fmt)
        except ValueError:
            continue
        year = today.year
        try:
            day = date(year, parsed.month, parsed.day)
        except ValueError:  # Feb 29 in a year without one
            return None
        if day > today + timedelta(days=1):
            day = date(year - 1, parsed.month, parsed.day)
        return datetime(day.year, day.month, day.day, tzinfo=UTC)
    return None


_PAY = re.compile(r"\$\s*([\d,.]+)\s*(k)?\s*(?:/|\s*per\s*)\s*(hr|hour|h|yr|year|y)\b", re.I)


def salary(text: str):
    """ "$58/hr" -> (58, 58, "hour"); "$172k/yr" -> (172000, 172000, "year")."""
    from decimal import Decimal, InvalidOperation

    m = _PAY.search(text or "")
    if not m:
        return None, None, None
    try:
        amount = Decimal(m.group(1).replace(",", ""))
    except InvalidOperation:
        return None, None, None
    if m.group(2):
        amount *= 1000
    unit = "hour" if m.group(3).lower().startswith("h") else "year"
    return amount, amount, unit
