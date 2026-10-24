"""Recomendador: testa todas as estratégias em vários tempos gráficos numa moeda da Binance e mostra qual se saiu melhor.

Regras para não "recomendar sorte":
- sempre com os custos da Binance à vista (0,1% por lado + 0,05% de escorregamento) e só comprado (mercado à vista);
- o período é dividido em AJUSTE (70%) e CONFIRMAÇÃO (30% finais): só é "aprovada" a combinação que ganhou nos dois
  e teve operações suficientes; "nenhuma" é uma resposta válida;
- a ordem do ranking usa o resultado na confirmação (o trecho que não serviu para escolher).

Roda em segundo plano (pode levar mais que o limite de uma requisição) e o resultado fica em cache por 1 hora para a
mesma moeda e período, compartilhado entre os clientes (é o mesmo histórico público).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.redis import get_redis
from app.engine.backtest import BacktestConfig, filter_warmup, run_backtest
from app.services.brokers.base import BrokerError
from app.strategies.filters import STRATEGY_FAMILY, TF_MS
from app.strategies.library import STRATEGIES

log = logging.getLogger(__name__)

# Tempos gráficos testados por estratégia (os que fazem sentido para cada estilo).
CANDIDATES: dict[str, tuple[str, ...]] = {
    "scalp_media": ("5m", "15m"),
    "reversao_ams": ("1m",),
    "ema_cross_day": ("5m", "15m", "1h"),
    "rsi_reversion": ("15m", "1h"),
    "ema_cross_swing": ("4h", "1d"),
    "donchian_breakout": ("4h", "1d"),
}
# Histórico máximo por tempo gráfico (dias), para caber no limite de candles do backtest.
MAX_DAYS = {"1m": 30, "5m": 100, "15m": 300, "30m": 600, "1h": 730, "4h": 730, "1d": 730}
OOS_PCT = 30
MIN_TRADES = 20
MIN_CONF_TRADES = 8
CACHE_TTL = 3600
JOB_TTL = 3600

COSTS = {"fee_rate": 0.001, "slippage_bps": 5.0}
BASE = {"initial_balance": 1000.0, "order_size_quote": 100.0, "stop_loss_pct": 2.0, "take_profit_pct": 4.0, "max_trades_per_day": 500}

VERDICT_RANK = {"approved": 0, "marginal": 1, "only_fit": 2, "rejected": 3, "few_trades": 4, "error": 5}


@dataclass
class Combo:
    strategy: str
    timeframe: str


def combos() -> list[Combo]:
    return [Combo(code, tf) for code, tfs in CANDIDATES.items() if code in STRATEGIES for tf in tfs]


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


def evaluate(result) -> dict:
    """Resumo de um backtest + selo (aprovada, só no ajuste, reprovada, poucas operações)."""
    m = result.metrics
    seg = {s.label: s for s in result.segments}
    fit, conf = seg.get("Ajuste"), seg.get("Confirmação")
    pf = lambda s: (s.profit_factor if s and s.profit_factor is not None else (99.0 if s and s.trades and s.net_pnl > 0 else 0.0))  # noqa: E731
    if m.trades < MIN_TRADES or not conf or conf.trades < MIN_CONF_TRADES:
        verdict = "few_trades"
    elif pf(fit) >= 1.1 and pf(conf) >= 1.1 and fit.net_pnl > 0 and conf.net_pnl > 0:
        verdict = "approved"
    elif fit.net_pnl > 0 and conf.net_pnl > 0:
        verdict = "marginal"  # ganhou nos dois, mas pouco (fator de lucro abaixo de 1,1 em algum)
    elif pf(fit) >= 1.0 and fit.net_pnl > 0:
        verdict = "only_fit"
    else:
        verdict = "rejected"

    def s(x):
        return None if not x else {"trades": x.trades, "win_rate_pct": x.win_rate_pct, "profit_factor": _f(x.profit_factor),
                                   "return_pct": x.return_pct, "net_pnl": x.net_pnl, "buy_hold_pct": x.buy_hold_pct}

    return {
        "verdict": verdict,
        "trades": m.trades,
        "win_rate_pct": m.win_rate_pct,
        "breakeven_win_rate_pct": m.breakeven_win_rate_pct,
        "profit_factor": _f(m.profit_factor),
        "net_pnl": m.net_pnl,
        "return_pct": m.return_pct,
        "buy_hold_pct": m.buy_hold_pct,
        "max_drawdown_pct": m.max_drawdown_pct,
        "fees_total": m.fees_total,
        "fit": s(fit),
        "confirm": s(conf),
        "start": result.start,
        "end": result.end,
    }


def sort_key(row: dict) -> tuple:
    conf = row.get("confirm") or {}
    return (VERDICT_RANK.get(row["verdict"], 9), -(conf.get("profit_factor") or 0), -(conf.get("return_pct") or -1e9))


async def _load(symbol: str, tf: str, days: int, warmup: int, load_candles) -> list:
    step = TF_MS[tf]
    days = min(days, MAX_DAYS.get(tf, days))
    end = datetime.now(UTC).replace(second=0, microsecond=0)
    start = end - timedelta(days=days)
    start_ms = int(start.timestamp() * 1000) - warmup * step
    return await load_candles(symbol, tf, start_ms, int(end.timestamp() * 1000))


async def analyze(job: dict, load_candles) -> None:
    """Executa as combinações em sequência, atualizando o progresso em `job`."""
    symbol, days = job["symbol"], job["days"]
    rows: list[dict] = []
    for i, c in enumerate(combos()):
        strat = STRATEGIES[c.strategy]
        job["current"] = f"{strat.name} · {c.timeframe}"
        base_row = {"strategy": c.strategy, "name": strat.name, "timeframe": c.timeframe, "style": strat.style}
        try:
            params = strat.parse_params({"timeframe": c.timeframe})
            warmup = max(strat.required_candles(params), filter_warmup(None, c.timeframe)) + 2
            candles = await _load(symbol, c.timeframe, days, warmup, load_candles)
            split = None
            if len(candles) > warmup + 10:
                first = candles[warmup].open_time
                split = first + int((candles[-1].close_time - first) * (1 - OOS_PCT / 100))
            cfg = BacktestConfig(**BASE, **COSTS, allow_short=False, timeframe=c.timeframe,
                                 family=STRATEGY_FAMILY.get(c.strategy, "trend"), split_time=split)
            result = await asyncio.to_thread(run_backtest, strat, params, candles, cfg)
            rows.append({**base_row, **evaluate(result)})
        except BrokerError as exc:
            if "Invalid symbol" in str(exc) or "-1121" in str(exc):
                raise
            rows.append({**base_row, "verdict": "error", "error": str(exc)[:200]})
        except ValueError as exc:  # histórico curto demais etc.
            rows.append({**base_row, "verdict": "error", "error": str(exc)[:200]})
        job["done"] = i + 1
        job["results"] = sorted(rows, key=sort_key)
    job["results"] = sorted(rows, key=sort_key)


# ---------------------------------------------------------------- tarefas em segundo plano
_jobs: dict[str, dict] = {}


def _cache_key(symbol: str, days: int) -> str:
    return f"rec:{symbol}:{days}"


async def start(symbol: str, days: int, load_candles, owner: str = "") -> dict:
    """Começa (ou reaproveita) uma análise. Devolve o estado inicial da tarefa."""
    r = get_redis()
    cached = await r.get(_cache_key(symbol, days))
    job_id = uuid.uuid4().hex
    if cached:
        data = json.loads(cached)
        job = {**data, "id": job_id, "status": "done", "cached": True, "_owner": owner}
        _jobs[job_id] = job
        return job
    job = {"id": job_id, "status": "running", "symbol": symbol, "days": days, "done": 0, "total": len(combos()),
           "current": "", "results": [], "started_at": time.time(), "cached": False, "oos_pct": OOS_PCT, "_owner": owner,
           "config": {**BASE, **COSTS}}
    _jobs[job_id] = job

    async def run() -> None:
        try:
            await analyze(job, load_candles)
            job["status"] = "done"
            job["finished_at"] = time.time()
            keep = {k: v for k, v in job.items() if k != "id" and not k.startswith("_")}
            await r.set(_cache_key(symbol, days), json.dumps(keep), ex=CACHE_TTL)
        except BrokerError as exc:
            job["status"], job["error"] = "error", f"Não foi possível baixar o histórico de {symbol} na Binance: {exc}"
        except Exception:  # noqa: BLE001
            log.exception("Falha no recomendador (%s)", symbol)
            job["status"], job["error"] = "error", "Falha inesperada ao analisar. Tente de novo."
        finally:
            _cleanup()

    job["_task"] = asyncio.get_running_loop().create_task(run())
    return job


def get(job_id: str) -> dict | None:
    return _jobs.get(job_id)


def public(job: dict) -> dict:
    return {k: v for k, v in job.items() if not k.startswith("_")}


def _cleanup() -> None:
    now = time.time()
    for k in [k for k, j in _jobs.items() if now - j.get("started_at", now) > JOB_TTL and j.get("status") != "running"]:
        _jobs.pop(k, None)
