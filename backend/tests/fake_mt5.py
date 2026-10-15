"""MetaTrader 5 simulado (subconjunto do pacote MetaTrader5) para testar o conector sem Windows.

Imita uma conta de bolsa (B3) em modo netting: relógio do servidor em Brasília (UTC-3), contratos
WIN/WDO com vencimento, ordens a mercado executadas na hora, corretagem por contrato.
"""
from __future__ import annotations

import fnmatch
import itertools
import time
from collections import namedtuple
from datetime import datetime

import numpy as np

SymbolInfo = namedtuple(
    "SymbolInfo",
    "name expiration_time trade_tick_size trade_tick_value volume_min volume_step volume_max digits point "
    "trade_mode trade_exemode filling_mode currency_profit",
)
Tick = namedtuple("Tick", "time bid ask last")
Account = namedtuple("Account", "login server company name currency trade_mode trade_allowed trade_expert margin_mode")
Terminal = namedtuple("Terminal", "trade_allowed connected build")
Result = namedtuple("Result", "retcode deal order volume price comment")
Position = namedtuple("Position", "ticket symbol type volume price_open magic sl tp")
Deal = namedtuple("Deal", "ticket order time type entry magic position_id volume price commission swap profit fee symbol comment")

RATE_DTYPE = [("time", "<i8"), ("open", "<f8"), ("high", "<f8"), ("low", "<f8"), ("close", "<f8"), ("tick_volume", "<u8"), ("spread", "<i4"), ("real_volume", "<u8")]
TF_SECONDS = {1: 60, 5: 300, 15: 900, 30: 1800, 1 | 0x4000: 3600, 4 | 0x4000: 14400, 24 | 0x4000: 86400}


