import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from global_pulse.core import Store
from global_pulse.media_widget import MediaPanel, youtube_id
from global_pulse.sources import load_media_catalog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _entry(identity, group, *, kind="video"):
    return {
        "id": identity,
        "title": identity.upper(),
        "provider": "Synthetic provider",
        "type": kind,
        "group": group,
        "region": "Global",
        "url": f"https://example.com/{identity}",
        "availability": "synthetic test entry",
        "rights": "test only",
    }


def test_tv_channel_catalog_has_requested_banks_and_worldwide_sources():
    catalog = load_media_catalog()
    groups = {}
    for item in catalog:
        groups.setdefault(item.get("group"), []).append(item)
        assert str(item.get("url", "")).startswith("https://")
        assert item.get("rights")
        assert item.get("availability")

    assert len(groups.get("News", [])) >= 4
    assert len(groups.get("Markets", [])) >= 4
    assert len(groups.get("Weather", [])) >= 3

    ids = {item["id"] for item in catalog}
    assert {
        "associated_press",
        "bbc_news",
        "nbc_news_now",
        "france24_en",
        "dw_news",
        "trt_world",
        "aljazeera_en",
        "cna",
        "africanews",
        "globalnews_ca",
        "bloomberg_tv",
        "schwab_network",
        "yahoo_finance",
        "fox_weather",
        "accuweather_now",
        "weathernation",
    } <= ids

    ap = next(item for item in catalog if item["id"] == "associated_press")
    assert "commercial" in ap["description"].lower()
    assert "authorization" in ap["rights"].lower()


def test_direct_official_youtube_live_entries_remain_embed_parseable():
    catalog = {item["id"]: item for item in load_media_catalog()}
    assert youtube_id(catalog["nbc_news_now"]["url"]) == "yDOkVG1uytM"
    assert youtube_id(catalog["france24_en"]["url"]) == "Ap-UM1O9RBU"
    assert youtube_id(catalog["trt_world"]["url"]) == "ABfFhWzWs0s"


def test_each_media_tile_can_channel_up_down_across_whole_bank(app):
    panel = MediaPanel()
    catalog = [_entry(f"n{i}", "News") for i in range(6)]
    panel.set_catalog(catalog)
    panel.bank_combo.setCurrentText("News")
    app.processEvents()
    tile = panel.tiles[0]

    assert tile.selector.count() == 6
    assert tile._current()["id"] == "n0"
    assert tile.select_relative(1)
    assert tile._current()["id"] == "n1"
    assert tile.select_relative(-1)
    assert tile._current()["id"] == "n0"
    assert tile.select_relative(-1)
    assert tile._current()["id"] == "n5"

    # All four tiles see the full channel bank but start at different channels.
    assert [t.selector.count() for t in panel.tiles] == [6, 6, 6, 6]
    assert [t._current()["id"] for t in panel.tiles] == ["n5", "n1", "n2", "n3"]
    panel.close()


def test_channel_bank_filters_and_resets_media_kind_filter(app):
    panel = MediaPanel()
    panel.set_catalog([
        _entry("news1", "News"),
        _entry("news2", "News"),
        _entry("market1", "Markets"),
        _entry("market2", "Markets"),
        _entry("weather1", "Weather"),
        _entry("radio1", "World", kind="radio"),
    ])

    panel._filter("Radio")
    assert panel.filter_kind == "Radio"
    panel.bank_combo.setCurrentText("Markets")
    app.processEvents()

    assert panel.filter_kind == "All"
    for tile in panel.tiles:
        current = tile._current()
        assert current and current["group"] == "Markets"
        for index in range(tile.selector.count()):
            data = tile.selector.itemData(index) or {}
            if data:
                assert data["group"] == "Markets"
    panel.close()


def test_channel_change_never_autostarts_playback(app):
    panel = MediaPanel()
    panel.set_catalog([
        {
            "id": "one",
            "title": "One",
            "provider": "Synthetic",
            "type": "video",
            "group": "News",
            "region": "Global",
            "url": "https://www.youtube.com/watch?v=yDOkVG1uytM",
            "availability": "test",
            "rights": "test",
        },
        {
            "id": "two",
            "title": "Two",
            "provider": "Synthetic",
            "type": "video",
            "group": "News",
            "region": "Global",
            "url": "https://www.youtube.com/watch?v=Ap-UM1O9RBU",
            "availability": "test",
            "rights": "test",
        },
    ])
    tile = panel.tiles[0]
    assert tile.view is None
    tile.select_relative(1)
    assert tile.view is None
    assert "not connected" in tile.display.text().lower()
    panel.close()


