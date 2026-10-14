import type { Metadata } from "next";
// Fonte servida pelo próprio app (sem chamada ao Google em build ou em produção).
import "@fontsource-variable/schibsted-grotesk";
import "./globals.css";
import { BRAND } from "@/lib/brand";

export const metadata: Metadata = {
  title: `${BRAND} — robôs de negociação para cripto e forex`,
  description: "Robôs de negociação para Binance e cTrader com simulação, sinais e execução automática.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
