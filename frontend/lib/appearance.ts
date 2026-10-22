/**
 * Aparência do painel: tema (automático/claro/escuro), paleta, cor de destaque, cores de texto e fundo,
 * fonte, tamanho do texto, cantos e cores de ganho/perda.
 *
 * Como funciona:
 * - `cssFor()` gera um bloco de CSS que sobrescreve os tokens de globals.css (seletores `html:root...` têm
 *   especificidade maior, então valem em qualquer ordem de carregamento).
 * - O mesmo `cssFor()` vai, como texto, para um script inline no <head> (ver app/layout.tsx), que aplica a
 *   aparência salva no navegador ANTES da primeira pintura: sem "piscar" claro antes do escuro.
 * - A escolha é salva no navegador (instantâneo) e na conta (PUT /me/appearance), para valer em todos os aparelhos.
 * - Só entram valores conhecidos e cores #RRGGBB (validadas aqui e no servidor): nada de CSS arbitrário.
 */

export type ThemeMode = "auto" | "light" | "dark";
export type PaletteId = "razao" | "grafite" | "oceano" | "floresta" | "areia" | "oled";
export type FontId = "schibsted" | "inter" | "atkinson" | "plex" | "serif" | "system";
export type ColorKey = "paper" | "surface" | "ink" | "muted";
export type Mode = "light" | "dark";

export interface Appearance {
  v: 1;
  theme: ThemeMode;
  palette: PaletteId;
  accent: string | null;
  font: FontId;
  scale: 90 | 100 | 110 | 120;
  radius: "square" | "default" | "round";
  pnl: "green-red" | "blue-orange";
  custom: { light: Partial<Record<ColorKey, string>>; dark: Partial<Record<ColorKey, string>> };
}

export const DEFAULT_APPEARANCE: Appearance = {
  v: 1,
  theme: "auto",
  palette: "razao",
  accent: null,
  font: "schibsted",
  scale: 100,
  radius: "default",
  pnl: "green-red",
  custom: { light: {}, dark: {} },
};

type Tokens = { paper: string; surface: string; ink: string; muted: string; rule: string };

