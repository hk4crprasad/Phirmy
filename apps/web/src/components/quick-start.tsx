"use client";
import { useState } from "react";
import { ArrowRight, Globe, Check, Sparkles, ExternalLink } from "lucide-react";
import { command, Row } from "@/lib/api";
import { StudioContext } from "./ui";

export default function QuickStart({ ctx }: { ctx: StudioContext }) {
  const [url, setUrl] = useState(""),
    [busy, setBusy] = useState(false),
    [preview, setPreview] = useState<Row | null>(null),
    [error, setError] = useState("");
  if (ctx.summary.published_agents > 0) return null;
  return (
    <section className="quick-start">
      <div className="quick-start-copy">
        <span className="eyebrow">
          <Sparkles size={13} /> YOUR FIRST SMALL WIN
        </span>
        <h2>See your website answer back.</h2>
        <p>
          Start with one page. See a real source-backed answer, then keep it as
          your first agent.
        </p>
        <div className="quick-start-steps">
          <span>
            <Check size={13} />
            No instructions to write
          </span>
          <span>
            <Check size={13} />
            You can edit everything
          </span>
        </div>
      </div>
      <div className="quick-start-action">
        {preview ? (
          <div className="quick-answer">
            <strong>{preview.name}</strong>
            <p>{preview.answer?.text}</p>
            {preview.answer?.citations?.[0] && (
              <a
                className="table-action"
                href={preview.answer.citations[0].url}
                target="_blank"
                rel="noreferrer"
              >
                Read the source <ExternalLink size={12} />
              </a>
            )}
            <button
              className="btn primary wide"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setError("");
                try {
                  const saved = await command(ctx.base + "/preview/claim");
                  await ctx.refresh();
                  ctx.go("agents/" + saved.agent_id);
                } catch (e) {
                  setError((e as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy ? "Saving your agent…" : "Keep my agent"}
              <ArrowRight size={15} />
            </button>
          </div>
        ) : (
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setError("");
              try {
                setPreview(await command("/v1/public/preview", { url }));
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <label>
              Your website
              <div className="website-input">
                <Globe size={17} />
                <input
                  required
                  aria-label="Your website"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="your-business.com"
                  maxLength={2000}
                  inputMode="url"
                  autoComplete="url"
                />
              </div>
            </label>
            <button className="btn primary wide" disabled={busy}>
              {busy ? "Reading your page…" : "Try my website"}
              <ArrowRight size={15} />
            </button>
            <p className="small-text muted">
              A source-backed preview from your page. Voice and model settings
              come next.
            </p>
          </form>
        )}
        {error && (
          <div className="error" role="alert">
            {error}
            <p>
              You can also{" "}
              <button className="text-button" onClick={() => ctx.go("agents")}>
                create an agent yourself
              </button>
              .
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
