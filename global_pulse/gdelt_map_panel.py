"""Explicit coded-observation map layer and plain-text local record drill-down."""
from __future__ import annotations
from datetime import datetime, timezone
import sqlite3
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPen, QBrush
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QCheckBox,QLabel,QPushButton,QDialog,QComboBox,QListWidget,QListWidgetItem
from .gdelt_map_data import read_archive,empty
from .crisis_overlay import normalize_country


class GdeltMapPanel(QWidget):
    def __init__(self,controller,world_map,parent=None):
        super().__init__(parent)
        self.controller=controller
        self.world_map=world_map
        self.filters={}
        self.snapshot=empty()
        self.dialog=None
        self._dialog_records=[]
        self._error=''
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
        self.timer=QTimer(self);self.timer.setInterval(60000);self.timer.timeout.connect(self.refresh);self.timer.start()
        controller.gdelt_status_changed.connect(self.refresh)
        world_map.view_changed.connect(self.refresh)

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

    def refresh(self,filters=None):
        if getattr(self.controller,'_closed',False):
            self.timer.stop();return
        if isinstance(filters,dict):self.filters=dict(filters)
        if not self.enabled.isChecked():
            self.snapshot=empty('off','GDELT layer off; cached data is unchanged.')
        elif self.controller.demo:
            self.snapshot=empty('demo','GDELT live-data layer is disabled in synthetic mode.')
        elif self.filters.get('before') or any(self.filters.get(k) for k in ('query','category','region')) or self.world_map.categories is not None:
            self.snapshot=empty('filtered','GDELT layer hidden during news-only filters or historical replay; clear filters to inspect coded data.')
        else:
            self.snapshot=read_archive(self.controller.store.path,self.world_map.country_names,since=self.filters.get('since'))
        self.status.setText(self.snapshot['message']+(' '+self._error if self._error else ''))
        self.details.setEnabled(bool(self.snapshot['records']))
        self.world_map.update()

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
