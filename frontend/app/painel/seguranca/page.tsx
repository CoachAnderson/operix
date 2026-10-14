"use client";

import { useRouter } from "next/navigation";
import QRCode from "qrcode";
import { useState } from "react";
import { useUser } from "@/components/AppShell";
import { ErrorText, PageHead, useAction } from "@/components/ui";
import { api } from "@/lib/api";
import { date } from "@/lib/format";

const RISK_TERMS_VERSION = "2026-10";

export default function SecurityPage() {
  const { user, refresh } = useUser();
  const router = useRouter();
  const twofa = useAction();
  const risk = useAction();
  const pwd = useAction();
  const danger = useAction();
  const [qr, setQr] = useState<{ img: string; secret: string } | null>(null);
  const [code, setCode] = useState("");
  const [riskOk, setRiskOk] = useState(false);
  const [passwords, setPasswords] = useState({ current_password: "", new_password: "" });
  const [pwdDone, setPwdDone] = useState(false);

  async function startTotp() {
    const res = await twofa.run(() => api<{ secret: string; otpauth_uri: string }>("/me/2fa/setup", { method: "POST" }));
    if (res) setQr({ img: await QRCode.toDataURL(res.otpauth_uri, { margin: 1, width: 200 }), secret: res.secret });
  }

  async function confirmTotp(e: React.FormEvent, verb: "enable" | "disable") {
    e.preventDefault();
    let ok = false;
    await twofa.run(async () => {
      await api(`/me/2fa/${verb}`, { json: { code } });
      ok = true;
    });
    if (ok) {
      setQr(null);
      setCode("");
      await refresh();
    }
  }

  async function acceptRisk() {
    const ok = await risk.run(() => api("/me/accept-risk", { json: { version: RISK_TERMS_VERSION, confirm: true } }));
    if (ok) await refresh();
  }

  async function changePassword(e: React.FormEvent) {
    e.preventDefault();
    let ok = false;
    await pwd.run(async () => {
      await api("/me/password", { json: passwords });
      ok = true;
    });
    if (ok) {
      setPasswords({ current_password: "", new_password: "" });
      setPwdDone(true);
    }
  }

  async function deleteAccount() {
    if (!window.confirm("Excluir sua conta? Suas chaves de corretora serão apagadas e os robôs param. Cancele a assinatura antes. Isso não pode ser desfeito.")) return;
    let ok = false;
    await danger.run(async () => {
      await api("/me", { method: "DELETE" });
      ok = true;
    });
    if (ok) router.replace("/");
  }

  return (
    <>
      <PageHead title="Segurança" lead="Proteja o acesso à sua conta e libere a operação em conta real." />

      <section className="panel" style={{ display: "grid", gap: 14 }}>
        <h2>Verificação em duas etapas</h2>
        {user.totp_enabled ? (
          <>
            <p className="gain">Ativa. Toda entrada pede o código do app autenticador.</p>
            <form className="actions" onSubmit={(e) => confirmTotp(e, "disable")}>
              <input inputMode="numeric" placeholder="Código de 6 dígitos" style={{ maxWidth: 200 }} required value={code} onChange={(e) => setCode(e.target.value)} />
              <button className="btn btn-danger" disabled={twofa.busy}>Desativar</button>
            </form>
          </>
        ) : qr ? (
          <form className="form" onSubmit={(e) => confirmTotp(e, "enable")}>
            <p>Escaneie o código com o app autenticador e digite os 6 dígitos que aparecerem.</p>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img className="qr" src={qr.img} alt="Código QR para o app autenticador" width={200} height={200} />
            <p className="muted small">Sem câmera? Digite esta chave no app: {qr.secret}</p>
            <input inputMode="numeric" autoComplete="one-time-code" placeholder="Código de 6 dígitos" required value={code} onChange={(e) => setCode(e.target.value)} />
            <button className="btn btn-primary" disabled={twofa.busy}>Ativar verificação</button>
          </form>
        ) : (
          <>
            <p className="muted">Obrigatória para operar em conta real e para acessar a administração.</p>
            <div><button className="btn btn-primary" onClick={startTotp} disabled={twofa.busy}>Configurar app autenticador</button></div>
          </>
        )}
        <ErrorText>{twofa.error}</ErrorText>
      </section>

      <section className="panel section" style={{ display: "grid", gap: 14 }}>
        <h2>Termo de ciência de risco</h2>
        {user.risk_terms_accepted_at ? (
          <p className="muted">Aceito em {date(user.risk_terms_accepted_at)}.</p>
        ) : (
          <>
            <div className="muted" style={{ display: "grid", gap: 8, maxWidth: "68ch" }}>
              <p>Antes de operar com dinheiro real, confirme que você entende que:</p>
              <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 4 }}>
                <li>criptoativos são voláteis e você pode perder parte ou todo o valor aplicado;</li>
                <li>os robôs seguem regras que você escolheu e configurou, sem garantia de resultado;</li>
                <li>resultados em simulação ou testnet não se repetem necessariamente na conta real;</li>
                <li>falhas de internet, da corretora ou da plataforma podem atrasar ou impedir ordens;</li>
                <li>a plataforma não é consultoria nem gestão de recursos, e as decisões são suas.</li>
              </ul>
            </div>
            <label className="check">
              <input type="checkbox" checked={riskOk} onChange={(e) => setRiskOk(e.target.checked)} />
              <span>Li e entendi os riscos acima.</span>
            </label>
            <div><button className="btn btn-primary" disabled={!riskOk || risk.busy} onClick={acceptRisk}>Aceitar termo</button></div>
            <ErrorText>{risk.error}</ErrorText>
          </>
        )}
      </section>

      <section className="panel section">
        <form className="form" onSubmit={changePassword}>
          <h2>Trocar senha</h2>
          <label>
            Senha atual
            <input type="password" autoComplete="current-password" required value={passwords.current_password} onChange={(e) => setPasswords({ ...passwords, current_password: e.target.value })} />
          </label>
          <label>
            Nova senha
            <span className="hint">Pelo menos 10 caracteres, com letras e números. Outras sessões serão encerradas.</span>
            <input type="password" autoComplete="new-password" minLength={10} required value={passwords.new_password} onChange={(e) => setPasswords({ ...passwords, new_password: e.target.value })} />
          </label>
          <ErrorText>{pwd.error}</ErrorText>
          {pwdDone && <p className="gain small">Senha trocada.</p>}
          <div><button className="btn" disabled={pwd.busy}>Trocar senha</button></div>
        </form>
      </section>

      <section className="section" style={{ display: "grid", gap: 8 }}>
        <h2>Excluir conta</h2>
        <p className="muted">Apaga seus dados pessoais e as chaves de corretora. Cancele a assinatura antes.</p>
        <div><button className="btn btn-danger" onClick={deleteAccount} disabled={danger.busy}>Excluir minha conta</button></div>
        <ErrorText>{danger.error}</ErrorText>
      </section>
    </>
  );
}
