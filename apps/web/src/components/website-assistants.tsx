"use client";
import { useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  Check,
  Copy,
  Globe,
  LoaderCircle,
  RefreshCw,
  Settings2,
  Square,
} from "lucide-react";
import { api, command, Row, when } from "@/lib/api";
import { StudioContext, Header, Panel, Badge } from "./ui";
import WidgetChat from "./widget-chat";
import WidgetCustomizer from "./widget-customizer";

export function embedSnippet(origin: string, installation: Row) {
  return `<script defer src="${origin}/widget.js" data-widget-id="${installation.public_id}" data-public-key="${installation.theme?.publishable_key || ""}"></script>`;
}

export default function WebsiteAssistants({
  ctx,
  agentId,
}: {
  ctx: StudioContext;
  agentId?: string;
}) {
  const [editingWidget, setEditingWidget] = useState<Row | null>(null);
  const [legacyTest, setLegacyTest] = useState("");
  const [targetAgent, setTargetAgent] = useState(agentId || "");
  const [rows, setRows] = useState<Row[]>([]),
    [selected, setSelected] = useState(""),
    [url, setUrl] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [tab, setTab] = useState("install"),
    [pages, setPages] = useState<Row[]>([]),
    [platform, setPlatform] = useState("html");
  const seen = useRef(new Set<string>());
  const row = rows.find((x) => x.id === selected) || rows[0];
  const load = async () => {
    const result = await api(ctx.base + "/website-assistants");
    const items = (result.items || []).filter(
      (x: Row) => !agentId || x.agent_id === agentId,
    );
    setRows(items);
    for (const item of items)
      if (
        item.knowledge?.active_snapshot_id &&
        !seen.current.has(item.knowledge.active_snapshot_id)
      ) {
        seen.current.add(item.knowledge.active_snapshot_id);
        await ctx.refresh();
      }
  };
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      if (!active) return;
      if (!document.hidden) {
        try {
          await load();
        } catch (e) {
          if (active) setError((e as Error).message);
        }
      }
      if (active) timer = setTimeout(refresh, 4000);
    };
    refresh();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [ctx.base, agentId]);
  useEffect(() => {
    if (row)
      api(ctx.base + "/website-assistants/" + row.id + "/pages")
        .then((x) => setPages(x.items))
        .catch((e) => setError(e.message));
  }, [row?.id, row?.knowledge?.active_snapshot_id, ctx.base]);
  async function perform(action: () => Promise<any>, notice: string) {
    setBusy(true);
    setError("");
    try {
      await action();
      await load();
      ctx.notify(notice);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function appearance(installation: Row = row.installation) {
    setEditingWidget(installation);
  }

  function crawlSettings() {
    ctx.form({
      title: "Website updates",
      description:
        "Crawls respect robots.txt, domain boundaries and rate limits. Large or blocked websites can have incomplete coverage.",
      fields: [
        {
          key: "max_pages",
          label: "Page limit per crawl",
          type: "number",
          min: 1,
          max: 1000,
          value: row.options.max_pages,
          required: true,
        },
        {
          key: "refresh_hours",
          label: "Refresh interval in hours · 0 pauses automatic updates",
          type: "number",
          min: 0,
          max: 720,
          value: row.options.refresh_hours,
          required: true,
        },
        {
          key: "render_js",
          label: "Render JavaScript when static text is insufficient",
          type: "checkbox",
          value: row.options.render_js,
        },
      ],
      action: async (values) => {
        await command(
          ctx.base + "/website-assistants/" + row.id + "/options",
          { ...row.options, ...values },
          "PUT",
        );
        await load();
        ctx.notify("Update schedule saved");
      },
    });
  }
  let snippet = row
    ? embedSnippet(
        typeof window === "undefined" ? "" : window.location.origin,
        row.installation,
      )
    : "";
  if (platform === "wordpress")
    snippet =
      "<!-- WordPress: add in a Custom HTML block or your footer scripts plugin. -->\n" +
      snippet;
  if (platform === "shopify")
    snippet =
      "<!-- Shopify: Online Store → Themes → Edit code → layout/theme.liquid, before </body>. -->\n" +
      snippet;
  if (platform === "gtm")
    snippet =
      "<!-- Google Tag Manager: Custom HTML tag, All Pages trigger. -->\n" +
      snippet;
  return (
    <>
      {editingWidget && (
        <WidgetCustomizer
          ctx={ctx}
          installation={editingWidget}
          close={() => setEditingWidget(null)}
          saved={load}
        />
      )}
      <Header
        eyebrow="YOUR WEBSITE, READY TO HELP"
        title={
          agentId
            ? "Website knowledge & widget"
            : "Turn your website into an assistant."
        }
        description="Connect your public pages, test real answers, then add one script to your website."
      />
      <section className="website-start panel">
        <div>
          <Globe size={22} />
          <h2>
            {rows.length
              ? "Connect another website"
              : "Start with your website"}
          </h2>
          <p className="muted small-text">
            Pages, products, services and policies connect automatically. You
            can keep working while we crawl.
          </p>
        </div>
        <form
          className="website-create-form"
          onSubmit={(e) => {
            e.preventDefault();
            perform(async () => {
              const created = await command(ctx.base + "/website-assistants", {
                website_url: url,
                name: new URL(url).hostname + " assistant",
                ...(targetAgent ? { agent_id: targetAgent } : {}),
              });
              setSelected(created.id);
              setUrl("");
            }, "Website crawl started");
          }}
        >
          {!agentId && (
            <label>
              Connect to
              <select
                aria-label="Website agent"
                value={targetAgent}
                onChange={(e) => setTargetAgent(e.target.value)}
              >
                <option value="">Create a new agent</option>
                {(ctx.data.agents || []).map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label>
            Website URL
            <input
              aria-label="Assistant website URL"
              type="url"
              placeholder="https://your-business.com"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              required
              maxLength={2000}
            />
          </label>
          <button className="btn primary" disabled={busy}>
            {busy ? (
              <LoaderCircle size={15} className="spin" />
            ) : (
              <ArrowUpRight size={15} />
            )}{" "}
            Create website assistant
          </button>
        </form>
      </section>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {row && (
        <>
          <div className="website-toolbar">
            <label>
              Website assistant
              <select
                aria-label="Website assistant"
                value={row.id}
                onChange={(e) => setSelected(e.target.value)}
              >
                {rows.map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.knowledge.website_url}
                  </option>
                ))}
              </select>
            </label>
            <button className="btn" onClick={() => appearance()}>
              <Settings2 size={14} /> Customize widget
            </button>
            <button className="btn" onClick={crawlSettings}>
              Updates
            </button>
            <button
              className="btn"
              disabled={busy || ["queued", "running"].includes(row.job?.state)}
              onClick={() =>
                perform(
                  () =>
                    command(
                      ctx.base + "/website-assistants/" + row.id + "/recrawl",
                    ),
                  "Recrawl queued",
                )
              }
            >
              <RefreshCw size={14} /> Recrawl
            </button>
            {["queued", "running"].includes(row.job?.state) && (
              <button
                className="btn"
                disabled={busy || row.job.cancel_requested}
                onClick={() =>
                  perform(
                    () => command(ctx.base + "/jobs/" + row.job.id + "/cancel"),
                    "Stopping crawl; previously published knowledge stays connected",
                  )
                }
              >
                <Square size={14} />{" "}
                {row.job.cancel_requested ? "Stopping…" : "Stop crawl"}
              </button>
            )}
          </div>
          <div className="website-progress panel" aria-live="polite">
            <div className="row between">
              <strong>
                {row.knowledge.status === "ready"
                  ? "Your website knowledge is connected"
                  : row.job?.state === "canceled"
                    ? "Crawl stopped"
                    : row.job?.cancel_requested
                      ? "Stopping crawl…"
                      : "Preparing your website knowledge"}
              </strong>
              <Badge value={row.job?.state || row.knowledge.status} />
            </div>
            <div className="website-steps">
              {[
                "Discover public pages",
                "Extract business facts",
                "Index knowledge",
                "Connect agent & widget",
              ].map((label, i) => (
                <span key={label}>
                  {row.knowledge.status === "ready" ? (
                    <Check size={13} />
                  ) : (
                    <span>{i + 1}</span>
                  )}
                  {label}
                </span>
              ))}
            </div>
            <p className="muted small-text">
              {row.job?.completed_items || 0} pages collected ·{" "}
              {row.knowledge.chunks_indexed} searchable passages ·{" "}
              {row.job?.phase?.replaceAll("_", " ")} · limit{" "}
              {row.options.max_pages} pages
            </p>
            <p className="muted small-text">
              {row.usage?.conversations || 0} conversations ·{" "}
              {row.usage?.visitor_turns || 0} visitor turns
            </p>
            {row.job?.error && <p className="error">{row.job.error}</p>}
            {row.job?.result?.remaining_urls > 0 && (
              <p className="notice">
                More pages were discovered than the crawl limit. Increase the
                page limit and recrawl for wider coverage.
              </p>
            )}
            {row.job?.result?.failures?.length > 0 && (
              <details>
                <summary>
                  {row.job.result.failures.length} crawl notices
                </summary>
                {row.job.result.failures.map((f: Row, i: number) => (
                  <p key={i} className="small-text">
                    {f.url}: {f.reason}
                  </p>
                ))}
              </details>
            )}
          </div>
          <div className="tabs">
            {["install", "test", "pages"].map((x) => (
              <button
                key={x}
                onClick={() => setTab(x)}
                className={"tab " + (tab === x ? "active" : "")}
              >
                {x === "install"
                  ? "Install widget"
                  : x === "test"
                    ? "Test agent"
                    : "Indexed pages"}
              </button>
            ))}
          </div>
          {tab === "install" && (
            <div className="website-install split">
              <Panel title="Add your assistant to your website">
                <div className="panel-body stack">
                  <label>
                    Website platform
                    <select
                      aria-label="Website platform"
                      value={platform}
                      onChange={(e) => setPlatform(e.target.value)}
                    >
                      <option value="html">HTML / any website</option>
                      <option value="wordpress">WordPress</option>
                      <option value="shopify">Shopify</option>
                      <option value="gtm">Google Tag Manager</option>
                    </select>
                  </label>
                  <p className="small-text muted">
                    Paste this before the closing &lt;/body&gt; tag on every
                    page. Your widget ID and publishable key identify this
                    assistant; private provider keys stay on the server.
                  </p>
                  <pre className="code mono website-code">{snippet}</pre>
                  <button
                    className="btn"
                    onClick={() =>
                      navigator.clipboard
                        .writeText(snippet)
                        .then(() => ctx.notify("Installation snippet copied"))
                        .catch(() =>
                          ctx.notify("Select the snippet to copy it."),
                        )
                    }
                  >
                    <Copy size={14} /> Copy installation snippet
                  </button>
                  <p className="field-note">
                    Allowed origins:{" "}
                    {row.installation.allowed_origins.join(", ")}. Use Customize
                    widget to add an exact domain. Publishable keys work only
                    with these origins.
                  </p>
                  <button
                    className="btn subtle small"
                    onClick={() =>
                      perform(
                        () =>
                          command(
                            ctx.base +
                              "/website-assistants/" +
                              row.id +
                              "/rotate-key",
                          ),
                        "Key rotated. Replace your installed snippet.",
                      )
                    }
                  >
                    Rotate publishable key
                  </button>
                </div>
              </Panel>
              <Panel title="Everything stays connected">
                <div className="panel-body stack">
                  <button
                    className="btn"
                    onClick={() => ctx.go("agents/" + row.agent_id)}
                  >
                    Agent instructions & actions <ArrowUpRight size={13} />
                  </button>
                  <button className="btn" onClick={() => ctx.go("inbox")}>
                    Conversation history
                  </button>
                  <button className="btn" onClick={() => ctx.go("leads")}>
                    Captured leads
                  </button>
                  <button
                    className="btn"
                    onClick={() => ctx.go("appointments")}
                  >
                    Booking records
                  </button>
                  <button className="btn" onClick={() => ctx.go("")}>
                    Usage overview
                  </button>
                  <p className="muted small-text">
                    Bookings use your connected calendar tools and require the
                    visitor’s confirmation. Checkout and cart changes require a
                    configured commerce integration.
                  </p>
                </div>
              </Panel>
            </div>
          )}
          {tab === "test" && (
            <Panel title="Try your connected website assistant">
              <p className="panel-body muted small-text">
                Ask about a product, service or policy. Website actions appear
                as links here; the installed widget can navigate your actual
                site.
              </p>
              {row.knowledge.active_snapshot_id ? (
                <WidgetChat
                  dashboardPreview
                  key={
                    row.installation.public_id +
                    row.installation.theme.publishable_key
                  }
                  publicId={row.installation.public_id}
                  publicKey={row.installation.theme.publishable_key}
                />
              ) : (
                <div className="panel-body muted">
                  Testing opens when the first successful crawl finishes.
                </div>
              )}
            </Panel>
          )}
          {tab === "pages" && (
            <Panel title="Website pages">
              <div className="panel-body stack">
                <p className="muted small-text">
                  Exclude pages from the next published snapshot. Existing
                  conversations retain their pinned knowledge version.
                </p>
                {pages.length ? (
                  pages.map((page) => (
                    <div className="website-page" key={page.url}>
                      <div>
                        <a
                          href={page.url}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {page.title || page.url}
                        </a>
                        <p className="muted small-text">
                          {page.url} ·{" "}
                          {page.indexed ? "Indexed" : "Previous revision"} ·{" "}
                          {when(page.fetched_at)}
                        </p>
                      </div>
                      <button
                        className="btn small"
                        disabled={busy}
                        onClick={() =>
                          perform(async () => {
                            const excluded = new Set<string>(
                              row.options.excluded_urls,
                            );
                            if (page.excluded) excluded.delete(page.url);
                            else excluded.add(page.url);
                            await command(
                              ctx.base +
                                "/website-assistants/" +
                                row.id +
                                "/options",
                              { ...row.options, excluded_urls: [...excluded] },
                              "PUT",
                            );
                            await command(
                              ctx.base +
                                "/website-assistants/" +
                                row.id +
                                "/recrawl",
                            );
                          }, "Page setting saved; recrawl queued")
                        }
                      >
                        {page.excluded ? "Include" : "Exclude"}
                      </button>
                    </div>
                  ))
                ) : (
                  <p className="muted">
                    Indexed pages will appear here after crawling.
                  </p>
                )}
              </div>
            </Panel>
          )}
        </>
      )}
      {(ctx.data.installations || []).filter(
        (i) => !rows.some((r) => r.installation_id === i.id),
      ).length > 0 && (
        <details className="panel panel-body" style={{ marginTop: 24 }}>
          <summary>Other agent installations</summary>
          <p className="muted small-text">
            Your existing installations continue to work with their published
            agent configuration.
          </p>
          {(ctx.data.installations || [])
            .filter((i) => !rows.some((r) => r.installation_id === i.id))
            .map((i) => (
              <div className="stack" key={i.id} style={{ marginTop: 20 }}>
                <div className="row between">
                  <strong>{i.name}</strong>
                  <Badge value={i.enabled ? "active" : "disabled"} />
                  <button className="btn small" onClick={() => appearance(i)}>
                    Customize widget
                  </button>
                  <button
                    className="btn small"
                    onClick={() =>
                      setLegacyTest(legacyTest === i.id ? "" : i.id)
                    }
                  >
                    Test installation
                  </button>
                </div>
                <pre className="code mono website-code">
                  {embedSnippet(window.location.origin, i)}
                </pre>
                {legacyTest === i.id && (
                  <WidgetChat
                    dashboardPreview
                    publicId={i.public_id}
                    publicKey={i.theme?.publishable_key || ""}
                  />
                )}
              </div>
            ))}
        </details>
      )}
    </>
  );
}
