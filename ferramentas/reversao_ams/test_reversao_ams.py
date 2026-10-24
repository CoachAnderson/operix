"""Testes da Reversão AMS.  Rodar com:  python -m pytest -q"""
import numpy as np
import pandas as pd
import pytest

import reversao_ams as ams

CFG = ams.Config(fuso_relatorio="UTC", simulacoes=200)


def candles(pares, inicio="2025-03-03 13:00", passo_min=None):
    """pares = [(abertura, fechamento), ...] em minutos seguidos (ou nos minutos de passo_min)."""
    ts = pd.Timestamp(inicio, tz="UTC") + pd.to_timedelta(passo_min if passo_min is not None else range(len(pares)), unit="min")
    o = np.array([p[0] for p in pares], float)
    c = np.array([p[1] for p in pares], float)
    return pd.DataFrame({"ts": ts, "open": o, "high": np.maximum(o, c) + 1, "low": np.minimum(o, c) - 1, "close": c, "volume": 1.0})


A, B, D = (10, 11), (11, 10), (10, 10)  # alta, baixa, doji


def ops_de(df, regra="reversao", cfg=CFG):
    return ams.gerar_operacoes(ams.preparar(df, cfg), cfg, regra, detalhado=True)[0]


def test_3_altas_gera_put_na_abertura_do_6o():
    df = candles([A, B, A, B, A, (20, 18)])
    o = ops_de(df)
    assert len(o) == 1
    op = o.iloc[0]
    assert op["sinal"] == "PUT" and op["qtd_alta"] == 3 and op["qtd_baixa"] == 2 and op["padrao"] == "3x2"
    assert op["data_hora"] == df["ts"].iloc[5]
    assert op["preco_entrada"] == 20 and op["preco_saida"] == 18 and op["resultado"] == "WIN"
    assert op["candles_analisados"] == "A B A B A"


def test_baixas_geram_call_e_padroes():
    o = ops_de(candles([B, B, B, B, B, (5, 6)]))
    assert o.iloc[0]["sinal"] == "CALL" and o.iloc[0]["padrao"] == "5x0" and o.iloc[0]["resultado"] == "WIN"
    o = ops_de(candles([B, A, B, B, B, (5, 4)]))
    assert o.iloc[0]["padrao"] == "4x1" and o.iloc[0]["resultado"] == "LOSS"


def test_doji_nao_conta():
    assert len(ops_de(candles([A, A, B, B, D, (5, 6)]))) == 0      # 2 x 2 + doji: sem sinal
    o = ops_de(candles([A, D, A, B, A, (5, 6)]))                   # 3 altas, 1 baixa, 1 doji
    assert o.iloc[0]["sinal"] == "PUT" and o.iloc[0]["qtd_doji"] == 1 and o.iloc[0]["padrao"] == "3x2"
    assert o.iloc[0]["resultado"] == "LOSS"


def test_empate():
    o = ops_de(candles([A, A, A, B, B, (7, 7)]))
    assert o.iloc[0]["resultado"] == "EMPATE" and o.iloc[0]["resultado_financeiro"] == 0
    assert o.iloc[0]["retorno_preco_pct"] == 0 and str(o.iloc[0]["retorno_preco_pct"]) == "0.0"


def test_cada_candle_novo_e_avaliado():
    df = candles([A, A, A, B, B, B, B, (1, 2)])
    o = ops_de(df)
    # candles 6, 7 e 8 (índices 5, 6, 7) são entradas: janelas AAABB, AABBB, ABBBB
    assert list(o["sinal"]) == ["PUT", "CALL", "CALL"]
    assert list(o["data_hora"]) == list(df["ts"].iloc[5:8])


def test_financeiro_binaria_e_preco():
    cfg = ams.Config(fuso_relatorio="UTC", payout=0.8, valor_entrada=10, saldo_inicial=100)
    o = ops_de(candles([B, B, B, B, B, (100, 101), (100, 99)]), cfg=cfg)
    assert list(o["resultado"]) == ["WIN", "LOSS"]
    assert list(o["resultado_financeiro"]) == [8.0, -10.0]
    assert list(o["saldo"]) == [108.0, 98.0]
    cfgp = ams.Config(fuso_relatorio="UTC", modo="preco", valor_entrada=1000, custo_pct=0.01)
    o = ops_de(candles([B, B, B, B, B, (100, 101)]), cfg=cfgp)
    assert o.iloc[0]["retorno_preco_pct"] == pytest.approx(1.0)
    assert o.iloc[0]["resultado_financeiro"] == pytest.approx(10 - 0.1)


def test_lacuna_na_sequencia_nao_opera():
    df = candles([A, A, A, B, B, (5, 4)], passo_min=[0, 1, 2, 3, 5, 6])  # falta o minuto 4
    assert len(ops_de(df)) == 0
    cfg = ams.Config(fuso_relatorio="UTC", exigir_sequencia=False)
    assert len(ops_de(df, cfg=cfg)) == 1


