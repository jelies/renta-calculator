"""Tests para los helpers del parser de Koinly (sin PDFs reales)."""

from datetime import datetime
from decimal import Decimal

import pytest

from renta.parsers.koinly import (
    _GAIN_RE,
    _REWARD_RE,
    _parse_datetime,
    _parse_decimal,
    _parse_capital_gains,
    _parse_rewards,
    validate,
)
from renta.models import CryptoCapitalGain, CryptoReward, KoinlyData


# ---------------------------------------------------------------------------
# _parse_datetime
# ---------------------------------------------------------------------------

class TestParseDatetime:
    def test_valid_datetime(self):
        result = _parse_datetime("29/07/2024 14:35")
        assert result == datetime(2024, 7, 29, 14, 35)

    def test_midnight(self):
        result = _parse_datetime("01/01/2024 00:00")
        assert result == datetime(2024, 1, 1, 0, 0)

    def test_invalid_returns_none(self):
        assert _parse_datetime("foo") is None

    def test_empty_returns_none(self):
        assert _parse_datetime("") is None

    def test_wrong_format_returns_none(self):
        assert _parse_datetime("2024-07-29 14:35") is None


# ---------------------------------------------------------------------------
# _parse_decimal
# ---------------------------------------------------------------------------

class TestKoinlyParseDecimal:
    def test_plain_number(self):
        assert _parse_decimal("15.55") == Decimal("15.55")

    def test_negative(self):
        assert _parse_decimal("-82.27") == Decimal("-82.27")

    def test_with_comma(self):
        assert _parse_decimal("1,234.56") == Decimal("1234.56")

    def test_zero(self):
        assert _parse_decimal("0.00") == Decimal("0.00")

    def test_invalid_returns_none(self):
        assert _parse_decimal("N/A") is None


# ---------------------------------------------------------------------------
# Regexes
# ---------------------------------------------------------------------------

class TestGainRe:
    def test_matches_capital_gain_line(self):
        line = "29/07/2024 14:35 17/01/2018 23:10 BTC 0.00152000 15.55 97.82 82.27 Kraken"
        m = _GAIN_RE.match(line)
        assert m is not None
        assert m.group(1) == "29/07/2024 14:35"
        assert m.group(2) == "17/01/2018 23:10"
        assert m.group(3) == "BTC"
        assert m.group(4) == "0.00152000"
        assert m.group(5) == "15.55"
        assert m.group(6) == "97.82"

    def test_no_match_on_reward_line(self):
        line = "01/01/2024 01:00 ADA 0.00006762 0.00 Reward Flexible REALTIME Binance"
        assert _GAIN_RE.match(line) is None

    def test_matches_with_notes_and_wallet(self):
        line = "29/07/2024 14:35 17/01/2018 23:10 ETH 1.00000000 100.00 150.00 50.00 Some note Kraken"
        m = _GAIN_RE.match(line)
        assert m is not None
        assert "Kraken" in m.group(9)


class TestRewardRe:
    def test_matches_ada_reward(self):
        line = "01/01/2024 01:00 ADA 0.00006762 0.00 Reward Flexible REALTIME Binance"
        m = _REWARD_RE.match(line)
        assert m is not None
        assert m.group(1) == "01/01/2024 01:00"
        assert m.group(2) == "ADA"
        assert m.group(3) == "0.00006762"
        assert m.group(4) == "0.00"
        assert m.group(5) == "Reward"

    def test_matches_steth_reward(self):
        line = "01/01/2024 13:22 STETH 0.00004390 0.09 Reward stETH"
        m = _REWARD_RE.match(line)
        assert m is not None
        assert m.group(2) == "STETH"

    def test_no_match_on_gain_line(self):
        line = "29/07/2024 14:35 17/01/2018 23:10 BTC 0.00152000 15.55 97.82 82.27 Kraken"
        assert _REWARD_RE.match(line) is None


# ---------------------------------------------------------------------------
# _parse_capital_gains
# ---------------------------------------------------------------------------

class TestParseCapitalGains:
    def _pages_text_with_gains(self, lines: list[str]) -> list[str]:
        """Crea pages_text con los datos en la página índice 0."""
        return ["\n".join(lines)]

    def test_parses_single_gain(self):
        pages_text = self._pages_text_with_gains([
            "29/07/2024 14:35 17/01/2018 23:10 BTC 0.00152000 15.55 97.82 82.27 Kraken",
        ])
        gains = _parse_capital_gains([0], pages_text, "koinly.pdf")
        assert len(gains) == 1
        g = gains[0]
        assert g.date_sold == datetime(2024, 7, 29, 14, 35)
        assert g.date_acquired == datetime(2018, 1, 17, 23, 10)
        assert g.asset == "BTC"
        assert g.cost_eur == Decimal("15.55")
        assert g.proceeds_eur == Decimal("97.82")
        assert g.gain_loss_eur == Decimal("82.27")
        assert g.wallet == "Kraken"

    def test_parses_multiple_gains(self):
        pages_text = self._pages_text_with_gains([
            "29/07/2024 14:35 17/01/2018 23:10 BTC 0.00152000 15.55 97.82 82.27 Kraken",
            "01/03/2024 10:00 17/01/2019 12:00 ETH 0.50000000 100.00 200.00 100.00 Coinbase",
        ])
        gains = _parse_capital_gains([0], pages_text, "koinly.pdf")
        assert len(gains) == 2

    def test_skips_header_and_blank_lines(self):
        pages_text = self._pages_text_with_gains([
            "Operaciones de Ganancias Patrimoniales",
            "Fecha de venta Fecha de adquisición Activo ...",
            "",
            "29/07/2024 14:35 17/01/2018 23:10 BTC 0.00152000 15.55 97.82 82.27 Kraken",
        ])
        gains = _parse_capital_gains([0], pages_text, "koinly.pdf")
        assert len(gains) == 1

    def test_source_ref_populated(self):
        pages_text = self._pages_text_with_gains([
            "29/07/2024 14:35 17/01/2018 23:10 BTC 0.00152000 15.55 97.82 82.27 Kraken",
        ])
        gains = _parse_capital_gains([0], pages_text, "test.pdf")
        assert gains[0].source.file == "test.pdf"
        assert gains[0].source.page == 1  # page_num_0=0 → page=1
        assert gains[0].source.section == "Operaciones de Ganancias Patrimoniales"

    def test_empty_pages_returns_empty(self):
        gains = _parse_capital_gains([], [], "koinly.pdf")
        assert gains == []


