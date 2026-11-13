"""Live admission audit for the open/public source-expansion batch.

No article bodies, images, audio, or video are downloaded by Global Pulse.
The admitted feeds are metadata-only RSS/Atom sources.
"""
from __future__ import annotations
import argparse,json,sys
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from global_pulse.map_evidence import incident_country
from global_pulse.sources import Collector,load_catalog

SOURCE_IDS=[
    "ukhsa","hm_treasury","cabinet_office","rba_media","eurostat_news",
    "phac_public_health","phac_travel_health","health_canada_news",
    "bank_canada_press","ecdc_cdtr","ecdc_news","eu_council_press",
]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--consent-network",action="store_true")
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if not args.consent_network:
        parser.error("Explicit --consent-network is required")

    catalog={row["id"]:row for row in load_catalog()}
    evidence={
        "recorded_at":datetime.now(timezone.utc).isoformat(),
        "source_ids":SOURCE_IDS,
        "results":[],
        "status":"PASS",
    }
    failures=[]
    for identity in SOURCE_IDS:
        result=Collector(catalog[identity]).collect()
        state=result["state"]
        reports=result.get("reports",[])
        countries=sorted({
            c for report in reports
            if (c:=incident_country({"reports":[report]}))
        })
        row={
            "source_id":identity,
            "publisher_origin_id":catalog[identity].get("publisher_origin_id",""),
            "status":state.get("status"),
            "http_status":state.get("http_status"),
            "reports":len(reports),
            "latest_publication":state.get("latest_publication",""),
            "countries":countries[:30],
            "error":state.get("error",""),
        }
        evidence["results"].append(row)
        print("SOURCE_EXPANSION",json.dumps(row,sort_keys=True),flush=True)
        if state.get("status") not in {"available","stale","not_modified"}:
            failures.append(f"{identity}:{state.get('status')}:{state.get('http_status')}")
        elif not reports:
            failures.append(f"{identity}:no_reports")

    if failures:
        evidence["status"]="FAIL"
        evidence["failures"]=failures
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(evidence,indent=2),encoding="utf-8")
    return 0 if evidence["status"]=="PASS" else 1

if __name__=="__main__":
    raise SystemExit(main())
