"""chain.py — Monad testnet client: deploy, run the market, keep everyone solvent.

TESTNET ONLY. Every entry point asserts chain id 10143 and refuses otherwise — the x402
facilitator also serves mainnet 143, and a config slip is the only way this touches real value.

THREE ROLES, kept apart on purpose:
  COORD    market operator  — openClaim, finalize, settleDeterministic
  AGENT_*  ORACLES          — attest (bonded, slashable), withdraw
  BETTOR_* punters          — stake, claim, withdraw
An oracle never takes a position; a bettor never attests. role() asserts it before every send,
because the contract does not enforce it and a blurred role is the one thing that would make
the whole premise incoherent.
"""
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from eth_account import Account
from web3 import Web3

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

CHAIN_ID = 10143
MIN_AGENT_BALANCE = 5 * 10**17     # 0.5 MON = 5 bonds + gas
ORACLES = ["AGENT_A", "AGENT_B", "AGENT_C"]
BETTORS = ["BETTOR_1", "BETTOR_2"]
EXPLORER = "https://testnet.monadscan.com"

ROLES = {"COORD": "operator", **{a: "oracle" for a in ORACLES}, **{b: "bettor" for b in BETTORS}}
ALLOWED = {
    "operator": {"openClaim", "finalize", "settleDeterministic", "fund"},
    "oracle": {"attest", "withdraw"},
    "bettor": {"stake", "claim", "withdraw"},
}


def role_check(name: str, action: str):
    r = ROLES.get(name)
    if r is None:
        raise SystemExit(f"unknown wallet {name}")
    if action not in ALLOWED[r]:
        raise SystemExit(f"ROLE VIOLATION: {name} is a {r} and must never call {action}()")


def connect() -> Web3:
    # timeout is not optional: an unresponsive RPC on venue wifi otherwise hangs with no traceback
    w3 = Web3(Web3.HTTPProvider(os.environ["MONAD_RPC"], request_kwargs={"timeout": 20}))
    actual = w3.eth.chain_id
    if actual != CHAIN_ID:
        raise SystemExit(
            f"REFUSING TO RUN: connected to chain {actual}, expected {CHAIN_ID} (Monad testnet).\n"
            f"Check MONAD_RPC in .env. This guard exists so the demo can never touch mainnet."
        )
    return w3


def acct(name: str) -> Account:
    return Account.from_key(os.environ[f"{name}_PK"])


