"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ErrorText, useAction } from "@/components/ui";
import { api } from "@/lib/api";
import { Logo } from "@/components/Logo";

export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = useState({ name: "", email: "", password: "", accept_terms: false });
  const { busy, error, run } = useAction();
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const ok = await run(() => api("/auth/register", { json: form }));
    if (ok !== undefined) router.replace("/painel/assinatura");
  }

  return (
    <div className="auth">
      <form className="panel" onSubmit={submit}>
        <Logo height={30} />
        <h1>Criar conta</h1>
        <label>
          Nome
          <input autoComplete="name" required minLength={2} value={form.name} onChange={set("name")} />
        </label>
        <label>
          E-mail
          <input type="email" autoComplete="email" required value={form.email} onChange={set("email")} />
        </label>
        <label>
          Senha
          <span className="hint">Pelo menos 10 caracteres, com letras e números.</span>
          <input type="password" autoComplete="new-password" required minLength={10} value={form.password} onChange={set("password")} />
        </label>
        <label className="check">
          <input type="checkbox" required checked={form.accept_terms} onChange={set("accept_terms")} />
          <span>
            Li e aceito os <a href="/termos" target="_blank">termos de uso</a> e a{" "}
            <a href="/privacidade" target="_blank">política de privacidade</a>.
          </span>
        </label>
        <ErrorText>{error}</ErrorText>
        <button className="btn btn-primary" disabled={busy}>
          {busy ? "Criando conta…" : "Criar conta"}
        </button>
        <p className="muted small">
          Já tem conta? <Link href="/entrar">Entrar</Link>
        </p>
      </form>
    </div>
  );
}
