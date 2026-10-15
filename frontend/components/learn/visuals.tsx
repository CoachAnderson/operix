"use client";

import { useMemo, useState } from "react";
import { MiniChart } from "./MiniChart";
import { REGIME_LABEL, breakoutSeries, hourly, mixed, regime, short, type RegimeName } from "@/lib/learn/datasets";
import { aggregate, breakout, buyAndHold, ema, emaCross, mulberry32, num, pct, rsi, rsiReversion, sma, type Candle, type Result } from "@/lib/learn/market";

const A = "var(--learn-a)";
const B = "var(--learn-b)";
const C = "var(--learn-c)";

// ---------------- peças comuns ----------------
function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: { id: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="lv-seg" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.id} type="button" role="radio" aria-checked={value === o.id} className={value === o.id ? "on" : ""} onClick={() => onChange(o.id)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

function Slider({ label, value, min, max, step = 1, onChange, format }: { label: string; value: number; min: number; max: number; step?: number; onChange: (v: number) => void; format?: (v: number) => string }) {
  return (
    <label className="lv-slider">
      <span>
        {label} <strong>{format ? format(value) : value}</strong>
      </span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "gain" | "loss" | "" }) {
  return (
    <div className="lv-stat">
      <dt>{label}</dt>
      <dd className={tone ?? ""}>{value}</dd>
    </div>
  );
}

const tone = (v: number) => (v > 0 ? "gain" : v < 0 ? "loss" : "");

function Frame({ children, note = true }: { children: React.ReactNode; note?: boolean }) {
  return (
    <div className="lv">
      {children}
      {note && <p className="lv-note">Dados fictícios, gerados para a aula. Não são cotações reais.</p>}
    </div>
  );
}

function tradeMarks(r: Result) {
  return {
    markers: r.trades.flatMap((t) => [
      { i: t.entry, kind: "buy" as const },
      { i: t.exit, kind: "sell" as const },
    ]),
    spans: r.trades.map((t) => ({ from: t.entry, to: t.exit, tone: t.pct > 0 ? ("gain" as const) : ("loss" as const) })),
  };
}

function ResultStats({ r, candles }: { r: Result; candles: Candle[] }) {
  const bh = buyAndHold(candles);
  return (
    <dl className="lv-stats">
      <Stat label="Operações" value={String(r.trades.length)} />
      <Stat label="Acertos" value={r.trades.length ? `${r.wins} de ${r.trades.length}` : "—"} />
      <Stat label="Resultado da estratégia" value={pct(r.totalPct)} tone={tone(r.totalPct)} />
      <Stat label="Comprar e segurar" value={pct(bh)} tone={tone(bh)} />
    </dl>
  );
}

// ---------------- 1. Comprado e vendido ----------------
export function LongShortDemo() {
  const [price, setPrice] = useState(108);
  const [lev, setLev] = useState<"1" | "5" | "10">("1");
  const move = (price / 100 - 1) * 100;
  const L = Number(lev);
  const long = move * L;
  const shortR = -move * L;
  const fmt = (v: number) => (v <= -100 ? "−100% (perdeu toda a margem)" : pct(v));
  return (
    <Frame note={false}>
      <p className="lv-q">Você entrou em 100. Arraste para mudar o preço de agora:</p>
      <Slider label="Preço agora" value={price} min={80} max={120} onChange={setPrice} format={(v) => num(v, 0)} />
      <div className="lv-scale" aria-hidden="true">
        <span className="lv-scale-entry" style={{ left: "50%" }}>
          entrada 100
        </span>
        <span className="lv-scale-now" style={{ left: `${((price - 80) / 40) * 100}%` }} />
      </div>
      <Segmented
        label="Alavancagem"
        value={lev}
        onChange={setLev}
        options={[
          { id: "1", label: "Sem alavancagem" },
          { id: "5", label: "5x" },
          { id: "10", label: "10x" },
        ]}
      />
      <dl className="lv-stats lv-stats-2">
        <Stat label="Comprado (aposta na alta)" value={fmt(long)} tone={tone(long)} />
        <Stat label="Vendido (aposta na queda)" value={fmt(shortR)} tone={tone(shortR)} />
      </dl>
      <p className="lv-explain">
        O preço andou {pct(move)}.{" "}
        {L > 1
          ? `Com alavancagem de ${L}x, o resultado sobre o seu dinheiro é ${L} vezes maior, para o bem e para o mal.`
          : "Sem alavancagem, o resultado é igual ao movimento do preço."}
      </p>
    </Frame>
  );
}

// ---------------- 2. Custo das operações ----------------
export function CostDemo() {
  const [ops, setOps] = useState(6);
  const [cost, setCost] = useState(0.2);
  const monthly = ops * cost * 22;
  return (
    <Frame note={false}>
      <Slider label="Operações por dia" value={ops} min={1} max={30} onChange={setOps} />
      <Slider label="Custo de cada operação (entrada + saída)" value={cost} min={0.04} max={0.4} step={0.02} onChange={setCost} format={(v) => `${num(v, 2)}%`} />
      <dl className="lv-stats lv-stats-2">
        <Stat label="Custo em um mês (22 dias)" value={`${num(monthly, 1)}% do capital`} tone="loss" />
        <Stat label="Para empatar, o robô precisa render" value={`${num(monthly, 1)}% ao mês`} />
      </dl>
      <p className="lv-explain">Cada operação paga taxa e spread, ganhando ou perdendo. Operar muito multiplica esse custo: ele é a primeira conta que a estratégia precisa vencer.</p>
    </Frame>
  );
}

// ---------------- 3. Anatomia do candle ----------------
const READ: { id: string; label: string; c: Candle; text: string }[] = [
  { id: "forte-alta", label: "Alta forte", c: { o: 30, c: 88, h: 92, l: 26 }, text: "Corpo grande e verde, quase sem pavio: os compradores dominaram o período do começo ao fim." },
  { id: "forte-baixa", label: "Queda forte", c: { o: 86, c: 28, h: 90, l: 24 }, text: "Corpo grande e vermelho: os vendedores dominaram o período inteiro." },
  { id: "rejeicao", label: "Pavio longo embaixo", c: { o: 74, c: 82, h: 86, l: 20 }, text: "O preço caiu bastante, mas voltou e fechou perto da máxima: a queda foi rejeitada pelos compradores." },
  { id: "doji", label: "Indecisão", c: { o: 56, c: 57, h: 84, l: 28 }, text: "Abriu e fechou quase no mesmo preço, com pavios dos dois lados: ninguém venceu. Sozinho, não indica direção." },
];

export function CandleAnatomy() {
  const [kind, setKind] = useState<"alta" | "baixa">("alta");
  const [read, setRead] = useState(READ[0].id);
  const up = kind === "alta";
  const c = up ? { o: 40, c: 80, h: 92, l: 24 } : { o: 80, c: 40, h: 92, l: 24 };
  const Y = (v: number) => 196 - v * 2;
  const r = READ.find((x) => x.id === read)!;
  return (
    <Frame note={false}>
      <Segmented
        label="Tipo de candle"
        value={kind}
        onChange={setKind}
        options={[
          { id: "alta", label: "Candle de alta" },
          { id: "baixa", label: "Candle de baixa" },
        ]}
      />
      <svg viewBox="0 0 400 200" className="lv-anatomy" role="img" aria-label={`Candle de ${kind} com abertura, fechamento, máxima e mínima indicadas`}>
        <g className={up ? "mc-up" : "mc-down"}>
          <line x1={80} x2={80} y1={Y(c.h)} y2={Y(c.l)} className="mc-wick" strokeWidth={3} />
          <rect x={50} y={Y(Math.max(c.o, c.c))} width={60} height={Math.abs(Y(c.o) - Y(c.c))} rx={3} className="mc-body" />
        </g>
        {[
          { v: c.h, t: "Máxima: o preço mais alto" },
          { v: up ? c.c : c.o, t: up ? "Fechamento (o último preço)" : "Abertura (o primeiro preço)" },
          { v: up ? c.o : c.c, t: up ? "Abertura (o primeiro preço)" : "Fechamento (o último preço)" },
          { v: c.l, t: "Mínima: o preço mais baixo" },
        ].map((a) => (
          <g key={a.t}>
            <line x1={116} x2={134} y1={Y(a.v)} y2={Y(a.v)} className="lv-anno-line" />
            <text x={140} y={Y(a.v) + 4} className="lv-anno">
              {a.t}
            </text>
          </g>
        ))}
        <text x={80} y={Y((c.o + c.c) / 2) + 4} textAnchor="middle" className="lv-anno lv-anno-in">
          corpo
        </text>
      </svg>
      <p className="lv-explain">
        {up
          ? "Verde: fechou ACIMA de onde abriu. O corpo vai da abertura (embaixo) ao fechamento (em cima)."
          : "Vermelho: fechou ABAIXO de onde abriu. O corpo vai da abertura (em cima) ao fechamento (embaixo)."}{" "}
        Os traços finos são os pavios: até onde o preço foi e voltou.
      </p>
      <p className="lv-q">Agora tente ler estes candles:</p>
      <div className="lv-read">
        {READ.map((x) => {
          const y = (v: number) => 100 - v;
          const upx = x.c.c >= x.c.o;
          return (
            <button key={x.id} type="button" className={read === x.id ? "on" : ""} onClick={() => setRead(x.id)} aria-pressed={read === x.id}>
              <svg viewBox="0 0 40 100" aria-hidden="true">
                <g className={upx ? "mc-up" : "mc-down"}>
                  <line x1={20} x2={20} y1={y(x.c.h)} y2={y(x.c.l)} className="mc-wick" strokeWidth={2} />
                  <rect x={11} y={y(Math.max(x.c.o, x.c.c))} width={18} height={Math.max(2, Math.abs(x.c.o - x.c.c))} className="mc-body" />
                </g>
              </svg>
              <span>{x.label}</span>
            </button>
          );
        })}
      </div>
      <p className="lv-explain" aria-live="polite">
        {r.text}
      </p>
    </Frame>
  );
}

// ---------------- 4. Tempo gráfico ----------------
export function TimeframeDemo() {
  const [tf, setTf] = useState<"1h" | "4h" | "1d">("1h");
  const base = hourly();
  const candles = useMemo(() => (tf === "1h" ? base : aggregate(base, tf === "4h" ? 4 : 24)), [base, tf]);
  const text = {
    "1h": "240 candles de 1 hora: dá para ver cada sobe e desce, mas também muito ruído.",
    "4h": "Os mesmos 10 dias em 60 candles de 4 horas: cada candle junta 4 de 1 hora. A direção fica mais clara.",
    "1d": "Os mesmos 10 dias em 10 candles diários: só o movimento grande aparece.",
  }[tf];
  return (
    <Frame>
      <Segmented
        label="Tempo gráfico"
        value={tf}
        onChange={setTf}
        options={[
          { id: "1h", label: "1 hora" },
          { id: "4h", label: "4 horas" },
          { id: "1d", label: "Diário" },
        ]}
      />
      <MiniChart candles={candles} label={`Gráfico de 10 dias no tempo gráfico de ${tf}`} />
      <p className="lv-explain">{text}</p>
    </Frame>
  );
}

// ---------------- 5. Tendência, suporte e resistência ----------------
function pivots(c: Candle[], w = 7) {
  const pts: { i: number; price: number; up: boolean }[] = [];
  for (let i = w; i < c.length - w; i++) {
    const win = c.slice(i - w, i + w + 1);
    if (c[i].h === Math.max(...win.map((x) => x.h))) pts.push({ i, price: c[i].h, up: true });
    if (c[i].l === Math.min(...win.map((x) => x.l))) pts.push({ i, price: c[i].l, up: false });
  }
  return pts;
}

export function TrendDemo() {
  const [g, setG] = useState<RegimeName>("alta");
  const c = regime(g);
  const pts = useMemo(() => pivots(c), [c]);
  const levels = useMemo(() => {
    if (g !== "lateral") return [];
    const tops = pts.filter((p) => p.up).map((p) => p.price);
    const bots = pts.filter((p) => !p.up).map((p) => p.price);
    const avg = (a: number[]) => a.reduce((x, y) => x + y, 0) / a.length;
    return [
      { price: avg(tops), label: "Resistência: onde o preço costuma parar de subir", color: "var(--loss)" },
      { price: avg(bots), label: "Suporte: onde o preço costuma parar de cair", color: "var(--gain)" },
    ];
  }, [g, pts]);
  const text = {
    alta: "Topos e fundos cada vez mais altos: cada queda para antes da anterior. Isso é tendência de alta.",
    queda: "Topos e fundos cada vez mais baixos: cada repique para antes do anterior. Isso é tendência de queda.",
    lateral: "Topos e fundos na mesma altura: o preço vai e volta entre um piso (suporte) e um teto (resistência).",
  }[g];
  return (
    <Frame>
      <Segmented label="Tipo de mercado" value={g} onChange={setG} options={(["alta", "lateral", "queda"] as const).map((id) => ({ id, label: REGIME_LABEL[id] }))} />
      <MiniChart
        candles={c}
        label={`${REGIME_LABEL[g]} com topos e fundos marcados`}
        points={pts.map((p) => ({ ...p, label: p.up ? "T" : "F" }))}
        levels={levels}
      />
      <p className="lv-explain">
        <strong>T</strong> = topo, <strong>F</strong> = fundo. {text}
      </p>
    </Frame>
  );
}

// ---------------- 6. Médias móveis ----------------
export function MovingAverageDemo() {
  const [n, setN] = useState(10);
  const [kind, setKind] = useState<"ema" | "sma">("ema");
  const c = short();
  const closes = c.map((x) => x.c);
  const line = kind === "ema" ? ema(closes, n) : sma(closes, n);
  return (
    <Frame>
      <Slider label="Média de quantos candles" value={n} min={3} max={50} onChange={setN} />
      <Segmented
        label="Tipo de média"
        value={kind}
        onChange={setKind}
        options={[
          { id: "ema", label: "Exponencial (MME)" },
          { id: "sma", label: "Simples (MMS)" },
        ]}
      />
      <MiniChart candles={c} label={`Preço com média móvel de ${n} candles`} lines={[{ values: line, color: A, label: `Média de ${n}`, width: 2.5 }]} />
      <p className="lv-explain">
        {n <= 10
          ? "Média curta: acompanha o preço de perto e reage rápido, mas se mexe com qualquer ruído."
          : n >= 30
            ? "Média longa: linha suave que mostra só a direção principal, mas avisa a virada com atraso."
            : "Média intermediária: equilíbrio entre suavidade e velocidade."}{" "}
        A exponencial dá mais peso aos candles recentes e reage um pouco antes da simples.
      </p>
    </Frame>
  );
}

// ---------------- 7. RSI ----------------
export function RsiDemo() {
  const [n, setN] = useState(14);
  const c = regime("lateral");
  const r = rsi(
    c.map((x) => x.c),
    n,
  );
  return (
    <Frame>
      <Slider label="Período do RSI" value={n} min={5} max={30} onChange={setN} />
      <MiniChart
        candles={c}
        height={220}
        label="Preço e RSI no painel de baixo"
        sub={{
          values: r,
          label: `RSI ${n}`,
          min: 0,
          max: 100,
          levels: [
            { v: 70, color: "var(--loss)" },
            { v: 30, color: "var(--gain)" },
          ],
        }}
      />
      <p className="lv-explain">
        Acima de 70, o preço subiu rápido demais nos últimos {n} candles (<strong>sobrecomprado</strong>). Abaixo de 30, caiu rápido demais (
        <strong>sobrevendido</strong>). Com período menor, o RSI encosta nos extremos com mais frequência.
      </p>
    </Frame>
  );
}

// ---------------- 8. Cruzamento de médias ----------------
export function EmaCrossDemo() {
  const [fast, setFast] = useState(9);
  const [slow, setSlow] = useState(21);
  const c = mixed();
  const s = Math.max(slow, fast + 1);
  const r = useMemo(() => emaCross(c, fast, s), [c, fast, s]);
  return (
    <Frame>
      <div className="lv-row">
        <Slider label="Média rápida" value={fast} min={3} max={30} onChange={setFast} />
        <Slider label="Média lenta" value={s} min={fast + 1} max={100} onChange={setSlow} />
      </div>
      <MiniChart
        candles={c}
        label="Estratégia de cruzamento de médias: compras e vendas marcadas"
        lines={[
          { values: r.fast, color: A, label: `Média rápida (${fast})` },
          { values: r.slow, color: B, label: `Média lenta (${s})` },
        ]}
        {...tradeMarks(r)}
      />
      <ResultStats r={r} candles={c} />
      <p className="lv-explain">
        ▲ compra quando a rápida cruza para cima da lenta; ▼ vende no cruzamento para baixo. Repare: na alta (começo) ela ganha bem; no trecho lateral (meio) leva
        prejuízos pequenos seguidos. Já com custo de 0,2% por operação.
      </p>
    </Frame>
  );
}

// ---------------- 9. Reversão com RSI ----------------
export function RsiStrategyDemo() {
  const [g, setG] = useState<RegimeName>("lateral");
  const [low, setLow] = useState(30);
  const [exit, setExit] = useState(55);
  const c = regime(g);
  const r = useMemo(() => rsiReversion(c, 14, low, exit), [c, low, exit]);
  return (
    <Frame>
      <Segmented label="Tipo de mercado" value={g} onChange={setG} options={(["lateral", "queda", "alta"] as const).map((id) => ({ id, label: REGIME_LABEL[id] }))} />
      <div className="lv-row">
        <Slider label="Comprar com RSI abaixo de" value={low} min={15} max={45} onChange={setLow} />
        <Slider label="Vender com RSI acima de" value={exit} min={45} max={75} onChange={setExit} />
      </div>
      <MiniChart
        candles={c}
        height={220}
        label="Estratégia de reversão por RSI"
        {...tradeMarks(r)}
        sub={{
          values: r.rsi,
          label: "RSI 14",
          min: 0,
          max: 100,
          levels: [
            { v: exit, color: "var(--loss)" },
            { v: low, color: "var(--gain)" },
          ],
        }}
      />
      <ResultStats r={r} candles={c} />
      <p className="lv-explain">
        {g === "lateral"
          ? "No lateral, comprar o exagero da queda e vender na volta funciona: o preço oscila em torno de um centro."
          : g === "queda"
            ? "Na tendência de queda, o mesmo sinal compra uma queda que continua caindo. É por isso que o robô do sistema usa um filtro de tendência (média de 200)."
            : "Na alta forte, o RSI quase nunca fica sobrevendido: a estratégia fica parada e perde a subida inteira."}
      </p>
    </Frame>
  );
}

// ---------------- 10. Rompimento de canal ----------------
export function BreakoutDemo() {
  const [entry, setEntry] = useState(20);
  const [exitN, setExitN] = useState(10);
  const c = breakoutSeries();
  const r = useMemo(() => breakout(c, entry, exitN), [c, entry, exitN]);
  return (
    <Frame>
      <div className="lv-row">
        <Slider label="Comprar na máxima de" value={entry} min={10} max={55} onChange={setEntry} format={(v) => `${v} candles`} />
        <Slider label="Sair na mínima de" value={exitN} min={5} max={30} onChange={setExitN} format={(v) => `${v} candles`} />
      </div>
      <MiniChart
        candles={c}
        label="Estratégia de rompimento de canal"
        band={{ upper: r.upper, lower: r.lower, color: C, label: `Canal de ${entry} candles` }}
        lines={[{ values: r.exitLower, color: B, label: `Saída: mínima de ${exitN}`, dash: "5 4", width: 1.5 }]}
        {...tradeMarks(r)}
      />
      <ResultStats r={r} candles={c} />
      <p className="lv-explain">
        O canal mostra a máxima e a mínima dos últimos {entry} candles. Quando o preço fecha acima do teto, algo mudou: o robô compra e segue junto até perder a
        mínima de {exitN}. Erra várias vezes em rompimentos falsos e compensa nos movimentos longos.
      </p>
    </Frame>
  );
}

// ---------------- 11. Qual estratégia em qual mercado ----------------
export function RegimeDemo() {
  const [g, setG] = useState<RegimeName>("alta");
  const rows = useMemo(
    () =>
      (["alta", "lateral", "queda"] as const).map((name) => {
        const c = regime(name);
        return {
          name,
          bh: buyAndHold(c),
          ema: emaCross(c, 9, 21).totalPct,
          rsi: rsiReversion(c, 14, 30, 55).totalPct,
          brk: breakout(c, 20, 10).totalPct,
        };
      }),
    [],
  );
  const c = regime(g);
  const e = emaCross(c, 9, 21);
  return (
    <Frame>
      <div className="table-wrap">
        <table className="lv-table">
          <thead>
            <tr>
              <th>Mercado</th>
              <th className="num">Cruzamento de médias</th>
              <th className="num">Reversão RSI</th>
              <th className="num">Rompimento</th>
              <th className="num">Comprar e segurar</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const best = Math.max(r.ema, r.rsi, r.brk);
              const cell = (v: number) => (
                <td className={`num ${tone(v)}${v === best ? " lv-best" : ""}`}>{pct(v)}</td>
              );
              return (
                <tr key={r.name} className={r.name === g ? "lv-sel" : ""} onClick={() => setG(r.name)}>
                  <td>
                    <button type="button" className="lv-link" onClick={() => setG(r.name)}>
                      {REGIME_LABEL[r.name]}
                    </button>
                  </td>
                  {cell(r.ema)}
                  {cell(r.rsi)}
                  {cell(r.brk)}
                  <td className={`num ${tone(r.bh)}`}>{pct(r.bh)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <MiniChart candles={c} height={200} label={`${REGIME_LABEL[g]} com o cruzamento de médias`} lines={[{ values: e.fast, color: A, label: "Média 9" }, { values: e.slow, color: B, label: "Média 21" }]} />
      <p className="lv-explain">
        Mesmas três estratégias, três mercados diferentes. Nenhuma ganha em todos. Em destaque, a melhor de cada linha; na queda, a melhor foi ficar de fora (0%), já que estas estratégias só operam compradas. Toque em um mercado para ver o gráfico.
      </p>
    </Frame>
  );
}

// ---------------- 12. Tamanho da posição ----------------
export function RiskCalculator() {
  const [capital, setCapital] = useState(5000);
  const [risk, setRisk] = useState(1);
  const [entry, setEntry] = useState(100);
  const [stop, setStop] = useState(97);
  const valid = stop < entry && stop > 0;
  const riskMoney = (capital * risk) / 100;
  const perUnit = entry - stop;
  const units = valid ? riskMoney / perUnit : 0;
  const position = units * entry;
  const capped = position > capital;
  let left = capital;
  for (let i = 0; i < 10; i++) left -= (left * risk) / 100;
  const brl = (v: number) => v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  return (
    <Frame note={false}>
      <div className="lv-row">
        <label className="lv-field">
          Capital
          <input type="number" min={100} step={100} value={capital} onChange={(e) => setCapital(Math.max(0, Number(e.target.value)))} />
        </label>
        <label className="lv-field">
          Preço de entrada
          <input type="number" min={0.01} step={0.01} value={entry} onChange={(e) => setEntry(Number(e.target.value))} />
        </label>
        <label className="lv-field">
          Stop (onde você desiste)
          <input type="number" min={0.01} step={0.01} value={stop} onChange={(e) => setStop(Number(e.target.value))} />
        </label>
      </div>
      <Slider label="Quanto arriscar por operação" value={risk} min={0.25} max={5} step={0.25} onChange={setRisk} format={(v) => `${num(v, 2)}% do capital`} />
      {valid ? (
        <>
          <dl className="lv-stats">
            <Stat label="Perda máxima se o stop for atingido" value={brl(riskMoney)} tone="loss" />
            <Stat label="Distância do stop" value={pct((-perUnit / entry) * 100)} />
            <Stat label="Quantidade a comprar" value={num(units, units < 10 ? 4 : 0)} />
            <Stat label="Valor da posição" value={brl(position)} />
          </dl>
          {capped && <p className="lv-warn">A posição passa do seu capital: só seria possível com alavancagem. Afaste o stop ou arrisque menos.</p>}
          <p className="lv-explain">
            Depois de 10 perdas seguidas arriscando {num(risk, 2)}% em cada uma, sobrariam <strong>{brl(left)}</strong> ({pct(((left - capital) / capital) * 100)}).{" "}
            {risk <= 1 ? "Dá para continuar." : risk >= 3 ? "Um tombo difícil de recuperar." : "Doído, mas recuperável."}
          </p>
        </>
      ) : (
        <p className="lv-warn">Numa compra, o stop fica abaixo do preço de entrada.</p>
      )}
    </Frame>
  );
}

// ---------------- 13. Recuperar uma perda ----------------
export function RecoveryDemo() {
  const [loss, setLoss] = useState(30);
  const need = (1 / (1 - loss / 100) - 1) * 100;
  return (
    <Frame note={false}>
      <Slider label="Se você perder" value={loss} min={5} max={90} step={5} onChange={setLoss} format={(v) => `${v}%`} />
      <div className="lv-bars" aria-hidden="true">
        <div>
          <span>Perda</span>
          <i className="loss-bg" style={{ width: `${Math.min(100, loss / 4)}%` }} />
          <b className="loss">−{loss}%</b>
        </div>
        <div>
          <span>Para voltar</span>
          <i className="gain-bg" style={{ width: `${Math.min(100, need / 4)}%` }} />
          <b className="gain">+{num(need, 0)}%</b>
        </div>
      </div>
      <p className="lv-explain">
        Quem perde {loss}% fica com {100 - loss}. Para voltar a 100, precisa ganhar {num(need, 0)}% em cima do que sobrou. Por isso proteger o capital vem antes de
        buscar ganho.
      </p>
    </Frame>
  );
}

// ---------------- 14. Expectativa ----------------
export function ExpectancyDemo() {
  const [win, setWin] = useState(60);
  const [gain, setGain] = useState(1);
  const [loss, setLoss] = useState(1.5);
  const [seed, setSeed] = useState(1);
  const cost = 0.2;
  const exp = (win / 100) * gain - (1 - win / 100) * loss - cost;
  const sim = useMemo(() => {
    const rand = mulberry32(seed * 7919);
    let eq = 100;
    let streak = 0;
    let worst = 0;
    const curve = [eq];
    for (let i = 0; i < 100; i++) {
      const w = rand() < win / 100;
      eq *= 1 + ((w ? gain : -loss) - cost) / 100;
      streak = w ? 0 : streak + 1;
      worst = Math.max(worst, streak);
      curve.push(eq);
    }
    return { curve, worst, final: eq - 100 };
  }, [win, gain, loss, seed]);
  const lo = Math.min(...sim.curve);
  const hi = Math.max(...sim.curve);
  const W = 600;
  const H = 120;
  const d = sim.curve.map((v, i) => `${i ? "L" : "M"}${((i / 100) * W).toFixed(1)},${(H - 6 - ((v - lo) / (hi - lo || 1)) * (H - 12)).toFixed(1)}`).join("");
  const presets = [
    { label: "Acerta muito, ganha pouco", w: 80, g: 0.5, l: 2.5 },
    { label: "Acerta pouco, ganha muito", w: 35, g: 3, l: 1 },
  ];
  return (
    <Frame note={false}>
      <div className="actions">
        {presets.map((p) => (
          <button
            key={p.label}
            type="button"
            className="btn"
            onClick={() => {
              setWin(p.w);
              setGain(p.g);
              setLoss(p.l);
            }}
          >
            {p.label}
          </button>
        ))}
      </div>
      <Slider label="Taxa de acerto" value={win} min={20} max={90} onChange={setWin} format={(v) => `${v}%`} />
      <div className="lv-row">
        <Slider label="Ganho médio quando acerta" value={gain} min={0.25} max={5} step={0.25} onChange={setGain} format={(v) => `${num(v, 2)}%`} />
        <Slider label="Perda média quando erra" value={loss} min={0.25} max={5} step={0.25} onChange={setLoss} format={(v) => `${num(v, 2)}%`} />
      </div>
      <dl className="lv-stats">
        <Stat label="Expectativa por operação (com custo de 0,2%)" value={pct(exp, 2)} tone={tone(exp)} />
        <Stat label="100 operações sorteadas" value={pct(sim.final)} tone={tone(sim.final)} />
        <Stat label="Pior sequência de erros" value={`${sim.worst} seguidas`} />
      </dl>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="lv-curve" role="img" aria-label={`Saldo ao longo de 100 operações sorteadas: ${pct(sim.final)}`}>
        <line x1={0} x2={W} y1={H - 6 - ((100 - lo) / (hi - lo || 1)) * (H - 12)} y2={H - 6 - ((100 - lo) / (hi - lo || 1)) * (H - 12)} className="mc-level" style={{ stroke: "var(--muted)" }} />
        <path d={d} className="mc-line" style={{ stroke: exp >= 0 ? "var(--gain)" : "var(--loss)", strokeWidth: 2 }} />
      </svg>
      <div className="actions">
        <button type="button" className="btn btn-quiet" onClick={() => setSeed((s) => s + 1)}>
          Sortear outras 100 operações
        </button>
      </div>
      <p className="lv-explain">
        Expectativa = acerto × ganho médio − erro × perda média − custo. Se ela é negativa, acertar muito não salva. Sorteie de novo e veja como a sorte muda o
        caminho, mas não o destino.
      </p>
    </Frame>
  );
}

export const VISUALS = {
  "long-short": LongShortDemo,
  cost: CostDemo,
  candle: CandleAnatomy,
  timeframe: TimeframeDemo,
  trend: TrendDemo,
  "moving-average": MovingAverageDemo,
  rsi: RsiDemo,
  "ema-cross": EmaCrossDemo,
  "rsi-strategy": RsiStrategyDemo,
  breakout: BreakoutDemo,
  regime: RegimeDemo,
  risk: RiskCalculator,
  recovery: RecoveryDemo,
  expectancy: ExpectancyDemo,
} as const;

export type VisualId = keyof typeof VISUALS;
