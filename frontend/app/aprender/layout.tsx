import type { Metadata } from "next";
import { LearnHeader } from "@/components/learn/LearnHeader";
import { BRAND } from "@/lib/brand";

export const metadata: Metadata = {
  title: { default: `Aprender — ${BRAND}`, template: `%s — Aprender — ${BRAND}` },
  description: "Aulas curtas e interativas sobre mercado financeiro: candles, tempo gráfico, médias móveis, RSI, estratégias, risco e backtest.",
};

export default function LearnLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="learn">
      <LearnHeader />
      <main className="learn-main">{children}</main>
      <footer className="learn-foot">
        Conteúdo educativo. Não é recomendação de investimento. Operar envolve risco de perder parte ou todo o capital, e resultados passados não garantem
        resultados futuros.
      </footer>
    </div>
  );
}
