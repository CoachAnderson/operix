#!/usr/bin/env python3
"""
Reversão AMS — backtester de reversão em candles de 1 minuto.

Regras da estratégia
--------------------
1. Só candles de 1 minuto.
2. A cada candle novo, olha os 5 candles anteriores JÁ FECHADOS.
3. Alta: fechamento > abertura.  Baixa: fechamento < abertura.  Doji: fechamento = abertura (não conta).
4. 3, 4 ou 5 de ALTA  -> VENDA/PUT na abertura do 6º candle.
5. 3, 4 ou 5 de BAIXA -> COMPRA/CALL na abertura do 6º candle.
6. Operação de 1 candle: entra na abertura do 6º e sai no fechamento do 6º.
7. WIN:  CALL com fechamento > abertura;  PUT com fechamento < abertura.  Fechamento = abertura -> EMPATE.

Sem look-ahead: o sinal do candle i usa só as linhas i-5 .. i-1. O preço de entrada é a abertura do
candle i, que já é conhecida no instante da entrada; o fechamento do candle i só é usado para apurar o
resultado. Não há martingale: todas as entradas têm o mesmo valor.

Uso
---
    python reversao_ams.py dados.csv                 # relatório completo na pasta "resultados"
    python reversao_ams.py dados.csv --payout 0.87 --valor 5 --fuso America/Sao_Paulo
    python reversao_ams.py                           # sem arquivo: roda um EXEMPLO FICTÍCIO

O CSV precisa de: timestamp, open, high, low, close, volume (aceita também nomes em português e o
formato de exportação do MetaTrader 5: <DATE> <TIME> <OPEN> ...). Veja `python reversao_ams.py -h`.
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import itertools
import math
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from scipy.stats import binomtest
except ImportError:  # sem scipy, usa a aproximação normal
    binomtest = None

NOME = "Reversão AMS"
JANELA = 5           # candles analisados
MAIORIA = 3          # mínimo de candles na mesma direção
DIAS_SEMANA = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
PADROES = ["3x2", "4x1", "5x0"]
ESTRATEGIAS = {
    "reversao": "A) Reversão AMS (3 de 5, contra a maioria)",
    "aleatoria": "B) Entrada aleatória (mesmos candles, direção sorteada)",
    "maioria": "C) Seguir a maioria (3 de 5, a favor)",
}


# =============================================================================================
# Configuração
# =============================================================================================
@dataclass
class Config:
    modo: str = "binaria"          # "binaria" (payout fixo) ou "preco" (variação do preço)
    payout: float = 0.85           # binária: lucro do WIN como fração do valor (0,85 = 85%)
    valor_entrada: float = 10.0    # valor fixo de cada entrada (sem martingale)
    saldo_inicial: float = 1000.0
    custo_pct: float = 0.0         # modo preço: custo por operação, em % do valor
    fuso_dados: str = "UTC"        # fuso dos horários do CSV quando eles vêm sem fuso
    fuso_relatorio: str = "America/Sao_Paulo"
    exigir_sequencia: bool = True  # pula sinais quando falta algum minuto entre os 6 candles
    semente: int = 42
    simulacoes: int = 1000         # sorteios da entrada aleatória (Monte Carlo)
    min_ops_hora: int = 30         # mínimo de operações para um horário entrar no ranking

    @property
    def breakeven(self) -> float | None:
        """Taxa de acerto que zera o resultado na binária: WIN paga payout, LOSS perde 1."""
        return 1 / (1 + self.payout) if self.modo == "binaria" else None


# =============================================================================================
# Leitura do CSV
# =============================================================================================
_ALIASES = {
    "timestamp": ["timestamp", "datetime", "date_time", "data_hora", "datahora", "open_time", "time_open", "gmt_time", "local_time", "tempo"],
    "open": ["open", "abertura", "abert", "o"],
    "high": ["high", "maxima", "max", "h"],
    "low": ["low", "minima", "min", "l"],
    "close": ["close", "fechamento", "fech", "ultimo", "c"],
    "volume": ["volume", "tick_volume", "tickvol", "vol", "real_volume", "quantidade", "v"],
}
_DATA = ["date", "data", "dia"]
_HORA = ["time", "hora", "horario"]


def _norm(nome: str) -> str:
    s = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode()
    return re.sub(r"[\s\-]+", "_", s.strip().strip("<>").strip().lower())


def _numero(s: pd.Series) -> pd.Series:
    """Converte texto em número aceitando 1234.5, 1234,5, 1.234,5 e 1,234.5."""
    txt = s.astype(str).str.strip().str.replace(" ", "", regex=False)
    amostra = txt.dropna().head(500)
    tem_v, tem_p = amostra.str.contains(",").any(), amostra.str.contains(r"\.").any()
    if tem_v and tem_p:
        ult_v = amostra.str.rfind(",").max()
        ult_p = amostra.str.rfind(".").max()
        txt = txt.str.replace(".", "", regex=False).str.replace(",", ".", regex=False) if ult_v > ult_p else txt.str.replace(",", "", regex=False)
    elif tem_v:
        txt = txt.str.replace(",", ".", regex=False)
    return pd.to_numeric(txt, errors="coerce")


def _tempo(s: pd.Series, fuso_dados: str) -> pd.Series:
    num = pd.to_numeric(s, errors="coerce")
    if num.notna().all():  # epoch
        m = num.abs().max()
        unidade = "us" if m > 1e14 else "ms" if m > 1e11 else "s"
        return pd.to_datetime(num.astype("int64"), unit=unidade, utc=True)
    txt = s.astype(str).str.strip().str.replace(r"^(\d{4})\.(\d{2})\.(\d{2})", r"\1-\2-\3", regex=True)  # 2024.01.02 (MT5)
    try:
        t = pd.to_datetime(txt, format="ISO8601")
    except (ValueError, TypeError):
        try:
            t = pd.to_datetime(txt, format="ISO8601", utc=True)  # fusos diferentes no mesmo arquivo
        except (ValueError, TypeError):
            t = pd.to_datetime(txt, dayfirst=True, format="mixed")  # 02/01/2024 09:00
    if t.dt.tz is None:
        t = t.dt.tz_localize(fuso_dados, ambiguous="NaT", nonexistent="NaT")
    return t.dt.tz_convert("UTC")


def carregar_csv(caminho: str | Path, cfg: Config) -> tuple[pd.DataFrame, dict]:
    """Lê o CSV, padroniza colunas e valida que os candles são de 1 minuto."""
    caminho = Path(caminho)
    with open(caminho, encoding="utf-8-sig", errors="replace") as f:
        cabecalho = f.readline()
    sep = max([";", ",", "\t"], key=cabecalho.count)
    if cabecalho.count(sep) == 0:
        sep = r"\s+"
    bruto = pd.read_csv(caminho, sep=sep, dtype=str, encoding="utf-8-sig", engine="python" if sep == r"\s+" else "c")
    bruto.columns = [_norm(c) for c in bruto.columns]
    cols = set(bruto.columns)

    def achar(chave: str) -> str | None:
        return next((a for a in _ALIASES[chave] if a in cols), None)

    escolhidas = {k: achar(k) for k in _ALIASES}
    data_col, hora_col = next((a for a in _DATA if a in cols), None), next((a for a in _HORA if a in cols), None)
    if escolhidas["timestamp"] is None:
        if data_col and hora_col:
            bruto["__ts"] = bruto[data_col].str.strip() + " " + bruto[hora_col].str.strip()
            escolhidas["timestamp"] = "__ts"
        else:
            escolhidas["timestamp"] = data_col or hora_col
    faltam = [k for k in ("timestamp", "open", "high", "low", "close") if escolhidas[k] is None]
    if faltam:
        raise ValueError(f"Colunas não encontradas: {', '.join(faltam)}. Colunas do arquivo: {', '.join(bruto.columns)}")

    df = pd.DataFrame({"ts": _tempo(bruto[escolhidas["timestamp"]], cfg.fuso_dados)})
    for k in ("open", "high", "low", "close"):
        df[k] = _numero(bruto[escolhidas[k]])
    df["volume"] = _numero(bruto[escolhidas["volume"]]) if escolhidas["volume"] else np.nan

    info = {"arquivo": caminho.name, "linhas_lidas": len(df)}
    invalidas = df[["ts", "open", "close"]].isna().any(axis=1)
    info["linhas_invalidas"] = int(invalidas.sum())
    df = df[~invalidas].sort_values("ts", kind="stable")
    dup = df["ts"].duplicated(keep="first")
    info["horarios_duplicados"] = int(dup.sum())
    df = df[~dup].reset_index(drop=True)
    if len(df) < JANELA + 1:
        raise ValueError(f"São necessários pelo menos {JANELA + 1} candles; o arquivo tem {len(df)}.")

    passos = df["ts"].diff().dropna().dt.total_seconds()
    comum = float(passos.mode().iloc[0])
    if comum != 60:
        raise ValueError(f"O arquivo não parece ter candles de 1 minuto: o intervalo mais comum é de {comum:g} s. "
                         "A Reversão AMS trabalha exclusivamente com candles de 1 minuto.")
    alto = df[["open", "close"]].max(axis=1)
    baixo = df[["open", "close"]].min(axis=1)
    info["ohlc_inconsistente"] = int(((df["high"] < alto) | (df["low"] > baixo)).sum()) if df["high"].notna().all() else 0
    info["lacunas"] = int((passos > 60).sum())
    info["minutos_faltando"] = int((passos[passos > 60] / 60 - 1).sum())
    return df, info


def preparar(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    df = df.copy()
    df["local"] = df["ts"].dt.tz_convert(cfg.fuso_relatorio)
    return df


# =============================================================================================
# Sinais e operações
# =============================================================================================
def direcoes(df: pd.DataFrame) -> np.ndarray:
    """1 = alta, -1 = baixa, 0 = doji."""
    return np.sign(df["close"].to_numpy(float) - df["open"].to_numpy(float)).astype(np.int8)


def gerar_operacoes(df: pd.DataFrame, cfg: Config, regra: str = "reversao", rng: np.random.Generator | None = None,
                    detalhado: bool = False) -> tuple[pd.DataFrame, dict]:
    """Gera as operações de uma regra: "reversao" (A), "aleatoria" (B) ou "maioria" (C).

    Para o candle i (o 6º), só as linhas i-5..i-1 decidem o sinal. Os vetores n_alta/n_baixa vêm de somas
    acumuladas deslocadas, então o candle i nunca entra na própria decisão.
    """
    o, c = df["open"].to_numpy(float), df["close"].to_numpy(float)
    d = direcoes(df)
    n = len(d)
    i = np.arange(JANELA, n)
    acum_alta = np.concatenate(([0], np.cumsum(d == 1)))
    acum_baixa = np.concatenate(([0], np.cumsum(d == -1)))
    n_alta = acum_alta[i] - acum_alta[i - JANELA]       # candles i-5 .. i-1
    n_baixa = acum_baixa[i] - acum_baixa[i - JANELA]

    seg = ((df["ts"] - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(seconds=1)).to_numpy(np.int64)
    passo_ok = np.concatenate(([0], np.cumsum(np.diff(seg) == 60)))
    seguidos = (passo_ok[i] - passo_ok[i - JANELA]) == JANELA  # i-5 -> i sem minuto faltando
    if not cfg.exigir_sequencia:
        seguidos = np.ones_like(seguidos, dtype=bool)

    maioria_alta, maioria_baixa = n_alta >= MAIORIA, n_baixa >= MAIORIA
    tem_padrao = maioria_alta | maioria_baixa
    valido = tem_padrao & seguidos
    stats = {"candles_avaliados": int(len(i)), "com_padrao": int(tem_padrao.sum()),
             "pulados_por_lacuna": int((tem_padrao & ~seguidos).sum())}

    sel = i[valido]
    if regra == "reversao":
        sinal = np.where(maioria_alta, -1, 1)[valido]           # maioria de alta -> PUT
    elif regra == "maioria":
        sinal = np.where(maioria_alta, 1, -1)[valido]           # maioria de alta -> CALL
    elif regra == "aleatoria":
        rng = rng or np.random.default_rng(cfg.semente)
        sinal = rng.choice(np.array([-1, 1], dtype=np.int64), size=len(sel))
    else:
        raise ValueError(f"Regra desconhecida: {regra}")

    entrada, saida = o[sel], c[sel]
    res = np.sign(saida - entrada).astype(np.int64) * sinal   # 1 WIN, -1 LOSS, 0 EMPATE
    retorno_pct = sinal * (saida - entrada) / entrada * 100 + 0.0  # + 0.0 evita "-0" nos empates
    fin = financeiro(res, retorno_pct, cfg)
    maj = np.maximum(n_alta, n_baixa)[valido]

    ops = pd.DataFrame({
        "data_hora": df["local"].iloc[sel].reset_index(drop=True),
        "qtd_alta": n_alta[valido],
        "qtd_baixa": n_baixa[valido],
        "qtd_doji": JANELA - n_alta[valido] - n_baixa[valido],
        "padrao": pd.Categorical([f"{m}x{JANELA - m}" for m in maj], categories=PADROES),
        "maioria": np.where(maioria_alta[valido], "ALTA", "BAIXA"),
        "sinal": np.where(sinal == 1, "CALL", "PUT"),
        "preco_entrada": entrada,
        "preco_saida": saida,
        "resultado": pd.Categorical(np.select([res == 1, res == -1], ["WIN", "LOSS"], "EMPATE"), categories=["WIN", "LOSS", "EMPATE"]),
        "retorno_preco_pct": retorno_pct,
        "resultado_financeiro": fin,
    })
    ops["saldo"] = cfg.saldo_inicial + np.cumsum(fin)
    ops["hora"] = ops["data_hora"].dt.hour
    ops["dia_semana"] = pd.Categorical(ops["data_hora"].dt.dayofweek.map(dict(enumerate(DIAS_SEMANA))), categories=DIAS_SEMANA)

    if detalhado:
        letras = np.array(["B", "D", "A"])[d + 1]   # -1 B(aixa), 0 D(oji), 1 A(lta)
        ops.insert(1, "inicio_janela", df["local"].iloc[sel - JANELA].reset_index(drop=True))
        seq = letras[sel - JANELA]
        for k in range(1, JANELA):
            seq = np.char.add(np.char.add(seq, " "), letras[sel - JANELA + k])
        ops.insert(2, "candles_analisados", seq)
        for k in range(1, JANELA + 1):  # c1 = mais antigo, c5 = último fechado antes da entrada
            j = sel - JANELA - 1 + k
            ops[f"c{k}_abertura"] = o[j]
            ops[f"c{k}_fechamento"] = c[j]
    return ops, stats


def financeiro(res: np.ndarray, retorno_pct: np.ndarray, cfg: Config) -> np.ndarray:
    if cfg.modo == "binaria":
        return np.select([res == 1, res == -1], [cfg.valor_entrada * cfg.payout, -cfg.valor_entrada], 0.0)
    return cfg.valor_entrada * retorno_pct / 100 - cfg.valor_entrada * cfg.custo_pct / 100


# =============================================================================================
# Métricas e estatística
# =============================================================================================
def maior_sequencia(resultados: pd.Series, alvo: str) -> int:
    """Maior sequência de `alvo`. Empates são ignorados: não aumentam nem interrompem a sequência."""
    seq = [r for r in resultados.astype(str) if r != "EMPATE"]
    return max((len(list(g)) for k, g in itertools.groupby(seq) if k == alvo), default=0)


def drawdown(saldo: np.ndarray, inicial: float) -> tuple[float, float]:
    curva = np.concatenate(([inicial], saldo))
    pico = np.maximum.accumulate(curva)
    queda = pico - curva
    k = int(np.argmax(queda))
    return float(queda[k]), float(queda[k] / pico[k] * 100) if pico[k] > 0 else float("nan")


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    centro = (p + z * z / (2 * n)) / (1 + z * z / n)
    meia = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centro - meia, centro + meia


def p_binomial(k: int, n: int, p0: float = 0.5, alternativa: str = "two-sided") -> float:
    if n == 0:
        return float("nan")
    if binomtest is not None:
        return float(binomtest(k, n, p0, alternative=alternativa).pvalue)
    z = (k - n * p0) / math.sqrt(n * p0 * (1 - p0))
    cauda = 0.5 * math.erfc(abs(z) / math.sqrt(2))
    return min(1.0, 2 * cauda) if alternativa == "two-sided" else (0.5 * math.erfc(z / math.sqrt(2)) if alternativa == "greater" else 1 - 0.5 * math.erfc(z / math.sqrt(2)))


def resumo(ops: pd.DataFrame, cfg: Config) -> dict:
    w = int((ops["resultado"] == "WIN").sum())
    l = int((ops["resultado"] == "LOSS").sum())
    e = int((ops["resultado"] == "EMPATE").sum())
    dd, dd_pct = drawdown(ops["saldo"].to_numpy(), cfg.saldo_inicial) if len(ops) else (0.0, 0.0)
    sem_saldo = np.flatnonzero(ops["saldo"].to_numpy() < cfg.valor_entrada)
    return {
        "operacoes": len(ops), "win": w, "loss": l, "empate": e,
        "taxa_acerto_pct": w / (w + l) * 100 if w + l else float("nan"),          # sem empates
        "taxa_acerto_com_empates_pct": w / len(ops) * 100 if len(ops) else float("nan"),
        "resultado_liquido": float(ops["resultado_financeiro"].sum()),
        "saldo_final": cfg.saldo_inicial + float(ops["resultado_financeiro"].sum()),
        "media_por_operacao": float(ops["resultado_financeiro"].mean()) if len(ops) else float("nan"),
        "retorno_preco_total_pct": float(ops["retorno_preco_pct"].sum()),
        "maior_seq_win": maior_sequencia(ops["resultado"], "WIN"),
        "maior_seq_loss": maior_sequencia(ops["resultado"], "LOSS"),
        "drawdown_max": dd, "drawdown_max_pct": dd_pct,
        # Primeira operação depois da qual o saldo não cobre mais uma entrada (o teste continua para medir a regra).
        "sem_saldo_apos_operacao": int(sem_saldo[0]) + 1 if len(sem_saldo) else None,
        "sem_saldo_em": ops["data_hora"].iloc[sem_saldo[0]] if len(sem_saldo) else None,
    }


def testes_estatisticos(r: dict, cfg: Config) -> dict:
    k, n = r["win"], r["win"] + r["loss"]
    lo, hi = wilson(k, n)
    out = {
        "n_sem_empates": n,
        "taxa_acerto_pct": r["taxa_acerto_pct"],
        "ic95_inferior_pct": lo * 100, "ic95_superior_pct": hi * 100,
        "z_vs_50": (k - n / 2) / math.sqrt(n / 4) if n else float("nan"),
        "p_valor_vs_50_bilateral": p_binomial(k, n, 0.5),
        "significativo_5pct": bool(n and p_binomial(k, n, 0.5) < 0.05),
    }
    if cfg.breakeven is not None:
        out["breakeven_pct"] = cfg.breakeven * 100
        out["p_valor_acima_breakeven"] = p_binomial(k, n, cfg.breakeven, "greater")
    return out


def monte_carlo(ops_a: pd.DataFrame, cfg: Config, rng: np.random.Generator) -> dict:
    """Sorteia a direção nos MESMOS candles da estratégia A, `simulacoes` vezes."""
    S = cfg.simulacoes
    mov = np.sign(ops_a["preco_saida"].to_numpy() - ops_a["preco_entrada"].to_numpy()).astype(np.int8)
    abs_ret = np.abs(ops_a["retorno_preco_pct"].to_numpy())
    n_dec = int((mov != 0).sum())
    taxas, liquidos = np.empty(S), np.empty(S)
    lote = max(1, int(2e7 // max(len(mov), 1)))
    feito = 0
    while feito < S:
        m = min(lote, S - feito)
        s = rng.choice(np.array([-1, 1], dtype=np.int8), size=(m, len(mov)))
        res = s * mov
        wins = (res == 1).sum(axis=1)
        taxas[feito:feito + m] = wins / n_dec * 100 if n_dec else np.nan
        if cfg.modo == "binaria":
            liquidos[feito:feito + m] = wins * cfg.valor_entrada * cfg.payout - (res == -1).sum(axis=1) * cfg.valor_entrada
        else:
            liquidos[feito:feito + m] = (cfg.valor_entrada * (s * abs_ret * (mov != 0)) / 100).sum(axis=1) - len(mov) * cfg.valor_entrada * cfg.custo_pct / 100
        feito += m
    r = resumo(ops_a, cfg)
    dist = np.abs(taxas - 50)
    return {
        "simulacoes": S,
        "taxa_media_pct": float(np.nanmean(taxas)),
        "taxa_p2_5_pct": float(np.nanpercentile(taxas, 2.5)), "taxa_p97_5_pct": float(np.nanpercentile(taxas, 97.5)),
        "liquido_medio": float(liquidos.mean()),
        "liquido_p2_5": float(np.percentile(liquidos, 2.5)), "liquido_p97_5": float(np.percentile(liquidos, 97.5)),
        "percentil_taxa_A": float((taxas < r["taxa_acerto_pct"]).mean() * 100),
        "percentil_liquido_A": float((liquidos < r["resultado_liquido"]).mean() * 100),
        "p_valor_empirico": float(((dist >= abs(r["taxa_acerto_pct"] - 50) - 1e-12).sum() + 1) / (S + 1)),
        "taxas": taxas, "liquidos": liquidos,
    }


def agrupar(ops: pd.DataFrame, coluna: str) -> pd.DataFrame:
    tmp = ops.assign(win=ops["resultado"] == "WIN", loss=ops["resultado"] == "LOSS", empate=ops["resultado"] == "EMPATE")
    g = tmp.groupby(coluna, observed=False).agg(
        operacoes=("resultado", "size"), win=("win", "sum"), loss=("loss", "sum"), empate=("empate", "sum"),
        resultado_liquido=("resultado_financeiro", "sum"), retorno_preco_pct=("retorno_preco_pct", "sum"),
    ).reset_index()
    dec = g["win"] + g["loss"]
    g["taxa_acerto_pct"] = np.where(dec > 0, g["win"] / dec.replace(0, np.nan) * 100, np.nan)
    g["p_valor_vs_50"] = [p_binomial(int(w), int(w + l)) for w, l in zip(g["win"], g["loss"])]
    return g[[coluna, "operacoes", "win", "loss", "empate", "taxa_acerto_pct", "resultado_liquido", "retorno_preco_pct", "p_valor_vs_50"]]


def melhores_piores_horarios(por_hora: pd.DataFrame, cfg: Config, n: int = 5) -> pd.DataFrame:
    base = por_hora[por_hora["operacoes"] >= cfg.min_ops_hora].copy()
    testes = max(len(base), 1)
    base["p_valor_bonferroni"] = (base["p_valor_vs_50"] * testes).clip(upper=1)
    melhores = base.sort_values(["taxa_acerto_pct", "resultado_liquido"], ascending=False).head(n).assign(grupo="Melhores")
    piores = base.sort_values(["taxa_acerto_pct", "resultado_liquido"], ascending=True).head(n).assign(grupo="Piores")
    return pd.concat([melhores, piores], ignore_index=True)[["grupo", "hora", "operacoes", "win", "loss", "empate", "taxa_acerto_pct", "resultado_liquido", "p_valor_vs_50", "p_valor_bonferroni"]]


# =============================================================================================
# Execução completa
# =============================================================================================
@dataclass
class Resultado:
    cfg: Config
    info: dict
    ops: dict            # regra -> DataFrame
    stats_sinais: dict
    resumos: dict        # regra -> dict
    testes: dict         # regra -> dict
    por_hora: pd.DataFrame
    por_padrao: pd.DataFrame
    por_padrao_sinal: pd.DataFrame
    por_dia: pd.DataFrame
    horarios_rank: pd.DataFrame
    mc: dict
    dados: pd.DataFrame
    exemplo: bool = False


def backtest(df: pd.DataFrame, cfg: Config, info: dict | None = None, exemplo: bool = False) -> Resultado:
    dados = preparar(df, cfg)
    rng = np.random.default_rng(cfg.semente)
    ops, stats = {}, {}
    ops["reversao"], stats = gerar_operacoes(dados, cfg, "reversao", detalhado=True)
    ops["aleatoria"], _ = gerar_operacoes(dados, cfg, "aleatoria", rng=rng)
    ops["maioria"], _ = gerar_operacoes(dados, cfg, "maioria")
    resumos = {k: resumo(v, cfg) for k, v in ops.items()}
    testes = {k: testes_estatisticos(resumos[k], cfg) for k in ops}
    a = ops["reversao"]
    por_hora = agrupar(a, "hora")
    por_hora = por_hora[por_hora["operacoes"] > 0].reset_index(drop=True)
    info = dict(info or {})
    d = direcoes(dados)
    info.update({
        "candles": len(dados), "inicio": dados["local"].iloc[0], "fim": dados["local"].iloc[-1],
        "dias_com_dados": int(dados["local"].dt.date.nunique()),
        "candles_alta_pct": float((d == 1).mean() * 100), "candles_baixa_pct": float((d == -1).mean() * 100),
        "candles_doji_pct": float((d == 0).mean() * 100),
    })
    return Resultado(
        cfg=cfg, info=info, ops=ops, stats_sinais=stats, resumos=resumos, testes=testes,
        por_hora=por_hora, por_padrao=agrupar(a, "padrao"),
        por_padrao_sinal=agrupar(a.assign(padrao_sinal=a["padrao"].astype(str) + " " + a["sinal"]), "padrao_sinal"),
        por_dia=agrupar(a, "dia_semana"), horarios_rank=melhores_piores_horarios(por_hora, cfg),
        mc=monte_carlo(a, cfg, rng) if len(a) and cfg.simulacoes > 0 else {}, dados=dados, exemplo=exemplo,
    )


# =============================================================================================
# Formatação
# =============================================================================================
def br(x, casas: int = 2) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    s = f"{x:,.{casas}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def pval(p: float) -> str:
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "—"
    return "< 0,0001" if p < 1e-4 else br(p, 4)


def dinheiro(x: float) -> str:
    return ("−" if x < 0 else "") + br(abs(x))


def _tabela_fmt(t: pd.DataFrame) -> pd.DataFrame:
    """Cópia com números em formato brasileiro e nomes de colunas legíveis."""
    nomes = {"hora": "Hora", "padrao": "Padrão", "padrao_sinal": "Padrão / sinal", "dia_semana": "Dia", "grupo": "Grupo",
             "operacoes": "Operações", "win": "WIN", "loss": "LOSS", "empate": "Empates", "taxa_acerto_pct": "Acerto %",
             "resultado_liquido": "Resultado", "retorno_preco_pct": "Retorno preço %", "p_valor_vs_50": "p-valor (vs 50%)",
             "p_valor_bonferroni": "p-valor Bonferroni"}
    out = t.copy()
    for col in out.columns:
        if col == "hora":
            out[col] = out[col].map(lambda h: f"{int(h):02d}h")
        elif col in ("taxa_acerto_pct", "retorno_preco_pct"):
            out[col] = out[col].map(lambda v: br(v, 2))
        elif col == "resultado_liquido":
            out[col] = out[col].map(dinheiro)
        elif col.startswith("p_valor"):
            out[col] = out[col].map(pval)
        elif col in ("operacoes", "win", "loss", "empate"):
            out[col] = out[col].map(lambda v: br(v, 0))
    return out.rename(columns=nomes)


def _comparacao(res: Resultado) -> pd.DataFrame:
    linhas = []
    for k, nome in ESTRATEGIAS.items():
        r, t = res.resumos[k], res.testes[k]
        linhas.append({"Estratégia": nome, "Operações": br(r["operacoes"], 0), "WIN": br(r["win"], 0), "LOSS": br(r["loss"], 0),
                       "Empates": br(r["empate"], 0), "Acerto %": br(r["taxa_acerto_pct"]),
                       "IC 95%": f"{br(t['ic95_inferior_pct'])} – {br(t['ic95_superior_pct'])}",
                       "p-valor vs 50%": pval(t["p_valor_vs_50_bilateral"]), "Resultado": dinheiro(r["resultado_liquido"]),
                       "Drawdown máx.": br(r["drawdown_max"])})
    return pd.DataFrame(linhas)


def conclusao(res: Resultado) -> list[str]:
    r, t, cfg = res.resumos["reversao"], res.testes["reversao"], res.cfg
    txt = []
    if t["n_sem_empates"] == 0:
        return ["Nenhuma operação: não há candles suficientes com o padrão 3 de 5."]
    if t["p_valor_vs_50_bilateral"] < 0.05:
        lado = "acima" if r["taxa_acerto_pct"] > 50 else "abaixo"
        txt.append(f"A taxa de acerto ({br(r['taxa_acerto_pct'])}%) é estatisticamente diferente de 50% "
                   f"(p = {pval(t['p_valor_vs_50_bilateral'])}), {lado} do acaso.")
    else:
        txt.append(f"A taxa de acerto ({br(r['taxa_acerto_pct'])}%) NÃO é estatisticamente diferente de 50% "
                   f"(p = {pval(t['p_valor_vs_50_bilateral'])}): com estes dados, não dá para distinguir a estratégia do acaso.")
    if cfg.breakeven is not None:
        be = cfg.breakeven * 100
        if t["ic95_inferior_pct"] > be:
            txt.append(f"Com payout de {br(cfg.payout * 100, 0)}%, é preciso acertar mais de {br(be)}% para lucrar; "
                       f"o intervalo de 95% ({br(t['ic95_inferior_pct'])}% a {br(t['ic95_superior_pct'])}%) fica todo acima disso.")
        else:
            txt.append(f"Com payout de {br(cfg.payout * 100, 0)}%, é preciso acertar mais de {br(be)}% só para empatar; "
                       f"o intervalo de 95% da taxa ({br(t['ic95_inferior_pct'])}% a {br(t['ic95_superior_pct'])}%) "
                       f"{'não chega a esse nível' if t['ic95_superior_pct'] < be else 'inclui esse nível'}, então não há evidência de lucro.")
    if t["n_sem_empates"] < 1000:
        txt.append(f"Amostra pequena ({br(t['n_sem_empates'], 0)} operações decididas): o intervalo de confiança é largo. "
                   "Teste com vários meses de dados antes de tirar conclusões.")
    txt.append("C (seguir a maioria) é o espelho exato de A nos mesmos candles: cada WIN de A é um LOSS de C e vice-versa.")
    if len(res.horarios_rank):
        txt.append("Melhores/piores horários são escolhidos depois de ver os dados; veja o p-valor com correção de Bonferroni "
                   "antes de operar só nesses horários, e confirme em um período diferente.")
    return txt


# =============================================================================================
# Gráficos
# =============================================================================================
COR = {"A": "#2a78d6", "B": "#8a8984", "C": "#eb6834", "win": "#008300", "loss": "#e34948", "empate": "#8a8984",
       "texto": "#0b0b0b", "texto2": "#52514e", "grade": "#e4e3df", "ref": "#52514e"}


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "figure.dpi": 110, "savefig.dpi": 140, "font.size": 10, "axes.edgecolor": COR["grade"], "axes.labelcolor": COR["texto2"],
        "xtick.color": COR["texto2"], "ytick.color": COR["texto2"], "axes.titleweight": "bold", "axes.titlesize": 12,
        "axes.titlelocation": "left", "axes.grid": True, "grid.color": COR["grade"], "grid.linewidth": 0.7,
        "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False, "axes.axisbelow": True,
    })
    return plt


def _salvar(fig, caminho: Path) -> Path:
    fig.savefig(caminho, bbox_inches="tight", facecolor="white")
    import matplotlib.pyplot as plt
    plt.close(fig)
    return caminho


def _fmt_moeda(ax):
    from matplotlib.ticker import FuncFormatter
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: br(v, 0)))


def graficos(res: Resultado, pasta: Path) -> dict[str, Path]:
    plt = _plt()
    from matplotlib.ticker import FuncFormatter
    cfg, a = res.cfg, res.ops["reversao"]
    sufixo = " — DADOS FICTÍCIOS" if res.exemplo else ""
    out = {}

    # 1. Evolução do saldo + drawdown
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    x = np.arange(1, len(a) + 1)
    curva = np.concatenate(([cfg.saldo_inicial], a["saldo"].to_numpy()))
    ax.plot(np.arange(0, len(a) + 1), curva, color=COR["A"], lw=1.6)
    ax.axhline(cfg.saldo_inicial, color=COR["ref"], lw=0.9, ls="--")
    ax.annotate(f"saldo inicial {br(cfg.saldo_inicial, 0)}", (0, cfg.saldo_inicial), xytext=(4, 4), textcoords="offset points", color=COR["texto2"], fontsize=8)
    ax.annotate(f"final {dinheiro(curva[-1])}", (len(a), curva[-1]), xytext=(6, 0), textcoords="offset points", va="center", color=COR["A"], fontsize=9, fontweight="bold", annotation_clip=False)
    quebra = res.resumos["reversao"]["sem_saldo_apos_operacao"]
    if quebra:
        for eixo in (ax, ax2):
            eixo.axvline(quebra, color=COR["loss"], lw=0.9, ls=":")
        ax.annotate(f"sem saldo para entrar (op. {br(quebra, 0)})", (quebra, ax.get_ylim()[1]), xytext=(4, -12), textcoords="offset points", fontsize=8, color=COR["loss"])
    ax.set_title(f"Evolução do saldo — {NOME}{sufixo}")
    ax.set_ylabel("Saldo")
    _fmt_moeda(ax)
    pico = np.maximum.accumulate(curva)
    ax2.fill_between(np.arange(0, len(a) + 1), -(pico - curva), 0, color=COR["loss"], alpha=0.35, lw=0)
    ax2.set_ylabel("Drawdown")
    ax2.set_xlabel("Nº da operação")
    _fmt_moeda(ax2)
    out["saldo"] = _salvar(fig, pasta / "grafico_saldo.png")

    # 2. WIN/LOSS
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(10, 4), gridspec_kw={"width_ratios": [1, 1.4]})
    r = res.resumos["reversao"]
    rot = ["WIN", "LOSS", "Empate"]
    vals = [r["win"], r["loss"], r["empate"]]
    barras = ax.bar(rot, vals, color=[COR["win"], COR["loss"], COR["empate"]], width=0.6)
    for b, v in zip(barras, vals):
        ax.annotate(br(v, 0), (b.get_x() + b.get_width() / 2, v), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=9)
    ax.set_title(f"Resultados{sufixo}")
    ax.set_ylabel("Operações")
    ax.grid(axis="x", visible=False)
    p = res.por_padrao
    pad = p["padrao"].astype(str).tolist()
    w, l, e = p["win"].to_numpy(), p["loss"].to_numpy(), p["empate"].to_numpy()
    tot = np.maximum(w + l + e, 1)
    ax2.barh(pad, w / tot * 100, color=COR["win"], label="WIN")
    ax2.barh(pad, l / tot * 100, left=w / tot * 100, color=COR["loss"], label="LOSS")
    ax2.barh(pad, e / tot * 100, left=(w + l) / tot * 100, color=COR["empate"], label="Empate")
    for k, (ww, ll, n) in enumerate(zip(w, l, p["operacoes"])):
        tx = ww / (ww + ll) * 100 if ww + ll else float("nan")
        ax2.annotate(f"acerto {br(tx, 1)}%  ·  {br(n, 0)} ops", (101, k), va="center", fontsize=8.5, color=COR["texto2"], annotation_clip=False)
    ax2.axvline(50, color=COR["ref"], lw=0.9, ls="--")
    ax2.set_xlim(0, 100)
    ax2.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax2.set_title("Por padrão (5 candles)")
    ax2.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3)
    ax2.grid(axis="y", visible=False)
    ax2.invert_yaxis()
    out["win_loss"] = _salvar(fig, pasta / "grafico_win_loss.png")

    # 3. Acerto por hora
    h = res.por_hora
    if len(h):
        fig, ax = plt.subplots(figsize=(10, 4))
        poucas = h["operacoes"] < cfg.min_ops_hora
        cores = np.where(poucas, "#c9c8c2", COR["A"])
        ax.bar(h["hora"], h["taxa_acerto_pct"].fillna(0), color=cores, width=0.75)
        ax.axhline(50, color=COR["ref"], lw=0.9, ls="--", label="50% (acaso)")
        if cfg.breakeven is not None:
            ax.axhline(cfg.breakeven * 100, color=COR["loss"], lw=1.1, ls=":", label=f"acerto para empatar com payout de {br(cfg.payout * 100, 0)}% ({br(cfg.breakeven * 100, 1)}%)")
        ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.32), ncol=2, fontsize=8.5)
        lo = max(0, np.nanmin(h["taxa_acerto_pct"]) - 8)
        hi = min(100, max(np.nanmax(h["taxa_acerto_pct"]), (cfg.breakeven or 0.5) * 100) + 8)
        ax.set_ylim(lo, hi)
        ax.set_xticks(h["hora"])
        ax.set_xticklabels([f"{int(v):02d}" for v in h["hora"]])
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
        ax.set_xlabel(f"Hora da entrada ({cfg.fuso_relatorio})")
        ax.set_title(f"Taxa de acerto por hora{sufixo}")
        ax.grid(axis="x", visible=False)
        if poucas.any():
            ax.annotate(f"barras cinza: menos de {cfg.min_ops_hora} operações", (1.0, 1.0), xycoords="axes fraction", xytext=(0, 4), textcoords="offset points", ha="right", fontsize=8, color=COR["texto2"])
        out["horas"] = _salvar(fig, pasta / "grafico_acerto_por_hora.png")

    # 4. Comparação A / B / C
    fig, ax = plt.subplots(figsize=(10, 4.5))
    for k, cor, rot in (("reversao", COR["A"], "A) Reversão AMS"), ("aleatoria", COR["B"], "B) Aleatória"), ("maioria", COR["C"], "C) Seguir a maioria")):
        o = res.ops[k]
        y = np.concatenate(([cfg.saldo_inicial], o["saldo"].to_numpy()))
        r_ = res.resumos[k]
        ax.plot(np.arange(len(y)), y, color=cor, lw=1.6 if k == "reversao" else 1.1,
                label=f"{rot}: acerto {br(r_['taxa_acerto_pct'], 1)}%, resultado {dinheiro(r_['resultado_liquido'])}")
    ax.axhline(cfg.saldo_inicial, color=COR["ref"], lw=0.8, ls="--")
    ax.set_title(f"Comparação do saldo: A × B × C{sufixo}")
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.36), ncol=1, fontsize=8.5)
    ax.set_xlabel("Nº da operação")
    ax.set_ylabel("Saldo")
    _fmt_moeda(ax)
    out["comparacao"] = _salvar(fig, pasta / "grafico_comparacao.png")

    # 5. Distribuição da entrada aleatória (Monte Carlo)
    if res.mc:
        fig, ax = plt.subplots(figsize=(10, 3.6))
        ax.hist(res.mc["taxas"], bins=40, color=COR["B"], alpha=0.8)
        ta = res.resumos["reversao"]["taxa_acerto_pct"]
        ax.axvline(ta, color=COR["A"], lw=2)
        ax.annotate(f"Reversão AMS {br(ta)}%", (ta, 1.0), xycoords=("data", "axes fraction"), xytext=(0, 4), textcoords="offset points",
                    ha="center", color=COR["A"], fontsize=9, fontweight="bold")
        ax.set_title(f"Taxa de acerto em {br(res.mc['simulacoes'], 0)} sorteios aleatórios nos mesmos candles{sufixo}", pad=20)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{br(v, 1)}%"))
        ax.set_ylabel("Sorteios")
        ax.grid(axis="x", visible=False)
        out["monte_carlo"] = _salvar(fig, pasta / "grafico_aleatorio.png")
    return out


# =============================================================================================
# Exportação e relatórios
# =============================================================================================
def exportar_csv(res: Resultado, pasta: Path, padrao_br: bool = True) -> list[Path]:
    sep, dec = (";", ",") if padrao_br else (",", ".")
    arquivos = []

    def salvar(df: pd.DataFrame, nome: str):
        # Formatação vetorizada: o formatador do pandas com decimal="," fica lento em arquivos de milhões de linhas.
        df = df.copy()
        for col in df.columns:
            serie = df[col]
            if isinstance(serie.dtype, pd.DatetimeTZDtype):  # horário local do relatório (fuso em --fuso)
                df[col] = serie.dt.tz_localize(None).astype(str)
            elif pd.api.types.is_float_dtype(serie.dtype):
                v = serie.to_numpy(float)
                txt = np.char.mod("%.10g", v)
                if dec == ",":
                    txt = np.char.replace(txt, ".", ",")
                df[col] = np.where(np.isnan(v), "", txt)
        caminho = pasta / nome
        df.to_csv(caminho, sep=sep, index=False, encoding="utf-8-sig")
        arquivos.append(caminho)

    salvar(res.ops["reversao"], "operacoes_reversao_ams.csv")
    enxuto = ["data_hora", "padrao", "sinal", "preco_entrada", "preco_saida", "resultado", "retorno_preco_pct", "resultado_financeiro", "saldo"]
    salvar(res.ops["aleatoria"][enxuto], "operacoes_B_aleatoria.csv")
    salvar(res.ops["maioria"][enxuto], "operacoes_C_seguir_maioria.csv")
    linhas = []
    for k, nome in ESTRATEGIAS.items():
        linhas.append({"estrategia": nome, **res.resumos[k], **res.testes[k]})
    salvar(pd.DataFrame(linhas), "resumo_comparacao.csv")
    salvar(res.por_hora, "resultado_por_hora.csv")
    salvar(res.por_padrao, "resultado_por_padrao.csv")
    salvar(res.por_padrao_sinal, "resultado_por_padrao_e_sinal.csv")
    salvar(res.por_dia, "resultado_por_dia_semana.csv")
    salvar(res.horarios_rank, "melhores_piores_horarios.csv")
    if res.mc:
        salvar(pd.DataFrame({k: [v] for k, v in res.mc.items() if not isinstance(v, np.ndarray)}), "monte_carlo_aleatorio.csv")
    return arquivos


def _cabecalho(res: Resultado) -> list[tuple[str, str]]:
    cfg, info, st = res.cfg, res.info, res.stats_sinais
    modo = (f"Opção binária: WIN paga {br(cfg.payout * 100, 0)}% do valor, LOSS perde o valor, empate devolve"
            if cfg.modo == "binaria" else f"Variação do preço entre abertura e fechamento, custo de {br(cfg.custo_pct, 3)}% por operação")
    linhas = [
        ("Arquivo", info.get("arquivo", "—")),
        ("Período", f"{info['inicio']:%d/%m/%Y %H:%M} a {info['fim']:%d/%m/%Y %H:%M} ({cfg.fuso_relatorio})"),
        ("Candles de 1 min", f"{br(info['candles'], 0)} em {br(info['dias_com_dados'], 0)} dias · alta {br(info['candles_alta_pct'], 1)}% · baixa {br(info['candles_baixa_pct'], 1)}% · doji {br(info['candles_doji_pct'], 1)}%"),
        ("Qualidade dos dados", f"{br(info.get('lacunas', 0), 0)} lacunas ({br(info.get('minutos_faltando', 0), 0)} min faltando) · "
                                f"{br(info.get('horarios_duplicados', 0), 0)} horários duplicados removidos · {br(info.get('linhas_invalidas', 0), 0)} linhas inválidas · "
                                f"{br(info.get('ohlc_inconsistente', 0), 0)} candles com máxima/mínima incoerente"),
        ("Sinais", f"{br(st['com_padrao'], 0)} candles com padrão 3 de 5 · {br(st['pulados_por_lacuna'], 0)} pulados por falta de minuto na sequência"),
        ("Cálculo do resultado", modo),
        ("Entrada", f"valor fixo de {br(cfg.valor_entrada)} por operação (sem martingale) · saldo inicial {br(cfg.saldo_inicial)}"),
    ]
    return linhas


def relatorio_texto(res: Resultado) -> str:
    cfg = res.cfg
    r, t = res.resumos["reversao"], res.testes["reversao"]
    L = []
    if res.exemplo:
        L += ["#" * 78, "#  ATENÇÃO: DADOS FICTÍCIOS GERADOS SÓ PARA DEMONSTRAR O CÓDIGO.", "#  Estes números NÃO dizem nada sobre o mercado real.", "#" * 78, ""]
    L += [f"RELATÓRIO — {NOME.upper()}", f"Gerado em {datetime.now():%d/%m/%Y %H:%M}", ""]
    L += [f"{k:<22} {v}" for k, v in _cabecalho(res)]
    L += ["", "RESUMO DA ESTRATÉGIA A (REVERSÃO AMS)", "-" * 40]
    itens = [
        ("Total de operações", br(r["operacoes"], 0)), ("WIN", br(r["win"], 0)), ("LOSS", br(r["loss"], 0)), ("Empates", br(r["empate"], 0)),
        ("Taxa de acerto", f"{br(r['taxa_acerto_pct'])}% (sem empates) · {br(r['taxa_acerto_com_empates_pct'])}% contando empates"),
        ("Resultado líquido", f"{dinheiro(r['resultado_liquido'])} (saldo final {dinheiro(r['saldo_final'])})"),
        ("Média por operação", dinheiro(r["media_por_operacao"])),
        ("Retorno de preço somado", f"{br(r['retorno_preco_total_pct'], 3)}%"),
        ("Maior sequência de WIN", br(r["maior_seq_win"], 0)), ("Maior sequência de LOSS", br(r["maior_seq_loss"], 0)),
        ("Drawdown máximo", f"{br(r['drawdown_max'])} ({br(r['drawdown_max_pct'])}% do pico)"),
    ]
    if r["sem_saldo_apos_operacao"]:
        itens.append(("Saldo insuficiente", f"a partir da operação {br(r['sem_saldo_apos_operacao'], 0)} ({r['sem_saldo_em']:%d/%m/%Y %H:%M}); "
                                            "o teste continua só para medir a regra"))
    L += [f"{k:<26} {v}" for k, v in itens]
    L += ["", "TESTES ESTATÍSTICOS (taxa de acerto × 50%)", "-" * 40]
    L += [f"{'Operações decididas':<26} {br(t['n_sem_empates'], 0)} (empates fora do teste)",
          f"{'Intervalo de 95% (Wilson)':<26} {br(t['ic95_inferior_pct'])}% a {br(t['ic95_superior_pct'])}%",
          f"{'Teste binomial exato':<26} p = {pval(t['p_valor_vs_50_bilateral'])} (bilateral) · z = {br(t['z_vs_50'], 2)}",
          f"{'Diferente de 50% a 5%?':<26} {'SIM' if t['significativo_5pct'] else 'NÃO'}"]
    if cfg.breakeven is not None:
        L += [f"{'Acerto mínimo p/ empatar':<26} {br(t['breakeven_pct'])}% (payout {br(cfg.payout * 100, 0)}%)",
              f"{'Acima do mínimo?':<26} p = {pval(t['p_valor_acima_breakeven'])} (unilateral, H1: acerto > mínimo)"]
    if res.mc:
        mc = res.mc
        L += [f"{'Entrada aleatória (MC)':<26} {br(mc['simulacoes'], 0)} sorteios nos mesmos candles: acerto médio {br(mc['taxa_media_pct'])}%, "
              f"95% entre {br(mc['taxa_p2_5_pct'])}% e {br(mc['taxa_p97_5_pct'])}%",
              f"{'':<26} A fica no percentil {br(mc['percentil_taxa_A'], 1)} · p empírico = {pval(mc['p_valor_empirico'])}"]
    L += ["", "COMPARAÇÃO A × B × C", "-" * 40, _comparacao(res).to_string(index=False)]
    L += ["", "POR PADRÃO (3x2, 4x1, 5x0)", "-" * 40, _tabela_fmt(res.por_padrao).to_string(index=False)]
    L += ["", "POR PADRÃO E SINAL", "-" * 40, _tabela_fmt(res.por_padrao_sinal).to_string(index=False)]
    L += ["", f"POR HORA DO DIA ({cfg.fuso_relatorio})", "-" * 40, _tabela_fmt(res.por_hora).to_string(index=False)]
    L += ["", f"MELHORES E PIORES HORÁRIOS (mínimo de {cfg.min_ops_hora} operações)", "-" * 40,
          _tabela_fmt(res.horarios_rank).to_string(index=False) if len(res.horarios_rank) else "Nenhum horário com operações suficientes."]
    L += ["", "POR DIA DA SEMANA", "-" * 40, _tabela_fmt(res.por_dia[res.por_dia["operacoes"] > 0]).to_string(index=False)]
    L += ["", "CONCLUSÃO", "-" * 40] + [f"• {c}" for c in conclusao(res)]
    cols = ["data_hora", "candles_analisados", "qtd_alta", "qtd_baixa", "sinal", "preco_entrada", "preco_saida", "resultado", "retorno_preco_pct", "resultado_financeiro"]
    amostra = res.ops["reversao"][cols].head(20).copy()
    amostra["data_hora"] = amostra["data_hora"].dt.strftime("%d/%m/%Y %H:%M")
    for col in ("preco_entrada", "preco_saida"):
        amostra[col] = amostra[col].map(lambda v: br(v, 5 if v < 10 else 2))
    amostra["retorno_preco_pct"] = amostra["retorno_preco_pct"].map(lambda v: br(v, 4))
    amostra["resultado_financeiro"] = amostra["resultado_financeiro"].map(dinheiro)
    L += ["", "PRIMEIRAS 20 OPERAÇÕES (todas em operacoes_reversao_ams.csv; A=alta B=baixa D=doji, do mais antigo ao mais recente)", "-" * 40,
          amostra.to_string(index=False)]
    return "\n".join(L) + "\n"


def _img(caminho: Path | None) -> str:
    if not caminho:
        return ""
    return f'<img alt="" src="data:image/png;base64,{base64.b64encode(caminho.read_bytes()).decode()}">'


def _html_tab(df: pd.DataFrame) -> str:
    return df.to_html(index=False, escape=True, classes="t", border=0)


def relatorio_html(res: Resultado, imgs: dict[str, Path]) -> str:
    cfg = res.cfg
    r, t = res.resumos["reversao"], res.testes["reversao"]
    e = html.escape
    sig = t["significativo_5pct"]
    cards = [
        ("Operações", br(r["operacoes"], 0), f"{br(r['win'], 0)} WIN · {br(r['loss'], 0)} LOSS · {br(r['empate'], 0)} empates"),
        ("Taxa de acerto", f"{br(r['taxa_acerto_pct'])}%", f"IC 95%: {br(t['ic95_inferior_pct'])}% – {br(t['ic95_superior_pct'])}%"),
        ("Resultado líquido", dinheiro(r["resultado_liquido"]), f"saldo final {dinheiro(r['saldo_final'])}"
         + (f" · sem saldo na operação {br(r['sem_saldo_apos_operacao'], 0)}" if r["sem_saldo_apos_operacao"] else "")),
        ("Drawdown máximo", br(r["drawdown_max"]), f"{br(r['drawdown_max_pct'])}% do pico"),
        ("Sequências", f"{r['maior_seq_win']} / {r['maior_seq_loss']}", "maior de WIN / maior de LOSS"),
        ("Teste vs 50%", f"p = {pval(t['p_valor_vs_50_bilateral'])}", "diferente do acaso" if sig else "não difere do acaso"),
    ]
    if cfg.breakeven is not None:
        cards.append(("Acerto para empatar", f"{br(cfg.breakeven * 100)}%", f"com payout de {br(cfg.payout * 100, 0)}%"))
    cards_html = "".join(f'<div class="card"><div class="k">{e(a)}</div><div class="v">{e(b)}</div><div class="s">{e(c)}</div></div>' for a, b, c in cards)
    cab = "".join(f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in _cabecalho(res))
    cols = ["data_hora", "candles_analisados", "qtd_alta", "qtd_baixa", "padrao", "sinal", "preco_entrada", "preco_saida", "resultado", "retorno_preco_pct", "resultado_financeiro", "saldo"]
    amostra = res.ops["reversao"][cols].head(50).copy()
    amostra["data_hora"] = amostra["data_hora"].dt.strftime("%d/%m/%Y %H:%M")
    for c_ in ("retorno_preco_pct",):
        amostra[c_] = amostra[c_].map(lambda v: br(v, 4))
    for c_ in ("resultado_financeiro", "saldo"):
        amostra[c_] = amostra[c_].map(dinheiro)
    for c_ in ("preco_entrada", "preco_saida"):
        amostra[c_] = amostra[c_].map(lambda v: br(v, 5 if v < 10 else 2))
    amostra.columns = ["Data/hora", "5 candles (antigo→recente)", "Altas", "Baixas", "Padrão", "Sinal", "Entrada", "Saída", "Resultado", "Retorno preço %", "Resultado", "Saldo"]
    mc = ""
    if res.mc:
        m = res.mc
        mc = (f"<p>Em {br(m['simulacoes'], 0)} sorteios de direção nos mesmos candles, o acerto médio foi {br(m['taxa_media_pct'])}% "
              f"(95% dos sorteios entre {br(m['taxa_p2_5_pct'])}% e {br(m['taxa_p97_5_pct'])}%). A Reversão AMS ficou no percentil "
              f"{br(m['percentil_taxa_A'], 1)}; p-valor empírico = {pval(m['p_valor_empirico'])}.</p>{_img(imgs.get('monte_carlo'))}")
    aviso = ('<div class="aviso"><strong>DADOS FICTÍCIOS.</strong> Este relatório foi gerado com candles inventados só para '
             'demonstrar o código. Os números não dizem nada sobre o mercado real. Rode com o seu CSV para o teste de verdade.</div>') if res.exemplo else ""
    rank = _html_tab(_tabela_fmt(res.horarios_rank)) if len(res.horarios_rank) else f"<p>Nenhum horário com pelo menos {cfg.min_ops_hora} operações.</p>"
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Relatório {e(NOME)}</title>
<style>
:root {{ --bg:#fcfcfb; --fg:#0b0b0b; --fg2:#52514e; --line:#e4e3df; --card:#ffffff; --a:#2a78d6; --warn:#fff4e5; --warnb:#eda100; }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
main {{ max-width:1080px; margin:0 auto; padding:24px 16px 64px; }}
h1 {{ font-size:26px; margin:0 0 4px }} h2 {{ font-size:18px; margin:36px 0 10px; padding-top:8px; border-top:1px solid var(--line) }}
.sub {{ color:var(--fg2); margin:0 0 18px }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:10px; margin:16px 0 }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px }}
.card .k {{ color:var(--fg2); font-size:12px; text-transform:uppercase; letter-spacing:.04em }}
.card .v {{ font-size:22px; font-weight:700; font-variant-numeric:tabular-nums; margin:2px 0 }}
.card .s {{ color:var(--fg2); font-size:12.5px }}
.aviso {{ background:var(--warn); border-left:4px solid var(--warnb); padding:12px 14px; border-radius:6px; margin:12px 0 }}
.wrap {{ overflow-x:auto; }}
table.t, table.cab {{ border-collapse:collapse; font-size:13.5px; font-variant-numeric:tabular-nums; width:100% }}
table.t th, table.t td {{ padding:6px 10px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap }}
table.t th:first-child, table.t td:first-child {{ text-align:left }}
table.t th {{ color:var(--fg2); font-weight:600; background:#f4f3f0 }}
table.cab th {{ text-align:left; color:var(--fg2); font-weight:600; padding:4px 12px 4px 0; vertical-align:top; white-space:nowrap }}
table.cab td {{ padding:4px 0; overflow-wrap:anywhere }}
@media (max-width:640px) {{ table.cab, table.cab tbody, table.cab tr, table.cab th, table.cab td {{ display:block; width:100% }} table.cab td {{ padding:0 0 8px }} }}
img {{ max-width:100%; height:auto; display:block; margin:10px 0; border:1px solid var(--line); border-radius:8px; background:#fff }}
ul.conc li {{ margin:6px 0 }}
.nota {{ color:var(--fg2); font-size:13px }}
</style></head><body><main>
<h1>Relatório — {e(NOME)}</h1>
<p class="sub">Reversão após 3, 4 ou 5 candles na mesma direção entre os 5 últimos candles fechados de 1 minuto. Gerado em {datetime.now():%d/%m/%Y %H:%M}.</p>
{aviso}
<div class="wrap"><table class="cab">{cab}</table></div>
<div class="cards">{cards_html}</div>
<h2>Conclusão</h2><ul class="conc">{''.join(f'<li>{e(c)}</li>' for c in conclusao(res))}</ul>
<h2>Evolução do saldo</h2>{_img(imgs.get('saldo'))}
<h2>WIN e LOSS</h2>{_img(imgs.get('win_loss'))}
<h2>Por padrão: 3x2, 4x1 e 5x0</h2>
<p class="nota">Padrão = quantos dos 5 candles estavam na direção da maioria. Com dojis, "3x2" inclui casos como 3 altas, 1 baixa e 1 doji.</p>
<div class="wrap">{_html_tab(_tabela_fmt(res.por_padrao))}</div>
<h3>Por padrão e sinal</h3><div class="wrap">{_html_tab(_tabela_fmt(res.por_padrao_sinal))}</div>
<h2>Comparação: A × B × C</h2>
<div class="wrap">{_html_tab(_comparacao(res))}</div>
<p class="nota">B sorteia CALL ou PUT nos mesmos candles em que A entra (semente {cfg.semente}). C entra a favor da maioria: é o espelho de A.</p>
{_img(imgs.get('comparacao'))}
<h2>Entrada aleatória: {br(res.mc.get('simulacoes', 0), 0)} sorteios</h2>{mc}
<h2>Resultado por hora do dia</h2>{_img(imgs.get('horas'))}
<div class="wrap">{_html_tab(_tabela_fmt(res.por_hora))}</div>
<h3>Melhores e piores horários (mínimo de {cfg.min_ops_hora} operações)</h3>
<div class="wrap">{rank}</div>
<p class="nota">Escolher horários depois de ver o resultado infla o acerto. O p-valor de Bonferroni corrige para o número de horários testados; confirme em outro período antes de filtrar.</p>
<h2>Resultado por dia da semana</h2>
<div class="wrap">{_html_tab(_tabela_fmt(res.por_dia[res.por_dia['operacoes'] > 0]))}</div>
<h2>Primeiras 50 operações</h2>
<p class="nota">A = alta, B = baixa, D = doji, do candle mais antigo ao mais recente. Todas as operações, com abertura e fechamento de cada um dos 5 candles, estão em <code>operacoes_reversao_ams.csv</code>.</p>
<div class="wrap">{_html_tab(amostra)}</div>
</main></body></html>"""


