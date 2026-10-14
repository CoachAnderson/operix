"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Signal, User } from "@/lib/types";
import { BRAND } from "@/lib/brand";
import { Logo } from "@/components/Logo";

const UserContext = createContext<{ user: User; refresh: () => Promise<void> } | null>(null);

export function useUser() {
  const ctx = useContext(UserContext);
  if (!ctx) throw new Error("useUser fora do AppShell");
  return ctx;
}

type NavItem = { href: string; label: string; count?: number };

export function AppShell({ area, children }: { area: "painel" | "admin"; children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [pending, setPending] = useState(0);

  async function refresh() {
    try {
      setUser(await api<User>("/me"));
    } catch {
      router.replace(`/entrar?voltar=${encodeURIComponent(pathname)}`);
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (area !== "painel" || !user) return;
    const load = () => api<Signal[]>("/signals?status=pending").then((s) => setPending(s.length)).catch(() => {});
    load();
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, [area, user]);

  if (!user) return <div className="auth"><p className="muted">Carregando…</p></div>;

  if (area === "admin" && user.role !== "admin") {
    router.replace("/painel");
    return null;
  }
  if (area === "admin" && !user.totp_enabled) {
    return (
      <div className="auth">
        <div className="panel notice">
          <strong>Ative a verificação em duas etapas</strong>
          O painel administrativo só abre com 2FA ativo. <Link href="/painel/seguranca">Configurar agora</Link>
        </div>
      </div>
    );
  }

  const items: NavItem[] =
    area === "painel"
      ? [
          { href: "/painel", label: "Robôs" },
          { href: "/painel/sinais", label: "Sinais", count: pending },
          { href: "/painel/backtest", label: "Backtest" },
          { href: "/painel/ordens", label: "Ordens" },
          { href: "/painel/corretora", label: "Corretora" },
          { href: "/painel/assinatura", label: "Assinatura" },
          { href: "/painel/seguranca", label: "Segurança" },
        ]
      : [
          { href: "/admin", label: "Visão geral" },
          { href: "/admin/usuarios", label: "Usuários" },
          { href: "/admin/assinaturas", label: "Assinaturas" },
          { href: "/admin/planos", label: "Planos" },
          { href: "/admin/robos", label: "Robôs" },
          { href: "/admin/auditoria", label: "Auditoria" },
        ];

  const isCurrent = (href: string) => (href === `/${area}` ? pathname === href : pathname.startsWith(href));

  async function logout() {
    await api("/auth/logout", { method: "POST" }).catch(() => {});
    router.replace("/entrar");
  }

  return (
    <UserContext.Provider value={{ user, refresh }}>
      <div className="shell">
        <aside className="sidebar">
          <Link href={`/${area}`} className="brand" aria-label={`${BRAND}${area === "admin" ? ", administração" : ", início"}`}>
            <Logo height={26} suffix={area === "admin" ? "admin" : undefined} />
          </Link>
          <nav className="nav" aria-label="Navegação principal">
            {items.map((i) => (
              <Link key={i.href} href={i.href} aria-current={isCurrent(i.href) ? "page" : undefined}>
                {i.label}
                {!!i.count && <span className="count" aria-label={`${i.count} pendentes`}>{i.count}</span>}
              </Link>
            ))}
          </nav>
          <div className="sidebar-foot">
            <span>{user.name}</span>
            {user.role === "admin" && (
              <Link href={area === "admin" ? "/painel" : "/admin"}>{area === "admin" ? "Ir para meu painel" : "Painel admin"}</Link>
            )}
            <button className="btn btn-quiet" style={{ justifyContent: "flex-start", padding: 0 }} onClick={logout}>
              Sair
            </button>
          </div>
        </aside>
        <main className="main">{children}</main>
      </div>
    </UserContext.Provider>
  );
}
