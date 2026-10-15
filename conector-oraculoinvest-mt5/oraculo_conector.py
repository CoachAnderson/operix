"""Conector OráculoInvest para MetaTrader 5 (futuros da B3).

Roda no Windows do cliente, ao lado do MetaTrader 5 já logado na corretora. Busca comandos no servidor
do OráculoInvest e executa no MetaTrader 5 dele. Login e senha da corretora nunca saem deste computador.

Proteções locais (o servidor não consegue mudar):
  - só opera os ativos da lista `ativos` (padrão WIN e WDO);
  - nunca envia mais que `max_contratos` por ordem;
  - não soma posição em cima de uma posição que já exista no contrato (manual ou de outro robô);
  - só fecha posições abertas por ele mesmo (número mágico do OráculoInvest);
  - o servidor confere se a conta é demo ou real antes de mandar qualquer ordem.

Uso:  python oraculo_conector.py            (lê conector.ini na mesma pasta)
"""
from __future__ import annotations

import configparser
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

VERSION = "1.0.0"
MAGIC = 26051954  # identifica as ordens do OráculoInvest no MetaTrader 5
MONTHS = "FGHJKMNQUVXZ"
ROLL_DAYS = 3  # troca para o próximo vencimento quando faltar isso para o atual
DEFAULT_OFFSET_HOURS = -3  # horário do servidor das corretoras da B3 (Brasília)
TIMEFRAMES = {"1m": "TIMEFRAME_M1", "5m": "TIMEFRAME_M5", "15m": "TIMEFRAME_M15", "30m": "TIMEFRAME_M30",
              "1h": "TIMEFRAME_H1", "4h": "TIMEFRAME_H4", "1d": "TIMEFRAME_D1"}
RETRYABLE = {10004, 10020, 10021, 10024, 10031}  # requote, preço mudou, sem cotação, muitas requisições, sem conexão

log = logging.getLogger("conector")


