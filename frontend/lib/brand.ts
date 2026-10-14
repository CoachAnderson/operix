/** Nome da plataforma. Troque em um lugar só: variável NEXT_PUBLIC_BRAND_NAME no build (padrão provisório). */
export const BRAND = process.env.NEXT_PUBLIC_BRAND_NAME || "OráculoInvest";

/** Link de indicação da Binance mostrado a quem ainda não tem conta. Troque por NEXT_PUBLIC_BINANCE_REF_URL no build; vazio esconde o convite. */
export const BINANCE_REF_URL = process.env.NEXT_PUBLIC_BINANCE_REF_URL ?? "https://www.binance.com/register?ref=65851965";