class FakeMT5:
    TIMEFRAME_M1, TIMEFRAME_M5, TIMEFRAME_M15, TIMEFRAME_M30 = 1, 5, 15, 30
    TIMEFRAME_H1, TIMEFRAME_H4, TIMEFRAME_D1 = 1 | 0x4000, 4 | 0x4000, 24 | 0x4000
    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
    ORDER_TIME_DAY = 1
    TRADE_ACTION_DEAL, TRADE_ACTION_SLTP = 1, 6
    TRADE_RETCODE_PLACED, TRADE_RETCODE_DONE, TRADE_RETCODE_DONE_PARTIAL = 10008, 10009, 10010
    SYMBOL_TRADE_MODE_FULL = 4
    SYMBOL_TRADE_EXECUTION_EXCHANGE = 3
    COMMISSION = 0.25  # por contrato, por lado

    def __init__(self, clock=time.time, offset: int = -10800, trade_mode: int = 0, login: int = 5550123):
        self.clock = clock
        self.offset = offset
        self.account = Account(login, "Corretora-DEMO", "Corretora Exemplo S.A.", "Cliente Teste", "BRL", trade_mode, True, True, 0)
        self.terminal = Terminal(True, True, 4755)
        now = self.server_now()
        day = 86400
        self.symbols = {
            # WINV26 vence amanhã: dentro da janela de rolagem, o conector deve escolher WINZ26
            "WINV26": SymbolInfo("WINV26", now + 1 * day, 5.0, 1.0, 1.0, 1.0, 500.0, 0, 1.0, 4, 3, 1, "BRL"),
            "WINZ26": SymbolInfo("WINZ26", now + 63 * day, 5.0, 1.0, 1.0, 1.0, 500.0, 0, 1.0, 4, 3, 1, "BRL"),
            "WDOX26": SymbolInfo("WDOX26", now + 18 * day, 0.5, 5.0, 1.0, 1.0, 500.0, 1, 0.1, 4, 3, 1, "BRL"),
            "WDOZ26": SymbolInfo("WDOZ26", now + 48 * day, 0.5, 5.0, 1.0, 1.0, 500.0, 1, 0.1, 4, 3, 1, "BRL"),
            "WIN$N": SymbolInfo("WIN$N", 0, 5.0, 1.0, 1.0, 1.0, 500.0, 0, 1.0, 0, 3, 1, "BRL"),
        }
        self.prices = {"WINV26": 130_500.0, "WINZ26": 131_000.0, "WDOX26": 5_420.5, "WDOZ26": 5_440.0, "WIN$N": 131_000.0}
        self.positions: dict[int, Position] = {}
        self.deals: list[Deal] = []
        self.sent: list[dict] = []
        self._ids = itertools.count(900_000_001)

    # ---------------- utilidades do teste ----------------
    def server_now(self) -> int:
        return int(self.clock()) + self.offset

    def set_price(self, symbol: str, price: float) -> None:
        self.prices[symbol] = price

    def broker_close(self, ticket: int, price: float, comment: str = "[sl]") -> None:
        """Fechamento pela corretora (stop no servidor)."""
        pos = self.positions[ticket]
        self.prices[pos.symbol] = price
        self._close(pos, pos.volume, price, magic=pos.magic, comment=comment, order=next(self._ids))

    # ---------------- API do MetaTrader5 ----------------
    def initialize(self, *a, **k) -> bool:
        return True

    def shutdown(self) -> None:
        return None

    def last_error(self):
        return (1, "Success")

    def account_info(self):
        return self.account

    def terminal_info(self):
        return self.terminal

    def symbols_get(self, group: str = "*"):
        return tuple(s for n, s in self.symbols.items() if fnmatch.fnmatch(n, group))

    def symbol_info(self, name: str):
        return self.symbols.get(name)

    def symbol_select(self, name: str, enable: bool = True) -> bool:
        return name in self.symbols

    def symbol_info_tick(self, name: str):
        if name not in self.prices:
            return None
        p = self.prices[name]
        step = self.symbols[name].trade_tick_size
        return Tick(self.server_now(), p - step, p + step, p)

    def _bars(self, name: str, tf: int, end_server: int, count: int) -> np.ndarray:
        sec = TF_SECONDS[tf]
        last_open = end_server - end_server % sec
        base = self.prices[name]
        rows = []
        for i in range(count):
            t = last_open - (count - 1 - i) * sec
            c = base * (1 + 0.002 * np.sin(i / 7))
            rows.append((t, c - 10, c + 25, c - 25, c, 100, 1, 50))
        return np.array(rows, dtype=RATE_DTYPE)

    def copy_rates_from_pos(self, name, tf, start, count):
        if name not in self.prices:
            return None
        return self._bars(name, tf, self.server_now(), count)

    def copy_rates_range(self, name, tf, date_from: datetime, date_to: datetime):
        if name not in self.prices:
            return None
        sec = TF_SECONDS[tf]
        a, b = int(date_from.timestamp()), min(int(date_to.timestamp()), self.server_now())
        count = max(0, (b - a) // sec)
        return self._bars(name, tf, b, count)

    def positions_get(self, symbol: str | None = None, ticket: int | None = None):
        out = [p for p in self.positions.values() if (symbol is None or p.symbol == symbol) and (ticket is None or p.ticket == ticket)]
        return tuple(out)

    def history_deals_get(self, *args, ticket: int | None = None, position: int | None = None):
        if ticket is not None:
            return tuple(d for d in self.deals if d.ticket == ticket)
        if position is not None:
            return tuple(d for d in self.deals if d.position_id == position)
        a, b = (int(x.timestamp()) for x in args[:2])
        return tuple(d for d in self.deals if a <= d.time <= b)

    def _point_value(self, symbol: str) -> float:
        s = self.symbols[symbol]
        return s.trade_tick_value / s.trade_tick_size

    def _close(self, pos: Position, volume: float, price: float, *, magic: int, comment: str, order: int) -> Deal:
        sign = 1 if pos.type == 0 else -1
        profit = round(sign * (price - pos.price_open) * volume * self._point_value(pos.symbol), 2)
        deal = Deal(next(self._ids), order, self.server_now(), 1 if pos.type == 0 else 0, 1, magic, pos.ticket, volume, price,
                    -self.COMMISSION * volume, 0.0, profit, 0.0, pos.symbol, comment)
        self.deals.append(deal)
        if volume >= pos.volume:
            del self.positions[pos.ticket]
        else:
            self.positions[pos.ticket] = pos._replace(volume=pos.volume - volume)
        return deal

    def order_send(self, req: dict):
        self.sent.append(dict(req))
        order = next(self._ids)
        if req["action"] == self.TRADE_ACTION_SLTP:
            pos = self.positions[req["position"]]
            self.positions[pos.ticket] = pos._replace(sl=req.get("sl", 0.0), tp=req.get("tp", 0.0))
            return Result(self.TRADE_RETCODE_DONE, 0, order, 0.0, 0.0, "done")
        symbol, vol = req["symbol"], float(req["volume"])
        price = self.prices[symbol]
        if "position" in req:  # fechamento (netting com ticket)
            pos = self.positions[req["position"]]
            deal = self._close(pos, vol, price, magic=req["magic"], comment=req["comment"], order=order)
            return Result(self.TRADE_RETCODE_DONE, deal.ticket, order, vol, price, "done")
        ticket = order
        self.positions[ticket] = Position(ticket, symbol, req["type"], vol, price, req["magic"], 0.0, 0.0)
        deal = Deal(next(self._ids), order, self.server_now(), req["type"], 0, req["magic"], ticket, vol, price,
                    -self.COMMISSION * vol, 0.0, 0.0, 0.0, symbol, req["comment"])
        self.deals.append(deal)
        return Result(self.TRADE_RETCODE_DONE, deal.ticket, order, vol, price, "done")
