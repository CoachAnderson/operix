import { BRAND } from "@/lib/brand";

/** Logo da plataforma. Com o nome padrão usa o logo completo (nome em curvas); com outro nome, símbolo + texto. */
export function Logo({ height = 28, suffix }: { height?: number; suffix?: string }) {
  const official = BRAND === "OráculoInvest";
  return (
    <span className="logo">
      {/* Duas versões; o CSS mostra a certa para o tema efetivo (aparelho ou escolha em Aparência). */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        className="logo-light"
        src={official ? "/logo/oraculoinvest-logo.svg" : "/logo/oraculoinvest-simbolo.svg"}
        alt={official ? BRAND : ""}
        style={{ height, width: "auto", display: "block" }}
      />
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        className="logo-dark"
        src={official ? "/logo/oraculoinvest-logo-branco.svg" : "/logo/oraculoinvest-simbolo-branco.svg"}
        alt={official ? BRAND : ""}
        style={{ height, width: "auto" }}
      />
      {!official && <span>{BRAND}</span>}
      {suffix && <span className="logo-suffix">{suffix}</span>}
    </span>
  );
}
