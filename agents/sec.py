"""sec.py — the deterministic settlement path.

Some claims do not need a panel. This one reads a number straight out of a company's
XBRL filing, and the accession number of that filing is the receipt that goes on chain.

Selection is by the (start, end, form) triple, NEVER by the `frame` field: ARM's fiscal
year ending 2026-03-31 is tagged frame "CY2025", so anyone matching on frame settles the
wrong year. Where a period appears more than once (SEC re-reports prior years in each new
filing), the latest `filed` wins.

Usage:  python sec.py            # fetch, evaluate, write out/sec_arm.json
"""
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import REPO_ROOT, settings  # noqa: E402

BASE = "https://data.sec.gov/api/xbrl/companyconcept"

# The claim, as data. Changing the question means changing this dict, not the code.
ARM_FY2026 = {
    "id": "arm-fy2026-revenue",
    "entity": "ARM HOLDINGS PLC /UK",
    "cik": "0001973239",
    "taxonomy": "us-gaap",
    "tag": "RevenueFromContractWithCustomerExcludingAssessedTax",
    "metric": "Revenue from contract with customer, excluding assessed tax",
    "start": "2025-04-01",
    "end": "2026-03-31",
    "form": "20-F",
    "period_label": "FY ended 31 March 2026",
    "threshold": 4_500_000_000,
    "cache": "data/arm_rev.json",
}


def fetch_concept(spec: dict) -> tuple[dict, str, str]:
    """Return (document, source, note). Falls back to the local cache if SEC is unreachable.

    data.sec.gov rejects requests without a declared identity, so the User-Agent is not
    decoration — without SEC_IDENTITY this 403s and the deterministic beat dies on stage.
    """
    identity = settings.sec_identity.strip()
    if not identity:
        raise SystemExit("SEC_IDENTITY is not set in .env — data.sec.gov rejects anonymous requests.")

    url = f"{BASE}/CIK{spec['cik']}/{spec['taxonomy']}/{spec['tag']}.json"
    try:
        r = requests.get(url, headers={"User-Agent": identity}, timeout=30)
        r.raise_for_status()
        return r.json(), "LIVE", f"data.sec.gov - fetched {time.strftime('%H:%M:%S')}"
    except requests.HTTPError as e:
        raise RuntimeError(
            f"data.sec.gov returned {e.response.status_code} - check SEC_IDENTITY. "
            f"Refusing to fall back to cache on an identity failure."
        )
    except Exception as e:
        cache = REPO_ROOT / spec["cache"]
        if not cache.exists():
            raise SystemExit(f"SEC unreachable ({e}) and no cache at {cache}")
        return (
            json.loads(cache.read_text(encoding="utf-8")),
            "CACHED",
            f"{spec['cache']} - SEC unreachable ({type(e).__name__})",
        )


def select_fact(doc: dict, spec: dict) -> dict:
    """Pick the one datapoint the claim is about. Latest filing wins on a re-report."""
    rows = [
        r for r in doc.get("units", {}).get("USD", [])
        if r.get("start") == spec["start"]
        and r.get("end") == spec["end"]
        and r.get("form") == spec["form"]
    ]
    if not rows:
        raise SystemExit(
            f"No {spec['form']} datapoint for {spec['start']}..{spec['end']} — "
            f"the filing may not be out yet, or the tag changed."
        )
    return max(rows, key=lambda r: r["filed"])


def settle(spec: dict = ARM_FY2026) -> dict:
    doc, source, note = fetch_concept(spec)
    fact = select_fact(doc, spec)
    value = int(fact["val"])
    outcome = value > spec["threshold"]

    result = {
        "id": spec["id"],
        "entity": doc.get("entityName", spec["entity"]),
        "cik": spec["cik"],
        "metric": spec["metric"],
        "period": spec["period_label"],
        "value": value,
        "threshold": spec["threshold"],
        "outcome": outcome,
        "form": fact["form"],
        "accession": fact["accn"],
        "filed": fact["filed"],
        "frame": fact.get("frame", ""),
        "source": source,
        "source_note": note,
        "evidence_uri": f"sec:{fact['accn']}",
        "filing_url": (
            f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
            f"&CIK={spec['cik']}&type={spec['form']}"
        ),
    }

    out = REPO_ROOT / "out"
    out.mkdir(exist_ok=True)
    (out / "sec_arm.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


if __name__ == "__main__":
    r = settle()
    print(f"{r['entity']}  ({r['source']})")
    print(f"  {r['metric']}")
    print(f"  {r['period']:28} ${r['value']:,}")
    print(f"  threshold                    ${r['threshold']:,}")
    print(f"  -> {'TRUE' if r['outcome'] else 'FALSE'}   {r['form']} accession {r['accession']} filed {r['filed']}")
    print(f"  {r['source_note']}")
    print("\n  out/sec_arm.json")