export const APPEARANCE_DATA = {
  palettes: {
    razao: {
      name: "Livro-razão",
      hint: "Padrão: papel contábil e tinta azul-escura",
      light: { paper: "#f2f4f1", surface: "#ffffff", ink: "#17202b", muted: "#56606b", rule: "#d5dbd8" },
      dark: { paper: "#12171d", surface: "#1a2129", ink: "#e6eaee", muted: "#9aa5b1", rule: "#2c353f" },
    },
    grafite: {
      name: "Grafite",
      hint: "Cinzas neutros, sem tom de cor",
      light: { paper: "#f4f4f5", surface: "#ffffff", ink: "#18181b", muted: "#52525b", rule: "#d4d4d8" },
      dark: { paper: "#111113", surface: "#1b1b1f", ink: "#ececef", muted: "#a1a1aa", rule: "#2e2e33" },
    },
    oceano: {
      name: "Oceano",
      hint: "Fundo azulado",
      light: { paper: "#edf2f8", surface: "#ffffff", ink: "#0f2537", muted: "#4b6074", rule: "#cddae6" },
      dark: { paper: "#0b1622", surface: "#12202e", ink: "#e3edf6", muted: "#93a8bb", rule: "#24384b" },
    },
    floresta: {
      name: "Floresta",
      hint: "Fundo esverdeado",
      light: { paper: "#eef4ef", surface: "#ffffff", ink: "#14261b", muted: "#4d6255", rule: "#cddbd1" },
      dark: { paper: "#0d1611", surface: "#152119", ink: "#e2ede5", muted: "#93a99b", rule: "#26382c" },
    },
    areia: {
      name: "Areia",
      hint: "Tons quentes, como papel antigo",
      light: { paper: "#f6f1e7", surface: "#fffdf8", ink: "#2a2118", muted: "#6b5d4f", rule: "#e2d8c6" },
      dark: { paper: "#17130e", surface: "#211b14", ink: "#efe7da", muted: "#b0a291", rule: "#3a3127" },
    },
    oled: {
      name: "Preto total",
      hint: "No escuro, fundo preto puro (economiza bateria em telas OLED)",
      light: { paper: "#f4f4f5", surface: "#ffffff", ink: "#111111", muted: "#525252", rule: "#d4d4d4" },
      dark: { paper: "#000000", surface: "#0d0d0d", ink: "#f2f2f2", muted: "#a3a3a3", rule: "#262626" },
    },
  } as Record<PaletteId, { name: string; hint: string; light: Tokens; dark: Tokens }>,
  fonts: {
    schibsted: { name: "Schibsted Grotesk", hint: "Padrão do sistema", stack: '"Schibsted Grotesk Variable"' },
    inter: { name: "Inter", hint: "Neutra, muito usada em painéis", stack: '"Inter Variable"' },
    atkinson: { name: "Atkinson Hyperlegible", hint: "Feita para baixa visão: letras bem diferentes entre si", stack: '"Atkinson Hyperlegible"' },
    plex: { name: "IBM Plex Sans", hint: "Técnica, números largos", stack: '"IBM Plex Sans"' },
    serif: { name: "Source Serif", hint: "Serifada, para quem prefere leitura de livro", stack: '"Source Serif 4 Variable", Georgia, serif' },
    system: { name: "Fonte do aparelho", hint: "A mesma do Windows, Mac, Android ou iPhone", stack: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif' },
  } as Record<FontId, { name: string; hint: string; stack: string }>,
  radius: { square: [0, 2], default: [4, 8], round: [10, 18] } as Record<Appearance["radius"], [number, number]>,
  pnl: {
    "blue-orange": {
      light: { gain: "#1d63c4", loss: "#c2570c" },
      dark: { gain: "#6aa8f0", loss: "#f0954d" },
    },
  } as Record<string, { light: { gain: string; loss: string }; dark: { gain: string; loss: string } }>,
};

export const ACCENTS: { name: string; hex: string | null }[] = [
  { name: "Padrão (cor do texto)", hex: null },
  { name: "Azul", hex: "#2563eb" },
  { name: "Verde", hex: "#15803d" },
  { name: "Roxo", hex: "#7c3aed" },
  { name: "Laranja", hex: "#ea580c" },
  { name: "Rosa", hex: "#db2777" },
  { name: "Ciano", hex: "#0e7490" },
  { name: "Dourado", hex: "#b7791f" },
];

/**
 * Gera o CSS da aparência. AUTOCONTIDA de propósito (sem imports, sem variáveis de fora): o texto desta função
 * também é embutido no script do <head>. Não use spread, optional chaining nem funções externas aqui.
 */
/* eslint-disable no-var, @typescript-eslint/no-explicit-any */
export function cssFor(a: any, D: any): { theme: string | null; css: string } {
  var hex = /^#[0-9a-fA-F]{6}$/;
  if (!a || typeof a !== "object") a = {};
  var pal = D.palettes[a.palette] || D.palettes.razao;
  var custom = a.custom && typeof a.custom === "object" ? a.custom : {};
  var pnl = D.pnl[a.pnl] || null;
  function block(mode: string) {
    var src = pal[mode];
    var cm = custom[mode] && typeof custom[mode] === "object" ? custom[mode] : {};
    var keys = ["paper", "surface", "ink", "muted", "rule"];
    var out = [];
    for (var i = 0; i < keys.length; i++) {
      var k = keys[i];
      out.push("--" + k + ":" + (hex.test(cm[k] || "") ? cm[k] : src[k]));
    }
    out.push("--live:var(--ink)");
    if (pnl) out.push("--gain:" + pnl[mode].gain, "--loss:" + pnl[mode].loss);
    return out.join(";");
  }
  var common = [];
  var f = D.fonts[a.font];
  if (f) common.push("--font-sans:" + f.stack);
  var r = D.radius[a.radius];
  if (r) common.push("--radius-s:" + r[0] + "px", "--radius-m:" + r[1] + "px");
  if (hex.test(a.accent || "")) {
    var n = parseInt(a.accent.slice(1), 16);
    var ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    var lum = 0;
    var w = [0.2126, 0.7152, 0.0722];
    for (var j = 0; j < 3; j++) {
      var c = ch[j] / 255;
      lum += w[j] * (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
    }
    common.push("--accent:" + a.accent, "--on-accent:" + (lum > 0.179 ? "#111111" : "#ffffff"));
  }
  var scale = [90, 100, 110, 120].indexOf(a.scale) >= 0 ? a.scale : 100;
  common.push("font-size:" + scale + "%");
  var css =
    "html:root{" + common.join(";") + ";" + block("light") + "}" +
    '@media (prefers-color-scheme: dark){html:root:not([data-theme="light"]){' + block("dark") + "}}" +
    'html:root[data-theme="dark"]{' + block("dark") + "}";
  var theme = a.theme === "light" || a.theme === "dark" ? a.theme : null;
  return { theme: theme, css: css };
}
/* eslint-enable no-var, @typescript-eslint/no-explicit-any */

export const STORAGE_KEY = "oi-aparencia";
export const APPEARANCE_EVENT = "oi-aparencia";

/** Script do <head>: aplica a aparência salva no navegador antes da primeira pintura. */
export function bootScript(): string {
  const data = JSON.stringify(APPEARANCE_DATA).replace(/</g, "\\u003c");
  return (
    `(function(){try{var D=${data};var cssFor=${cssFor.toString()};var a=null;` +
    `try{a=JSON.parse(localStorage.getItem(${JSON.stringify(STORAGE_KEY)})||"null")}catch(e){}` +
    `var r=cssFor(a,D);var h=document.documentElement;if(r.theme)h.setAttribute("data-theme",r.theme);` +
    `var s=document.createElement("style");s.id="oi-aparencia";s.textContent=r.css;document.head.appendChild(s)}catch(e){}})();`
  );
}

const HEX = /^#[0-9a-fA-F]{6}$/;

/** Normaliza qualquer coisa (do navegador ou do servidor) para uma aparência válida. */
export function normalize(raw: unknown): Appearance {
  const a = (raw && typeof raw === "object" ? raw : {}) as Partial<Appearance>;
  const pick = <T,>(v: unknown, allowed: readonly T[], def: T): T => (allowed.includes(v as T) ? (v as T) : def);
  const colors = (m: unknown) => {
    const out: Partial<Record<ColorKey, string>> = {};
    if (m && typeof m === "object")
      for (const k of ["paper", "surface", "ink", "muted"] as ColorKey[]) {
        const v = (m as Record<string, unknown>)[k];
        if (typeof v === "string" && HEX.test(v)) out[k] = v.toLowerCase();
      }
    return out;
  };
  return {
    v: 1,
    theme: pick(a.theme, ["auto", "light", "dark"] as const, "auto"),
    palette: pick(a.palette, Object.keys(APPEARANCE_DATA.palettes) as PaletteId[], "razao"),
    accent: typeof a.accent === "string" && HEX.test(a.accent) ? a.accent.toLowerCase() : null,
    font: pick(a.font, Object.keys(APPEARANCE_DATA.fonts) as FontId[], "schibsted"),
    scale: pick(a.scale, [90, 100, 110, 120] as const, 100),
    radius: pick(a.radius, ["square", "default", "round"] as const, "default"),
    pnl: pick(a.pnl, ["green-red", "blue-orange"] as const, "green-red"),
    custom: { light: colors(a.custom?.light), dark: colors(a.custom?.dark) },
  };
}

export function loadLocal(): Appearance | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? normalize(JSON.parse(raw)) : null;
  } catch {
    return null;
  }
}

