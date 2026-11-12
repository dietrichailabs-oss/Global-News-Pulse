"""Source-linked briefs with the same severity palette as the map and feed."""
from PySide6.QtGui import QTextDocument, QTextCursor, QTextCharFormat, QColor
from .core import build_brief
from .theme import SEVERITY


def brief_html(events, period="daily"):
    document = QTextDocument()
    document.setMarkdown(build_brief(events, period))
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
        block = block.next()
    return document.toHtml()
