import Link from "next/link";
import { BRAND } from "@/lib/brand";
import { Logo } from "@/components/Logo";

export const metadata = { title: `Privacidade — ${BRAND}` };

export default function Privacy() {
  return (
    <main className="landing" style={{ display: "grid", gap: 16 }}>
      <Link href="/" className="brand" aria-label={`${BRAND}, início`}><Logo height={28} /></Link>
      <h1>Política de privacidade</h1>
      <div className="notice">
        <strong>Modelo a ser revisado por advogado</strong>
        Ajuste à operação real e à LGPD (Lei 13.709/2018) antes de publicar, incluindo o contato do encarregado de dados.
      </div>
      <p>Coletamos nome, e-mail, registros de acesso (data, hora e IP) e as configurações e ordens dos seus robôs, para prestar o serviço contratado.</p>
      <p>As chaves de API da corretora são guardadas cifradas e usadas apenas para enviar as ordens dos seus robôs. Dados de pagamento ficam com o Mercado Pago.</p>
      <p>Você pode excluir a conta pelo painel. Registros de auditoria são mantidos pelo prazo exigido em lei.</p>
    </main>
  );
}