class CommandError(Exception):
    def __init__(self, message: str, *, retryable: bool = False, code: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.code = code


def tag(coid: str) -> str:
    """Comentário da ordem (o MT5 aceita até 31 caracteres)."""
    return "OI" + re.sub(r"[^0-9a-zA-Z]", "", coid)[2:28]


@dataclass
class Limits:
    roots: list[str] = field(default_factory=lambda: ["WIN", "WDO"])
    max_contracts: int = 5


class Handlers:
    """Executa cada tipo de comando no MetaTrader 5. `mt5` é o módulo MetaTrader5 (ou um simulado nos testes)."""

    def __init__(self, mt5: Any, limits: Limits, offset_hours: float | None = None, clock=time.time):
        self.mt5 = mt5
        self.limits = limits
        self.fixed_offset = None if offset_hours is None else int(offset_hours * 3600)
        self._auto_offset: int | None = None
        self.clock = clock

    # ---------------- utilidades ----------------
    def _err(self, prefix: str) -> CommandError:
        code, msg = self.mt5.last_error()
        return CommandError(f"{prefix}: {msg} ({code})", retryable=True, code=code)

    def offset(self) -> int:
        """Segundos entre o relógio do servidor da corretora e o UTC (Brasília = -10800)."""
        if self.fixed_offset is not None:
            return self.fixed_offset
        if self._auto_offset is None:
            self._auto_offset = DEFAULT_OFFSET_HOURS * 3600
            for root in self.limits.roots:
                try:
                    sym = self.front(root)
                    tick = self.mt5.symbol_info_tick(sym.name)
                except CommandError:
                    continue
                if tick and tick.time:
                    diff = tick.time - self.clock()
                    rounded = int(round(diff / 1800.0) * 1800)
                    if abs(diff - rounded) < 120:  # cotação recente: dá para medir o fuso com segurança
                        self._auto_offset = rounded
                        break
        return self._auto_offset

    def _check_root(self, root: str) -> str:
        root = (root or "").upper()
        if root not in self.limits.roots:
            raise CommandError(f"Ativo {root} não liberado neste conector (liberados: {', '.join(self.limits.roots)})")
        return root

    def _contracts(self, root: str) -> list[Any]:
        pattern = re.compile(rf"^{root}[{MONTHS}]\d{{2}}$")
        syms = self.mt5.symbols_get(group=f"{root}*") or ()
        now_server = self.clock() + self.offset()
        alive = [s for s in syms if pattern.match(s.name) and (not s.expiration_time or s.expiration_time > now_server)]
        return sorted(alive, key=lambda s: s.expiration_time or 0)

    def front(self, root: str) -> Any:
        contracts = self._contracts(root)
        if not contracts:
            raise CommandError(f"Nenhum contrato de {root} disponível no MetaTrader 5. Confira se a conta tem acesso à B3.")
        current = contracts[0]
        now_server = self.clock() + (self.fixed_offset if self.fixed_offset is not None else (self._auto_offset or DEFAULT_OFFSET_HOURS * 3600))
        if len(contracts) > 1 and current.expiration_time and current.expiration_time - now_server < ROLL_DAYS * 86400:
            current = contracts[1]
        if not self.mt5.symbol_select(current.name, True):
            raise self._err(f"Não foi possível selecionar {current.name}")
        return self.mt5.symbol_info(current.name) or current

    def _filling(self, info: Any) -> int:
        m = self.mt5
        if getattr(info, "trade_exemode", None) == getattr(m, "SYMBOL_TRADE_EXECUTION_EXCHANGE", 3):
            return m.ORDER_FILLING_RETURN
        flags = getattr(info, "filling_mode", 0)
        if flags & 1:
            return m.ORDER_FILLING_FOK
        if flags & 2:
            return m.ORDER_FILLING_IOC
        return m.ORDER_FILLING_RETURN

    @staticmethod
    def _round_tick(price: float, tick: float) -> float:
        return round(round(price / tick) * tick, 10) if tick else price

    def _deals_window(self) -> list[Any]:
        now = self.clock() + self.offset()
        start = datetime.fromtimestamp(now - 3 * 86400, UTC)
        end = datetime.fromtimestamp(now + 86400, UTC)
        return list(self.mt5.history_deals_get(start, end) or ())

    def _deal_of(self, result: Any) -> Any:
        if getattr(result, "deal", 0):
            deals = self.mt5.history_deals_get(ticket=result.deal) or ()
            if deals:
                return deals[0]
        deadline = self.clock() + 5
        while True:  # mercado de bolsa: a execução pode chegar logo depois da resposta
            for d in self._deals_window():
                if d.order == result.order:
                    return d
            if self.clock() > deadline:
                raise CommandError("Ordem aceita, mas a execução não apareceu no histórico", retryable=True)
            time.sleep(0.25)

    def _send(self, request: dict) -> Any:
        res = self.mt5.order_send(request)
        if res is None:
            raise self._err("O MetaTrader 5 não aceitou a ordem")
        ok = {self.mt5.TRADE_RETCODE_DONE, getattr(self.mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010), getattr(self.mt5, "TRADE_RETCODE_PLACED", 10008)}
        if res.retcode not in ok:
            raise CommandError(f"Ordem recusada: {res.comment or 'sem detalhe'} (código {res.retcode})", retryable=res.retcode in RETRYABLE, code=res.retcode)
        return res

    @staticmethod
    def _side(deal_type: int) -> str:
        return "buy" if deal_type == 0 else "sell"

    # ---------------- comandos ----------------
    def rules(self, args: dict) -> dict:
        root = self._check_root(args.get("root"))
        info = self.front(root)
        contracts = self._contracts(root)
        names = [c.name for c in contracts]
        nxt = names[names.index(info.name) + 1] if info.name in names and names.index(info.name) + 1 < len(names) else None
        exp = info.expiration_time - self.offset() if getattr(info, "expiration_time", 0) else None
        return {
            "root": root,
            "contract": info.name,
            "next_contract": nxt,
            "tick_size": info.trade_tick_size,
            "tick_value": info.trade_tick_value,
            "volume_min": info.volume_min,
            "volume_step": info.volume_step,
            "volume_max": min(info.volume_max, self.limits.max_contracts),
            "digits": info.digits,
            "expiration": exp,
            "currency": getattr(info, "currency_profit", "BRL") or "BRL",
            "trade_allowed": info.trade_mode == getattr(self.mt5, "SYMBOL_TRADE_MODE_FULL", 4),
        }

    def _series(self, root: str) -> list[str]:
        # Série contínua quando a corretora oferece (histórico longo); senão, o contrato atual.
        names = [f"{root}$N", f"{root}$", f"{root}@N", f"{root}@"]
        return [n for n in names if self.mt5.symbol_info(n) is not None] + [self.front(root).name]

    def _rates(self, rows: Any) -> list[dict]:
        """Converte as barras do MT5 (array do numpy) para UTC real."""
        if rows is None or not len(rows):
            return []
        off = self.offset()
        names = rows.dtype.names
        vol = "real_volume" if "real_volume" in names else "tick_volume"
        return [
            {"t": int(r["time"]) - off, "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]), "c": float(r["close"]), "v": float(r[vol])}
            for r in rows
        ]

    def candles(self, args: dict) -> list[dict]:
        root = self._check_root(args.get("root"))
        tf = getattr(self.mt5, TIMEFRAMES[args["timeframe"]])
        count = int(min(max(args.get("count", 200), 1), 5000))
        for name in self._series(root):
            self.mt5.symbol_select(name, True)
            rows = self.mt5.copy_rates_from_pos(name, tf, 0, count)
            if rows is not None and len(rows):
                return self._rates(rows)
        raise self._err(f"Sem histórico de {root}")

    def candles_range(self, args: dict) -> list[dict]:
        root = self._check_root(args.get("root"))
        tf = getattr(self.mt5, TIMEFRAMES[args["timeframe"]])
        off = self.offset()
        start = datetime.fromtimestamp(int(args["from"]) + off, UTC)
        end = datetime.fromtimestamp(int(args["to"]) + off, UTC)
        for name in self._series(root):
            self.mt5.symbol_select(name, True)
            rows = self.mt5.copy_rates_range(name, tf, start, end)
            if rows is not None and len(rows):
                return self._rates(rows)[: int(args.get("max", 30000))]
        raise self._err(f"Sem histórico de {root} nesse período")

    def tick(self, args: dict) -> dict:
        root = self._check_root(args.get("root"))
        info = self.front(root)
        t = self.mt5.symbol_info_tick(info.name)
        if t is None:
            raise self._err(f"Sem cotação de {info.name}")
        return {"contract": info.name, "bid": t.bid, "ask": t.ask, "last": t.last, "time": int(t.time) - self.offset()}

    def find(self, args: dict) -> dict | None:
        mark = tag(args["coid"])
        for d in sorted(self._deals_window(), key=lambda d: d.time):
            if d.magic == MAGIC and d.comment == mark:
                closing = d.entry in (1, 3)  # DEAL_ENTRY_OUT, DEAL_ENTRY_OUT_BY
                return {"contract": d.symbol, "position": d.position_id, "order": d.order, "deal": d.ticket, "price": d.price,
                        "volume": d.volume, "commission": d.commission, "fee": getattr(d, "fee", 0.0), "swap": d.swap,
                        "profit": d.profit, "side": self._side(d.type), "closing": closing}
        return None

    def open(self, args: dict) -> dict:
        root = self._check_root(args.get("root"))
        volume = float(args["volume"])
        if volume <= 0 or volume != int(volume):
            raise CommandError("Número de contratos inválido")
        if volume > self.limits.max_contracts:
            raise CommandError(f"Ordem de {int(volume)} contratos acima do limite deste conector ({self.limits.max_contracts})")
        done = self.find({"coid": args["coid"]})
        if done:  # reenvio do mesmo comando: devolve a execução que já aconteceu
            return done
        info = self.front(root)
        if self.mt5.positions_get(symbol=info.name):
            raise CommandError(f"Já existe posição aberta em {info.name} nesta conta (manual ou de outro robô). Por segurança, o conector não soma posições.")
        tick = self.mt5.symbol_info_tick(info.name)
        if tick is None:
            raise self._err(f"Sem cotação de {info.name}")
        buy = args["side"] == "buy"
        req = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": info.name,
            "volume": volume,
            "type": self.mt5.ORDER_TYPE_BUY if buy else self.mt5.ORDER_TYPE_SELL,
            "price": tick.ask if buy else tick.bid,
            "deviation": int(max(1, round(info.trade_tick_size * 5 / (info.point or 1)))),
            "magic": MAGIC,
            "comment": tag(args["coid"]),
            "type_time": self.mt5.ORDER_TIME_DAY,
            "type_filling": self._filling(info),
        }
        res = self._send(req)
        deal = self._deal_of(res)
        protection = None
        if args.get("sl") or args.get("tp"):
            sltp = {"action": self.mt5.TRADE_ACTION_SLTP, "symbol": info.name, "position": deal.position_id, "magic": MAGIC}
            if args.get("sl"):
                sltp["sl"] = self._round_tick(float(args["sl"]), info.trade_tick_size)
            if args.get("tp"):
                sltp["tp"] = self._round_tick(float(args["tp"]), info.trade_tick_size)
            r = self.mt5.order_send(sltp)
            protection = bool(r and r.retcode == self.mt5.TRADE_RETCODE_DONE)
            if not protection:
                log.warning("Stop/alvo não aceitos pela corretora; o robô vigia stop e alvo a cada ciclo")
        log.info("ABRIU %s %s %s contrato(s) a %s (posição %s)", "COMPRA" if buy else "VENDA", info.name, volume, deal.price, deal.position_id)
        return {"contract": info.name, "order": res.order, "deal": deal.ticket, "position": deal.position_id, "price": deal.price,
                "volume": deal.volume, "commission": deal.commission, "fee": getattr(deal, "fee", 0.0), "protection": protection}

    def close(self, args: dict) -> dict:
        contract = args["contract"]
        self._check_root(re.sub(rf"[{MONTHS}]\d{{2}}$", "", contract))
        done = self.find({"coid": args["coid"]})
        if done and done.get("closing"):
            return done
        ticket = int(args["position"])
        pos = next(iter(self.mt5.positions_get(ticket=ticket) or ()), None)
        if pos is None:
            raise CommandError(f"A posição {ticket} não está mais aberta (pode ter sido encerrada pelo stop ou manualmente)")
        if pos.magic != MAGIC:
            raise CommandError("Essa posição não foi aberta pelo OráculoInvest; o conector não mexe nela")
        tick = self.mt5.symbol_info_tick(contract)
        info = self.mt5.symbol_info(contract)
        sell = args["side"] == "sell"
        req = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": contract,
            "volume": min(float(args["volume"]), pos.volume),
            "type": self.mt5.ORDER_TYPE_SELL if sell else self.mt5.ORDER_TYPE_BUY,
            "position": ticket,
            "price": tick.bid if sell else tick.ask,
            "deviation": int(max(1, round(info.trade_tick_size * 5 / (info.point or 1)))),
            "magic": MAGIC,
            "comment": tag(args["coid"]),
            "type_time": self.mt5.ORDER_TIME_DAY,
            "type_filling": self._filling(info),
        }
        res = self._send(req)
        deal = self._deal_of(res)
        log.info("FECHOU %s %s contrato(s) a %s, resultado %s", contract, deal.volume, deal.price, deal.profit)
        return {"contract": contract, "position": ticket, "order": res.order, "deal": deal.ticket, "price": deal.price, "volume": deal.volume,
                "profit": deal.profit, "commission": deal.commission, "swap": deal.swap, "fee": getattr(deal, "fee", 0.0)}

    def position_status(self, args: dict) -> dict:
        ticket = int(args["position"])
        if self.mt5.positions_get(ticket=ticket):
            return {"open": True, "closing": None}
        deals = [d for d in (self.mt5.history_deals_get(position=ticket) or ()) if d.entry in (1, 2, 3)]
        if not deals:
            return {"open": False, "closing": None}
        vol = sum(d.volume for d in deals)
        last = max(deals, key=lambda d: d.time)
        return {
            "open": False,
            "closing": {
                "price": sum(d.price * d.volume for d in deals) / vol if vol else last.price,
                "volume": vol,
                "profit": sum(d.profit for d in deals),
                "commission": sum(d.commission for d in deals),
                "swap": sum(d.swap for d in deals),
                "fee": sum(getattr(d, "fee", 0.0) for d in deals),
                "side": self._side(last.type),
                "deal": last.ticket,
                "order": last.order,
            },
        }

    def handle(self, cmd: dict) -> Any:
        kind = cmd.get("type")
        fn = {"rules": self.rules, "candles": self.candles, "candles_range": self.candles_range, "tick": self.tick,
              "open": self.open, "close": self.close, "position_status": self.position_status, "find": self.find}.get(kind)
        if fn is None:
            raise CommandError(f"Comando desconhecido: {kind}")
        return fn(cmd.get("args") or {})


