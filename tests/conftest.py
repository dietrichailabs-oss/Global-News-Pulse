"""Explicit Qt test-session teardown for native Windows interpreter safety.

The full native Qt suite creates hidden top-level QWidget objects across
unrelated modules. Without flushing their deferred deletions before pytest
returns, they can remain owned by QApplication until Python extension-module
finalization. This hook affects tests only; it does not change product cleanup,
test selection, fixture expectations, or any native process exit status.
"""
from __future__ import annotations

import pytest


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """Drain Qt widgets after all test fixtures have torn down.

    Do not force-exit, override QApplication lifetime, weaken the Chromium
    sandbox or swallow Qt destruction errors. A failed teardown remains a
    genuine pytest failure, rather than converting a native STOP into PASS.
    """
    try:
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return  # Non-GUI/source-only environment with no Qt installation.

    app = QApplication.instance()
    if app is None:
        return
    # At this point all pytest test cases and fixture finalizers have run.
    # Hidden top-level widgets should not survive into Python interpreter
    # module finalization merely because their deleteLater never got pumped.
    pending = tuple(app.topLevelWidgets())
    print("QT_TEST_SESSION_TEARDOWN_BEFORE=%d" % len(pending), flush=True)
    for widget in pending:
        widget.hide()  # Avoid custom user-close handlers during test teardown.
        widget.deleteLater()
    for _ in range(3):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
    remaining = len(app.topLevelWidgets())
    print("QT_TEST_SESSION_TEARDOWN_AFTER=%d" % remaining, flush=True)
    if remaining:
        raise RuntimeError(
            "Qt test session still owns %d top-level widget(s)" % remaining
        )
