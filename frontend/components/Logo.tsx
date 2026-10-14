import { BRAND } from "@/lib/brand";

/** Logo da plataforma. Com o nome padrão usa o logo completo (nome em curvas); com outro nome, símbolo + texto. */
export function Logo({ height = 28, suffix }: { height?: number; suffix?: string }) {
  const official = BRAND === "OráculoInvest";
  return (
    <span className="logo">
      <picture>
        <source
          srcSet={official ? "/logo/oraculoinvest-logo-branco.svg" : "/logo/oraculoinvest-simbolo-branco.svg"}
          media="(prefers-color-scheme: dark)"
        />
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={official ? "/logo/oraculoinvest-logo.svg" : "/logo/oraculoinvest-simbolo.svg"}
          alt={official ? BRAND : ""}
          style={{ height, width: "auto", display: "block" }}
        />
      </picture>
      {!official && <span>{BRAND}</span>}
      {suffix && <span className="logo-suffix">{suffix}</span>}
    </span>
  );
}
