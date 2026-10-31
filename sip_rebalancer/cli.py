"""Command-line interface for the SIP & index rebalancer."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .core import (
    Fund,
    PortfolioError,
    allocate_sip,
    annual_stepup_needed,
    drift_report,
    lump_sum_trades,
    months_to_rebalance,
    required_extra_contribution,
    required_monthly_sip,
    round_allocation,
    total_value,
    validate,
)

DEFAULT_THRESHOLD_PP = 5.0


# ---------------------------------------------------------------- formatting
def inr(amount: float) -> str:
    """Format a number with Indian digit grouping, e.g. 1166667 -> ₹11,66,667."""
    sign = "-" if amount < 0 else ""
    digits = str(int(round(abs(amount))))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        parts: List[str] = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        digits = ",".join(parts + [tail])
    return f"{sign}₹{digits}"


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]], right: Sequence[int] = ()) -> str:
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)]

    def fmt(row: Sequence[Any]) -> str:
        cells = []
        for i, cell in enumerate(row):
            text = str(cell)
            cells.append(text.rjust(widths[i]) if i in right else text.ljust(widths[i]))
        return "  ".join(cells).rstrip()

    lines = [fmt(headers), "  ".join("-" * w for w in widths)]
    lines += [fmt(r) for r in rows]
    return "\n".join(lines)


# ------------------------------------------------------------------- input
def load_portfolio(path: str) -> Tuple[List[Fund], Dict[str, Any]]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as exc:
        raise PortfolioError(f"cannot read {path}: {exc.strerror}") from exc
    except json.JSONDecodeError as exc:
        raise PortfolioError(f"{path} is not valid JSON: {exc}") from exc

    funds: List[Fund] = []
    for i, item in enumerate(data.get("funds", []), start=1):
        try:
            if "current_value" in item:
                value = float(item["current_value"])
            else:
                value = float(item["units"]) * float(item["nav"])
            funds.append(Fund(str(item["name"]), float(item["target_pct"]), value))
        except (KeyError, TypeError, ValueError) as exc:
            raise PortfolioError(
                f"fund #{i} is invalid: needs name, target_pct and either "
                f"current_value or units + nav ({exc!r})"
            ) from exc
    return funds, data


# ------------------------------------------------------------------ report
def _status(drift_pp: float, threshold_pp: float) -> str:
    if drift_pp > threshold_pp:
        return "overweight"
    if drift_pp < -threshold_pp:
        return "underweight"
    return "ok"


def _round(value: float, step: float) -> float:
    return round(value / step) * step if step else value


def build_report(
    funds: Sequence[Fund],
    sip: float,
    *,
    horizon_months: Optional[int] = None,
    cash: float = 0.0,
    full: bool = False,
    round_to: float = 1.0,
    threshold_pp: float = DEFAULT_THRESHOLD_PP,
) -> Dict[str, Any]:
    validate(funds)
    total = total_value(funds)

    portfolio = [
        {**asdict(row), "status": _status(row.drift_pp, threshold_pp)}
        for row in drift_report(funds)
    ]

    split = allocate_sip(funds, sip)
    if round_to:
        split = round_allocation(split, round_to)
    extra = required_extra_contribution(funds)

    report: Dict[str, Any] = {
        "total_value": total,
        "threshold_pp": threshold_pp,
        "portfolio": portfolio,
        "needs_attention": any(p["status"] != "ok" for p in portfolio),
        "sip": {
            "amount": sip,
            "split": [
                {
                    "name": f.name,
                    "amount": split[f.name],
                    "pct_of_sip": (100.0 * split[f.name] / sip) if sip > 0 else 0.0,
                }
                for f in funds
            ],
            "extra_needed_to_reach_target": extra,
            "months_to_rebalance": months_to_rebalance(funds, sip),
        },
        "horizon": None,
        "full_rebalance": None,
    }

    if horizon_months:
        required = required_monthly_sip(funds, horizon_months)
        stepup = annual_stepup_needed(sip, horizon_months, extra)
        report["horizon"] = {
            "months": horizon_months,
            "required_monthly_sip": required,
            "increase_vs_current": max(required - sip, 0.0),
            "increase_pct": (100.0 * (required - sip) / sip) if sip > 0 and required > sip else 0.0,
            "already_sufficient": required <= sip + 1e-9,
            "annual_stepup_pct": None if stepup is None else 100.0 * stepup,
        }

    if full:
        trades = lump_sum_trades(funds, cash, allow_sell=True)
        rows = []
        for f in funds:
            amount = _round(trades[f.name], round_to)
            action = "buy" if amount > 0 else "sell" if amount < 0 else "hold"
            rows.append({"name": f.name, "action": action, "amount": abs(amount)})
        report["full_rebalance"] = {"cash": cash, "trades": rows}

    return report


def render_text(report: Dict[str, Any]) -> str:
    out: List[str] = []

    out.append(f"PORTFOLIO  (total {inr(report['total_value'])}, drift threshold ±{report['threshold_pp']:g} pp)")
    out.append(
        _table(
            ["Index", "Value", "Current", "Target", "Drift", "Status"],
            [
                [
                    p["name"],
                    inr(p["value"]),
                    f"{p['current_pct']:.1f}%",
                    f"{p['target_pct']:.1f}%",
                    f"{p['drift_pp']:+.1f} pp",
                    p["status"],
                ]
                for p in report["portfolio"]
            ],
            right=(1, 2, 3, 4),
        )
    )

    sip = report["sip"]
    out.append("")
    out.append(f"THIS MONTH'S SIP: {inr(sip['amount'])}")
    out.append(
        _table(
            ["Index", "Invest", "% of SIP"],
            [[s["name"], inr(s["amount"]), f"{s['pct_of_sip']:.1f}%"] for s in sip["split"]],
            right=(1, 2),
        )
    )
    if sip["extra_needed_to_reach_target"] <= 0:
        out.append("Portfolio is already at target, so the SIP is split in target proportions.")
    else:
        out.append(f"Buy-only, {inr(sip['extra_needed_to_reach_target'])} of new money is needed to reach target.")
        months = sip["months_to_rebalance"]
        if months is None:
            out.append("With a zero SIP, contributions alone cannot rebalance the portfolio.")
        else:
            out.append(f"At {inr(sip['amount'])}/month and no market movement, that takes {months} month(s).")

    h = report["horizon"]
    if h:
        out.append("")
        out.append(f"TO REACH TARGET WITHIN {h['months']} MONTH(S)")
        if h["already_sufficient"]:
            out.append(f"Your current SIP already covers it (needs {inr(h['required_monthly_sip'])}/month).")
        else:
            out.append(
                f"Flat SIP needed: {inr(h['required_monthly_sip'])}/month "
                f"(+{inr(h['increase_vs_current'])}, +{h['increase_pct']:.1f}% vs current)."
            )
            if h["months"] <= 12:
                out.append("A yearly step-up cannot help within 12 months, so raise the SIP itself.")
            elif h["annual_stepup_pct"] is None:
                out.append("A yearly step-up alone cannot get there in this horizon.")
            else:
                out.append(
                    f"Or keep the current SIP and step it up by {h['annual_stepup_pct']:.1f}% every 12 months."
                )

    fr = report["full_rebalance"]
    if fr:
        out.append("")
        title = "FULL REBALANCE"
        if fr["cash"]:
            title += f" (with {inr(fr['cash'])} of new cash)"
        out.append(title)
        out.append(
            _table(
                ["Index", "Action", "Amount"],
                [[t["name"], t["action"], inr(t["amount"])] for t in fr["trades"]],
                right=(2,),
            )
        )
        if any(t["action"] == "sell" for t in fr["trades"]):
            out.append("Selling can trigger capital gains tax and exit loads; check these before acting.")

    out.append("")
    out.append("Assumes no market movement between contributions, so re-run it every month.")
    out.append("Educational tool, not investment advice.")
    return "\n".join(out)


# --------------------------------------------------------------------- main
def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sip-rebalance",
        description="Work out the SIP split and step-up needed to hold a target index allocation.",
    )
    p.add_argument("config", help="path to the portfolio JSON file")
    p.add_argument("--sip", type=float, help="monthly SIP amount (overrides the config file)")
    p.add_argument("--horizon-months", type=int, metavar="N", help="also show the SIP needed to reach target in N months")
    p.add_argument("--full", action="store_true", help="also show the buy/sell trades for an immediate full rebalance")
    p.add_argument("--cash", type=float, default=0.0, help="extra lump-sum cash to include in a full rebalance (implies --full)")
    p.add_argument("--threshold", type=float, help=f"drift (in pp) before a fund is flagged (default {DEFAULT_THRESHOLD_PP:g})")
    p.add_argument("--round-to", type=float, default=1.0, help="round amounts to a multiple of this (default 1, use 0 for no rounding)")
    p.add_argument("--json", action="store_true", help="print the report as JSON")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")  # so ₹ prints on Windows consoles
        funds, config = load_portfolio(args.config)
        sip = args.sip if args.sip is not None else config.get("monthly_sip")
        if sip is None:
            raise PortfolioError("monthly SIP not set: add 'monthly_sip' to the config or pass --sip")
        threshold = args.threshold if args.threshold is not None else float(
            config.get("drift_threshold_pp", DEFAULT_THRESHOLD_PP)
        )
        report = build_report(
            funds,
            float(sip),
            horizon_months=args.horizon_months,
            cash=args.cash,
            full=args.full or args.cash > 0,
            round_to=args.round_to,
            threshold_pp=threshold,
        )
    except PortfolioError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else render_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