# ---------------- comunicação com o servidor ----------------
class ServerError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class Api:
    def __init__(self, base_url: str, token: str, session: Any = None):
        import requests  # importado aqui para os testes poderem trocar a sessão

        self.base = base_url.rstrip("/") + "/api/v1/mt5/agent"
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "User-Agent": f"OraculoConector/{VERSION}"})

    def _check(self, r: Any) -> Any:
        if r.status_code >= 400:
            try:
                msg = r.json().get("detail", r.text)
            except Exception:  # noqa: BLE001
                msg = r.text
            raise ServerError(r.status_code, str(msg))
        return r.json()

    def hello(self, payload: dict) -> dict:
        return self._check(self.session.post(f"{self.base}/hello", json=payload, timeout=20))

    def poll(self, wait: int = 25) -> list[dict]:
        return self._check(self.session.get(f"{self.base}/poll", params={"wait": wait}, timeout=wait + 15)).get("commands", [])

    def result(self, payload: dict) -> None:
        self._check(self.session.post(f"{self.base}/result", json=payload, timeout=20))


def hello_payload(mt5: Any, limits: Limits) -> dict:
    acc = mt5.account_info()
    term = mt5.terminal_info()
    if acc is None or term is None:
        code, msg = mt5.last_error()
        raise CommandError(f"MetaTrader 5 sem conta conectada: {msg} ({code})", retryable=True)
    return {
        "agent_version": VERSION,
        "account": {"login": acc.login, "server": acc.server, "company": acc.company, "name": acc.name, "currency": acc.currency,
                    "trade_mode": acc.trade_mode, "trade_allowed": bool(acc.trade_allowed and getattr(acc, "trade_expert", True)),
                    "margin_mode": getattr(acc, "margin_mode", None)},
        "terminal": {"trade_allowed": bool(term.trade_allowed), "connected": bool(term.connected), "build": getattr(term, "build", None)},
        "limits": {"roots": limits.roots, "max_contracts": limits.max_contracts},
    }


