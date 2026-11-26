"""Qt rendering of attributed warning polygons, separate from point markers."""
from __future__ import annotations

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QPainterPath, QPen, QPolygonF

from .map_evidence import wrapped_polygons
from .theme import SEVERITY


MAX_AREAS=200
MAX_VERTICES=100_000


def normalized_coordinates(lon,lat):
    return ((lon+180.0)/360.0,(85.0-lat)/145.0)


def prepare_warning_areas(events):
    """Plain immutable geometry preparation; safe off the GUI thread."""
    entries=[]
    omitted=0
    vertices=0
    for event in events:
        context=event.get("status")=="pending" and event.get("map_history_incomplete") is True
        if (event.get("status","active")!="active" and not context) or event.get("future_dated"):
            continue
        for area in event.get("map_areas",[])[:32]:
            if context and (not isinstance(area,dict) or area.get("context_only") is not True):
                continue
            try:
                polygons=list(wrapped_polygons(area.get("geometry")))
            except (AttributeError,ValueError,TypeError):
                omitted+=1
                continue
            size=sum(len(ring) for polygon in polygons for ring in polygon)
            if len(entries)>=MAX_AREAS or vertices+size>MAX_VERTICES:
                omitted+=1
                continue
            vertices+=size
            rings=tuple(tuple(normalized_coordinates(*position) for position in ring)
                        for polygon in polygons for ring in polygon)
            entries.append((rings,event,area))
    return {"record_ids":tuple(id(event) for event in events),
            "entries":tuple(entries),"omitted":omitted}


class WarningAreaLayer:
    MAX_AREAS = MAX_AREAS
    MAX_VERTICES = MAX_VERTICES

    def __init__(self, owner):
        self.owner = owner
        self.paths = []
        self.omitted = 0
        self._visible_key = None
        self._visible_paths = ()
        self._geometry_paths = {}

    def set_events(self, events, *, prepared=None):
        if (not isinstance(prepared,dict) or
                prepared.get("record_ids")!=tuple(id(event) for event in events)):
            prepared=prepare_warning_areas(events)
        old=self._geometry_paths
        cache={}
        paths=[]
        for rings,event,area in prepared["entries"]:
            path=old.get(rings)
            if path is None:
                path=cache.get(rings)
            if path is None:
                path=QPainterPath()
                path.setFillRule(Qt.FillRule.OddEvenFill)
                for ring in rings:
                    path.addPolygon(QPolygonF([QPointF(*position) for position in ring]))
                    path.closeSubpath()
            cache[rings]=path
            paths.append((path,event,area))
        # Only bounded current geometry is retained. Reuse the value path,
        # never the superseded source/area references.
        self._geometry_paths=cache
        self.paths=paths
        self.omitted=prepared["omitted"]
        self._visible_key=None
        self._visible_paths=()

    def visible(self):
        categories = self.owner.categories
        key = (id(self.paths), len(self.paths),
               None if categories is None else frozenset(categories),
               self.owner.disabled_hazards())
        if key != self._visible_key:
            self._visible_paths = tuple(
                (path,event,area) for path,event,area in self.paths
                if (categories is None or event.get("category") in categories)
                and self.owner.warning_area_visible(event, area))
            self._visible_key = key
        # Keep the original list-return contract and do not expose the cache
        # itself to a caller that might mutate the returned collection.
        return list(self._visible_paths)

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
