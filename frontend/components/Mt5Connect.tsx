"use client";

import { useEffect, useState } from "react";
import { ErrorText, VenueTag, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { Credential, Mt5Status } from "@/lib/types";

export const CONNECTOR_ZIP = "/downloads/conector-oraculoinvest-mt5.zip";

function CopyField({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* sem permissão de área de transferência: o campo continua selecionável */
    }
  }
  return (
    <div className="mt5-token">
      <input readOnly value={value} onFocus={(e) => e.target.select()} aria-label="Token do conector" spellCheck={false} />
      <button type="button" className="btn" onClick={copy}>
        {copied ? "Copiado" : "Copiar"}
      </button>
    </div>
  );
}

/** Seção "Futuros da B3 com MetaTrader 5" da tela Corretora. */
export function Mt5Connect({ creds, onChange }: { creds: Credential[]; onChange: () => void }) {
  const status = useApi<Mt5Status[]>("/mt5/status");
  const action = useAction();
  const [form, setForm] = useState({ label: "", venue: "testnet" });
  const [token, setToken] = useState<{ label: string; value: string } | null>(null);

  // Atualiza o estado do conector a cada 8 s enquanto a tela está aberta.
  const reloadStatus = status.reload;
  useEffect(() => {
    const t = setInterval(() => void reloadStatus(), 8000);
    return () => clearInterval(t);
  }, [reloadStatus]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    const res = await action.run(() => api<{ credential: Credential; token: string }>("/mt5/connections", { json: form }));
    if (res) {
      setToken({ label: res.credential.label, value: res.token });
      setForm({ label: "", venue: form.venue });
      onChange();
      void status.reload();
    }
  }

  async function rotate(c: Credential) {
    if (!window.confirm(`Gerar um token novo para "${c.label}"? O conector que usa o token atual para na hora.`)) return;
    const res = await action.run(() => api<{ credential: Credential; token: string }>(`/mt5/connections/${c.id}/token`, { method: "POST" }));
    if (res) setToken({ label: c.label, value: res.token });
  }

  const mt5 = creds.filter((c) => c.exchange === "mt5");
  const byId = new Map(status.data?.map((s) => [s.credential_id, s]) ?? []);

  return (
    <section className="section">
      <h2 style={{ marginBottom: 6 }}>Futuros da B3 com MetaTrader 5</h2>
      <p className="muted" style={{ marginBottom: 16, maxWidth: "75ch" }}>
        Mini-índice (WIN) e mini-dólar (WDO) pela sua corretora (XP, Clear, Rico, Genial e outras que oferecem MetaTrader 5). Um pequeno programa, o
        Conector OráculoInvest, roda no seu computador ou VPS Windows ao lado do MetaTrader 5. Seu login e sua senha da corretora ficam só lá.
      </p>

      {token && (
        <div className="notice" style={{ marginBottom: 16, display: "grid", gap: 10 }} role="status">
          <strong>Token do conector &quot;{token.label}&quot;</strong>
          <span>Copie agora e cole no arquivo conector.ini. Ele não aparece de novo; se perder, gere outro.</span>
          <CopyField value={token.value} />
          <div className="actions">
            <a className="btn btn-primary" href={CONNECTOR_ZIP} download>
              Baixar o conector (Windows)
            </a>
            <button type="button" className="btn btn-quiet" onClick={() => setToken(null)}>
              Já copiei
            </button>
          </div>
        </div>
      )}

      {mt5.length > 0 && (
        <div className="mt5-list">
          {mt5.map((c) => {
            const st = byId.get(c.id);
            const online = !!st?.online;
            const algo = st?.terminal?.trade_allowed;
            return (
              <div key={c.id} className="mt5-card">
                <div className="mt5-head">
                  <span className={`mt5-dot ${online ? "on" : ""}`} aria-hidden="true" />
                  <strong>{c.label}</strong>
                  <VenueTag venue={c.venue} market="b3" />
                </div>
                <dl className="mt5-facts">
                  <div>
                    <dt>Conector</dt>
                    <dd className={online ? "gain" : "loss"}>{online ? "Online" : st?.last_seen ? `Offline desde ${dateTime(st.last_seen)}` : "Ainda não conectou"}</dd>
                  </div>
                  <div>
                    <dt>Conta</dt>
                    <dd>{st?.account ? `${st.account.login} · ${st.account.company || st.account.server}` : c.external_account_id ? `conta ${c.external_account_id}` : "—"}</dd>
                  </div>
                  <div>
                    <dt>Algo Trading no MT5</dt>
                    <dd className={online ? (algo ? "gain" : "loss") : ""}>{online ? (algo ? "Ligado" : "Desligado: ligue o botão no MetaTrader 5") : "—"}</dd>
                  </div>
                  <div>
                    <dt>Travas do conector</dt>
                    <dd>{st?.limits ? `${st.limits.roots.join(", ")} · até ${st.limits.max_contracts} contrato(s)` : "—"}</dd>
                  </div>
                </dl>
                <div className="actions">
                  <button type="button" className="btn btn-quiet" onClick={() => rotate(c)} disabled={action.busy}>
                    Gerar novo token
                  </button>
                  <a className="btn btn-quiet" href={CONNECTOR_ZIP} download>
                    Baixar o conector
                  </a>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <form className="form panel" onSubmit={create} style={{ marginTop: mt5.length ? 16 : 0 }}>
        <strong>Nova conexão</strong>
        <ol className="muted small" style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 4 }}>
          <li>Instale o MetaTrader 5 da sua corretora, entre na conta e ligue o botão <strong>Algo Trading</strong>.</li>
          <li>Crie a conexão aqui e copie o token.</li>
          <li>Baixe o conector, abra o <strong>iniciar.bat</strong>, cole o token no conector.ini e rode de novo. A conexão fica verde.</li>
        </ol>
        <div className="choice">
          <label>
            <input type="radio" name="mt5venue" checked={form.venue === "testnet"} onChange={() => setForm({ ...form, venue: "testnet" })} />
            Conta demo
            <span className="hint">Comece por aqui. O servidor recusa o conector se o MT5 estiver numa conta real.</span>
          </label>
          <label>
            <input type="radio" name="mt5venue" checked={form.venue === "live"} onChange={() => setForm({ ...form, venue: "live" })} />
            Conta real
            <span className="hint">Ordens com dinheiro de verdade na sua conta da B3.</span>
          </label>
        </div>
        <label>
          Nome para identificar
          <input required maxLength={80} placeholder="XP demo" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} />
        </label>
        <ErrorText>{action.error}</ErrorText>
        <div>
          <button className="btn btn-primary" disabled={action.busy}>
            {action.busy ? "Criando…" : "Criar conexão e gerar token"}
          </button>
        </div>
      </form>
    </section>
  );
}
