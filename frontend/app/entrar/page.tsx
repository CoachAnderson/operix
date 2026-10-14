"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { ErrorText, useAction } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { User } from "@/lib/types";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [needsCode, setNeedsCode] = useState(false);
  const { busy, error, setError } = useAction();
  const [submitting, setSubmitting] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const user = await api<User>("/auth/login", { json: { email, password, totp_code: needsCode ? code : undefined } });
      const back = params.get("voltar");
      router.replace(back && back.startsWith("/") && !back.startsWith("//") ? back : user.role === "admin" ? "/admin" : "/painel");
    } catch (err) {
      if (err instanceof ApiError) {
        const detail = (err.data as { detail?: { totp_required?: boolean } })?.detail;
        if (detail && typeof detail === "object" && detail.totp_required) {
          setNeedsCode(true);
          setError(null);
        } else setError(err.message);
      } else setError("Falha de conexão");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="panel" onSubmit={submit}>
      <h1>Entrar</h1>
      {!needsCode ? (
        <>
          <label>
            E-mail
            <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label>
            Senha
            <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
        </>
      ) : (
        <label>
          Código do app autenticador
          <span className="hint">Abra o app (Google Authenticator, Authy etc.) e digite os 6 dígitos.</span>
          <input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]{6,7}" required autoFocus value={code} onChange={(e) => setCode(e.target.value)} />
        </label>
      )}
      <ErrorText>{error}</ErrorText>
      <button className="btn btn-primary" disabled={busy || submitting}>
        {submitting ? "Entrando…" : "Entrar"}
      </button>
      <p className="muted small">
        Ainda não tem conta? <Link href="/cadastro">Criar conta</Link>
      </p>
    </form>
  );
}

export default function LoginPage() {
  return (
    <div className="auth">
      <Suspense>
        <LoginForm />
      </Suspense>
    </div>
  );
}
