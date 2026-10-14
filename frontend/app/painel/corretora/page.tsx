"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { ErrorText, Loading, PageHead, VenueTag, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { date } from "@/lib/format";
import type { Credential } from "@/lib/types";
import { BinanceSignup } from "@/components/BinanceSignup";

function BrokerView() {
  const back = useSearchParams().get("ctrader");
  const list = useApi<Credential[]>("/credentials");
  const ct = useApi<{ platform_app: boolean; redirect_uri: string }>("/ctrader/status");
  const action = useAction();
  const ctAction = useAction();
  const [form, setForm] = useState({ label: "", venue: "testnet", api_key: "", api_secret: "" });
  const [ctForm, setCtForm] = useState({ label: "", client_id: "", client_secret: "", access_token: "", refresh_token: "" });
  const [added, setAdded] = useState<string | null>(null);

  async function addBinance(e: React.FormEvent) {
    e.preventDefault();
    const ok = await action.run(() => api("/credentials", { json: form }));
    if (ok) {
      setForm({ label: "", venue: form.venue, api_key: "", api_secret: "" });
      await list.reload();
    }
  }

  async function addCTrader(e: React.FormEvent) {
    e.preventDefault();
    const res = await ctAction.run(() => api<Credential[]>("/ctrader/credentials", { json: ctForm }));
    if (res) {
      setAdded(`${res.length} conta${res.length > 1 ? "s" : ""} conectada${res.length > 1 ? "s" : ""}: ${res.map((c) => c.label).join(", ")}.`);
      setCtForm({ label: "", client_id: "", client_secret: "", access_token: "", refresh_token: "" });
      await list.reload();
    }
  }

  async function loginCTrader() {
    const res = await ctAction.run(() => api<{ url: string }>("/ctrader/connect"));
    if (res?.url) window.location.href = res.url;
  }

  async function remove(c: Credential) {
    if (!window.confirm(`Remover "${c.label}"? Os robôs que usam esta conexão vão parar.`)) return;
    await action.run(() => api(`/credentials/${c.id}`, { method: "DELETE" }));
    await list.reload();
  }

  const setCt = (k: keyof typeof ctForm) => (e: React.ChangeEvent<HTMLInputElement>) => setCtForm({ ...ctForm, [k]: e.target.value });

  return (
    <>
      <PageHead title="Corretora" lead="Cada conexão usa as suas próprias credenciais. Elas ficam cifradas e os segredos nunca voltam para a tela." />

      {back === "ok" && <p className="notice small" style={{ marginBottom: 16 }}><strong>Conta cTrader conectada</strong>Ela já aparece na lista e pode ser usada nos robôs de forex.</p>}
      {back === "erro" && <p className="notice notice-danger small" style={{ marginBottom: 16 }}><strong>Não foi possível conectar ao cTrader</strong>Tente de novo ou use as credenciais do seu próprio app.</p>}

      <section>
        <h2 style={{ marginBottom: 12 }}>Conexões</h2>
        {list.loading && !list.data && <Loading />}
        {list.data && list.data.length === 0 && <div className="panel empty">Nenhuma conexão ainda. A simulação de cripto funciona sem chave.</div>}
        {!!list.data?.length && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Nome</th>
                  <th>Corretora</th>
                  <th>Ambiente</th>
                  <th>Identificação</th>
                  <th>Permissão</th>
                  <th>Conectada em</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {list.data.map((c) => (
                  <tr key={c.id}>
                    <td>{c.label}</td>
                    <td>{c.exchange === "ctrader" ? `cTrader${c.broker_name ? ` (${c.broker_name})` : ""}` : "Binance"}</td>
                    <td><VenueTag venue={c.venue} market={c.exchange === "ctrader" ? "forex" : "crypto"} /></td>
                    <td>{c.exchange === "ctrader" ? `conta ${c.external_account_id}` : `chave …${c.key_last4}`}</td>
                    <td>
                      {c.can_trade ? "Negociação" : <span className="loss">Só leitura</span>}
                      {c.exchange === "binance" && c.venue === "live" && !c.ip_restricted && <div className="loss small">sem restrição de IP</div>}
                    </td>
                    <td>{date(c.verified_at)}</td>
                    <td className="num">
                      <button className="btn btn-quiet" onClick={() => remove(c)}>Remover</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <ErrorText>{action.error}</ErrorText>
      </section>

      <section className="section">
        <h2 style={{ marginBottom: 6 }}>Forex com cTrader</h2>
        <p className="muted" style={{ marginBottom: 16 }}>
          Funciona com qualquer corretora que ofereça cTrader. Cada conta demo e real liberada pelo token vira uma conexão.
        </p>

        {ct.data?.platform_app && (
          <div className="panel" style={{ display: "grid", gap: 10, marginBottom: 16, maxWidth: 560 }}>
            <strong>Jeito rápido</strong>
            <p className="muted small">Você entra no cTrader, escolhe as contas e autoriza. Nenhuma chave para copiar.</p>
            <div><button className="btn btn-primary" onClick={loginCTrader} disabled={ctAction.busy}>Conectar com cTrader</button></div>
          </div>
        )}

        <form className="form panel" onSubmit={addCTrader}>
          <strong>{ct.data?.platform_app ? "Ou use o seu próprio app" : "Credenciais do seu app no cTrader"}</strong>
          <ol className="muted small" style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 4 }}>
            <li>Entre em <a href="https://openapi.ctrader.com/apps" target="_blank" rel="noopener">openapi.ctrader.com/apps</a> com o seu cTrader ID e crie um app (a aprovação pode levar alguns dias).</li>
            <li>Copie o <strong>Client ID</strong> e o <strong>Client Secret</strong> do app.</li>
            <li>No mesmo portal, abra o <strong>Playground</strong> do app, autorize com escopo <strong>trading</strong> marcando as contas desejadas e copie o <strong>Access Token</strong> e o <strong>Refresh Token</strong>.</li>
          </ol>
          <label>
            Nome para identificar
            <input required maxLength={60} placeholder="Minha corretora" value={ctForm.label} onChange={setCt("label")} />
          </label>
          <div className="grid-2">
            <label>
              Client ID
              <input required autoComplete="off" spellCheck={false} value={ctForm.client_id} onChange={setCt("client_id")} />
            </label>
            <label>
              Client Secret
              <input required type="password" autoComplete="off" spellCheck={false} value={ctForm.client_secret} onChange={setCt("client_secret")} />
            </label>
            <label>
              Access Token
              <input required type="password" autoComplete="off" spellCheck={false} value={ctForm.access_token} onChange={setCt("access_token")} />
            </label>
            <label>
              Refresh Token
              <input required type="password" autoComplete="off" spellCheck={false} value={ctForm.refresh_token} onChange={setCt("refresh_token")} />
            </label>
          </div>
          <p className="muted small">O Access Token vence em cerca de 30 dias; a plataforma renova sozinha com o Refresh Token.</p>
          <ErrorText>{ctAction.error}</ErrorText>
          {added && <p className="gain small">{added}</p>}
          <div><button className="btn btn-primary" disabled={ctAction.busy}>{ctAction.busy ? "Verificando no cTrader…" : "Verificar e conectar"}</button></div>
        </form>
      </section>

      <section className="section">
        <h2 style={{ marginBottom: 12 }}>Cripto com Binance</h2>
        {!list.data?.some((c) => c.exchange === "binance") && (
          <div style={{ marginBottom: 16, maxWidth: 560 }}>
            <BinanceSignup />
          </div>
        )}
        <form className="form panel" onSubmit={addBinance}>
          <div className="choice">
            <label>
              <input type="radio" name="venue" checked={form.venue === "testnet"} onChange={() => setForm({ ...form, venue: "testnet" })} />
              Testnet
              <span className="hint">Chave criada em testnet.binance.vision</span>
            </label>
            <label>
              <input type="radio" name="venue" checked={form.venue === "live"} onChange={() => setForm({ ...form, venue: "live" })} />
              Conta real
              <span className="hint">Chave criada em binance.com</span>
            </label>
          </div>
          {form.venue === "live" && (
            <div className="notice small">
              <strong>Como criar a chave com segurança</strong>
              Na Binance, em Gerenciamento de API, habilite somente leitura e negociação Spot. Deixe o saque desligado (chaves com saque são recusadas) e restrinja o acesso ao IP do servidor da plataforma.
            </div>
          )}
          <label>
            Nome para identificar
            <input required maxLength={80} placeholder="Minha conta principal" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} />
          </label>
          <label>
            API Key
            <input required autoComplete="off" spellCheck={false} value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })} />
          </label>
          <label>
            Secret Key
            <input required type="password" autoComplete="off" spellCheck={false} value={form.api_secret} onChange={(e) => setForm({ ...form, api_secret: e.target.value })} />
          </label>
          <ErrorText>{action.error}</ErrorText>
          <div><button className="btn btn-primary" disabled={action.busy}>{action.busy ? "Verificando na Binance…" : "Verificar e conectar"}</button></div>
        </form>
      </section>
    </>
  );
}

export default function BrokerPage() {
  return (
    <Suspense>
      <BrokerView />
    </Suspense>
  );
}