def _radio(identity, receiver, frequency, mode):
    return {
        "id": identity,
        "title": identity.upper(),
        "name": identity.upper(),
        "provider": "Synthetic receiver",
        "type": "radio",
        "group": "World",
        "region": "Global",
        "url": f"https://example.com/{identity}",
        "availability": "synthetic tuned receiver",
        "rights": "test only",
        "receiver": receiver,
        "frequency": frequency,
        "mode": mode,
    }


def test_radio_presets_persist_receiver_frequency_mode_and_recall(app):
    settings = {}

    def get_setting(key, default=None):
        return settings.get(key, default)

    def set_setting(key, value):
        settings[key] = value

    panel = MediaPanel()
    panel.configure_radio_preferences(get_setting, set_setting)
    panel.set_catalog([
        _radio("station1", "rx-a", "101.7", "FM"),
        _radio("station2", "rx-b", "7.200", "LSB"),
    ])
    panel._filter("Radio")
    assert panel.tiles[0]._current()["id"] == "station1"

    assert panel.save_radio_preset(0)
    stored = settings["radio_presets"][0]
    assert stored["receiver"] == "rx-a"
    assert stored["frequency"] == "101.7"
    assert stored["mode"] == "FM"
    assert stored["name"] == "STATION1"

    panel.tiles[0].selector.setCurrentIndex(1)
    assert panel.recall_radio_preset(0)
    assert panel.tiles[0]._current()["id"] == "station1"
    assert panel.radio_manual_override
    assert not panel.radio_off_state
    panel.close()

    second = MediaPanel()
    second.configure_radio_preferences(get_setting, set_setting)
    second.set_catalog([
        _radio("station1", "rx-a", "101.7", "FM"),
        _radio("station2", "rx-b", "7.200", "LSB"),
    ])
    assert second.recall_radio_preset(0)
    assert second.tiles[0]._current()["id"] == "station1"
    second.close()


def test_radio_scan_fallback_scans_presets_not_fake_activity(app):
    panel = MediaPanel()
    settings = {
        "radio_presets": [
            {"receiver": "rx-a", "frequency": "101.7", "mode": "FM", "name": "One", "id": "station1", "url": "https://example.com/station1"},
            {"receiver": "rx-b", "frequency": "7.200", "mode": "LSB", "name": "Two", "id": "station2", "url": "https://example.com/station2"},
            None,
            None,
            None,
        ]
    }
    panel.configure_radio_preferences(lambda key, default=None: settings.get(key, default), lambda key, value: settings.__setitem__(key, value))
    panel.set_catalog([
        _radio("station1", "rx-a", "101.7", "FM"),
        _radio("station2", "rx-b", "7.200", "LSB"),
    ])
    panel._filter("Radio")
    assert panel.radio_scan_next.text() == "Scan presets ▶"
    assert panel._scan_radio_presets(1)
    assert panel.tiles[0]._current()["id"] == "station2"
    assert panel._scan_radio_presets(1)
    assert panel.tiles[0]._current()["id"] == "station1"
    panel.close()


def test_radio_off_and_manual_control_block_auto_tune_without_touching_presets(app):
    panel = MediaPanel()
    panel.set_catalog([
        _radio("station1", "rx-a", "101.7", "FM"),
        _radio("station2", "rx-b", "7.200", "LSB"),
    ])
    panel._filter("Radio")
    panel.radio_presets[0] = {
        "receiver": "rx-a",
        "frequency": "101.7",
        "mode": "FM",
        "name": "One",
        "id": "station1",
        "url": "https://example.com/station1",
    }
    original = [dict(item) if item else None for item in panel.radio_presets]

    panel.radio_off()
    assert panel.radio_off_state
    assert not panel.auto_tune_radio(_radio("station2", "rx-b", "7.200", "LSB"))

    panel.resume_auto_tune()
    assert not panel.radio_manual_override
    assert not panel.radio_off_state
    assert panel.auto_tune_radio(_radio("station2", "rx-b", "7.200", "LSB"))
    assert panel.radio_presets == original

    panel.hold_radio()
    assert panel.radio_manual_override
    assert not panel.auto_tune_radio(_radio("station1", "rx-a", "101.7", "FM"))
    assert panel.radio_presets == original
    panel.close()


