"""Bounded offline translation using explicitly installed, pinned model files.

The inference path never contacts a server. Model downloads need a separate,
explicit consent action in the controller. Only SentencePiece + CTranslate2
assets are extracted; embedded Python/PyTorch/Stanza files are not loaded.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import zipfile
from pathlib import Path, PurePosixPath

import httpx

from .language_codes import normalize_language
from .model_layout import model_layout_complete


class TranslationUnavailable(RuntimeError):
    pass


def language_of(text, declared=""):
    code = normalize_language(declared)
    if code and code not in {"und", "unknown", "auto"}:
        return code
    if len(text.strip()) < 30:
        return "und"
    try:
        from langdetect import DetectorFactory, detect_langs
        DetectorFactory.seed = 0
        guesses = detect_langs(text[:3000])
        return normalize_language(guesses[0].lang) if guesses and guesses[0].prob > 0.85 else "und"
    except Exception:
        return "und"


class Translator:
    def __init__(self, data_dir, *, work_dir=None):
        self.root = Path(data_dir) / "models"
        self.root.mkdir(parents=True, exist_ok=True)
        self.work_root = Path(work_dir) if work_dir is not None else self.root
        catalog_path = Path(__file__).with_name("resources") / "translation_models.json"
        self.catalog = json.loads(catalog_path.read_text()) if catalog_path.exists() else {}
        self._cache = {}
        self._lock = threading.Lock()
        self.cancelled = threading.Event()

    def installed(self, code):
        item = self.catalog.get(code)
        if not item:
            return False
        path = self.root / item["key"]
        try:
            receipt = json.loads((path / "receipt.json").read_text())
            return receipt.get("archive_sha256") == item["sha256"] and model_layout_complete(path, item, receipt)
        except (OSError, ValueError):
            return False

    def remove(self, code):
        item = self.catalog.get(code)
        if not item:
            raise ValueError("Unknown reviewed translation model")
        key = Path(str(item.get("key", "")))
        if key.is_absolute() or len(key.parts) != 1 or key.name in {"", ".", ".."}:
            raise ValueError("Reviewed model path is invalid")
        root = self.root.resolve()
        path = self.root / key.name
        if path.is_symlink():
            raise ValueError("Reviewed model directory must not be a symbolic link")
        if path.parent.resolve() != root:
            raise ValueError("Reviewed model path escaped the model root")
        with self._lock:
            self._cache.pop(code, None)
            if not path.exists():
                return False
            if not path.is_dir():
                raise ValueError("Reviewed model path is not a directory")
            shutil.rmtree(path)
            return True

    def download(self, code, progress=None):
        item = self.catalog.get(code)
        if not item:
            raise TranslationUnavailable("No reviewed offline model is available for this language")
        if self.cancelled.is_set():
            raise TranslationUnavailable("Translation stopped")
        fd, name = tempfile.mkstemp(suffix=".argosmodel", dir=self.work_root)
        os.close(fd)
        try:
            with httpx.Client(timeout=httpx.Timeout(15, connect=10), follow_redirects=False) as client:
                with client.stream("GET", item["url"], headers={"User-Agent": "GlobalPulse/0.1 (consented language model download)", "Accept-Encoding": "identity"}) as response:
                    response.raise_for_status()
                    if response.headers.get("content-encoding", "identity").lower() not in {"identity", ""}:
                        raise ValueError("Unexpected compressed model response")
                    total = 0
                    with open(name, "wb") as target:
                        for chunk in response.iter_raw(65536):
                            if self.cancelled.is_set():
                                raise TranslationUnavailable("Translation download cancelled")
                            total += len(chunk)
                            if total > item["size_bytes"]:
                                raise ValueError("Model download exceeds reviewed size")
                            target.write(chunk)
                            if progress:
                                progress(total, item["size_bytes"])
            self.install_archive(name, code)
        finally:
            Path(name).unlink(missing_ok=True)

    def install_archive(self, archive, code):
        item = self.catalog[code]
        archive = Path(archive)
        if archive.stat().st_size != item["size_bytes"]:
            raise ValueError("Unexpected model archive size")
        with archive.open("rb") as file:
            digest = hashlib.file_digest(file, "sha256").hexdigest()
        if digest != item["sha256"]:
            raise ValueError("Model integrity check failed")
        staging = Path(tempfile.mkdtemp(prefix=".install-", dir=self.work_root))
        destination = self.root / item["key"]
        try:
            total = 0
            hashes = {}
            with zipfile.ZipFile(archive) as bundle:
                if len(bundle.infolist()) > 200:
                    raise ValueError("Too many model archive entries")
                for info in bundle.infolist():
                    parts = PurePosixPath(info.filename).parts
                    if not parts or info.is_dir():
                        continue
                    if ".." in parts or info.filename.startswith(("/", "\\")) or "\\" in info.filename:
                        raise ValueError("Invalid archive path")
                    relative = PurePosixPath(*parts[1:])
                    name = str(relative)
                    allowed = name in {"sentencepiece.model", "bpe.model", "metadata.json", "README.md"} or (name.startswith("model/") and relative.suffix in {".json", ".bin", ".txt"})
                    if not allowed:
                        continue
                    if ((info.external_attr >> 16) & 0o170000) == 0o120000:
                        raise ValueError("Model archive symbolic links are not permitted")
                    total += info.file_size
                    if total > 600_000_000 or info.file_size > 550_000_000:
                        raise ValueError("Expanded model exceeds the safety limit")
                    target = staging / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(info) as source, target.open("wb") as out:
                        shutil.copyfileobj(source, out, length=65536)
                    with target.open("rb") as check:
                        hashes[name] = hashlib.file_digest(check, "sha256").hexdigest()
            metadata = json.loads((staging / "metadata.json").read_text())
            if metadata.get("from_code") != code or metadata.get("to_code") != "en":
                raise ValueError("Unexpected language model metadata")
            (staging / "receipt.json").write_text(json.dumps({"archive_sha256": digest, "files": hashes}, indent=2))
            if destination.exists():
                # Only replace this reviewed model directory, never the model root.
                shutil.rmtree(destination)
            staging.rename(destination)
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def translate(self, text, code):
        text = str(text).strip()
        if len(text) > 4000:
            raise ValueError("Translate the available headline and excerpt, up to 4,000 characters")
        if code == "en":
            return text
        if not self.installed(code):
            raise TranslationUnavailable("Install the reviewed offline language model first")
        if self.cancelled.is_set():
            raise TranslationUnavailable("Translation stopped")
        import ctranslate2
        import sentencepiece
        with self._lock:
            if code not in self._cache:
                if len(self._cache) >= 2:
                    self._cache.pop(next(iter(self._cache)))
                path = self.root / self.catalog[code]["key"]
                receipt = json.loads((path / "receipt.json").read_text())
                for name, expected in receipt["files"].items():
                    relative = PurePosixPath(name)
                    if relative.is_absolute() or ".." in relative.parts or "\\" in name or not (path / name).resolve().is_relative_to(path.resolve()):
                        raise ValueError("Invalid installed model receipt path")
                    with (path / name).open("rb") as check:
                        if hashlib.file_digest(check, "sha256").hexdigest() != expected:
                            raise ValueError("Installed model integrity check failed")
                tokenizer = _BPETokenizer(path / "bpe.model", code) if (path / "bpe.model").exists() else _SentencePieceTokenizer(path / "sentencepiece.model")
                model = ctranslate2.Translator(str(path / "model"), device="cpu", compute_type="int8", inter_threads=1, intra_threads=2)
                self._cache[code] = (tokenizer, model)
            tokenizer, model = self._cache[code]
            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
            tokens = [tokenizer.encode(s) for s in sentences]
            if any(len(t) > 512 for t in tokens) or len(tokens) > 40:
                raise ValueError("Excerpt is too long for the reviewed translation limit")
            results = model.translate_batch(tokens, beam_size=2, max_batch_size=4, max_input_length=512, max_decoding_length=512)
            return " ".join(tokenizer.decode(r.hypotheses[0]) for r in results)


class _SentencePieceTokenizer:
    def __init__(self, path):
        import sentencepiece
        self.processor = sentencepiece.SentencePieceProcessor(model_file=str(path))

    def encode(self, text):
        return self.processor.encode(text, out_type=str)

    def decode(self, tokens):
        # Some Argos target vocabularies contain pieces absent from the source
        # tokenizer; preserve byte fallback decoding and normalize residual
        # SentencePiece word-boundary symbols only (not ordinary underscores).
        return self.processor.decode_pieces(tokens).replace("▁", " ").strip()


class _BPETokenizer:
    def __init__(self, path, code):
        from sacremoses import MosesTokenizer, MosesDetokenizer, MosesPunctNormalizer
        from subword_nmt.apply_bpe import BPE
        self.normalizer = MosesPunctNormalizer(lang=code)
        self.tokenizer = MosesTokenizer(lang=code)
        self.detokenizer = MosesDetokenizer(lang="en")
        with Path(path).open(encoding="utf-8") as stream:
            self.bpe = BPE(stream)

    def encode(self, text):
        words = self.tokenizer.tokenize(self.normalizer.normalize(text))
        return self.bpe.segment_tokens(words)

    def decode(self, tokens):
        return self.detokenizer.detokenize(" ".join(tokens).replace("@@ ", "").split())