def process(api: Api, handlers: Handlers, commands: list[dict]) -> None:
    for cmd in commands:
        try:
            data = handlers.handle(cmd)
            api.result({"id": cmd["id"], "ok": True, "data": data})
        except CommandError as exc:
            log.warning("%s: %s", cmd.get("type"), exc)
            api.result({"id": cmd["id"], "ok": False, "error": str(exc), "retryable": exc.retryable, "code": exc.code})
        except Exception as exc:  # noqa: BLE001 - nunca derrubar o conector por um comando
            log.exception("Falha inesperada em %s", cmd.get("type"))
            api.result({"id": cmd["id"], "ok": False, "error": f"Erro no conector: {exc}", "retryable": True})


# ---------------- configuração e laço principal ----------------
@dataclass
class Config:
    url: str
    token: str
    terminal_path: str | None
    offset_hours: float | None
    limits: Limits


def load_config(path: Path) -> Config:
    cp = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
    cp.read(path, encoding="utf-8")
    url = cp.get("servidor", "url", fallback="").strip()
    token = cp.get("servidor", "token", fallback="").strip() or os.environ.get("ORACULO_TOKEN", "")
    if not url or not token:
        raise SystemExit(f"Preencha url e token em {path} (o token aparece no painel: Corretora → MetaTrader 5).")
    off = cp.get("metatrader", "fuso_servidor", fallback="auto").strip().lower()
    roots = [r.strip().upper() for r in cp.get("limites", "ativos", fallback="WIN,WDO").split(",") if r.strip()]
    return Config(
        url=url,
        token=token,
        terminal_path=cp.get("metatrader", "caminho", fallback="").strip() or None,
        offset_hours=None if off in ("", "auto") else float(off),
        limits=Limits(roots=roots, max_contracts=cp.getint("limites", "max_contratos", fallback=5)),
    )


