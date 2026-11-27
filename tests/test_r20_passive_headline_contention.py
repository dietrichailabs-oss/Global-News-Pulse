"""Retain the independent one-pass Qt row regression.

The experimental nonblocking timer implementation and its feature-specific
test are preserved at 03a72dc7, but not part of this rollback candidate.
The original deferred-routing, consent, and loaded responsiveness tests
remain in the suite unchanged.
"""
from types import SimpleNamespace
from PySide6.QtCore import Qt
from global_pulse.ui import MainWindow


def test_passive_refresh_reads_each_row_once_and_uses_updated_selected_identity():
    class Item:
        def __init__(self, index):
            self.row = {"id": str(index), "title": f"Original {index}",
                        "_display_title": f"Original {index}",
                        "_translation_label": "Original headline",
                        "_situation_starred": index == 499}
            self.reads = 0
            self.display = self.row["title"]

        def data(self, role):
            assert role == Qt.ItemDataRole.UserRole
            self.reads += 1
            return dict(self.row)

        def text(self):
            return self.display

        def setText(self, value):
            self.display = value

        def setData(self, role, value):
            assert role == Qt.ItemDataRole.UserRole
            self.row = dict(value)

        def setToolTip(self, value):
            self.tip = value

    rows = [Item(i) for i in range(500)]
    rendered = []
    restored = []
    bar = SimpleNamespace(value=lambda: 42, setValue=restored.append)
    window = SimpleNamespace(
        feed_list=SimpleNamespace(count=lambda: len(rows), item=rows.__getitem__),
        english_headlines=SimpleNamespace(isChecked=lambda: True),
        _selected_id="499", _history_at=None,
        controller=SimpleNamespace(headline_view=lambda event, **kw: {
            "title": "Translated " + event["id"], "original": event["title"],
            "label": "Machine translated"}),
        intel_browser=SimpleNamespace(verticalScrollBar=lambda: bar),
        _render_event=lambda event, **kw: rendered.append((event, kw)),
        _selected_event=lambda: (_ for _ in ()).throw(AssertionError("unexpected Store read")),
    )
    MainWindow._refresh_translated_headlines(window)
    assert all(item.reads == 1 for item in rows)
    assert all(item.display == "Translated " + item.row["id"] for item in rows)
    assert rendered == [(rows[-1].row, {"update_media": False,
                                       "english_enabled": True, "starred_override": True})]
    assert restored == [42]
