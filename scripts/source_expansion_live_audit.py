"""Live admission audit for the open/public source-expansion batches.

No article bodies, images, audio, or video are downloaded by Global Pulse.
Admitted feeds are metadata-only RSS/Atom sources. Current-source admission
rejects stale feeds; explicitly seasonal/release-day feeds may be empty.
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
    # Batch 1, already admitted.
    "ukhsa","hm_treasury","cabinet_office","rba_media","eurostat_news",
    "health_canada_news","bank_canada_press","ecdc_news","eu_council_press",
    # Batch 2 candidates.
    "nass_news","nass_reports","nass_asb","nass_census",
    "sec_litigation","sec_suspensions",
    "noaa_news","nhc_atlantic_outlook","nhc_east_pacific_outlook",
    "ec_trade_news","ec_energy_news","ec_environment_news",
    "nz_economic_growth","nz_energy","nz_foreign_affairs","nz_health",
    "nz_infrastructure","nz_national_security","nz_trade",
    # Batch 3 candidates.
    "bls_employment","bls_jolts","bls_cpi","bls_ppi",
    "bls_import_export","bls_work_stoppages",
    # Batch 4 candidates.
    "uk_mod","uk_home_office","uk_desnz","uk_dft","uk_dhsc","uk_defra","uk_dsit",
    "ons_releases",
]

ALLOW_EMPTY={
    # Documented event/release feeds can legitimately have no item today.
    "nass_news","nass_reports","nass_asb","nass_census",
    "nhc_atlantic_outlook","nhc_east_pacific_outlook",
    "nz_national_security",
}

ALLOW_STALE={
    # Low-frequency official event/topic feeds remain useful for the next
    # publication; old items retain their source dates and cannot masquerade
    # as current evidence.
    "sec_suspensions","nz_economic_growth","nz_energy",
    "bls_work_stoppages","nass_asb","nass_census",
}

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
        if state.get("status") not in {"available","not_modified"} and not (
            state.get("status")=="stale" and identity in ALLOW_STALE
        ):
            failures.append(f"{identity}:{state.get('status')}:{state.get('http_status')}")
        elif not reports and identity not in ALLOW_EMPTY:
            failures.append(f"{identity}:no_reports")

    if failures:
        evidence["status"]="FAIL"
        evidence["failures"]=failures
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(evidence,indent=2),encoding="utf-8")
    return 0 if evidence["status"]=="PASS" else 1

if __name__=="__main__":
    raise SystemExit(main())