def _ledger(row: dict):
    """out/chain.jsonl is the feed the frontend renders as the ledger."""
    out = REPO_ROOT / "out"
    out.mkdir(exist_ok=True)
    with (out / "chain.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def send(w3: Web3, signer, tx: dict, label: str = "tx"):
    """Sign, send, wait. Gas from estimate*1.15 — Monad bills the LIMIT, not usage."""
    tx.setdefault("chainId", CHAIN_ID)
    # "pending", not the default "latest": a stuck rehearsal tx otherwise causes nonce reuse
    tx.setdefault("nonce", w3.eth.get_transaction_count(signer.address, "pending"))
    tx.setdefault("gasPrice", w3.eth.gas_price)
    if "gas" not in tx:
        try:
            tx["gas"] = int(w3.eth.estimate_gas({**tx, "from": signer.address}) * 1.15)
        except Exception as e:
            # estimate_gas fails BECAUSE the call reverts. Sending anyway burns gas and
            # prints a red tx on the projector, so stop here instead.
            raise SystemExit(f"{label}: would revert ({str(e)[:160]}) — not sending")

    h = w3.eth.send_raw_transaction(signer.sign_transaction(tx).raw_transaction)
    r = w3.eth.wait_for_transaction_receipt(h, timeout=180)
    ok = r.status == 1
    print(f"  {label:28} {'ok' if ok else 'REVERTED':9} block {r.blockNumber}  gas {r.gasUsed:,}  {w3.to_hex(h)}")
    _ledger({
        "ts": time.time(), "label": label, "tx": w3.to_hex(h), "block": r.blockNumber,
        "gas": r.gasUsed, "ok": ok, "explorer": f"{EXPLORER}/tx/{w3.to_hex(h)}",
    })
    if not ok:
        raise SystemExit(f"{label} REVERTED — {EXPLORER}/tx/{w3.to_hex(h)}")
    return r


def load_contract(w3: Web3):
    addr_file = REPO_ROOT / "out" / "contract.json"
    if not addr_file.exists():
        raise SystemExit("No deployment found. Run: python chain.py deploy")
    meta = json.loads(addr_file.read_text())
    abi = json.loads((REPO_ROOT / "contracts" / "Assay.abi.json").read_text())
    return w3.eth.contract(address=meta["address"], abi=abi), meta


def bond(contract) -> int:
    """Read the bond from the contract, never assume it — it is a constructor arg."""
    return contract.functions.BOND().call()


def _claims_file() -> Path:
    return REPO_ROOT / "out" / "claims.json"


def load_claims() -> dict:
    f = _claims_file()
    return json.loads(f.read_text()) if f.exists() else {}


def save_claims(d: dict):
    _claims_file().write_text(json.dumps(d, indent=1), encoding="utf-8")


def first_url(text: str) -> str:
    """Citations arrive as 'https://x: \"quote\"' or 'https://x (via ... snippet: \"...\")'.

    Only the bare URL may go on chain — the parenthetical would otherwise be written to
    Monad permanently.
    """
    import re
    m = re.search(r"https?://[^\s\"'<>)]+", text or "")
    return m.group(0).rstrip(".,:;") if m else ""


# ------------------------------------------------------------------ commands

def deploy():
    w3 = connect()
    coord = acct("COORD")
    b = int(os.environ.get("VALUE ORACLE_BOND_WEI", 10**17))
    abi = json.loads((REPO_ROOT / "contracts" / "Assay.abi.json").read_text())
    bytecode = (REPO_ROOT / "contracts" / "Assay.bin").read_text().strip()
    print(f"deploying Assay (bond {b/1e18} MON) from {coord.address} ({w3.eth.get_balance(coord.address)/1e18:.2f} MON)")

    c = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx = c.constructor(b).build_transaction(
        {"from": coord.address, "nonce": w3.eth.get_transaction_count(coord.address, "pending"),
         "gasPrice": w3.eth.gas_price, "chainId": CHAIN_ID}
    )
    tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.15)
    r = send(w3, coord, tx, "deploy Assay")
    (REPO_ROOT / "out").mkdir(exist_ok=True)
    (REPO_ROOT / "out" / "contract.json").write_text(
        json.dumps({"address": r.contractAddress, "block": r.blockNumber}, indent=1)
    )
    print(f"\n  ADDRESS: {r.contractAddress}\n  EXPLORER: {EXPLORER}/address/{r.contractAddress}")


def open_claim(kind: str = "judgement"):
    """Open a claim. specHash is keccak of the spec file — the question becomes immutable."""
    w3 = connect()
    contract, _ = load_contract(w3)
    coord = acct("COORD")
    role_check("COORD", "openClaim")

    spec_file = REPO_ROOT / "data" / "claims" / f"{kind}.md"
    if not spec_file.exists():
        raise SystemExit(f"no spec at {spec_file}")
    spec = spec_file.read_bytes()
    spec_hash = Web3.keccak(spec)
    spec_uri = f"https://github.com/dimknaf/monad-blitz-london/blob/main/data/claims/{kind}.md"

    # resolveAfter = 0, NOT time.time(): the laptop clock running ahead of the block
    # timestamp would revert finalize with TooEarly, live.
    r = send(w3, coord, contract.functions.openClaim(spec_hash, spec_uri, 0, 2).build_transaction(
        {"from": coord.address, "nonce": w3.eth.get_transaction_count(coord.address, "pending"),
         "gasPrice": w3.eth.gas_price, "chainId": CHAIN_ID}), f"open claim [{kind}]")

    cid = contract.functions.claimCount().call() - 1
    claims = load_claims()
    claims[kind] = {"id": cid, "spec_hash": spec_hash.hex(), "spec_uri": spec_uri,
                    "title": spec.decode("utf-8").splitlines()[0].lstrip("# ").strip()}
    save_claims(claims)
    print(f"  claim id {cid}  specHash 0x{spec_hash.hex()}")
    return cid


def bet(who: str = "BETTOR_1", side: str = "yes", amount_mon: str = "0.3"):
    """A punter takes a position. Oracles must never reach this path."""
    w3 = connect()
    contract, _ = load_contract(w3)
    role_check(who, "stake")
    claims = load_claims()
    if "judgement" not in claims:
        raise SystemExit("no judgement claim open — run: python chain.py open")
    cid = claims["judgement"]["id"]
    a = acct(who)
    value = w3.to_wei(amount_mon, "ether")

    send(w3, a, contract.functions.stake(cid, side.lower() == "yes").build_transaction(
        {"from": a.address, "nonce": w3.eth.get_transaction_count(a.address, "pending"),
         "gasPrice": w3.eth.gas_price, "chainId": CHAIN_ID, "value": value}),
        f"{who} stake {amount_mon} {side.upper()}")
    print(f"  impliedYes now {contract.functions.impliedYes(cid).call()/1e16:.0f}%")


