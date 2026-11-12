"""Canonical language identities for reviewed local English translation packs.

Script variants are not interchangeable. In particular, traditional Chinese is
kept separate from simplified Chinese; unknown/mixed language is never English.
"""
from __future__ import annotations
import re

ALIASES = {'eng':'en','fra':'fr','fre':'fr','deu':'de','ger':'de','spa':'es','por':'pt','zho':'zh','chi':'zh','jpn':'ja','kor':'ko','rus':'ru','ukr':'uk','ara':'ar','fas':'fa','per':'fa','hin':'hi','ben':'bn','nld':'nl','dut':'nl','pol':'pl','tur':'tr','ces':'cs','cze':'cs','ell':'el','gre':'el','ron':'ro','rum':'ro','heb':'he','ind':'id','vie':'vi','swe':'sv','dan':'da','fin':'fi','ita':'it','hun':'hu','slk':'sk','slo':'sk','fil':'tl','iw':'he','in':'id','no':'nb'}

def normalize_language(value: object) -> str:
    text = str(value or '').strip().lower().replace('_','-')
    # Keep an explicit script authoritative, then preserve traditional-region
    # routing across optional BCP-47 variant/private-use/Unicode extensions.
    # In particular, zh-TW-x-... and zh-HK-u-... must not fall back to zh.
    subtags = text.split('-')
    if text == 'zht' or (len(subtags) >= 2 and subtags[0] == 'zh' and
                          subtags[1] in {'hant', 'tw', 'hk'}):
        return 'zt'
    if text == 'zhs':
        return 'zh'
    code = text.split('-')[0]
    if not re.fullmatch('[a-z]{2,3}',code) or code in {'und','mul','zxx'}:
        return 'und'
    return ALIASES.get(code,code)

def translation_coverage(languages, catalog, installed=None):
    """Describe real coverage without downloading a model or inventing support."""
    result = {}
    for raw in languages:
        code = normalize_language(raw)
        if code == 'en':
            state='original_english'
        elif code == 'und':
            state='language_unknown'
        elif code not in catalog:
            state='model_unavailable'
        elif installed is None or not installed(code):
            state='model_install_required'
        else:
            state='local_model_ready'
        result[str(raw)]={'language':code,'state':state}
    return result
