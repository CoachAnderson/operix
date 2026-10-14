import { AppShell } from "@/components/AppShell";

export default function PainelLayout({ children }: { children: React.ReactNode }) {
  return <AppShell area="painel">{children}</AppShell>;
}
