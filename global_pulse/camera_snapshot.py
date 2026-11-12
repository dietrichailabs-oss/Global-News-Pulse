"""Bounded, memory-only asynchronous snapshots from the bundled reviewed registry."""
from datetime import datetime, timezone
from time import monotonic
from PySide6.QtCore import Qt, QTimer, QUrl, Signal, QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QPixmap, QImageReader
from PySide6.QtWidgets import QLabel, QSizePolicy
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from .camera_context import approved_camera


class CameraSnapshot(QLabel):
    status_changed=Signal(str)
    MAX_BYTES=4_000_000
    # Process-memory only. Rapid event switches must not bypass provider cadence.
    # Exactly the bundled registry IDs may create entries; no feed URLs are keys.
    _attempts = {}
    _images = {}

    def __init__(self,item,parent=None):
        super().__init__(parent)
        self.item=approved_camera(item)
        if not self.item:raise ValueError('Camera is not in the reviewed public registry')
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Ignored)
        self.setMinimumSize(40,40)
        self.manager=QNetworkAccessManager(self)
        self.reply=None;self._data=bytearray();self._pixmap=None;self._stopped=True
        self.timer=QTimer(self);self.timer.setInterval(max(900,self.item['refresh_seconds'])*1000)
        self.timer.timeout.connect(self.refresh)
        self.deadline=QTimer(self);self.deadline.setSingleShot(True);self.deadline.setInterval(15000)
        self.deadline.timeout.connect(self._timeout)

    def start(self):
        self._stopped=False;self.refresh();self.timer.start()

    def refresh(self):
        if self._stopped or self.reply:return
        key=self.item['id']; interval=max(900,self.item['refresh_seconds'])
        previous=self._attempts.get(key)
        remaining=interval-(monotonic()-previous) if previous is not None else 0
        if remaining>0:
            cached=self._images.get(key)
            if cached:
                self._pixmap=QPixmap.fromImage(cached[0]);self._paint_image()
                self.status_changed.emit(f"{self.item['provider']} · cached snapshot fetched {cached[1]}; capture time: see image · area context only")
            else:
                self.setText('Camera refresh deferred to provider cadence\nUse original source for current availability')
            self.timer.setInterval(max(1000,int(remaining*1000)+1))
            return
        self._attempts[key]=monotonic()
        self.timer.setInterval(interval*1000)
        request=QNetworkRequest(QUrl(self.item['snapshot_url']))
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setAttribute(QNetworkRequest.Attribute.CookieLoadControlAttribute,QNetworkRequest.LoadControl.Manual)
        request.setAttribute(QNetworkRequest.Attribute.CookieSaveControlAttribute,QNetworkRequest.LoadControl.Manual)
        request.setAttribute(QNetworkRequest.Attribute.CacheLoadControlAttribute,QNetworkRequest.CacheLoadControl.AlwaysNetwork)
        request.setRawHeader(b'User-Agent',b'GlobalPulse/0.1 (consented public landscape camera)')
        request.setRawHeader(b'Accept',b'image/jpeg,image/png')
        request.setRawHeader(b'Accept-Encoding',b'identity')
        self._data.clear();self.setText('Connecting to public camera…')
        self.reply=self.manager.get(request)
        self.reply.setReadBufferSize(65536)
        self.reply.readyRead.connect(self._read)
        self.reply.finished.connect(self._finished)
        self.deadline.start()

    def _read(self):
        if not self.reply:return
        self._data.extend(bytes(self.reply.readAll()))
        if len(self._data)>self.MAX_BYTES:
            self.reply.abort()

    def _timeout(self):
        if self.reply:self.reply.abort()

    def _finished(self):
        reply=self.reply
        if not reply:return
        self._read();self.reply=None;self.deadline.stop()
        status=reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        content=bytes(reply.rawHeader('Content-Type')).decode('ascii','ignore').split(';')[0].lower()
        valid=not self._stopped and reply.error()==QNetworkReply.NetworkError.NoError and status==200 and content in {'image/jpeg','image/png'} and len(self._data)<=self.MAX_BYTES
        if valid:
            data=QByteArray(bytes(self._data));buffer=QBuffer(data);buffer.open(QIODevice.OpenModeFlag.ReadOnly)
            reader=QImageReader(buffer);size=reader.size()
            valid=size.isValid() and size.width()*size.height()<=16_000_000
            image=reader.read() if valid else None
            valid=valid and image is not None and not image.isNull()
            if valid:
                self._pixmap=QPixmap.fromImage(image);self._paint_image()
                now=datetime.now(timezone.utc).strftime('%d %b %H:%M UTC')
                self._images[self.item['id']]=(image,now)
                self.status_changed.emit(f"{self.item['provider']} · snapshot fetched {now}; capture time: see image · area context, not incident proof")
        if not valid and not self._stopped:
            self._images.pop(self.item['id'],None)
            self._pixmap=None;self.clear();self.setText(f'Camera unavailable (HTTP {status or "network error"})\nUse original source')
            self.status_changed.emit('Camera unavailable; no live status claimed. Retry on provider cadence.')
        self._data.clear();reply.deleteLater()

    def _paint_image(self):
        if self._pixmap:
            self.setPixmap(self._pixmap.scaled(self.size(),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self,event):
        super().resizeEvent(event);self._paint_image()

    def stop(self):
        self._stopped=True;self.timer.stop();self.deadline.stop()
        reply,self.reply=self.reply,None
        if reply:reply.abort();reply.deleteLater()
        self._data.clear();self._pixmap=None;self.clear()

    def closeEvent(self,event):
        self.stop();super().closeEvent(event)
