from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class SourceRef:
    """Referencia al dato original en el PDF para trazabilidad."""
    file: str
    page: int
    row: int
    section: str

    def __str__(self) -> str:
        return f"{self.file} · pág {self.page}, fila {self.row + 1} ({self.section})"


# ---------------------------------------------------------------------------
# Datos de Fidelity (en USD)
# ---------------------------------------------------------------------------

@dataclass
class DividendEntry:
    date: date
    amount_usd: Decimal
    amount_eur: Decimal | None = None
    exchange_rate: Decimal | None = None
    source: SourceRef | None = None


@dataclass
class StockSale:
    date_sold: date
    date_acquired: date
    quantity: Decimal
    cost_basis_usd: Decimal
    proceeds_usd: Decimal
    gain_loss_usd: Decimal
    stock_source: str  # RS = RSU, SP = ESPP, etc.
    ticker: str = ""
    # Calculados tras conversion
    cost_basis_eur: Decimal | None = None
    proceeds_eur: Decimal | None = None
    gain_loss_eur: Decimal | None = None
    exchange_rate_acquired: Decimal | None = None  # tipo BCE a fecha de vesting
    exchange_rate_sold: Decimal | None = None       # tipo BCE a fecha de venta
    source: SourceRef | None = None


@dataclass
class WithholdingEntry:
    date: date
    amount_usd: Decimal  # negativo = retención, positivo = ajuste
    amount_eur: Decimal | None = None
    exchange_rate: Decimal | None = None
    source: SourceRef | None = None


@dataclass
class FidelityData:
    dividends: list[DividendEntry] = field(default_factory=list)
    stock_sales: list[StockSale] = field(default_factory=list)
    withholdings: list[WithholdingEntry] = field(default_factory=list)
    # Totales del resumen del PDF (para validación)
    summary_dividends_usd: Decimal | None = None
    summary_stock_sales_usd: Decimal | None = None
    summary_withholding_usd: Decimal | None = None


# ---------------------------------------------------------------------------
# Datos de Koinly (ya en EUR)
# ---------------------------------------------------------------------------

@dataclass
class CryptoCapitalGain:
    date_sold: datetime
    date_acquired: datetime
    asset: str
    quantity: Decimal
    cost_eur: Decimal      # valor (coste de adquisición)
    proceeds_eur: Decimal  # ingresos (valor de venta)
    gain_loss_eur: Decimal
    notes: str
    wallet: str
    source: SourceRef | None = None


@dataclass
class CryptoReward:
    date: datetime
    asset: str
    quantity: Decimal
    price_eur: Decimal
    reward_type: str
    description: str
    wallet: str
    source: SourceRef | None = None


@dataclass
class KoinlyData:
    capital_gains: list[CryptoCapitalGain] = field(default_factory=list)
    rewards: list[CryptoReward] = field(default_factory=list)
    # Totales del resumen del PDF (para validación)
    summary_gains_eur: Decimal | None = None
    summary_losses_eur: Decimal | None = None
    summary_net_gains_eur: Decimal | None = None
    summary_rewards_eur: Decimal | None = None


# ---------------------------------------------------------------------------
# Resultado: casillas del modelo 100
# ---------------------------------------------------------------------------

@dataclass
class LineaDetalle:
    """Una fila de detalle en el informe."""
    descripcion: str
    importe_eur: Decimal | None  # None = no calculable (fallo de tipo de cambio)
    fuente: SourceRef | None = None
    extras: dict = field(default_factory=dict)  # campos adicionales para el HTML
    error: str | None = None  # mensaje de error si no se pudo calcular


@dataclass
class Casilla:
    numero: str
    nombre: str
    valor: Decimal | None  # None = no calculable por errores en alguna fila
    desglose: list[LineaDetalle] = field(default_factory=list)
    notas: str = ""
    errores: list[str] = field(default_factory=list)  # filas que no se pudieron calcular
    template: str | None = None  # nombre del template parcial, ej. "_dividendos.html"
    extras: dict = field(default_factory=dict)  # datos extra para el template


@dataclass
class ResultadoRenta:
    year: int
    # Rendimientos del capital mobiliario
    dividendos: Casilla | None = None
    rendimientos_crypto: Casilla | None = None
    # Ganancias y pérdidas patrimoniales
    ganancias_acciones: Casilla | None = None
    ganancias_crypto: Casilla | None = None
    # Deducción doble imposición internacional
    doble_imposicion: Casilla | None = None
    # Tipos de cambio utilizados {fecha: (rate, fuente)}
    exchange_rates_used: dict = field(default_factory=dict)
    # Advertencias generadas durante el cálculo
    warnings: list[str] = field(default_factory=list)

    @property
    def casillas(self) -> list["Casilla"]:
        """Todas las casillas no-None en orden de presentación."""
        return [c for c in [
            self.dividendos,
            self.ganancias_acciones,
            self.ganancias_crypto,
            self.doble_imposicion,
            self.rendimientos_crypto,
        ] if c is not None]