def attest():
    """Each ORACLE posts its own verdict with its own bond, from its own wallet."""
    w3 = connect()
    contract, _ = load_contract(w3)
    claims = load_claims()
    cid = claims["judgement"]["id"]
    b = bond(contract)

    for key, name in zip("ABC", ORACLES):
        f = REPO_ROOT / "out" / f"agent_{key}.json"
        if not f.exists():
            print(f"  {name}: no result file — skipped")
            continue
        res = json.loads(f.read_text(encoding="utf-8"))
        if not res.get("ok"):
            # A crashed agent is not a dissent. Posting its fallback verdict=false would
            # manufacture the dissent the demo must never fake.
            print(f"  {name}: agent did not complete ({res.get('reasoning','')[:60]}) - NOT attesting")
            continue

        evidence = next((u for u in (first_url(c) for c in res.get("citations", [])) if u), "")
        if not evidence:                       # fall back to something it demonstrably fetched
            log = REPO_ROOT / "out" / f"tools_{key}.jsonl"
            fetched = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if l.strip()] if log.exists() else []
            ok_fetch = [e for e in fetched if e.get("ok") and e.get("bytes", 0) > 5000 and e["arg"].startswith("http")]
            evidence = max(ok_fetch, key=lambda e: e["bytes"])["arg"] if ok_fetch else "no-verified-evidence"

        a = acct(name)
        role_check(name, "attest")
        send(w3, a, contract.functions.attest(cid, bool(res["verdict"]), evidence).build_transaction(
            {"from": a.address, "nonce": w3.eth.get_transaction_count(a.address, "pending"),
             "gasPrice": w3.eth.gas_price, "chainId": CHAIN_ID, "value": b}),
            f"{name} attest {'YES' if res['verdict'] else 'NO'}")

    print(f"  attestations: {contract.functions.attestationCount(cid).call()}")


def finalize():
    w3 = connect()
    contract, _ = load_contract(w3)
    coord = acct("COORD")
    role_check("COORD", "finalize")
    cid = load_claims()["judgement"]["id"]

    send(w3, coord, contract.functions.finalize(cid).build_transaction(
        {"from": coord.address, "nonce": w3.eth.get_transaction_count(coord.address, "pending"),
         "gasPrice": w3.eth.gas_price, "chainId": CHAIN_ID}), "finalize judgement claim")

    c = contract.functions.claims(cid).call()
    print(f"  status: {['Open','ResolvedYes','ResolvedNo','Void'][c[7]]}")
    for name in ORACLES:
        addr = os.environ[f"{name}_ADDR"]
        cr = contract.functions.credits(addr).call()
        if not contract.functions.hasAttested(cid, addr).call():
            note = "(did not attest - no bond at risk)"   # never call this a slash
        elif cr == 0:
            note = "(SLASHED - bond went to the majority)"
        else:
            note = ""
        print(f"    {name:8} credits {cr/1e18:.3f} MON  {note}")


def settle():
    """Deterministic claim: no panel. The SEC accession is the receipt."""
    import sec
    w3 = connect()
    contract, _ = load_contract(w3)
    coord = acct("COORD")
    role_check("COORD", "settleDeterministic")
    cid = load_claims()["deterministic"]["id"]

    r = sec.settle()
    send(w3, coord, contract.functions.settleDeterministic(
        cid, bool(r["outcome"]), r["evidence_uri"]).build_transaction(
        {"from": coord.address, "nonce": w3.eth.get_transaction_count(coord.address, "pending"),
         "gasPrice": w3.eth.gas_price, "chainId": CHAIN_ID}),
        f"settle ARM {'TRUE' if r['outcome'] else 'FALSE'}")
    print(f"  ${r['value']:,} vs ${r['threshold']:,}  [{r['source']}]  accession {r['accession']}")