export function saveLocal(a: Appearance | null): void {
  try {
    if (a) localStorage.setItem(STORAGE_KEY, JSON.stringify(a));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* navegador sem armazenamento: vale só nesta página */
  }
}

/** Aplica na página agora (e avisa gráficos e widgets para se redesenharem). */
export function applyAppearance(a: Appearance | null): void {
  const r = cssFor(a, APPEARANCE_DATA);
  const html = document.documentElement;
  if (r.theme) html.setAttribute("data-theme", r.theme);
  else html.removeAttribute("data-theme");
  let el = document.getElementById("oi-aparencia") as HTMLStyleElement | null;
  if (!el) {
    el = document.createElement("style");
    el.id = "oi-aparencia";
    document.head.appendChild(el);
  }
  el.textContent = r.css;
  window.dispatchEvent(new Event(APPEARANCE_EVENT));
}

export function isDark(): boolean {
  const t = document.documentElement.getAttribute("data-theme");
  if (t) return t === "dark";
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

/** Valor do token como está na página agora (já com tema e personalizações). */
export function tokenColor(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Contraste WCAG entre duas cores #RRGGBB (1 a 21). 4,5 é o mínimo para texto comum. */
export function contrast(a: string, b: string): number {
  const lum = (h: string) => {
    const n = parseInt(h.slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
      .map((c) => c / 255)
      .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
      .reduce((s, c, i) => s + c * [0.2126, 0.7152, 0.0722][i], 0);
  };
  if (!HEX.test(a) || !HEX.test(b)) return 21;
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

/** Cores efetivas de um modo (paleta + personalizações), para prévia e conferência de contraste. */
export function resolvedColors(a: Appearance, mode: Mode): Tokens {
  const base = APPEARANCE_DATA.palettes[a.palette][mode];
  return { ...base, ...a.custom[mode] };
}
