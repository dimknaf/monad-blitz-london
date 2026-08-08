# ARM Holdings plc FY2026 revenue exceeded $4.5 billion

## Claim

ARM Holdings plc reported revenue greater than USD 4,500,000,000 for the fiscal year ended
31 March 2026.

## Resolution method

No panel. This settles from the company's own XBRL filing data, published by the SEC. There is
nothing to judge, so nothing to bond and nobody to slash — the cost of resolution is one HTTP
request.

## Source

`data.sec.gov/api/xbrl/companyconcept/CIK0001973239/us-gaap/RevenueFromContractWithCustomerExcludingAssessedTax.json`

## Selection rule

The datapoint is selected by the triple `(start = 2025-04-01, end = 2026-03-31, form = 20-F)`.
Where the same period appears in more than one filing — the SEC re-reports prior years in each
new filing — the latest `filed` date wins.

**Selection is never by the `frame` field.** ARM's fiscal year ending 31 March 2026 carries the
frame label `CY2025`, so anyone matching on frame settles the wrong year. This is the single
trap in the dataset and it is the reason the rule is written down before resolution rather than
after.

Two further notes: ARM files a **20-F**, not a 10-K; and SoftBank consolidates ARM in JPY under
IFRS, so the scope is fixed by CIK, not by company name.

## Settlement

The filing's accession number is written on chain as the evidence URI. Anyone can fetch the same
endpoint and check the number themselves.
