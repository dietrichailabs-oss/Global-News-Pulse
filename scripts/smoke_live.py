"""Engineering-only live collection integration check. No native notifications."""
from __future__ import annotations
import argparse
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--consent-network", action="store_true")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path)
    args = parser.parse_args()
    if not args.consent_network:
        parser.error("Explicit --consent-network is required to contact five public sources")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from global_pulse.controller import Controller
    from global_pulse.ui import MainWindow
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    with tempfile.TemporaryDirectory(prefix="global-pulse-live-smoke-") as temporary:
        controller = Controller(temporary)
        selected = {"usgs", "nws", "globalvoices", "fcdo", "wb_inflation"}
        controller.set_setting("enabled_sources", sorted(selected))
        controller.set_setting("notifications_enabled", False)
        window = MainWindow(controller)
        window.show()
        started = time.monotonic()
        timer = QTimer()
        observed = set()
        result = {"status": "INCOMPLETE"}

        def check():
            rows = []
            for identifier in selected:
                state = controller.store.get_source_state(identifier)
                rows.append({"source_id": identifier, **state})
                if state.get("last_success") or state.get("last_failure"):
                    if identifier not in observed:
                        observed.add(identifier)
                        print(identifier, state.get("status"), flush=True)
            if observed == selected or time.monotonic() - started > 70:
                timer.stop()
                controller.pause()
                all_sources_succeeded = observed == selected and all(
                    row.get("last_success") and row.get("status") == "available"
                    for row in rows
                )
                result.update({"recorded_at": datetime.now(timezone.utc).isoformat(), "elapsed_seconds": round(time.monotonic()-started, 3), "sources": rows, "stats": controller.store.stats(), "ingest_errors": controller.store.last_ingest_errors, "native_notifications": "NOT EXERCISED", "status": "PASS" if all_sources_succeeded and not controller.store.last_ingest_errors and controller.store.stats().get("events", 0) > 0 else "REVIEW"})
                args.evidence.parent.mkdir(parents=True, exist_ok=True)
                args.evidence.write_text(json.dumps(result, indent=2))
                if args.snapshot:
                    args.snapshot.parent.mkdir(parents=True, exist_ok=True)
                    window.grab().save(str(args.snapshot))
                window.set_close_handler(None)
                window.close()
                controller.close()
                print(json.dumps({"status": result["status"], "stats": result["stats"]}), flush=True)
                app.quit()

        timer.timeout.connect(check)
        timer.start(250)
        controller.start()
        app.exec()
        return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
