# SIP & Index Rebalancer

[![Tests](https://github.com/Ruzen05/sip-rebalancer/actions/workflows/tests.yml/badge.svg)](https://github.com/Ruzen05/sip-rebalancer/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

A command-line tool that keeps an index-fund portfolio (for example **Nifty 50**, **Nifty Next 50** and **Nifty Midcap 150**) on its target allocation *by directing new SIP money*, so you don't have to sell anything.

Every month it tells you:

1. **How far each index has drifted** from its target weight.
2. **Exactly how to split this month's SIP** across the indices.
3. **How long** your current SIP needs to restore the target, or **what SIP / yearly step-up** you need to get there within a deadline you choose.
4. *(Optional)* the exact **buy/sell trades** for an immediate full rebalance.

It uses only the Python standard library.

## Install

```bash
git clone https://github.com/Ruzen05/sip-rebalancer.git
cd sip-rebalancer
pip install -e .
```

You can also run it without installing: `python -m sip_rebalancer examples/portfolio.json`.

## Usage

1. Copy `examples/portfolio.json` and put in your own numbers (see below).
2. Run:

```bash
sip-rebalance portfolio.json
sip-rebalance portfolio.json --horizon-months 6 --full
```

### Example output

```text
PORTFOLIO  (total ₹9,00,000, drift threshold ±5 pp)
Index                 Value  Current  Target    Drift  Status
----------------  ---------  -------  ------  -------  -----------
Nifty 50          ₹4,20,000    46.7%   50.0%  -3.3 pp  ok
Nifty Next 50     ₹1,30,000    14.4%   20.0%  -5.6 pp  underweight
Nifty Midcap 150  ₹3,50,000    38.9%   30.0%  +8.9 pp  overweight

THIS MONTH'S SIP: ₹30,000
Index              Invest  % of SIP
----------------  -------  --------
Nifty 50               ₹0      0.0%
Nifty Next 50     ₹30,000    100.0%
Nifty Midcap 150       ₹0      0.0%
Buy-only, ₹2,66,667 of new money is needed to reach target.
At ₹30,000/month and no market movement, that takes 9 month(s).

TO REACH TARGET WITHIN 6 MONTH(S)
Flat SIP needed: ₹44,444/month (+₹14,444, +48.1% vs current).
A yearly step-up cannot help within 12 months, so raise the SIP itself.

FULL REBALANCE
Index             Action   Amount
----------------  ------  -------
Nifty 50          buy     ₹30,000
Nifty Next 50     buy     ₹50,000
Nifty Midcap 150  sell    ₹80,000
Selling can trigger capital gains tax and exit loads; check these before acting.

Assumes no market movement between contributions, so re-run it every month.
Educational tool, not investment advice.
```

### Config file

```json
{
  "monthly_sip": 30000,
  "drift_threshold_pp": 5,
  "funds": [
    { "name": "Nifty 50",         "target_pct": 50, "current_value": 420000 },
    { "name": "Nifty Next 50",    "target_pct": 20, "current_value": 130000 },
    { "name": "Nifty Midcap 150", "target_pct": 30, "current_value": 350000 }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `monthly_sip` | Your current monthly SIP. Can be overridden with `--sip`. |
| `drift_threshold_pp` | Percentage points of drift before a fund is flagged (default 5). |
| `funds[].name` | Label for the index or fund. Must be unique. |
| `funds[].target_pct` | Target share of the portfolio. Must be above 0 and all targets must add up to 100. |
| `funds[].current_value` | Current market value. Instead, you can give `units` and `nav` and the tool multiplies them. |

### Command-line options

| Option | Purpose |
| --- | --- |
| `--sip N` | Override the monthly SIP from the config. |
| `--horizon-months N` | Also show the SIP (and yearly step-up) needed to reach target in N months. |
| `--full` | Also show buy/sell trades for an immediate full rebalance. |
| `--cash N` | Extra lump-sum cash to include in the full rebalance (implies `--full`). |
| `--threshold N` | Drift in percentage points before a fund is flagged. |
| `--round-to N` | Round amounts to a multiple of N (default 1; `0` disables rounding). |
| `--json` | Print the report as JSON, for scripts and automation. |

## How the maths works

All of it lives in [`sip_rebalancer/core.py`](sip_rebalancer/core.py) as pure functions with no I/O.

- **Splitting a SIP.** Funds already above their target share receive nothing. The money goes to the remaining funds in the amounts that bring them to a common, target-proportional level (a buy-only "water-filling" step). If no fund is over target, the SIP is simply split by target weights.
- **Extra money needed.** Because nothing is sold, the most over-weight fund decides the final portfolio size: `final_total = max(value_i / target_i)`. The extra money required is `final_total - current_total`.
- **Months to rebalance.** `ceil(extra_money / monthly_sip)`. Tests check this against a month-by-month simulation.
- **Required SIP for a deadline.** `extra_money / months`.
- **Yearly step-up.** Solved numerically (bisection) so that a SIP rising by *g* at the start of every 12th month contributes the required total within the horizon. A step-up never applies within the first 12 months, and the tool says so.
- **Rounding.** Amounts are rounded with the largest-remainder method, so the rounded split still adds up exactly to your SIP.

## Limitations

- It assumes **no market movement** between contributions. Real prices move, so re-run the tool every month with fresh values.
- You supply current values by hand (or via `units` x `nav`). It does not fetch live NAVs.
- It ignores taxes, exit loads and fund expense ratios, which matter for the full-rebalance (sell) option.
- Targets must be above 0, and at least two funds are needed.

## Development

```bash
pip install -e ".[dev]"
pytest
```

## Roadmap

- [ ] Fetch live NAVs for each fund
- [ ] Import holdings from a broker or fund-house CSV export
- [ ] Scheduled monthly run with an email or Telegram summary
- [ ] Per-fund minimum SIP amounts and lot sizes
- [ ] Optional rebalancing bands (only act when drift passes a limit)

## Disclaimer

This is an educational tool. It is not investment, tax or legal advice, and I'm not a financial advisor. Check the numbers and talk to a qualified professional before making financial decisions.

## License

MIT. See [LICENSE](LICENSE).