# =============================================================================================
# Dataset fictício de exemplo
# =============================================================================================
def gerar_exemplo_ficticio(caminho: Path, dias: int = 3, semente: int = 7) -> Path:
    """Cria candles INVENTADOS (passeio aleatório) só para demonstrar o código. Não são dados de mercado."""
    rng = np.random.default_rng(semente)
    n = dias * 1440
    inicio = pd.Timestamp("2025-01-06 00:00", tz="UTC")  # datas fictícias
    ts = inicio + pd.to_timedelta(np.arange(n), unit="min")
    tick = 0.5
    preco = 5000.0
    linhas = []
    for t in ts:
        abertura = preco
        passos = rng.normal(0, 2.2, 4).cumsum()
        fechamento = round((abertura + passos[-1]) / tick) * tick
        caminho_px = np.concatenate(([abertura], abertura + passos[:-1], [fechamento]))
        maxima = round(max(caminho_px.max(), abertura, fechamento) / tick) * tick + tick * rng.integers(0, 3)
        minima = round(min(caminho_px.min(), abertura, fechamento) / tick) * tick - tick * rng.integers(0, 3)
        linhas.append((t.strftime("%Y-%m-%d %H:%M:%S"), abertura, maxima, minima, fechamento, int(rng.integers(50, 900))))
        preco = fechamento
    df = pd.DataFrame(linhas, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = df.drop(index=rng.choice(np.arange(100, n - 100), size=4, replace=False))  # algumas lacunas para mostrar o tratamento
    df.to_csv(caminho, index=False)
    return caminho


# =============================================================================================
# Linha de comando
# =============================================================================================
def executar(caminho_csv: str | None, cfg: Config, pasta_saida: str = "resultados", csv_br: bool = True, com_graficos: bool = True) -> Resultado:
    pasta = Path(pasta_saida)
    pasta.mkdir(parents=True, exist_ok=True)
    exemplo = caminho_csv is None
    if exemplo:
        caminho_csv = gerar_exemplo_ficticio(pasta / "EXEMPLO_FICTICIO_candles_1m.csv")
        print("Nenhum arquivo informado: usando um EXEMPLO FICTÍCIO (candles inventados) só para demonstrar o código.")
        print(f"Dataset fictício salvo em {caminho_csv}\n")
    df, info = carregar_csv(caminho_csv, cfg)
    if exemplo:
        info["arquivo"] = f"{Path(caminho_csv).name} (DADOS FICTÍCIOS)"
    res = backtest(df, cfg, info, exemplo=exemplo)
    imgs = graficos(res, pasta) if com_graficos else {}
    arquivos = exportar_csv(res, pasta, csv_br)
    txt = relatorio_texto(res)
    (pasta / "relatorio.txt").write_text(txt, encoding="utf-8")
    (pasta / "relatorio.html").write_text(relatorio_html(res, imgs), encoding="utf-8")
    print(txt)
    print(f"Arquivos gerados em {pasta.resolve()}:")
    for p in [pasta / "relatorio.html", pasta / "relatorio.txt", *imgs.values(), *arquivos]:
        print(f"  - {p.name}")
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=f"Backtest da estratégia {NOME} (candles de 1 minuto).",
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("csv", nargs="?", help="CSV com timestamp, open, high, low, close, volume. Sem arquivo, roda um exemplo fictício.")
    ap.add_argument("--saida", default="resultados", help="pasta dos relatórios, gráficos e CSVs")
    ap.add_argument("--modo", choices=["binaria", "preco"], default="binaria", help="binaria: payout fixo; preco: variação do preço")
    ap.add_argument("--payout", type=float, default=0.85, help="lucro do WIN na binária (0.85 ou 85 = 85%%)")
    ap.add_argument("--valor", type=float, default=10.0, help="valor fixo de cada entrada")
    ap.add_argument("--saldo", type=float, default=1000.0, help="saldo inicial")
    ap.add_argument("--custo", type=float, default=0.0, help="modo preço: custo por operação em %% do valor")
    ap.add_argument("--fuso-dados", default="UTC", help="fuso dos horários do CSV, se vierem sem fuso (ex.: America/Sao_Paulo)")
    ap.add_argument("--fuso", default="America/Sao_Paulo", help="fuso usado nas horas e dias do relatório")
    ap.add_argument("--permitir-lacunas", action="store_true", help="opera mesmo se faltar algum minuto entre os 6 candles")
    ap.add_argument("--simulacoes", type=int, default=1000, help="sorteios da entrada aleatória (Monte Carlo)")
    ap.add_argument("--semente", type=int, default=42, help="semente do sorteio (resultado reproduzível)")
    ap.add_argument("--min-ops-hora", type=int, default=30, help="mínimo de operações para um horário entrar no ranking")
    ap.add_argument("--csv-padrao", action="store_true", help="exporta CSV com vírgula e ponto decimal (padrão: ';' e ',' para Excel em português)")
    ap.add_argument("--sem-graficos", action="store_true")
    a = ap.parse_args(argv)
    payout = a.payout / 100 if a.payout > 1.5 else a.payout
    cfg = Config(modo=a.modo, payout=payout, valor_entrada=a.valor, saldo_inicial=a.saldo, custo_pct=a.custo,
                 fuso_dados=a.fuso_dados, fuso_relatorio=a.fuso, exigir_sequencia=not a.permitir_lacunas,
                 semente=a.semente, simulacoes=a.simulacoes, min_ops_hora=a.min_ops_hora)
    try:
        executar(a.csv, cfg, a.saida, csv_br=not a.csv_padrao, com_graficos=not a.sem_graficos)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
