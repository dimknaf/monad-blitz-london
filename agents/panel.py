"""panel.py — run the three agents concurrently, one process each.

Spec §3.2: "For parallel runs, use multiprocessing — one process per agent — not threads."
tools.py holds module-level browser refs and a delegation depth counter; three agents in one
process would collide on them and on the Playwright user_data_dir (§12.2).

The result FILE is the contract, not the exit code: the crawl4ai/Playwright teardown
segfaults on Windows *after* a successful run, and crawl4ai prints banners to stdout.

Usage:  python panel.py
"""
import json
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

    procs = {
        k: subprocess.Popen(
            [sys.executable, str(here / "run_agent.py"), k],
            cwd=str(here),
            stdout=subprocess.DEVNULL,
            stderr=open(here / f"agent_{k}.log", "w", encoding="utf-8"),
        )
        for k in AGENTS
    }
    for k, p in procs.items():
        p.wait()
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
        print(f"\n[{r['agent']}] {r['name']:26} -> {mark}  conf {r['confidence']:.2f}  {r['elapsed']}s")
        print(f"    {r['reasoning'][:600]}")
        for c in r.get("citations", [])[:3]:
            print(f"      * {c[:120]}")

    yes = sum(1 for r in results if r["verdict"])
    no = len(results) - yes
    print("\n" + "=" * 100)
    if not results:
        outcome = "NO QUORUM"
    elif yes == no:
        outcome = "VOID (tie — bonds refunded, nobody slashed)"
    else:
        outcome = f"RESOLVED_{'YES' if yes > no else 'NO'}"
    print(f"TALLY: {yes} yes / {no} no   ->   {outcome}")
    if yes and no:
        dissent = [r["agent"] for r in results if r["verdict"] != (yes > no)]
        print(f"DISSENT: agent(s) {', '.join(dissent)} — bond slashed to the majority")
    return 0


if __name__ == "__main__":
    sys.exit(main())
