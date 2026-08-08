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

```bash
pip install openai-agents litellm playwright crawl4ai web3 flask pymupdf python-dotenv
playwright install chromium

cp .env.example .env        # add your keys
python agents/chain.py deploy
python run_demo.py --reset  # the full arc
python agents/server.py     # the console, http://127.0.0.1:8080
```

The console is plain HTML/CSS/JS with no build step. All logic is server-side — the page renders
strings it is handed and computes nothing.

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
