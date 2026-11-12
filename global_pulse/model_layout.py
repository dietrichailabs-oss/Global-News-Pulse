"""Recognize explicitly cataloged legacy CT2 assets without fabricating config.

Archive pinning/extraction and every-file verification before inference remain
Translator responsibilities. This helper checks only the declared file layout.
"""
from pathlib import Path
import re

LEGACY = 'legacy_ct2_text_vocabulary'


def model_layout_complete(path: Path, item: dict, receipt: dict) -> bool:
    layout = item.get('model_layout', 'modern')
    if layout == 'modern':
        return all((path / name).is_file() for name in ('model/model.bin', 'model/config.json')) and any(
            (path / name).is_file() for name in ('sentencepiece.model', 'bpe.model'))
    if layout != LEGACY or not isinstance(receipt, dict):
        return False
    files = receipt.get('files')
    if not isinstance(files, dict) or path.is_symlink() or (path / 'model/config.json').exists():
        return False
    root = path.resolve()

    def reviewed_file(name: str) -> bool:
        candidate = path / name
        digest = files.get(name)
        return (isinstance(digest, str) and re.fullmatch(r'[a-f0-9]{64}', digest) is not None
                and candidate.is_file() and not candidate.is_symlink()
                and candidate.resolve().is_relative_to(root))

    vocabulary = reviewed_file('model/shared_vocabulary.txt') or all(
        reviewed_file(name) for name in ('model/source_vocabulary.txt', 'model/target_vocabulary.txt'))
    tokenizer = any(reviewed_file(name) for name in ('sentencepiece.model', 'bpe.model'))
    return reviewed_file('model/model.bin') and vocabulary and tokenizer
