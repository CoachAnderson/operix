import type { Metadata } from "next";
// Fonte servida pelo próprio app (sem chamada ao Google em build ou em produção).
import "@fontsource-variable/schibsted-grotesk";
// Fontes opcionais (Aparência). O navegador só baixa o arquivo da fonte escolhida.
import "@fontsource-variable/inter";
import "@fontsource/atkinson-hyperlegible/400.css";
import "@fontsource/atkinson-hyperlegible/700.css";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-sans/700.css";
import "@fontsource-variable/source-serif-4";
import "./globals.css";
import { BRAND } from "@/lib/brand";
import { bootScript } from "@/lib/appearance";

export const metadata: Metadata = {
  title: `${BRAND} — robôs de negociação para cripto e forex`,
  description: "Robôs de negociação para Binance e cTrader com simulação, sinais e execução automática.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // data-theme é definido pelo script abaixo antes da hidratação (tema escolhido pelo usuário).
    <html lang="pt-BR" suppressHydrationWarning>
      <head>
        {/* Aplica tema, cores e fonte salvos antes da primeira pintura (sem piscar). */}
        <script dangerouslySetInnerHTML={{ __html: bootScript() }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
