"use client";

import { useEffect, useMemo, useState } from "react";
import { persistAppearance, useAppearanceVersion } from "@/components/Appearance";
import { useUser } from "@/components/AppShell";
import { PageHead } from "@/components/ui";
import { api } from "@/lib/api";
import {
  ACCENTS,
  APPEARANCE_DATA,
  DEFAULT_APPEARANCE,
  applyAppearance,
  contrast,
  isDark,
  loadLocal,
  normalize,
  resolvedColors,
  saveLocal,
  type Appearance,
  type ColorKey,
  type FontId,
  type Mode,
  type PaletteId,
} from "@/lib/appearance";
import { money } from "@/lib/format";

const COLOR_FIELDS: { key: ColorKey; label: string }[] = [
  { key: "paper", label: "Fundo" },
  { key: "surface", label: "Cartões e tabelas" },
  { key: "ink", label: "Texto" },
  { key: "muted", label: "Texto secundário" },
];

const THEMES: { id: Appearance["theme"]; label: string; hint: string }[] = [
  { id: "auto", label: "Automático", hint: "Segue o tema do celular ou do computador" },
  { id: "light", label: "Claro", hint: "Sempre claro" },
  { id: "dark", label: "Escuro", hint: "Sempre escuro" },
];

function Ratio({ label, a, b }: { label: string; a: string; b: string }) {
  const r = contrast(a, b);
  const ok = r >= 4.5;
  return (
    <span>
      {label}: <b className={ok ? "gain" : "loss"}>{money(r, 1)}:1</b>
      <span className="muted">{ok ? "boa leitura" : r >= 3 ? "fraco para texto pequeno" : "difícil de ler"}</span>
    </span>
  );
}