def test_production_radio_station_creator_persists_and_recall_survives_restart(app):
    settings = {}

    def get_setting(key, default=None):
        return settings.get(key, default)

    def set_setting(key, value):
        settings[key] = value

    panel = MediaPanel()
    panel.configure_radio_preferences(get_setting, set_setting)
    assert panel.radio_add.text() == "Add station…"
    station = panel.add_radio_station(
        "Night receiver",
        "https://receiver.example.org/listen?f=7200&mode=lsb",
        "7.200 MHz",
        "LSB",
    )
    assert station["type"] == "radio"
    assert station["receiver"] == station["url"]
    assert station["frequency"] == "7.200 MHz"
    assert station["mode"] == "LSB"
    assert settings["radio_stations"][0]["id"] == station["id"]
    assert panel._same_station(panel._radio_current_item(), station)

    assert panel.save_radio_preset(0)
    saved_preset = dict(settings["radio_presets"][0])
    assert saved_preset["receiver"] == station["url"]
    panel.close()

    reopened = MediaPanel()
    reopened.configure_radio_preferences(get_setting, set_setting)
    assert len(reopened.radio_stations) == 1
    assert reopened.recall_radio_preset(0)
    assert reopened._same_station(reopened._radio_current_item(), saved_preset)
    assert reopened.radio_manual_override
    assert not reopened.radio_off_state
    reopened.close()


def test_production_station_watch_connects_exact_receiver_only_after_consent_and_off_disconnects(app, monkeypatch):
    loaded = []

    class DummyReceiverView:
        def __init__(self):
            self.stopped = 0
            self.blanked = []
            self.hidden = 0

        def load(self, url):
            loaded.append(url.toString())

        def show(self):
            pass

        def stop(self):
            self.stopped += 1

        def setUrl(self, url):
            self.blanked.append(url.toString())

        def hide(self):
            self.hidden += 1

    panel = MediaPanel()
    station = panel.add_radio_station(
        "Public receiver",
        "https://receiver.example.org/tune?freq=101.7&mode=fm",
        "101.7 MHz",
        "FM",
    )
    tile = panel.tiles[0]
    dummy = DummyReceiverView()

    def ensure_receiver(_url):
        tile.radio_view = dummy

    monkeypatch.setattr(tile, "_ensure_radio_player", ensure_receiver)
    monkeypatch.setattr(
        "global_pulse.media_widget.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        "global_pulse.media_widget.QDesktopServices.openUrl",
        lambda *args, **kwargs: pytest.fail("configured receiver Watch must stay in-app"),
    )

    assert loaded == []
    assert panel._same_station(tile._current(), station)
    tile.watch()
    assert loaded == [station["url"]]
    assert "Off disconnects" in tile.note.text()

    panel.radio_off()
    assert panel.radio_off_state
    assert dummy.stopped >= 1
    assert "about:blank" in dummy.blanked
    assert dummy.hidden >= 1
    panel.close()


def _raw_live_radio_report(identity, event_key, receiver, frequency, mode, *, synthetic=False):
    return {
        "id": identity,
        "source_id": "radio_source_" + identity,
        "publisher": "Radio source " + identity,
        "title": "Radio-linked event " + identity,
        "url": "https://news.example.org/" + identity,
        "retrieved_at": "2026-11-09T22:00:00Z",
        "published_at": "2026-11-09T21:00:00Z",
        "summary": "Current event with an explicitly linked public receiver.",
        "language": "en",
        "region": "Test region",
        "country": "Testland",
        "category": "News",
        "kind": "report",
        "origin_id": "origin-" + identity,
        "independence": "original",
        "event_key": event_key,
        "severity": "moderate",
        "claims": {},
        "official": False,
        "synthetic": synthetic,
        "retention_days": 30,
        "media": [{
            "url": receiver if not str(receiver).startswith("https://127.") else "https://public.example.org/radio",
            "title": "Event receiver " + identity,
            "name": "Event receiver " + identity,
            "provider": "Public receiver",
            "type": "radio",
            "receiver": receiver,
            "frequency": frequency,
            "mode": mode,
        }],
    }


