import Link from "next/link";
import { BRAND } from "@/lib/brand";
import { Logo } from "@/components/Logo";

export const metadata = { title: `Termos de uso — ${BRAND}` };

export default function Terms() {
  return (
    <main className="landing" style={{ display: "grid", gap: 16 }}>
      <Link href="/" className="brand" aria-label={`${BRAND}, início`}><Logo height={28} /></Link>
      <h1>Termos de uso</h1>
      <div className="notice">
        <strong>Modelo a ser revisado por advogado</strong>
        Este texto é um ponto de partida. Antes de publicar, adapte com assessoria jurídica especializada em mercado de capitais,
        criptoativos e defesa do consumidor.
      </div>
      <p>1. O {BRAND} é um software de automação. O usuário conecta a própria conta na corretora, escolhe as estratégias e define os parâmetros e limites de risco.</p>
      <p>2. A plataforma não presta consultoria, análise ou recomendação de investimento, não administra carteira e não recebe, guarda ou movimenta recursos do usuário.</p>
      <p>3. Operações com criptoativos e com moedas (forex) envolvem risco de perda, inclusive total; no forex, a alavancagem da corretora pode ampliar as perdas. Resultados passados, simulados ou de testnet não garantem resultados futuros.</p>
      <p>4. O usuário opera com as próprias credenciais (chaves de API da Binance, app e tokens do cTrader) e é responsável por elas; as chaves devem ter apenas permissão de leitura e negociação, sem saque. A escolha da corretora e o cumprimento das regras do país dela são do usuário.</p>
      <p>5. A assinatura é mensal, cobrada pelo Mercado Pago, e pode ser cancelada a qualquer momento pelo painel.</p>
      <p>6. A plataforma pode suspender operações em caso de incidente técnico, instabilidade da corretora ou suspeita de uso indevido.</p>
    </main>
  );
}
