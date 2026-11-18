"""Explicit coded-observation map layer and plain-text local record drill-down."""
from __future__ import annotations
from datetime import datetime, timezone
import sqlite3
import threading
import time
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QPen, QBrush
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QCheckBox,QLabel,QPushButton,QDialog,QComboBox,QListWidget,QListWidgetItem
from .gdelt_map_data import read_archive,empty
from .crisis_overlay import normalize_country


class GdeltMapPanel(QWidget):
    _idle_ready=Signal(object)

    def __init__(self,controller,world_map,parent=None):
        super().__init__(parent)
        self.controller=controller
        self.world_map=world_map
        self.filters={}
        self.snapshot=empty()
        self.dialog=None
        self._dialog_records=[]
        self._error=''
        # Splash-owned initial read stays synchronous. Post-READY timer,
        # status and evidence refreshes must never query SQLite on Qt.
        self._idle_inflight=False
        self._idle_pending=False
        self._idle_epoch=0
        self._idle_scope=None
        self._idle_last_key=None
        self._idle_last_at=0.0
        self._idle_ready.connect(self._apply_idle_result)
        layout=QHBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.enabled=QCheckBox('GDELT coded layer')
        self.enabled.setChecked(controller.get_setting('gdelt_map_visible',True) is True)
        self.enabled.setToolTip('Dotted country borders show retained automated observations, not verified crises or exact incident positions. No network request.')
        self.enabled.toggled.connect(self._toggle)
        layout.addWidget(self.enabled)
        self.status=QLabel();self.status.setWordWrap(True);self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status,1)
        self.details=QPushButton('GDELT records');self.details.clicked.connect(self.show_records)
        layout.addWidget(self.details)
        world_map.gdelt_layer=self
        self.timer=QTimer(self);self.timer.setInterval(60000);self.timer.timeout.connect(self._timed_refresh);self.timer.start()
        controller.gdelt_status_changed.connect(self._timed_refresh)
        # Pan/zoom is a map transform, not a 20,000-row SQLite query.
        # The old view_changed -> refresh could consume 250 ms on Qt.

    @property
    def mapped_count(self):
        return len(self.snapshot['countries']) if self.enabled.isChecked() else 0

    def _toggle(self,value):
        try:
            self.controller.set_setting('gdelt_map_visible',bool(value))
            self._error=''
        except (sqlite3.Error,OSError,ValueError,RuntimeError):
            self._error='Display preference could not be saved.'
            blocked=self.enabled.blockSignals(True)
            try:self.enabled.setChecked(not value)
            finally:self.enabled.blockSignals(blocked)
        self.refresh()

    def _inactive_snapshot(self):
        """Filtering must hide coded observations immediately, even mid-read."""
        if not self.enabled.isChecked():
            return empty('off','GDELT layer off; cached data is unchanged.')
        if self.controller.demo:
            return empty('demo','GDELT live-data layer is disabled in synthetic mode.')
        if (self.filters.get('before')
                or any(self.filters.get(k) for k in ('query','category','region'))
                or self.world_map.categories is not None):
            return empty('filtered','GDELT layer hidden during news-only filters or historical replay; clear filters to inspect coded data.')
        return None

    def _scope_key(self):
        # Freeze pure Python inputs on Qt; no connection or store lock.
        return (self.filters.get('since'),tuple(self.world_map.country_names))

    def _present(self):
        self.status.setText(self.snapshot['message']+(' '+self._error if self._error else ''))
        self.details.setEnabled(bool(self.snapshot['records']))
        self.world_map.update()

    @Slot()
    def _timed_refresh(self):
        self.refresh_idle(force=True)

    def refresh_idle(self,filters=None,*,force=False):
        """Schedule a bounded read-only projection without blocking idle Qt.

        Coalesce repeated status/timer pulses to one worker and one pending
        refresh. Never show a result from an obsolete filter or user action.
        """
        if getattr(self.controller,'_closed',False):
            self.timer.stop()
            return
        if isinstance(filters,dict):
            self.filters=dict(filters)
        inactive=self._inactive_snapshot()
        if inactive is not None:
            self._idle_epoch+=1
            self._idle_pending=False
            self._idle_last_key=None
            self.snapshot=inactive
            self._present()
            return
        scope=self._scope_key()
        if self._idle_inflight:
            if scope!=self._idle_scope or force:
                self._idle_epoch+=1
                self._idle_pending=True
                if scope!=self._idle_scope:
                    self.snapshot=empty('loading','Updating the GDELT coded layer for this filter; previous scope hidden.')
                    self._present()
            return
        if (not force and scope==self._idle_last_key
                and time.monotonic()-self._idle_last_at<60):
            return
        self._idle_epoch+=1
        token=self._idle_epoch
        self._idle_scope=scope
        self._idle_inflight=True
        if scope!=self._idle_last_key:
            self.snapshot=empty('loading','Updating the GDELT coded layer; no unverified observations displayed yet.')
            self._present()
        path=self.controller.store.path
        signal=self._idle_ready

        def collect():
            try:
                rows=read_archive(path,scope[1],since=scope[0])
            except Exception:
                rows=empty('unavailable','GDELT display worker failed; no old layer is shown.')
            try:
                signal.emit((token,scope,rows))
            except RuntimeError:
                pass

        threading.Thread(target=collect,name='pulse-idle-gdelt',daemon=True).start()

    @Slot(object)
    def _apply_idle_result(self,payload):
        if getattr(self.controller,'_closed',False):
            self._idle_inflight=False
            return
        token,scope,rows=payload
        if not self._idle_inflight or scope!=self._idle_scope:
            return
        self._idle_inflight=False
        pending=self._idle_pending
        self._idle_pending=False
        if (pending or token!=self._idle_epoch
                or self._inactive_snapshot() is not None
                or scope!=self._scope_key()):
            if self._inactive_snapshot() is None:
                self.refresh_idle(force=True)
            return
        self.snapshot=rows
        self._idle_last_key=scope
        self._idle_last_at=time.monotonic()
        self._present()

    def refresh(self,filters=None):
        """Explicit action and splash first paint retain current-source reads."""
        if getattr(self.controller,'_closed',False):
            self.timer.stop();return
        if isinstance(filters,dict):self.filters=dict(filters)
        self._idle_epoch+=1
        self._idle_pending=False
        inactive=self._inactive_snapshot()
        if inactive is not None:
            self.snapshot=inactive
            self._idle_last_key=None
        else:
            scope=self._scope_key()
            self.snapshot=read_archive(self.controller.store.path,scope[1],since=scope[0])
            self._idle_last_key=scope
            self._idle_last_at=time.monotonic()
        self._present()

    def paint(self,painter,transform,countries):
        if not self.mapped_count:return
        painter.save()
        for country in countries:
            key=normalize_country(country['name'])
            group=self.snapshot['countries'].get(key)
            if not group:continue
            path=transform.map(country['path'])
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor('#58c2cd'),1.8,Qt.PenStyle.DotLine))
            painter.drawPath(path)

            # Secondary coded fallback: only when the stricter source-derived
            # crisis layer has no accepted activity for that kind. Lower-alpha
            # hatching makes the distinction visible instead of pretending
            # GDELT coding is independent verification.
            accepted=self.world_map.country_activity_for(country['name'])
            if int(group.get('material_conflict',0)) and not int(accepted.get('conflict',0) or 0):
                shade=QColor('#d84a52');shade.setAlpha(80)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(shade,Qt.BrushStyle.BDiagPattern))
                painter.drawPath(path)
            if int(group.get('protest',0)) and not int(accepted.get('unrest',0) or 0):
                shade=QColor('#e3bd4d');shade.setAlpha(80)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(shade,Qt.BrushStyle.FDiagPattern))
                painter.drawPath(path)
        painter.restore()

    def country_text(self,name):
        group=self.snapshot['countries'].get(normalize_country(name)) if self.enabled.isChecked() else None
        if not group:return ''
        detail=[]
        if group.get('material_conflict'):detail.append(f"{group['material_conflict']} material-conflict code(s)")
        if group.get('protest'):detail.append(f"{group['protest']} protest code(s)")
        suffix=(" · "+", ".join(detail)) if detail else ""
        return (f"GDELT: {group['count']} retained coded observation(s){suffix}; "
                "automated coding, not verified crises or independent corroboration. Use GDELT records for source links.")

    def show_records(self):
        if not self.snapshot['records']:return
        if self.dialog is not None:
            old=self.dialog
            self.dialog=None
            old.close();old.deleteLater()
        # A frozen inspection view avoids changing the selected link underneath
        # the user when the collection timer refreshes the map.
        self._dialog_records=[dict(r) for r in self.snapshot['records']]
        dialog_records=self._dialog_records
        sampled=self.snapshot['truncated']
        dialog=QDialog(self);self.dialog=dialog
        dialog.setWindowTitle('Retained GDELT observations — not verified news')
        dialog.resize(780,510)
        layout=QVBoxLayout(dialog)
        note=QLabel('Automated codes are not independent reports or confirmed incidents. Event dates have day precision. Links open only on your explicit click; this app does not fetch the articles.')
        note.setTextFormat(Qt.TextFormat.PlainText);note.setWordWrap(True);layout.addWidget(note)
        country=QComboBox();country.addItem('All retained observations','')
        for name in sorted({r['country'] for r in self._dialog_records if r['country']}):country.addItem(name,name)
        country.addItem('Unlocated / unsupported country','__unlocated__')
        selected=country.findData(self.world_map.selected_country)
        if selected>=0:country.setCurrentIndex(selected)
        layout.addWidget(country)
        listing=QListWidget();listing.setAccessibleName('GDELT coded records and original attribution');layout.addWidget(listing,1)
        count=QLabel();count.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(count)
        original=QPushButton('Open selected source article');original.setEnabled(False);layout.addWidget(original)
        def fill():
            listing.clear();wanted=country.currentData()
            records=[r for r in dialog_records if not wanted or (not r['country'] if wanted=='__unlocated__' else r['country']==wanted)]
            for r in records[:100]:
                day=r['event_day'];added=r['date_added'];batch=r['batch']
                text=(f"{r['country'] or 'Unlocated'} · FIPS {r['fips']} · CAMEO {r['event_code']} · record {r['id']}\n"
                    f"Event date {day[:4]}-{day[4:6]}-{day[6:]} · GDELT added {added} UTC · batch {batch} UTC\n"
                    f"{r['location']}\n{r['url']}")
                item=QListWidgetItem(text);item.setData(Qt.ItemDataRole.UserRole,r['url']);listing.addItem(item)
            count.setText(f'{min(100,len(records))} of {len(records)} retained display records shown. '+('Source sample was capped.' if sampled else ''))
            original.setEnabled(False)
        def open_original():
            item=listing.currentItem()
            if item is not None:self.controller.open_url(item.data(Qt.ItemDataRole.UserRole))
        country.currentIndexChanged.connect(fill)
        listing.currentItemChanged.connect(lambda current,previous:original.setEnabled(current is not None))
        original.clicked.connect(open_original)
        self.record_list=listing;self.record_country=country;self.open_original=original
        fill();dialog.show()