def test_store_to_media_panel_radio_event_follow_end_to_end(app, tmp_path, monkeypatch):
    connections = []
    monkeypatch.setattr(
        "global_pulse.media_widget._MediaTile._connect_radio_receiver",
        lambda self, url: connections.append(url) or pytest.fail("event auto-follow must never open a receiver"),
    )

    with Store(tmp_path / "radio-live.sqlite3", mode="live") as store:
        first = store.ingest([_raw_live_radio_report(
            "one", "event:radio-one", "https://rx-one.example.org/tune?f=101.7", "101.7 MHz", "FM"
        )], now="2026-11-09T22:00:00Z")[0]
        second = store.ingest([_raw_live_radio_report(
            "two", "event:radio-two", "https://rx-two.example.org/tune?f=7200", "7.200 MHz", "LSB"
        )], now="2026-11-09T22:00:00Z")[0]

        assert first["media"][0]["receiver"] == "https://rx-one.example.org/tune?f=101.7"
        assert second["media"][0]["frequency"] == "7.200 MHz"

        settings = {}
        panel = MediaPanel()
        panel.configure_radio_preferences(
            lambda key, default=None: settings.get(key, default),
            lambda key, value: settings.__setitem__(key, value),
        )
        local = panel.add_radio_station(
            "Local preset",
            "https://local-preset.example.org/tune?f=900",
            "900 kHz",
            "AM",
        )
        assert panel.save_radio_preset(0)
        presets_before = [dict(item) if item else None for item in panel.radio_presets]

        # Resume is armed before event selection. Store-derived event selection
        # auto-selects the exact receiver identity but never opens a network session.
        panel.resume_auto_tune()
        panel.set_event(first)
        assert panel._same_station(panel._radio_current_item(), first["media"][0])
        assert "Auto-tuned for selected event" in panel.radio_status.text()
        assert panel.radio_presets == presets_before
        assert connections == []

        # Manual Hold wins even when a different Store-derived event is selected.
        panel.hold_radio()
        panel.set_event(second)
        assert panel._same_station(panel._radio_current_item(), first["media"][0])
        assert panel.radio_presets == presets_before
        assert connections == []

        # Off disconnects/clears the active route and later event selection cannot reactivate it.
        panel.radio_off()
        panel.set_event(second)
        assert panel.radio_off_state
        assert panel._active_radio_tile is None
        assert panel.radio_presets == presets_before
        assert connections == []

        # Resume on the current real event selects its explicit station immediately.
        panel.resume_auto_tune()
        assert panel._same_station(panel._radio_current_item(), second["media"][0])
        assert panel.radio_presets == presets_before
        assert connections == []

        # Historical projection never invokes event auto-follow.
        calls = []
        original_auto = panel.auto_tune_radio
        monkeypatch.setattr(panel, "auto_tune_radio", lambda item: calls.append(item) or original_auto(item))
        historical = dict(first, historical_view=True)
        panel.set_event(historical)
        assert calls == []

        # A private receiver is rejected at Store normalization even if its display URL is public.
        unsafe = store.ingest([_raw_live_radio_report(
            "unsafe", "event:radio-unsafe", "https://127.0.0.1/private", "1000 kHz", "AM"
        )], now="2026-11-09T22:00:00Z")[0]
        assert unsafe["media"] == []
        panel.close()

    with Store(tmp_path / "radio-synthetic.sqlite3", mode="synthetic") as synthetic_store:
        synthetic = synthetic_store.ingest([_raw_live_radio_report(
            "synthetic", "event:radio-synthetic", "https://rx-synthetic.example.org/tune", "1200 kHz", "AM",
            synthetic=True,
        )], now="2026-11-09T22:00:00Z")[0]
        panel = MediaPanel()
        panel.resume_auto_tune()
        synthetic_calls = []
        monkeypatch.setattr(panel, "auto_tune_radio", lambda item: synthetic_calls.append(item) or True)
        panel.set_event(synthetic)
        assert synthetic_calls == []
        assert connections == []
        panel.close()


