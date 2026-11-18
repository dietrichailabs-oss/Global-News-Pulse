"""Global Pulse native desktop workstation.

All network and analysis work is delegated to the controller. UI-originated text
is rendered as plain text or escaped HTML. No source HTML is executed here.
"""
from __future__ import annotations

import html
import json
import math
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt, Signal, Slot, QByteArray, QTimer, QPoint, QPointF, QRect, QRectF, QSize, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QKeySequence, QShortcut, QTextDocument, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton, QToolButton,
    QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QLineEdit, QComboBox,
    QSplitter, QStackedWidget, QListWidget, QListWidgetItem, QTextBrowser,
    QTableWidget, QTableWidgetItem, QTableView, QHeaderView, QCheckBox, QSpinBox, QTimeEdit,
    QSlider, QGroupBox, QScrollArea, QFileDialog, QMessageBox, QCompleter,
    QAbstractItemView, QStyledItemDelegate, QStyle, QSizeGrip, QMenu, QInputDialog, QSizePolicy,
)

from .map_widget import WorldMap, CATEGORY_COLORS
from .situation_actions import SituationActions
from .theme import STYLE, SEVERITY


def esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def timestamp(value):
    if not value:
        return "Not yet retrieved"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%d %b %H:%M UTC")
    except (ValueError, TypeError):
        return str(value)[:40]


def geometry_has_useful_screen_overlap(frame, available_rects, min_width=80, min_height=48):
    """Return whether enough of a saved frame is reachable on a current screen."""
    if not isinstance(frame, QRect) or not frame.isValid():
        return False
    required_width=min(max(1,int(min_width)),frame.width())
    required_height=min(max(1,int(min_height)),frame.height())
    for area in available_rects:
        if not isinstance(area,QRect) or not area.isValid():
            continue
        overlap=frame.intersected(area)
        if overlap.width()>=required_width and overlap.height()>=required_height:
            return True
    return False


def recovered_window_rect(frame, available, minimum=QSize(960,640)):
    """Fit an unreachable top-level window into one current work area."""
    if not isinstance(available,QRect) or not available.isValid():
        return QRect(frame)
    source=frame if isinstance(frame,QRect) and frame.isValid() else QRect(available.topLeft(),minimum)
    width=min(max(minimum.width(),source.width()),available.width())
    height=min(max(minimum.height(),source.height()),available.height())
    x=available.left()+max(0,(available.width()-width)//2)
    y=available.top()+max(0,(available.height()-height)//2)
    return QRect(x,y,width,height)


def report_time(record):
    if record.get("publication_time_known") is False or record.get("publication_time_unknown"):
        return "First retrieved " + timestamp(record.get("first_retrieved_at") or record.get("retrieved_at")) + " · publication time unknown"
    return timestamp(record.get("published_at") or record.get("updated_at"))


def row(*widgets, stretch=False):
    layout = QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for widget in widgets:
        layout.addWidget(widget)
    if stretch:
        layout.addStretch()
    return layout


def label(text="", name=None, wrap=False):
    w = QLabel(text)
    w.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    return w


def button(text, callback=None, tooltip=None, checkable=False):
    b = QPushButton(text)
    b.setCheckable(checkable)
    if callback:
        b.clicked.connect(callback)
    if tooltip:
        b.setToolTip(tooltip)
        b.setAccessibleName(tooltip)
    return b


class Panel(QFrame):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(7, 6, 7, 6)
        self.layout.setSpacing(5)
        self.heading = row(label(title, "SectionTitle"))
        self.heading.addStretch()
        self.layout.addLayout(self.heading)


class RadarLogo(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(32, 32)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#8e70c9"), 1))
        for r in (6, 11, 15):
            p.drawEllipse(QPointF(16, 16), r, r)
        p.setPen(QPen(QColor("#c2a8f8"), 2))
        p.drawLine(QPointF(16, 16), QPointF(26, 6))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor("#dbc9ff"))
        p.drawEllipse(QPointF(20, 13), 2, 2)
        p.drawEllipse(QPointF(9, 21), 1.5, 1.5)


class TitleBar(QFrame):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setObjectName("TitleBar")
        self.setFixedHeight(42)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 4, 0, 4)
        layout.setSpacing(10)
        layout.addWidget(RadarLogo())
        layout.addWidget(label("GLOBAL PULSE", "Brand"))
        self.tagline = label("INTELLIGENCE WORKSTATION", "Eyebrow")
        layout.addWidget(self.tagline)
        layout.addStretch()
        self.status = label("PAUSED", "LiveBadge")
        layout.addWidget(self.status)
        for text, name, fn in (("−", "Minimize", window.showMinimized), ("□", "Maximize or restore", self.toggle_maximized), ("×", "Close window", window.close)):
            b = QToolButton()
            b.setText(text)
            b.setObjectName("WindowControl" if text != "×" else "WindowClose")
            b.setFixedSize(37, 33)
            b.setToolTip(name); b.setAccessibleName(name)
            b.clicked.connect(fn)
            layout.addWidget(b)
            if text == "□": self.maximize_button = b

    def toggle_maximized(self):
        self.window.showNormal() if self.window.isMaximized() else self.window.showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.window.windowHandle():
            self.window.windowHandle().startSystemMove()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()


class EventDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(200, 125)

    def paint(self, painter, option, index):
        e = index.data(Qt.ItemDataRole.UserRole) or {}
        painter.save()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.fillRect(option.rect, QColor("#272239" if selected else "#151619"))
        painter.setPen(QPen(QColor("#323338"), 1))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        if selected:
            painter.fillRect(option.rect.x(), option.rect.y(), 3, option.rect.height(), QColor("#b091e4"))
        rect = option.rect.adjusted(13, 9, -11, -8)
        severity = str(e.get("severity", "unassessed"))
        painter.setPen(QColor(SEVERITY.get(severity, SEVERITY["unassessed"])))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        category = ("★ SAVED / " if e.get("_situation_starred") else "") + str(e.get("category", "News")).upper()
        painter.drawText(rect.x(), rect.y()+10, f"● {severity.upper()}  /  {category}")
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        painter.setPen(QColor("#f0f1f7"))
        title_rect = QRectF(rect.x(), rect.y()+19, rect.width(), 34)
        painter.drawText(title_rect, Qt.TextFlag.TextWordWrap, str(e.get("_display_title", e.get("title", "Untitled event")))[:180])
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor("#b1bccf"))
        painter.drawText(rect.x(),rect.y()+67,painter.fontMetrics().elidedText(str(e.get("recap", "Limited source text available.")),Qt.TextElideMode.ElideRight,rect.width()))
        painter.setPen(QColor("#a5b0c2"))
        meta = f"{e.get('region') or e.get('country') or 'Global'}  ·  {e.get('report_count',len(e.get('reports',[])))} reports  ·  {e.get('verification','unverified').title()}"
        painter.drawText(rect.x(), rect.y()+85, painter.fontMetrics().elidedText(meta,Qt.TextElideMode.ElideRight,rect.width()))
        painter.setPen(QColor("#6f7d93"))
        painter.drawText(rect.x(), rect.y()+102, painter.fontMetrics().elidedText(str(e.get("_translation_label", "")) + " · " + report_time(e),Qt.TextElideMode.ElideRight,rect.width()))
        painter.restore()


