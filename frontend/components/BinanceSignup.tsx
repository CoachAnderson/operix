import { BINANCE_REF_URL, BRAND } from "@/lib/brand";

/** Convite para abrir conta na Binance pelo link de indicação, com aviso de que é um link de indicação. */
export function BinanceSignup({ compact = false }: { compact?: boolean }) {
  if (!BINANCE_REF_URL) return null;
  if (compact) {
    return (
      <span>
        Ainda não tem conta?{" "}
        <a href={BINANCE_REF_URL} target="_blank" rel="noopener sponsored">
          Criar conta na Binance
        </a>
        .
      </span>
    );
  }
  return (
    <div className="signup-cta">
      <div style={{ display: "grid", gap: 4 }}>
        <strong>Ainda não tem conta na Binance?</strong>
        <span className="muted small">
          Crie a conta, faça a verificação de identidade e depois volte aqui para gerar a chave de API.
        </span>
      </div>
      <a className="btn btn-primary" href={BINANCE_REF_URL} target="_blank" rel="noopener sponsored">
        Criar conta na Binance
      </a>
      <p className="muted small signup-note">
        Link de indicação: o {BRAND} pode receber uma parte das taxas da Binance das contas criadas por ele, sem custo extra para
        você. Se preferir, crie a conta direto em binance.com.
      </p>
    </div>
  );
}
