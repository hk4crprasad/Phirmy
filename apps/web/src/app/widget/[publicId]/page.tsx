import WidgetChat from "@/components/widget-chat";
import PublicVoice from "@/components/public-voice";
export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ publicId: string }>;
  searchParams: Promise<{ mode?: string; public_key?: string }>;
}) {
  const { publicId } = await params;
  if ((await searchParams).mode === "voice")
    return (
      <main className="voice-embed-page">
        <PublicVoice publicId={publicId} />
      </main>
    );
  return (
    <main style={{ maxWidth: 460, margin: "20px auto", padding: 16 }}>
      <section className="panel">
        <div className="panel-header">
          <h2>How can we help?</h2>
          <span className="badge">AI assistant</span>
        </div>
        <WidgetChat
          publicId={publicId}
          publicKey={(await searchParams).public_key || ""}
        />
      </section>
    </main>
  );
}
