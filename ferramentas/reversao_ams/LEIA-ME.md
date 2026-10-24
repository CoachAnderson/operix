# Reversão AMS — backtester

Testa a estratégia de reversão em candles de 1 minuto:

- olha os 5 candles anteriores **já fechados**;
- 3, 4 ou 5 de alta → **PUT** na abertura do 6º candle;
- 3, 4 ou 5 de baixa → **CALL** na abertura do 6º candle;
- doji (fechamento = abertura) não conta;
- a operação dura exatamente 1 candle: entra na abertura e sai no fechamento do 6º;
- WIN, LOSS ou EMPATE (fechamento = abertura do 6º), sem martingale.

## Instalação

Python 3.10 ou mais novo.

```
pip install -r requirements.txt
```

## Uso

```
python reversao_ams.py meus_candles.csv
```

Sem arquivo (`python reversao_ams.py`), o programa cria um **dataset fictício** (passeio aleatório, marcado como
FICTÍCIO no nome do arquivo e no relatório) só para mostrar o funcionamento. Esses números não dizem nada sobre o mercado.

### Formato do CSV

Colunas `timestamp, open, high, low, close, volume`. Também aceita:

- nomes em português (`data`, `hora`, `abertura`, `maxima`, `minima`, `fechamento`, `volume`);
- a exportação do MetaTrader 5 (`<DATE> <TIME> <OPEN> <HIGH> <LOW> <CLOSE> <TICKVOL> ...`, separada por tab);
- a exportação da Binance (`open_time` em milissegundos);
- separador `,` `;` ou tab, e números com vírgula decimal (`1.234,56`).

O `timestamp` é o horário de **abertura** do candle. Se vier sem fuso, informe qual é com `--fuso-dados`
(padrão UTC). As horas e dias do relatório usam `--fuso` (padrão America/Sao_Paulo).

### Opções principais

| Opção | Padrão | O que faz |
|---|---|---|
| `--payout` | 0.85 | lucro do WIN na binária (0.85 ou 85 = 85%) |
| `--valor` | 10 | valor fixo de cada entrada |
| `--saldo` | 1000 | saldo inicial |
| `--modo` | binaria | `preco` usa a variação do preço em vez do payout (com `--custo` em %) |
| `--fuso-dados` | UTC | fuso dos horários do CSV |
| `--fuso` | America/Sao_Paulo | fuso das horas e dias do relatório |
| `--permitir-lacunas` | desligado | por padrão, sinais com minuto faltando entre os 6 candles são pulados |
| `--simulacoes` | 1000 | sorteios da entrada aleatória |
| `--min-ops-hora` | 30 | mínimo de operações para um horário entrar no ranking |
| `--csv-padrao` | desligado | exporta com `,` e ponto decimal (o padrão é `;` e vírgula, para o Excel em português) |

## O que é gerado (pasta `resultados`)

- `relatorio.html`: relatório completo com gráficos (abre no navegador);
- `relatorio.txt`: o mesmo relatório em texto;
- `grafico_saldo.png`: evolução do saldo e drawdown;
- `grafico_win_loss.png`: WIN/LOSS/empates e por padrão 3x2, 4x1, 5x0;
- `grafico_acerto_por_hora.png`: taxa de acerto por hora, com as linhas de 50% e do acerto que empata com o payout;
- `grafico_comparacao.png`: saldo de A, B e C;
- `grafico_aleatorio.png`: distribuição do acerto em 1.000 sorteios aleatórios;
- `operacoes_reversao_ams.csv`: cada operação com data/hora, os 5 candles (sequência A/B/D e abertura/fechamento de cada um),
  quantidades de alta e baixa, padrão, sinal, entrada, saída, resultado, retorno e saldo;
- `operacoes_B_aleatoria.csv`, `operacoes_C_seguir_maioria.csv`;
- `resumo_comparacao.csv`, `resultado_por_hora.csv`, `resultado_por_padrao.csv`, `resultado_por_padrao_e_sinal.csv`,
  `resultado_por_dia_semana.csv`, `melhores_piores_horarios.csv`, `monte_carlo_aleatorio.csv`.

## Como ler os números

- **Taxa de acerto** = WIN / (WIN + LOSS). Empates ficam fora (o relatório mostra também a taxa contando empates).
- **Teste binomial exato**: verifica se o acerto é diferente de 50%. p < 0,05 → diferença estatisticamente significativa.
- **Intervalo de 95% (Wilson)**: faixa onde o acerto verdadeiro provavelmente está.
- **Acerto para empatar**: com payout de 85%, cada LOSS custa 1 e cada WIN rende 0,85, então é preciso acertar
  1 / 1,85 = **54,05%** só para não perder. O relatório testa também se o acerto passa desse nível.
- **B — entrada aleatória**: sorteia CALL/PUT nos **mesmos candles** em que A entra; o Monte Carlo repete o sorteio
  1.000 vezes e mostra onde A fica nessa distribuição.
- **C — seguir a maioria** é o espelho de A: nos mesmos candles, cada WIN de A é um LOSS de C.
- **Sequências**: empates não aumentam nem interrompem uma sequência de WIN ou LOSS.
- **Drawdown máximo**: maior queda do saldo desde um pico. O saldo pode ficar negativo porque o teste continua para medir a
  regra; o relatório marca a operação a partir da qual não haveria saldo para entrar.
- **Melhores e piores horários**: são escolhidos depois de ver os dados, então sempre aparecem horários "bons" por acaso
  (o exemplo fictício mostra isso). Use o p-valor de Bonferroni e confirme em outro período antes de filtrar horários.

## Sem look-ahead

O sinal do candle *i* é calculado só com as linhas *i-5* a *i-1*. A abertura do candle *i* (preço de entrada) já é conhecida
no instante da entrada; o fechamento do candle *i* só é usado para apurar o resultado. O teste `test_sem_look_ahead`
altera os dados futuros e confere que nenhum sinal anterior muda.

## Testes

```
python -m pytest -q
```

## Uso como biblioteca

```python
import reversao_ams as ams
cfg = ams.Config(payout=0.87, valor_entrada=5)
df, info = ams.carregar_csv("meus_candles.csv", cfg)
res = ams.backtest(df, cfg, info)
print(res.resumos["reversao"], res.testes["reversao"])
```
