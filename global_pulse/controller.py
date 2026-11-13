"""Orchestrates background collection, evidence storage, alerts and the Qt UI."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from contextlib import ExitStack
import threading
import tempfile
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, QTimer, QEvent, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QInputDialog

from .core import Store, alert_reason, build_brief, notification_view, muted_source_ids
from .sources import Scheduler, load_catalog, load_media_catalog, make_user_feed
from .translation import Translator, language_of
from .translation_process import TranslationProcess
from .security import atomic_text, csv_cell, safe_url, redact


def _rollback_partial_controller_resource(close):
    """Preserve the original startup exception while closing acquired resources."""
    try:
        close()
    except Exception:
        logging.getLogger("global_pulse").exception(
            "Unable to close a resource after failed Controller construction"
        )


def in_quiet_hours(settings, now=None):
    from .settings_boundary import quiet_hours_active
    return quiet_hours_active(settings, now)


class Controller(QObject):
    data_changed = Signal()
    status_changed = Signal(str)
    alert_received = Signal(dict)
    translation_ready = Signal(str, str)
    storage_problem = Signal(str)
    feed_translation_changed = Signal()
    gdelt_status_changed = Signal()
    model_download_changed = Signal(str, str)
    model_download_progress = Signal(str, int, int)
    quit_requested = Signal()
    native_alert = Signal(dict, str)

    def __init__(self, data_dir, *, demo=False, parent=None):
        super().__init__(parent)
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.demo = demo
        # Every acquired startup resource remains provisional until the full
        # controller, including the GDELT service, has initialized.
        with ExitStack() as rollback:
            self.store = Store(self.data_dir / ("synthetic.sqlite3" if demo else "global-pulse.sqlite3"), mode="synthetic" if demo else "live")
            rollback.callback(_rollback_partial_controller_resource, self.store.close)
            bundled = load_catalog()
            self._bundled_source_ids = {source["id"] for source in bundled}
            self.catalog = bundled + self.get_setting("user_feeds", [])
            self.media_catalog = load_media_catalog()
            self.monitoring = False
            self.notification_status = "Registering native notifications"
            self.last_collection = "Never"
            self._closed = False
            self.storage_problem.connect(self._pause_for_storage)
            self._ingest_lock = threading.RLock()
            self._workers = TranslationProcess(self.data_dir, self)
            rollback.callback(_rollback_partial_controller_resource, self._workers.close)
            self._workers.completed.connect(self._translation_complete)
            self._workers.progress.connect(self._model_progress)
            self._model_jobs = {}
            self._model_dialog = None
            self._store_closed = False
            self._translation_keys = {}
            self._translation_pending = set()
            self.translator = Translator(self.data_dir)
            rollback.callback(_rollback_partial_controller_resource, self.translator.cancelled.set)
            from .headline_translation import HeadlineTranslations
            self._headlines = HeadlineTranslations(self.translator, self._workers,
                lambda: self.get_setting("english_headlines", True), self)
            rollback.callback(_rollback_partial_controller_resource, self._headlines.close)
            self._headlines.changed.connect(self.feed_translation_changed.emit)
            self.scheduler = Scheduler(self.store, self._on_reports, self._on_source_status, self._on_observations, interval=self.get_setting("interval", 600))
            rollback.callback(_rollback_partial_controller_resource, self.scheduler.stop)
            self._apply_sources()
            self._retention_timer = QTimer(self)
            rollback.callback(_rollback_partial_controller_resource, self._retention_timer.stop)
            self._retention_timer.setInterval(24 * 60 * 60 * 1000)
            self._retention_timer.timeout.connect(self._prune_archive)
            self._retention_timer.start()
            from .gdelt_service import GdeltService
            self._gdelt = GdeltService(self.data_dir / ("synthetic.sqlite3" if demo else "global-pulse.sqlite3"),
                lambda: self.get_setting("gdelt_retention_days", 7), self)
            rollback.callback(_rollback_partial_controller_resource, self._gdelt.close)
            self._gdelt.changed.connect(self.gdelt_status_changed.emit)
            rollback.pop_all()  # Normal Controller.close() now owns these resources.

    def _prune_archive(self):
        if not self._closed:
            self.store.prune(self.get_setting("retention_days", 365))
            self.data_changed.emit()

    def _apply_sources(self):
        from .source_availability import enabled_ids
        enabled = enabled_ids(self.catalog, self.get_setting("enabled_sources", None))
        self.scheduler.set_sources([dict(source, enabled=source["id"] in enabled and not (
            self.get_setting("gdelt_batches_enabled", False) is True and source.get("adapter") == "gdelt_doc"))
                                    for source in self.catalog])

    def set_source_enabled(self, source_id, enabled):
        """Explicit provider-ID action; never starts monitoring or bypasses due times."""
        from .source_availability import capability
        if self._closed:
            raise RuntimeError("Controller is closed")
        if type(enabled) is not bool or not isinstance(source_id, str):
            raise ValueError("A provider identity and boolean state are required")
        source = next((s for s in self.catalog if s["id"] == source_id), None)
        if source is None:
            raise ValueError("Provider is no longer configured")
        if enabled and not capability(source)[0]:
            raise ValueError("This provider has no eligible configured collector")
        preference = self.get_setting("enabled_sources", None)
        # Match enabled_ids(): local/imported JSON settings may contain
        # non-string (including unhashable) entries.  Ignore those before
        # adding/removing a source; never reinterpret corrupt values as IDs.
        requested = ({s["id"] for s in self.catalog if s.get("enabled")}
                     if preference is None else
                     {item for item in preference if isinstance(item, str)}
                     if isinstance(preference, list) else set())
        if enabled:
            requested.add(source_id)
        else:
            requested.discard(source_id)
        self.set_setting("enabled_sources", sorted(requested))
        return enabled

    def get_setting(self, key, default=None):
        from .settings_boundary import monitoring_interval, retention_days, user_feeds
        value = self.store.get_setting(key, default)
        if key == "archive_max_gb":
            from .archive_storage import size_gb
            return size_gb(value)
        if key == "gdelt_batches_enabled":
            return value is True
        if key == "gdelt_retention_days":
            from .gdelt_schedule import retention_days as gdelt_days
            return gdelt_days(value)
        if key == "interval":
            return monitoring_interval(value)
        if key == "retention_days":
            return retention_days(value)
        if key == "user_feeds":
            return user_feeds(value, self._bundled_source_ids)
        return value

    def set_setting(self, key, value):
        if self._closed:
            return
        if key == "gdelt_batches_enabled" and type(value) is not bool:
            raise ValueError("GDELT collection requires a boolean")
        if key == "gdelt_retention_days" and (type(value) is not int or not 1 <= value <= 365):
            raise ValueError("GDELT retention must be 1 to 365 whole days")
        if key == "interval" and int(value) not in {300, 600, 1800, 3600}:
            raise ValueError("Choose a supported monitoring interval")
        if key in {"quiet_start", "quiet_end"}:
            datetime.strptime(value, "%H:%M")
        if key == "retention_days":
            value = max(1, min(3650, int(value)))
        if key == "english_headlines" and type(value) is not bool:
            raise ValueError("English headlines requires a boolean")
        if key in {"countries", "categories", "muted_sources", "enabled_sources"}:
            from .capacity_limits import MAX_TOTAL_SOURCES
            limit = MAX_TOTAL_SOURCES if key in {"muted_sources", "enabled_sources"} else 300
            if not isinstance(value, list) or len(value) > limit:
                raise ValueError("Invalid preference list")
        if key == "archive_max_gb":
            from .archive_storage import CHOICES_GB
            if type(value) is not int or value not in CHOICES_GB:
                raise ValueError("Choose 5, 10, 15, 20, 30, 50 or 100 GB")
            was_active = self._gdelt.active
            self._gdelt.set_active(False)
            try:
                self.store.set_setting(key, value)
            finally:
                self._gdelt.set_active(was_active and self.monitoring and not self.demo)
        else:
            self.store.set_setting(key, value)
        if key == "gdelt_batches_enabled":
            self._apply_sources()
            self._gdelt.set_active(value and self.monitoring and not self.demo)
        if key == "english_headlines" and not value:
            self._headlines.cancel_pending()
        if key == "interval":
            self.scheduler.set_interval(int(value))
        elif key == "enabled_sources":
            self._apply_sources()
        elif key == "retention_days":
            self.store.prune(int(value))
        self.data_changed.emit()

    def archive_storage_status(self):
        from .archive_storage import snapshot, last_cleanup, last_cleanup_attempt
        with self.store._lock:
            result = snapshot(self.store._conn, self.store.path)
            result["last_cleanup"] = last_cleanup(self.store._conn)
            result["cleanup_attempt"] = last_cleanup_attempt(self.store._conn)
        # The live result takes precedence over an older persisted attempt,
        # including when SQLite could not save the new status.
        if self._gdelt.cleanup_outcome:
            result["cleanup_attempt"] = dict(self._gdelt.cleanup_outcome)
        result["cleanup_error"] = self._gdelt.cleanup_error
        result["cleanup_running"] = self._gdelt._maintenance and self._gdelt.process is not None
        return result

    def clean_archive_cache(self):
        if self.demo or self._closed:
            return False
        return self._gdelt.request_cleanup()

    def _pause_for_storage(self, message):
        if not self._closed:
            self.pause()
            self.status_changed.emit(message)

    def gdelt_status(self):
        return self._gdelt.status()

    def gdelt_review_retry(self):
        self._gdelt.review_retry()

    def headline_view(self, event):
        return self._headlines.view(event)

    def events(self, **filters):
        return self.store.list_events(**filters)

    def event_filter_options(self):
        return self.store.event_filter_options()

    def event(self, identifier, at=None):
        # Preserve QObject's native event dispatch while retaining the public
        # event lookup contract used by the workstation view.
        if isinstance(identifier, QEvent):
            return super().event(identifier)
        return self.store.get_event(identifier, at=at)

    def start(self):
        if self.demo or self._closed:
            return
        self._prune_archive()
        self.monitoring = True
        self.scheduler.start()
        self.scheduler.resume()
        self._gdelt.set_active(self.get_setting("gdelt_batches_enabled", False) is True)
        self.status_changed.emit("Monitoring active")

    def pause(self):
        self.monitoring = False
        self.scheduler.pause()
        self._gdelt.set_active(False)
        self.status_changed.emit("Monitoring paused")
        self.data_changed.emit()

    def resume(self):
        if self.demo:
            self.status_changed.emit("Synthetic review mode · live collection is disabled")
            return
        if self._closed:
            return
        self.monitoring = True
        self.scheduler.start()
        self.scheduler.resume()
        self._gdelt.set_active(self.get_setting("gdelt_batches_enabled", False) is True)
        self.status_changed.emit("Monitoring active")
        self.data_changed.emit()

    def refresh(self):
        if self.demo:
            self.status_changed.emit("Synthetic review mode · no network collection")
        elif not self.monitoring:
            self.status_changed.emit("Monitoring is paused. Resume to collect source updates.")
        else:
            self.scheduler.poll_now()
            self.status_changed.emit("Checking eligible sources · provider intervals still apply")

    def _on_source_status(self, source_id, state):
        if self._closed:
            return
        if state.get("last_success"):
            self.last_collection = max(self.last_collection if self.last_collection != "Never" else "", state["last_success"])
        self.data_changed.emit()

    def _on_observations(self, observations):
        with self._ingest_lock:
            if not self._closed and self.monitoring:
                from .archive_storage import StorageBlocked
                try:
                    self.store.put_observations(observations)
                except StorageBlocked as error:
                    self.storage_problem.emit(str(error))
                    return
                self.data_changed.emit()

    def _watched(self, event, previous=None, *, reason=None):
        # Persisted/imported JSON can bypass the Settings UI's list validation.
        # Only actual nonblank string selections constitute a user filter.
        # An all-invalid list must not silently suppress legitimate alerts.
        def saved_filter(key):
            value = self.get_setting(key, [])
            return [item for item in value if isinstance(item, str) and item.strip()] if isinstance(value, list) else []

        countries = saved_filter("countries")
        categories = saved_filter("categories")
        muted = muted_source_ids(self.get_setting("muted_sources", []))
        if countries and not any(item.casefold() in {str(event.get("country", "")).casefold(), str(event.get("region", "")).casefold()} for item in countries):
            return False
        if categories and event.get("category") not in categories:
            return False
        reports = event.get("reports", [])
        if reports and all(r.get("source_id") in muted for r in reports):
            return False
        threshold = self.get_setting("alert_threshold", "moderate")
        ranks = {"unassessed": 0, "informational": 1, "moderate": 2, "high": 3, "critical": 4}
        if not isinstance(threshold, str) or threshold not in ranks:
            threshold = "moderate"
        significance = ranks.get(event.get("severity", "unassessed"), 0)
        # A validated correction/retraction may lower the current severity. The
        # prior, unmuted view of this SAME event must still qualify its notice.
        # Do not inherit severity for ordinary updates or unrelated events.
        if (previous and event.get("id") and previous.get("id") == event["id"]
                and isinstance(reason, str)
                and reason.startswith(("Correction:", "Retraction:"))):
            significance = max(significance, ranks.get(previous.get("severity", "unassessed"), 0),
                max((ranks.get(level, 0) for source, level in event.get("significance_history", {}).items()
                     if source not in muted), default=0))
        if significance < ranks.get(threshold, 2):
            return False
        return True

    def _on_reports(self, reports, *, allow_synthetic=False, now=None):
        if self._closed or (not self.monitoring and not allow_synthetic):
            return
        if not allow_synthetic:
            reports = [r for r in reports if not r.get("synthetic", False)]
        with self._ingest_lock:
            if self._closed or (not self.monitoring and not allow_synthetic):
                return
            from .archive_storage import StorageBlocked
            try:
                changed = self.store.ingest(reports, now=now)
            except StorageBlocked as error:
                self.storage_problem.emit(str(error))
                return
            if self.store.last_ingest_errors:
                self.status_changed.emit(f"{len(self.store.last_ingest_errors)} source record(s) were rejected; other reports remain available")
            previous = self.store.last_previous_events
            muted = self.get_setting("muted_sources", [])
            for stored_event in changed:
                if self._closed or (not self.monitoring and not allow_synthetic):
                    break
                event = notification_view(stored_event, muted)
                if not event:
                    continue
                prior = notification_view(previous.get(event["id"]), muted)
                reason = alert_reason(event, prior)
                if (not reason or not self._has_fresh_change(event, now=now, reason=reason)
                        or not self._watched(event, previous=prior, reason=reason)):
                    continue
                alert = self.store.add_alert(event, reason)
                if not alert:
                    continue
                self.alert_received.emit(alert)
                settings = {k: self.get_setting(k, default) for k, default in [("quiet_enabled", False), ("quiet_start", "22:00"), ("quiet_end", "07:00")]}
                if self.demo:
                    self.store.update_alert_delivery(alert["id"], "Synthetic review: native delivery disabled")
                elif not self.get_setting("notifications_enabled", True):
                    self.store.update_alert_delivery(alert["id"], "Notifications muted: retained in internal history")
                elif in_quiet_hours(settings):
                    self.store.update_alert_delivery(alert["id"], "Quiet hours: retained in internal history")
                elif self.monitoring:
                    self.native_alert.emit(dict(event, _alert_id=alert["id"]), reason)
            self.data_changed.emit()

    @staticmethod
    def _has_fresh_change(event, now=None, *, reason=None):
        """Historical imports remain searchable without masquerading as alerts.

        A fresh correction to an older event qualifies by its dated source
        update. Retrieval time alone is never evidence of publication recency.
        """
        try:
            moment = datetime.fromisoformat(str(now).replace("Z", "+00:00")) if now else datetime.now(timezone.utc)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return False
        notice_kind = ("retraction" if isinstance(reason, str) and reason.startswith("Retraction:")
                       else "correction" if isinstance(reason, str) and reason.startswith("Correction:") else None)
        changed = {c.get("record_key") for c in event.get("changes", [])
                   if notice_kind is None or c.get("kind") == notice_kind}
        for report in event.get("reports", []):
            if report.get("record_key") not in changed or not report.get("publication_time_known", True):
                continue
            for value in (report.get("source_updated_at"), report.get("published_at")):
                if not value:
                    continue
                try:
                    published = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                    if published.tzinfo is None:
                        published = published.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    continue
                age = (moment - published).total_seconds()
                if -600 <= age <= 86400:
                    return True
        return False

    def load_fixture(self, path):
        if not self.demo:
            raise ValueError("Synthetic fixtures require --demo and a separate database")
        payload = json.loads(Path(path).read_text())
        stages = payload.get("stages", []) if isinstance(payload, dict) else []
        if stages:
            for stage in stages:
                reports = stage.get("reports", [stage["report"]] if "report" in stage else [])
                for report in reports:
                    report["synthetic"] = True
                self._on_reports(reports, allow_synthetic=True, now=stage.get("at"))
                if stage.get("observations"):
                    observations = [dict(o, synthetic=True) for o in stage["observations"]]
                    self.store.put_observations(observations)
        else:
            reports = payload.get("reports", []) if isinstance(payload, dict) else payload
            for report in reports:
                report["synthetic"] = True
            self._on_reports(reports, allow_synthetic=True)
        self.status_changed.emit("SYNTHETIC SCENARIO · No live reports or native alerts")
        self.data_changed.emit()

    def set_situation_saved(self, identifier, saved):
        if self._closed:
            raise ValueError("Archive is closed")
        state = self.store.set_situation_saved(identifier, saved)
        self.data_changed.emit()
        return state

    def save_situation(self, identifier):
        self.store.save_situation(identifier)
        self.data_changed.emit()

    def open_url(self, url):
        try:
            return QDesktopServices.openUrl(QUrl(safe_url(url)))
        except ValueError as error:
            self.status_changed.emit(str(error))
            return False

    def translate_report(self, report):
        rid = str(report.get("id", ""))
        text = (str(report.get("title", "")) + ". " + str(report.get("summary", ""))).strip()[:4000]
        language = language_of(text, report.get("language", ""))
        if language == "en":
            self.translation_ready.emit(rid, "Original English excerpt\n\n" + text)
            return
        if language not in self.translator.catalog:
            self.translation_ready.emit(rid, "No reviewed offline model is available for " + language + ". The original language and publisher link are preserved.")
            return
        if rid in self._translation_pending:
            return
        item = self.translator.catalog[language]
        install = not self.translator.installed(language)
        if install:
            answer = QMessageBox.question(None, "Download an offline language model?", f"Translate {item['name']} into English locally. Download {item['size_bytes'] / 1_000_000:.1f} MB from Argos Open Technologies?\n\nThe package is checked against its reviewed SHA-256. Your article text stays on this computer. Machine translations can contain errors.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                self.translation_ready.emit(rid, "Model download declined. Original text preserved.")
                return
        key = "translation:" + hashlib.sha256((language + text).encode()).hexdigest()
        cached = self.get_setting(key)
        if cached is not None:
            self._translation_complete(rid, language, cached, "")
            return
        self._translation_pending.add(rid)
        self._translation_keys[rid] = key
        self.status_changed.emit("Preparing local translation…")
        if not self._workers.submit(rid, language, text, install):
            self._translation_pending.discard(rid)
            self._translation_keys.pop(rid, None)
            self.translation_ready.emit(rid, "Translation queue is full or the application is closing.")

    def _translation_complete(self, rid, language, text, error):
        if self._headlines.complete(rid, language, text, error):
            return
        if rid in self._model_jobs:
            self._model_jobs.pop(rid, None)
            if not self._closed:
                status = ("Installed" if not error and self.translator.installed(language)
                          else "Download failed: " + redact(error or "installed files could not be verified"))
                self.model_download_changed.emit(language, status)
            return
        self._translation_pending.discard(rid)
        key = self._translation_keys.pop(rid, None)
        if self._closed:
            return
        if error:
            self.translation_ready.emit(rid, "Translation unavailable: " + redact(error))
        else:
            if key:
                self.store.set_setting(key, text)
            self.translation_ready.emit(rid, f"Machine translation · {language} → English · processed locally\n\n{text}\n\nOriginal text is retained in the source record.")

    def _model_progress(self, rid, received, total):
        code = self._model_jobs.get(rid)
        if code and not self._closed:
            self.model_download_progress.emit(code, received, total)

    def download_translation_model(self, code, parent=None):
        from uuid import uuid4
        if self._closed or code not in self.translator.catalog or code in self._model_jobs.values():
            return False
        if self.translator.installed(code):
            self.model_download_changed.emit(code, "Installed")
            return False
        item = self.translator.catalog[code]
        answer = QMessageBox.question(parent, "Download offline language model?",
            f"Download {item['name']} → English ({item['size_bytes']/1_000_000:.1f} MB) from Argos Open Technologies?\n\n"
            "The download is checked against its reviewed SHA-256. Translation stays on this computer; no article text is uploaded.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return False
        rid = "model-download:" + uuid4().hex
        self._model_jobs[rid] = code
        self.model_download_changed.emit(code, "Queued / downloading")
        # Empty text means install only; no sample inference or source text.
        if not self._workers.submit(rid, code, "", True):
            self._model_jobs.pop(rid, None)
            self.model_download_changed.emit(code, "Download queue full or application closing")
            return False
        return True

    def cancel_model_download(self, code):
        for rid, language in list(self._model_jobs.items()):
            if language == code:
                self._workers.cancel(rid)
                return True
        return False

    def remove_translation_model(self, code):
        if self._closed or code not in self.translator.catalog:
            return False
        if code in self._model_jobs.values():
            return False
        removed = self.translator.remove(code)
        self.model_download_changed.emit(code, "Removed from this computer" if removed else "Available — not installed")
        return removed

    def manage_translation_models(self, parent=None):
        from .model_manager import ModelManager
        if self._model_dialog is None:
            self._model_dialog = ModelManager(self, parent)
            self._model_dialog.destroyed.connect(lambda:setattr(self, "_model_dialog", None))
        self._model_dialog.show()
        self._model_dialog.raise_()
        self._model_dialog.refresh()

    def add_user_feed(self, url, name, category="News"):
        # Validate syntax here; the background collector validates public DNS
        # before making any request. Adding a feed must not block the UI on DNS.
        source = make_user_feed(url, name, category=category, validate_dns=False)
        feeds = self.get_setting("user_feeds", [])
        if source["id"] in {s["id"] for s in self.catalog}:
            raise ValueError("This feed is already configured")
        from .settings_boundary import MAX_TOTAL_SOURCES
        if len(self.catalog) >= MAX_TOTAL_SOURCES:
            raise ValueError("Source catalog is full")
        feeds.append(source)
        self.store.set_setting("user_feeds", feeds)
        self.catalog.append(source)
        self._apply_sources()
        self.data_changed.emit()

    def remove_user_feed(self, source_id):
        source_id = str(source_id)
        feeds = self.get_setting("user_feeds", [])
        selected = next((s for s in feeds if s.get("id") == source_id), None)
        if not selected or selected.get("access_status") != "user_supplied" or not selected.get("custom"):
            raise ValueError("Only a user-configured public feed can be removed")
        self.store.set_setting("user_feeds", [s for s in feeds if s.get("id") != source_id])
        for key in ("enabled_sources", "muted_sources"):
            values = self.store.get_setting(key, None)
            if isinstance(values, list) and source_id in values:
                self.store.set_setting(key, [value for value in values if value != source_id])
        self.catalog = [s for s in self.catalog if s.get("id") != source_id]
        self.store.delete_source_state(source_id)
        self._apply_sources()
        self.data_changed.emit()
        return True

    def export_brief(self, path, period="daily"):
        days = 7 if period == "weekly" else 1
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        events = self.store.list_events(since=since, limit=500)
        if Path(path).suffix.lower() in {".html", ".htm"}:
            from .brief_rendering import brief_html
            text = brief_html(events, period)
        else:
            text = build_brief(events, period)
            if self.demo:
                text = "# SYNTHETIC TEST DATA — NOT REAL EVENTS\n\n" + text
        atomic_text(path, text)
        self.status_changed.emit("Intelligence brief exported")

    def export_events(self, path):
        path = Path(path).expanduser().absolute()
        if path.is_symlink():
            raise ValueError("Export destination must not be a symbolic link")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".global-pulse-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as target:
                events = self.store.iter_events(batch_size=100)
                if path.suffix.lower() == ".csv":
                    writer = csv.writer(target)
                    fields = ["id", "title", "category", "region", "severity", "verification", "published_at", "updated_at", "recap", "synthetic"]
                    writer.writerow(fields + ["source_urls", "attributions"])
                    for event in events:
                        reports = event.get("reports", [])
                        writer.writerow([csv_cell(event.get(k, "")) for k in fields] + [csv_cell(" | ".join(r.get("url", "") for r in reports)), csv_cell(" | ".join(str(r.get("attribution", r.get("publisher", ""))) for r in reports))])
                else:
                    header = {"product": "Global Pulse", "synthetic": self.demo, "exported_at": datetime.now(timezone.utc).isoformat()}
                    target.write(json.dumps(header, ensure_ascii=False)[:-1] + ',"events":[\n')
                    for index, event in enumerate(events):
                        if index:
                            target.write(",\n")
                        target.write(json.dumps(event, ensure_ascii=False))
                    target.write("\n]}\n")
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        self.status_changed.emit("Event archive exported")

    def quit(self):
        self.quit_requested.emit()

    def close(self):
        if self._store_closed:
            return
        self.monitoring = False
        self._closed = True
        self._retention_timer.stop()
        self._gdelt.close()
        self.translator.cancelled.set()
        self.scheduler.stop()
        self._headlines.close()
        self._workers.close()
        self._translation_pending.clear()
        self._translation_keys.clear()
        self._model_jobs.clear()
        with self._ingest_lock:
            self.store.close()
            self._store_closed = True
