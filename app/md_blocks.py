"""Markdown → block-model parser (shared by all MD exporters).

Parses Markdown text into a flat list of typed blocks that the DOCX, PPTX
and PDF exporters consume. Handles the subset produced by this app plus
common hand-written lecture notes:

- YAML front matter (skipped)
- ATX headings ``#`` … ``######``
- paragraphs (lazy continuation joined with spaces)
- bullet/numbered lists with nesting (2- or 4-space indents), soft wraps
- GFM tables (``| a | b |`` + ``|---|---|`` separator)
- fenced code blocks (```lang)
- block quotes
- horizontal rules (``---``, ``***``)
- standalone images ``![alt](src)``
- inline formatting: **bold**, *italic*, `code`, [text](url), inline images

Images are kept as the raw source string; exporters resolve them against
the .md file's directory (``base_dir``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ------------------------------------------------------------------ model


@dataclass
class Run:
    """Inline run: plain text possibly marked bold/italic/code/link/image."""

    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    href: Optional[str] = None
    image: bool = False  # href points at an image source

    def plain(self) -> str:
        return self.text


@dataclass
class Heading:
    level: int
    runs: list[Run] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


@dataclass
class Paragraph:
    runs: list[Run] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


@dataclass
class ListItem:
    level: int
    ordered: bool
    runs: list[Run] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


@dataclass
class ListBlock:
    items: list[ListItem] = field(default_factory=list)


@dataclass
class TableBlock:
    header: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)


@dataclass
class CodeBlock:
    text: str = ""
    lang: str = ""


@dataclass
class QuoteBlock:
    paragraphs: list[Paragraph] = field(default_factory=list)


@dataclass
class ImageBlock:
    alt: str = ""
    src: str = ""

    @property
    def text(self) -> str:
        return self.alt


@dataclass
class RuleBlock:
    pass


Block = object  # union of the dataclasses above (documented, not enforced)

# --------------------------------------------------------------- patterns

_RE_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_RE_FENCE = re.compile(r"^\s*(```|~~~)\s*([A-Za-z0-9_+-]*)\s*$")
_RE_RULE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
_RE_LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")
_RE_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_RE_BULLET_ONLY = re.compile(r"^\s*([-*+]|\d{1,9}[.)])\s*$")

_RE_INLINE = re.compile(
    r"!\[(?P<imgalt>[^\]]*)\]\((?P<imgsrc>[^)]+)\)"
    r"|\[(?P<linktext>[^\]]+)\]\((?P<linkhref>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
    r"|(?P<strong>\*\*|__)(?P<stronginner>.+?)(?P=strong)"
    r"|(?P<em>\*|_)(?P<eminner>[^*_]+?)(?P=em)"
    r"|(?P<code>`)(?P<codeinner>[^`]+?)(?P=code)"
)


# ------------------------------------------------------------- inline API

def parse_inline(text: str) -> list[Run]:
    """Parse inline markdown into a list of Runs."""
    runs: list[Run] = []
    pos = 0
    for match in _RE_INLINE.finditer(text):
        if match.start() > pos:
            runs.append(Run(text[pos:match.start()]))
        if match.group("imgalt") is not None:
            src = match.group("imgsrc").strip()
            title = re.match(r'^(.*?)\s+"[^"]*"$', src)
            if title:
                src = title.group(1)
            runs.append(Run(text=match.group("imgalt") or "image", href=src, image=True))
        elif match.group("linktext") is not None:
            inner = parse_inline(match.group("linktext"))
            href = match.group("linkhref")
            if len(inner) == 1:
                inner[0].href = href
                runs.append(inner[0])
            else:
                runs.append(Run(text="".join(r.text for r in inner), href=href))
        elif match.group("strong") is not None:
            inner = parse_inline(match.group("stronginner"))
            for run in inner:
                run.bold = True
            runs.extend(inner)
        elif match.group("em") is not None:
            inner = parse_inline(match.group("eminner"))
            for run in inner:
                run.italic = True
            runs.extend(inner)
        elif match.group("code") is not None:
            runs.append(Run(text=match.group("codeinner"), code=True))
        pos = match.end()
    if pos < len(text):
        runs.append(Run(text[pos:]))
    return [r for r in runs if r.text]


def runs_plain(runs: list[Run]) -> str:
    return "".join(r.text for r in runs)


# ------------------------------------------------------------------ files

def _skip_front_matter(lines: list[str]) -> list[str]:
    if lines and lines[0].strip() == "---":
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                return lines[idx + 1:]
    return lines


def _split_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and not stripped.endswith("\\|"):
        stripped = stripped[:-1]
    return [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", stripped)]


def _is_table_separator(line: str) -> bool:
    if "|" not in line:
        return False
    cells = _split_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{1,}:?", cell) for cell in cells)


def _is_block_start(line: str) -> bool:
    """True when a line begins a new block (ends lazy paragraph continuation)."""
    return bool(
        _RE_HEADING.match(line)
        or _RE_FENCE.match(line)
        or _RE_RULE.match(line)
        or _RE_LIST_ITEM.match(line)
        or _RE_QUOTE.match(line)
    )


def _indent_level(indent: str) -> int:
    width = len(indent.replace("\t", "    "))
    if width == 0:
        return 0
    if width % 4 == 0:
        level = width // 4          # 4-space style
    else:
        level = width // 2          # 2-space style
    return min(3, level)


# --------------------------------------------------------------- the API

def parse_markdown(text: str) -> list[object]:
    """Parse markdown text into a flat list of block objects."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = _skip_front_matter(lines)

    blocks: list[object] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]

        # --- fenced code block -------------------------------------------
        fence = _RE_FENCE.match(line)
        if fence:
            marker, lang = fence.group(1), fence.group(2)
            body: list[str] = []
            i += 1
            while i < n and not lines[i].strip().startswith(marker[:3]):
                body.append(lines[i])
                i += 1
            i += 1  # skip closing fence (or EOF)
            blocks.append(CodeBlock(text="\n".join(body), lang=lang))
            continue

        # --- heading -------------------------------------------------------
        heading = _RE_HEADING.match(line)
        if heading:
            blocks.append(Heading(level=len(heading.group(1)),
                                  runs=parse_inline(heading.group(2))))
            i += 1
            continue

        # --- horizontal rule ----------------------------------------------
        if _RE_RULE.match(line):
            blocks.append(RuleBlock())
            i += 1
            continue

        # --- block quote ---------------------------------------------------
        if _RE_QUOTE.match(line):
            quote = QuoteBlock()
            current: list[str] = []
            while i < n and _RE_QUOTE.match(lines[i]):
                content = _RE_QUOTE.match(lines[i]).group(1)  # type: ignore[union-attr]
                if content.strip():
                    current.append(content.strip())
                else:
                    if current:
                        quote.paragraphs.append(Paragraph(runs=parse_inline(" ".join(current))))
                        current = []
                i += 1
            if current:
                quote.paragraphs.append(Paragraph(runs=parse_inline(" ".join(current))))
            if quote.paragraphs:
                blocks.append(quote)
            continue

        # --- table ----------------------------------------------------------
        if "|" in line and i + 1 < n and _is_table_separator(lines[i + 1]):
            header = _split_row(line)
            i += 2
            rows: list[list[str]] = []
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(_split_row(lines[i]))
                i += 1
            width = max([len(header)] + [len(r) for r in rows])
            header += [""] * (width - len(header))
            rows = [r + [""] * (width - len(r)) for r in rows]
            blocks.append(TableBlock(header=header, rows=rows))
            continue

        # --- list ------------------------------------------------------------
        item_match = _RE_LIST_ITEM.match(line)
        if item_match and not _RE_RULE.match(line):
            block = ListBlock()
            while i < n:
                m = _RE_LIST_ITEM.match(lines[i])
                if m and not _RE_RULE.match(lines[i]):
                    marker = m.group(2)
                    ordered = marker[0].isdigit()
                    block.items.append(ListItem(
                        level=_indent_level(m.group(1)),
                        ordered=ordered,
                        runs=parse_inline(m.group(3).strip()),
                    ))
                    i += 1
                elif lines[i].strip() and block.items and not _is_block_start(lines[i]):
                    # soft-wrapped continuation of the previous item
                    last = block.items[-1]
                    last.runs = parse_inline(last.text + " " + lines[i].strip())
                    i += 1
                else:
                    break
            blocks.append(block)
            continue

        # --- blank line -------------------------------------------------------
        if not line.strip():
            i += 1
            continue

        # --- standalone image --------------------------------------------------
        stripped = line.strip()
        img_only = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", stripped)
        if img_only and not blocks_needing_paragraph(blocks):
            src = img_only.group(2).strip()
            title = re.match(r'^(.*?)\s+"[^"]*"$', src)
            if title:
                src = title.group(1)
            blocks.append(ImageBlock(alt=img_only.group(1), src=src))
            i += 1
            continue

        # --- paragraph (lazy continuation) ---------------------------------------
        para_lines = [stripped]
        i += 1
        while i < n and lines[i].strip() and not _is_block_start(lines[i]):
            para_lines.append(lines[i].strip())
            i += 1
        blocks.append(Paragraph(runs=parse_inline(" ".join(para_lines))))

    return blocks


