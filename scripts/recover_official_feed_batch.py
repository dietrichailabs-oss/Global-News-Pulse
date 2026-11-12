"""Recover catalog publication from the completed live audit; NO feed requests.

The original job passed its audit, then failed git diff --check because its JSON
writer emitted CRLF on Windows. Receipts below are transcribed from that job log,
not claimed to be a recovered original live-check.json or a new network audit.
"""
from __future__ import annotations
import ast
import copy
import json
from pathlib import Path
import re
import subprocess

AUDITED_SOURCE = '0975d2f774084f04aae02c54c17335fa6b07bc6c'
RECOVERY_PATH = Path('docs/engineering/GP-OFFICIAL-FEEDS-20261111/audit-log-recovery.json')


def admitted_from_receipts(document, proposals):
    if not isinstance(document, dict) or document.get('original_run_id') != 43036773337 or document.get('original_job_id') != 130577540369:
        raise ValueError('Wrong original audit identity')
    if document.get('original_source') != AUDITED_SOURCE or document.get('recovery_kind') != 'transcribed_completed_job_log_receipts':
        raise ValueError('Wrong receipt provenance')
    receipts = document.get('sources')
    expected = {row['id']: row for row in proposals}
    if not isinstance(receipts, list) or len(receipts) != len(expected):
        raise ValueError('Incomplete receipt set')
    seen, admitted = set(), []
    for receipt in receipts:
        if not isinstance(receipt, dict) or receipt.get('id') not in expected or receipt['id'] in seen:
            raise ValueError('Duplicate or unknown receipt')
        sid = receipt['id']; seen.add(sid); proposal = expected[sid]
        if receipt.get('feed_url') != proposal['url'] or receipt.get('article_fetches') != 0:
            raise ValueError('Receipt endpoint/scope mismatch')
        if receipt.get('status') != 'collector_store_pass':
            continue
        if (receipt.get('http_status') != 200 or receipt.get('collector_status') != 'available'
                or receipt.get('sqlite_reopen_verified') is not True
                or not isinstance(receipt.get('current_linked_reports'), int)
                or receipt['current_linked_reports'] <= 0
                or not isinstance(receipt.get('stored_report_ids'), int)
                or receipt['stored_report_ids'] < receipt['current_linked_reports']
                or not re.fullmatch(r'[0-9a-f]{64}', str(receipt.get('parsed_identity_sha256', '')))):
            raise ValueError('Insufficient successful collector/store evidence')
        admitted.append(copy.deepcopy(proposal))
    if {row['id'] for row in admitted} != {'bls_latest', 'un_geneva'}:
        raise ValueError('Admission differs from the original audited outcome')
    return admitted


def repair_writer():
    path = Path('scripts/official_feed_batch.py')
    expected = subprocess.check_output(['git', 'show', AUDITED_SOURCE+':'+path.as_posix()])
    if path.read_bytes() != expected:
        raise RuntimeError('Audit writer changed; reconcile before patching')
    original = expected.decode('utf-8')
    old = "temporary.write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\\n',encoding='utf-8')"
    new = "temporary.write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\\n',encoding='utf-8',newline='\\n')"
    if original.count(old) != 1:
        raise RuntimeError('JSON writer anchor mismatch')
    corrected = original.replace(old, new, 1)
    ast.parse(corrected)
    path.write_text(corrected, encoding='utf-8', newline='\n')


def recover():
    repair_writer()
    from scripts.official_feed_batch import BASE, CATALOG, OUT, candidates, atomic_json
    raw = subprocess.check_output(['git', 'show', BASE+':'+CATALOG.as_posix()])
    if CATALOG.read_bytes() != raw:
        raise RuntimeError('Catalog changed; refuse to overwrite concurrent work')
    document = json.loads(RECOVERY_PATH.read_text(encoding='utf-8'))
    accepted = admitted_from_receipts(document, candidates())
    catalog = json.loads(raw)
    existing_ids = {row['id'] for row in catalog['sources']}
    existing_urls = {row['url'] for row in catalog['sources']}
    if any(row['id'] in existing_ids or row['url'] in existing_urls for row in accepted):
        raise RuntimeError('Recovered addition duplicates an existing source')
    report = dict(baseline=BASE, complete=True, attempted=len(document['sources']),
        admitted_ids=[row['id'] for row in accepted], admitted_count=len(accepted),
        sources=document['sources'], receipt_provenance=document['recovery_kind'],
        original_run_id=document['original_run_id'], original_job_id=document['original_job_id'],
        original_audited_source=AUDITED_SOURCE, new_provider_requests=0,
        zero_throttle_guarantee=False, sustained_reliability_verified=False,
        packaged_windows_verified=False,
        limits='Completed live Collector/Store results recovered from original job log. No original receipt-file hash claimed. Publication regenerated offline; full regression and independent QA are separate.')
    catalog['sources'].extend(accepted)
    catalog['catalog_version'] = '2026.11.11.official1'
    catalog['reviewed_at'] = '2026-11-11'
    atomic_json(CATALOG, catalog)
    atomic_json(OUT/'live-check.json', report)
    if b'\r' in CATALOG.read_bytes() or b'\r' in (OUT/'live-check.json').read_bytes():
        raise RuntimeError('Recovered JSON is not canonical LF')
    print('GP_OFFICIAL_RECOVERED_WITHOUT_NETWORK', ','.join(report['admitted_ids']), flush=True)


if __name__ == '__main__':
    recover()