def test_sem_look_ahead():
    """Mudar qualquer coisa a partir do candle k não pode mudar sinais de entradas até k."""
    rng = np.random.default_rng(1)
    n = 600
    o = 100 + rng.normal(0, 1, n).cumsum().round(1)
    c = (o + rng.normal(0, 0.3, n)).round(1)
    df = pd.DataFrame({"ts": pd.Timestamp("2025-03-03", tz="UTC") + pd.to_timedelta(range(n), unit="min"),
                       "open": o, "high": np.maximum(o, c), "low": np.minimum(o, c), "close": c, "volume": 1.0})
    base = ops_de(df).set_index("data_hora")
    for k in (50, 300, 599):
        mexido = df.copy()
        mexido.loc[k:, "close"] = mexido.loc[k:, "close"] + rng.normal(0, 5, n - k)   # muda o futuro (inclui o fechamento do 6º)
        mexido.loc[k + 1:, "open"] = mexido.loc[k + 1:, "open"] + 3
        novo = ops_de(mexido).set_index("data_hora")
        corte = df["ts"].iloc[k]
        a = base[base.index <= corte][["sinal", "qtd_alta", "qtd_baixa", "preco_entrada"]]
        b = novo[novo.index <= corte][["sinal", "qtd_alta", "qtd_baixa", "preco_entrada"]]
        pd.testing.assert_frame_equal(a, b)


def test_seguir_maioria_e_espelho():
    rng = np.random.default_rng(3)
    pares = [(10, 10 + int(v)) for v in rng.integers(-1, 2, 400)]
    df = candles(pares)
    a, c = ops_de(df), ops_de(df, "maioria")
    assert len(a) == len(c)
    assert ((a["sinal"] == "CALL") == (c["sinal"] == "PUT")).all()
    assert (a["resultado"] == "WIN").sum() == (c["resultado"] == "LOSS").sum()
    assert (a["resultado"] == "EMPATE").sum() == (c["resultado"] == "EMPATE").sum()


def test_sequencias_e_drawdown():
    r = pd.Series(["WIN", "WIN", "EMPATE", "WIN", "LOSS", "LOSS", "WIN", "LOSS", "LOSS", "LOSS"])
    assert ams.maior_sequencia(r, "WIN") == 3   # empate não interrompe
    assert ams.maior_sequencia(r, "LOSS") == 3
    dd, pct = ams.drawdown(np.array([110, 120, 90, 100, 80, 130]), 100)
    assert dd == 40 and pct == pytest.approx(40 / 120 * 100)


def test_estatistica():
    t = ams.testes_estatisticos({"win": 60, "loss": 40, "taxa_acerto_pct": 60.0}, ams.Config())
    assert t["p_valor_vs_50_bilateral"] == pytest.approx(0.05689, abs=1e-4)   # binomial exato
    assert t["ic95_inferior_pct"] == pytest.approx(50.2, abs=0.1) and t["ic95_superior_pct"] == pytest.approx(69.1, abs=0.1)
    assert t["breakeven_pct"] == pytest.approx(100 / 1.85)


def test_csv_mt5_e_formato_brasileiro(tmp_path):
    mt5 = tmp_path / "mt5.csv"
    mt5.write_text("<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
                   + "".join(f"2025.03.03\t09:{m:02d}:00\t10{m}.5\t10{m}.9\t10{m}.1\t10{m}.7\t12\t0\t1\n" for m in range(8)))
    df, info = ams.carregar_csv(mt5, ams.Config(fuso_dados="America/Sao_Paulo"))
    assert len(df) == 8 and df["ts"].iloc[0] == pd.Timestamp("2025-03-03 12:00", tz="UTC")
    assert df["open"].iloc[1] == 101.5 and df["volume"].iloc[0] == 12

    br = tmp_path / "br.csv"
    br.write_text("Data;Hora;Abertura;Máxima;Mínima;Fechamento;Volume\n"
                  + "".join(f"04/03/2025;10:{m:02d};1.234,{m}0;1.235,00;1.233,00;1.234,{m}5;7\n" for m in range(8)))
    df, _ = ams.carregar_csv(br, ams.Config())
    assert df["open"].iloc[2] == pytest.approx(1234.2) and df["ts"].iloc[0] == pd.Timestamp("2025-03-04 10:00", tz="UTC")

    ep = tmp_path / "epoch.csv"
    ep.write_text("open_time,open,high,low,close,volume\n" + "".join(f"{1741000000000 + 60000 * m},1,2,0.5,1.5,3\n" for m in range(8)))
    df, _ = ams.carregar_csv(ep, ams.Config())
    assert df["ts"].diff().dropna().dt.total_seconds().eq(60).all()


def test_recusa_candles_que_nao_sao_de_1_minuto(tmp_path):
    f = tmp_path / "5m.csv"
    f.write_text("timestamp,open,high,low,close,volume\n" + "".join(f"2025-03-03 10:{m:02d}:00,1,2,0.5,1.5,3\n" for m in range(0, 50, 5)))
    with pytest.raises(ValueError, match="1 minuto"):
        ams.carregar_csv(f, ams.Config())


def test_execucao_completa(tmp_path):
    res = ams.executar(None, ams.Config(simulacoes=100), tmp_path / "saida")
    pasta = tmp_path / "saida"
    for nome in ("relatorio.html", "relatorio.txt", "grafico_saldo.png", "grafico_win_loss.png", "grafico_acerto_por_hora.png",
                 "grafico_comparacao.png", "operacoes_reversao_ams.csv", "melhores_piores_horarios.csv", "resumo_comparacao.csv"):
        assert (pasta / nome).exists(), nome
    assert "DADOS FICTÍCIOS" in (pasta / "relatorio.html").read_text(encoding="utf-8")
    exp = pd.read_csv(pasta / "operacoes_reversao_ams.csv", sep=";", decimal=",")
    assert len(exp) == res.resumos["reversao"]["operacoes"]
    r = res.resumos["reversao"]
    assert r["win"] + r["loss"] + r["empate"] == r["operacoes"]
    assert exp["resultado_financeiro"].sum() == pytest.approx(r["resultado_liquido"])
