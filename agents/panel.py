"""panel.py — run the three agents concurrently, one process each.

Spec §3.2: "For parallel runs, use multiprocessing — one process per agent — not threads."
tools.py holds module-level browser refs and a delegation depth counter; three agents in one
process would collide on them and on the Playwright user_data_dir (§12.2).

The result FILE is the contract, not the exit code: the crawl4ai/Playwright teardown
segfaults on Windows *after* a successful run, and crawl4ai prints banners to stdout.

Usage:  python panel.py
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import REPO_ROOT, settings  # noqa: E402

AGENTS = ["A", "B", "C"]
OUT = REPO_ROOT / "out"


def main() -> int:
    OUT.mkdir(exist_ok=True)
    for k in AGENTS:
        (OUT / f"agent_{k}.json").unlink(missing_ok=True)

    here = Path(__file__).resolve().parent
    print(f"launching {len(AGENTS)} agents in parallel (backend={settings.web_backend})\n")
    t0 = time.time()

    # Force UTF-8 in the children. crawl4ai prints an arrow in its banner and Windows'
    # default cp1252 stderr raises UnicodeEncodeError on it, killing the agent before it
    # writes a verdict — a full panel wipe caused by a decorative character.
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}

    procs = {
        k: subprocess.Popen(
            [sys.executable, str(here / "run_agent.py"), k],
            cwd=str(here),
            # stdin MUST be closed. wait_for_human calls input() with no timeout, and its
            # prompt goes nowhere, so an agent hitting a consent wall would hang the panel
            # silently and forever. Closed stdin turns that into an EOFError the agent
            # handles as an ordinary tool failure.
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=open(here / f"agent_{k}.log", "w", encoding="utf-8"),
            env=env,
        )
        for k in AGENTS
    }
    # A wall-clock cap, because nothing else in the stack has one: a stalled page can burn
    # ~180s inside a single tool call and max_turns cannot bound that.
    budget = settings.panel_budget_seconds
    for k, p in procs.items():
        try:
            p.wait(timeout=max(5, budget - (time.time() - t0)))
        except subprocess.TimeoutExpired:
            p.kill()
            print(f"  {k} EXCEEDED the {budget}s research budget - killed")
            f = OUT / f"agent_{k}.json"
            if not f.exists():
                f.write_text(json.dumps({
                    "verdict": False, "confidence": 0.0, "agent": k, "ok": False,
                    "reasoning": f"did not finish within the {budget}s research budget",
                    "citations": [], "elapsed": round(time.time() - t0, 1),
                }, indent=1), encoding="utf-8")
            continue
        print(f"  {k} finished after {time.time() - t0:5.1f}s (rc={p.returncode})")

    print(f"\nwall clock: {time.time() - t0:.1f}s\n")

    results = []
    for k in AGENTS:
        f = OUT / f"agent_{k}.json"
        if not f.exists():
            print(f"  {k}: NO RESULT FILE — agent produced nothing")
            continue
        try:
            results.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"  {k}: unreadable result ({e})")

    print("=" * 100)
    for r in results:
        mark = "YES" if r["verdict"] else "NO "
        name = r.get("name", "(fallback)")       # the §6.3 fallback dict carries no name
        print(f"\n[{r['agent']}] {name:26} -> {mark}  conf {r['confidence']:.2f}  {r['elapsed']}s")
        print(f"    {r['reasoning'][:600]}")
        for c in r.get("citations", [])[:3]:
            print(f"      * {c[:120]}")

    # Only completed agents have an opinion. A crash carries verdict=False from the fallback
    # dict, and counting that as a NO would manufacture the dissent this demo must never fake.
    voted = [r for r in results if r.get("ok")]
    yes = sum(1 for r in voted if r["verdict"])
    no = len(voted) - yes
    for r in results:
        if not r.get("ok"):
            print(f"NOTE: agent {r['agent']} did not complete - no bond posted, not counted as a vote")
    print("\n" + "=" * 100)
    if not voted:
        outcome = "NO QUORUM"
    elif yes == no:
        outcome = "VOID (tie — bonds refunded, nobody slashed)"
    else:
        outcome = f"RESOLVED_{'YES' if yes > no else 'NO'}"
    print(f"TALLY: {yes} yes / {no} no   ->   {outcome}")
    if yes and no:
        dissent = [r["agent"] for r in voted if r["verdict"] != (yes > no)]
        print(f"DISSENT: agent(s) {', '.join(dissent)} — bond slashed to the majority")
    return 0


if __name__ == "__main__":
    sys.exit(main())
