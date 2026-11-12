"""Losslessly encode the pinned unrtf output as UTF-8; retain both originals.

Only a derived readable text file is normalized. Microsoft's original RTF is
unchanged and authoritative. Unknown input bytes or lossy decoding are rejected.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/'docs/engineering/GP-ENG-FREEWARE-COMPLIANCE-001/upstream'
RTF_SHA='dd07eb178e00c6bba4148457fc00ff77cd4887eb521d504186fe59c9ec8bbe62'
RAW_SHA='c032b983c970a58fe1ccfde3d3bbd1bf45f5bcbc13ea9225451c9b7c99811208'


def sha(data):return hashlib.sha256(data).hexdigest()


def convert(data, expected=RAW_SHA):
    if sha(data)!=expected:raise ValueError('Unreviewed unrtf output')
    text=data.decode('cp1252',errors='strict')
    if text.encode('cp1252',errors='strict')!=data:raise ValueError('Lossy license conversion')
    return text.encode('utf-8')


def main():
    if sha((ROOT/'windows-sdk-license.rtf').read_bytes())!=RTF_SHA:
        raise ValueError('Original Microsoft license changed')
    target=ROOT/'windows-sdk-license-converted.txt'
    receipt_path=ROOT/'windows-sdk-conversion.json'
    backup=ROOT/'windows-sdk-license-unrtf-original.bin'
    receipt=json.loads(receipt_path.read_text())
    data=target.read_bytes()
    if sha(data)!=RAW_SHA:
        if (receipt.get('normalization')=='lossless-cp1252-to-utf8'
                and receipt.get('output_sha256')==sha(data) and backup.is_file()
                and sha(backup.read_bytes())==RAW_SHA
                and convert(backup.read_bytes())==data):
            print('SDK readable text already verified UTF-8; original RTF and unrtf bytes unchanged.')
            return
        raise ValueError('Unknown normalized license state')
    if receipt.get('input_sha256')!=RTF_SHA or receipt.get('output_sha256')!=RAW_SHA:
        raise ValueError('Original conversion provenance differs')
    output=convert(data)
    if backup.exists() and backup.read_bytes()!=data:raise ValueError('Original text backup differs')
    backup.write_bytes(data)
    target.write_bytes(output)
    updated={**receipt,'unrtf_original_sha256':RAW_SHA,'unrtf_original_file':backup.name,
             'unrtf_output_encoding':'cp1252','normalization':'lossless-cp1252-to-utf8',
             'output_encoding':'utf-8','output_sha256':sha(output),
             'output_bytes':len(output),'roundtrip_verified':True,
             'original_rtf_changed':False}
    receipt_path.write_text(json.dumps(updated,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(updated,indent=2),flush=True)


if __name__=='__main__':main()
