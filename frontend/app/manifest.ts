import type { MetadataRoute } from "next";
import { BRAND } from "@/lib/brand";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: BRAND,
    short_name: BRAND,
    start_url: "/painel",
    display: "standalone",
    background_color: "#F4F3F9",
    theme_color: "#17133D",
    icons: [
      { src: "/logo/icone-app-192.png", sizes: "192x192", type: "image/png" },
      { src: "/logo/icone-app-512.png", sizes: "512x512", type: "image/png" },
    ],
  };
}
