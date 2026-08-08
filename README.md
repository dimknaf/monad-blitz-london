# ASSAY

**Agents that get paid to judge reality — and get slashed when they're wrong.**

Built at Monad Blitz London, 8 August 2026.

A prediction market needs an oracle. For "what was the BTC price at noon" that's easy. For
*"did TSMC signal that AI demand is accelerating?"* there is no feed to read — it's a judgement
call about what a company conveyed. ASSAY makes that judgement a bonded, slashable, on-chain act.

Three research agents each read **different evidence**, independently, in their own processes.
Each posts a verdict with a bond. The contract takes the majority and **slashes the minority**.
Bettors stake on the outcome and collect from the losing pool.

Claims that *don't* need judgement don't get a panel: they settle straight from the filing.

---

## Live on Monad Testnet

**Contract:** [`0xA3A015F68289c9f4D959788CBddcc43655f7BA5F`](https://testnet.monadscan.com/address/0xA3A015F68289c9f4D959788CBddcc43655f7BA5F)

Everything is testnet. Faucet tokens, no real value, nobody is charged. `chain.py` asserts
chain id `10143` at startup and refuses to run anywhere else — including mainnet `143`.

## The two claim types

| | Judgement | Deterministic |
|---|---|---|
| Example | *TSMC signalled AI-accelerator demand is **accelerating** on its Q2 2026 call, vs its Q4 2025 outlook* | *ARM FY2026 revenue > $4.5bn* |
| Resolved by | three bonded research agents, majority wins | one HTTP request to `data.sec.gov` |
| Cost to resolve | a research bounty | nothing |
| On-chain evidence | each agent's source URL | the filing's accession number |

The ARM claim settles from ARM's own XBRL data: **$4,920,000,000**, form 20-F, accession
`0001973239-26-000097`. That accession goes on chain as the receipt — anyone can fetch the same
endpoint and check.

## The three oracles differ by evidence, not by instruction

None is told what to conclude. They differ in **what they are allowed to read**:

- **A — Primary Source Analyst** · what management itself said and published
- **B — Sell-Side Analyst** · what professional analysts concluded
- **C — Financial Press Analyst** · established press with editorial standards

Three agents on one document agree for the wrong reasons. Three on different evidence disagree
for real ones.

## Roles never mix

| Wallet | Role | May call |
|---|---|---|
| COORD | market operator | `openClaim`, `finalize`, `settleDeterministic` |
| AGENT A/B/C | **oracles** | `attest` (bonded, slashable), `withdraw` |
| BETTOR 1/2 | **punters** | `stake`, `claim`, `withdraw` |

An oracle never takes a position on the market it judges. `chain.py` asserts the role before
every transaction.

## The audit trail is the product

Every tool call an agent makes is logged — URL, bytes returned, seconds taken. The backend
cross-checks each citation against that agent's own log and marks it **VERIFIED** or
**UNVERIFIED**.

This catches real problems. In the recorded run, one agent voted with the majority and was
*correct* — but two of its three citations were search snippets it never actually opened. The
audit trail flags them. **That is the reason the verdict carries a bond.**

## The spec hash

Each claim's full resolution spec — period, metric, scope, source precedence, void conditions —
is hashed on open. The question is immutable; nobody can reinterpret it after seeing which way
it went. Specs live in [`data/claims/`](data/claims/).

---

## Run it

### 1 · Install

```bash
pip install openai-agents litellm playwright crawl4ai web3 flask pymupdf python-dotenv requests
playwright install chromium
```

### 2 · Configure

Create `.env` in the repo root:

```bash
DEEPINFRA_API_KEY=          # the three research agents
FIRECRAWL_API_KEY=          # optional: WEB_BACKEND=firecrawl, for bad wifi
MONAD_RPC=https://testnet-rpc.monad.xyz
SEC_IDENTITY=Your Name your@email.com   # data.sec.gov rejects anonymous requests

COORD_PK=      COORD_ADDR=              # market operator
AGENT_A_PK=    AGENT_A_ADDR=            # oracle
AGENT_B_PK=    AGENT_B_ADDR=            # oracle
AGENT_C_PK=    AGENT_C_ADDR=            # oracle
BETTOR_1_PK=   BETTOR_1_ADDR=           # punter
BETTOR_2_PK=   BETTOR_2_ADDR=           # punter

AGENT_MAX_TURNS=10
PAGE_LOAD_TIMEOUT=150000
PANEL_BUDGET_SECONDS=240   # hard wall-clock cap per agent
```

Generate the six throwaway keys with `eth_account`, then fund COORD from the
[Monad testnet faucet](https://testnet.monad.xyz) and run `python agents/chain.py fund` to
distribute. Oracles are funded above ~10 MON so Monad's reserve-balance throttle never bites.

### 3 · Run the demo — you control every step

```bash
python agents/server.py       # the console -> http://127.0.0.1:8080
```

Then drive it from the page and one terminal:

| # | You do | What happens |
|---|---|---|
| 1 | `python agents/chain.py open judgement` | A fresh claim opens. The spec is hashed on chain — the question is now immutable. Price reads 50/50 because nothing is staked. |
| 2 | **Click `STAKE 0.3 MON ▸ YES`** on the page | A real transaction. The implied probability moves. |
| 3 | **Click `STAKE 0.2 MON ▸ NO`** | Someone takes the other side. Price settles to the pool ratio, 60%. |
| 4 | **Click `▸ RUN THE PANEL`** | The three oracles start researching. Their tool calls, page fetches and quotes stream onto the page live, then verdicts land, bonds are posted, the contract finalizes and slashes, and the winning bettor collects. |

**Bets go in before the oracles start** — that is the whole point: you take a position without knowing the answer.

Prefer the terminal? Every step is a command:

```bash
python agents/panel.py           # the three oracles research, in parallel
python agents/chain.py attest    # each oracle posts its verdict + 0.1 MON bond
python agents/chain.py finalize  # contract tallies, slashes the minority
python agents/chain.py payout    # winning bettor collects the losing pool
python agents/chain.py settle    # market 2 settles from the SEC filing
python agents/chain.py status    # balances, claims, implied probability
```

`python run_demo.py` runs steps 4 onward in one go.

### Two markets, one contract

| | Market 1 · Judgement | Market 2 · Deterministic |
|---|---|---|
| Claim | TSMC signalled accelerating AI demand | ARM FY2026 revenue > $4.5bn |
| Resolved by | three bonded oracles, majority wins | one SEC filing |
| Cost | a research bounty | one HTTP request |
| Slashing | minority loses its bond | nobody — nothing to judge |

Same contract, same market primitive. The contrast is the point.

### 4 · Deploy from scratch

```bash
python agents/chain.py deploy              # writes out/contract.json
python agents/chain.py fund                # distribute MON to the six wallets
python agents/chain.py open judgement      # market 1
python agents/chain.py open deterministic  # market 2
python agents/server.py                    # the console -> http://127.0.0.1:8080
```

Then place the bets from the page and press **RUN THE PANEL** — or run `python run_demo.py`,
which does research → attest → finalize → payout → settle without touching the bets.

### Reset between runs

```bash
python agents/chain.py open judgement      # a fresh claim; the old one stays settled on chain
```

Old claims are never overwritten — every run is permanently on
[monadscan](https://testnet.monadscan.com/address/0xA3A015F68289c9f4D959788CBddcc43655f7BA5F).

### Every command

```bash
python agents/chain.py status              # balances, claims, implied probability
python agents/chain.py deploy              # deploy the contract
python agents/chain.py fund                # top up all six wallets from COORD
python agents/chain.py open <kind>         # judgement | deterministic
python agents/chain.py bet BETTOR_1 yes 0.3
python agents/panel.py                     # the three oracles, in parallel
python agents/chain.py attest              # bonded verdicts on chain
python agents/chain.py finalize            # tally and slash
python agents/chain.py payout              # winners collect
python agents/chain.py settle              # market 2, from the SEC filing
python agents/sec.py                       # the SEC lookup on its own
python agents/server.py                    # the console
python agents/server.py snapshot           # bake web/state.json for a static deploy
```

### Troubleshooting

| Symptom | Fix |
|---|---|
| Page looks stale | `python agents/server.py snapshot`, then reload |
| `429 Too Many Requests` | The public RPC is rate-limiting. The page keeps serving the last good state; wait ~20s. Use a private RPC in `MONAD_RPC` if you have one. |
| An oracle times out | Expected and handled — it posts no bond and is badged on the page. It is never counted as a dissent. |
| `REVERTED` on attest | The claim is already resolved, or that wallet already attested. Open a fresh claim. |
| Panel hangs | Ctrl-C. `attest` still works off the last good `out/agent_*.json`. |

The console is plain HTML/CSS/JS with no build step, no framework and no external requests. All
logic is server-side: the page fetches one file and copies strings onto nodes. The backend writes
`web/state.json` on a background thread, so a rate-limited RPC can never stall the page — and that
same file is what a static deploy serves.

## Stack

Solidity 0.8.24 · web3.py · [openai-agents](https://github.com/openai/openai-agents-python) +
LiteLLM on DeepInfra (`google/gemma-4-31B-it`) · Playwright + crawl4ai for browsing ·
PyMuPDF for filings · Flask.

## Roadmap

- **x402 micropayments** — pay each oracle per research request over
  [Monad's facilitator](https://x402-facilitator.molandak.org). The market pays for its own truth.
- **Static replay deployed to Vercel** — the console serves a baked snapshot, no browser needed
  in production.
- **Staking deadline at first attestation** — closes the window where a position could be taken
  after a verdict is already public.
- **ERC-8004 identity** — agent reputation that persists across claims, so a consistently
  slashed oracle is priced accordingly.

## Licence

MIT.
