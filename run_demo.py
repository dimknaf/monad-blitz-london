"""run_demo.py — the stage sequence, one command.

  python run_demo.py            full arc
  python run_demo.py --reset    open fresh claims first (do this before every rehearsal)

The arc, and why it is in this order:

  OPEN      the question goes on chain as a hash, so nobody can reinterpret it afterwards
  BET       punters take positions; the implied price moves off 50/50
  RESEARCH  three oracles read real sources, in parallel, in their own processes
  ATTEST    each oracle posts its verdict with its own bond, from its own wallet
  FINALIZE  the contract tallies and slashes the minority
  COLLECT   the winning punter takes the losing pool
  SETTLE    the deterministic claim resolves from the SEC filing, no panel needed

Roles never mix: the oracles judge and never bet, the punters bet and never judge.
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AGENTS = ROOT / "agents"


def run(*args, label=""):
    print(f"\n{'=' * 78}\n>> {label or ' '.join(args)}\n{'=' * 78}")
    r = subprocess.run([sys.executable, *args], cwd=str(AGENTS))
    if r.returncode != 0:
        print(f"!! step failed: {label} (rc={r.returncode})")
    return r.returncode == 0


def main() -> int:
    reset = "--reset" in sys.argv
    t0 = time.time()

    print("ASSAY - agents that get paid to judge reality, and get slashed when they're wrong")
    run("chain.py", "status", label="PREFLIGHT")

    if reset:
        run("chain.py", "open", "judgement", label="OPEN judgement claim")
        run("chain.py", "open", "deterministic", label="OPEN deterministic claim")
        run("chain.py", "bet", "BETTOR_1", "yes", "0.3", label="BET 0.3 MON on YES")
        run("chain.py", "bet", "BETTOR_2", "no", "0.2", label="BET 0.2 MON on NO")

    # Bets are already in by the time this runs — they are placed from the page, before the
    # oracles start, which is the correct order: you take a position without knowing the answer.
    run("panel.py", label="RESEARCH - three oracles, in parallel")
    run("chain.py", "attest", label="ATTEST - bonded verdicts on chain")
    run("chain.py", "finalize", label="FINALIZE - tally and slash")
    run("chain.py", "payout", label="COLLECT - winners take the pool")
    run("chain.py", "settle", label="SETTLE - ARM, straight from the SEC filing")
    run("chain.py", "status", label="FINAL STATE")

    print(f"\ntotal {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