def blocks_needing_paragraph(blocks: list[object]) -> bool:
    """An image directly after a paragraph joins that paragraph (inline flow)."""
    return bool(blocks) and isinstance(blocks[-1], Paragraph)


def parse_file(path: Path) -> list[object]:
    """Parse a .md file from disk (utf-8, BOM tolerated)."""
    return parse_markdown(path.read_text(encoding="utf-8-sig"))


# ------------------------------------------------------------------ HTML
# (used by the PDF exporter; keeps unicode/math intact)

def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def run_to_html(run: Run, image_resolver=None) -> str:
    if run.image and run.href:
        src = image_resolver(run.href) if image_resolver else run.href
        return f'<img src="{_escape(src)}" alt="{_escape(run.text)}"/>'
    inner = _escape(run.text)
    if run.code:
        inner = f"<code>{inner}</code>"
    if run.bold:
        inner = f"<strong>{inner}</strong>"
    if run.italic:
        inner = f"<em>{inner}</em>"
    if run.href:
        inner = f'<a href="{_escape(run.href)}">{inner}</a>'
    return inner


def runs_to_html(runs: list[Run], image_resolver=None) -> str:
    return "".join(run_to_html(r, image_resolver) for r in runs)


def blocks_to_html(blocks: list[object], image_resolver=None) -> str:
    """Render the block model as a complete HTML fragment."""
    out: list[str] = []
    list_stack: list[str] = []

    def close_lists(depth: int = 0) -> None:
        while len(list_stack) > depth:
            out.append(f"</{list_stack.pop()}>")

    for block in blocks:
        if isinstance(block, Heading):
            close_lists()
            level = min(6, max(1, block.level))
            out.append(f"<h{level}>{runs_to_html(block.runs, image_resolver)}</h{level}>")
        elif isinstance(block, Paragraph):
            close_lists()
            out.append(f"<p>{runs_to_html(block.runs, image_resolver)}</p>")
        elif isinstance(block, ListBlock):
            for item in block.items:
                depth = item.level + 1
                tag = "ol" if item.ordered else "ul"
                while len(list_stack) < depth:
                    list_stack.append(tag)
                    out.append(f"<{tag}>")
                while len(list_stack) > depth:
                    out.append(f"</{list_stack.pop()}>")
                if list_stack and list_stack[-1] != tag:  # ol ↔ ul switch
                    out.append(f"</{list_stack.pop()}>")
                    list_stack.append(tag)
                    out.append(f"<{tag}>")
                out.append(f"<li>{runs_to_html(item.runs, image_resolver)}</li>")
            close_lists()
        elif isinstance(block, TableBlock):
            close_lists()
            out.append("<table>")
            out.append("<tr>" + "".join(f"<th>{_escape(c)}</th>" for c in block.header) + "</tr>")
            for row in block.rows:
                out.append("<tr>" + "".join(f"<td>{_escape(c)}</td>" for c in row) + "</tr>")
            out.append("</table>")
        elif isinstance(block, CodeBlock):
            close_lists()
            lang = f' class="lang-{_escape(block.lang)}"' if block.lang else ""
            out.append(f"<pre><code{lang}>{_escape(block.text)}</code></pre>")
        elif isinstance(block, QuoteBlock):
            close_lists()
            inner = "".join(f"<p>{runs_to_html(p.runs, image_resolver)}</p>"
                            for p in block.paragraphs)
            out.append(f"<blockquote>{inner}</blockquote>")
        elif isinstance(block, ImageBlock):
            close_lists()
            src = image_resolver(block.src) if image_resolver else block.src
            out.append(f'<p><img src="{_escape(src)}" alt="{_escape(block.alt)}"/></p>')
        elif isinstance(block, RuleBlock):
            close_lists()
            out.append("<hr/>")
    close_lists()
    return "\n".join(out)
