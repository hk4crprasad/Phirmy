import { notFound } from "next/navigation";
import { isWorkspaceRoute } from "@/lib/workspace-routes";
export default async function Page({
  params,
}: {
  params: Promise<{ section?: string[] }>;
}) {
  if (!isWorkspaceRoute((await params).section || [])) notFound();
  return null;
}
