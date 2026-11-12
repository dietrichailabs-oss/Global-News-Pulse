"""Owned translation child, bounded private JSON files, no GUI or database.

The parent obtains download consent. Catalog entries are the only permitted
models/URLs. File IPC also works with Windows windowed (no-console) executables.
A process boundary controls lifetime; it is not an OS security sandbox.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

MAX_INPUT = 32768
MAX_OUTPUT = 65536


def main(argv=None):
    from global_pulse.translation import Translator
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] != "--job":
        return 2
    work = Path(args[1])
    if work.is_symlink() or not work.name.startswith("job-") or work.parent.name != "translation-jobs":
        return 2
    work = work.resolve(strict=True)
    request = work / "request.json"
    if request.is_symlink():
        return 2
    try:
        with request.open("rb") as source:
            raw = source.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError("Translation request too large")
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {"data_dir", "work_dir", "language", "text", "install"}:
            raise ValueError("Invalid translation request")
        text, code = value["text"], value["language"]
        if not isinstance(text, str) or len(text) > 4000 or not isinstance(code, str) or type(value["install"]) is not bool:
            raise ValueError("Invalid translation request fields")
        data = Path(value["data_dir"]).resolve(strict=True)
        if Path(value["work_dir"]).resolve(strict=True) != work or work.parent != data / "translation-jobs":
            raise ValueError("Invalid translation work directory")
        translator = Translator(data, work_dir=work)
        if code not in translator.catalog:
            raise ValueError("Unsupported reviewed model")
        if value["install"]:
            def progress(received, total):
                pending = work / "progress.tmp"
                pending.write_text(json.dumps({"received": received, "total": total}), encoding="utf-8")
                pending.replace(work / "progress.json")
            translator.download(code, progress=progress)
        result = {"text": translator.translate(text, code) if text.strip() else "", "error": ""}
    except Exception as exc:
        result = {"text": "", "error": type(exc).__name__}
    encoded = json.dumps(result, ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_OUTPUT:
        result = {"text": "", "error": "Translation output exceeds limit"}
        encoded = json.dumps(result).encode("utf-8")
    temporary = work / "response.tmp"
    with temporary.open("xb") as target:
        target.write(encoded)
        target.flush()
        os.fsync(target.fileno())
    temporary.replace(work / "response.json")
    return 0 if not result["error"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