def test_event_station_preset_is_self_contained_across_restart(app, tmp_path):
    settings = {}
    with Store(tmp_path / "radio-preset-live.sqlite3", mode="live") as store:
        event_row = store.ingest([_raw_live_radio_report(
            "preset-source", "event:radio-preset", "https://event-preset.example.org/tune?f=650", "650 kHz", "AM"
        )], now="2026-11-09T22:00:00Z")[0]

    panel = MediaPanel()
    panel.configure_radio_preferences(
        lambda key, default=None: settings.get(key, default),
        lambda key, value: settings.__setitem__(key, value),
    )
    panel.resume_auto_tune()
    panel.set_event(event_row)
    assert panel.save_radio_preset(2)
    saved = dict(settings["radio_presets"][2])
    assert saved["receiver"] == "https://event-preset.example.org/tune?f=650"
    assert settings.get("radio_stations", []) == []
    panel.close()

    reopened = MediaPanel()
    reopened.configure_radio_preferences(
        lambda key, default=None: settings.get(key, default),
        lambda key, value: settings.__setitem__(key, value),
    )
    assert reopened.media == []
    assert reopened.radio_stations == []
    assert reopened.recall_radio_preset(2)
    assert reopened._same_station(reopened._radio_current_item(), saved)
    assert reopened.radio_manual_override
    assert not reopened.radio_off_state
    reopened.close()


def test_user_can_link_real_station_to_event_and_resume_after_restart(app):
    settings = {}

    def get_setting(key, default=None):
        return settings.get(key, default)

    def set_setting(key, value):
        settings[key] = value

    panel = MediaPanel()
    panel.configure_radio_preferences(get_setting, set_setting)
    station = panel.add_radio_station(
        "Bound station",
        "https://bound-rx.example.org/tune?f=550&mode=am",
        "550 kHz",
        "AM",
    )
    event = {"id": "event:local-binding", "media": [], "reports": []}
    panel.set_event(event)
    assert panel.radio_link_event.isEnabled()
    assert panel.radio_link_event.text() == "Link event"
    assert panel.toggle_event_radio_binding()
    assert panel.radio_link_event.text() == "Unlink event"
    assert settings["radio_event_bindings"]["event:local-binding"]["frequency"] == "550 kHz"
    assert panel.radio_manual_override
    panel.close()

    reopened = MediaPanel()
    reopened.configure_radio_preferences(get_setting, set_setting)
    reopened.set_event(event)
    assert reopened.radio_link_event.text() == "Unlink event"
    # Startup remains Off: selecting the event alone cannot open/reactivate radio.
    assert reopened.radio_off_state
    assert reopened.resume_auto_tune()
    assert not reopened.radio_off_state
    assert not reopened.radio_manual_override
    assert reopened._same_station(reopened._radio_current_item(), station)
    assert "Auto-tuned for selected event" in reopened.radio_status.text()

    # Toggle removes the persistent association and retains manual priority.
    assert reopened.toggle_event_radio_binding()
    assert reopened.radio_link_event.text() == "Link event"
    assert "event:local-binding" not in settings["radio_event_bindings"]
    assert reopened.radio_manual_override
    reopened.close()


def test_event_binding_rejects_directory_historical_and_synthetic_contexts(app):
    panel = MediaPanel()
    panel.configure_radio_preferences(lambda key, default=None: default, lambda key, value: None)
    panel.set_catalog([
        {
            "id": "directory",
            "title": "Receiver directory",
            "provider": "Directory",
            "type": "radio",
            "group": "World",
            "region": "Global",
            "url": "https://example.com/directory",
            "availability": "directory only",
            "rights": "test only",
        }
    ])
    panel._filter("Radio")
    panel.set_event({"id": "event:directory", "media": [], "reports": []})
    assert not panel.toggle_event_radio_binding()
    assert panel.radio_event_bindings == {}

    panel.set_event({"id": "event:history", "media": [], "reports": [], "historical_view": True})
    assert not panel.radio_link_event.isEnabled()
    assert not panel.toggle_event_radio_binding()

    panel.set_event({"id": "event:synthetic", "media": [], "reports": [], "synthetic": True})
    assert not panel.radio_link_event.isEnabled()
    assert not panel.toggle_event_radio_binding()
    panel.close()


