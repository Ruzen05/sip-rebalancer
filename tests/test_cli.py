import json
from pathlib import Path

import pytest

from sip_rebalancer.cli import build_report, inr, load_portfolio, main

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "portfolio.json"


@pytest.mark.parametrize(
    "amount, expected",
    [
        (0, "₹0"),
        (999, "₹999"),
        (1_000, "₹1,000"),
        (100_000, "₹1,00,000"),
        (1_166_667, "₹11,66,667"),
        (12_34_56_789, "₹12,34,56,789"),
        (-50_000, "-₹50,000"),
    ],
)
def test_inr_uses_indian_grouping(amount, expected):
    assert inr(amount) == expected


def test_text_report(capsys):
    assert main([str(EXAMPLE)]) == 0
    out = capsys.readouterr().out
    assert "Nifty Midcap 150" in out
    assert "overweight" in out
    assert "₹2,66,667" in out
    assert "9 month(s)" in out


def test_json_report_with_horizon(capsys):
    assert main([str(EXAMPLE), "--json", "--horizon-months", "6"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert sum(s["amount"] for s in data["sip"]["split"]) == pytest.approx(30_000)
    assert data["horizon"]["required_monthly_sip"] == pytest.approx(44_444.44, abs=1e-2)
    assert data["needs_attention"] is True


def test_sip_override(capsys):
    main([str(EXAMPLE), "--json", "--sip", "50000"])
    data = json.loads(capsys.readouterr().out)
    assert data["sip"]["amount"] == 50_000
    assert data["sip"]["months_to_rebalance"] == 6


def test_full_rebalance_nets_to_cash(capsys):
    main([str(EXAMPLE), "--json", "--cash", "100000"])
    trades = json.loads(capsys.readouterr().out)["full_rebalance"]["trades"]
    net = sum(t["amount"] if t["action"] == "buy" else -t["amount"] for t in trades)
    assert net == pytest.approx(100_000, abs=3)


def test_units_and_nav_are_supported(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({
        "monthly_sip": 1000,
        "funds": [
            {"name": "A", "target_pct": 50, "units": 100, "nav": 10},
            {"name": "B", "target_pct": 50, "current_value": 1000},
        ],
    }))
    funds, _ = load_portfolio(str(path))
    assert funds[0].value == 1000
    report = build_report(funds, 1000)
    assert report["needs_attention"] is False


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"monthly_sip": 1000, "funds": [{"name": "A", "target_pct": 60, "current_value": 1},
                                         {"name": "B", "target_pct": 30, "current_value": 1}]}, "add up to 100"),
        ({"funds": [{"name": "A", "target_pct": 50, "current_value": 1},
                    {"name": "B", "target_pct": 50, "current_value": 1}]}, "monthly SIP"),
        ({"monthly_sip": 1000, "funds": [{"name": "A", "target_pct": 50},
                                         {"name": "B", "target_pct": 50, "current_value": 1}]}, "fund #1"),
    ],
)
def test_bad_config_exits_with_error(tmp_path, capsys, payload, message):
    path = tmp_path / "p.json"
    path.write_text(json.dumps(payload))
    assert main([str(path)]) == 2
    assert message in capsys.readouterr().err


def test_missing_file(capsys):
    assert main(["does-not-exist.json"]) == 2
    assert "cannot read" in capsys.readouterr().err