# ---------------------------------------------------------------------------
# _parse_rewards
# ---------------------------------------------------------------------------

class TestParseRewards:
    def _pages_text_with_rewards(self, lines: list[str]) -> list[str]:
        return ["\n".join(lines)]

    def test_parses_single_reward(self):
        pages_text = self._pages_text_with_rewards([
            "01/01/2024 01:00 ADA 0.00006762 0.05 Reward Flexible REALTIME Binance",
        ])
        rewards = _parse_rewards([0], pages_text, "koinly.pdf")
        assert len(rewards) == 1
        r = rewards[0]
        assert r.date == datetime(2024, 1, 1, 1, 0)
        assert r.asset == "ADA"
        assert r.quantity == Decimal("0.00006762")
        assert r.price_eur == Decimal("0.05")
        assert r.reward_type == "Reward"

    def test_parses_multiple_rewards(self):
        pages_text = self._pages_text_with_rewards([
            "01/01/2024 01:00 ADA 0.00006762 0.05 Reward Binance",
            "01/01/2024 13:22 STETH 0.00004390 0.09 Reward stETH",
        ])
        rewards = _parse_rewards([0], pages_text, "koinly.pdf")
        assert len(rewards) == 2

    def test_skips_non_matching_lines(self):
        pages_text = self._pages_text_with_rewards([
            "Operaciones de rendimientos",
            "29/07/2024 14:35 17/01/2018 23:10 BTC 0.00152000 15.55 97.82 82.27 Kraken",
        ])
        rewards = _parse_rewards([0], pages_text, "koinly.pdf")
        assert rewards == []


# ---------------------------------------------------------------------------
# validate()
# ---------------------------------------------------------------------------

class TestKoinlyValidate:
    def _data(self, gains=None, rewards=None, net_gains=None, rewards_total=None):
        d = KoinlyData()
        d.capital_gains = gains or []
        d.rewards = rewards or []
        d.summary_net_gains_eur = net_gains
        d.summary_rewards_eur = rewards_total
        return d

    def _gain(self, amount: str) -> CryptoCapitalGain:
        return CryptoCapitalGain(
            date_sold=datetime(2024, 1, 1),
            date_acquired=datetime(2020, 1, 1),
            asset="BTC",
            quantity=Decimal("1"),
            cost_eur=Decimal("0"),
            proceeds_eur=Decimal(amount),
            gain_loss_eur=Decimal(amount),
            notes="",
            wallet="",
        )

    def _reward(self, amount: str) -> CryptoReward:
        return CryptoReward(
            date=datetime(2024, 1, 1),
            asset="ADA",
            quantity=Decimal("1"),
            price_eur=Decimal(amount),
            reward_type="Reward",
            description="",
            wallet="",
        )

    def test_matching_totals_no_warnings(self):
        data = self._data(gains=[self._gain("82.27")], net_gains=Decimal("82.27"))
        assert validate(data) == []

    def test_gains_mismatch_warning(self):
        data = self._data(gains=[self._gain("82.27")], net_gains=Decimal("100.00"))
        warnings = validate(data)
        assert len(warnings) == 1
        assert "ganancias" in warnings[0].lower()

    def test_rewards_mismatch_warning(self):
        data = self._data(rewards=[self._reward("5.00")], rewards_total=Decimal("10.00"))
        warnings = validate(data)
        assert len(warnings) == 1
        assert "rendimientos" in warnings[0].lower() or "staking" in warnings[0].lower()

    def test_none_summary_skips_check(self):
        data = self._data(gains=[self._gain("82.27")], net_gains=None)
        assert validate(data) == []

    def test_within_tolerance_no_warning(self):
        # diff exactamente 0.10 → no supera (> 0.10)
        data = self._data(gains=[self._gain("82.27")], net_gains=Decimal("82.37"))
        assert validate(data) == []

    def test_just_over_tolerance_warns(self):
        # diff 0.11 → sí genera warning
        data = self._data(gains=[self._gain("82.27")], net_gains=Decimal("82.38"))
        assert len(validate(data)) == 1

    def test_empty_gains_with_summary_no_warning(self):
        # Sin datos parseados, no se compara aunque haya summary
        data = self._data(gains=[], net_gains=Decimal("82.27"))
        assert validate(data) == []
