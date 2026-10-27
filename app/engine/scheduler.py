"""Agendador do motor: decide logo após cada fechamento de candle e vigia stop/alvo em tempo real.

Antes, todos os robôs eram conferidos a cada 20 s, então um sinal podia sair até 20 s depois do fechamento e
um stop até 20 s depois de atingido. Agora:

- **Decisão**: cada robô é agendado para `fechamento do candle + candle_close_delay_ms` (~1 s), de acordo com o
  tempo gráfico da estratégia. Uma conferência completa de segurança roda também a cada `worker_interval_seconds`.
- **Risco** (só robôs com posição aberta):
    * cripto: preço em tempo real da Binance; quando cruza o stop ou o alvo, a saída é disparada na hora;
    * simulação de forex/B3: preço a cada `risk_poll_seconds`;
    * cTrader/MT5: o stop e o alvo já estão na corretora; confere a cada `broker_risk_poll_seconds`
      (fechamentos feitos pela corretora, tempo máximo posicionado).
- Cada robô tem no máximo uma tarefa em andamento; entre réplicas do worker, o lock no Redis evita duplicidade.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select

from app.core.config import get_settings
from app.models import Bot, BotStatus, Market, Position, PosSide, Venue
from app.strategies.filters import TF_MS
from app.strategies.library import get_strategy

log = logging.getLogger("scheduler")

Runner = Callable[[uuid.UUID, str, Decimal | None], Awaitable[None]]  # (robô, "decision"|"risk", preço em tempo real)


def next_close(now: float, timeframe: str) -> float:
    """Próximo fechamento de candle (segundos, UTC). Candles são alinhados ao múltiplo do tempo gráfico."""
    step = TF_MS[timeframe] / 1000
    return (math.floor(now / step) + 1) * step


@dataclass
class Watch:
    bot_id: uuid.UUID
    symbol: str
    timeframe: str
    feed: str | None  # "live" | "testnet" quando há preço em tempo real da Binance
    broker_protected: bool  # cTrader/MT5 fora da simulação: stop/alvo na corretora
    due_decision: float
    next_risk: float = 0.0
    side: str | None = None  # posição aberta: "long" | "short"
    stop: float | None = None
    take: float | None = None
    # Grid e DCA: vigiados sempre (com ou sem lote), disparando quando o preço cruza o próximo nível.
    ladder: bool = False
    buy_at: float | None = None  # compra quando o preço CAIR até aqui
    sell_at: float | None = None  # vende quando SUBIR até aqui
    last_fire: float = 0.0


class Scheduler:
    def __init__(self, runner: Runner, clock: Callable[[], float] = time.time):
        s = get_settings()
        self.runner = runner
        self.clock = clock
        self.delay = s.candle_close_delay_ms / 1000
        self.fallback = float(s.worker_interval_seconds)
        self.risk_poll = s.risk_poll_seconds
        self.broker_poll = s.broker_risk_poll_seconds
        self.watches: dict[uuid.UUID, Watch] = {}
        self.running: dict[uuid.UUID, asyncio.Task] = {}
        self.wake = asyncio.Event()
        self.feeds: dict = {}  # nome -> BinanceFeed
        self.triggered: dict[uuid.UUID, Decimal] = {}  # preço que disparou a saída
        self._reload = True
        self.last_error: str | None = None  # erro ao ler os robôs do banco (ex.: migração não aplicada)

    # ------------------------------------------------------------ estado
    @staticmethod
    def _feed_for(bot: Bot) -> str | None:
        if bot.market != Market.crypto:
            return None
        return "testnet" if bot.venue == Venue.testnet else "live"  # simulação usa o preço de produção

    @staticmethod
    def _levels(bot: Bot, pos: Position) -> tuple[float | None, float | None]:
        sign = 1 if pos.side == PosSide.long else -1
        avg = float(pos.avg_price)
        stop = float(pos.stop_price) if pos.stop_price is not None else (avg * (1 - sign * float(bot.stop_loss_pct) / 100) if bot.stop_loss_pct else None)
        take = float(pos.take_price) if pos.take_price is not None else (avg * (1 + sign * float(bot.take_profit_pct) / 100) if bot.take_profit_pct else None)
        return stop, take

    def load(self, bots: list[Bot], positions: dict[uuid.UUID, Position]) -> None:
        """Atualiza a lista de robôs vigiados preservando os horários já agendados."""
        now = self.clock()
        seen = set()
        for bot in bots:
            seen.add(bot.id)
            try:
                tf = get_strategy(bot.strategy).parse_params(bot.params).timeframe
            except Exception:  # noqa: BLE001 - parâmetros inválidos: o tick completo registra o erro
                tf = "1h"
            w = self.watches.get(bot.id)
            if w is None:
                w = Watch(bot.id, bot.symbol, tf, self._feed_for(bot), bot.market != Market.crypto and bot.venue != Venue.paper, due_decision=now)
                self.watches[bot.id] = w
            else:
                w.symbol, w.feed = bot.symbol, self._feed_for(bot)
                w.broker_protected = bot.market != Market.crypto and bot.venue != Venue.paper
                if w.timeframe != tf:
                    w.timeframe, w.due_decision = tf, now
            pos = positions.get(bot.id)
            if get_strategy(bot.strategy).kind == "ladder":
                from app.engine.ladder import trigger_levels

                w.ladder = True
                w.side = None
                w.buy_at, w.sell_at, w.stop, act_now = trigger_levels(bot)
                w.take = None
                if act_now:
                    w.next_risk = min(w.next_risk, now + 2.0)
            elif pos is None:
                w.side = w.stop = w.take = None
            else:
                was_open = w.side is not None
                w.side = pos.side.value
                w.stop, w.take = self._levels(bot, pos)
                if not was_open:
                    w.next_risk = now  # posição nova: confere já
        for gone in set(self.watches) - seen:
            self.watches.pop(gone, None)
        self._subscribe()

    def _subscribe(self) -> None:
        for name, feed in self.feeds.items():
            feed.set_symbols({w.symbol for w in self.watches.values() if w.feed == name and (w.side or w.ladder)})

    # ------------------------------------------------------------ preço em tempo real
    def on_price(self, feed: str, symbol: str, bid: float, ask: float) -> None:
        for w in self.watches.values():
            if w.feed != feed or w.symbol != symbol or w.bot_id in self.running:
                continue
            if w.ladder:
                if self.clock() - w.last_fire < 3:
                    continue  # acabou de rodar: espera a nova situação ser recarregada
                # Compra quando o preço de venda dos outros (ask) cai ao nível; vende quando o bid sobe ao nível.
                hit_px = ask if (w.buy_at is not None and ask <= w.buy_at) else bid if (
                    (w.sell_at is not None and bid >= w.sell_at) or (w.stop is not None and bid <= w.stop)) else None
                if hit_px is not None:
                    w.next_risk = 0.0
                    self.triggered[w.bot_id] = Decimal(str(hit_px))
                    self.wake.set()
                continue
            if not w.side:
                continue
            # Saída de comprado acontece no bid; de vendido, no ask.
            px = bid if w.side == "long" else ask
            hit = (
                (w.side == "long" and ((w.stop is not None and px <= w.stop) or (w.take is not None and px >= w.take)))
                or (w.side == "short" and ((w.stop is not None and px >= w.stop) or (w.take is not None and px <= w.take)))
            )
            if hit:
                w.next_risk = 0.0
                self.triggered[w.bot_id] = Decimal(str(px))
                self.wake.set()

    # ------------------------------------------------------------ agenda
    def due(self) -> list[tuple[uuid.UUID, str]]:
        now = self.clock()
        out = []
        for w in self.watches.values():
            if w.bot_id in self.running:
                continue
            if now >= w.due_decision:
                out.append((w.bot_id, "decision"))
            elif (w.side or w.ladder) and now >= w.next_risk:
                out.append((w.bot_id, "risk"))
        return out

    def _reschedule(self, w: Watch, kind: str) -> None:
        now = self.clock()
        if kind == "decision":
            w.due_decision = min(next_close(now, w.timeframe) + self.delay, now + self.fallback)
            w.next_risk = now + self._risk_interval(w)
        else:
            w.next_risk = now + self._risk_interval(w)

    def _risk_interval(self, w: Watch) -> float:
        if w.broker_protected:
            return self.broker_poll
        if w.feed and w.feed in self.feeds and self.feeds[w.feed].quote(w.symbol):
            return 10.0  # o preço em tempo real dispara antes; isto é só uma rede de segurança
        return self.risk_poll

    def seconds_to_next(self) -> float:
        now = self.clock()
        times = [w.due_decision for w in self.watches.values() if w.bot_id not in self.running]
        times += [w.next_risk for w in self.watches.values() if (w.side or w.ladder) and w.bot_id not in self.running]
        return max(0.05, min([t - now for t in times], default=1.0))

    def dispatch(self) -> None:
        for bot_id, kind in self.due():
            w = self.watches[bot_id]
            price = self.triggered.pop(bot_id, None)
            if price is None and kind == "risk" and w.feed and w.feed in self.feeds:
                q = self.feeds[w.feed].quote(w.symbol)
                if q:
                    price = Decimal(str((q.bid + q.ask) / 2 if w.ladder else q.bid if w.side == "long" else q.ask))
            self._reschedule(w, kind)
            w.last_fire = self.clock()
            task = asyncio.get_running_loop().create_task(self.runner(bot_id, kind, price))
            self.running[bot_id] = task
            task.add_done_callback(lambda _t, b=bot_id: self._done(b))

    def _done(self, bot_id: uuid.UUID) -> None:
        self.running.pop(bot_id, None)
        self._reload = True  # a posição pode ter mudado: recarrega logo depois
        self.wake.set()

    # ------------------------------------------------------------ laço
    async def run(self, stop: asyncio.Event, load_state: Callable[[], Awaitable[tuple[list[Bot], dict]]], refresh_every: float = 3.0) -> None:
        last_refresh = 0.0
        while not stop.is_set():
            self.wake.clear()
            self.dispatch()  # primeiro o que está na hora (ex.: stop disparado pelo preço), depois o resto
            if self._reload or self.clock() - last_refresh >= refresh_every:
                self._reload = False
                try:
                    bots, positions = await load_state()
                    self.load(bots, positions)
                    self.last_error = None
                except Exception as exc:  # noqa: BLE001 - banco fora do ar: tenta de novo no próximo giro
                    if self.last_error is None:
                        log.exception("Falha ao carregar robôs")
                    self.last_error = f"{type(exc).__name__}: {str(exc).splitlines()[0][:240] if str(exc) else ''}"
                last_refresh = self.clock()
                self.dispatch()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.wake.wait(), timeout=min(self.seconds_to_next(), refresh_every))
        for t in list(self.running.values()):
            with contextlib.suppress(Exception):
                await asyncio.wait_for(t, timeout=30)


async def load_state(session_factory) -> tuple[list[Bot], dict[uuid.UUID, Position]]:
    async with session_factory() as db:
        bots = list(await db.scalars(select(Bot).where(Bot.status.in_([BotStatus.running, BotStatus.paused_billing]))))
        ids = [b.id for b in bots]
        positions = {p.bot_id: p for p in await db.scalars(select(Position).where(Position.bot_id.in_(ids)))} if ids else {}
        return bots, positions
