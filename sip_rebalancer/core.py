"""Pure portfolio maths for SIP-based index rebalancing.

No I/O and no network access, so everything here is unit-testable.
Money amounts are plain floats in a single currency (INR in the examples).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

EPS = 1e-9


class PortfolioError(ValueError):
    """Raised when the portfolio input is invalid."""


@dataclass(frozen=True)
class Fund:
    name: str
    target_pct: float  # desired share of the portfolio, in percent
    value: float       # current market value


@dataclass(frozen=True)
class DriftRow:
    name: str
    value: float
    current_pct: float
    target_pct: float
    drift_pp: float    # current minus target, in percentage points


def validate(funds: Sequence[Fund]) -> None:
    if len(funds) < 2:
        raise PortfolioError("need at least two funds to rebalance")
    names = [f.name for f in funds]
    if len(set(names)) != len(names):
        raise PortfolioError("fund names must be unique")
    for f in funds:
        if f.target_pct <= 0:
            raise PortfolioError(f"target for '{f.name}' must be greater than 0")
        if f.value < 0:
            raise PortfolioError(f"value for '{f.name}' cannot be negative")
    total_target = sum(f.target_pct for f in funds)
    if abs(total_target - 100.0) > 1e-6:
        raise PortfolioError(f"targets must add up to 100 (got {total_target:g})")


def total_value(funds: Sequence[Fund]) -> float:
    return sum(f.value for f in funds)


def drift_report(funds: Sequence[Fund]) -> List[DriftRow]:
    total = total_value(funds)
    rows = []
    for f in funds:
        current = 100.0 * f.value / total if total > 0 else 0.0
        rows.append(DriftRow(f.name, f.value, current, f.target_pct, current - f.target_pct))
    return rows


def allocate_sip(funds: Sequence[Fund], amount: float) -> Dict[str, float]:
    """Split one contribution so the portfolio ends as close to target as possible.

    Buy-only "water-filling": funds that are already above their target share
    after the contribution get nothing, and the money goes to the rest in the
    amounts that bring them to a common, target-proportional level.
    """
    if amount < 0:
        raise PortfolioError("contribution cannot be negative")
    alloc = {f.name: 0.0 for f in funds}
    if amount <= EPS:
        return alloc

    active = list(funds)
    while True:
        pool = sum(f.value for f in active) + amount
        weight = sum(f.target_pct for f in active)
        need = {f.name: pool * f.target_pct / weight - f.value for f in active}
        # Funds that would need a negative buy stay negative once removed, so
        # dropping them all at once is safe. The needs of the remaining funds
        # always sum to `amount`, so `active` can never become empty.
        keep = [f for f in active if need[f.name] >= -EPS]
        if len(keep) == len(active):
            for f in active:
                alloc[f.name] = max(need[f.name], 0.0)
            return alloc
        active = keep


def round_allocation(alloc: Dict[str, float], step: float) -> Dict[str, float]:
    """Round amounts to a multiple of `step` while keeping the total intact
    (largest-remainder method)."""
    if step <= 0:
        raise PortfolioError("rounding step must be greater than 0")
    total_units = round(sum(alloc.values()) / step)
    units = {k: math.floor(v / step + EPS) for k, v in alloc.items()}
    remainder = total_units - sum(units.values())
    order = sorted(alloc, key=lambda k: alloc[k] / step - units[k], reverse=True)
    for k in order[: max(remainder, 0)]:
        units[k] += 1
    return {k: u * step for k, u in units.items()}


def required_extra_contribution(funds: Sequence[Fund]) -> float:
    """Smallest total new money that, invested buy-only, restores exact targets.

    The most over-weight fund fixes the size of the final portfolio: it can't
    be sold, so everything else has to grow around it.
    """
    total = total_value(funds)
    final_total = max(f.value / (f.target_pct / 100.0) for f in funds)
    extra = final_total - total
    return extra if extra > 1e-6 else 0.0


def months_to_rebalance(funds: Sequence[Fund], monthly_sip: float) -> Optional[int]:
    """Months of a flat SIP needed to reach target (assuming no market movement).
    Returns None when the SIP is zero but rebalancing is needed."""
    extra = required_extra_contribution(funds)
    if extra <= EPS:
        return 0
    if monthly_sip <= EPS:
        return None
    return math.ceil(extra / monthly_sip - EPS)


def required_monthly_sip(funds: Sequence[Fund], months: int) -> float:
    """Flat monthly SIP that reaches target in exactly `months` months."""
    if months < 1:
        raise PortfolioError("horizon must be at least 1 month")
    return required_extra_contribution(funds) / months


def contributions_total(initial_sip: float, annual_stepup: float, months: int) -> float:
    """Total contributed over `months` when the SIP rises by `annual_stepup`
    (0.10 = 10%) at the start of every 12th month."""
    return sum(initial_sip * (1.0 + annual_stepup) ** (m // 12) for m in range(months))


def annual_stepup_needed(
    current_sip: float, months: int, needed_total: float, max_stepup: float = 10.0
) -> Optional[float]:
    """Annual step-up (as a fraction) so that the SIP contributes `needed_total`
    within `months`. Returns 0.0 if no step-up is needed and None if even
    `max_stepup` is not enough (for example a horizon of 12 months or less,
    where a yearly step-up never kicks in)."""
    if needed_total <= EPS:
        return 0.0
    if current_sip <= EPS:
        return None
    if contributions_total(current_sip, 0.0, months) >= needed_total - EPS:
        return 0.0
    if contributions_total(current_sip, max_stepup, months) < needed_total:
        return None
    lo, hi = 0.0, max_stepup
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if contributions_total(current_sip, mid, months) < needed_total:
            lo = mid
        else:
            hi = mid
    return hi


def lump_sum_trades(
    funds: Sequence[Fund], cash: float = 0.0, allow_sell: bool = True
) -> Dict[str, float]:
    """Signed trade per fund (positive = buy, negative = sell) that reaches the
    target allocation immediately. With allow_sell=False it only buys."""
    if cash < 0:
        raise PortfolioError("cash cannot be negative")
    if not allow_sell:
        return allocate_sip(funds, cash)
    pool = total_value(funds) + cash
    return {f.name: pool * f.target_pct / 100.0 - f.value for f in funds}