def payout():
    """Winners collect. Reads state first — a losing claim() reverts, and a red tx on the
    projector reads as a bug even when the contract is behaving correctly."""
    w3 = connect()
    contract, _ = load_contract(w3)
    cid = load_claims()["judgement"]["id"]
    c = contract.functions.claims(cid).call()
    status = ["Open", "ResolvedYes", "ResolvedNo", "Void"][c[7]]
    if status == "Open":
        raise SystemExit("claim still open — finalize first")
    print(f"claim #{cid} {status}")

    for who in BETTORS:
        addr = os.environ[f"{who}_ADDR"]
        y = contract.functions.stakeYes(cid, addr).call()
        n = contract.functions.stakeNo(cid, addr).call()
        won = (status == "ResolvedYes" and y) or (status == "ResolvedNo" and n) or (status == "Void" and (y or n))
        if not won:
            print(f"  {who}: staked {(y+n)/1e18:.2f} on the losing side - nothing to claim")
            continue
        if contract.functions.claimed(cid, addr).call():
            print(f"  {who}: already claimed")
            continue
        a = acct(who)
        role_check(who, "claim")
        before = w3.eth.get_balance(addr)
        send(w3, a, contract.functions.claim(cid).build_transaction(
            {"from": a.address, "nonce": w3.eth.get_transaction_count(a.address, "pending"),
             "gasPrice": w3.eth.gas_price, "chainId": CHAIN_ID}), f"{who} claim")
        _withdraw(w3, contract, who)
        print(f"    balance {before/1e18:.3f} -> {w3.eth.get_balance(addr)/1e18:.3f} MON")

    for name in ORACLES:                      # winning oracles collect bond + slashed share
        _withdraw(w3, contract, name)


def _withdraw(w3, contract, name: str):
    addr = os.environ[f"{name}_ADDR"]
    credits = contract.functions.credits(addr).call()
    if credits == 0:
        return
    a = acct(name)
    role_check(name, "withdraw")
    send(w3, a, contract.functions.withdraw().build_transaction(
        {"from": a.address, "nonce": w3.eth.get_transaction_count(a.address, "pending"),
         "gasPrice": w3.eth.gas_price, "chainId": CHAIN_ID}),
        f"{name} withdraw {credits/1e18:.3f}")


def fund():
    """Top every wallet up from COORD. Oracles go above ~10 MON so Monad's reserve-balance
    throttle (roughly 1 tx per 3 blocks below it) can never bite mid-demo."""
    w3 = connect()
    coord = acct("COORD")
    role_check("COORD", "fund")
    targets = {**{a: 8 * 10**18 for a in ORACLES}, **{b: 15 * 10**17 for b in BETTORS}}
    nonce = w3.eth.get_transaction_count(coord.address, "pending")
    for name, target in targets.items():
        addr = os.environ.get(f"{name}_ADDR")
        if not addr:
            print(f"  {name}: no address in .env — skipped")
            continue
        bal = w3.eth.get_balance(addr)
        if bal >= target:
            continue
        send(w3, coord, {"to": addr, "value": target - bal, "gas": 21000, "nonce": nonce},
             f"fund {name} {(target-bal)/1e18:.2f}")
        nonce += 1
    status()


def reset():
    """One command for a clean demo. Clears the last run's artefacts and opens fresh claims.

    Stale out/agent_*.json is what makes the page look already-judged before anyone has bet:
    the columns render the previous run's verdicts against a brand-new claim.
    """
    out = REPO_ROOT / "out"
    for pat in ("agent_A.json", "agent_B.json", "agent_C.json",
                "tools_A.jsonl", "tools_B.jsonl", "tools_C.jsonl", "chain.jsonl", "run.log"):
        (out / pat).unlink(missing_ok=True)
    print("cleared last run")
    open_claim("judgement")
    open_claim("deterministic")
    print("")
    print("CLEAN. Hard-reload the page (Ctrl+Shift+R), then bet, then RUN THE PANEL.")


def status():
    w3 = connect()
    print(f"chain {w3.eth.chain_id}  block {w3.eth.block_number:,}  gas {w3.eth.gas_price/1e9:.0f} gwei")
    try:
        contract, meta = load_contract(w3)
        n = contract.functions.claimCount().call()
        print(f"contract {meta['address']}  bond {bond(contract)/1e18} MON  claims: {n}")
        for i in range(n):
            c = contract.functions.claims(i).call()
            st = ["Open", "ResolvedYes", "ResolvedNo", "Void"][c[7]]
            print(f"  #{i} {st:12} quorum {c[4]}  attestations "
                  f"{contract.functions.attestationCount(i).call()}  "
                  f"impliedYes {contract.functions.impliedYes(i).call()/1e16:.0f}%")
    except SystemExit as e:
        print(e)
    for name in ["COORD"] + ORACLES + BETTORS:
        addr = os.environ.get(f"{name}_ADDR")
        if addr:
            print(f"  {name:9} {ROLES[name]:9} {w3.eth.get_balance(addr)/1e18:8.3f} MON")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    args = sys.argv[2:]
    {
        "deploy": deploy, "open": open_claim, "bet": bet, "attest": attest,
        "finalize": finalize, "settle": settle, "payout": payout,
        "fund": fund, "reset": reset, "status": status,
    }.get(cmd, status)(*args)
