# VALUE ORACLE — 3-minute run sheet

**Page:** http://127.0.0.1:8080 — already open, claim #2 is OPEN at 50%.
**Terminal:** `cd c:\Users\dimkn\source\repos\random\blitz-hackathon`

Have the browser full-screen on the projector and one terminal beside it.

---

## Before you start (30 seconds, do it now)

```bash
python agents/chain.py status
```

Claim **#2 Open, impliedYes 50%**. That is your starting frame. If it says anything else, run
`python agents/chain.py open judgement` again.

---

## 0:00–0:25 · THE CLAIM

**Point at the top of the screen. Do not touch anything yet.**

> "A prediction market needs an oracle. For 'what was the BTC price at noon' that's easy — read a
> feed. For **this** —"
>
> *(point at the claim)*
>
> "— *did TSMC signal that AI demand is accelerating?* — there is no feed. It's a judgement about
> what a company conveyed. So who decides?"
>
> *(point at the spec hash, 0xca4c7f…c3243b)*
>
> "First: the question is immutable. The full resolution spec — period, sources, tie-breaks — is
> hashed on chain when the claim opens. Nobody can reinterpret the question after seeing which way
> it went."

## 0:25–0:50 · THE BET  ← **you click here**

**Click `STAKE 0.3 MON ▸ YES`.** Wait for the bar to move (about a second).

> "I think it's true, so I'm taking a position. Real transaction, Monad testnet."

*(the bar jumps to 100%)*

> "I'm the only one in the market, so it reads 100%."

**Click `STAKE 0.2 MON ▸ NO`.**

*(the bar settles to 60%)*

> "Someone takes the other side. **Sixty percent.** That number is not a guess — it's the pool
> ratio. The price *is* the implied probability."

## 0:50–1:50 · THE ORACLES

**In the terminal:**

```bash
python agents/panel.py
```

**Point at the three columns on screen while it runs.**

> "Three research agents. They are **not** betting — they're oracles, separate wallets, no
> position. And they differ by **what they're allowed to read**: one reads only what management
> published, one reads the sell-side, one reads the press. Three agents on one document agree for
> the wrong reasons."

*(as lines stream in the feed)*

> "That's them working. Opening TSMC's transcript — 22-page filing, 68,000 characters. Not a
> summary. The actual document."

**When verdicts land, point at the citations.**

> "And here's the part I care about most. Every citation is checked against that agent's own tool
> log. Green means it genuinely opened that page. **Amber means it cited something it never
> opened** — a search snippet it passed off as a source."
>
> "That agent voted with the majority. It was *right*. And it still cut corners. **That is exactly
> why the verdict carries a bond.**"

## 1:50–2:25 · THE CHAIN

```bash
python agents/chain.py attest
python agents/chain.py finalize
```

> "Each oracle posts its verdict from its own wallet with its own stake. The contract tallies."

*(point at the ledger and the verdict box)*

> "Nobody voted on that. The contract did. Minority loses its bond to the majority."

**If an agent ran out of budget, say so — do not skip it:**

> "The third one didn't finish in budget. It's badged as a fallback and it posted **nothing** on
> chain — no bond, no verdict. We don't manufacture a dissent."

## 2:25–2:45 · THE PAYOUT

```bash
python agents/chain.py payout
```

**Point at the POSITIONS row — the balance changing is the moment.**

> "And I get paid. Staked 0.3, collected 0.5 — my stake plus the losing side. Watch the wallet."

## 2:45–2:55 · THE CHEAP ONE

```bash
python agents/chain.py settle
```

> "Not every claim needs a panel. *Did ARM earn more than four and a half billion?* That's in a
> filing. One HTTP request to the SEC, and the accession number goes on chain as the receipt."
>
> "Some facts cost nothing to verify. Some cost a research bounty. **This prices the difference.**"

## 2:55–3:00 · CLOSE

> "All testnet — faucet tokens, nobody's money. Agents that get paid to judge reality, and get
> slashed when they're wrong."

---

## One command, if you'd rather not type

```bash
python run_demo.py            # panel -> attest -> finalize -> payout -> settle
```

Place the two bets by clicking first, then run this.

---

## If something breaks

| Problem | Do this |
|---|---|
| Page blank / stale | `python agents/server.py snapshot` then reload |
| Server died | `python agents/server.py` (takes ~15s to warm) |
| Panel hangs | Ctrl-C. Attest works off the last good `out/agent_*.json` |
| Agent fails | Say it out loud — it's badged and posts nothing on chain |
| RPC 429s | Wait 20s. The page keeps serving the last good state |
| Everything is on fire | `screenshots/console.png` is the settled run. Talk over it. |

**Never say "parallel execution". Never claim a dissent that didn't happen.**

## The three lines to land

1. *"The question is immutable — it's hashed before anyone can see which way it goes."*
2. *"That agent was right, and it still cited something it never opened. That's what the bond is for."*
3. *"Some facts cost nothing to verify. Some cost a research bounty. This prices the difference."*
