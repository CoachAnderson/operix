"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Logo } from "@/components/Logo";
import { ThemeToggle } from "@/components/Appearance";

export function LearnHeader() {
  const path = usePathname();
  const [logged, setLogged] = useState(false);
  useEffect(() => {
    // O cookie csrf_token só existe com sessão aberta (o de sessão é httpOnly e não aparece aqui).
    setLogged(/(?:^|; )csrf_token=/.test(document.cookie));
  }, []);
  return (
    <header className="learn-top">
      <Link href="/" className="brand" aria-label="Página inicial">
        <Logo height={30} />
      </Link>
      <nav className="learn-nav" aria-label="Aprender">
        <Link href="/aprender" aria-current={path === "/aprender" ? "page" : undefined}>
          Aulas
        </Link>
        <Link href="/aprender/glossario" aria-current={path === "/aprender/glossario" ? "page" : undefined}>
          Glossário
        </Link>
      </nav>
      <div className="actions">
        <ThemeToggle compact />
        {logged ? (
          <Link className="btn" href="/painel">
            Ir para o painel
          </Link>
        ) : (
          <>
            <Link className="btn btn-quiet" href="/entrar">
              Entrar
            </Link>
            <Link className="btn btn-primary" href="/cadastro">
              Criar conta
            </Link>
          </>
        )}
      </div>
    </header>
  );
}
