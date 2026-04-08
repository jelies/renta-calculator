"""Factories para crear objetos de test sin PDFs ni red."""

from datetime import date, datetime
from decimal import Decimal

from renta.models import (
    CryptoCapitalGain,
    CryptoReward,
    DegiroDividend,
    DegiroStockSale,
    DividendEntry,
    StockSale,
    WithholdingEntry,
)


def make_dividend(d: date = date(2024, 1, 15), amount_usd: str = "100.00") -> DividendEntry:
    return DividendEntry(date=d, amount_usd=Decimal(amount_usd))


def make_stock_sale(
    date_sold: date = date(2024, 3, 12),
    date_acquired: date = date(2020, 5, 5),
    quantity: str = "10.0000",
    cost_basis_usd: str = "500.00",
    proceeds_usd: str = "750.00",
    gain_loss_usd: str = "250.00",
    stock_source: str = "RS",
    ticker: str = "ORCL",
) -> StockSale:
    return StockSale(
        date_sold=date_sold,
        date_acquired=date_acquired,
        quantity=Decimal(quantity),
        cost_basis_usd=Decimal(cost_basis_usd),
        proceeds_usd=Decimal(proceeds_usd),
        gain_loss_usd=Decimal(gain_loss_usd),
        stock_source=stock_source,
        ticker=ticker,
    )


def make_withholding(d: date = date(2024, 1, 15), amount_usd: str = "-7.08") -> WithholdingEntry:
    return WithholdingEntry(date=d, amount_usd=Decimal(amount_usd))


def make_crypto_gain(
    date_sold: datetime = datetime(2024, 7, 29, 14, 35),
    date_acquired: datetime = datetime(2018, 1, 17, 23, 10),
    asset: str = "BTC",
    quantity: str = "0.00152000",
    cost_eur: str = "15.55",
    proceeds_eur: str = "97.82",
    gain_loss_eur: str = "82.27",
    wallet: str = "Kraken",
) -> CryptoCapitalGain:
    return CryptoCapitalGain(
        date_sold=date_sold,
        date_acquired=date_acquired,
        asset=asset,
        quantity=Decimal(quantity),
        cost_eur=Decimal(cost_eur),
        proceeds_eur=Decimal(proceeds_eur),
        gain_loss_eur=Decimal(gain_loss_eur),
        notes="",
        wallet=wallet,
    )


def make_degiro_dividend(
    country: str = "US",
    product: str = "ARES CAPITAL CORP",
    gross_eur: str = "2.56",
    withholding_eur: str = "-0.38",
    net_eur: str = "2.18",
) -> DegiroDividend:
    return DegiroDividend(
        country=country,
        product=product,
        gross_eur=Decimal(gross_eur),
        withholding_eur=Decimal(withholding_eur),
        net_eur=Decimal(net_eur),
    )


def make_degiro_stock_sale(
    date_sold: date = date(2024, 5, 27),
    product: str = "Ares Capital Corp",
    symbol_isin: str = "US04010L1035",
    order_type: str = "V",
    quantity: str = "2",
    price: str = "21.87",
    value_local: str = "43.74",
    value_eur: str = "38.61",
    commission_eur: str = "2.00",
    exchange_rate: str = "0.8827",
    gain_loss_eur: str = "1.9045",
) -> DegiroStockSale:
    return DegiroStockSale(
        date_sold=date_sold,
        product=product,
        symbol_isin=symbol_isin,
        order_type=order_type,
        quantity=Decimal(quantity),
        price=Decimal(price),
        value_local=Decimal(value_local),
        value_eur=Decimal(value_eur),
        commission_eur=Decimal(commission_eur),
        exchange_rate=Decimal(exchange_rate),
        gain_loss_eur=Decimal(gain_loss_eur),
    )


def make_crypto_reward(
    dt: datetime = datetime(2024, 1, 1, 1, 0),
    asset: str = "ADA",
    quantity: str = "0.00006762",
    price_eur: str = "0.05",
    reward_type: str = "Reward",
    wallet: str = "Binance",
) -> CryptoReward:
    return CryptoReward(
        date=dt,
        asset=asset,
        quantity=Decimal(quantity),
        price_eur=Decimal(price_eur),
        reward_type=reward_type,
        description="",
        wallet=wallet,
    )