def test_event_selection_drives_production_auto_tune_but_hold_and_off_win(app):
    settings = {}
    panel = MediaPanel()
    panel.configure_radio_preferences(
        lambda key, default=None: settings.get(key, default),
        lambda key, value: settings.__setitem__(key, value),
    )
    one = panel.add_radio_station(
        "Station one",
        "https://rx-one.example.org/listen?f=101.7",
        "101.7 MHz",
        "FM",
    )
    two = panel.add_radio_station(
        "Station two",
        "https://rx-two.example.org/listen?f=7200",
        "7.200 MHz",
        "LSB",
    )
    assert panel.save_radio_preset(0)
    presets_before = [dict(item) if item else None for item in panel.radio_presets]

    # Resume arms the real event path. Selecting an event with an explicit
    # production-shaped station record tunes that exact station.
    panel.resume_auto_tune()
    panel.set_event({"id": "event-one", "media": [one], "reports": []})
    assert panel._same_station(panel._radio_current_item(), one)
    assert "Auto-tuned for selected event" in panel.radio_status.text()
    assert panel.radio_presets == presets_before

    # Hold gives manual control priority over later event selection.
    panel.hold_radio()
    panel.set_event({"id": "event-two", "media": [two], "reports": []})
    assert panel._same_station(panel._radio_current_item(), one)
    assert panel.radio_presets == presets_before

    # Off clears the active auto-tune target and cannot be reactivated by an event.
    panel.radio_off()
    assert panel.radio_off_state
    panel.set_event({"id": "event-two-again", "media": [two], "reports": []})
    assert panel.radio_off_state
    assert panel._active_radio_tile is None
    assert panel.radio_presets == presets_before

    # Resume on the currently selected event immediately uses its explicit station.
    panel.resume_auto_tune()
    assert panel._same_station(panel._radio_current_item(), two)
    assert panel.radio_presets == presets_before
    panel.close()


def test_hold_preserves_transient_event_station_without_network_open(app, monkeypatch):
    opened = []
    monkeypatch.setattr(
        "global_pulse.media_widget.QDesktopServices.openUrl",
        lambda url: opened.append(url.toString()) or True,
    )
    panel = MediaPanel()
    one = panel._normalize_radio_station({
        "name": "Event station one",
        "url": "https://event-rx-one.example.org/tune?f=1000",
        "frequency": "1000 kHz",
        "mode": "AM",
    })
    two = panel._normalize_radio_station({
        "name": "Event station two",
        "url": "https://event-rx-two.example.org/tune?f=2000",
        "frequency": "2000 kHz",
        "mode": "AM",
    })

    panel.resume_auto_tune()
    panel.set_event({"id": "one", "media": [one], "reports": []})
    assert panel._same_station(panel._radio_current_item(), one)
    assert opened == []

    panel.hold_radio()
    panel.set_event({"id": "two", "media": [two], "reports": []})
    assert panel._same_station(panel._radio_current_item(), one)
    assert opened == []
    panel.close()


def test_event_follow_never_guesses_directory_or_historical_radio(app):
    panel = MediaPanel()
    configured = panel.add_radio_station(
        "Configured",
        "https://receiver.example.org/listen?f=900",
        "900 kHz",
        "AM",
    )
    panel.resume_auto_tune()

    directory = {
        "id": "directory",
        "title": "Receiver directory",
        "provider": "Directory",
        "type": "radio",
        "group": "World",
        "region": "Global",
        "url": "https://example.com/directory",
        "availability": "directory only",
        "rights": "test only",
    }
    panel.set_event({"id": "directory-event", "media": [directory], "reports": []})
    assert not panel._same_station(panel._radio_current_item(), directory)

    panel.set_event({
        "id": "historical-event",
        "media": [configured],
        "reports": [],
        "historical_view": True,
    })
    # Historical views may display the station but never initiate auto-tune.
    assert "Auto-tuned for selected event" not in panel.radio_status.text()
    panel.close()


def test_user_radio_station_rejects_nonpublic_or_incomplete_receiver_identity(app):
    panel = MediaPanel()
    with pytest.raises(ValueError):
        panel.add_radio_station("Local", "https://127.0.0.1/radio", "101.7", "FM")
    with pytest.raises(ValueError):
        panel.add_radio_station("Missing frequency", "https://receiver.example.org/", "", "FM")
    with pytest.raises(ValueError):
        panel.add_radio_station("Missing mode", "https://receiver.example.org/", "101.7", "")
    assert panel.radio_stations == []
    panel.close()


def test_directory_radio_cannot_be_saved_as_fake_tuned_station(app):
    panel = MediaPanel()
    panel.set_catalog([
        {
            "id": "directory",
            "title": "Receiver directory",
            "provider": "Directory",
            "type": "radio",
            "group": "World",
            "region": "Global",
            "url": "https://example.com/directory",
            "availability": "directory only",
            "rights": "test only",
        }
    ])
    panel._filter("Radio")
    assert not panel.save_radio_preset(0)
    assert panel.radio_presets[0] is None
    assert "receiver/frequency/mode" in panel.radio_status.text()
    panel.close()
