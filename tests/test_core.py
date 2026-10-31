import pytest

from sip_rebalancer.core import (
    Fund,
    PortfolioError,
    allocate_sip,
    annual_stepup_needed,
    contributions_total,
    drift_report,
    lump_sum_trades,
    months_to_rebalance,
    required_extra_contribution,
    required_monthly_sip,
    round_allocation,
    total_value,
    validate,
)

FUNDS = [
    Fund("Nifty 50", 50, 420_000),
    Fund("Nifty Next 50", 20, 130_000),
    Fund("Nifty Midcap 150", 30, 350_000),
]


def simulate(funds, sip, months):
    """Invest `sip` for `months` months with no market movement."""
    values = {f.name: f.value for f in funds}
    for _ in range(months):
        step = [Fund(f.name, f.target_pct, values[f.name]) for f in funds]
        for name, amount in allocate_sip(step, sip).items():
            values[name] += amount
    return values


def pct(values):
    total = sum(values.values())
    return {k: 100 * v / total for k, v in values.items()}


# ------------------------------------------------------------- validation
def test_validate_accepts_good_portfolio():
    validate(FUNDS)


@pytest.mark.parametrize(
    "funds",
    [
        [Fund("A", 100, 10)],                              # single fund
        [Fund("A", 60, 10), Fund("B", 30, 10)],            # targets != 100
        [Fund("A", 50, 10), Fund("A", 50, 10)],            # duplicate names
        [Fund("A", 50, -1), Fund("B", 50, 10)],            # negative value
        [Fund("A", 0, 10), Fund("B", 100, 10)],            # zero target
    ],
)
def test_validate_rejects_bad_input(funds):
    with pytest.raises(PortfolioError):
        validate(funds)


# ------------------------------------------------------------------ drift
def test_drift_report():
    rows = {r.name: r for r in drift_report(FUNDS)}
    assert rows["Nifty Midcap 150"].current_pct == pytest.approx(38.888, abs=1e-2)
    assert rows["Nifty Midcap 150"].drift_pp == pytest.approx(8.888, abs=1e-2)
    assert rows["Nifty Next 50"].drift_pp < 0


# ---------------------------------------------------------- SIP allocation
def test_allocation_sums_to_amount_and_is_never_negative():
    alloc = allocate_sip(FUNDS, 30_000)
    assert sum(alloc.values()) == pytest.approx(30_000)
    assert all(v >= 0 for v in alloc.values())


def test_allocation_goes_to_the_most_underweight_fund_first():
    alloc = allocate_sip(FUNDS, 30_000)
    assert alloc["Nifty Next 50"] == pytest.approx(30_000)
    assert alloc["Nifty Midcap 150"] == 0


def test_allocation_spreads_when_every_fund_can_absorb_money():
    alloc = allocate_sip(FUNDS, 200_000)
    assert sum(alloc.values()) == pytest.approx(200_000)
    assert alloc["Nifty Midcap 150"] == 0  # still over target after 2 lakh
    assert alloc["Nifty 50"] > 0 and alloc["Nifty Next 50"] > 0


def test_balanced_portfolio_follows_targets():
    funds = [Fund("A", 50, 500), Fund("B", 20, 200), Fund("C", 30, 300)]
    alloc = allocate_sip(funds, 1000)
    assert alloc == pytest.approx({"A": 500, "B": 200, "C": 300})


def test_empty_portfolio_follows_targets():
    funds = [Fund("A", 50, 0), Fund("B", 50, 0)]
    assert allocate_sip(funds, 1000) == pytest.approx({"A": 500, "B": 500})


def test_zero_contribution():
    assert allocate_sip(FUNDS, 0) == {f.name: 0.0 for f in FUNDS}


def test_round_allocation_keeps_total():
    alloc = {"a": 100.4, "b": 199.6, "c": 300.0}
    assert round_allocation(alloc, 100) == {"a": 100, "b": 200, "c": 300}
    messy = {"a": 10_000 / 3, "b": 10_000 / 3, "c": 10_000 / 3}
    assert sum(round_allocation(messy, 1).values()) == 10_000


# -------------------------------------------------------- how long / how much
def test_required_extra_contribution():
    assert required_extra_contribution(FUNDS) == pytest.approx(266_666.667, abs=1e-2)


def test_no_extra_needed_when_balanced():
    funds = [Fund("A", 50, 500), Fund("B", 50, 500)]
    assert required_extra_contribution(funds) == 0
    assert months_to_rebalance(funds, 1000) == 0


def test_months_to_rebalance():
    assert months_to_rebalance(FUNDS, 30_000) == 9
    assert months_to_rebalance(FUNDS, 0) is None


def test_required_monthly_sip():
    assert required_monthly_sip(FUNDS, 6) == pytest.approx(44_444.44, abs=1e-2)
    with pytest.raises(PortfolioError):
        required_monthly_sip(FUNDS, 0)


def test_closed_form_matches_month_by_month_simulation():
    """9 months of ₹30,000 reaches target; 8 months does not."""
    after_9 = pct(simulate(FUNDS, 30_000, 9))
    for f in FUNDS:
        assert after_9[f.name] == pytest.approx(f.target_pct, abs=1e-6)
    after_8 = pct(simulate(FUNDS, 30_000, 8))
    assert after_8["Nifty Midcap 150"] > 30 + 1e-3


# ---------------------------------------------------------------- step-up
def test_annual_stepup_hits_the_needed_total():
    needed = 500_000
    g = annual_stepup_needed(10_000, 36, needed)
    assert g is not None and g > 0
    assert contributions_total(10_000, g, 36) == pytest.approx(needed, rel=1e-6)


def test_stepup_is_zero_when_flat_sip_is_enough():
    assert annual_stepup_needed(50_000, 12, 100_000) == 0.0


def test_stepup_cannot_help_within_a_year():
    assert annual_stepup_needed(10_000, 12, 500_000) is None
    assert annual_stepup_needed(0, 36, 500_000) is None


# ---------------------------------------------------------- full rebalance
def test_full_rebalance_reaches_targets():
    trades = lump_sum_trades(FUNDS)
    assert sum(trades.values()) == pytest.approx(0, abs=1e-6)
    after = {f.name: f.value + trades[f.name] for f in FUNDS}
    for f in FUNDS:
        assert 100 * after[f.name] / total_value(FUNDS) == pytest.approx(f.target_pct)


def test_full_rebalance_with_new_cash():
    trades = lump_sum_trades(FUNDS, cash=100_000)
    assert sum(trades.values()) == pytest.approx(100_000)


def test_buy_only_rebalance_never_sells():
    trades = lump_sum_trades(FUNDS, cash=50_000, allow_sell=False)
    assert all(v >= 0 for v in trades.values())
    assert sum(trades.values()) == pytest.approx(50_000)
