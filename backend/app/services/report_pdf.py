"""Relatório de operações em PDF (reportlab, sem dependências de sistema).

Recebe dados já consultados e filtrados (ReportData) e devolve os bytes do PDF.
Horários no fuso de Brasília; valores no formato brasileiro.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.platypus.flowables import Flowable

TZ = ZoneInfo("America/Sao_Paulo")

NOITE = colors.HexColor("#17133D")
AMBAR = colors.HexColor("#E9A03B")
NEVOA = colors.HexColor("#F4F3F9")
LINHA = colors.HexColor("#DCDAEA")
TEXTO2 = colors.HexColor("#4B4870")
GANHO = colors.HexColor("#1F7A4D")
PERDA = colors.HexColor("#B42318")

VENUE_LABEL = {"paper": "Simulação", "testnet": "Testnet", "live": "Conta real"}
SIDE_LABEL = {"BUY": "Compra", "SELL": "Venda"}
POS_LABEL = {"long": "Comprado", "short": "Vendido"}
QUOTES = ("USDT", "USDC", "FDUSD", "BRL", "BTC", "ETH", "BNB", "EUR", "TRY")


def venue_label(venue: str, market: str) -> str:
    return "Conta demo" if market in ("forex", "b3") and venue == "testnet" else VENUE_LABEL.get(venue, venue)


def currency_of(symbol: str, market: str) -> str:
    """Moeda em que o resultado é medido: cotação do par (cripto) ou moeda da conta (forex)."""
    if market == "forex":
        return "moeda da conta"
    if market == "b3":
        return "R$"
    for q in QUOTES:
        if symbol.endswith(q) and len(symbol) > len(q):
            return q
    return "cotação"


# ---------------- formatação pt-BR ----------------
def _br(n: Decimal | float, digits: int) -> str:
    s = f"{float(n):,.{digits}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def money(v: Decimal | None, digits: int = 2) -> str:
    return "—" if v is None else _br(v, digits)


def signed(v: Decimal | None) -> str:
    if v is None:
        return ""
    return ("+" if v > 0 else "") + _br(v, 2)


def price(v: Decimal | None) -> str:
    if v is None:
        return "—"
    n = abs(float(v))
    return _br(v, 2 if n >= 100 else 4 if n >= 1 else 6)


def qty(v: Decimal | None) -> str:
    if v is None:
        return "—"
    s = _br(v, 8).rstrip("0").rstrip(",")
    return s or "0"


def local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(TZ)


def dt_br(dt: datetime) -> str:
    return local(dt).strftime("%d/%m/%Y %H:%M")


# ---------------- dados ----------------
@dataclass
class OrderRow:
    created_at: datetime
    bot_name: str
    symbol: str
    market: str
    venue: str
    side: str
    qty: Decimal
    price: Decimal | None
    fee: Decimal
    pnl: Decimal | None
    reason: str


@dataclass
class OpenRow:
    bot_name: str
    symbol: str
    market: str
    venue: str
    side: str
    qty: Decimal
    avg_price: Decimal
    opened_at: datetime


@dataclass
class ReportData:
    brand: str
    user_name: str
    user_email: str
    start: date
    end: date
    symbols: list[str]
    venues: list[str]
    orders: list[OrderRow]
    open_positions: list[OpenRow]
    generated_at: datetime
    truncated: bool = False
    extra: dict = field(default_factory=dict)


@dataclass
class SummaryRow:
    symbol: str
    market: str
    venue: str
    orders: int = 0
    closed: int = 0
    wins: int = 0
    pnl: Decimal = Decimal("0")
    fees: Decimal = Decimal("0")

    @property
    def win_rate(self) -> str:
        return f"{self.wins / self.closed * 100:.0f}%".replace(".", ",") if self.closed else "—"


def summarize(orders: list[OrderRow]) -> list[SummaryRow]:
    rows: dict[tuple[str, str], SummaryRow] = {}
    for o in orders:
        r = rows.setdefault((o.symbol, o.venue), SummaryRow(o.symbol, o.market, o.venue))
        r.orders += 1
        r.fees += o.fee or 0
        if o.pnl is not None:
            r.closed += 1
            r.pnl += o.pnl
            if o.pnl > 0:
                r.wins += 1
    order = {"live": 0, "testnet": 1, "paper": 2}
    return sorted(rows.values(), key=lambda r: (order.get(r.venue, 9), r.symbol))


def totals(summary: list[SummaryRow]) -> list[tuple[str, str, Decimal, int, int]]:
    """Totais por ambiente e moeda de medida. Nunca soma moedas diferentes nem simulação com conta real."""
    acc: dict[tuple[str, str], list] = {}
    for r in summary:
        key = (venue_label(r.venue, r.market), currency_of(r.symbol, r.market))
        a = acc.setdefault(key, [Decimal("0"), 0, 0])
        a[0] += r.pnl
        a[1] += r.closed
        a[2] += r.wins
    return [(v, c, a[0], a[1], a[2]) for (v, c), a in acc.items()]


# ---------------- layout ----------------
class Symbol(Flowable):
    """Símbolo Vela: anel Noite com candle Âmbar (mesmas proporções do SVG 100x100)."""

    def __init__(self, size: float = 14 * mm):
        super().__init__()
        self.size = size
        self.width = self.height = size

    def draw(self) -> None:
        c, k = self.canv, self.size / 100
        c.setStrokeColor(NOITE)
        c.setLineWidth(10 * k)
        c.circle(50 * k, 50 * k, 40 * k, stroke=1, fill=0)
        c.setStrokeColor(AMBAR)
        c.setLineWidth(5 * k)
        c.setLineCap(1)
        c.line(50 * k, 22 * k, 50 * k, 78 * k)
        c.setFillColor(AMBAR)
        c.roundRect(40 * k, 35 * k, 20 * k, 30 * k, 4 * k, stroke=0, fill=1)


def _styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=8.5, leading=11, textColor=NOITE)
    return {
        "base": base,
        "muted": ParagraphStyle("muted", parent=base, textColor=TEXTO2),
        "small": ParagraphStyle("small", parent=base, fontSize=7.5, leading=9.5, textColor=TEXTO2),
        "cell": ParagraphStyle("cell", parent=base, fontSize=7.5, leading=9),
        "h1": ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=17, leading=21),
        "h2": ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=11.5, leading=15, spaceBefore=12, spaceAfter=6),
        "brand": ParagraphStyle("brand", parent=base, fontSize=20, leading=22),
        "right": ParagraphStyle("right", parent=base, alignment=TA_RIGHT, textColor=TEXTO2),
    }


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _wordmark(brand: str, st) -> Paragraph:
    # "OráculoInvest" → Oráculo em negrito, Invest regular (como no logo). Outro nome: tudo em negrito.
    if brand.endswith("Invest") and len(brand) > 6:
        html = f"<font name='Helvetica-Bold'>{_esc(brand[:-6])}</font>Invest"
    else:
        html = f"<font name='Helvetica-Bold'>{_esc(brand)}</font>"
    return Paragraph(html, st["brand"])


def _table(data, widths, *, num_cols=(), header_bg=NOITE, zebra=True, extra=None) -> Table:
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.5),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 7.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("TEXTCOLOR", (0, 1), (-1, -1), NOITE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINHA),
    ]
    for c in num_cols:
        style.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    if zebra:
        for i in range(2, len(data), 2):
            style.append(("BACKGROUND", (0, i), (-1, i), NEVOA))
    t.setStyle(TableStyle(style + (extra or [])))
    return t


def _pnl_colors(rows: list, col: int, values: list[Decimal | None], first_row: int = 1) -> list:
    out = []
    for i, v in enumerate(values):
        if v is not None and v != 0:
            out.append(("TEXTCOLOR", (col, i + first_row), (col, i + first_row), GANHO if v > 0 else PERDA))
    return out


def render(data: ReportData) -> bytes:
    st = _styles()
    buf = io.BytesIO()
    page = landscape(A4)
    margin = 14 * mm
    width = page[0] - 2 * margin - 12  # o quadro do reportlab tem 6 pt de respiro de cada lado

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(TEXTO2)
        x0, x1 = margin + 6, page[0] - margin - 6
        canvas.drawString(x0, 8 * mm, f"{data.brand} · Relatório de operações · {data.user_email}")
        canvas.drawRightString(x1, 8 * mm, f"Página {doc.page}")
        canvas.setStrokeColor(AMBAR)
        canvas.setLineWidth(2)
        canvas.line(x0, page[1] - 8 * mm, x1, page[1] - 8 * mm)
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buf,
        pagesize=page,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=13 * mm,
        bottomMargin=14 * mm,
        title=f"{data.brand} - Relatório de operações",
        author=data.brand,
        subject=f"Operações de {data.start:%d/%m/%Y} a {data.end:%d/%m/%Y}",
    )
    story: list = []

    # Cabeçalho
    head = Table(
        [[Symbol(13 * mm), _wordmark(data.brand, st), Paragraph(f"Gerado em {dt_br(data.generated_at)}<br/>Horário de Brasília", st["right"])]],
        colWidths=[16 * mm, width - 76 * mm, 60 * mm],
    )
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [head, Spacer(1, 5 * mm), Paragraph("Relatório de operações", st["h1"])]

    venues = ", ".join(VENUE_LABEL[v] if v != "testnet" else "Testnet / conta demo" for v in data.venues)
    info = [
        ["Assinante", f"{data.user_name} ({data.user_email})"],
        ["Período", f"{data.start:%d/%m/%Y} a {data.end:%d/%m/%Y}"],
        ["Moedas", ", ".join(data.symbols)],
        ["Ambientes", venues],
    ]
    info_t = Table(
        [[Paragraph(k, st["muted"]), Paragraph(_esc(v), st["base"])] for k, v in info],
        colWidths=[26 * mm, width - 26 * mm],
    )
    info_t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    story += [Spacer(1, 2 * mm), info_t]

    # Totais
    summary = summarize(data.orders)
    tot = totals(summary)
    if tot:
        cells = []
        for venue, cur, pnl, closed, wins in tot:
            color = "#1F7A4D" if pnl > 0 else "#B42318" if pnl < 0 else "#17133D"
            if closed == 1:
                rate = f"{wins * 100}% de acerto em 1 operação encerrada"
            elif closed:
                rate = f"{wins / closed * 100:.0f}% de acerto em {closed} operações encerradas"
            else:
                rate = "Nenhuma operação encerrada"
            cells.append(
                Paragraph(
                    f"<font size=7.5 color='#4B4870'>{_esc(venue)} · resultado em {_esc(cur)}</font><br/>"
                    f"<font name='Helvetica-Bold' size=15 color='{color}'>{signed(pnl) or '0,00'}</font><br/>"
                    f"<font size=7.5 color='#4B4870'>{rate}</font>",
                    ParagraphStyle("card", parent=st["base"], leading=17),
                )
            )
        per_row = min(4, len(cells))
        grid = [cells[i : i + per_row] for i in range(0, len(cells), per_row)]
        for g in grid:
            g += [""] * (per_row - len(g))
        cards = Table(grid, colWidths=[width / 4] * per_row, hAlign="LEFT")
        cards.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), NEVOA),
                    ("LINEAFTER", (0, 0), (-2, -1), 3, colors.white),
                    ("LINEBELOW", (0, 0), (-1, -2), 3, colors.white),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story += [Spacer(1, 5 * mm), cards]

    # Resumo por moeda
    story.append(Paragraph("Resumo por moeda", st["h2"]))
    if summary:
        rows = [["Moeda", "Mercado", "Ambiente", "Ordens", "Encerradas", "Acerto", "Taxas", "Resultado", "Medido em"]]
        for r in summary:
            rows.append(
                [
                    r.symbol,
                    {"forex": "Forex", "b3": "Futuros B3"}.get(r.market, "Cripto"),
                    venue_label(r.venue, r.market),
                    str(r.orders),
                    str(r.closed),
                    r.win_rate,
                    money(r.fees, 4),
                    signed(r.pnl) or "0,00",
                    currency_of(r.symbol, r.market),
                ]
            )
        w = [30, 20, 26, 18, 22, 18, 28, 30, 30]
        k = width / (sum(w) * mm)
        t = _table(rows, [x * mm * k for x in w], num_cols=(3, 4, 5, 6, 7), extra=_pnl_colors(rows, 7, [r.pnl for r in summary]))
        story.append(t)
    else:
        story.append(Paragraph("Nenhuma ordem executada nesse período para as moedas escolhidas.", st["muted"]))

    # Posições abertas
    story.append(Paragraph("Posições abertas agora", st["h2"]))
    if data.open_positions:
        rows = [["Moeda", "Robô", "Ambiente", "Direção", "Quantidade", "Preço de entrada", "Aberta em"]]
        for p in data.open_positions:
            rows.append(
                [
                    p.symbol,
                    Paragraph(_esc(p.bot_name), st["cell"]),
                    venue_label(p.venue, p.market),
                    POS_LABEL.get(p.side, p.side),
                    qty(p.qty),
                    price(p.avg_price),
                    dt_br(p.opened_at),
                ]
            )
        w = [30, 60, 28, 24, 32, 32, 32]
        k = width / (sum(w) * mm)
        story.append(_table(rows, [x * mm * k for x in w], num_cols=(4, 5)))
        story.append(Spacer(1, 1.5 * mm))
        story.append(Paragraph("O resultado das posições abertas só entra no relatório quando elas forem encerradas.", st["small"]))
    else:
        story.append(Paragraph("Nenhuma posição aberta nas moedas escolhidas.", st["muted"]))

    # Ordens
    story.append(Paragraph("Ordens executadas no período", st["h2"]))
    if data.orders:
        rows = [["Data e hora", "Robô", "Moeda", "Ambiente", "Lado", "Quantidade", "Preço médio", "Taxa", "Resultado", "Motivo"]]
        for o in data.orders:
            rows.append(
                [
                    dt_br(o.created_at),
                    Paragraph(_esc(o.bot_name), st["cell"]),
                    o.symbol,
                    venue_label(o.venue, o.market),
                    SIDE_LABEL.get(o.side, o.side),
                    qty(o.qty),
                    price(o.price),
                    money(o.fee, 4),
                    signed(o.pnl),
                    Paragraph(_esc(o.reason[:140]), st["cell"]),
                ]
            )
        w = [27, 32, 22, 22, 15, 24, 24, 20, 22, 62]
        k = width / (sum(w) * mm)
        story.append(_table(rows, [x * mm * k for x in w], num_cols=(5, 6, 7, 8), extra=_pnl_colors(rows, 8, [o.pnl for o in data.orders])))
        if data.truncated:
            story.append(Spacer(1, 1.5 * mm))
            story.append(Paragraph(f"Mostrando as {len(data.orders)} ordens mais recentes do período. Escolha um período menor para ver todas.", st["small"]))
    else:
        story.append(Paragraph("Nenhuma ordem executada nesse período.", st["muted"]))

    # Notas
    notes = [
        "Resultado realizado: lucro ou prejuízo das operações encerradas, já descontadas as taxas de entrada e saída.",
        "Cripto: resultado na moeda de cotação do par (por exemplo, USDT em BTCUSDT). Forex: na moeda da conta da corretora, já com swap e comissão informados por ela. Futuros da B3: em reais, com os custos informados pela corretora.",
        "Simulação, testnet e conta demo não movimentam dinheiro real; os números delas não representam ganhos ou perdas reais.",
        "Resultados passados não garantem resultados futuros. Este relatório não é recomendação de investimento.",
        "Para declaração de imposto de renda, confira os valores com os extratos da corretora.",
    ]
    story.append(
        KeepTogether(
            [Paragraph("Observações", st["h2"])] + [Paragraph(f"• {_esc(n)}", st["small"]) for n in notes]
        )
    )

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
