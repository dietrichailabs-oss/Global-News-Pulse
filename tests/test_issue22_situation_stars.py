"""Offline real Store/Controller/Qt star controls; all reports are synthetic."""
from __future__ import annotations
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from datetime import datetime, timedelta, timezone
import sqlite3
import pytest
from PySide6.QtCore import Qt, QEvent, QTimer
from PySide6.QtWidgets import QApplication, QMenu
from global_pulse.core import Store
from global_pulse.controller import Controller
from global_pulse.ui import MainWindow


def reports():
    now = (datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
    return [dict(id='STAR-FIXTURE-'+name, source_id='synthetic-star-source',
                 publisher='ISOLATED STAR TEST', title='SYNTHETIC star fixture '+name,
                 summary='Inert offline UI fixture, not reporting.',
                 url='https://example.org/star-test/'+name, event_key='star-fixture:'+name,
                 published_at=now, retrieved_at=now, category='News', region='Global',
                 country='', synthetic=True, severity='unassessed') for name in ('A','B')]


@pytest.fixture
def archive(tmp_path):
    with Store(tmp_path/'stars.sqlite3',mode='synthetic') as store:
        events=store.ingest(reports())
        yield store, [e['id'] for e in events]


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def desktop(app,tmp_path):
    controller=Controller(tmp_path,demo=True)
    events=controller.store.ingest(reports())
    window=MainWindow(controller)
    window.show();app.processEvents()
    ids=[e['id'] for e in events]
    window.navigate_event(ids[0]);app.processEvents()
    yield window,controller,ids
    window._force_close=True
    window.close();controller.close();window.deleteLater()
    app.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()


def test_explicit_save_is_idempotent_and_preserves_custom_title_and_visit(archive):
    store,ids=archive
    store.save_situation(ids[0],'My custom room')
    store.visit_situation(ids[0])
    before=store.list_situations()[0]
    for _ in range(3):
        assert store.set_situation_saved(ids[0],True)=={'event_id':ids[0],'saved':True}
    after=store.list_situations()[0]
    assert len(store.list_situations())==1
    for key in ('title','saved_at','last_visited_revision','last_visited_at'):
        assert after[key]==before[key]


def test_unstar_is_idempotent_and_never_deletes_evidence(archive):
    store,ids=archive
    before=store.get_event(ids[0]);stats=store.stats()
    store.set_situation_saved(ids[0],True)
    store.set_situation_saved(ids[0],False)
    store.set_situation_saved(ids[0],False)
    assert store.get_event(ids[0])==before
    assert store.stats()==stats
    assert store.situation_state(ids[0])['saved'] is False


def test_star_survives_database_close_and_reopen(tmp_path):
    path=tmp_path/'restart.sqlite3'
    with Store(path,mode='synthetic') as store:
        identity=store.ingest(reports())[0]['id']
        store.set_situation_saved(identity,True)
    with Store(path,mode='synthetic') as reopened:
        assert reopened.situation_state(identity)=={'event_id':identity,'saved':True}
        assert identity in reopened.saved_situation_ids()
        reopened.set_situation_saved(identity,False)
    with Store(path,mode='synthetic') as reopened:
        assert reopened.situation_state(identity)['saved'] is False
        assert reopened.get_event(identity) is not None


def test_unknown_event_cannot_create_or_redirect_a_bookmark(archive):
    store,ids=archive
    assert store.situation_state('no-such-event') is None
    with pytest.raises(ValueError):store.set_situation_saved('no-such-event',True)
    assert not store.saved_situation_ids()
    assert store.get_event(ids[0])


@pytest.mark.parametrize('value',[1,0,'true',None])
def test_saved_state_requires_actual_boolean(archive,value):
    store,ids=archive
    with pytest.raises(ValueError):store.set_situation_saved(ids[0],value)
    assert not store.saved_situation_ids()


def test_star_button_is_visible_and_toggles_persisted_state(desktop,app):
    window,controller,ids=desktop
    assert window.save_button.isVisible()
    assert window.save_button.text()=='☆ Star'
    window.save_button.click();app.processEvents()
    assert controller.store.situation_state(ids[0])['saved']
    assert window.save_button.text()=='★ Starred'
    assert window.save_button.isChecked()
    assert 'Unstar' in window.save_button.accessibleName()
    window.save_button.click();app.processEvents()
    assert not controller.store.situation_state(ids[0])['saved']
    assert window.save_button.text()=='☆ Star'
    assert controller.event(ids[0]) is not None


def test_star_state_follows_selection_not_previous_event(desktop,app):
    window,controller,ids=desktop
    window.save_button.click()
    window.navigate_event(ids[1]);app.processEvents()
    assert window.save_button.text()=='☆ Star'
    assert not window.save_button.isChecked()
    window.navigate_event(ids[0]);app.processEvents()
    assert window.save_button.text()=='★ Starred'


def test_stale_button_cannot_star_a_different_selection(desktop):
    window,controller,ids=desktop
    assert window.save_button.property('event_id')==ids[0]
    window._selected_id=ids[1]  # selection changed before its next render
    window.save_button.click()
    assert not controller.store.saved_situation_ids()
    assert 'Selection changed' in window.status_label.text()
    assert window.save_button.property('event_id')==ids[1]


def test_pruned_selection_is_refused_without_false_saved_state(desktop):
    window,controller,ids=desktop
    later=(datetime.now(timezone.utc)+timedelta(days=10)).isoformat()
    controller.store.prune(1,now=later)
    assert controller.event(ids[0]) is None
    window.save_button.click()
    assert not controller.store.saved_situation_ids()
    assert not window.save_button.isEnabled()
    assert window.save_button.text()=='☆ Star'


def test_feed_marker_updates_without_mutating_evidence(desktop,app):
    window,controller,ids=desktop
    window.save_button.click();app.processEvents()
    rows=[window.feed_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(window.feed_list.count())]
    assert next(row for row in rows if row['id']==ids[0])['_situation_starred'] is True
    assert next(row for row in rows if row['id']==ids[1])['_situation_starred'] is False
    assert '_situation_starred' not in controller.event(ids[0])
    assert all('_situation_starred' not in r for r in controller.event(ids[0])['reports'])


def test_feed_context_action_is_bound_to_clicked_row(desktop,app):
    window,controller,ids=desktop
    target=next(window.feed_list.item(i) for i in range(window.feed_list.count())
                if window.feed_list.item(i).data(Qt.ItemDataRole.UserRole)['id']==ids[1])
    window.feed_list.scrollToItem(target);app.processEvents()
    position=window.feed_list.visualItemRect(target).center()
    results=[]
    errors=[]
    timed_out=[]

    def close_menus():
        for menu in window.feed_list.findChildren(QMenu):
            menu.close()

    def choose():
        # Interact with the real modal QMenu inside its event loop. Replacing
        # the QMenu.exec descriptor did not intercept its native overload in
        # the earlier run, leaving a real menu waiting forever for user input.
        menu=app.activePopupWidget()
        try:
            if not isinstance(menu,QMenu) or not menu.isVisible():
                raise AssertionError('Expected the actual visible context menu')
            actions=menu.actions()
            if len(actions)!=1 or actions[0].text()!='★ Star situation':
                raise AssertionError('Expected the row-bound Star action')
            window._selected_id=ids[0]
            actions[0].trigger()
            results.append('triggered-real-action')
        except Exception as exc:
            # Exceptions in Qt callbacks can be swallowed; assert them back in
            # pytest after the menu closes, not only inside the callback.
            errors.append(type(exc).__name__+': '+str(exc))
        finally:
            close_menus()

    def timeout_menu():
        timed_out.append(True)
        close_menus()

    driver=QTimer(window);driver.setSingleShot(True);driver.timeout.connect(choose)
    watchdog=QTimer(window);watchdog.setSingleShot(True);watchdog.timeout.connect(timeout_menu)
    driver.start(0);watchdog.start(1500)
    try:
        window._show_feed_situation_menu(position)
    finally:
        driver.stop();watchdog.stop()
        driver.deleteLater();watchdog.deleteLater()
    assert not timed_out, 'Context-menu driver did not execute'
    assert not errors, errors
    assert results==['triggered-real-action']
    assert controller.store.saved_situation_ids()=={ids[1]}


def test_situations_page_can_unstar_without_deleting_event(desktop,app):
    window,controller,ids=desktop
    window.save_button.click();window.open_page(1);app.processEvents()
    assert window.situation_list.count()==1
    window.situation_list.setCurrentRow(0)
    assert window.unstar_button.isEnabled()
    window.unstar_button.click();app.processEvents()
    assert window.situation_list.count()==0
    assert not window.unstar_button.isEnabled()
    assert not controller.store.saved_situation_ids()
    assert controller.event(ids[0]) is not None
    window.open_page(0)
    assert window.save_button.text()=='☆ Star'


def test_situation_refresh_preserves_selection_and_does_not_mark_a_visit(desktop):
    window,controller,ids=desktop
    controller.set_situation_saved(ids[0],True)
    controller.set_situation_saved(ids[1],True)
    window.open_page(1);window.situation_list.setCurrentRow(0)
    identity=window.situation_list.currentItem().data(Qt.ItemDataRole.UserRole)
    before={s['event_id']:s['last_visited_revision'] for s in controller.store.list_situations()}
    window.refresh_data()
    assert window.situation_list.currentItem().data(Qt.ItemDataRole.UserRole)==identity
    assert {s['event_id']:s['last_visited_revision'] for s in controller.store.list_situations()}==before


def test_failed_write_restores_unstarred_control(desktop,monkeypatch):
    window,controller,ids=desktop
    def fail(*_):raise sqlite3.OperationalError('synthetic write failure')
    monkeypatch.setattr(controller,'set_situation_saved',fail)
    window.save_button.click()
    assert window.save_button.text()=='☆ Star'
    assert not window.save_button.isChecked()
    assert 'Could not change' in window.status_label.text()
    assert not controller.store.saved_situation_ids()


def test_old_save_entry_point_remains_explicit_and_idempotent(desktop):
    window,controller,ids=desktop
    window._save_selected();window._save_selected()
    assert controller.store.saved_situation_ids()=={ids[0]}
    assert window.save_button.isChecked()


def test_empty_brief_clears_the_bound_target(desktop):
    window,controller,ids=desktop
    window._render_empty_brief()
    assert not window.save_button.isEnabled()
    assert window.save_button.property('event_id')==''
    assert window.save_button.text()=='☆ Star'

def test_feed_star_menu_fails_closed_if_archive_unavailable(desktop, app, monkeypatch):
    window, controller, ids = desktop
    target = next(window.feed_list.item(i) for i in range(window.feed_list.count())
                  if window.feed_list.item(i).data(Qt.ItemDataRole.UserRole)['id'] == ids[0])
    window.feed_list.scrollToItem(target); app.processEvents()
    position = window.feed_list.visualItemRect(target).center()

    def unavailable(_):
        raise sqlite3.OperationalError("synthetic database busy")
    monkeypatch.setattr(controller.store, 'situation_state', unavailable)
    window._show_feed_situation_menu(position)

    assert "archive is unavailable" in window.status_label.text()
    assert app.activePopupWidget() is None
    assert not controller.store.saved_situation_ids()


def test_feed_star_menu_rejects_malformed_row_without_creating_bookmark(desktop, app):
    window, controller, ids = desktop
    target = next(window.feed_list.item(i) for i in range(window.feed_list.count())
                  if window.feed_list.item(i).data(Qt.ItemDataRole.UserRole)['id'] == ids[0])
    target.setData(Qt.ItemDataRole.UserRole, "not a canonical event")
    window.feed_list.scrollToItem(target); app.processEvents()
    window._show_feed_situation_menu(window.feed_list.visualItemRect(target).center())
    assert "no valid archived event" in window.status_label.text()
    assert not controller.store.saved_situation_ids()
