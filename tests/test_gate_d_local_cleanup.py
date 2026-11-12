from pathlib import Path

import pytest

from global_pulse.controller import Controller
from global_pulse.translation import Translator


def test_remove_user_feed_clears_config_checkpoint_but_keeps_history(tmp_path):
    controller=Controller(tmp_path,demo=True)
    try:
        controller.add_user_feed("https://example.com/feed.xml","Example Feed")
        source=next(item for item in controller.catalog if item.get("access_status")=="user_supplied")
        source_id=source["id"]
        controller.store.set_source_state(source_id,{"status":"available","etag":"abc"})
        controller.store.set_setting("enabled_sources",[source_id])
        controller.store.set_setting("muted_sources",[source_id])
        controller.store.ingest([{
            "source_id":source_id,"publisher":"Example Feed","id":"item-1",
            "url":"https://example.com/story","title":"Example retained history",
            "summary":"A locally retained historical item.","published_at":"2026-11-10T10:00:00Z",
            "retrieved_at":"2026-11-10T10:00:00Z","category":"News","region":"Global",
            "independence":"unknown","retention_days":30,"synthetic":True,
        }],now="2026-11-10T10:00:00Z")
        before=controller.store.stats()["reports"]
        assert controller.remove_user_feed(source_id)
        assert source_id not in {item["id"] for item in controller.catalog}
        assert controller.store.get_setting("user_feeds",[])==[]
        assert source_id not in controller.store.get_setting("enabled_sources",[])
        assert source_id not in controller.store.get_setting("muted_sources",[])
        assert controller.store.get_source_state(source_id)=={}
        assert controller.store.stats()["reports"]==before
    finally:
        controller.close()


def test_remove_user_feed_refuses_builtin_source(tmp_path):
    controller=Controller(tmp_path,demo=True)
    try:
        builtin=next(item for item in controller.catalog if item.get("access_status")!="user_supplied")
        with pytest.raises(ValueError,match="user-configured"):
            controller.remove_user_feed(builtin["id"])
    finally:
        controller.close()


def _model_dir(translator,code):
    item=translator.catalog[code]
    path=translator.root/item["key"]
    path.mkdir(parents=True)
    (path/"marker.txt").write_text("model")
    return path


def test_translator_remove_deletes_only_selected_reviewed_model(tmp_path):
    translator=Translator(tmp_path)
    codes=list(translator.catalog)[:2]
    first=_model_dir(translator,codes[0]);second=_model_dir(translator,codes[1])
    assert translator.remove(codes[0])
    assert not first.exists()
    assert second.exists()


def test_translator_remove_refuses_redirected_or_escaped_model_path(tmp_path):
    translator=Translator(tmp_path)
    outside=tmp_path/"outside";outside.mkdir()
    translator.catalog["bad"]={"key":"../outside","sha256":"x"}
    with pytest.raises(ValueError,match="path"):
        translator.remove("bad")


def test_controller_refuses_model_removal_while_download_is_active(tmp_path):
    controller=Controller(tmp_path,demo=True)
    try:
        code=next(iter(controller.translator.catalog))
        path=_model_dir(controller.translator,code)
        controller._model_jobs["model-download:test"]=code
        assert controller.remove_translation_model(code) is False
        assert path.exists()
    finally:
        controller.close()


def test_cleanup_controls_are_present_in_ui_sources():
    root=Path(__file__).parents[1]
    ui=(root/"global_pulse"/"ui.py").read_text(encoding="utf-8")
    manager=(root/"global_pulse"/"model_manager.py").read_text(encoding="utf-8")
    assert "Remove selected custom feed" in ui
    assert "Remove local model" in manager
