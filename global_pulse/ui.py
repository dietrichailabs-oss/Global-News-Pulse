"""Global Pulse native desktop workstation.

All network and analysis work is delegated to the controller. UI-originated text
is rendered as plain text or escaped HTML. No source HTML is executed here.
"""
from __future__ import annotations

import html
import json
import math
import sys
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt, Signal, QByteArray, QTimer, QPoint, QPointF, QRect, QRectF, QSize
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QKeySequence, QShortcut, QTextDocument
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton, QToolButton,
    QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QLineEdit, QComboBox,
    QSplitter, QStackedWidget, QListWidget, QListWidgetItem, QTextBrowser,
    QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox, QSpinBox, QTimeEdit,
    QSlider, QGroupBox, QScrollArea, QFileDialog, QMessageBox, QCompleter,
    QAbstractItemView, QStyledItemDelegate, QStyle, QSizeGrip, QMenu, QInputDialog, QSizePolicy,
)

from .map_widget import WorldMap
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


class EconomicChart(QWidget):
    """Small native chart with actual values; missing observations stay missing."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(230)
        self.setAccessibleName("Economic observation history")
        self.observations = []

    def set_observations(self, data):
        self.observations = [d for d in data if isinstance(d.get("value"), (int,float)) and not isinstance(d.get("value"),bool) and math.isfinite(d["value"])]
        self.update()

    def paintEvent(self, event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(),QColor("#151619"))
        chart=QRectF(65,24,max(1,self.width()-90),max(1,self.height()-67))
        if not self.observations:
            p.setPen(QColor("#8995ac")); p.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,"No numeric observations for this selection."); return
        groups={}
        for d in self.observations:
            country=str(d.get("country_name") or d.get("country") or "Global")
            date=str(d.get("date") or d.get("observation_date") or d.get("period") or "")
            if date: groups.setdefault(country,[]).append((date,float(d["value"])))
        dates=sorted({date for values in groups.values() for date,_ in values})
        if not dates:return
        vals=[v for values in groups.values() for _,v in values]
        lo,hi=min(vals),max(vals)
        pad=(hi-lo)*.1 if hi!=lo else max(1,abs(hi)*.1)
        lo-=pad;hi+=pad
        p.setFont(QFont("Segoe UI",8))
        for i in range(5):
            y=chart.bottom()-chart.height()*i/4
            p.setPen(QPen(QColor("#283144"),1));p.drawLine(QPointF(chart.left(),y),QPointF(chart.right(),y))
            p.setPen(QColor("#9aa8bf"));p.drawText(QRectF(0,y-8,55,16),Qt.AlignmentFlag.AlignRight,f"{lo+(hi-lo)*i/4:.2g}")
        colors=["#b59aea","#6ebccb","#e1bc74","#df8798","#87c7a0","#8da5ed"]
        for n,(name,values) in enumerate(sorted(groups.items())):
            p.setPen(QPen(QColor(colors[n%len(colors)]),2))
            points=[]
            for date,value in sorted(values):
                x=chart.left()+chart.width()*dates.index(date)/max(1,len(dates)-1)
                y=chart.bottom()-chart.height()*(value-lo)/(hi-lo)
                points.append(QPointF(x,y))
            for a,b in zip(points,points[1:]):p.drawLine(a,b)
            p.setBrush(QColor(colors[n%len(colors)]))
            for point in points:p.drawEllipse(point,3,3)
            p.drawText(chart.left()+n*130,self.height()-9,name[:20])
        p.setPen(QColor("#9aa8bf"))
        for i in sorted(set([0,len(dates)//2,len(dates)-1])):
            x=chart.left()+chart.width()*i/max(1,len(dates)-1)
            p.drawText(QRectF(x-40,chart.bottom()+8,80,17),Qt.AlignmentFlag.AlignCenter,dates[i])


class MainWindow(SituationActions, QMainWindow):
    """Controller-bound desktop. Native close/tray policy belongs to bootstrap."""
    def __init__(self, controller):
        super().__init__()
        self.controller=controller
        self._close_handler=None
        self._selected_id=""
        self._events=[]
        self._historical=False
        self._history_at=None
        self._refreshing=False
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
        self.search.textChanged.connect(lambda:self.search_timer.start())
        for combo in (self.category,self.region,self.time_range):combo.currentIndexChanged.connect(self.refresh_data)
        controller.data_changed.connect(self.refresh_data)
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
        w=label("◌ Unverified   ◔ Developing   ○ Corroborated   □ Official source","Muted");w.setToolTip("Importance uses color. Evidence uses ring patterns. Official means an attributed statement or measurement, not blanket confirmation of underlying claims.");legend.addWidget(w)
        self.map_panel.layout.addLayout(legend)
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
        self.save_button=button("☆ Star",self._toggle_selected_situation,"Star the selected event in Situations",checkable=True);intel.heading.addWidget(self.save_button)
        self.save_button.setObjectName("situation_star")
        self.intel_browser=QTextBrowser();self.intel_browser.setOpenExternalLinks(False);self.intel_browser.anchorClicked.connect(lambda u:self.controller.open_url(u.toString()));self.intel_browser.setAccessibleName("Selected event evidence brief")
        self.intel_stack=QSplitter(Qt.Orientation.Vertical);self.intel_stack.setHandleWidth(3)
        self.intel_stack.addWidget(self.intel_browser)
        self.evidence_status=Panel("EVIDENCE STATUS")
        self.evidence_status_text=QTextBrowser();self.evidence_status_text.setPlainText("No event selected");self.evidence_status_text.setStyleSheet("font-size:10px;")
        self.evidence_status.layout.addWidget(self.evidence_status_text)
        self.intel_stack.addWidget(self.evidence_status)
        self.change_status=Panel("SITUATION UPDATE")
        self.change_status_text=QTextBrowser();self.change_status_text.setPlainText("Select a source-linked situation.");self.change_status_text.setStyleSheet("font-size:10px;")
        self.change_status.layout.addWidget(self.change_status_text)
        self.intel_stack.addWidget(self.change_status)
        # Every expanded card must have real text space. A splitter alone can
        # shrink the nested panel headers until its text viewport is zero.
        # Keep a readable minimum and scroll the whole stack on small windows;
        # do not grow the main window or distort the reference's 40/40/20 split.
        for browser in (self.intel_browser,self.evidence_status_text,self.change_status_text):
            browser.ensurePolished()
            browser.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
            browser.setMinimumHeight(3 * browser.fontMetrics().lineSpacing() + 24)
        self.intel_stack.setChildrenCollapsible(False)
        self.intel_stack.setSizes([220,100,100])
        self.intel_scroll=QScrollArea()
        self.intel_scroll.setAccessibleName("Scrollable intelligence brief and status cards")
        self.intel_scroll.setWidgetResizable(True)
        self.intel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.intel_scroll.setMinimumSize(0,0)
        self.intel_scroll.setWidget(self.intel_stack)
        intel.layout.addWidget(self.intel_scroll,1)
        actionrow=QHBoxLayout()
        self.original_button=button("Source ↗",self._open_original);self.translate_button=button("Translate",self._translate_selected)
        actionrow.addWidget(self.original_button);actionrow.addWidget(self.translate_button);intel.layout.addLayout(actionrow)
        self.lower_split.addWidget(intel)
        self.lower_split.setSizes([560,560,280]);self.lower_split.setCollapsible(0,False);self.lower_split.setCollapsible(1,True);self.lower_split.setCollapsible(2,True)
        self.vertical_split.addWidget(self.lower_split);self.vertical_split.setSizes([470,350]);self.vertical_split.setCollapsible(0,False);self.vertical_split.setCollapsible(1,False)
        layout.addWidget(self.vertical_split);self.pages.addWidget(page)
        self.world_map.event_selected.connect(self.navigate_event)
        self.world_map.country_selected.connect(self._country_selected)

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
        self.economy_table=QTableWidget(0,9);self.economy_table.setHorizontalHeaderLabels(["Country","Observation date","Value","Prior value","Revisions","Unit","Release / update","Retrieved","Source ↗"])
        self._configure_table(self.economy_table);panel.layout.addWidget(self.economy_table,1)
        self.economy_table.cellDoubleClicked.connect(self._open_economic_source)
        self.indicator_combo.currentIndexChanged.connect(self._populate_economic_selection);self.economy_country.currentIndexChanged.connect(self._populate_economic_selection)
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
        self.setting_notify=QCheckBox("Enable native notifications");self.setting_notify.setChecked(bool(self.controller.get_setting("notifications_enabled",True)));form.addRow(self.setting_notify)
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
        sg.addWidget(label("Enable approved available sources for collection. Muting suppresses their alerts; their reports remain searchable.","Muted",True))
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

    def open_page(self,index):
        self.pages.setCurrentIndex(index)
        for i,b in enumerate(self.nav_buttons.values()):b.setChecked(i==index)
        if index==1:self._populate_situations()
        elif index==2:self._populate_economy()
        elif index==3:self._populate_sources()
        elif index==4:self._populate_alerts()
        elif index==5:self._generate_brief()

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

    def refresh_data(self,*args):
        if self._refreshing:return
        self._refreshing=True
        try:
            filters=self.events_filters()
            self._events=self.controller.events(**filters)
            # A filter or historical-time change can remove the previously
            # selected event from the visible feed without deleting it from
            # the Store. Never leave a hidden event bound to the Brief/Star.
            visible_ids={str(event.get("id","")) for event in self._events}
            if self._selected_id and self._selected_id not in visible_ids:
                self._selected_id=""
            self._populate_filter_options()
            self._sync_map_controls()
            map_filters={**filters,"limit":5000,"map_view":True,"keep_significant":not bool(self._history_at)}
            country_evidence=self.controller.events(**dict(map_filters,map_evidence=True))
            # Economic observations have their own dated country-level layer.
            # Hide it during search/region/history replay because observations
            # do not share those event-filter semantics.
            show_observations = (not self._history_at and not filters.get("query")
                                 and not filters.get("region")
                                 and filters.get("category") in {"", "Economy"})
            observations=self.controller.store.list_observations() if show_observations else []
            self.world_map.set_events(
                self.controller.events(**map_filters),
                country_events=country_evidence,
                observations=observations,
            )
            if self.gdelt_panel is not None:self.gdelt_panel.refresh(filters)
            self._populate_feed()
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
            elif page==2:self._populate_economy()
            elif page==3:self._populate_sources()
            elif page==4:self._populate_alerts()
        except Exception as exc:
            self.status_label.setText(f"Could not update view: {type(exc).__name__}: {str(exc)[:160]}")
        finally:self._refreshing=False

    def _populate_filter_options(self):
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
        if not hasattr(self,"feed_list"):return
        if hasattr(self,"english_headlines"):
            was_blocked=self.english_headlines.blockSignals(True)
            self.english_headlines.setChecked(self.controller.get_setting("english_headlines",True) is True)
            self.english_headlines.blockSignals(was_blocked)
        events=list(self._events)
        saved_ids=self.controller.store.saved_situation_ids()
        if self.sort_combo.currentIndex()==1:
            order={"critical":4,"high":3,"moderate":2,"informational":1,"unassessed":0};events.sort(key=lambda e:(order.get(e.get("severity"),0),str(e.get("updated_at",""))),reverse=True)
        elif self.sort_combo.currentIndex()==2:events.sort(key=lambda e:int(e.get("report_count",0)),reverse=True)
        self.feed_list.blockSignals(True);self.feed_list.clear()
        if not self._selected_id and events:self._selected_id=str(events[0].get("id",""))
        selected_item=None
        for e in events:
            e=dict(e,_situation_starred=str(e.get("id","")) in saved_ids)
            view=self.controller.headline_view(e) if hasattr(self.controller,"headline_view") else {"title":str(e.get("title","Untitled event")),"original":str(e.get("title","")),"label":"Original headline"}
            e=dict(e,_display_title=view["title"],_translation_label=view["label"])
            item=QListWidgetItem(view["title"]);item.setData(Qt.ItemDataRole.UserRole,e);item.setToolTip("<div style='white-space:pre-wrap'>"+esc(view["label"]+"\nOriginal: "+view["original"]+"\n"+str(e.get("recap","")))+"</div>");self.feed_list.addItem(item)
            if str(e.get("id"))==self._selected_id:selected_item=item
        if selected_item:self.feed_list.setCurrentItem(selected_item)
        self.feed_list.blockSignals(False)
        self.feed_empty.setVisible(not events);self.feed_list.setVisible(bool(events))

    def _refresh_translated_headlines(self):
        # Presentation only: no collection, map reload, or media retuning.
        feed_scroll=self.feed_list.verticalScrollBar().value()
        brief_scroll=self.intel_browser.verticalScrollBar().value()
        self._populate_feed()
        if self._selected_id:
            event=self._selected_event()
            if event:self._render_event(event,update_media=False)
        self.feed_list.verticalScrollBar().setValue(feed_scroll)
        self.intel_browser.verticalScrollBar().setValue(brief_scroll)

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
            e=item.data(Qt.ItemDataRole.UserRole);self._selected_id=str(e.get("id",""));self.world_map.select_event(self._selected_id);full=self._selected_event() or e;self._render_event(full)
        else:
            # Clearing the highlighted feed row must clear its Brief/Star
            # target too; a hidden archived event is not a user selection.
            self._selected_id=""
            self._render_empty_brief()

    def _selected_event(self):
        if self._history_at:
            return self.controller.store.get_event(self._selected_id,at=self._history_at)
        return self.controller.event(self._selected_id)

    def navigate_event(self,event_id):
        event=self.controller.event(event_id)
        if not event:
            self.status_label.setText("This event is no longer in the local archive.");return
        self._selected_id=str(event_id)
        self.open_page(0)
        if self.history_slider.value()!=1000:self.history_slider.setValue(1000)
        if not any(str(e.get("id"))==self._selected_id for e in self._events):
            self.search.clear();self.category.setCurrentIndex(0);self.region.setCurrentIndex(0);self.time_range.setCurrentIndex(3);self.history_slider.setValue(1000);self.refresh_data()
        self._populate_feed();self._render_event(event);self.world_map.select_event(event_id,center=True)
        if self.isMinimized():self.showNormal()
        self.show();self.raise_();self.activateWindow()

    def _open_original(self):
        e=self._selected_event()
        if e and e.get("reports"):self.controller.open_url(e["reports"][0].get("url",""))

    def _translate_selected(self):
        e=self._selected_event()
        if e and e.get("reports"):
            report=next((r for r in e["reports"] if r.get("language","en")!="en"),e["reports"][0])
            self.status_label.setText("Translating available source text locally…")
            self.controller.translate_report(report)

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

    def _populate_economy(self):
        self._observations=self.controller.store.list_observations()
        current=self.indicator_combo.currentData();country=self.economy_country.currentData()
        self.indicator_combo.blockSignals(True);self.indicator_combo.clear();indicators={str(o.get("indicator", "")):str(o.get("indicator_name") or o.get("description") or o.get("indicator") or "Economic indicator") for o in self._observations}
        for key,value in sorted(indicators.items()):self.indicator_combo.addItem(value,key)
        self.indicator_combo.setCurrentIndex(max(0,self.indicator_combo.findData(current)));self.indicator_combo.blockSignals(False)
        self.economy_country.blockSignals(True);self.economy_country.clear();self.economy_country.addItem("All countries","")
        for c in sorted({str(o.get("country_name") or o.get("country", "")) for o in self._observations}):self.economy_country.addItem(c,c)
        self.economy_country.setCurrentIndex(max(0,self.economy_country.findData(country)));self.economy_country.blockSignals(False);self._populate_economic_selection()

    def _populate_economic_selection(self,*args):
        selected=self.indicator_combo.currentData();country=self.economy_country.currentData()
        data=[o for o in getattr(self,"_observations",[]) if str(o.get("indicator",""))==selected and (not country or str(o.get("country_name") or o.get("country"))==country)]
        self.economic_chart.set_observations(data)
        if data:
            first=data[0];credit=" · ".join(str(first.get(key,"")) for key in ("attribution","source_license") if first.get(key))
            updated=" Provider dataset updated "+str(first["dataset_updated_at"])+"; individual release date shown only when supplied." if first.get("dataset_updated_at") else ""
            self.economy_explanation.setText(str(first.get("description") or selected or "")+" · Unit: "+str(first.get("unit") or "See source definition")+". "+credit+updated+" Double-click a row to open its original source.")
        else:self.economy_explanation.setText("No economic observations have been collected for this selection.")
        data=sorted(data,key=lambda o:str(o.get("date") or o.get("observation_date") or o.get("period") or ""),reverse=True)
        self.economy_table.setRowCount(len(data))
        for i,o in enumerate(data):
            values=[o.get("country_name") or o.get("country"),o.get("date") or o.get("observation_date") or o.get("period"),o.get("value"),o.get("previous_value") if o.get("previous_value") is not None else "No recorded revision",o.get("revision_count",1),o.get("unit") or "See indicator definition",o.get("release_date") or o.get("last_updated") or "Not supplied",timestamp(o.get("retrieved_at")),o.get("source_id") or o.get("source") or o.get("url")]
            for j,value in enumerate(values):
                item=QTableWidgetItem(str(value if value is not None else "Missing"));item.setData(Qt.ItemDataRole.UserRole,o.get("url",""));self.economy_table.setItem(i,j,item)

    def _open_economic_source(self,row,column):
        item=self.economy_table.item(row,column)
        if item and item.data(Qt.ItemDataRole.UserRole):self.controller.open_url(item.data(Qt.ItemDataRole.UserRole))

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
        from .core import build_brief
        period=self.brief_period.currentText().lower();days=1 if period=="daily" else 7
        events=self.controller.events(since=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat(),limit=500)
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
        try:
            for key,value in values.items():self.controller.set_setting(key,value)
            self.settings_result.setText("Settings saved. Provider rate limits still apply; existing history stays available.")
        except Exception as exc:self.settings_result.setText(f"Settings could not be saved: {exc}")

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

    def _status_update(self,text):
        monitoring=bool(getattr(self.controller,"monitoring",False))
        self.titlebar.status.setText("MONITORING" if monitoring else "PAUSED")
        self.pause_button.setText("Pause" if monitoring else "Resume")
        self.titlebar.status.setStyleSheet("color:#7fdbb2;background:#173029;border:1px solid #284d40;border-radius:9px;padding:3px 9px;font-size:10px;" if monitoring else "color:#d3bd8f;background:#30291e;border:1px solid #514532;border-radius:9px;padding:3px 9px;font-size:10px;")
        self.last_label.setText("Last collection  "+timestamp(getattr(self.controller,"last_collection","")))
        if text:self.status_label.setText(str(text)[:250])
        if self.pages.currentIndex()==3:self._populate_sources()

    def _on_alert(self,alert):
        self.status_label.setText("New alert saved in Alerts.")
        if self.pages.currentIndex()==4:self._populate_alerts()

    def _find_country(self,*args):
        name=args[0] if args and isinstance(args[0],str) else self.country_search.text().strip()
        if not self.world_map.select_country(name):self.status_label.setText("Country not found in the bundled world map.")

    def _country_selected(self,name):
        self.country_search.setText(name)
        self.status_label.setText(f"Map selection: {name}. Event locations may be approximate.")

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
        self.save_layout()
        if self._close_handler and not self._force_close:
            event.ignore();self._close_handler()
        else:
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