def run(cfg: Config, mt5: Any, api: Api, stop=lambda: False, poll_wait: int = 25) -> None:
    handlers = Handlers(mt5, cfg.limits, cfg.offset_hours)
    last_hello = 0.0
    backoff = 2
    while not stop():
        try:
            if time.time() - last_hello > 60:
                info = api.hello(hello_payload(mt5, cfg.limits))
                if last_hello == 0:
                    log.info("Conectado ao OráculoInvest. Conta %s (%s). Negociação automática: %s",
                             mt5.account_info().login, "conta real" if info.get("venue") == "live" else "conta demo",
                             "LIGADA" if info.get("can_trade") else "DESLIGADA (ative o botão Algo Trading no MetaTrader 5)")
                last_hello = time.time()
            process(api, handlers, api.poll(poll_wait))
            backoff = 2
        except ServerError as exc:
            if exc.status == 428:
                last_hello = 0
                continue
            log.error("Servidor: %s", exc)
            time.sleep(60 if exc.status in (401, 409) else backoff)
            last_hello = 0
        except CommandError as exc:  # MetaTrader 5 fechado ou sem conexão
            log.error("%s. Tentando reconectar…", exc)
            mt5.shutdown()
            time.sleep(backoff)
            mt5.initialize(cfg.terminal_path) if cfg.terminal_path else mt5.initialize()
            last_hello = 0
        except Exception as exc:  # noqa: BLE001 - rede caiu etc.
            log.warning("Sem conexão com o servidor (%s). Nova tentativa em %ss", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)


def main() -> None:
    here = Path(getattr(sys, "_MEIPASS", None) and sys.executable or __file__).resolve().parent
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(here / "conector.log", encoding="utf-8")],
    )
    cfg = load_config(here / "conector.ini")
    try:
        import MetaTrader5 as mt5  # noqa: N813
    except ImportError:
        raise SystemExit("Pacote MetaTrader5 não instalado. Rode o iniciar.bat (ele instala tudo).") from None
    ok = mt5.initialize(cfg.terminal_path) if cfg.terminal_path else mt5.initialize()
    if not ok:
        raise SystemExit(f"Não consegui abrir o MetaTrader 5: {mt5.last_error()}. Abra o MT5, entre na sua conta e tente de novo.")
    log.info("Conector OráculoInvest %s iniciado. Ativos liberados: %s · máximo %s contrato(s) por ordem",
             VERSION, ", ".join(cfg.limits.roots), cfg.limits.max_contracts)
    try:
        run(cfg, mt5, Api(cfg.url, cfg.token))
    except KeyboardInterrupt:
        log.info("Conector encerrado pelo usuário")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
