"""Source-linked briefs with the same severity palette as the map and feed."""
from PySide6.QtGui import QTextDocument, QTextCursor, QTextCharFormat, QColor
from .core import build_brief
from .theme import PANEL, PURPLE, SEVERITY, TEXT


def brief_html(events, period="daily", *, markdown=None):
    document = QTextDocument()
    document.setMarkdown(build_brief(events, period) if markdown is None else markdown)
    # The document is used both in the dark Qt preview and as standalone HTML.
    # Export an explicit matching canvas so source links stay readable in both
    # places rather than inheriting Qt's dark-blue default or a white browser.
    frame_format = document.rootFrame().frameFormat()
    frame_format.setBackground(QColor(PANEL))
    document.rootFrame().setFrameFormat(frame_format)
    cursor = QTextCursor(document)
    cursor.select(QTextCursor.SelectionType.Document)
    text_format = QTextCharFormat()
    text_format.setForeground(QColor(TEXT))
    cursor.mergeCharFormat(text_format)
    link_ranges = []
    block = document.begin()
    while block.isValid():
        text = block.text()
        if text.startswith("Severity: "):
            name = text[10:].split(" · ", 1)[0].strip().lower()
            if name in SEVERITY:
                cursor = QTextCursor(block)
                cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor, 10)
                cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, len(name))
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(SEVERITY[name]))
                fmt.setFontWeight(700)
                cursor.mergeCharFormat(fmt)
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid() and fragment.charFormat().isAnchor() and fragment.charFormat().anchorHref():
                link_ranges.append((fragment.position(), fragment.length()))
            iterator += 1
        block = block.next()
    # Collect first: merging formats while walking fragments can merge them.
    # Only presentation changes; hrefs and the browser's safe-link handler stay
    # untouched, and no network resource is loaded by this renderer.
    link_format = QTextCharFormat()
    link_format.setForeground(QColor(PURPLE))
    link_format.setFontUnderline(True)
    for position, length in link_ranges:
        cursor = QTextCursor(document)
        cursor.setPosition(position)
        cursor.setPosition(position + length, QTextCursor.MoveMode.KeepAnchor)
        cursor.mergeCharFormat(link_format)
    return document.toHtml()


# Preview pagination changes only on-screen layout, not the admitted evidence
# or the original complete Markdown/HTML export. Split at generated Markdown
# paragraph boundaries; never cut through a URL, inline format, or source row.
PREVIEW_PAGE_BYTES = 32 * 1024


def brief_markdown_pages(markdown):
    import re
    if len(markdown.encode("utf-8")) <= PREVIEW_PAGE_BYTES:
        return (markdown,)
    pieces = re.split(r"(\n\n+)", markdown)
    pages, current, size = [], [], 0
    for offset in range(0, len(pieces), 2):
        block = "".join(pieces[offset:offset + 2])
        if not block:
            continue
        length = len(block.encode("utf-8"))
        if current and size + length > PREVIEW_PAGE_BYTES:
            pages.append("".join(current))
            current, size = [], 0
        current.append(block)
        size += length
    if current:
        pages.append("".join(current))
    return tuple(pages)


def brief_preview_pages(markdown, full_html, period):
    parts = brief_markdown_pages(markdown)
    if len(parts) == 1:
        return (full_html,)
    return tuple(brief_html([], period, markdown=part) for part in parts)