export default function AparenciaPage() {
  const { user, refresh } = useUser();
  const [a, setA] = useState<Appearance | null>(null);
  const [status, setStatus] = useState("");
  const [editMode, setEditMode] = useState<Mode>("light");
  const version = useAppearanceVersion();

  useEffect(() => {
    const start = user.appearance ? normalize(user.appearance) : loadLocal() ?? DEFAULT_APPEARANCE;
    setA(start);
    setEditMode(isDark() ? "dark" : "light");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Ao trocar entre claro e escuro, edita as cores do tema que está na tela.
  useEffect(() => {
    if (a) setEditMode(isDark() ? "dark" : "light");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version]);

  function update(patch: Partial<Appearance>) {
    if (!a) return;
    const next = normalize({ ...a, ...patch });
    setA(next);
    setStatus("Salvando…");
    persistAppearance(next, {
      account: true,
      onDone: (ok) => setStatus(ok ? "Salvo na sua conta: vale em todos os seus aparelhos." : "Salvo neste navegador. Não foi possível salvar na conta agora."),
    });
  }

  function setColor(key: ColorKey, value: string | null) {
    if (!a) return;
    const mode = { ...a.custom[editMode] };
    if (value) mode[key] = value;
    else delete mode[key];
    update({ custom: { ...a.custom, [editMode]: mode } });
  }

  async function resetAll() {
    setA(DEFAULT_APPEARANCE);
    saveLocal(null);
    applyAppearance(null);
    try {
      await api("/me/appearance", { method: "DELETE" });
      await refresh();
      setStatus("Aparência padrão restaurada.");
    } catch {
      setStatus("Padrão restaurado neste navegador.");
    }
  }

  const colors = useMemo(() => (a ? resolvedColors(a, editMode) : null), [a, editMode]);
  if (!a || !colors) return null;
  const customized = Object.keys(a.custom[editMode]).length > 0;

  return (
    <div className="ap">
      <PageHead title="Aparência" lead="Tema claro ou escuro, cores, fonte e tamanho do texto. As mudanças aparecem na hora e ficam salvas na sua conta." />
      <p className="ap-status" role="status" aria-live="polite">
        {status}
      </p>

      <section className="ap-sec">
        <header>
          <h2>Tema</h2>
        </header>
        <div className="choice" role="radiogroup" aria-label="Tema">
          {THEMES.map((t) => (
            <label key={t.id}>
              <input type="radio" name="theme" checked={a.theme === t.id} onChange={() => update({ theme: t.id })} />
              {t.label}
              <span className="hint">{t.hint}</span>
            </label>
          ))}
        </div>
      </section>

      <section className="ap-sec">
        <header>
          <h2>Paleta</h2>
          <p className="muted small">Cores de fundo, cartões, texto e linhas. Cada paleta tem versão clara e escura.</p>
        </header>
        <div className="choice" role="radiogroup" aria-label="Paleta">
          {(Object.keys(APPEARANCE_DATA.palettes) as PaletteId[]).map((id) => {
            const p = APPEARANCE_DATA.palettes[id];
            const c = p[editMode];
            return (
              <label key={id}>
                <input type="radio" name="palette" checked={a.palette === id} onChange={() => update({ palette: id })} />
                {p.name}
                <span className="hint">{p.hint}</span>
                <span className="ap-mini" style={{ background: c.paper, color: c.ink, borderColor: c.rule }} aria-hidden="true">
                  <span style={{ background: c.surface, border: `1px solid ${c.rule}`, borderRadius: 4, padding: "4px 6px" }}>
                    Saldo <span style={{ color: c.muted }}>R$ 1.250,00</span>
                  </span>
                  <i style={{ background: a.accent ?? c.ink, width: "45%" }} />
                </span>
              </label>
            );
          })}
        </div>
      </section>

      <section className="ap-sec">
        <header>
          <h2>Cor de destaque</h2>
          <p className="muted small">Botão principal, item ativo do menu e contorno de foco.</p>
        </header>
        <div className="ap-accents">
          {ACCENTS.map((c) => (
            <button
              key={c.name}
              type="button"
              className="ap-accent"
              title={c.name}
              aria-label={c.name}
              aria-pressed={a.accent === c.hex}
              style={{ background: c.hex ?? colors.ink, color: c.hex ? "#fff" : colors.paper }}
              onClick={() => update({ accent: c.hex })}
            />
          ))}
          <label className="ap-accent-custom">
            <input
              type="color"
              value={a.accent ?? "#2563eb"}
              aria-label="Escolher outra cor de destaque"
              onChange={(e) => update({ accent: e.target.value })}
            />
            Outra cor
          </label>
        </div>
      </section>

      <section className="ap-sec">
        <header>
          <h2>Cores do texto e do fundo</h2>
          <p className="muted small">
            Ajuste fino por cima da paleta. Você está editando o tema <strong>{editMode === "dark" ? "escuro" : "claro"}</strong>
            {a.theme === "auto" ? " (o que o seu aparelho está usando agora)" : ""}.
          </p>
        </header>
        <div className="presets" role="group" aria-label="Tema que está sendo editado">
          {(["light", "dark"] as Mode[]).map((m) => (
            <button key={m} type="button" className="btn" aria-pressed={editMode === m} onClick={() => setEditMode(m)}>
              {m === "light" ? "Tema claro" : "Tema escuro"}
            </button>
          ))}
        </div>
        <div className="ap-colors">
          {COLOR_FIELDS.map((f) => {
            const own = a.custom[editMode][f.key];
            return (
              <label key={f.key} className="ap-color">
                <input type="color" value={colors[f.key]} onChange={(e) => setColor(f.key, e.target.value)} />
                {f.label}
                <span className="row">
                  <code>{colors[f.key]}</code>
                  {own ? (
                    <button type="button" onClick={(e) => { e.preventDefault(); setColor(f.key, null); }}>
                      usar a da paleta
                    </button>
                  ) : (
                    <span>da paleta</span>
                  )}
                </span>
              </label>
            );
          })}
        </div>
        <div className="ap-contrast">
          <Ratio label="Texto no fundo" a={colors.ink} b={colors.paper} />
          <Ratio label="Texto nos cartões" a={colors.ink} b={colors.surface} />
          <Ratio label="Texto secundário" a={colors.muted} b={colors.surface} />
        </div>
        {customized && (
          <button type="button" className="btn btn-quiet" style={{ width: "fit-content" }} onClick={() => update({ custom: { ...a.custom, [editMode]: {} } })}>
            Desfazer as cores personalizadas do tema {editMode === "dark" ? "escuro" : "claro"}
          </button>
        )}
      </section>

      <section className="ap-sec">
        <header>
          <h2>Fonte</h2>
        </header>
        <div className="choice" role="radiogroup" aria-label="Fonte">
          {(Object.keys(APPEARANCE_DATA.fonts) as FontId[]).map((id) => {
            const f = APPEARANCE_DATA.fonts[id];
            return (
              <label key={id}>
                <input type="radio" name="font" checked={a.font === id} onChange={() => update({ font: id })} />
                <span className="ap-font-sample" style={{ fontFamily: f.stack }}>
                  {f.name}
                  <small>Saldo R$ 12.480,35 · 0O 1Il</small>
                </span>
                <span className="hint">{f.hint}</span>
              </label>
            );
          })}
        </div>
      </section>

      <section className="ap-sec">
        <header>
          <h2>Tamanho do texto</h2>
        </header>
        <div className="presets" role="group" aria-label="Tamanho do texto">
          {([90, 100, 110, 120] as const).map((s) => (
            <button key={s} type="button" className="btn" aria-pressed={a.scale === s} onClick={() => update({ scale: s })}>
              {s === 100 ? "Normal" : `${s}%`}
            </button>
          ))}
        </div>
      </section>

      <section className="ap-sec">
        <header>
          <h2>Cantos</h2>
        </header>
        <div className="presets" role="group" aria-label="Cantos">
          {(
            [
              ["square", "Retos"],
              ["default", "Padrão"],
              ["round", "Arredondados"],
            ] as const
          ).map(([id, label]) => (
            <button key={id} type="button" className="btn" aria-pressed={a.radius === id} onClick={() => update({ radius: id })}>
              {label}
            </button>
          ))}
        </div>
      </section>

      <section className="ap-sec">
        <header>
          <h2>Ganho e perda</h2>
          <p className="muted small">Azul e laranja ajudam quem tem dificuldade de distinguir verde de vermelho (daltonismo).</p>
        </header>
        <div className="choice" role="radiogroup" aria-label="Cores de ganho e perda">
          {(
            [
              ["green-red", "Verde e vermelho"],
              ["blue-orange", "Azul e laranja"],
            ] as const
          ).map(([id, label]) => {
            const alt = APPEARANCE_DATA.pnl[id]?.[editMode];
            return (
              <label key={id}>
                <input type="radio" name="pnl" checked={a.pnl === id} onChange={() => update({ pnl: id })} />
                {label}
                <span className="hint">
                  <span style={{ color: alt?.gain ?? "var(--gain)", fontWeight: 600 }}>+R$ 120,00</span> ·{" "}
                  <span style={{ color: alt?.loss ?? "var(--loss)", fontWeight: 600 }}>−R$ 80,00</span>
                </span>
              </label>
            );
          })}
        </div>
      </section>

      <section className="ap-sec">
        <header>
          <h2>Prévia</h2>
        </header>
        <div className="ap-preview">
          <div className="row">
            <strong>Robô BTC · Reversão por RSI</strong>
            <span className="muted small">simulação</span>
          </div>
          <div className="row">
            <span>
              Hoje: <span className="gain">+R$ 120,00</span>
            </span>
            <span>
              Ontem: <span className="loss">−R$ 80,00</span>
            </span>
          </div>
          <div className="row">
            <button type="button" className="btn btn-primary">
              Botão principal
            </button>
            <button type="button" className="btn">
              Botão comum
            </button>
            <input aria-label="Campo de exemplo" defaultValue="Campo de texto" style={{ maxWidth: 200 }} />
          </div>
          <p className="notice small">Avisos aparecem assim.</p>
        </div>
      </section>

      <div className="ap-actions">
        <button type="button" className="btn" onClick={resetAll}>
          Restaurar a aparência padrão
        </button>
      </div>
    </div>
  );
}
