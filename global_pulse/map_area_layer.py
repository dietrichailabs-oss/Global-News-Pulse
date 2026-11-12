"""Qt rendering of attributed warning polygons, separate from point markers."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainterPath, QPen

from .map_evidence import wrapped_polygons
from .theme import SEVERITY


class WarningAreaLayer:
    MAX_AREAS = 200
    MAX_VERTICES = 100_000

    def __init__(self, owner):
        self.owner = owner
        self.paths = []
        self.omitted = 0

    def set_events(self, events):
        self.paths = []
        self.omitted = 0
        vertices = 0
        for event in events:
            context = event.get("status") == "pending" and event.get("map_history_incomplete") is True
            if (event.get("status", "active") != "active" and not context) or event.get("future_dated"):
                continue
            for area in event.get("map_areas", [])[:32]:
                if context and (not isinstance(area, dict) or area.get("context_only") is not True):
                    continue
                try:
                    polygons = list(wrapped_polygons(area.get("geometry")))
                except (AttributeError, ValueError, TypeError):
                    self.omitted += 1
                    continue
                size = sum(len(ring) for polygon in polygons for ring in polygon)
                if len(self.paths) >= self.MAX_AREAS or vertices + size > self.MAX_VERTICES:
                    self.omitted += 1
                    continue
                vertices += size
                path = QPainterPath()
                path.setFillRule(Qt.FillRule.OddEvenFill)
                for polygon in polygons:
                    for ring in polygon:
                        path.moveTo(self.owner.normalized(*ring[0]))
                        for position in ring[1:]:
                            path.lineTo(self.owner.normalized(*position))
                        path.closeSubpath()
                self.paths.append((path, event, area))

    def visible(self):
        categories = self.owner.categories
        return [(path, event, area) for path, event, area in self.paths
                if categories is None or event.get("category") in categories]

    def paint(self, painter):
        painter.save()
        transform = self.owner._transform()
        for path, event, _area in self.visible():
            context = _area.get("context_only") is True
            color = QColor(SEVERITY.get("unassessed" if context else event.get("severity"), SEVERITY["unassessed"]))
            fill = QColor(color)
            fill.setAlpha(20 if context else 55)
            pen = QPen(QColor("#f1e5ff") if str(event.get("id")) == self.owner.selected_event else color, 1.5)
            if context:pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(fill)
            painter.drawPath(transform.map(path))
        painter.restore()

    def hit(self, position):
        inverse, valid = self.owner._transform().inverted()
        if valid:
            point = inverse.map(position)
            for path, event, area in reversed(self.visible()):
                if path.contains(point):
                    return event, area
        return None