class EconomicTableModel(QAbstractTableModel):
    """Virtual economic table: even a large archive creates no per-cell widgets."""

    COLUMNS = (
        "Country", "Observation date", "Value", "Prior value", "Revisions",
        "Unit", "Release / update", "Retrieved", "Source ↗",
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []

    def set_observations(self, observations):
        self.beginResetModel()
        self._rows = sorted(
            observations,
            key=lambda o: str(o.get("date") or o.get("observation_date") or o.get("period") or ""),
            reverse=True,
        )
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self.COLUMNS):
                return self.COLUMNS[section]
        return None

    def url_at(self, row):
        if 0 <= row < len(self._rows):
            return str(self._rows[row].get("url") or "")
        return ""

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        o = self._rows[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return self.url_at(index.row())
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return None
        values = (
            o.get("country_name") or o.get("country"),
            o.get("date") or o.get("observation_date") or o.get("period"),
            o.get("value"),
            o.get("previous_value") if o.get("previous_value") is not None else "No recorded revision",
            o.get("revision_count", 1),
            o.get("unit") or "See indicator definition",
            o.get("release_date") or o.get("last_updated") or "Not supplied",
            timestamp(o.get("retrieved_at")),
            o.get("source_id") or o.get("source") or o.get("url"),
        )
        value = values[index.column()]
        return str(value if value is not None else "Missing")


class EconomicTableView(QTableView):
    """Retain the existing rowCount API used by desktop/QA view tests."""

    def rowCount(self):
        return self.model().rowCount() if self.model() is not None else 0


class EconomicChart(QWidget):
    """Small native chart with actual values; missing observations stay missing."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(230)
        self.setAccessibleName("Economic observation history")
        self.observations = []
        self._series = []
        self._dates = ()
        self._extents = (0, 1)
        self._chart_pixmap = None
        self._chart_cache_key = None

    def set_observations(self, data):
        self.observations = [d for d in data if isinstance(d.get("value"), (int,float)) and not isinstance(d.get("value"),bool) and math.isfinite(d["value"])]
        groups = {}
        for item in self.observations:
            date = str(item.get("date") or item.get("observation_date") or item.get("period") or "")
            if not date:
                continue
            country = str(item.get("country_name") or item.get("country") or "Global")
            groups.setdefault(country, []).append((date, float(item["value"])))
        self._dates = tuple(sorted({date for values in groups.values() for date, _ in values}))
        positions = {date: index for index, date in enumerate(self._dates)}
        self._series = tuple(
            (country, tuple((positions[date], value) for date, value in sorted(values)))
            for country, values in sorted(groups.items())
        )
        values = [value for _, series in self._series for _, value in series]
        self._extents = (min(values), max(values)) if values else (0, 1)
        self._chart_pixmap = None
        self.update()

    def paintEvent(self, event):
        ratio = self.devicePixelRatioF()
        cache_key = (self.width(), self.height(), ratio)
        if self._chart_pixmap is None or self._chart_cache_key != cache_key:
            self._chart_cache_key = cache_key
            size = QSize(max(1, round(self.width()*ratio)), max(1, round(self.height()*ratio)))
            pixmap = QPixmap(size)
            pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(QColor("#151619"))
            painter = QPainter(pixmap)
            try:
                self._paint_chart(painter)
            finally:
                painter.end()
            self._chart_pixmap = pixmap
        p = QPainter(self)
        p.drawPixmap(0, 0, self._chart_pixmap)
        p.end()

    def _paint_chart(self, p):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(),QColor("#151619"))
        chart=QRectF(65,24,max(1,self.width()-90),max(1,self.height()-67))
        if not self._series or not self._dates:
            p.setPen(QColor("#8995ac")); p.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,"No numeric observations for this selection."); return
        dates=self._dates
        lo,hi=self._extents
        pad=(hi-lo)*.1 if hi!=lo else max(1,abs(hi)*.1)
        lo-=pad;hi+=pad
        p.setFont(QFont("Segoe UI",8))
        for i in range(5):
            y=chart.bottom()-chart.height()*i/4
            p.setPen(QPen(QColor("#283144"),1));p.drawLine(QPointF(chart.left(),y),QPointF(chart.right(),y))
            p.setPen(QColor("#9aa8bf"));p.drawText(QRectF(0,y-8,55,16),Qt.AlignmentFlag.AlignRight,f"{lo+(hi-lo)*i/4:.2g}")
        colors=["#b59aea","#6ebccb","#e1bc74","#df8798","#87c7a0","#8da5ed"]
        # Thousands of observations are pre-indexed once when data changes.
        # A cached raster means switching away and back only blits a pixmap.
        p.save()
        p.setClipRect(chart)
        for n,(name,values) in enumerate(self._series):
            p.setPen(QPen(QColor(colors[n%len(colors)]),2))
            points=[]
            for date_index,value in values:
                x=chart.left()+chart.width()*date_index/max(1,len(dates)-1)
                y=chart.bottom()-chart.height()*(value-lo)/(hi-lo)
                points.append(QPointF(x,y))
            for a,b in zip(points,points[1:]):p.drawLine(a,b)
            p.setBrush(QColor(colors[n%len(colors)]))
            for point in points:p.drawEllipse(point,3,3)
        p.restore()
        p.setPen(QColor("#9aa8bf"))
        p.drawText(QRectF(chart.left(),self.height()-19,chart.width(),17),
                   Qt.AlignmentFlag.AlignRight,
                   f"{len(self._series)} countries · select a country to isolate its series")
        p.setPen(QColor("#9aa8bf"))
        for i in sorted(set([0,len(dates)//2,len(dates)-1])):
            x=chart.left()+chart.width()*i/max(1,len(dates)-1)
            p.drawText(QRectF(x-40,chart.bottom()+8,80,17),Qt.AlignmentFlag.AlignCenter,dates[i])


class MainWindow(SituationActions, QMainWindow):
    """Controller-bound desktop. Native close/tray policy belongs to bootstrap."""

    # A Store-only worker must deliver completed immutable snapshots to the GUI
    # thread. No Qt widget, model, WebEngine or painter runs inside that worker.
    _idle_snapshot_ready = Signal(object)
    _idle_brief_ready = Signal(object)
    def __init__(self, controller):
        super().__init__()
        self.controller=controller
        self._close_handler=None
        self._selected_id=""
        # User-cleared selection is distinct from an initially empty feed.
        # Delayed headline/collector repaint must not silently re-star a row.
        self._feed_explicitly_cleared=False
        self._events=[]
        self._overview_events=[]  # Category candidates from existing feed/map reads.
        self._archive_selection_id=""
        self._archive_selection_scope=None  # Explicit user navigation only.
        # A selected ordinary feed story may later fall beyond the newest 500.
        # Retain only explicit user choice; initial auto-selection is not pinned.
        self._explicit_feed_selection_id=""
        self._explicit_feed_selection_scope=None
        self._historical=False
        self._history_at=None
        self._refreshing=False
        self._idle_snapshot_inflight=False
        self._idle_brief_inflight=False
        self._idle_snapshot_generation=0
        # Last source-consistent display, used only if an evidence signal is a
        # no-op for the underlying SQLite revision. Never a TTL or blind cache.
        self._idle_feed_cache=None
        self._idle_snapshot_ready.connect(
            self._apply_idle_snapshot, Qt.ConnectionType.QueuedConnection)
        self._idle_brief_ready.connect(
            self._apply_idle_brief, Qt.ConnectionType.QueuedConnection)
        # Hidden workspaces are populated once per real data revision, not
        # synchronously on every back-and-forth tab switch.
        self._dirty_pages=set(range(1,6))
        # A country click during deferred Economy rebuilding must target the
        # newly collected observations, never stale prewarm dropdown rows.
        self._pending_economic_country=None
        # Splash warms all workspaces before showing a window. Live updates
        # use an idle timer; navigation itself never runs expensive queries.
        self._background_warm_enabled=False
        self._last_navigation_at=0.0
        self._last_full_refresh_at=0.0
        self._last_rendered_monitoring=None
        # Explicit settings changes must normally update the current view
        # immediately. Saving a whole Settings form is one logical action,
        # though, and must not rebuild the 5k-event map for each changed field.
        self._batch_settings_updates=False
        self._settings_data_changed=False
        self._force_close=False
        self.setWindowTitle("Global Pulse — Dietrich AI Labs")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(960,640)
        self.resize(1440,940)
        self.setStyleSheet(STYLE)
        self.central=QWidget();self.setCentralWidget(self.central)
        outer=QVBoxLayout(self.central);outer.setContentsMargins(1,1,1,1);outer.setSpacing(0)
        self.titlebar=TitleBar(self);outer.addWidget(self.titlebar)
        if bool(getattr(controller,"demo",False)):
            outer.addWidget(label("SYNTHETIC TRAINING SCENARIO  ·  Fictional reports in an isolated archive. These are not live events.","DemoBanner",True))
        nav=QWidget(); nav_layout=QHBoxLayout(nav);nav_layout.setContentsMargins(12,5,12,5);nav_layout.setSpacing(4)
        self.nav_buttons={}
        self.pages=QStackedWidget()
        for i,title in enumerate(("Monitor","Situations","Economy","Sources","Alerts","Briefs","Settings")):
            b=button(title,lambda checked=False,n=i:self.open_page(n),checkable=True)
            b.setObjectName(f"nav_{title.lower()}");self.nav_buttons[title]=b;nav_layout.addWidget(b)
        nav_layout.addStretch()
        self.last_label=label("Last collection  —","Muted");nav_layout.addWidget(self.last_label)
        outer.addWidget(nav)
        filters=QWidget();fl=QHBoxLayout(filters);fl.setContentsMargins(12,3,12,10);fl.setSpacing(8)
        self.search=QLineEdit();self.search.setPlaceholderText("Search events, sources, evidence…");self.search.setClearButtonEnabled(True);self.search.setAccessibleName("Search local event archive");self.search.setMinimumWidth(200)
        self.category=QComboBox();self.category.addItem("All categories","");self.category.setMinimumWidth(135);self.category.setAccessibleName("Category filter")
        self.region=QComboBox();self.region.addItem("All regions","");self.region.setMinimumWidth(125);self.region.setAccessibleName("Region filter")
        self.time_range=QComboBox();self.time_range.addItems(["24 hours","7 days","30 days","All history"]);self.time_range.setCurrentIndex(1);self.time_range.setAccessibleName("Event time range")
        self.pause_button=button("Pause",self._toggle_monitoring,"Pause or resume monitoring")
        self.pause_button.setMinimumWidth(max(80,self.pause_button.fontMetrics().horizontalAdvance("Resume")+28))
        self.refresh_button=button("↻ Refresh",self._refresh_sources,"Request due source collection")
        fl.addWidget(self.search,1);fl.addWidget(self.category);fl.addWidget(self.region);fl.addWidget(self.time_range);fl.addWidget(self.pause_button);fl.addWidget(self.refresh_button)
        outer.addWidget(filters)
        outer.addWidget(self.pages,1)
        self._build_monitor();self._build_situations();self._build_economy();self._build_sources();self._build_alerts();self._build_briefs();self._build_settings()
        self.media.restore_auto_cameras(self.controller.get_setting("auto_event_cameras",False))
        self.media.auto_cameras_changed.connect(lambda value:self.controller.set_setting("auto_event_cameras",value))
        if hasattr(self.media, "configure_radio_preferences"):
            self.media.configure_radio_preferences(self.controller.get_setting, self.controller.set_setting)
        self.status_label=label("Ready. Select an event to inspect its source trail.")
        self.statusBar().addWidget(self.status_label,1)
        self.count_label=label("0 events")
        self.statusBar().addPermanentWidget(self.count_label)
        self.statusBar().setSizeGripEnabled(True)
        self.search_timer=QTimer(self);self.search_timer.setSingleShot(True);self.search_timer.setInterval(180);self.search_timer.timeout.connect(self.refresh_data)
        # Collector events may arrive in bursts while the user is switching
        # tabs. Start the first-due timer once (never restart on every signal).
        # No widgets or QTimer are touched from the collector's worker thread.
        self._evidence_refresh_timer=QTimer(self)
        self._evidence_refresh_timer.setSingleShot(True)
        self._evidence_refresh_timer.setInterval(160)
        self._evidence_refresh_timer.timeout.connect(self._refresh_evidence_when_idle)
        # A burst of status-only callbacks (one per collector) can overwhelm
        # a normal interactive session. Coalesce them on the GUI event loop.
        self._collection_refresh_timer=QTimer(self)
        self._collection_refresh_timer.setSingleShot(True)
        self._collection_refresh_timer.setInterval(500)
        self._collection_refresh_timer.timeout.connect(self._refresh_source_status_ui)
        self._workspace_warm_timer=QTimer(self)
        self._workspace_warm_timer.setSingleShot(True)
        # Rebuilding a hidden 127-source table/charts in every 125 ms idle
        # slot could still seize the GUI between fast owner tab clicks.
        self._workspace_warm_timer.setInterval(750)
        self._workspace_warm_timer.timeout.connect(self._warm_next_workspace)
        self.search.textChanged.connect(lambda:self.search_timer.start())
        for combo in (self.category,self.region,self.time_range):combo.currentIndexChanged.connect(self.refresh_data)
        # User/settings changes retain immediate presentation semantics.
        # The collector uses its separate evidence_changed signal; that path
        # is coalesced to prevent high-frequency map rebuilds between clicks.
        controller.data_changed.connect(self._on_user_data_changed)
        controller.evidence_changed.connect(self._schedule_evidence_refresh)
        if hasattr(controller, "notification_changed"):
            controller.notification_changed.connect(self._notification_status_only)
        if hasattr(controller, "source_status_changed"):
            controller.source_status_changed.connect(self._schedule_collected_refresh)
        if hasattr(controller, "situation_changed"):
            controller.situation_changed.connect(self._situation_state_changed)
        controller.status_changed.connect(self._status_update)
        controller.alert_received.connect(self._on_alert)
        controller.translation_ready.connect(self._translation_done)
        if hasattr(controller, "feed_translation_changed"):
            controller.feed_translation_changed.connect(self._refresh_translated_headlines)
        QShortcut(QKeySequence("Ctrl+F"),self,activated=self.search.setFocus)
        QShortcut(QKeySequence("Ctrl+R"),self,activated=self._refresh_sources)
        QShortcut(QKeySequence("Ctrl+,"),self,activated=lambda:self.open_page(6))
        QShortcut(QKeySequence("Alt+F4"),self,activated=self.close)
        self._restore_layout()
        self.open_page(0)
        self.refresh_data()

    def _build_monitor(self):
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(12,0,12,8);layout.setSpacing(0)
        self.vertical_split=QSplitter(Qt.Orientation.Vertical);self.vertical_split.setHandleWidth(4)
        self.map_panel=Panel("GLOBAL SITUATION MAP")
        self.country_search=QLineEdit();self.country_search.setPlaceholderText("Find a country…");self.country_search.setMaximumWidth(190);self.country_search.setAccessibleName("Find a country on the map")
        self.world_map=WorldMap()
        comp=QCompleter(self.world_map.country_names,self);comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive);self.country_search.setCompleter(comp)
        self.country_search.returnPressed.connect(self._find_country);comp.activated.connect(self._find_country)
        self.map_panel.heading.addWidget(self.country_search)
        self.density_check=QCheckBox("Density");self.density_check.toggled.connect(self._density_changed);self.map_panel.heading.addWidget(self.density_check)
        self.layer_button=button("Layers",self._toggle_layer_panel,"Show or hide persistent map layer controls",checkable=True)
        self.layer_button.setChecked(True);self.map_panel.heading.addWidget(self.layer_button)
        self.map_panel.heading.addWidget(button("−",lambda:self.world_map.zoom_by(.8),"Zoom out"))
        self.map_panel.heading.addWidget(button("+",lambda:self.world_map.zoom_by(1.25),"Zoom in"))
        self.map_panel.heading.addWidget(button("World",self._reset_map,"Reset global map view and geographic filter"))
        map_frame=QWidget();map_grid=QGridLayout(map_frame);map_grid.setContentsMargins(0,0,0,0)
        map_grid.addWidget(self.world_map,0,0)
        self.map_overlay=QFrame();self.map_overlay.setObjectName("MapControls");self.map_overlay.setFixedWidth(156);self.map_overlay.setStyleSheet("QFrame#MapControls {background:#151619;border:1px solid #3b3c40;} QFrame#MapControls QWidget {background:transparent;}")
        overlay=QVBoxLayout(self.map_overlay);overlay.setContentsMargins(6,6,6,6);overlay.setSpacing(4)
        periods=QHBoxLayout();periods.setSpacing(2)
        self.map_period_buttons=[]
        for index,text in enumerate(("24h","7d","30d","All")):
            control=button(text,lambda checked=False,i=index:self.time_range.setCurrentIndex(i),"Filter event history: "+text,checkable=True)
            control.setStyleSheet("font-size:10px;padding:3px 4px;")
            periods.addWidget(control);self.map_period_buttons.append(control)
        overlay.addLayout(periods)
        self.layers_scroll=QScrollArea();self.layers_scroll.setWidgetResizable(True);self.layers_scroll.setFixedHeight(158)
        self.layers_content=QWidget();self.layers_layout=QVBoxLayout(self.layers_content);self.layers_layout.setContentsMargins(2,2,2,2);self.layers_layout.setSpacing(3)
        self.layer_checks={};self.layers_scroll.setWidget(self.layers_content);overlay.addWidget(self.layers_scroll)
        self.layers_layout.addWidget(button("All categories",self._all_layers,"Show all map categories"))
        self.crisis_master_check=QCheckBox("Crisis stripes")
        self.crisis_master_check.setStyleSheet("font-size:10px;font-weight:600;")
        self.crisis_master_check.setToolTip("Overlay recent source-backed conflict, unrest and displacement reporting. Not a legal designation.")
        self.crisis_master_check.toggled.connect(self._toggle_crisis_overlay)
        self.layers_layout.addWidget(self.crisis_master_check)
        self.crisis_checks={}
        for kind,text in (("conflict","Red · conflict/war"),("unrest","Yellow · protest/unrest"),("migration","Brown · migration")):
            check=QCheckBox(text);check.setStyleSheet("font-size:10px;")
            check.setAccessibleName("Crisis map layer: "+kind)
            check.toggled.connect(lambda checked,k=kind:self._toggle_crisis_kind(k,checked))
            self.crisis_checks[kind]=check;self.layers_layout.addWidget(check)
        map_grid.addWidget(self.map_overlay,0,0,Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignTop)
        self.map_panel.layout.addWidget(map_frame,1)
        self.gdelt_panel=None
        if hasattr(self.controller,"gdelt_status_changed") and hasattr(self.controller.store,"path"):
            from .gdelt_map_panel import GdeltMapPanel
            self.gdelt_panel=GdeltMapPanel(self.controller,self.world_map,self)
            self.map_panel.layout.addWidget(self.gdelt_panel)
        legend=QHBoxLayout();legend.setSpacing(6)
        for key,title in (("critical","Critical"),("high","High"),("moderate","Moderate"),("informational","Info"),("unassessed","Unassessed")):
            w=label(f"● {title}");w.setStyleSheet(f"color:{SEVERITY[key]};font-size:10px;");legend.addWidget(w)
        legend.addStretch()
        w=label("◌ Unverified   ◔ Developing   ◎ Official","Muted")
        w.setToolTip("Incident-pin color is importance; circular ring pattern is source status. Official is an attributed source, not independent corroboration.")
        legend.addWidget(w)
        self.map_panel.layout.addLayout(legend)
        country_legend=QHBoxLayout()
        country_legend.setSpacing(8)
        for kind in ("Government","Economy","Health","Humanitarian","Infrastructure","News"):
            dot=label(f"● {kind}", "Muted")
            dot.setStyleSheet(
                f"color:{CATEGORY_COLORS[kind]};font-size:9px;"
            )
            dot.setToolTip(
                "Country-colored circular badge: source reporting/observations "
                "attributed to the country, NOT a precise incident coordinate."
            )
            country_legend.addWidget(dot)
        country_legend.addStretch()
        self.map_panel.layout.addLayout(country_legend)
        crisis_legend=QHBoxLayout();crisis_legend.setSpacing(8)
        for text,color in (("//// Conflict / war","#d84a52"),("//// Protest / unrest","#e3bd4d"),("==== Migration / displacement","#9a6748")):
            item=label(text);item.setStyleSheet(f"color:{color};font-size:9px;");crisis_legend.addWidget(item)
        crisis_note=label("source-derived · toggle in Layers","Muted");crisis_note.setToolTip("Country hatching summarizes recent sourced events; it is not a legal declaration of war or crisis.");crisis_legend.addWidget(crisis_note)
        crisis_legend.addStretch();self.map_panel.layout.addLayout(crisis_legend)
        history=row(label("HISTORY","Eyebrow"))
        self.history_slider=QSlider(Qt.Orientation.Horizontal);self.history_slider.setRange(0,1000);self.history_slider.setValue(1000);self.history_slider.setAccessibleName("Historical event playback position")
        self.history_slider.valueChanged.connect(self._history_changed);history.addWidget(self.history_slider,1)
        self.history_label=label("Latest","Muted");history.addWidget(self.history_label)
        self.history_play=button("▶",self._toggle_playback,"Play historical timeline");history.addWidget(self.history_play)
        self.map_panel.layout.addLayout(history)
        self.play_timer=QTimer(self);self.play_timer.setInterval(450);self.play_timer.timeout.connect(self._play_step)
        self.vertical_split.addWidget(self.map_panel)
        self.lower_split=QSplitter(Qt.Orientation.Horizontal);self.lower_split.setHandleWidth(4)
        feed=Panel("NEWS & EVENT FEED");self.feed_count=label("0","Count");feed.heading.addWidget(self.feed_count)
        self.english_headlines=QCheckBox("English headlines")
        self.english_headlines.setToolTip("Translate displayed headlines locally using installed models. No automatic model downloads. Original source evidence is preserved.")
        self.english_headlines.setChecked(self.controller.get_setting("english_headlines",True) is True)
        self.english_headlines.toggled.connect(lambda value:self.controller.set_setting("english_headlines",value))
        feed.heading.addWidget(self.english_headlines)
        self.sort_combo=QComboBox();self.sort_combo.addItems(["Latest first","Highest importance","Most reports"]);self.sort_combo.currentIndexChanged.connect(self._populate_feed);feed.heading.addWidget(self.sort_combo)
        self.feed_list=QListWidget();self.feed_list.setObjectName("event_feed");self.feed_list.setAccessibleName("News and events");self.feed_list.setItemDelegate(EventDelegate(self.feed_list));self.feed_list.currentItemChanged.connect(self._feed_selected)
        # Clicking even an already-selected item is an explicit request for
        # its evidence view; initial auto-selection does NOT hide World Overview.
        self.feed_list.itemClicked.connect(
            lambda _item: self.intelligence_mode.setCurrentIndex(1)
        )
        self.feed_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.feed_list.customContextMenuRequested.connect(self._show_feed_situation_menu)
        feed.layout.addWidget(self.feed_list,1)
        self.feed_empty=label("Monitoring has not collected events yet.\nStart monitoring or change the filters.","Muted",True);self.feed_empty.setAlignment(Qt.AlignmentFlag.AlignCenter);feed.layout.addWidget(self.feed_empty)
        self.lower_split.addWidget(feed)
        media=Panel("CONTEXTUAL MEDIA")
        media.heading.addWidget(label("ON DEMAND","Eyebrow"))
        try:
            from .single_media import MediaPanel
            self.media=MediaPanel()
            self.media.set_catalog(getattr(self.controller,"media_catalog",[]))
        except ImportError:
            self.media=QTextBrowser();self.media.setPlainText("Media panel unavailable in this build.")
        self.media_scroll=QScrollArea();self.media_scroll.setWidgetResizable(True);self.media_scroll.setWidget(self.media);self.media_scroll.setMinimumSize(0,0)
        media.layout.addWidget(self.media_scroll,1)
        self.lower_split.addWidget(media)
        intel=Panel("INTELLIGENCE BRIEF")
        intel.setMinimumWidth(0)
        # Keep mode/Star controls beneath the heading: putting three labels
        # side-by-side forced the sidebar to 322px at the 960px minimum window.
        intel_controls=QHBoxLayout()
        intel_controls.setContentsMargins(0,0,0,0)
        intel_controls.setSpacing(4)
        self.intelligence_mode=QComboBox()
        self.intelligence_mode.addItems(["World overview","Selected event"])
        self.intelligence_mode.setObjectName("intelligence_brief_mode")
        self.intelligence_mode.setAccessibleName("World intelligence overview or selected event evidence")
        self.intelligence_mode.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.intelligence_mode.setMinimumContentsLength(5)
        self.intelligence_mode.setMinimumWidth(0)
        self.intelligence_mode.setSizePolicy(
            QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed
        )
        intel_controls.addWidget(self.intelligence_mode,1)
        self.save_button=button("☆ Star",self._toggle_selected_situation,"Star the selected event in Situations",checkable=True)
        self.save_button.setObjectName("situation_star")
        intel_controls.addWidget(self.save_button)
        intel.layout.addLayout(intel_controls)
        self.intel_browser=QTextBrowser();self.intel_browser.setOpenExternalLinks(False);self.intel_browser.anchorClicked.connect(lambda u:self.controller.open_url(u.toString()));self.intel_browser.setAccessibleName("Selected event evidence brief")
        self.intel_stack=QSplitter(Qt.Orientation.Vertical);self.intel_stack.setHandleWidth(3)
        # A small bottom gutter gives ensureWidgetVisible() enough range to
        # bring the final status card fully into the QScrollArea viewport.
        # Without it the final card center can stay 5px offscreen in native Qt.
        self.intel_stack.setContentsMargins(0,0,0,20)
        self.intel_stack.setMinimumWidth(0)
        self.intel_stack.setSizePolicy(
            QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Expanding
        )
        self.intel_stack.addWidget(self.intel_browser)
        self.evidence_status=Panel("EVIDENCE STATUS")
        self.evidence_status_text=QTextBrowser();self.evidence_status_text.setPlainText("No event selected");self.evidence_status_text.setStyleSheet("font-size:10px;")
        self.evidence_status.layout.addWidget(self.evidence_status_text)
        self.intel_stack.addWidget(self.evidence_status)
        self.change_status=Panel("SITUATION UPDATE")
        self.change_status_text=QTextBrowser();self.change_status_text.setPlainText("Select a source-linked situation.");self.change_status_text.setStyleSheet("font-size:10px;")
        self.change_status.layout.addWidget(self.change_status_text)
        self.intel_stack.addWidget(self.change_status)
        # A QTextBrowser's native minimumSizeHint defaults to about 256px.
        # Nested under two scroll/splitter layers that kept 960px windows at
        # a 257px minimum right pane, exceeding the original <25% contract.
        # Keep *height* readable while allowing text to wrap at narrow widths.
        for panel in (self.evidence_status,self.change_status):
            panel.setMinimumWidth(0)
            panel.setSizePolicy(
                QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Expanding
            )
        # Every expanded card must have real text space. A splitter alone can
        # shrink the nested panel headers until its text viewport is zero.
        # Keep a readable minimum and scroll the whole stack on small windows;
        # do not grow the main window or distort the reference's 40/40/20 split.
        for browser in (self.intel_browser,self.evidence_status_text,self.change_status_text):
            browser.ensurePolished()
            browser.setMinimumWidth(0)
            browser.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Expanding)
            browser.setMinimumHeight(3 * browser.fontMetrics().lineSpacing() + 24)
        self.intel_stack.setChildrenCollapsible(False)
        self.intel_stack.setSizes([220,100,100])
        self.intel_scroll=QScrollArea()
        self.intel_scroll.setAccessibleName("Scrollable intelligence brief and status cards")
        self.intel_scroll.setWidgetResizable(True)
        self.intel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.intel_scroll.setMinimumSize(0,0)
        self.intel_scroll.setSizePolicy(
            QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Expanding
        )
        self.intel_scroll.setWidget(self.intel_stack)
        self.overview_browser=QTextBrowser()
        self.overview_browser.setObjectName("world_intelligence_overview")
        self.overview_browser.setAccessibleName("Balanced local world intelligence overview")
        self.overview_browser.setOpenExternalLinks(False)
        self.overview_browser.setOpenLinks(False)  # Local event anchors are handled exactly once below.
        self.overview_browser.anchorClicked.connect(self._open_overview_event)
        self.overview_browser.setHtml(
            "<p>World overview will appear when local reports are loaded.</p>"
        )
        self.intelligence_pages=QStackedWidget()
        self.intelligence_pages.setMinimumWidth(0)
        self.intelligence_pages.setSizePolicy(
            QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Expanding
        )
        self.overview_browser.setMinimumWidth(0)
        self.overview_browser.setSizePolicy(
            QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Expanding
        )
        self.intelligence_pages.addWidget(self.overview_browser)
        self.intelligence_pages.addWidget(self.intel_scroll)
        self.intelligence_mode.currentIndexChanged.connect(
            self.intelligence_pages.setCurrentIndex
        )
        self._overview_html_cached=""
        intel.layout.addWidget(self.intelligence_pages,1)
        actionrow=QHBoxLayout()
        self.original_button=button("Source ↗",self._open_original);self.translate_button=button("Translate",self._translate_selected)
        actionrow.addWidget(self.original_button);actionrow.addWidget(self.translate_button);intel.layout.addLayout(actionrow)
        self.lower_split.addWidget(intel)
        self.lower_split.setSizes([560,560,280]);self.lower_split.setCollapsible(0,False);self.lower_split.setCollapsible(1,True);self.lower_split.setCollapsible(2,True)
        self.vertical_split.addWidget(self.lower_split);self.vertical_split.setSizes([470,350]);self.vertical_split.setCollapsible(0,False);self.vertical_split.setCollapsible(1,False)
        layout.addWidget(self.vertical_split);self.pages.addWidget(page)
        self.world_map.event_selected.connect(self.navigate_event)
        self.world_map.country_selected.connect(self._country_selected)
        self.world_map.economic_country_requested.connect(self._open_economic_country)
        self.world_map.global_search_requested.connect(self._search_full_archive)

    def _build_situations(self):
        panel=Panel("SITUATION ROOMS")
        self.unstar_button=button("☆ Unstar selected",self._unstar_current_situation,"Remove the selected situation bookmark, keeping its evidence")
        self.unstar_button.setEnabled(False);panel.heading.addWidget(self.unstar_button)
        desc=label("Saved situations preserve their evidence trail. Open one to see what changed since your last visit.","Muted",True);panel.layout.addWidget(desc)
        split=QSplitter();self.situation_list=QListWidget();self.situation_list.setAccessibleName("Saved Situation Rooms")
        self.situation_browser=QTextBrowser();self.situation_browser.setOpenExternalLinks(False);self.situation_browser.anchorClicked.connect(lambda u:self.controller.open_url(u.toString()))
        split.addWidget(self.situation_list);split.addWidget(self.situation_browser);split.setSizes([320,850]);panel.layout.addWidget(split,1)
        self.situation_list.itemClicked.connect(self._visit_situation)
        self.situation_list.currentItemChanged.connect(self._sync_situation_remove)
        self.pages.addWidget(panel)

    def _build_economy(self):
        panel=Panel("ECONOMIC STABILITY MONITOR")
        panel.layout.addWidget(label("Compare reported observations over time. One worsening indicator does not establish an economic crisis.","Muted",True))
        tools=QHBoxLayout();self.indicator_combo=QComboBox();self.indicator_combo.setMinimumWidth(300);self.indicator_combo.setAccessibleName("Economic indicator")
        self.economy_country=QComboBox();self.economy_country.addItem("All countries","");self.economy_country.setAccessibleName("Economic comparison country")
        tools.addWidget(self.indicator_combo,1);tools.addWidget(self.economy_country);panel.layout.addLayout(tools)
        self.economic_chart=EconomicChart();panel.layout.addWidget(self.economic_chart,1)
        self.economy_explanation=label("","Muted",True);panel.layout.addWidget(self.economy_explanation)
        self.economy_table=EconomicTableView()
        self.economy_model=EconomicTableModel(self.economy_table)
        self.economy_table.setModel(self.economy_model)
        self._configure_table(self.economy_table)
        # ResizeToContents walks *all* rows, even with a virtual model, and
        # rebuilt thousands of cell geometries every time this tab appeared.
        header=self.economy_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setDefaultSectionSize(140)
        header.setStretchLastSection(True)
        header.resizeSection(0,175)
        header.resizeSection(1,140)
        header.resizeSection(3,150)
        header.resizeSection(6,160)
        self.economy_table.verticalHeader().setDefaultSectionSize(23)
        self.economy_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        panel.layout.addWidget(self.economy_table,1)
        self.economy_table.doubleClicked.connect(
            lambda index:self._open_economic_source(index.row(),index.column())
        )
        # A later direct dropdown choice takes precedence over a deferred map click.
        # Rebuilding the controls blocks their signals; only a real selection
        # signal cancels the pending country. Existing local evidence is kept.
        self.indicator_combo.currentIndexChanged.connect(self._manual_economy_selection)
        self.economy_country.currentIndexChanged.connect(self._manual_economy_selection)
        self.pages.addWidget(panel)

    def _build_sources(self):
        from .provider_actions import build_sources
        return build_sources(self)

    def _build_alerts(self):
        panel=Panel("ALERT HISTORY")
        self.notification_label=label("","Muted",True);panel.layout.addWidget(self.notification_label)
        panel.layout.addWidget(label("Alerts remain here when Windows suppresses a toast. Click an alert to open its exact event.","Muted",True))
        self.alert_list=QListWidget();self.alert_list.setAccessibleName("Persistent alert history");self.alert_list.itemClicked.connect(self._open_alert);panel.layout.addWidget(self.alert_list,1)
        self.pages.addWidget(panel)

    def _build_briefs(self):
        panel=Panel("INTELLIGENCE BRIEFS & EXPORTS")
        controls=QHBoxLayout();self.brief_period=QComboBox();self.brief_period.addItems(["Daily","Weekly"]);controls.addWidget(self.brief_period)
        controls.addWidget(button("Generate brief",self._generate_brief));controls.addStretch();controls.addWidget(button("Export brief…",self._export_brief));controls.addWidget(button("Export event archive…",self._export_events));panel.layout.addLayout(controls)
        self.brief_browser=QTextBrowser();self.brief_browser.setOpenExternalLinks(False);self.brief_browser.anchorClicked.connect(lambda u:self.controller.open_url(u.toString()));panel.layout.addWidget(self.brief_browser,1)
        panel.layout.addWidget(label("Briefs are grounded in locally retained source records. They cannot fill gaps in source coverage or monitoring downtime.","Muted",True));self.pages.addWidget(panel)

    def _build_settings(self):
        scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();layout=QVBoxLayout(body);layout.setContentsMargins(20,15,20,20);layout.setSpacing(15)
        layout.addWidget(label("SETTINGS & WATCHLISTS","SectionTitle"))
        layout.addWidget(label("Your interests, history, and settings stay on this computer. No account or API key is needed for enabled public sources.","Muted",True))
        grid=QGridLayout();grid.setHorizontalSpacing(25)
        collection=QGroupBox("Monitoring");form=QFormLayout(collection)
        self.setting_interval=QComboBox()
        for text,seconds in (("5 minutes",300),("10 minutes",600),("30 minutes",1800),("60 minutes",3600)):self.setting_interval.addItem(text,seconds)
        self.setting_interval.setCurrentIndex(max(0,self.setting_interval.findData(self.controller.get_setting("interval",600))))
        form.addRow("Default check interval",self.setting_interval)
        form.addRow(label("Provider minimums and retry delays take precedence.","Muted",True))
        self.setting_retention=QSpinBox();self.setting_retention.setRange(1,3650);self.setting_retention.setValue(int(self.controller.get_setting("retention_days",365)));self.setting_retention.setSuffix(" days");form.addRow("Local retention",self.setting_retention)
        self.setting_close=QCheckBox("Keep monitoring in the tray when X is clicked");self.setting_close.setChecked(bool(self.controller.get_setting("close_to_tray",True)));form.addRow(self.setting_close)
        self.setting_notify=QCheckBox("Enable Windows pop-up notifications (off by default)");self.setting_notify.setChecked(bool(self.controller.get_setting("notifications_enabled",False)));form.addRow(self.setting_notify)
        form.addRow(label("Alerts remain searchable inside Pulse when pop-ups are off. Turn them on here only if you want desktop notifications.","Muted",True))
        self.setting_threshold=QComboBox()
        for severity in ("unassessed","informational","moderate","high","critical"):self.setting_threshold.addItem(severity.title(),severity)
        self.setting_threshold.setCurrentIndex(max(0,self.setting_threshold.findData(self.controller.get_setting("alert_threshold","moderate"))))
        form.addRow("Minimum alert importance",self.setting_threshold)
        grid.addWidget(collection,0,0)
        quiet=QGroupBox("Quiet hours & interests");qform=QFormLayout(quiet)
        self.setting_quiet=QCheckBox("Mute external notifications during quiet hours");self.setting_quiet.setChecked(bool(self.controller.get_setting("quiet_enabled",False)));qform.addRow(self.setting_quiet)
        self.quiet_start=QLineEdit(str(self.controller.get_setting("quiet_start","22:00")));self.quiet_end=QLineEdit(str(self.controller.get_setting("quiet_end","07:00")));qform.addRow("From / to (local HH:MM)",self._widget_row(self.quiet_start,self.quiet_end))
        self.setting_countries=QLineEdit(", ".join(self.controller.get_setting("countries",[])));self.setting_countries.setPlaceholderText("All countries; or comma-separated names");qform.addRow("Country watchlist",self.setting_countries)
        self.setting_categories=QLineEdit(", ".join(self.controller.get_setting("categories",[])));self.setting_categories.setPlaceholderText("All categories; or comma-separated topics");qform.addRow("Topic watchlist",self.setting_categories)
        grid.addWidget(quiet,0,1);layout.addLayout(grid)
        sources_group=QGroupBox("Source preferences");sg=QVBoxLayout(sources_group)
        sg.addWidget(label("Every available, approved collector is enabled for new profiles. Restricted, duplicate and website-only entries cannot be auto-collected. Muting affects alerts, not collection.","Muted",True))
        self.enable_all_sources_button=button("Enable all available sources",self._enable_all_available_sources)
        self.enable_all_sources_button.setToolTip("Select every currently collectable provider; press Save settings to apply. Does not bypass access or retry limits.")
        sg.addWidget(self.enable_all_sources_button,0,Qt.AlignmentFlag.AlignLeft)
        self.source_preferences=QTableWidget(0,4);self.source_preferences.setHorizontalHeaderLabels(["Collect","Mute alerts","Source","Access limitation"]);self._configure_table(self.source_preferences);self.source_preferences.setMinimumHeight(220);sg.addWidget(self.source_preferences);layout.addWidget(sources_group)
        translation=QGroupBox("Offline translation");tl=QVBoxLayout(translation)
        tl.addWidget(label("Translation uses installed local language models. Original text is preserved. Missing models are reported honestly; no model is downloaded without your consent.","Muted",True))
        self.translation_settings=button("Manage translation models",self._manage_translation);tl.addWidget(self.translation_settings,0,Qt.AlignmentFlag.AlignLeft);layout.addWidget(translation)
        if hasattr(self.controller,"gdelt_status_changed"):
            from .gdelt_controls import GdeltControls
            self.gdelt_controls=GdeltControls(self.controller,self)
            layout.addWidget(self.gdelt_controls)
        if hasattr(self.controller,"archive_storage_status"):
            from .archive_storage_controls import ArchiveStorageControls
            self.archive_storage_controls=ArchiveStorageControls(self.controller,self)
            layout.addWidget(self.archive_storage_controls)
        actions=QHBoxLayout();save=button("Save settings",self._save_settings);save.setObjectName("Primary");actions.addWidget(save);actions.addWidget(button("Reset window layout",self._reset_layout));actions.addStretch();actions.addWidget(button("Exit Completely",self.controller.quit));layout.addLayout(actions)
        self.settings_result=label("","Muted",True);layout.addWidget(self.settings_result);layout.addStretch();scroll.setWidget(body);self.pages.addWidget(scroll)
        self._populate_source_preferences()

    @staticmethod
    def _widget_row(*widgets):
        w=QWidget();w.setLayout(row(*widgets));return w

    @staticmethod
    def _configure_table(table):
        table.setAlternatingRowColors(True);table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection);table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);table.verticalHeader().hide();table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents);table.horizontalHeader().setStretchLastSection(True)

    def prepare_initial_workspaces(self):
        """Populate bounded local workspaces before releasing startup splash.

        A cold first click on Economy/Sources/Alerts/Briefs previously ran the
        entire SQLite/table/brief construction on the visible UI thread.
        This runs once while the dashboard is hidden, no live media starts,
        and future report or settings changes still mark workspaces dirty.
        """
        current=self.pages.currentIndex()
        for index in (1,2,3,4,5):
            if index in self._dirty_pages:
                self.open_page(index)
        self.open_page(current)
        success=not (self._dirty_pages & {1,2,3,4,5})
        if success:
            self._background_warm_enabled=True
        return success

    def prime_initial_paint_caches(self, app, splash):
        """Render the first real-sized Map/Economy frames before releasing splash.

        Data prewarming does not itself trigger Qt paintEvent for hidden tabs.
        Expose the disabled window under the on-top splash just long enough
        for Qt to settle its actual DPI/layout, draw the heavyweight first
        frames, and verify their cache keys. Never open video or network here.
        """
        if not self._background_warm_enabled or self._dirty_pages.intersection(range(1, 6)):
            return False
        previous_page = self.pages.currentIndex()
        was_enabled = self.isEnabled()
        self._initial_painted_pages = set()
        self.setEnabled(False)
        try:
            # A hidden widget's geometry is not the real Windows viewport.
            # Rendering at its default size would get invalidated on show().
            self.show()
            splash.raise_()
            app.processEvents()
            self.open_page(0)
            app.processEvents()
            if (not self.world_map.isVisible() or self.world_map.width() < 32
                    or self.world_map.height() < 32):
                return False
            self.world_map.grab()
            self._initial_painted_pages.add(0)

            # Data is already preloaded for every workspace. Force its
            # initial Qt geometry/viewport draw under splash as well; a cold
            # first click must not pay for Sources, Settings, Alerts or Briefs.
            for index in (1, 3, 4, 5, 6):
                self.open_page(index)
                app.processEvents()
                page = self.pages.currentWidget()
                if page is None or not page.isVisible():
                    return False
                page.grab()
                self._initial_painted_pages.add(index)

            self.open_page(2)
            app.processEvents()
            if (not self.economic_chart.isVisible() or self.economic_chart.width() < 32
                    or self.economic_chart.height() < 32):
                return False
            self.economic_chart.grab()
            # Initial QTableView viewport/layout must also complete under
            # splash, but only visible virtual rows are materialized.
            self.economy_table.viewport().grab()
            self._initial_painted_pages.add(2)

            self.open_page(previous_page)
            app.processEvents()
            self.world_map.grab()
            world = self.world_map
            chart = self.economic_chart
            expected_map_key = (
                world.width(), world.height(), world.zoom, world.pan_x, world.pan_y,
            )
            expected_chart_key = (
                chart.width(), chart.height(), chart.devicePixelRatioF(),
            )
            return (
                world._projected_view_key == expected_map_key
                and len(world._projected_paths) == len(world._countries)
                and chart._chart_pixmap is not None
                and chart._chart_cache_key == expected_chart_key
                and self._initial_painted_pages == set(range(7))
            )
        finally:
            if self.pages.currentIndex() != previous_page:
                self.open_page(previous_page)
            self.setEnabled(was_enabled)
            # This disabled-window traversal is splash-owned geometry/first
            # paint work, NOT a user tab click. Retaining its navigation stamp
            # artificially delayed the first real no-click collector update
            # by another 1.8s after READY. Any subsequent real open_page()
            # will establish its own full user-navigation cooldown.
            self._last_navigation_at=0.0

    def _schedule_workspace_warm(self):
        if (self._background_warm_enabled and self._dirty_pages
                and not self._force_close and not getattr(self.controller,"_closed",False)
                and not self._workspace_warm_timer.isActive()):
            self._workspace_warm_timer.start()

    @Slot()
    def _warm_next_workspace(self):
        if (not self._background_warm_enabled or self._force_close
                or getattr(self.controller,"_closed",False) or not self._dirty_pages):
            return
        # Never let a hidden-table rebuild interrupt an active sequence of
        # clicks. Users continue to see the fully initialized cached view.
        if time.monotonic()-self._last_navigation_at < 1.8:
            self._workspace_warm_timer.start(1000)
            return
        # Prefer the visible page, then keep hidden snapshots warm. A tab click
        # does no SQLite work; each idle turn handles at most one workspace.
        current=self.pages.currentIndex()
        page=current if current in self._dirty_pages else min(self._dirty_pages)
        # The Daily/Weekly SQL runs independently after the critical feed/map
        # result, so a slow brief cannot starve the no-click GUI refresh.
        # Do not perform a hidden synchronous SQLite brief query meanwhile.
        if page==5 and self._idle_brief_inflight:
            other=self._dirty_pages-{5}
            if not other:
                self._workspace_warm_timer.start()
                return
            page=min(other)
        # An archive/collector worker may already own the Store RLock for
        # hundreds of milliseconds. Hidden prewarm is not user-requested:
        # defer rather than blocking the GUI event loop behind its SQLite
        # transaction. Keep the exact dirty page and provider-status evidence.
        if self.controller.store.content_revision_if_available() is None:
            self._workspace_warm_timer.start(250)
            return
        self._populate_workspace(page)
        self._dirty_pages.discard(page)
        self._schedule_workspace_warm()

    def _populate_workspace(self,index):
        if index==1:self._populate_situations()
        elif index==2:self._populate_economy()
        elif index==3:self._populate_sources()
        elif index==4:self._populate_alerts()
        elif index==5:self._generate_brief()

    def open_page(self,index):
        previous=self.pages.currentIndex()
        self.pages.setCurrentIndex(index)
        for i,b in enumerate(self.nav_buttons.values()):b.setChecked(i==index)
        # After splash warmup, switching pages is strictly a widget-stack
        # operation. New collector data arrives in a coalesced idle refresh.
        if self._background_warm_enabled:
            self._last_navigation_at=time.monotonic()
            self._schedule_workspace_warm()
            return
        if index in self._dirty_pages:
            self._populate_workspace(index)
            self._dirty_pages.discard(index)

    @Slot()
    def _notification_status_only(self):
        """Refresh the Alerts view only, never the 5,000-event world map."""
        self._dirty_pages.add(4)
        if self._background_warm_enabled:
            self._schedule_workspace_warm()
        elif self.pages.currentIndex()==4:
            self._populate_alerts()
            self._dirty_pages.discard(4)

    def _situation_state_changed(self, event_id, saved):
        """Update a bookmark without re-querying/repainting the world map.

        The archive's events and provenance are unchanged. Only the starred
        marker on matching feed entries and (when visible) Situations view need
        to change; all other expensive views remain untouched.
        """
        identity=str(event_id or "")
        if not identity:
            return
        if hasattr(self,"feed_list"):
            for index in range(self.feed_list.count()):
                item=self.feed_list.item(index)
                event=item.data(Qt.ItemDataRole.UserRole)
                if not isinstance(event,dict) or str(event.get("id") or "")!=identity:
                    continue
                row=dict(event,_situation_starred=bool(saved))
                item.setData(Qt.ItemDataRole.UserRole,row)
                self.feed_list.viewport().update(self.feed_list.visualItemRect(item))
                break
        if self._selected_id==identity:
            self._sync_situation_star({"id":identity})
        self._dirty_pages.add(1)
        if self.pages.currentIndex()==1:
            # Situations query is bounded by user's own bookmarks, not map size.
            self._populate_situations()
            self._dirty_pages.discard(1)

    def _archive_scope_key(self):
        """User-selected filter controls, excluding drifting time-based since."""
        return (self.search.text().strip(), self.category.currentData() or "",
                self.region.currentData() or "", self.time_range.currentIndex(),
                self.history_slider.value())

    def events_filters(self):
        self._history_at=None
        filters={"query":self.search.text().strip(),"category":self.category.currentData() or "","region":self.region.currentData() or "","limit":500}
        days={0:1,1:7,2:30}.get(self.time_range.currentIndex())
        if days is not None:
            filters["since"]=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
        if self.history_slider.value()<1000:
            all_events=self.controller.events(limit=500)
            dates=[str(t.get("at") or t.get("timestamp") or "") for e in all_events for t in e.get("timeline",[])]
            if not dates:dates=[str(e.get("updated_at") or e.get("created_at") or "") for e in all_events]
            parsed=[]
            for date in dates:
                try:parsed.append(datetime.fromisoformat(date.replace("Z","+00:00")))
                except ValueError:pass
            if parsed:
                earliest,latest=min(parsed),max(parsed)
                at=earliest+(latest-earliest)*self.history_slider.value()/1000
                self._history_at=at.isoformat();filters["before"]=self._history_at;self.history_label.setText(timestamp(at.isoformat()))
        return filters

    @Slot()
    def _on_user_data_changed(self):
        """Honor direct user updates while collapsing a multi-field Save."""
        if self._batch_settings_updates:
            self._settings_data_changed=True
        else:
            self.refresh_data()

    @Slot()
    def _schedule_evidence_refresh(self):
        """Batch real collector changes; keep explicit filter/user refresh immediate.

        The first signal fixes the deadline: a continuous source burst cannot
        starve the UI by continually pushing that deadline into the future.
        """
        if self._force_close or getattr(self.controller, "_closed", False):
            return
        if not self._evidence_refresh_timer.isActive():
            self._evidence_refresh_timer.start()

    @Slot()
    def _refresh_evidence_when_idle(self):
        """Delay costly live map/feed revisions until a navigation pause.

        Source intake is independent of UI presentation. During fast tab
        switching the last warmed snapshot is displayed without blocking
        clicks on SQLite queries, map reconciliation, or chart updates.
        """
        if self._force_close or getattr(self.controller, "_closed", False):
            return
        idle_for=time.monotonic()-self._last_navigation_at
        if self._background_warm_enabled and idle_for < 1.8:
            self._evidence_refresh_timer.start(max(100,int((1.8-idle_for)*1000)))
            return
        # No-click collector updates were held for a separate three seconds
        # *before* starting a 500/5000-event worker read. The exact hosted
        # heavy-archive profiler proved that window could exhaust its freshness
        # deadline despite an already responsive Qt heartbeat. Start the
        # worker after the existing bounded signal coalescing plus one second
        # since the last committed display. The independent 1.8-second
        # navigation pause above still protects rapid real user interaction.
        # This advances real source reading, not the test deadline or UI PASS.
        since_last=time.monotonic()-self._last_full_refresh_at
        if self._background_warm_enabled and since_last < 1.0:
            self._evidence_refresh_timer.start(max(100,int((1.0-since_last)*1000)))
            return
        if self._background_warm_enabled:
            self._start_idle_snapshot()
        else:
            self.refresh_data()

    @staticmethod
    def _unchanged_source_feed(cache, revision, scope, filters):
        """Return an exact stored feed after a source-no-op, or None if unsafe.

        The rolling time cutoff can only advance: removing rows aged beyond
        the new cutoff is exact because no older omitted row can re-enter a
        top-500 page. Never reuse a different query, history scope, archive
        revision, or backwards-moving clock. All source corrections and real
        ingestion change Store revision, so they always take the worker path.
        """
        if not cache or cache["revision"] != revision or cache["scope"] != scope:
            return None
        old_filters=cache["filters"]
        if any(filters.get(key)!=old_filters.get(key)
               for key in ("query","category","region","limit","before")):
            return None
        older=old_filters.get("since")
        newer=filters.get("since")
        if (older is None) != (newer is None):
            return None
        if older is not None and newer < older:
            return None
        return [event for event in cache["feed"]
                if newer is None or event["updated_at"] >= newer]

    def _start_idle_snapshot(self):
        """Read a bounded collector revision off the main thread, never paint there.

        Initial splash loading and explicit user/filter refreshes keep their
        existing synchronous semantics. Only coalesced post-splash evidence
        notifications use this path. Store itself serializes SQLite access.
        """
        if self._idle_snapshot_inflight:
            return
        filters=self.events_filters()
        # This source snapshot contains dictionaries, not Qt widgets. It is
        # valid only when the worker confirms the exact stored revision; a
        # real collector write always performs the full fresh source read.
        unchanged_cache=self._idle_feed_cache
        historical_at=self._history_at
        scope=self._archive_scope_key()
        generation=self._idle_snapshot_generation
        map_filters={**filters,"limit":5000,"map_view":True,
                     "keep_significant":not bool(historical_at)}
        show_observations=(not historical_at and not filters.get("query")
                           and not filters.get("region")
                           and filters.get("category") in {"","Economy"})
        # Capture map-only category selection while still on Qt's GUI thread.
        # The worker may process plain source dictionaries, never Qt widgets.
        map_categories=(None if self.world_map.categories is None
                        else tuple(self.world_map.categories))
        # The daily/weekly intelligence brief is another expensive hidden
        # workspace prewarm. Capture its period/cutoff before entering the
        # Store worker; only immutable source dictionaries cross the thread.
        brief_period=self.brief_period.currentText().lower()
        brief_since=(datetime.now(timezone.utc)-timedelta(
            days=1 if brief_period=="daily" else 7)).isoformat()
        controller=self.controller
        signal=self._idle_snapshot_ready
        brief_pending=not self._idle_brief_inflight
        if brief_pending:
            self._idle_brief_inflight=True
        self._idle_snapshot_inflight=True

        def collect():
            result={"scope":scope,"generation":generation,"filters":filters,
                    "history_at":historical_at,"show_observations":show_observations,
                    "brief_pending":brief_pending,"brief_period":brief_period,
                    "brief_since":brief_since}
            try:
                store=controller.store
                before=store.content_revision()
                # Archive selector metadata is two DISTINCT SQLite scans. The
                # idle collector path must not run either one on the Qt thread
                # after splash; include them in the same revision-checked worker.
                existing=(
                    None if historical_at else self._unchanged_source_feed(
                        unchanged_cache, before, scope, filters))
                if existing is None:
                    result["filter_options"]=controller.event_filter_options()
                    result["feed"]=controller.events(**filters)
                else:
                    result["filter_options"]=unchanged_cache["filter_options"]
                    result["feed"]=existing
                    result["unchanged_revision_feed"]=True
                result["country_evidence"]=controller.events(
                    **dict(map_filters,map_evidence=True))
                result["map_events"]=controller.events(**map_filters)
                result["observations"]=(store.list_observations()
                                        if show_observations else [])
                # This expensive, pure source/date/corroboration classification
                # used to run on the GUI thread immediately after the Store
                # worker returned. Compute it on the same bounded worker;
                # pass back the exact source object identities for validation.
                from .crisis_overlay import build_country_activity
                from .map_widget import _map_category
                category_key=(None if map_categories is None else
                              frozenset(_map_category(c) for c in map_categories))
                evidence=result["country_evidence"][:5000]
                selected=[record for record in evidence
                          if category_key is None or
                          _map_category(record.get("category")) in category_key]
                credits=set()
                classified=build_country_activity(
                    selected, now=datetime.now(timezone.utc),
                    single_record_credits=credits)
                result["map_classification"]={
                    "category_key":category_key,
                    "record_ids":tuple(id(record) for record in evidence),
                    "activity":classified, "credits":credits,
                }
                after=store.content_revision()
                result["revision_before"]=before
                result["revision_after"]=after
            except Exception as error:
                result["error"]=f"{type(error).__name__}: {str(error)[:160]}"
            try:
                signal.emit(result)
            except RuntimeError:
                # The native window may have been destroyed during shutdown.
                pass
        threading.Thread(target=collect, name="pulse-idle-evidence",
                         daemon=True).start()

    def _begin_idle_brief_read(self, snapshot):
        """Read source-balanced brief only AFTER the critical Qt refresh completes.

        Starting immediately after a worker signal previously took the Store
        lock before the queued Qt snapshot handler, leaving the visible map
        refresh blocked for >7 seconds. Never acquire that lock before the
        full evidence snapshot is committed to the GUI event loop.
        """
        if self._force_close or getattr(self.controller,"_closed",False):
            self._idle_brief_inflight=False
            return
        controller=self.controller
        signal=self._idle_brief_ready
        generation=snapshot["generation"]
        period=snapshot["brief_period"]
        since=snapshot["brief_since"]

        def collect_brief():
            brief={"generation":generation,"period":period}
            try:
                before=controller.store.content_revision()
                brief["events"]=controller.brief_events(since=since,period=period)
                after=controller.store.content_revision()
                brief["revision_before"]=before
                brief["revision_after"]=after
            except Exception as error:
                brief["error"]=f"{type(error).__name__}: {str(error)[:160]}"
            try:
                signal.emit(brief)
            except RuntimeError:
                pass

        threading.Thread(target=collect_brief,name="pulse-idle-brief",
                         daemon=True).start()

    @Slot(object)
    def _apply_idle_snapshot(self, snapshot):
        """Apply only a current, source-consistent worker result on Qt thread."""
        self._idle_snapshot_inflight=False
        if self._force_close or getattr(self.controller,"_closed",False):
            if snapshot.get("brief_pending"):
                self._idle_brief_inflight=False
            return
        if "error" in snapshot:
            if snapshot.get("brief_pending"):
                self._idle_brief_inflight=False
            self.status_label.setText("Idle evidence refresh failed: "+snapshot["error"])
            return
        if (snapshot["generation"]!=self._idle_snapshot_generation
                or snapshot["scope"]!=self._archive_scope_key()):
            # User actions have their own immediate refresh; stale worker
            # completion must never roll back a newer filter or selection.
            if snapshot.get("brief_pending"):
                self._idle_brief_inflight=False
            return
        # Even checking a revision acquired the same Store lock as the
        # background 5k-event/3.2k-observation read. Do not stall Qt to verify
        # an idle snapshot while another worker owns that lock. Retry the same
        # bounded snapshot and revalidate its generation/scope/revision.
        current_revision=self.controller.store.content_revision_if_available()
        if current_revision is None:
            # Keep single-flight ownership while waiting for a Store reader:
            # otherwise another collector signal can launch a second identical
            # snapshot and cause duplicate map/model population when both land.
            self._idle_snapshot_inflight=True
            QTimer.singleShot(120,lambda s=snapshot:self._apply_idle_snapshot(s))
            return
        if (snapshot["revision_before"]!=snapshot["revision_after"]
                or current_revision!=snapshot["revision_after"]):
            # New collection arrived during the multi-read snapshot: never
            # present a mixed evidence revision or fabricate a status update.
            if snapshot.get("brief_pending"):
                self._idle_brief_inflight=False
            self._schedule_evidence_refresh()
            return
        self.refresh_data(_idle_snapshot=snapshot)
        if snapshot.get("brief_pending"):
            # Give Qt a chance to repaint the newly committed feed/map before
            # the expensive Brief SQL competes for SQLite and the Python GIL.
            QTimer.singleShot(150,lambda s=snapshot:self._begin_idle_brief_read(s))

    @Slot(object)
    def _apply_idle_brief(self, brief):
        self._idle_brief_inflight=False
        if self._force_close or getattr(self.controller,"_closed",False):
            return
        if "error" in brief:
            self.status_label.setText("Idle brief update failed: "+brief["error"])
        elif (brief["generation"]==self._idle_snapshot_generation
              and brief["period"]==self.brief_period.currentText().lower()
              and brief["revision_before"]==brief["revision_after"]
              and brief["revision_after"]==self.controller.store.content_revision()):
            self._deferred_brief_events=brief["events"]
            self._deferred_brief_period=brief["period"]
            self._deferred_brief_revision=brief["revision_after"]
        # A stale result is never displayed. Its current-Store fallback is
        # still available through an explicit user action/next warm.
        self._schedule_workspace_warm()

    @Slot()
    def _schedule_collected_refresh(self):
        """Queue worker-origin source status to this GUI QObject thread."""
        if self._force_close or getattr(self.controller, "_closed", False):
            return
        if not self._collection_refresh_timer.isActive():
            self._collection_refresh_timer.start()

    def _refresh_source_status_ui(self):
        """A provider polling status is not a reason to reload 5k map events."""
        self._dirty_pages.add(3)
        self.last_label.setText(
            "Last collection  " +
            timestamp(getattr(self.controller,"last_collection",""))
        )
        # Source details are only needed if that tab is actually on screen.
        # Actual material report ingest uses Controller.evidence_changed and a
        # bounded, coalesced full event/map refresh. No location is invented.
        if self._background_warm_enabled:
            self._schedule_workspace_warm()
        elif self.pages.currentIndex()==3 and self.isVisible():
            self._populate_sources()
            self._dirty_pages.discard(3)

    def refresh_data(self,*args,_idle_snapshot=None):
        if self._force_close or getattr(self.controller,"_closed",False):
            return
        if (_idle_snapshot is not None
                and self.controller.store.content_revision()!=_idle_snapshot["revision_after"]):
            self._schedule_evidence_refresh()
            return
        if self._refreshing:
            # A newer revision arrived during a reentrant Qt paint. Never
            # drop it; run one more coalesced refresh after this pass.
            self._schedule_evidence_refresh()
            return
        if _idle_snapshot is None:
            # Invalidate any in-flight collector snapshot before applying a
            # newer explicit user selection or filter state.
            self._idle_snapshot_generation+=1
        # Explicit user/filter refresh subsumes a pending collector refresh.
        if self._evidence_refresh_timer.isActive():
            self._evidence_refresh_timer.stop()
        # User-triggered refreshes reconcile providers directly. An
        # evidence-only worker snapshot does NOT include source health; never
        # swallow a separately queued provider failure/retry status pulse.
        if _idle_snapshot is None and self._collection_refresh_timer.isActive():
            self._collection_refresh_timer.stop()
        self._refreshing=True
        # Include Store changes from outside this full UI pass. Only equal
        # before/after revisions can authorize reuse on the next idle signal.
        read_revision=(
            _idle_snapshot["revision_before"] if _idle_snapshot is not None
            else self.controller.store.content_revision())
        try:
            # Apply a source-revision-consistent brief snapshot in a later
            # hidden workspace warm. A manual refresh never reuses old briefs.
            self._deferred_brief_events=None
            self._deferred_brief_period=None
            self._deferred_brief_revision=None
            # An archive/economy evidence revision cannot by itself change
            # source checkpoint state or catalog metadata. The dedicated
            # source_status_changed signal marks Sources dirty when needed.
            # Keep any *already* queued status refresh; never clear it here.
            self._dirty_pages.update(
                range(1,6) if _idle_snapshot is None else (1,2,4,5)
            )
            if _idle_snapshot is None:
                filters=self.events_filters()
                self._events=self.controller.events(**filters)
            else:
                filters=_idle_snapshot["filters"]
                self._history_at=_idle_snapshot["history_at"]
                self._events=_idle_snapshot["feed"]
            if self._archive_selection_id:
                pin=self._archive_selection_id
                if (self._archive_selection_scope!=self._archive_scope_key()
                        or self._feed_explicitly_cleared or self._selected_id!=pin):
                    self._archive_selection_id=""
                    self._archive_selection_scope=None
                elif all(str(e.get("id"))!=pin for e in self._events):
                    # Preserve one explicitly navigated older event on an
                    # evidence refresh, with current (not cached) source bytes.
                    pinned=self.controller.event(pin)
                    if pinned:
                        self._events=[pinned]+list(self._events[:499])
                    else:
                        # Retention or source withdrawal may remove a previously
                        # pinned report between refreshes. Do not silently switch
                        # the Selected Event/Star to a different first feed row.
                        self._archive_selection_id=""
                        self._archive_selection_scope=None
                        self._explicit_feed_selection_id=""
                        self._explicit_feed_selection_scope=None
                        self._feed_explicitly_cleared=True
            # A user-selected ordinary feed row can also age beyond the 500-row
            # page after new collection. Keep just that explicit choice and its
            # current Store evidence; do not silently rebind Star to a new row.
            scope=self._archive_scope_key()
            if (self._explicit_feed_selection_id
                    and self._explicit_feed_selection_scope!=scope):
                self._explicit_feed_selection_id=""
                self._explicit_feed_selection_scope=None
            if (self._selected_id and self._selected_id==self._explicit_feed_selection_id
                    and not self._archive_selection_id and not self._feed_explicitly_cleared
                    and all(str(e.get("id"))!=self._selected_id for e in self._events)):
                pinned=self.controller.event(self._selected_id)
                if pinned:
                    self._events=[pinned]+list(self._events[:499])
                    self._archive_selection_id=self._selected_id
                    self._archive_selection_scope=scope
                else:
                    self._explicit_feed_selection_id=""
                    self._explicit_feed_selection_scope=None
                    self._feed_explicitly_cleared=True
            # A filter or historical-time change can remove the previously
            # selected event from the visible feed without deleting it from
            # the Store. Never leave a hidden event bound to the Brief/Star.
            visible_ids={str(event.get("id","")) for event in self._events}
            if self._selected_id and self._selected_id not in visible_ids:
                self._selected_id=""
            self._populate_filter_options(
                None if _idle_snapshot is None else _idle_snapshot["filter_options"])
            self._sync_map_controls()
            map_filters={**filters,"limit":5000,"map_view":True,"keep_significant":not bool(self._history_at)}
            country_evidence=(self.controller.events(**dict(map_filters,map_evidence=True))
                              if _idle_snapshot is None
                              else _idle_snapshot["country_evidence"])
            from .brief_selection import overview_evidence_candidates
            self._overview_events=overview_evidence_candidates(self._events,country_evidence)
            # Economic observations have their own dated country-level layer.
            # Hide it during search/region/history replay because observations
            # do not share those event-filter semantics.
            show_observations = (not self._history_at and not filters.get("query")
                                 and not filters.get("region")
                                 and filters.get("category") in {"", "Economy"})
            economy_revision_before=(
                _idle_snapshot["revision_before"] if _idle_snapshot is not None and show_observations
                else self.controller.store.content_revision() if show_observations else None)
            observations=(
                _idle_snapshot["observations"] if _idle_snapshot is not None
                else self.controller.store.list_observations() if show_observations else [])
            economy_revision_after=(
                _idle_snapshot["revision_after"] if _idle_snapshot is not None and show_observations
                else self.controller.store.content_revision() if show_observations else None)
            # Reuse only a source-consistent revision in the deferred Economy
            # workspace. Worker writes, including those made after the initial
            # paint, MUST invalidate the old in-RAM rows before prewarm.
            valid_economy_revision=(show_observations
                                    and economy_revision_before==economy_revision_after)
            self._deferred_economy_observations=(observations
                                                 if valid_economy_revision else None)
            self._deferred_economy_revision=(economy_revision_after
                                             if valid_economy_revision else None)
            self.world_map.set_events(
                (self.controller.events(**map_filters) if _idle_snapshot is None
                 else _idle_snapshot["map_events"]),
                country_events=country_evidence,
                observations=observations,
                preclassified_country=(_idle_snapshot.get("map_classification")
                                       if _idle_snapshot is not None else None),
            )
            if self.gdelt_panel is not None:self.gdelt_panel.refresh(filters)
            self._populate_feed()
            self._update_world_overview()
            self.last_label.setText("Last collection  "+timestamp(getattr(self.controller,"last_collection","")))
            self._status_update("")
            count=len(self._events);self.feed_count.setText(str(count))
            retained=sum(bool(e.get("retained_on_map")) for e in self.world_map.events)
            suffix=f" · {retained} significant retained" if retained else ""
            cap=" · map limit 5,000; narrow filters" if len(self.world_map.events)>=5000 else ""
            self.count_label.setText(f"{count} feed events · "+self.world_map.coverage_summary()+suffix+cap)
            if self._selected_id:
                selected=self._selected_event()
                if selected:self._render_event(selected)
                else:self._render_empty_brief()
            else:self._render_empty_brief()
            page=self.pages.currentIndex()
            if page==1:self._populate_situations()
            elif page==2:self._populate_economy(observations if show_observations else None)
            elif page==3 and _idle_snapshot is None:self._populate_sources()
            elif page==4:self._populate_alerts()
            elif page==5:self._generate_brief()
            if page!=3 or _idle_snapshot is None:
                self._dirty_pages.discard(page)
            self._schedule_workspace_warm()
            confirmed=self.controller.store.content_revision_if_available()
            if (confirmed is not None and confirmed==read_revision
                    and not self._history_at and not self._archive_selection_id
                    and not self._explicit_feed_selection_id):
                # Evidence is immutable at this Store revision; capture only
                # source dictionaries and the already rebuilt selector values.
                self._idle_feed_cache={
                    "revision":confirmed, "scope":self._archive_scope_key(),
                    "filters":dict(filters), "feed":tuple(self._events),
                    "filter_options":{
                        "category":[self.category.itemData(i) for i in range(1,self.category.count())],
                        "region":[self.region.itemData(i) for i in range(1,self.region.count())],
                    },
                }
            else:
                self._idle_feed_cache=None
            self._last_full_refresh_at=time.monotonic()
        except Exception as exc:
            self._idle_feed_cache=None
            self.status_label.setText(f"Could not update view: {type(exc).__name__}: {str(exc)[:160]}")
        finally:self._refreshing=False

    def _populate_filter_options(self, options=None):
        # Explicit/filter refreshes retain synchronous semantics; validated
        # idle snapshots use the worker-read, same-revision selector metadata.
        # Preserve a now-missing *selected* value below (never broaden to All).
        if options is None:
            options=self.controller.event_filter_options()
        for combo,key,all_title in ((self.category,"category","All categories"),(self.region,"region","All regions")):
            current=combo.currentData() or ""
            # Explicit filters must never broaden because a feed page changes or
            # the last matching record is pruned. A now-empty selection stays.
            values=sorted(set(options[key]) | ({current} if current else set()))
            existing=[combo.itemData(i) for i in range(1,combo.count())]
            if values!=existing:
                blocked=combo.blockSignals(True)
                try:
                    combo.clear();combo.addItem(all_title,"")
                    for value in values:combo.addItem(value,value)
                    combo.setCurrentIndex(combo.findData(current))
                finally:
                    combo.blockSignals(blocked)

    def _populate_feed(self,*args):
        if not hasattr(self,"feed_list"):
            return
        english_enabled=self.controller.get_setting("english_headlines",True) is True
        if hasattr(self,"english_headlines"):
            was_blocked=self.english_headlines.blockSignals(True)
            self.english_headlines.setChecked(english_enabled)
            self.english_headlines.blockSignals(was_blocked)
        events=list(self._events)
        saved_ids=self.controller.store.saved_situation_ids()
        if self.sort_combo.currentIndex()==1:
            order={"critical":4,"high":3,"moderate":2,"informational":1,"unassessed":0}
            events.sort(key=lambda e:(order.get(e.get("severity"),0),str(e.get("updated_at",""))),reverse=True)
        elif self.sort_combo.currentIndex()==2:
            events.sort(key=lambda e:int(e.get("report_count",0)),reverse=True)
        if not self._selected_id and events and not self._feed_explicitly_cleared:
            self._selected_id=str(events[0].get("id",""))

        # Complete canonical source bytes, not just ID/update time: a corrected
        # story, retraction, report URL or nested warning area can change without
        # a new feed identity. The snapshot is volatile, never persisted/uploaded.
        # Star state, user sort and language preference are separate inputs.
        # On an unchanged collector revision there is no reason to touch 500
        # Qt rows or repeat 500 local headline-resolution calls on the GUI thread.
        feed_key=(json.dumps(events,sort_keys=True,ensure_ascii=False,
                             separators=(",",":"),default=str),
                  tuple(sorted(saved_ids)),self.sort_combo.currentIndex(),
                  english_enabled)
        if (feed_key==getattr(self,"_feed_snapshot_key",None)
                and self.feed_list.count()==len(events)):
            selected_item=next((self.feed_list.item(i) for i,event in enumerate(events)
                                if str(event.get("id",""))==self._selected_id),None)
            if self.feed_list.currentItem() is not selected_item:
                old_block=self.feed_list.blockSignals(True)
                try:
                    self.feed_list.setCurrentItem(selected_item)
                finally:
                    self.feed_list.blockSignals(old_block)
            self.feed_empty.setVisible(not events)
            self.feed_list.setVisible(bool(events))
            return

        # Collector refreshes often change map/source evidence without changing
        # the visible 500 feed identities. Never destroy/recreate hundreds of
        # QListWidgetItems on those idle GUI revisions. Keep the existing row
        # objects, current selection, scroll position and translated labels;
        # reconcile changed source/Star/language data on the existing rows.
        role=Qt.ItemDataRole.UserRole
        same_order=(self.feed_list.count()==len(events) and all(
            isinstance((row:=self.feed_list.item(i).data(role)),dict)
            and str(row.get("id",""))==str(event.get("id",""))
            for i,event in enumerate(events)
        ))
        old_block=self.feed_list.blockSignals(True)
        self.feed_list.setUpdatesEnabled(False)
        try:
            if not same_order:
                self.feed_list.clear()
            selected_item=None
            for index,event in enumerate(events):
                starred=str(event.get("id","")) in saved_ids
                view=(self.controller.headline_view(event,defer_language=True)
                      if hasattr(self.controller,"headline_view")
                      else {"title":str(event.get("title","Untitled event")),
                            "original":str(event.get("title","")),
                            "label":"Original headline"})
                row=dict(event,_situation_starred=starred,
                         _display_title=view["title"],_translation_label=view["label"])
                tip=("<div style='white-space:pre-wrap'>"+
                     esc(view["label"]+"\nOriginal: "+view["original"]+"\n"+
                         str(event.get("recap","")))+"</div>")
                item=self.feed_list.item(index) if same_order else QListWidgetItem(view["title"])
                if not same_order:
                    self.feed_list.addItem(item)
                if item.text()!=view["title"]:
                    item.setText(view["title"])
                if item.data(role)!=row:
                    item.setData(role,row)
                if item.toolTip()!=tip:
                    item.setToolTip(tip)
                if str(event.get("id",""))==self._selected_id:
                    selected_item=item
            if self.feed_list.currentItem() is not selected_item:
                # A vanished/filtered explicit selection must never remain
                # bound to an unrelated Star or evidence view.
                self.feed_list.setCurrentItem(selected_item)
        finally:
            self.feed_list.setUpdatesEnabled(True)
            self.feed_list.blockSignals(old_block)
        self.feed_empty.setVisible(not events)
        self.feed_list.setVisible(bool(events))
        self._feed_snapshot_key=feed_key

    @Slot()
    def _refresh_translated_headlines(self):
        """Refresh display text IN PLACE, preserving Qt row object ownership.

        Language-worker notifications may arrive during a context-menu modal
        event loop or Star/tab navigation. Clearing the list deletes its
        QListWidgetItems and invalidates the row a pending click still owns.
        This method never changes ordering, selection, media, evidence, or map.
        """
        if not hasattr(self,"feed_list"):
            return
        for index in range(self.feed_list.count()):
            item=self.feed_list.item(index)
            if item is None:
                continue
            event=item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(event,dict):
                continue
            view=(self.controller.headline_view(event,defer_language=True)
                  if hasattr(self.controller,"headline_view")
                  else {"title":str(event.get("title","Untitled event")),
                        "original":str(event.get("title","")),
                        "label":"Original headline"})
            title=str(view["title"])
            if title != item.text():
                item.setText(title)
            if event.get("_display_title") != title or event.get("_translation_label") != view["label"]:
                item.setData(Qt.ItemDataRole.UserRole,dict(
                    event,_display_title=title,_translation_label=view["label"]
                ))
                item.setToolTip(
                    "<div style='white-space:pre-wrap'>" +
                    esc(view["label"]+"\nOriginal: "+view["original"]+
                        "\n"+str(event.get("recap",""))) + "</div>"
                )
        if self._selected_id:
            event=self._selected_event()
            if event:
                brief_scroll=self.intel_browser.verticalScrollBar().value()
                self._render_event(event,update_media=False)
                self.intel_browser.verticalScrollBar().setValue(brief_scroll)

    def _update_world_overview(self):
        """Format bounded already-loaded feed/map records without new queries."""
        from .brief_selection import overview_html
        scope=(self.time_range.currentText().lower() +
               (", filtered" if self.category.currentData() or
                self.region.currentData() or self.search.text().strip()
                else ", all categories"))
        updated=overview_html(self._overview_events, label=scope+" local feed and retained map evidence")
        if updated != self._overview_html_cached:
            position=self.overview_browser.verticalScrollBar().value()
            self.overview_browser.setHtml(updated)
            self.overview_browser.verticalScrollBar().setValue(position)
            self._overview_html_cached=updated

    def _open_overview_event(self, url):
        """Only local event IDs are actionable; never treat links as web URLs."""
        if url.scheme() != "pulse-event" or url.host() != "open":
            return
        from urllib.parse import unquote
        identity=unquote(url.path().lstrip("/"))
        if identity and any(str(e.get("id"))==identity for e in self._overview_events):
            self.navigate_event(identity)
            self.intelligence_mode.setCurrentIndex(1)

    def _render_empty_brief(self):
        self.intel_browser.setHtml("<p style='color:#a78bfa;font-size:18px'><b>Connect the evidence.</b></p><p style='color:#a5afc1'>Select an event to inspect its recap, original sources, verification state, and competing claims.</p><p style='color:#748198'>Official attribution and independent corroboration are shown separately. Coverage gaps remain visible.</p>")
        self.evidence_status_text.setPlainText("No event selected · no confidence inferred.")
        self.change_status_text.setPlainText("Saved situations and recorded changes appear here.")
        if hasattr(self.media,"set_event"):self.media.set_event(None)
        for b in (self.save_button,self.original_button,self.translate_button):b.setEnabled(False)
        self._sync_situation_star(None)

    def _render_event(self,event, *, update_media=True):
        view=self.controller.headline_view(event) if hasattr(self.controller,"headline_view") else {"title":str(event.get("title","")),"original":str(event.get("title","")),"label":"Original headline"}
        severity=event.get("severity","unassessed");color=SEVERITY.get(severity,SEVERITY["unassessed"])
        reports=event.get("reports",[]);ind=event.get("independent_origins",[])
        if not isinstance(ind,list):ind=[]
        parts=[f"<p style='color:{color};font-size:10px'><b>{esc(severity).upper()}  /  {esc(event.get('verification','unverified')).upper()}</b></p>",f"<h3 style='font-size:17px;color:#f0edf8'>{esc(view['title'])}</h3>",f"<p style='color:#8e9cb3;font-size:10px'>{esc(event.get('region'))} · {esc(report_time(event))}<br>Updated {esc(timestamp(event.get('updated_at')))}</p>",f"<p style='line-height:145%'>{esc(event.get('recap','Limited source information is available.'))}</p>"]
        parts.append(f"<p>{esc(view['label'])}</p>")
        if view["title"] != view["original"]:parts.append(f"<p><b>Original headline:</b> {esc(view['original'])}</p>")
        if event.get("synthetic"):parts.append("<p style='color:#edc46a'><b>FICTIONAL TRAINING EVENT</b></p>")
        parts.append(f"<hr><p style='color:#b59ae8'><b>EVIDENCE</b></p><p>{len(reports)} reports · {len(ind)} identified independent origins</p>")
        if any(r.get("official") for r in reports):parts.append("<p style='color:#9caac0'>Official attribution confirms that the source made a statement or published a measurement. It does not confirm every underlying claim.</p>")
        for reason in event.get("reasons",[]):parts.append(f"<p>• {esc(reason)}</p>")
        contradictions=event.get("contradictions",[])
        if contradictions:
            parts.append("<p style='color:#e2b070'><b>CONFLICTING REPORTS</b></p>")
            for c in contradictions:
                text=c.get("description") or c.get("summary") or json.dumps(c,ensure_ascii=False) if isinstance(c,dict) else str(c)
                parts.append(f"<p>{esc(text)}</p>")
        parts.append("<p style='color:#b59ae8'><b>SOURCE TRAIL</b></p>")
        for r in reports[:25]:
            source=r.get("publisher") or r.get("source_id") or "Source"
            status="Retracted" if r.get("retraction_of") or r.get("kind")=="retraction" else "Correction" if r.get("correction_of") or r.get("kind")=="correction" else r.get("independence","unknown")
            credit=" · ".join(str(r.get(k,"")) for k in ("byline","attribution","source_license") if r.get(k))
            provenance=[]
            if r.get("source_country"):
                provenance.append("Outlet/source country (not event location): " + str(r["source_country"]))
            if r.get("metadata_only"):
                provenance.append("Metadata-only discovery record")
            provenance_text=" · ".join(provenance)
            parts.append(f"<p><a style='color:#bfa8ec' href='{esc(r.get('url',''))}'>{esc(source)}</a> <span style='color:#7d8ca6'> · {esc(status)}</span><br>{esc(r.get('title',''))}<br><span style='font-size:10px;color:#7d8ca6'>{esc(report_time(r))}<br>{esc(provenance_text)}{('<br>' if provenance_text and credit else '')}{esc(credit)}</span></p>")
        if len(reports)>25:parts.append(f"<p style='color:#8e9cb3'>{len(reports)-25} further source records are retained. Open this Situation Room or export the archive to inspect the complete evidence trail.</p>")
        timeline=event.get("timeline",[])
        if timeline:
            parts.append("<p style='color:#b59ae8'><b>RECENT CHANGES</b></p>")
            for t in timeline[-6:]:
                if isinstance(t,dict):parts.append(f"<p style='color:#a5b1c4'>{esc(timestamp(t.get('at') or t.get('created_at') or t.get('timestamp')))}<br>{esc(t.get('description') or t.get('summary') or t.get('title') or t.get('change') or 'Evidence updated')}</p>")
        if event.get("geo_precision") and event.get("geo_precision")!="exact":parts.append(f"<p style='color:#8c9ab2'>Location precision: {esc(event.get('geo_precision'))}. Regional markers are not exact incident locations.</p>")
        for linked, snapshots in event.get("linked_event_histories", {}).items():
            parts.append(f"<p><b>Linked warning history</b> · {esc(linked)}</p>")
            for snapshot in snapshots:
                parts.append(f"<p>{esc(timestamp(snapshot['at']))} · {esc(snapshot['title'])}</p>")
        self.intel_browser.setHtml("".join(parts))
        eligible=[r for r in reports if not r.get("future_dated") and r.get("evidence_status","active")=="active"]
        self.evidence_status_text.setPlainText(
            f"{event.get('verification','unverified').title()} · {len(ind)} independent origins\n"
            f"{len(reports)} source records · {len(event.get('contradictions',[]))} discrepancies\n"
            f"{len(eligible)} currently eligible records")
        self.change_status_text.setPlainText(
            f"{event.get('status','active').title()} · revision {event.get('revision',1)}\n"
            f"{timestamp(event.get('updated_at'))}\n"
            f"{len(event.get('changes',[]))} recorded change(s)")
        self._sync_situation_star(event);self.original_button.setEnabled(bool(reports and reports[0].get("url")));self.translate_button.setEnabled(bool(reports))
        if update_media and hasattr(self.media,"set_event"):self.media.set_event(dict(event,historical_view=bool(self._history_at)))

    def _feed_selected(self,item,previous):
        if item:
            self._feed_explicitly_cleared=False
            self.intelligence_mode.setCurrentIndex(1)
            e=item.data(Qt.ItemDataRole.UserRole)
            self._explicit_feed_selection_id=str(e.get("id") or "")
            self._explicit_feed_selection_scope=self._archive_scope_key()
            if str(e.get("id") or "")!=self._archive_selection_id:
                self._archive_selection_id=""
                self._archive_selection_scope=None
            self._selected_id=str(e.get("id",""));self.world_map.select_event(self._selected_id);full=self._selected_event() or e;self._render_event(full)
        else:
            # Explicit deselection survives queued headline and source refresh.
            # It must never silently bind the Star button to another event.
            self._feed_explicitly_cleared=True
            self._archive_selection_id=""
            self._archive_selection_scope=None
            self._explicit_feed_selection_id=""
            self._explicit_feed_selection_scope=None
            self._selected_id=""
            self._render_empty_brief()

    def _selected_event(self):
        if self._history_at:
            return self.controller.store.get_event(self._selected_id,at=self._history_at)
        return self.controller.event(self._selected_id)

    def navigate_event(self,event_id):
        """Navigate from map/alerts without repeated full archive/map rebuilds.

        The old map-click path could emit four filter signals followed by one
        explicit refresh, then rebuild all 500 feed rows again. On an active
        collector with thousands of country-evidence reports, those synchronous
        refreshes stall the Windows GUI event loop.
        """
        identity = str(event_id or "")
        event = self.controller.event(identity)
        if not event:
            self.status_label.setText("This event is no longer in the local archive.")
            return
        self._selected_id = identity
        self._feed_explicitly_cleared=False
        self.open_page(0)
        self.intelligence_mode.setCurrentIndex(1)

        # Historical replay or an event outside the current feed requires one
        # deliberate broaden-to-All archive navigation. Change ALL dimensions
        # atomically, without invoking every combo's refresh_data slot.
        visible = any(str(e.get("id")) == identity for e in self._events)
        reset_view = not visible or self.history_slider.value() != 1000
        if reset_view:
            self.search_timer.stop()
            updates = (
                (self.search, "text", ""),
                (self.category, "index", 0),
                (self.region, "index", 0),
                (self.time_range, "index", 3),
                (self.history_slider, "value", 1000),
            )
            for control, mode, value in updates:
                before = control.blockSignals(True)
                try:
                    if mode == "text":
                        control.setText(value)
                    elif mode == "index":
                        control.setCurrentIndex(value)
                    else:
                        control.setValue(value)
                finally:
                    control.blockSignals(before)
            self.history_label.setText("Latest")
            # This refresh also populates the feed and renders the selected
            # record if it is inside the 500-row feed window.
            self.refresh_data()
            if not any(str(e.get("id")) == identity for e in self._events):
                # A country/incident map may expose any of 5,000 positions;
                # it is normal for the clicked archived record to fall outside
                # the first 500 feed rows. Explicitly include only that chosen
                # event in the current feed (one list construction), so the
                # selected Brief/Star remains bound to a visible canonical row.
                self._events = [event] + list(self._events[:499])
                self._selected_id = identity
                self._populate_feed()
                self._render_event(event)
                self.feed_count.setText(str(len(self._events)))
                self._archive_selection_id=identity
                self._archive_selection_scope=self._archive_scope_key()
            else:
                self._archive_selection_id=""
                self._archive_selection_scope=None
        else:
            # The selected row already exists; only synchronize its selection
            # and the brief. Never reconstruct 500 QListWidgetItems for a
            # single map click.
            # Re-opening the same explicitly pinned archive record is not
            # deselection. Keep the pin until a different story or filter wins.
            if identity != self._archive_selection_id:
                self._archive_selection_id=""
                self._archive_selection_scope=None
            previous = self.feed_list.blockSignals(True)
            try:
                for row_index in range(self.feed_list.count()):
                    row = self.feed_list.item(row_index)
                    data = row.data(Qt.ItemDataRole.UserRole) or {}
                    if str(data.get("id") or "") == identity:
                        self.feed_list.setCurrentItem(row)
                        break
            finally:
                self.feed_list.blockSignals(previous)
            self._render_event(event)

        self._explicit_feed_selection_id=identity
        self._explicit_feed_selection_scope=self._archive_scope_key()
        self.world_map.select_event(identity,center=True)
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def _open_original(self):
        e=self._selected_event()
        if e and e.get("reports"):self.controller.open_url(e["reports"][0].get("url",""))

    def _translate_selected(self):
        e=self._selected_event()
        if e and e.get("reports"):
            report=next((r for r in e["reports"] if r.get("language","en")!="en"),e["reports"][0])
            self.status_label.setText("Translating available source text locally…")
            self.controller.translate_report(report)

    @Slot(str, str)
    def _translation_done(self,report_id,text):
        self.status_label.setText("Translation request completed.")
        box=QMessageBox(self);box.setWindowTitle("English translation");box.setTextFormat(Qt.TextFormat.PlainText);box.setText(str(text));box.setIcon(QMessageBox.Icon.Information);box.exec()

    def _save_selected(self):
        if self._selected_id:
            self._set_situation_star(self._selected_id, True)

    def _populate_situations(self):
        self._refresh_saved_situations()

    def _visit_situation(self,item):
        event_id=item.data(Qt.ItemDataRole.UserRole);result=self.controller.store.visit_situation(event_id);event=self.controller.event(event_id) or {}
        changes=result.get("changes",[]) if isinstance(result,dict) else []
        parts=[f"<h2>{esc(event.get('title','Situation Room'))}</h2>","<h3>What changed since my last visit?</h3>"]
        if not changes:parts.append("<p>No newer recorded changes since your last visit.</p>")
        else:
            for change in changes:
                value=change.get("description") or change.get("summary") or change.get("title") or json.dumps(change,ensure_ascii=False) if isinstance(change,dict) else str(change)
                parts.append(f"<p>{esc(value)}</p>")
        parts.append(f"<h3>Current assessment</h3><p>{esc(event.get('recap',''))}</p><p>{esc(event.get('verification','unverified'))} · {esc(event.get('severity','unassessed'))}</p><h3>Evidence and timeline</h3>")
        for report in event.get("reports",[]):
            credit=" · ".join(str(report.get(k,"")) for k in ("byline","attribution","source_license") if report.get(k))
            parts.append(f"<p>{esc(report_time(report))} — <a href='{esc(report.get('url',''))}'>{esc(report.get('publisher','Source'))}</a><br>{esc(report.get('title',''))}<br><span style='color:#8e9cb3'>{esc(credit)}</span></p>")
        self.situation_browser.setHtml("".join(parts))

    def _populate_economy(self,observations=None):
        # During a collector refresh, the map already read all dated economy
        # observations. Reuse that exact source snapshot ONCE in scheduled
        # idle workspace prewarm, rather than a second synchronous SQLite read.
        # Explicit later activation (or a fresh Store revision) still reads
        # current evidence. Never cache across a separate refresh revision.
        if observations is None:
            revision=getattr(self,"_deferred_economy_revision",None)
            if (revision is not None
                    and revision==self.controller.store.content_revision()):
                observations=getattr(self,"_deferred_economy_observations",None)
        self._deferred_economy_observations=None
        self._deferred_economy_revision=None
        fresh_observations=(self.controller.store.list_observations()
                            if observations is None else observations)
        # A collector can change a crisis/feed/source checkpoint while the
        # dated economy dataset is byte-for-byte unchanged. The hidden idle
        # warm used to reset the virtual table model, invalidate the chart
        # pixmap, and rebuild both dropdowns for all 3,200 unchanged rows.
        # Compare complete source dictionaries, not only a Store revision or
        # row count: corrected values, dates, attribution and withdrawal must
        # still repaint. A queued map country selection must always execute.
        if (self._pending_economic_country is None
                and hasattr(self, "_observations")
                and fresh_observations == self._observations):
            return
        self._observations=fresh_observations
        by_indicator={}
        for observation in self._observations:
            by_indicator.setdefault(str(observation.get("indicator","")),[]).append(observation)
        self._observations_by_indicator=by_indicator
        current=self.indicator_combo.currentData();country=self.economy_country.currentData()
        self.indicator_combo.blockSignals(True);self.indicator_combo.clear();indicators={str(o.get("indicator", "")):str(o.get("indicator_name") or o.get("description") or o.get("indicator") or "Economic indicator") for o in self._observations}
        for key,value in sorted(indicators.items()):self.indicator_combo.addItem(value,key)
        self.indicator_combo.setCurrentIndex(max(0,self.indicator_combo.findData(current)));self.indicator_combo.blockSignals(False)
        self.economy_country.blockSignals(True);self.economy_country.clear();self.economy_country.addItem("All countries","")
        for c in sorted({str(o.get("country_name") or o.get("country", "")) for o in self._observations}):self.economy_country.addItem(c,c)
        self.economy_country.setCurrentIndex(max(0,self.economy_country.findData(country)));self.economy_country.blockSignals(False)
        # Resolve the pending map selection BEFORE building a chart/model.
        # Previously this populated the entire chart/table twice on one
        # collector-driven warm cycle, including the idle period before clicks.
        if self._pending_economic_country is None:
            self._populate_economic_selection()
        else:
            self._apply_pending_economic_country()

    def _manual_economy_selection(self,*args):
        """A deliberate dropdown choice supersedes an older queued map click."""
        self._pending_economic_country=None
        self._populate_economic_selection()

    def _populate_economic_selection(self,*args):
        selected=self.indicator_combo.currentData();country=self.economy_country.currentData()
        data=[o for o in getattr(self,"_observations_by_indicator",{}).get(selected,())
              if not country or str(o.get("country_name") or o.get("country"))==country]
        self.economic_chart.set_observations(data)
        if data:
            first=data[0];credit=" · ".join(str(first.get(key,"")) for key in ("attribution","source_license") if first.get(key))
            updated=" Provider dataset updated "+str(first["dataset_updated_at"])+"; individual release date shown only when supplied." if first.get("dataset_updated_at") else ""
            self.economy_explanation.setText(str(first.get("description") or selected or "")+" · Unit: "+str(first.get("unit") or "See source definition")+". "+credit+updated+" Double-click a row to open its original source.")
        else:self.economy_explanation.setText("No economic observations have been collected for this selection.")
        # All source records are already in RAM. QTableView materializes only
        # visible cells: no per-row or per-cell Qt object creation on a tab.
        self.economy_model.set_observations(data)

    def _open_economic_source(self,row,column):
        url=self.economy_model.url_at(row)
        if url:self.controller.open_url(url)

    def _populate_sources(self):
        from .provider_actions import populate_sources
        return populate_sources(self)

    def _source_selected(self):
        from .provider_actions import source_selected
        return source_selected(self)

    def _populate_alerts(self):
        self.notification_label.setText(str(getattr(self.controller,"notification_status","Native notification status unavailable.")))
        self.alert_list.clear()
        for a in self.controller.store.list_alerts():
            event=a.get("event") if isinstance(a.get("event"),dict) else self.controller.event(a.get("event_id","")) or {}
            title=a.get("title") or event.get("title") or "Event alert"
            item=QListWidgetItem(f"{title}\n{a.get('reason','Material development')}\n{timestamp(a.get('created_at') or a.get('timestamp'))}");item.setData(Qt.ItemDataRole.UserRole,a);self.alert_list.addItem(item)

    def _open_alert(self,item):
        a=item.data(Qt.ItemDataRole.UserRole)
        if a.get("id"):self.controller.store.mark_alert_read(a["id"])
        event_id=a.get("event_id") or (a.get("event") or {}).get("id")
        if event_id:self.navigate_event(event_id)

    def _generate_brief(self):
        period=self.brief_period.currentText().lower();days=1 if period=="daily" else 7
        # A collector-driven idle refresh has already queried this exact
        # period off Qt. Verify the same Store revision before presentation;
        # user period changes and intervening evidence writes use a new query.
        # No stale cached brief can replace a newer or corrected story.
        cached=getattr(self,"_deferred_brief_events",None)
        valid=(cached is not None
               and getattr(self,"_deferred_brief_period",None)==period
               and getattr(self,"_deferred_brief_revision",None)==self.controller.store.content_revision())
        self._deferred_brief_events=None
        self._deferred_brief_revision=None
        self._deferred_brief_period=None
        events=(cached if valid else self.controller.brief_events(
            since=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat(),period=period))
        from .brief_rendering import brief_html
        self.brief_browser.setHtml(brief_html(events,period))

    def _export_brief(self):
        path,_=QFileDialog.getSaveFileName(self,"Export intelligence brief","Global-Pulse-brief.html","HTML with severity colors (*.html);;Markdown (*.md);;Text (*.txt)")
        if path:
            try:self.controller.export_brief(path,self.brief_period.currentText().lower());self.status_label.setText("Intelligence brief exported.")
            except Exception as exc:QMessageBox.warning(self,"Export failed",str(exc))

    def _export_events(self):
        path,_=QFileDialog.getSaveFileName(self,"Export event archive","Global-Pulse-events.json","JSON (*.json);;CSV (*.csv)")
        if path:
            try:self.controller.export_events(path);self.status_label.setText("Event archive exported.")
            except Exception as exc:QMessageBox.warning(self,"Export failed",str(exc))

    def _populate_source_preferences(self):
        from .provider_actions import populate_preferences
        return populate_preferences(self)

    def _enable_all_available_sources(self):
        from .source_availability import available_ids
        collectable=available_ids(self.controller.catalog)
        for i in range(self.source_preferences.rowCount()):
            control=self.source_preferences.cellWidget(i,0)
            if isinstance(control,QCheckBox) and control.isEnabled():
                control.setChecked(control.property("source_id") in collectable)
        self.settings_result.setText(
            f"{len(collectable)} available sources selected. Choose Save settings to activate; provider limits still apply."
        )

    def _save_settings(self):
        try:
            for value in (self.quiet_start.text(),self.quiet_end.text()):datetime.strptime(value,"%H:%M")
        except ValueError:
            self.settings_result.setText("Enter quiet hours in 24-hour HH:MM format, such as 22:00 and 07:00.");return
        values={"interval":self.setting_interval.currentData(),"retention_days":self.setting_retention.value(),"close_to_tray":self.setting_close.isChecked(),"notifications_enabled":self.setting_notify.isChecked(),"quiet_enabled":self.setting_quiet.isChecked(),"quiet_start":self.quiet_start.text().strip(),"quiet_end":self.quiet_end.text().strip(),"countries":[v.strip() for v in self.setting_countries.text().split(",") if v.strip()],"categories":[v.strip() for v in self.setting_categories.text().split(",") if v.strip()]}
        enabled=[];muted=[]
        for i in range(self.source_preferences.rowCount()):
            check=self.source_preferences.cellWidget(i,0);source_id=check.property("source_id")
            if isinstance(check,QCheckBox) and check.isChecked() and check.isEnabled():enabled.append(source_id)
            if self.source_preferences.cellWidget(i,1).isChecked():muted.append(source_id)
        values["enabled_sources"]=enabled;values["muted_sources"]=muted
        values["alert_threshold"]=self.setting_threshold.currentData()
        self._batch_settings_updates=True
        self._settings_data_changed=False
        try:
            for key,value in values.items():
                # No-op saves must not redraw the map or relaunch the helper.
                if self.controller.get_setting(key,None)!=value:
                    self.controller.set_setting(key,value)
            self._dirty_pages.update((2,3,4,5))
            self._schedule_workspace_warm()
            self.settings_result.setText("Settings saved. Provider rate limits still apply; existing history stays available.")
        except Exception as exc:
            self.settings_result.setText(f"Settings could not be saved: {exc}")
        finally:
            # Even if a later field fails, earlier successfully saved fields
            # must become visible, but they cause only one map reconciliation.
            self._batch_settings_updates=False
            if self._settings_data_changed:
                self._settings_data_changed=False
                self.refresh_data()

    def _add_user_feed(self):
        if not hasattr(self.controller,"add_user_feed"):
            self.status_label.setText("Custom-feed configuration is unavailable in this build.");return
        url,ok=QInputDialog.getText(self,"Add public RSS / Atom feed","HTTPS feed URL (use only a source you are permitted to process):")
        if not ok or not url.strip():return
        name,ok=QInputDialog.getText(self,"Source name","Publisher or feed name:")
        if not ok or not name.strip():return
        try:
            self.controller.add_user_feed(url.strip(),name.strip())
            self._populate_sources();self._populate_source_preferences();self.status_label.setText("Public feed added. Its source limits and attribution remain visible in Sources.")
        except (ValueError,TypeError) as exc:QMessageBox.warning(self,"Feed could not be added",str(exc))

    def _remove_user_feed(self):
        items=self.source_table.selectedItems()
        if not items:
            self.status_label.setText("Select a custom feed in Sources first.");return
        source=items[0].data(Qt.ItemDataRole.UserRole) or {}
        if source.get("access_status")!="user_supplied" or not source.get("custom"):
            QMessageBox.information(self,"Built-in source","Only a user-configured public feed can be removed.");return
        answer=QMessageBox.question(
            self,
            "Remove custom feed?",
            f"Stop collecting {source.get('name',source.get('id','this feed'))} and remove its saved feed configuration?\n\n"
            "Existing local history remains until its retention limit. Separately exported files are unchanged.",
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer!=QMessageBox.StandardButton.Yes:return
        try:
            self.controller.remove_user_feed(source.get("id",""))
            self.source_browser.clear();self._populate_sources();self._populate_source_preferences()
            self.status_label.setText("Custom feed removed. Existing history remains subject to retention.")
        except (ValueError,TypeError) as exc:QMessageBox.warning(self,"Feed could not be removed",str(exc))

    def _manage_translation(self):
        if hasattr(self.controller,"manage_translation_models"):
            self.controller.manage_translation_models(self)
        else:
            QMessageBox.information(self,"Offline translation","Install a licensed Argos Translate model package through the approved translation setup. Global Pulse does not silently download models. Installed languages are detected when translation is requested.")

    def _refresh_sources(self):
        self.controller.refresh();self.status_label.setText("Collection requested. Provider cooldowns and rate limits remain in effect.")

    def _toggle_monitoring(self):
        self.controller.pause() if self.controller.monitoring else self.controller.resume();self._status_update("")

    @Slot(str)
    def _status_update(self,text):
        monitoring=bool(getattr(self.controller,"monitoring",False))
        changed=monitoring!=self._last_rendered_monitoring
        if changed:
            # Style-sheet reparsing on each provider status used to invalidate
            # every child widget in the main Qt window during live collection.
            self.titlebar.status.setText("MONITORING" if monitoring else "PAUSED")
            self.pause_button.setText("Pause" if monitoring else "Resume")
            self.titlebar.status.setStyleSheet("color:#7fdbb2;background:#173029;border:1px solid #284d40;border-radius:9px;padding:3px 9px;font-size:10px;" if monitoring else "color:#d3bd8f;background:#30291e;border:1px solid #514532;border-radius:9px;padding:3px 9px;font-size:10px;")
            self._last_rendered_monitoring=monitoring
        last="Last collection  "+timestamp(getattr(self.controller,"last_collection",""))
        if self.last_label.text()!=last:self.last_label.setText(last)
        if text:self.status_label.setText(str(text)[:250])
        if not text and not changed:return
        self._dirty_pages.add(3)
        if self._background_warm_enabled:
            self._schedule_workspace_warm()
        elif self.pages.currentIndex()==3:
            self._populate_sources()
            self._dirty_pages.discard(3)

    @Slot(dict)
    def _on_alert(self,alert):
        self.status_label.setText("New alert saved in Alerts.")
        self._dirty_pages.add(4)
        if self._background_warm_enabled:
            self._schedule_workspace_warm()
        elif self.pages.currentIndex()==4:
            self._populate_alerts()
            self._dirty_pages.discard(4)

    def _find_country(self,*args):
        name=args[0] if args and isinstance(args[0],str) else self.country_search.text().strip()
        if not self.world_map.select_country(name):self.status_label.setText("Country not found in the bundled world map.")

    def _country_selected(self,name):
        self.country_search.setText(name)
        self.status_label.setText(f"Map selection: {name}. Event locations may be approximate.")

    def _apply_pending_economic_country(self):
        """Resolve the last explicit map-country request against current rows."""
        name=self._pending_economic_country
        if name is None:
            return
        self._pending_economic_country=None
        from .crisis_overlay import normalize_country
        target=normalize_country(name)
        for index in range(1,self.economy_country.count()):
            if normalize_country(self.economy_country.itemText(index))==target:
                # A country can have observations for a different indicator
                # than the one last selected. Use already-warmed rows to
                # choose a real available series, without a SQLite read.
                country_name=self.economy_country.itemText(index)
                by_indicator=getattr(self,"_observations_by_indicator",{})
                def has_country(rows):
                    return any(str(o.get("country_name") or o.get("country") or "")==country_name
                               for o in rows)
                current=self.indicator_combo.currentData()
                if not has_country(by_indicator.get(current,())):
                    for choice in range(self.indicator_combo.count()):
                        if has_country(by_indicator.get(self.indicator_combo.itemData(choice),())):
                            blocked=self.indicator_combo.blockSignals(True)
                            self.indicator_combo.setCurrentIndex(choice)
                            self.indicator_combo.blockSignals(blocked)
                            break
                blocked=self.economy_country.blockSignals(True)
                self.economy_country.setCurrentIndex(index)
                self.economy_country.blockSignals(blocked)
                self._populate_economic_selection()
                self.status_label.setText(
                    f"Economy: dated sourced observations for {name}; not a verified crisis."
                )
                return
        # A missing source country still needs the rebuilt model to match the
        # latest real controls, not the chart left from a prior revision.
        self._populate_economic_selection()
        self.status_label.setText(
            f"Economy data for {name} is no longer in the local archive."
        )

    def _open_economic_country(self,name):
        """Country map clicks must not read SQLite or use stale prewarm rows.

        After a collector revision the Economy workspace is dirty while
        visible map observations are already refreshed. A map click chooses
        the last requested country and defers the heavyweight table/chart
        reconstruction to the existing navigation-idle warm cycle. The
        pending choice is resolved only against freshly populated controls.
        """
        self._pending_economic_country=str(name)
        self.open_page(2)
        if 2 in self._dirty_pages:
            self.status_label.setText(
                f"Preparing dated sourced Economy observations for {name}..."
            )
            self._schedule_workspace_warm()
        else:
            self._apply_pending_economic_country()

    def _search_full_archive(self, phrase):
        """Search all local headlines with one refresh and no invented geography."""
        phrase=str(phrase or "").strip()[:200]
        if not phrase:
            return
        self.open_page(0)
        # Change the full-archive search dimensions atomically: the normal
        # search timer and each combo callback would otherwise rebuild map
        # evidence several times on one country-dialog click.
        self.search_timer.stop()
        for control, value in (
            (self.search, phrase),
            (self.category, 0),
            (self.region, 0),
            (self.time_range, 3),
            (self.history_slider, 1000),
        ):
            blocked=control.blockSignals(True)
            try:
                if control is self.search:
                    control.setText(value)
                else:
                    control.setCurrentIndex(value) if hasattr(control,"setCurrentIndex") else control.setValue(value)
            finally:
                control.blockSignals(blocked)
        self.refresh_data()
        self.status_label.setText(
            f"Full archive search: {phrase}. Results have no implied country coordinates."
        )

    def _reset_map(self):
        self.world_map.reset_view();self.country_search.clear()

    def _density_changed(self,checked):
        self.world_map.density=checked;self.world_map.update()

    def _toggle_crisis_overlay(self,checked):
        self.world_map.set_crisis_overlay_enabled(checked)
        for control in self.crisis_checks.values():control.setEnabled(checked)

    def _toggle_crisis_kind(self,kind,checked):
        self.world_map.set_crisis_layer(kind,checked)

    def _toggle_layer_panel(self, checked):
        self.map_overlay.setVisible(checked)

    def _sync_map_controls(self):
        self.crisis_master_check.blockSignals(True);self.crisis_master_check.setChecked(self.world_map.crisis_overlay_enabled);self.crisis_master_check.blockSignals(False)
        for kind,control in self.crisis_checks.items():
            control.blockSignals(True);control.setChecked(bool(self.world_map.crisis_layers.get(kind,True)));control.setEnabled(self.world_map.crisis_overlay_enabled);control.blockSignals(False)
        categories=sorted({str(x.get("category")) for x in self.controller.catalog+self._events if x.get("category")})
        for category in categories:
            if category not in self.layer_checks:
                check=QCheckBox(category);check.setStyleSheet("font-size:10px;")
                check.setAccessibleName("Map layer: "+category)
                check.toggled.connect(lambda checked,c=category:self._toggle_layer(c,checked,list(self.layer_checks)))
                self.layer_checks[category]=check;self.layers_layout.addWidget(check)
        for category,check in self.layer_checks.items():
            check.blockSignals(True);check.setChecked(self.world_map.categories is None or category in self.world_map.categories);check.blockSignals(False)
        for index,control in enumerate(self.map_period_buttons):control.setChecked(index==self.time_range.currentIndex())

    def _layer_menu(self):
        menu=QMenu(self)
        categories=sorted({str(e.get("category")) for e in self._events if e.get("category")})
        all_action=menu.addAction("Show all categories");all_action.triggered.connect(self._all_layers)
        menu.addSeparator()
        for category in categories:
            a=menu.addAction(category);a.setCheckable(True);a.setChecked(self.world_map.categories is None or category in self.world_map.categories)
            a.triggered.connect(lambda checked,c=category:self._toggle_layer(c,checked,categories))
        menu.exec(self.layer_button.mapToGlobal(QPoint(0,self.layer_button.height())))

    def _all_layers(self):
        self.world_map.categories=None;self.world_map.update();self._sync_map_controls()

    def _toggle_layer(self,category,checked,all_categories):
        if self.world_map.categories is None:self.world_map.categories=set(all_categories)
        if checked:self.world_map.categories.add(category)
        else:self.world_map.categories.discard(category)
        self.world_map.update();self._sync_map_controls()

    def _history_changed(self,value):
        if value==1000:self.history_label.setText("Latest")
        self.refresh_data()

    def _toggle_playback(self):
        if self.play_timer.isActive():self.play_timer.stop();self.history_play.setText("▶")
        else:
            if self.history_slider.value()==1000:self.history_slider.setValue(0)
            self.play_timer.start();self.history_play.setText("Ⅱ")

    def _play_step(self):
        value=min(1000,self.history_slider.value()+15);self.history_slider.setValue(value)
        if value==1000:self.play_timer.stop();self.history_play.setText("▶")

    def save_layout(self):
        self.controller.set_setting("window_geometry",bytes(self.saveGeometry().toBase64()).decode("ascii"))
        self.controller.set_setting("vertical_split",self.vertical_split.sizes());self.controller.set_setting("lower_split",self.lower_split.sizes());self.controller.set_setting("map_view",self.world_map.view_state())
        self.controller.set_setting("intel_split",self.intel_stack.sizes())
        self.controller.set_setting("map_layers_visible",self.layer_button.isChecked())

    def _restore_layout(self):
        geometry=self.controller.get_setting("window_geometry","")
        restored=False
        if geometry:
            try:restored=bool(self.restoreGeometry(QByteArray.fromBase64(str(geometry).encode("ascii"))))
            except (ValueError,TypeError):pass
        if restored:self._ensure_window_on_screen()
        for splitter,key in ((self.vertical_split,"vertical_split"),(self.lower_split,"lower_split"),(self.intel_stack,"intel_split")):
            sizes=self.controller.get_setting(key,[])
            if isinstance(sizes,list) and len(sizes)==splitter.count() and all(isinstance(x,int) and x>=0 for x in sizes):splitter.setSizes(sizes)
        self.world_map.restore_view(self.controller.get_setting("map_view",{}));self.density_check.setChecked(self.world_map.density)
        self.layer_button.setChecked(self.controller.get_setting("map_layers_visible",True))
        self.map_overlay.setVisible(self.layer_button.isChecked())
        self._sync_map_controls()

    def _ensure_window_on_screen(self):
        screens=[screen.availableGeometry() for screen in QApplication.screens()]
        if not screens or geometry_has_useful_screen_overlap(self.frameGeometry(),screens):
            return False
        primary=QApplication.primaryScreen()
        available=primary.availableGeometry() if primary else screens[0]
        target=recovered_window_rect(self.frameGeometry(),available,self.minimumSize())
        self.setGeometry(target)
        return True

    def _reset_layout(self):
        self.vertical_split.setSizes([470,350]);self.lower_split.setSizes([560,560,280]);self.intel_stack.setSizes([220,70,55]);self.layer_button.setChecked(True);self.map_overlay.show();self.world_map.reset_view();self._all_layers();self.save_layout();self.settings_result.setText("Default layout restored.")

    def set_close_handler(self,callback):
        self._close_handler=callback

    def closeEvent(self,event):
        if self._force_close or getattr(self.controller,"_closed",False):
            event.accept();return
        if self._close_handler and not self._force_close:
            # Close-to-tray policy and one deferred settings save belong to
            # bootstrap; avoid blocking the X click with duplicate SQLite IO.
            event.ignore();self._close_handler()
        else:
            self.save_layout()
            if hasattr(self.media,"shutdown"):self.media.shutdown()
            event.accept()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,"titlebar"):self.titlebar.tagline.setVisible(self.width()>=1200)
        if hasattr(self,"last_label"):self.last_label.setVisible(self.width()>=1100)

    def showEvent(self,event):
        super().showEvent(event)
        if sys.platform=="win32" and not getattr(self,"_native_configured",False):
            self._configure_windows_frame()

    def _configure_windows_frame(self):
        """Retain native window management while drawing our own title bar."""
        try:
            import ctypes
            from ctypes import wintypes
            user32=ctypes.windll.user32
            get_long=user32.GetWindowLongPtrW;get_long.argtypes=[wintypes.HWND,ctypes.c_int];get_long.restype=ctypes.c_ssize_t
            set_long=user32.SetWindowLongPtrW;set_long.argtypes=[wintypes.HWND,ctypes.c_int,ctypes.c_ssize_t];set_long.restype=ctypes.c_ssize_t
            hwnd=int(self.winId());style=get_long(hwnd,-16)
            set_long(hwnd,-16,style | 0x00040000 | 0x00020000 | 0x00010000 | 0x00080000)
            user32.SetWindowPos.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_uint]
            user32.SetWindowPos.restype=wintypes.BOOL
            user32.SetWindowPos(hwnd,None,0,0,0,0,0x0020|0x0001|0x0002|0x0004)
            self._native_configured=True
        except (AttributeError,OSError):
            self._native_configured=False

    def nativeEvent(self,event_type,message):
        if sys.platform!="win32":return False,0
        try:
            import ctypes
            from ctypes import wintypes
            msg=wintypes.MSG.from_address(int(message))
            if msg.message==0x0083 and msg.wParam: # WM_NCCALCSIZE
                return True,0
            if msg.message==0x0024: # WM_GETMINMAXINFO: keep taskbar work area.
                class MinMaxInfo(ctypes.Structure):
                    _fields_=[("reserved",wintypes.POINT),("max_size",wintypes.POINT),("max_position",wintypes.POINT),("min_track",wintypes.POINT),("max_track",wintypes.POINT)]
                class MonitorInfo(ctypes.Structure):
                    _fields_=[("size",wintypes.DWORD),("monitor",wintypes.RECT),("work",wintypes.RECT),("flags",wintypes.DWORD)]
                user32=ctypes.windll.user32
                user32.MonitorFromWindow.argtypes=[wintypes.HWND,wintypes.DWORD];user32.MonitorFromWindow.restype=wintypes.HANDLE
                monitor=user32.MonitorFromWindow(msg.hwnd,2)
                info=MonitorInfo();info.size=ctypes.sizeof(info)
                user32.GetMonitorInfoW.argtypes=[wintypes.HANDLE,ctypes.POINTER(MonitorInfo)];user32.GetMonitorInfoW.restype=wintypes.BOOL
                if user32.GetMonitorInfoW(monitor,ctypes.byref(info)):
                    mmi=ctypes.cast(msg.lParam,ctypes.POINTER(MinMaxInfo)).contents
                    mmi.max_position.x=info.work.left-info.monitor.left;mmi.max_position.y=info.work.top-info.monitor.top
                    mmi.max_size.x=info.work.right-info.work.left;mmi.max_size.y=info.work.bottom-info.work.top
                    mmi.min_track.x=int(self.minimumWidth()*self.devicePixelRatioF());mmi.min_track.y=int(self.minimumHeight()*self.devicePixelRatioF())
                    return True,0
            if msg.message==0x0084: # WM_NCHITTEST
                # Message coordinates are physical pixels; map Qt caption button
                # geometry through devicePixelRatio to support mixed DPI screens.
                rect=wintypes.RECT();ctypes.windll.user32.GetWindowRect(msg.hwnd,ctypes.byref(rect))
                x=ctypes.c_short(msg.lParam&0xffff).value-rect.left;y=ctypes.c_short((msg.lParam>>16)&0xffff).value-rect.top
                ratio=self.devicePixelRatioF();qx,qy=x/ratio,y/ratio
                if not self.isMaximized():
                    margin=7;left=qx<margin;right=qx>self.width()-margin;top=qy<margin;bottom=qy>self.height()-margin
                    if top and left:return True,13
                    if top and right:return True,14
                    if bottom and left:return True,16
                    if bottom and right:return True,17
                    if left:return True,10
                    if right:return True,11
                    if top:return True,12
                    if bottom:return True,15
                max_button=self.titlebar.maximize_button;position=max_button.mapTo(self,QPoint(0,0))
                if QRectF(position.x(),position.y(),max_button.width(),max_button.height()).contains(QPointF(qx,qy)):return True,9 # HTMAXBUTTON / Windows 11 Snap menu
            if msg.message==0x00A1 and msg.wParam==9:return True,0 # WM_NCLBUTTONDOWN
            if msg.message==0x00A2 and msg.wParam==9: # WM_NCLBUTTONUP
                self.titlebar.toggle_maximized();return True,0
        except (ValueError,TypeError,AttributeError,OSError):pass
        return super().nativeEvent(event_type,message)

