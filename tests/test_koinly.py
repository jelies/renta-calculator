"""Tests para los helpers del parser de Koinly (sin PDFs reales)."""

from datetime import datetime
from decimal import Decimal

import pytest

from renta.parsers.koinly import (
    _GAIN_RE,
    _REWARD_RE,
    _extract_summary,
    _extract_asset_summary,
    _parse_datetime,
    _parse_decimal,
    _parse_capital_gains,
    _parse_rewards,
    detect,
    stats_summary,
    year_hint,
    usd_dates,
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

    def test_with_comma_thousands_dot_decimal(self):
        assert _parse_decimal("1,234.56") == Decimal("1234.56")

    def test_zero(self):
        assert _parse_decimal("0.00") == Decimal("0.00")

    def test_invalid_returns_none(self):
        assert _parse_decimal("N/A") is None

    # Formato español (coma decimal)
    def test_spanish_decimal_comma(self):
        assert _parse_decimal("1,41") == Decimal("1.41")

    def test_spanish_negative_comma(self):
        assert _parse_decimal("-0,47") == Decimal("-0.47")

    def test_spanish_thousands_dot_decimal_comma(self):
        assert _parse_decimal("3.838,80") == Decimal("3838.80")

    def test_spanish_zero_comma(self):
        assert _parse_decimal("0,00") == Decimal("0.00")

    def test_spanish_small_quantity(self):
        assert _parse_decimal("0,00798389") == Decimal("0.00798389")


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

    # Formato español con coma decimal (PDF 2025)
    def test_matches_spanish_decimal_comma(self):
        line = "21/01/2025 13:04 18/02/2018 13:27 LTC 0,00798389 1,41 0,94 -0,47 Litecoin (LTC)"
        m = _GAIN_RE.match(line)
        assert m is not None
        assert m.group(3) == "LTC"
        assert m.group(4) == "0,00798389"
        assert m.group(5) == "1,41"
        assert m.group(6) == "0,94"
        assert m.group(7) == "-0,47"


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

    # Formato español con coma decimal (PDF 2025)
    def test_matches_spanish_decimal_comma(self):
        line = "15/03/2025 10:30 STETH 0,00004390 0,09 Reward stETH Kraken"
        m = _REWARD_RE.match(line)
        assert m is not None
        assert m.group(2) == "STETH"
        assert m.group(3) == "0,00004390"
        assert m.group(4) == "0,09"

    def test_matches_airdrop(self):
        line = "06/06/2025 03:06 BTC 0.00009463 8.45 Airdrop Kraken"
        m = _REWARD_RE.match(line)
        assert m is not None
        assert m.group(2) == "BTC"
        assert m.group(5) == "Airdrop"

    def test_matches_airdrop_with_description(self):
        line = "20/09/2024 10:00 ETH 0.00050000 1.50 Airdrop OP airdrop Coinbase"
        m = _REWARD_RE.match(line)
        assert m is not None
        assert m.group(5) == "Airdrop"
        assert "OP airdrop" in m.group(6)


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

    def test_parses_spanish_comma_decimal(self):
        pages_text = self._pages_text_with_gains([
            "21/01/2025 13:04 18/02/2018 13:27 LTC 0,00798389 1,41 0,94 -0,47 Litecoin (LTC)",
        ])
        gains = _parse_capital_gains([0], pages_text, "koinly.pdf")
        assert len(gains) == 1
        g = gains[0]
        assert g.asset == "LTC"
        assert g.cost_eur == Decimal("1.41")
        assert g.proceeds_eur == Decimal("0.94")
        assert g.gain_loss_eur == Decimal("-0.47")


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

    def test_parses_airdrop_row(self):
        pages_text = self._pages_text_with_rewards([
            "06/06/2025 03:06 BTC 0.00009463 8.45 Airdrop Kraken",
        ])
        rewards = _parse_rewards([0], pages_text, "koinly.pdf")
        assert len(rewards) == 1
        assert rewards[0].reward_type == "Airdrop"
        assert rewards[0].asset == "BTC"
        assert rewards[0].price_eur == Decimal("8.45")

    def test_parses_mixed_rewards_and_airdrops(self):
        pages_text = self._pages_text_with_rewards([
            "01/01/2024 01:00 ADA 0.50000000 0.25 Reward Binance",
            "06/06/2024 03:06 BTC 0.00009463 8.45 Airdrop Kraken",
        ])
        all_parsed = _parse_rewards([0], pages_text, "koinly.pdf")
        assert len(all_parsed) == 2
        reward_types = {r.reward_type for r in all_parsed}
        assert reward_types == {"Reward", "Airdrop"}


# ---------------------------------------------------------------------------
# validate()
# ---------------------------------------------------------------------------

class TestExtractSummary:
    # Fixture con el formato real del PDF de Koinly 2025: dos columnas intercaladas.
    # Columna izquierda: Resumen de rendimientos. Columna derecha: Resumen de gastos.
    _RESUMEN_PAGE = (
        "AÑO FISCAL 2025\n"
        "Resumen de rendimientos Resumen de gastos\n"
        "Airdrop €8,45\n"
        "Margin fee €0,00\n"
        "Fork €0,00\n"
        "Loan fee €0,00\n"
        "Mining €0,00\n"
        "Other fee €0,00\n"
        "Reward €46,93\n"
        "Cost €6,00\n"
        "Salary €0,00\n"
        "Total €6,00\n"
        "Lending interest €0,00\n"
        "Other income €0,00\n"
        "Total €55,38\n"
    )

    def test_captura_reward_no_total(self):
        result = _extract_summary([self._RESUMEN_PAGE])
        assert result["rewards"] == Decimal("46.93")

    def test_ignora_other_income_y_total(self):
        # El Total de rendimientos (55,38) y Other income NO deben aparecer en rewards
        result = _extract_summary([self._RESUMEN_PAGE])
        assert result["rewards"] != Decimal("55.38")
        assert result["rewards"] != Decimal("8.45")

    def test_captura_costs(self):
        result = _extract_summary([self._RESUMEN_PAGE])
        assert result["costs"] == Decimal("6.00")

    def test_costs_sin_bloque_gastos_devuelve_none(self):
        page = (
            "Resumen de rendimientos\n"
            "Reward €46,93\n"
            "Total €46,93\n"
        )
        result = _extract_summary([page])
        assert result["costs"] is None

    def test_costs_cero_se_asigna(self):
        page = (
            "Resumen de rendimientos Resumen de gastos\n"
            "Reward €10,00\n"
            "Cost €0,00\n"
            "Total €0,00\n"
            "Total €10,00\n"
        )
        result = _extract_summary([page])
        assert result["costs"] == Decimal("0.00")

    def test_reward_cero_no_se_asigna(self):
        page = (
            "Resumen de rendimientos\n"
            "Reward €0,00\n"
            "Other income €8,45\n"
            "Total €8,45\n"
        )
        result = _extract_summary([page])
        assert result["rewards"] is None

    def test_sin_pagina_resumen_devuelve_none(self):
        result = _extract_summary(["Cualquier texto sin la sección."])
        assert result["rewards"] is None

    def test_captura_airdrop_no_nulo(self):
        result = _extract_summary([self._RESUMEN_PAGE])
        assert result["airdrops"] == Decimal("8.45")

    def test_airdrop_cero_no_se_asigna(self):
        page = (
            "Resumen de rendimientos\n"
            "Airdrop €0,00\n"
            "Reward €46,93\n"
            "Total €46,93\n"
        )
        result = _extract_summary([page])
        assert result["airdrops"] is None

    def test_airdrop_ausente_devuelve_none(self):
        page = "Resumen de rendimientos\nReward €10,00\nTotal €10,00\n"
        result = _extract_summary([page])
        assert result["airdrops"] is None


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

    def test_airdrops_mismatch_warning(self):
        airdrop = CryptoReward(
            date=datetime(2024, 6, 6),
            asset="BTC",
            quantity=Decimal("0.00009463"),
            price_eur=Decimal("5.00"),
            reward_type="Airdrop",
            description="",
            wallet="Kraken",
        )
        data = KoinlyData()
        data.airdrops = [airdrop]
        data.summary_airdrops_eur = Decimal("10.00")
        warnings = validate(data)
        assert len(warnings) == 1
        assert "airdrop" in warnings[0].lower()


# ---------------------------------------------------------------------------
# Funciones del contrato de parser
# ---------------------------------------------------------------------------

class TestExtractAssetSummary:
    _ASSET_PAGE = (
        "AÑO FISCAL 2025\n"
        "Resumen de activos\n"
        "Activo Ganancias (EUR) Pérdidas (EUR) Neto (EUR)\n"
        "XRP 0,03 0,00 0,03\n"
        "ETH 0,01 0,00 0,01\n"
        "LTC 0,00 89,59 -89,59\n"
        "Total 0,04 89,59 -89,55\n"
        "Generado por Koinly 6 (40)\n"
    )

    def test_parses_three_assets(self):
        result = _extract_asset_summary([self._ASSET_PAGE])
        assert set(result.keys()) == {"XRP", "ETH", "LTC"}

    def test_ltc_perdida(self):
        result = _extract_asset_summary([self._ASSET_PAGE])
        assert result["LTC"]["ganancias"] == Decimal("0.00")
        assert result["LTC"]["perdidas"] == Decimal("89.59")
        assert result["LTC"]["neto"] == Decimal("-89.59")

    def test_xrp_ganancia(self):
        result = _extract_asset_summary([self._ASSET_PAGE])
        assert result["XRP"]["ganancias"] == Decimal("0.03")
        assert result["XRP"]["perdidas"] == Decimal("0.00")

    def test_no_incluye_total(self):
        result = _extract_asset_summary([self._ASSET_PAGE])
        assert "Total" not in result

    def test_pagina_sin_resumen_devuelve_vacio(self):
        result = _extract_asset_summary(["Cualquier texto sin la sección."])
        assert result == {}


class TestParserContract:
    def test_detect_koinly_text(self):
        assert detect("Koinly Tax Report 2024") is True

    def test_detect_koinly_lowercase(self):
        assert detect("generated by koinly.com") is True

    def test_detect_rejects_other_text(self):
        assert detect("Fidelity NetBenefits Summary") is False

    def test_detect_empty_text(self):
        assert detect("") is False

    def test_stats_summary_empty(self):
        data = KoinlyData()
        assert "0 ganancias" in stats_summary(data)
        assert "0 rewards" in stats_summary(data)
        assert "0 airdrops" in stats_summary(data)

    def test_stats_summary_with_data(self):
        gain = CryptoCapitalGain(
            date_sold=datetime(2024, 7, 29),
            date_acquired=datetime(2018, 1, 17),
            asset="BTC",
            quantity=Decimal("0.001"),
            cost_eur=Decimal("15.55"),
            proceeds_eur=Decimal("97.82"),
            gain_loss_eur=Decimal("82.27"),
            notes="",
            wallet="Kraken",
        )
        data = KoinlyData(capital_gains=[gain])
        assert "1 ganancias" in stats_summary(data)

    def test_year_hint_from_gains(self):
        gain = CryptoCapitalGain(
            date_sold=datetime(2024, 7, 29),
            date_acquired=datetime(2018, 1, 17),
            asset="BTC",
            quantity=Decimal("0.001"),
            cost_eur=Decimal("15"),
            proceeds_eur=Decimal("97"),
            gain_loss_eur=Decimal("82"),
            notes="",
            wallet="Kraken",
        )
        data = KoinlyData(capital_gains=[gain])
        assert year_hint(data) == 2024

    def test_year_hint_empty_returns_none(self):
        assert year_hint(KoinlyData()) is None

    def test_usd_dates_returns_empty_set(self):
        # Koinly ya provee datos en EUR
        gain = CryptoCapitalGain(
            date_sold=datetime(2024, 7, 29),
            date_acquired=datetime(2018, 1, 17),
            asset="BTC",
            quantity=Decimal("0.001"),
            cost_eur=Decimal("15"),
            proceeds_eur=Decimal("97"),
            gain_loss_eur=Decimal("82"),
            notes="",
            wallet="Kraken",
        )
        data = KoinlyData(capital_gains=[gain])
        assert usd_dates(data) == set()
