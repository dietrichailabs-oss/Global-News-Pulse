"""Source-linked briefs with the same severity palette as the map and feed."""
from PySide6.QtGui import QTextDocument, QTextCursor, QTextCharFormat, QColor
from .core import build_brief
from .theme import PANEL, PURPLE, SEVERITY, TEXT


def brief_html(events, period="daily"):
    document = QTextDocument()
    document.setMarkdown(build_brief(events, period))
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
