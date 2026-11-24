"""Offline engineering diagnostic for the exact reviewed R20 HAM layout.
Captures Qt constraints on the same hosted Windows configuration as the
failing geometry tests. No product source modifications, network or playback.
"""
from __future__ import annotations

import json
import os
import platform
import socket
import sys
from unittest.mock import patch

from PySide6.QtCore import qVersion
from PySide6.QtWidgets import QApplication, QWidget, QLayout, QSizePolicy
from PySide6.QtNetwork import QNetworkAccessManager
from PySide6.QtGui import QDesktopServices
from global_pulse.internet_radio import RadioPanel
from global_pulse.theme import STYLE


def emit(kind, **data):
    print(kind + " " + json.dumps(data, ensure_ascii=True, sort_keys=True), flush=True)


def dims(s):
    return [s.width(), s.height()]


def rect(r):
    return [r.x(), r.y(), r.width(), r.height()]


def deny(*args, **kwargs):
    raise AssertionError("Network/browser access forbidden during layout diagnosis")


def aliases(panel):
    names={}
    for name, value in vars(panel).items():
        if isinstance(value, (QWidget,QLayout)):
            names.setdefault(id(value),[]).append(name)
    return names


def metrics(widget, names):
    policy=widget.sizePolicy()
    return {
        "aliases":names.get(id(widget),[]),
        "class":widget.metaObject().className(),
        "object":widget.objectName(),
        "accessible":widget.accessibleName()[:150],
        "visible":widget.isVisible(),
        "hidden":widget.isHidden(),
        "minimum":dims(widget.minimumSize()),
        "minimum_hint":dims(widget.minimumSizeHint()),
        "hint":dims(widget.sizeHint()),
        "maximum":dims(widget.maximumSize()),
        "geometry":rect(widget.geometry()),
        "policy":[policy.horizontalPolicy().name,policy.verticalPolicy().name],
        "font":[widget.font().family(),widget.font().pointSizeF(),widget.font().pixelSize()],
    }


def walk_layout(layout, path, names):
    if layout is None:
        return
    emit("LAYOUT",path=path,aliases=names.get(id(layout),[]),
         minimum=dims(layout.minimumSize()),hint=dims(layout.sizeHint()),
         geometry=rect(layout.geometry()),spacing=layout.spacing(),
         constraint=layout.sizeConstraint().name)
    for i in range(layout.count()):
        item=layout.itemAt(i)
        here=f"{path}/{i}"
        emit("ITEM",path=here,minimum=dims(item.minimumSize()),hint=dims(item.sizeHint()),
             geometry=rect(item.geometry()),empty=item.isEmpty())
        child=item.widget()
        if child is not None:
            emit("LAYOUT_WIDGET",path=here,**metrics(child,names))
            walk_layout(child.layout(),here+"/layout",names)
        elif item.layout() is not None:
            walk_layout(item.layout(),here+"/layout",names)


def flush(app,panel):
    for _ in range(5):
        panel.layout().activate()
        app.processEvents()


def snapshot(app,panel,label):
    flush(app,panel)
    names=aliases(panel)
    emit("SNAPSHOT",label=label,geometry=rect(panel.geometry()),
         minimum=dims(panel.minimumSize()),minimum_hint=dims(panel.minimumSizeHint()),
         hint=dims(panel.sizeHint()))
    for i in range(panel.radio_tabs.count()):
        page=panel.radio_tabs.widget(i)
        emit("TAB",index=i,text=panel.radio_tabs.tabText(i),**metrics(page,names))
        walk_layout(page.layout(),f"tab/{i}",names)
    # QScrollArea's widget and viewport aren't necessarily layout items.
    for i,widget in enumerate([panel]+panel.findChildren(QWidget)):
        emit("WIDGET",index=i,**metrics(widget,names))


def probe(app,panel,label):
    """Non-shipping perturbations: report which individual width hints matter."""
    ham=panel.radio_tabs.widget(1)
    candidates=[panel.radio_tabs.widget(0),ham]
    candidates.extend(ham.findChildren(QWidget))
    names=aliases(panel)
    # Start with the widest hint contributors; include hidden tab contents
    # and scan controls in snapshots, but don't change hidden children.
    unique={id(w):w for w in candidates if w.isVisible() or w in candidates[:2]}
    ordered=sorted(unique.values(),key=lambda w:max(w.minimumWidth(),w.minimumSizeHint().width(),w.sizeHint().width()),reverse=True)
    baseline=panel.minimumSizeHint().width()
    for widget in ordered[:35]:
        previous=QSizePolicy(widget.sizePolicy())
        minimum=widget.minimumSize()
        changed=QSizePolicy(previous)
        changed.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        widget.setSizePolicy(changed)
        widget.setMinimumWidth(0)
        widget.updateGeometry()
        flush(app,panel)
        observed=panel.minimumSizeHint().width()
        if observed!=baseline:
            emit("PROBE",label=label,baseline_width=baseline,observed_width=observed,
                 **metrics(widget,names))
        widget.setSizePolicy(previous)
        widget.setMinimumSize(minimum)
        widget.updateGeometry()
        flush(app,panel)
    # Determine whether one of the stacked tab pages is imposing the
    # top-level minimum even while its content is hidden.
    broadcast=panel.radio_tabs.widget(0)
    ham=panel.radio_tabs.widget(1)
    name=panel.radio_tabs.tabText(0)
    panel.radio_tabs.removeTab(0)
    flush(app,panel)
    emit("PAGE_ISOLATION",label=label,removed="broadcast",baseline_width=baseline,
         minimum_hint=dims(panel.minimumSizeHint()),ham_hint=dims(ham.minimumSizeHint()))
    panel.radio_tabs.insertTab(0,broadcast,name)
    panel.radio_tabs.setCurrentWidget(ham)
    flush(app,panel)


def main():
    app=QApplication.instance() or QApplication([])
    emit("ENV",platform=platform.platform(),python=sys.version,
         qt=qVersion(),qt_platform=app.platformName(),
         scale=os.environ.get("QT_SCALE_FACTOR",""),
         screens=[{"dpi":s.logicalDotsPerInch(),"ratio":s.devicePixelRatio(),
                   "geometry":rect(s.geometry())} for s in app.screens()])
    with patch.object(socket,"getaddrinfo",deny),patch.object(socket.socket,"connect",deny), \
         patch.object(QNetworkAccessManager,"get",deny),patch.object(QDesktopServices,"openUrl",deny):
        for larger in (False,True):
            panel=RadioPanel(confirm=lambda:False)
            try:
                panel.setStyleSheet(STYLE.replace("font-size: 12px;","font-size: 13px;") if larger else STYLE)
                panel.radio_tabs.setCurrentIndex(1)
                panel.resize(600,480)
                panel.show()
                label="larger" if larger else "normal"
                snapshot(app,panel,label+"/collapsed")
                probe(app,panel,label+"/collapsed")
                panel.ham_details_toggle.setChecked(True)
                panel.advanced_scan.setChecked(True)
                panel.resize(600,480)
                snapshot(app,panel,label+"/expanded")
                probe(app,panel,label+"/expanded")
            finally:
                panel.shutdown()
                panel.close()
                panel.deleteLater()
                app.processEvents()


if __name__=="__main__":
    main()
