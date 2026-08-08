"""server.py — the demo backend. ALL logic lives here.

The browser renders strings it is handed and computes nothing: no percentages, no number
formatting, no hash truncation, no deriving a colour from a value. Every field below arrives
display-ready, and every conditional the page might need is pre-resolved into a `*_kind`.

Chain reads are cached for 3s. The RPC caps eth_call at 15/second; the page polls at 2Hz and
one payload costs ~12 reads, which without the cache is 24/second sustained and a blank screen.

Usage:  python server.py            # http://127.0.0.1:8080
        python server.py snapshot   # bake web/state.json for the static deploy
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chain  # noqa: E402
from config import REPO_ROOT  # noqa: E402

WEB = REPO_ROOT / "web"
OUT = REPO_ROOT / "out"
AGENT_KEYS = ["A", "B", "C"]
SNIPPET_TELLS = ("via google", "search snippet", "search result", "referenced via",
                 "simulated", "ai overview", "placeholder")
MIN_REAL_BYTES = 5000        # a 404 shell renders as ~3-4kB of text; real articles are far bigger
# Display-only stand-in for an agent that ran out of budget. Badged on screen, never on chain.
DEMO_FALLBACK = os.environ.get("DEMO_FALLBACK", "1") == "1"   # display only, never on chain

app = Flask(__name__, static_folder=None)
_cache: dict = {"t": 0.0, "v": None}
_run_id = str(int(time.time()))
_last_block = {"v": None}
_run: dict = {"proc": None}


# ----------------------------------------------------------------- formatting

def mon(wei: int, dp: int = 3) -> str:
    return f"{wei / 1e18:.{dp}f} MON"


def short(h: str, head: int = 6, tail: int = 4) -> str:
    return h if not h or len(h) <= head + tail + 1 else f"{h[:head]}…{h[-tail:]}"


def clock(ts: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts))


def url_of(citation: str) -> str:
    m = re.search(r"https?://[^\s\"'<>)]+", citation or "")
    return m.group(0).rstrip(".,:;") if m else ""


def quote_of(citation: str) -> str:
    m = re.search(r'"([^"]{10,})"', citation or "")
    return m.group(1) if m else ""


def pretty_url(u: str, cap: int = 62) -> str:
    s = re.sub(r"^https?://(www\.)?", "", u)
    return s if len(s) <= cap else s[: cap - 20] + "…" + s[-19:]


def read_jsonl(p: Path) -> list:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


# ------------------------------------------------------- citation verification

def verify(citation: str, log: list) -> dict:
    """A citation is VERIFIED only if the agent demonstrably opened it in THIS run.

    Four conditions, not one. A URL-only match certifies fabrication: one agent invented a
    URL ending '...-123456789', fetched it, got a 3,963-byte error page logged ok=true — and a
    lax check would have put a green tick on it. Meanwhile genuine citations carry an inline
    quote after the URL, so an exact string match marks real sources unverified.
    """
    u = url_of(citation)
    low = (citation or "").lower()
    tell = next((t for t in SNIPPET_TELLS if t in low), "")
    hit = next((e for e in log
                if e.get("arg", "").rstrip(".,:;") == u and e.get("ok")
                and e.get("bytes", 0) >= MIN_REAL_BYTES), None)

    if not u:
        ok, detail = False, "no URL in citation"
    elif hit:
        # An actual fetch is dispositive. Checking the prose first would defame a real source
        # because the model happened to write the words "search result" beside it.
        ok, detail = True, f"opened in this run - {hit['bytes']:,} B in {hit.get('elapsed', 0)}s"
    elif tell:
        ok, detail = False, f"cited via '{tell.strip()}' - a snippet is not an opened document"
    else:
        thin = next((e for e in log if e.get("arg", "").rstrip(".,:;") == u), None)
        detail = (f"fetched but only {thin.get('bytes', 0):,} B - too thin to be the source"
                  if thin else "never opened in this run")
        ok = False

    return {
        "url": u, "url_short": pretty_url(u), "quote": quote_of(citation),
        "verified": ok, "verified_label": "VERIFIED" if ok else "UNVERIFIED",
        "verified_kind": "verified" if ok else "unverified", "detail": detail,
    }


# --------------------------------------------------------------- chain reading

def chain_state() -> dict:
    """Every RPC read in one place so the TTL cache covers all of them."""
    w3 = chain.connect()
    contract, meta = chain.load_contract(w3)
    claims_meta = chain.load_claims()
    bond_wei = chain.bond(contract)
    block = w3.eth.block_number

    claims, market, controls = [], None, None
    for kind, cm in claims_meta.items():
        cid = cm["id"]
        c = contract.functions.claims(cid).call()
        status = ["OPEN", "RESOLVED YES", "RESOLVED NO", "VOID"][c[7]]
        kinds = ["open", "yes", "no", "void"][c[7]]
        pct = contract.functions.impliedYes(cid).call() // 10**16
        n_att = contract.functions.attestationCount(cid).call()
        yes = sum(1 for i in range(n_att) if contract.functions.attestations(cid, i).call()[1])

        card = MARKET_CARD[kind]
        claims.append({
            "id": cid, "kind": kind, "title": cm["title"],
            "label": card["label"], "resolved_by": card["resolved_by"],
            "resolved_note": card["resolved_note"], "cost": card["cost"],
            "claim": claim_body(kind),
            "spec_hash_full": "0x" + cm["spec_hash"], "spec_hash_short": short("0x" + cm["spec_hash"], 8, 6),
            "spec_uri": cm["spec_uri"],
            "status": status, "status_kind": kinds,
            "implied_yes_pct": pct, "implied_yes_label": f"{pct}%",
            "pool_yes": mon(c[5], 2), "pool_no": mon(c[6], 2),
            "quorum_label": f"{c[4]} OF 3", "attestations": str(n_att),
            "tally": f"{yes} YES / {n_att - yes} NO" if n_att else "NO ATTESTATIONS YET",
            "slashed": slashed_list(contract, cid, c, n_att, bond_wei),
        })

        if kind == "judgement":
            market, controls = market_state(w3, contract, cid, c, status, kinds)

    balances = []
    for n in ["COORD"] + chain.ORACLES + chain.BETTORS:
        addr = chain.os.environ.get(f"{n}_ADDR")
        if not addr:
            continue
        bal = w3.eth.get_balance(addr)          # ONCE per wallet — this was doubling RPC load
        balances.append({"name": n.replace("_", " "), "role": chain.ROLES[n].upper(),
                         "address_short": short(addr), "mon": f"{bal / 1e18:.3f}",
                         "mon_label": mon(bal)})

    changed = _last_block["v"] is not None and _last_block["v"] != block
    _last_block["v"] = block

    return {
        "meta": {
            "chain_label": f"MONAD TESTNET · CHAIN {chain.CHAIN_ID}",
            "block": f"{block:,}", "block_changed": changed,
            "contract_short": short(meta["address"], 6, 5), "contract_full": meta["address"],
            "explorer": f"{chain.EXPLORER}/address/{meta['address']}",
            "bond": mon(bond_wei, 1), "updated": clock(time.time()), "run_id": _run_id,
        },
        "claims": claims, "market": market, "bet_controls": controls, "balances": balances,
        "_bond": bond_wei,
    }


def slashed_list(contract, cid, c, n_att, bond_wei) -> list:
    """Who actually lost a bond. Read back from the attestations against the resolved status —
    the slash is the headline mechanic and the panel showing it was hardcoded empty."""
    if c[7] not in (1, 2) or not n_att:          # ResolvedYes / ResolvedNo only
        return []
    outcome = c[7] == 1
    out = []
    for i in range(n_att):
        a = contract.functions.attestations(cid, i).call()
        if a[1] != outcome:
            out.append({"agent": short(a[0]), "address_short": short(a[0]),
                        "amount": mon(a[2], 1)})
    return out


MARKET_CARD = {
    "judgement": {
        "label": "MARKET 1 · JUDGEMENT",
        "resolved_by": "RESOLVED BY THREE BONDED ORACLES",
        "resolved_note": "NO FEED EXISTS - AGENTS JUDGE, AND ARE SLASHED WHEN THEY ARE WRONG",
        "cost": "COSTS A RESEARCH BOUNTY",
    },
    "deterministic": {
        "label": "MARKET 2 · DETERMINISTIC",
        "resolved_by": "RESOLVED BY ONE SEC FILING",
        "resolved_note": "NOTHING TO JUDGE - NO PANEL, NO BONDS, NOBODY SLASHED",
        "cost": "COSTS ONE HTTP REQUEST",
    },
}


def market_state(w3, contract, cid, c, status, kinds):
    """Positions and payouts. The bettors are NOT the oracles — separate wallets, separate role."""
    positions = []
    for who in chain.BETTORS:
        addr = chain.os.environ.get(f"{who}_ADDR")
        if not addr:
            continue
        y = contract.functions.stakeYes(cid, addr).call()
        n = contract.functions.stakeNo(cid, addr).call()
        if not (y or n):
            continue
        side, stake_wei = ("YES", y) if y else ("NO", n)
        paid = contract.functions.claimed(cid, addr).call()

        if status == "OPEN":
            st, sk, payout_wei = "OPEN", "open", 0
        elif status == "VOID":
            st, sk, payout_wei = "REFUNDED", "refunded", stake_wei
        elif (status == "RESOLVED YES" and y) or (status == "RESOLVED NO" and n):
            pool_win, pool_lose = (c[5], c[6]) if y else (c[6], c[5])
            payout_wei = stake_wei + (stake_wei * pool_lose // pool_win if pool_win else 0)
            st, sk = ("COLLECTED" if paid else "WON"), "won"
        else:
            st, sk, payout_wei = "LOST", "lost", 0

        profit = payout_wei - stake_wei
        positions.append({
            "who": who.replace("_", " "), "address_short": short(addr),
            "side": side, "side_kind": side.lower(), "stake": mon(stake_wei, 2),
            "status": st, "status_kind": sk,
            "payout": mon(payout_wei, 2),
            "profit": f"{'+' if profit > 0 else ''}{profit / 1e18:.2f} MON",
            "profit_kind": "up" if profit > 0 else ("down" if profit < 0 else "flat"),
            "balance_after": mon(w3.eth.get_balance(addr)),
        })

    headline = {"OPEN": "MARKET OPEN", "VOID": "VOID - EVERYONE REFUNDED"}.get(
        status, f"SETTLED - {status.split()[-1]}")
    market = {
        "present": bool(positions), "headline": headline, "headline_kind": kinds,
        "note": "PARIMUTUEL - WINNERS SPLIT THE LOSING POOL", "positions": positions,
    }
    is_open = status == "OPEN"
    controls = {
        "enabled": is_open,
        "note": "CLAIM IS OPEN - STAKE TO MOVE THE PRICE" if is_open
                else "BETTING CLOSED - CLAIM RESOLVED",
        # `disabled` is served alongside `enabled` so the browser copies it straight to the DOM
        # property. Writing `!enabled` in JS would be derivation, and pointer-events is not a
        # real disable for keyboard or assistive tech.
        "buttons": [
            {"id": "yes", "label": "STAKE 0.3 MON ▸ YES", "side_kind": "yes",
             "enabled": is_open, "disabled": not is_open},
            {"id": "no", "label": "STAKE 0.2 MON ▸ NO", "side_kind": "no",
             "enabled": is_open, "disabled": not is_open},
        ],
    }
    return market, controls


def claim_body(kind: str) -> str:
    f = REPO_ROOT / "data" / "claims" / f"{kind}.md"
    if not f.exists():
        return ""
    lines = f.read_text(encoding="utf-8").splitlines()
    try:
        i = lines.index("## Claim")
    except ValueError:
        return ""
    body = []
    for l in lines[i + 1:]:
        if l.startswith("##"):
            break
        if l.strip():
            body.append(l.strip())
    return " ".join(body)


# ------------------------------------------------------------- agents and feed

def agent_state() -> tuple[list, list]:
    agents, feed = [], []
    running = [json.loads(l) for l in (OUT / "panel_status.json").read_text(encoding="utf-8").splitlines()
               ] if (OUT / "panel_status.json").exists() else []
    active = running[-1].get("running", []) if running else []

    for key, name in zip(AGENT_KEYS, chain.ORACLES):
        log = read_jsonl(OUT / f"tools_{key}.jsonl")
        res = read_json(OUT / f"agent_{key}.json")

        lines, prev_end = [], None
        for e in log:
            # The gap between one tool returning and the next being called IS the model
            # thinking. Showing it turns a list of fetches into an agent visibly working.
            think = (e["ts"] - e.get("elapsed", 0)) - prev_end if prev_end else 0
            if think > 1.5:
                gap = {"t": clock(prev_end), "kind": "think", "ok": True,
                       "text": "reasoning over what it just read",
                       "detail": f"{think:.1f}s of deliberation"}
                lines.append(gap)
                feed.append({**gap, "_ts": prev_end, "agent": key,
                             "text": f"{PANEL_SHORT[key]} is reasoning over what it just read"})
            prev_end = e["ts"]

            k, text, detail = narrate(e)
            lines.append({"t": clock(e["ts"]), "kind": k, "ok": bool(e.get("ok")),
                          "text": text, "detail": detail})
            feed.append({"t": clock(e["ts"]), "_ts": e["ts"], "agent": key, "kind": k,
                         "ok": bool(e.get("ok")),
                         "text": f"{PANEL_SHORT[key]} {text[0].lower() + text[1:]}",
                         "detail": detail})

        # The quotes that actually decided it — the most interesting thing an agent produces.
        if res and res.get("ok"):
            for c in res.get("citations", []):
                q = quote_of(c)
                if q:
                    ev = {"t": clock(prev_end or 0), "_ts": (prev_end or 0) + 0.1, "agent": key,
                          "kind": "quote", "ok": True,
                          "text": f"{PANEL_SHORT[key]} quotes: “{q[:150]}”",
                          "detail": pretty_url(url_of(c))}
                    feed.append(ev)

        if res is None:
            st, sk = ("RESEARCHING", "running") if key in active else ("WAITING", "waiting")
            agents.append({
                "key": key, "name": PANEL_NAMES[key], "brief": PANEL_BRIEFS[key],
                "address_short": short(chain.os.environ.get(f"{chain.ORACLES[AGENT_KEYS.index(key)]}_ADDR", "")),
                "status": st, "status_kind": sk, "verdict": "—", "verdict_kind": "none",
                "confidence": "—", "confidence_pct": 0, "reasoning": "", "elapsed": "—",
                "fetches": f"{sum(1 for e in log if e.get('ok'))} SOURCES READ",
                "bond": "—", "outcome": "", "outcome_kind": "none",
                "lines": lines, "citations": [],
            })
            continue

        ok = res.get("ok")
        if not ok and DEMO_FALLBACK:
            # Display-only stand-in so a failed agent does not leave a dead column on the
            # projector. It is badged as a fallback everywhere it appears and it NEVER
            # attests — chain.py refuses to post a verdict for an agent with ok=false, so
            # nothing fabricated can reach Monad.
            agents.append({
                "key": key, "name": PANEL_NAMES[key], "brief": PANEL_BRIEFS[key],
                "address_short": short(chain.os.environ.get(f"{chain.ORACLES[AGENT_KEYS.index(key)]}_ADDR", "")),
                "status": "FALLBACK", "status_kind": "failed",
                "verdict": "PLACEHOLDER", "verdict_kind": "none",
                "confidence": "—", "confidence_pct": 0,
                "reasoning": "DEMO FALLBACK — this agent did not finish its research in budget. "
                             "The verdict shown is a placeholder, it is NOT a research result, "
                             "and no bond was posted for it on chain.",
                "elapsed": f"{float(res.get('elapsed', 0)):.1f}s",
                "fetches": f"{sum(1 for e in log if e.get('ok'))} SOURCES READ",
                "bond": "—", "outcome": "NOT ON CHAIN", "outcome_kind": "none",
                "lines": lines, "citations": [],
            })
            continue

        agents.append({
            "key": key, "name": res.get("name", PANEL_NAMES[key]), "brief": PANEL_BRIEFS[key],
            "address_short": short(chain.os.environ.get(f"{chain.ORACLES[AGENT_KEYS.index(key)]}_ADDR", "")),
            "status": "DONE" if ok else "FAILED", "status_kind": "done" if ok else "failed",
            "verdict": ("YES" if res["verdict"] else "NO") if ok else "NO VERDICT",
            "verdict_kind": ("yes" if res["verdict"] else "no") if ok else "none",
            "confidence": f"{res.get('confidence', 0):.2f}",
            "confidence_pct": int(round(res.get("confidence", 0) * 100)),
            "reasoning": res.get("reasoning", ""),
            "elapsed": f"{float(res.get('elapsed', 0)):.1f}s",
            "fetches": f"{res.get('fetches', sum(1 for e in log if e.get('ok')))} SOURCES READ",
            "lines": lines,
            "citations": [verify(c, log) for c in res.get("citations", [])],
        })

    feed.sort(key=lambda f: f["_ts"])
    for i, f in enumerate(feed):
        f["id"] = i
        f.pop("_ts")
    return agents, feed


def source_name(url: str) -> str:
    """A human name for a source. 'the TSMC investor site', not a 90-character URL."""
    host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
    known = {
        "investor.tsmc.com": "TSMC's own investor site", "fool.com": "Motley Fool",
        "reuters.com": "Reuters", "cnbc.com": "CNBC", "finance.yahoo.com": "Yahoo Finance",
        "investing.com": "Investing.com", "sec.gov": "the SEC", "nikkei.com": "Nikkei",
        "bloomberg.com": "Bloomberg", "ft.com": "the Financial Times", "wsj.com": "the WSJ",
    }
    if host in known:
        return known[host]
    doc = url.rstrip("/").split("/")[-1].split("?")[0]
    doc = re.sub(r"[-_]+", " ", re.sub(r"\.(pdf|html?)$", "", doc)).strip()
    return f"{host} — {doc[:48]}" if 3 < len(doc) < 70 else host


def narrate(e: dict) -> tuple[str, str, str]:
    """Turn a raw tool-call record into a sentence a room can follow.

    The feed is the 60-second beat of the demo. 'visit_webpage ok 68101B' tells an audience
    nothing; 'reading TSMC's own investor site' tells them what the agent is doing and why.
    """
    tool, arg, ok = e["tool"], e.get("arg", ""), bool(e.get("ok"))
    secs = e.get("elapsed", 0)
    note = e.get("note", "")

    if tool in ("search_google", "firecrawl_search"):
        if not ok:
            return "error", f"search failed: “{arg[:70]}”", f"{note or 'no results'} — trying another route"
        return "search", f"searched the web: “{arg[:110]}”", f"results back in {secs}s"

    if tool == "submit_result":
        return "submit", f"submitted its verdict — {arg.replace('verdict=True', 'YES').replace('verdict=False', 'NO')}", note

    if tool == "delegate_to_subagent":
        return "search", f"delegated a sub-task: {arg[:70]}", f"{secs}s"

    if tool == "wait_for_human":
        return "error", f"asked for help: {arg[:70]}", "blocked by a consent wall or CAPTCHA"

    # a page or PDF fetch
    if not ok:
        why = "timed out" if "imeout" in note else (note[:60] or "would not load")
        return "error", f"could not open {source_name(arg)}", f"{why} after {secs}s — it will find another source"

    pages = re.search(r"pdf (\d+)p", note)
    what = f"{pages.group(1)}-page filing" if pages else "web page"
    return "fetch", f"opened {source_name(arg)} and read it in full",            f"{what}, {e.get('bytes', 0):,} characters pulled in {secs}s"


PANEL_NAMES = {"A": "PRIMARY SOURCE ANALYST", "B": "SELL-SIDE ANALYST", "C": "FINANCIAL PRESS ANALYST"}
PANEL_SHORT = {"A": "PRIMARY SOURCE", "B": "SELL-SIDE", "C": "FINANCIAL PRESS"}
PANEL_BRIEFS = {
    "A": "Reads only what management said and published",
    "B": "Reads what professional analysts concluded",
    "C": "Reads established press with editorial standards",
}


def oracle_outcomes(agents: list, claims: list, bond_wei: int):
    """Who was slashed. Decided by the contract, read back — never inferred from the verdicts."""
    j = next((c for c in claims if c["kind"] == "judgement"), None)
    if not j or j["status_kind"] not in ("yes", "no"):
        return
    w3 = chain.connect()
    contract, _ = chain.load_contract(w3)
    for a in agents:
        if a["status_kind"] == "failed":       # placeholder verdict: never scored, never on chain
            a["outcome"], a["outcome_kind"], a["bond"] = "NOT ON CHAIN", "none", "-"
            continue
        addr = chain.os.environ.get(f"{chain.ORACLES[AGENT_KEYS.index(a['key'])]}_ADDR")
        if not addr or not contract.functions.hasAttested(j["id"], addr).call():
            a["outcome"], a["outcome_kind"], a["bond"] = "NO BOND AT RISK", "none", "—"
            continue
        a["bond"] = mon(bond_wei, 1)
        won = (a["verdict_kind"] == j["status_kind"])
        a["outcome"] = "PAID" if won else "SLASHED"
        a["outcome_kind"] = "majority" if won else "slashed"


def sec_state(claims: list) -> dict:
    """Market 2. It carries its own claim text and spec hash so it reads as a market in its
    own right rather than a stray SEC readout parked beside an unrelated TSMC page."""
    det = next((c for c in claims if c["kind"] == "deterministic"), {})
    r = read_json(OUT / "sec_arm.json")
    if not r:
        return {"present": False, "state_kind": "absent", **_card(det)}
    head = (r["value"] - r["threshold"]) / r["threshold"] * 100
    return {
        "present": True, "state_kind": "present", **_card(det),
        "entity": r["entity"], "cik": f"CIK {r['cik']}", "metric": r["metric"].upper(),
        "period": r["period"].upper(), "value": f"${r['value']:,}",
        "threshold": f"> ${r['threshold']:,}", "headroom": f"+{head:.1f}% HEADROOM",
        "outcome": "TRUE" if r["outcome"] else "FALSE",
        "outcome_kind": "yes" if r["outcome"] else "no",
        "form": r["form"], "accession": r["accession"], "filed": f"FILED {r['filed']}",
        "source": r["source"], "source_kind": r["source"].lower(), "source_note": r["source_note"],
    }


def ledger() -> list:
    return [{
        "t": clock(e["ts"]), "label": e["label"].upper(),
        "tx_short": short(e["tx"], 6, 4), "block": f"{e['block']:,}",
        "gas": f"{e['gas']:,}", "status": "OK" if e.get("ok") else "FAILED",
        "status_kind": "ok" if e.get("ok") else "failed", "explorer": e.get("explorer", ""),
    } for e in read_jsonl(OUT / "chain.jsonl")]


def _card(c: dict) -> dict:
    return {
        "label": c.get("label", "MARKET 2 · DETERMINISTIC"),
        "title": c.get("title", ""), "claim": c.get("claim", ""),
        "resolved_by": c.get("resolved_by", "RESOLVED BY ONE SEC FILING"),
        "resolved_note": c.get("resolved_note", "NOTHING TO JUDGE - NO PANEL, NO BONDS"),
        "cost": c.get("cost", "COSTS ONE HTTP REQUEST"),
        "spec_hash_short": c.get("spec_hash_short", ""),
        "spec_hash_full": c.get("spec_hash_full", ""),
        "spec_uri": c.get("spec_uri", ""),
        "status": c.get("status", ""), "status_kind": c.get("status_kind", "open"),
    }


PHASES = [("done", "COMPLETE"), ("settling", "SETTLING ON CHAIN"),
          ("voting", "ORACLES ATTESTING"), ("research", "PANEL RESEARCHING"), ("idle", "STANDING BY")]


def build_state() -> dict:
    cs = chain_state()
    agents, feed = agent_state()
    oracle_outcomes(agents, cs["claims"], cs.pop("_bond"))
    sec = sec_state(cs["claims"])

    j = next((c for c in cs["claims"] if c["kind"] == "judgement"), None)
    if j and j["status_kind"] in ("yes", "no", "void"):
        kind, label = ("done", "COMPLETE") if sec.get("present") else ("settling", "SETTLING ON CHAIN")
    elif j and int(j["attestations"]):
        kind, label = "voting", "ORACLES ATTESTING"
    elif any(a["status_kind"] == "running" for a in agents):
        kind, label = "research", "PANEL RESEARCHING"
    else:
        kind, label = "idle", "STANDING BY"
    cs["meta"]["phase_label"], cs["meta"]["phase_kind"] = label, kind

    live = bool(_run["proc"] and _run["proc"].poll() is None)
    staked = any(p["stake"] != "0.00 MON" for p in (cs.get("market") or {}).get("positions", []))
    if live:
        note, label = "PANEL RUNNING - RESEARCH IN PROGRESS", "RUNNING..."
    elif staked:
        note, label = "BETS ARE IN - START THE ORACLES", "▸ RUN THE PANEL"
    else:
        note, label = "PLACE A BET FIRST, THEN RUN THE PANEL", "▸ RUN THE PANEL"
    cs["run_controls"] = {
        "present": True, "note": note, "label": label,
        "running": live, "disabled": live,
        "kind": "running" if live else "ready",
    }
    return {**cs, "agents": agents, "feed": feed, "chain": ledger(), "sec": sec}


def build_state_resilient(tries: int = 3) -> dict:
    """The public RPC caps eth_call at 15/sec and 429s past it. Back off rather than 500."""
    for i in range(tries):
        try:
            return build_state()
        except Exception as e:
            if "429" not in str(e) or i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))
    raise RuntimeError("unreachable")


def refresher():
    """Rebuild state on a background thread and write it to web/state.json, forever.

    A request must NEVER wait on the chain. The RPC 429s under load and the retry backoff
    can run past twenty seconds — long enough for the projector to sit on a blank page while
    a poll blocks. So the page reads a plain file and the chain work happens off to one side.

    The file is also exactly the artefact the static deploy serves, so the live console and
    the replay are the same code path rather than two things that can drift apart.
    """
    while True:
        try:
            write_state(build_state_resilient())
        except Exception as e:
            print(f"  refresh failed, keeping last good state: {type(e).__name__}")
        time.sleep(2.0)


def write_state(payload: dict):
    WEB.mkdir(exist_ok=True)
    tmp = WEB / "state.json.tmp"        # write-then-rename: a poll never sees a half-file
    tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    tmp.replace(WEB / "state.json")


# ---------------------------------------------------------------------- routes

@app.get("/")
def index():
    return send_from_directory(WEB, "index.html")


@app.get("/state.json")
def state():
    # A file read. The chain is never touched on the request path.
    return send_from_directory(WEB, "state.json", mimetype="application/json",
                               max_age=0, conditional=False)


@app.get("/<path:f>")
def asset(f):
    # max_age=0: without it the browser caches assay.css and a CSS fix appears not to have
    # landed. During a demo that reads as "the fix did not work" rather than "reload harder".
    return send_from_directory(WEB, f, max_age=0, conditional=False)


@app.post("/api/bet")
def api_bet():
    """The one write. Button id -> a real stake from a real bettor wallet."""
    plan = {"yes": ("BETTOR_1", "yes", "0.3"), "no": ("BETTOR_2", "no", "0.2")}
    pick = plan.get((request.get_json(silent=True) or {}).get("id"))
    if not pick:
        return jsonify({"ok": False, "error": "unknown button"}), 400
    try:
        chain.bet(*pick)
    except SystemExit as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    try:
        write_state(build_state_resilient())   # repaint now rather than waiting for the tick
    except Exception:
        pass    # the stake LANDED. A rate-limited repaint must not report the click as failed;
                # the 2s refresher will catch up on its own.
    return jsonify({"ok": True})


@app.post("/api/run")
def api_run():
    """RUN THE PANEL. One button starts the whole thing and the page narrates it live.

    Bets are placed before this; from here it is research -> attest -> finalize -> payout ->
    settle, with every step appending to out/chain.jsonl so the page tells the story itself.
    """
    if _run["proc"] and _run["proc"].poll() is None:
        return jsonify({"ok": False, "error": "already running"}), 409
    for k in AGENT_KEYS:                      # clear the last run so columns start empty
        (OUT / f"agent_{k}.json").unlink(missing_ok=True)
        (OUT / f"tools_{k}.jsonl").unlink(missing_ok=True)
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    _run["proc"] = subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "run_demo.py")], cwd=str(REPO_ROOT),
        stdin=subprocess.DEVNULL, stdout=open(REPO_ROOT / "out" / "run.log", "w", encoding="utf-8"),
        stderr=subprocess.STDOUT, env=env)
    return jsonify({"ok": True})


def snapshot():
    write_state(build_state_resilient(tries=6))
    print(f"baked {WEB / 'state.json'}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "snapshot":
        snapshot()
    else:
        # REFUSE to be the second server. Every instance writes web/state.json on its own
        # timer and holds its own _run state, so two of them alternate the payload every
        # couple of seconds — buttons flicker and the panel looks like it started itself.
        import socket
        probe = socket.socket()
        probe.settimeout(0.5)
        if probe.connect_ex(("127.0.0.1", 8080)) == 0:
            probe.close()
            raise SystemExit("VALUE ORACLE is already running at http://127.0.0.1:8080 - not starting a second one.")
        probe.close()

        # Warm the file if we can, but never die trying: an existing state.json from the
        # last run is a perfectly good first paint, and the refresher will replace it within
        # seconds. A rate-limited RPC must not be able to stop the console from starting.
        print("warming state...")
        try:
            write_state(build_state_resilient())
        except Exception as e:
            have = (WEB / "state.json").exists()
            print(f"  warm-up failed ({type(e).__name__}); "
                  f"{'serving the last good state.json' if have else 'starting empty'}")
        threading.Thread(target=refresher, daemon=True).start()
        print("VALUE ORACLE -> http://127.0.0.1:8080")
        app.run(host="127.0.0.1", port=8080, threaded=True)
