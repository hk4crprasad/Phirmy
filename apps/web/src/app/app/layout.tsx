import Studio from "@/components/studio";
export default function WorkspaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <Studio>{children}</Studio>;
}
