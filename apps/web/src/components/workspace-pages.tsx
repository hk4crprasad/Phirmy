"use client";
import { useState, useEffect } from "react";
import Link from "next/link";
import { CallLatency } from "./call-latency";
import {
  AudioLines,
  Bot,
  BookOpen,
  Phone,
  ArrowUpRight,
  Plus,
  ArrowLeft,
  ArrowRight,
  Check,
  Search,
  Upload,
  RefreshCw,
  Globe,
  FileText,
  Play,
  Pause,
  Square,
  Wallet,
  Users,
  Ticket,
  ShoppingBag,
  Copy,
  Code2,
  CalendarDays,
  Plug,
  ShieldCheck,
  Radio,
  ExternalLink,
  Trash2,
} from "lucide-react";
import { api, command, Row, money, when } from "@/lib/api";
import {
  Header,
  Panel,
  Empty,
  Badge,
  Table,
  Dialog,
  StudioContext,
  Field,
} from "./ui";
import WidgetChat from "./widget-chat";
import AgentDeleteButton from "./agent-deletion";
import LiveInbox from "./live-inbox";
import WebsiteAssistants, { embedSnippet } from "./website-assistants";
import VariableEditor from "./variable-editor";
import { generation } from "@/lib/stream";

type Props = { ctx: StudioContext };
const nameFields: Field[] = [{ key: "name", label: "Name", required: true }];
function run(
  ctx: StudioContext,
  action: () => Promise<any>,
  message = "Saved",
) {
  action()
    .then(async () => {
      ctx.notify(message);
      await ctx.refresh();
    })
    .catch((e) => ctx.notify(e.message));
}
function sourceUrl(url: string) {
  return /^https?:\/\//.test(url);
}

export function Knowledge({ ctx, id }: Props & { id?: string }) {
  const [search, setSearch] = useState(""),
    [sources, setSources] = useState<Row[]>([]),
    [query, setQuery] = useState(""),
    [result, setResult] = useState<Row | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const kb = (ctx.data.knowledge || []).find((x) => x.id === id);
  useEffect(() => {
    if (id)
      api(ctx.base + "/knowledge/" + id + "/sources")
        .then((x) => setSources(x.items))
        .catch((e) => setError(e.message));
  }, [id, ctx.base, ctx.data.jobs]);
  function add() {
    ctx.form({
      title: "Connect website knowledge",
      description:
        "A durable crawl collects public pages, stores snapshots, and indexes the extracted text. Progress survives this browser tab.",
      fields: [
        { key: "name", label: "Knowledge base name", required: true },
        {
          key: "website_url",
          label: "Website URL",
          type: "url",
          required: true,
          value: "",
        },
        {
          key: "max_pages",
          label: "Maximum pages",
          type: "number",
          min: 1,
          max: 100,
          value: 15,
          required: true,
        },
      ],
      submit: "Start crawl",
      action: async (values) => {
        const result = await command(ctx.base + "/knowledge", values);
        await ctx.refresh();
        ctx.go("knowledge/" + result.kb_id);
      },
    });
  }
  if (id && !kb)
    return (
      <Empty
        title="Opening knowledge…"
        text="The record is loading or is unavailable in this workspace."
      />
    );
  if (kb)
    return (
      <>
        <Header
          eyebrow="KNOWLEDGE BASE"
          title={kb.name}
          description={kb.website_url}
        >
          <button className="btn" onClick={() => ctx.go("knowledge")}>
            <ArrowLeft size={13} />
            All knowledge
          </button>
          <button
            className="btn"
            onClick={() =>
              run(
                ctx,
                () => command(ctx.base + "/knowledge/" + id + "/recrawls"),
                "Recrawl queued",
              )
            }
          >
            <RefreshCw size={13} />
            Recrawl
          </button>
        </Header>
        <div className="split">
          <div className="stack">
            <Panel
              title="Sources & coverage"
              action={<Badge value={kb.status} />}
            >
              <div className="panel-body stack">
                <div className="row">
                  <span className="badge">{kb.pages_indexed} pages</span>
                  <span className="badge">{kb.chunks_indexed} chunks</span>
                  <span className="badge">
                    {ctx.capabilities.retrieval || "lexical-development"}
                  </span>
                </div>
                <div className="coverage">
                  {Object.entries(kb.assessment || {}).map(([topic, state]) => (
                    <span
                      className={
                        "badge " + (state === "covered" ? "ready" : "queued")
                      }
                      key={topic}
                    >
                      {topic}: {String(state)}
                    </span>
                  ))}
                </div>
                {sources.map((source) => (
                  <div className="source-item" key={source.id}>
                    <h4>{source.title || source.canonical_url}</h4>
                    {sourceUrl(source.canonical_url) ? (
                      <a
                        href={source.canonical_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {source.canonical_url}
                        <ExternalLink size={10} />
                      </a>
                    ) : (
                      <span className="mono">{source.canonical_url}</span>
                    )}
                    <div
                      className="muted"
                      style={{ fontSize: 9, marginTop: 7 }}
                    >
                      Fetched {when(source.fetched_at)} ·{" "}
                      {source.content_hash.slice(0, 12)}
                    </div>
                  </div>
                ))}
                {!sources.length && (
                  <Empty
                    title="Collecting your sources"
                    text="Progress and any source errors are shown in the jobs panel."
                  />
                )}
              </div>
            </Panel>
            <Panel
              title="Attach a document"
              note="TXT, PDF or DOCX · up to 20 MB"
            >
              <div className="panel-body">
                <input
                  aria-label="Upload knowledge document"
                  type="file"
                  accept=".txt,.pdf,.docx"
                  onChange={async (event) => {
                    const file = event.target.files?.[0];
                    if (!file) return;
                    const form = new FormData();
                    form.append("file", file);
                    try {
                      await api(ctx.base + "/knowledge/" + id + "/documents", {
                        method: "POST",
                        body: form,
                      });
                      ctx.notify("Document queued for extraction");
                      ctx.refresh();
                    } catch (e) {
                      setError((e as Error).message);
                    }
                    event.target.value = "";
                  }}
                />
                <p className="field-note" style={{ marginTop: 10 }}>
                  Original documents use{" "}
                  {ctx.capabilities.object_storage === "azure"
                    ? "Azure Blob Storage"
                    : "the local development object store"}
                  . Scanned PDFs need OCR and report an error if no text can be
                  extracted.
                </p>
              </div>
            </Panel>
            <Panel title="Background jobs">
              <Table
                rows={(ctx.data.jobs || []).filter(
                  (x) => x.payload.kb_id === id,
                )}
                columns={[
                  { label: "JOB", render: (r) => <strong>{r.kind}</strong> },
                  {
                    label: "PROGRESS",
                    render: (r) => (
                      <>
                        {r.phase}
                        <span className="cell-sub">
                          {r.completed_items} / {r.total_items || "?"}
                        </span>
                        {r.error && (
                          <span
                            className="cell-sub"
                            style={{
                              color: "var(--danger)",
                              whiteSpace: "normal",
                              maxWidth: 240,
                            }}
                          >
                            {r.error}
                          </span>
                        )}
                      </>
                    ),
                  },
                  { label: "STATUS", render: (r) => <Badge value={r.state} /> },
                  {
                    label: "",
                    render: (r) =>
                      ["failed", "canceled"].includes(r.state) ? (
                        <button
                          className="table-action"
                          onClick={() =>
                            run(
                              ctx,
                              () =>
                                command(ctx.base + "/jobs/" + r.id + "/retry"),
                              "Job queued",
                            )
                          }
                        >
                          Retry
                        </button>
                      ) : ["queued", "running"].includes(r.state) ? (
                        <button
                          className="table-action"
                          onClick={() =>
                            run(
                              ctx,
                              () =>
                                command(ctx.base + "/jobs/" + r.id + "/cancel"),
                              "Cancellation requested",
                            )
                          }
                        >
                          Cancel
                        </button>
                      ) : null,
                  },
                ]}
              />
            </Panel>
          </div>
          <div className="stack">
            <Panel
              title="Test your knowledge"
              note="Inspect actual source passages before using them in conversations."
            >
              <form
                className="panel-body"
                onSubmit={async (e) => {
                  e.preventDefault();
                  setBusy(true);
                  setError("");
                  try {
                    setResult(
                      await command(ctx.base + "/knowledge/" + id + "/query", {
                        query,
                        limit: 6,
                      }),
                    );
                  } catch (e) {
                    setError((e as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <label>
                  Your question
                  <textarea
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="What is the engraving character limit?"
                    required
                  />
                </label>
                <button className="btn primary" disabled={busy}>
                  {busy ? "Retrieving…" : "Retrieve sources"}
                  <Search size={13} />
                </button>
                {error && <div className="error">{error}</div>}
                {result && (
                  <>
                    <div className="notice">
                      {result.reason} · {result.retrieval_mode}
                    </div>
                    {result.passages.map((p: Row) => (
                      <div className="source-item" key={p.chunk_id}>
                        <h4>{p.title}</h4>
                        <p>{p.text}</p>
                        {sourceUrl(p.url) && (
                          <a href={p.url} target="_blank" rel="noreferrer">
                            View source
                            <ArrowUpRight size={10} />
                          </a>
                        )}
                      </div>
                    ))}
                  </>
                )}
              </form>
            </Panel>
            <Panel
              title="Business guidance"
              note="Reviewed instructions; not a replacement for missing facts."
            >
              <div className="panel-body">
                <p
                  className="small-text muted"
                  style={{ whiteSpace: "pre-wrap", marginBottom: 15 }}
                >
                  {kb.priority_guidance ||
                    "No additional guidance has been added."}
                </p>
                <button
                  className="btn small"
                  onClick={() =>
                    ctx.form({
                      title: "Edit business guidance",
                      fields: [
                        {
                          key: "priority_guidance",
                          label: "Guidance",
                          type: "textarea",
                          value: kb.priority_guidance,
                        },
                      ],
                      action: async (value) => {
                        await command(
                          ctx.base + "/knowledge/" + id,
                          value,
                          "PATCH",
                        );
                        ctx.notify("Guidance saved");
                        await ctx.refresh();
                      },
                    })
                  }
                >
                  Edit guidance
                </button>
              </div>
            </Panel>
          </div>
        </div>
      </>
    );
  return (
    <>
      <Header
        eyebrow="CONTEXT MAKES THE DIFFERENCE"
        title="A little knowledge goes a long way."
        description="Websites and documents that give your agents something useful to say."
      >
        <button className="btn primary" onClick={add}>
          <Plus size={14} />
          Connect website
        </button>
      </Header>
      <div className="toolbar">
        <div className="searchbox">
          <Search size={14} />
          <input
            aria-label="Search knowledge"
            placeholder="Find a knowledge base…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <span className="muted" style={{ fontSize: 10 }}>
          {(ctx.data.knowledge || []).length} knowledge bases
        </span>
      </div>
      <div className="resource-grid">
        {(ctx.data.knowledge || [])
          .filter((x) => x.name.toLowerCase().includes(search.toLowerCase()))
          .map((item) => (
            <Link
              href={"/app/knowledge/" + item.id}
              className="resource-card"
              key={item.id}
            >
              <div className="card-top">
                <span className="resource-icon">
                  <BookOpen size={18} />
                </span>
                <Badge value={item.status} />
              </div>
              <h3>{item.name}</h3>
              <p>{item.website_url}</p>
              <div className="card-bottom">
                <span>
                  {item.pages_indexed} pages · {item.chunks_indexed} chunks
                </span>
                <ArrowUpRight size={14} />
              </div>
            </Link>
          ))}
      </div>
      {!(ctx.data.knowledge || []).length && (
        <Panel>
          <Empty
            title="Start with what you know"
            text="Connect a website, then attach documents and test the retrieved facts."
            action={
              <button className="btn" onClick={add}>
                Connect a website
                <ArrowUpRight size={13} />
              </button>
            }
          />
        </Panel>
      )}
    </>
  );
}

export function Agents({ ctx, id }: Props & { id?: string }) {
  const item = (ctx.data.agents || []).find((x) => x.id === id),
    [config, setConfig] = useState<Row | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [tab, setTab] = useState("instructions"),
    [versions, setVersions] = useState<Row[]>([]);
  useEffect(() => {
    if (item) {
      const draft = structuredClone(item.draft_config);
      if (ctx.capabilities.voice_provider === "sarvam" && draft?.speech) {
        const rawLanguage = draft.speech.live_stt_language || "auto";
        const language =
          (
            { en: "en-IN", hi: "hi-IN", multi: "auto" } as Record<
              string,
              string
            >
          )[rawLanguage] || rawLanguage;
        draft.speech = {
          ...draft.speech,
          provider: "sarvam",
          model: ctx.capabilities.tts_model,
          voice_id:
            draft.speech.provider === "sarvam"
              ? draft.speech.voice_id
              : ctx.capabilities.voice_id,
          live_stt_provider: "sarvam",
          live_stt_model: ctx.capabilities.stt_model,
          live_stt_language: language,
          language_code:
            draft.speech.language_code ||
            (language === "auto" ? "auto" : language),
        };
      }
      setConfig(draft);
    }
  }, [item?.id, item?.draft_revision, ctx.capabilities.voice_provider]);
  useEffect(() => {
    if (id)
      api(ctx.base + "/agents/" + id + "/versions")
        .then((x) => setVersions(x.items))
        .catch((e) => setError(e.message));
  }, [id, ctx.base, item?.published_version_id]);
  function create() {
    ctx.form({
      title: "Build your next agent",
      description: ctx.capabilities.llm
        ? "Your connected model will turn your goal into a reviewable draft."
        : "Development mode creates a starter draft for you to review and test.",
      fields: [
        ...nameFields,
        {
          key: "website_url",
          label: "Website URL · optional",
          type: "url",
          note: "Automatically crawl your website, connect its knowledge and prepare a widget.",
        },
        {
          key: "goal",
          label: "What should this agent help people do?",
          type: "textarea",
          required: true,
        },
        {
          key: "kb_id",
          label: "Knowledge to connect",
          options: [
            { value: "", label: "Connect later" },
            ...(ctx.data.knowledge || [])
              .filter((k) => k.active_snapshot_id)
              .map((k) => ({ value: k.id, label: k.name })),
          ],
        },
      ],
      submit: "Generate draft",
      action: async (values) => {
        if (values.website_url) {
          const website = await command(ctx.base + "/website-assistants", {
            website_url: values.website_url,
            name: values.name,
            goal: values.goal,
          });
          await ctx.refresh();
          ctx.go("widget");
          ctx.notify(
            "Website assistant created; public pages are being indexed.",
          );
          return;
        }
        const result = await command(ctx.base + "/agents", {
          name: values.name,
        });
        try {
          const kb = (ctx.data.knowledge || []).find(
            (k) => k.id === values.kb_id,
          );
          const instructions = await generation(
            ctx.base + "/agents/generate",
            {
              goal: values.goal,
              language: "en",
              business_url: kb?.website_url || "",
            },
            (stage) =>
              ctx.notify("Preparing draft · " + stage.replaceAll("_", " ")),
          );
          const config = {
            ...result.draft_config,
            instructions,
            knowledge_snapshot_ids: kb ? [kb.active_snapshot_id] : [],
          };
          await command(
            ctx.base + "/agents/" + result.id + "/draft",
            { expected_revision: result.draft_revision, config },
            "PUT",
          );
          await ctx.refresh();
          ctx.go("agents/" + result.id);
          ctx.notify("Draft ready for review");
        } catch (error) {
          await ctx.refresh();
          throw error;
        }
      },
    });
  }
  async function save(publish = false) {
    if (!config || !item) return;
    setBusy(true);
    setError("");
    try {
      const draft = await command(
        ctx.base + "/agents/" + id + "/draft",
        { expected_revision: item.draft_revision, config },
        "PUT",
      );
      if (publish)
        await command(ctx.base + "/agents/" + id + "/publish", {
          expected_draft_revision: draft.draft_revision,
        });
      ctx.notify(
        publish
          ? "Agent published. New calls use this version."
          : "Draft saved",
      );
      await ctx.refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (id && (!item || !config))
    return (
      <Empty
        title="Opening agent…"
        text="This agent is loading or is unavailable in this workspace."
      />
    );
  if (item && config)
    return (
      <>
        <Header
          eyebrow={"AGENT STUDIO · DRAFT " + item.draft_revision}
          title={config.name}
          description="Build the conversation. Publish when it feels right."
        >
          <button className="btn" onClick={() => ctx.go("agents")}>
            <ArrowLeft size={13} />
            Agents
          </button>
          <AgentDeleteButton ctx={ctx} agent={item} />
          <button className="btn" disabled={busy} onClick={() => save()}>
            Save draft
          </button>
          <button
            className="btn primary"
            disabled={busy}
            onClick={() => save(true)}
          >
            <Check size={13} />
            {busy ? "Saving…" : "Publish agent"}
          </button>
        </Header>
        {error && <div className="error inline-error">{error}</div>}
        <div className="agent-identity">
          <span className="small-text muted">Agent ID</span>
          <code>{item.id}</code>
          <button
            className="btn subtle small"
            aria-label="Copy agent ID"
            onClick={() =>
              navigator.clipboard
                .writeText(item.id)
                .then(() => ctx.notify("Agent ID copied"))
                .catch(() => ctx.notify("Select the agent ID to copy it"))
            }
          >
            <Copy size={13} />
            Copy
          </button>
          <button
            className="btn small"
            disabled={!item.published_version_id}
            onClick={() => ctx.go("voice?agent=" + item.id)}
          >
            Test this agent
            <ArrowUpRight size={13} />
          </button>
        </div>
        <div className="tabs">
          {[
            "instructions",
            "knowledge",
            "voice & behavior",
            "actions",
            "versions",
          ].map((t) => (
            <button
              key={t}
              className={"tab " + (tab === t ? "active" : "")}
              onClick={() => setTab(t)}
            >
              {t[0].toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>
        <div className="split">
          <Panel
            title={
              tab === "instructions"
                ? "The conversation"
                : tab === "knowledge"
                  ? "Connected knowledge"
                  : tab === "versions"
                    ? "Published versions"
                    : "Voice and behavior"
            }
          >
            <div className="panel-body">
              {tab === "instructions" && (
                <div className="stack">
                  <label>
                    Agent name
                    <input
                      value={config.name}
                      onChange={(e) =>
                        setConfig({ ...config, name: e.target.value })
                      }
                    />
                  </label>
                  <label>
                    First words
                    <textarea
                      aria-label="First words"
                      value={config.greeting}
                      onChange={(e) =>
                        setConfig({ ...config, greeting: e.target.value })
                      }
                      style={{ minHeight: 80 }}
                    />
                  </label>
                  <label>
                    Agent instructions
                    <textarea
                      value={config.instructions}
                      onChange={(e) =>
                        setConfig({ ...config, instructions: e.target.value })
                      }
                      style={{ minHeight: 250 }}
                    />
                  </label>
                  <label>
                    Business guidance
                    <textarea
                      value={config.priority_guidance}
                      onChange={(e) =>
                        setConfig({
                          ...config,
                          priority_guidance: e.target.value,
                        })
                      }
                    />
                  </label>
                  <VariableEditor
                    value={config.variables || []}
                    onChange={(variables) =>
                      setConfig({ ...config, variables })
                    }
                  />
                </div>
              )}
              {tab === "knowledge" && (
                <div className="stack">
                  <p className="field-note">
                    Each published agent pins a knowledge snapshot. Recrawl and
                    publish again to update the facts used by new calls.
                  </p>
                  {(ctx.data.knowledge || [])
                    .filter((k) => k.active_snapshot_id)
                    .map((k) => (
                      <label className="checkbox-label" key={k.id}>
                        <input
                          type="checkbox"
                          checked={config.knowledge_snapshot_ids.includes(
                            k.active_snapshot_id,
                          )}
                          onChange={(e) =>
                            setConfig({
                              ...config,
                              knowledge_snapshot_ids: e.target.checked
                                ? [
                                    ...config.knowledge_snapshot_ids,
                                    k.active_snapshot_id,
                                  ]
                                : config.knowledge_snapshot_ids.filter(
                                    (x: string) => x !== k.active_snapshot_id,
                                  ),
                            })
                          }
                        />
                        {k.name}
                        <Badge value={k.status} />
                      </label>
                    ))}
                  {!(ctx.data.knowledge || []).some(
                    (k) => k.active_snapshot_id,
                  ) && (
                    <Empty
                      title="Connect knowledge first"
                      text="Once a knowledge base is ready, select its snapshot here."
                      action={
                        <button
                          className="btn"
                          onClick={() => ctx.go("knowledge")}
                        >
                          Go to knowledge
                        </button>
                      }
                    />
                  )}
                </div>
              )}
              {tab === "voice & behavior" && (
                <div className="stack">
                  <div className="notice">
                    {ctx.capabilities.voice_provider === "sarvam"
                      ? "Browser voice and phone calls use Sarvam for listening, replies and speech, with your enabled tools. The model below handles text chat."
                      : "Fish Audio handles speech. Your selected model handles reasoning."}
                  </div>
                  <label>
                    Text chat model
                    <select
                      value={config.llm.profile_id || ""}
                      onChange={(e) => {
                        const profile = (ctx.data.models || []).find(
                          (m) => m.id === e.target.value,
                        );
                        setConfig({
                          ...config,
                          llm: {
                            ...config.llm,
                            profile_id: profile?.id || null,
                            model: profile?.model || ctx.capabilities.model,
                            provider: profile ? "openai-compatible" : "openai",
                          },
                        });
                      }}
                    >
                      <option value="">
                        Server default · {ctx.capabilities.model}
                      </option>
                      {(ctx.data.models || []).map((m) => (
                        <option value={m.id} key={m.id}>
                          {m.name} · {m.model}
                        </option>
                      ))}
                    </select>
                    <span className="field-note">
                      Add a researched, tested endpoint under Models.
                    </span>
                  </label>
                  <label>
                    Speech model
                    <select
                      value={config.speech.model}
                      onChange={(e) =>
                        setConfig({
                          ...config,
                          speech: { ...config.speech, model: e.target.value },
                        })
                      }
                    >
                      {(ctx.capabilities.voice_provider === "sarvam"
                        ? ["bulbul:v4-flash"]
                        : ["drama-3", "s2.1-pro", "s2.1-pro-free", "s2-pro"]
                      ).map((model) => (
                        <option key={model} value={model}>
                          {model}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    {ctx.capabilities.voice_provider === "sarvam"
                      ? "Sarvam speaker"
                      : "Fish voice reference ID"}
                    <input
                      value={config.speech.voice_id}
                      onChange={(e) =>
                        setConfig({
                          ...config,
                          speech: {
                            ...config.speech,
                            voice_id: e.target.value,
                          },
                        })
                      }
                    />
                    <span className="field-note">
                      {ctx.capabilities.voice_provider === "sarvam"
                        ? "Use a Bulbul v4 Flash persona, such as simran_enhi_customer for English and Hindi."
                        : "Must be a voice accessible to your configured Fish account."}
                    </span>
                  </label>
                  <label>
                    Recognition language
                    <select
                      value={config.speech.live_stt_language}
                      onChange={(e) =>
                        setConfig({
                          ...config,
                          speech: {
                            ...config.speech,
                            live_stt_language: e.target.value,
                          },
                          language: e.target.value,
                        })
                      }
                    >
                      {ctx.capabilities.voice_provider === "sarvam" ? (
                        <>
                          <option value="auto">
                            Detect language automatically
                          </option>
                          <option value="en-IN">English</option>
                          <option value="hi-IN">Hindi</option>
                          <option value="ta-IN">Tamil</option>
                          <option value="te-IN">Telugu</option>
                          <option value="kn-IN">Kannada</option>
                          <option value="ml-IN">Malayalam</option>
                          <option value="mr-IN">Marathi</option>
                          <option value="bn-IN">Bengali</option>
                          <option value="gu-IN">Gujarati</option>
                          <option value="pa-IN">Punjabi</option>
                          <option value="or-IN">Odia</option>
                        </>
                      ) : (
                        <>
                          <option value="en">English</option>
                          <option value="hi">Hindi</option>
                          <option value="multi">Multilingual</option>
                        </>
                      )}
                    </select>
                  </label>
                  {ctx.capabilities.voice_provider === "sarvam" && (
                    <label>
                      Spoken language
                      <select
                        value={config.speech.language_code || "auto"}
                        onChange={(e) =>
                          setConfig({
                            ...config,
                            speech: {
                              ...config.speech,
                              language_code: e.target.value,
                            },
                          })
                        }
                      >
                        <option value="auto">Auto · follow the speaker</option>
                        {[
                          ["en-IN", "English"],
                          ["hi-IN", "Hindi"],
                          ["ta-IN", "Tamil"],
                          ["te-IN", "Telugu"],
                          ["kn-IN", "Kannada"],
                          ["ml-IN", "Malayalam"],
                          ["mr-IN", "Marathi"],
                          ["bn-IN", "Bengali"],
                          ["gu-IN", "Gujarati"],
                          ["pa-IN", "Punjabi"],
                          ["od-IN", "Odia"],
                        ].map(([value, label]) => (
                          <option key={value} value={value}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  <label>
                    Maximum connected seconds
                    <input
                      type="number"
                      min={10}
                      max={900}
                      value={config.behavior.max_connected_seconds}
                      onChange={(e) =>
                        setConfig({
                          ...config,
                          behavior: {
                            ...config.behavior,
                            max_connected_seconds: Number(e.target.value),
                          },
                        })
                      }
                    />
                  </label>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={config.behavior.interruptible}
                      onChange={(e) =>
                        setConfig({
                          ...config,
                          behavior: {
                            ...config.behavior,
                            interruptible: e.target.checked,
                          },
                        })
                      }
                    />
                    Allow caller interruptions
                  </label>
                  <label>
                    Silence check-in · seconds
                    <input
                      type="number"
                      min={3}
                      max={120}
                      value={config.behavior.silence_prompt_seconds}
                      onChange={(e) =>
                        setConfig({
                          ...config,
                          behavior: {
                            ...config.behavior,
                            silence_prompt_seconds: Number(e.target.value),
                          },
                        })
                      }
                    />
                  </label>
                  <label>
                    End idle session · seconds
                    <input
                      type="number"
                      min={10}
                      max={300}
                      value={config.behavior.idle_end_seconds}
                      onChange={(e) =>
                        setConfig({
                          ...config,
                          behavior: {
                            ...config.behavior,
                            idle_end_seconds: Number(e.target.value),
                          },
                        })
                      }
                    />
                  </label>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={config.recording.enabled}
                      onChange={(e) =>
                        setConfig({
                          ...config,
                          recording: {
                            ...config.recording,
                            enabled: e.target.checked,
                            retention_days:
                              config.recording.retention_days || 7,
                          },
                        })
                      }
                    />
                    Record live calls · caller and assistant on separate
                    channels
                  </label>
                  {config.recording.enabled && (
                    <label>
                      Keep recordings · days
                      <input
                        type="number"
                        min={1}
                        max={365}
                        value={config.recording.retention_days}
                        onChange={(e) =>
                          setConfig({
                            ...config,
                            recording: {
                              ...config.recording,
                              retention_days: Number(e.target.value),
                            },
                          })
                        }
                      />
                      <span className="field-note">
                        The greeting announces recording. Expired audio is
                        denied immediately and removed by the retention worker.
                      </span>
                    </label>
                  )}
                </div>
              )}
              {tab === "actions" && (
                <div className="stack">
                  <p className="small-text muted">
                    Enable only the actions this agent needs. Every write stays
                    inside your workspace and records its result before
                    confirmation.
                  </p>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={[
                        "check_scheduling_availability",
                        "prepare_scheduling_booking",
                        "confirm_scheduling_booking",
                        "get_scheduling_booking",
                      ].every((name) =>
                        config.tools.some((tool: Row) => tool.name === name),
                      )}
                      onChange={(event) => {
                        const names = [
                          "check_scheduling_availability",
                          "prepare_scheduling_booking",
                          "confirm_scheduling_booking",
                          "get_scheduling_booking",
                        ];
                        const remaining = config.tools.filter(
                          (tool: Row) => !names.includes(tool.name),
                        );
                        const provider =
                          (ctx.data.connections || []).find(
                            (connection) =>
                              ["calcom", "calendly"].includes(
                                connection.provider,
                              ) &&
                              connection.scopes?.includes("bookings:write"),
                          )?.provider || "calcom";
                        setConfig({
                          ...config,
                          tools: event.target.checked
                            ? [
                                ...remaining,
                                ...names.map((name) => ({
                                  name,
                                  schema_revision: "1",
                                  timeout_ms: 40000,
                                  ...(name === "check_scheduling_availability"
                                    ? { scheduling_provider: provider }
                                    : {}),
                                  side_effecting: [
                                    "prepare_scheduling_booking",
                                    "confirm_scheduling_booking",
                                  ].includes(name),
                                })),
                              ]
                            : remaining,
                        });
                      }}
                    />
                    Book meetings through Cal.com or Calendly
                  </label>
                  {config.tools.some(
                    (tool: Row) =>
                      tool.name === "check_scheduling_availability",
                  ) && (
                    <label>
                      Booking platform
                      <select
                        aria-label="Booking platform"
                        value={
                          config.tools.find(
                            (tool: Row) =>
                              tool.name === "check_scheduling_availability",
                          )?.scheduling_provider || "calcom"
                        }
                        onChange={(event) =>
                          setConfig({
                            ...config,
                            tools: config.tools.map((tool: Row) =>
                              tool.name === "check_scheduling_availability"
                                ? {
                                    ...tool,
                                    scheduling_provider: event.target.value,
                                  }
                                : tool,
                            ),
                          })
                        }
                      >
                        <option value="calcom">Cal.com</option>
                        <option value="calendly">Calendly</option>
                      </select>
                    </label>
                  )}
                  <p className="field-note">
                    Your agent checks live slots, collects details and asks for
                    confirmation before booking. Connect a scheduler and choose
                    its meeting type in{" "}
                    <Link href="/app/integrations">Integrations</Link>.
                  </p>
                  {[
                    {
                      name: "search_products",
                      label: "Look up verified products",
                    },
                    {
                      name: "create_support_ticket",
                      label: "Record requested support tickets",
                    },
                    {
                      name: "request_human_transfer",
                      label:
                        "Transfer phone calls to an approved staff destination",
                    },
                    {
                      name: "request_callback",
                      label: "Record confirmed callback requests in the inbox",
                    },
                    {
                      name: "capture_lead",
                      label: "Save contact details provided for follow-up",
                    },
                    {
                      name: "check_appointments",
                      label: "Check local appointment conflicts",
                    },
                    {
                      name: "book_appointment",
                      label: "Record requested local appointments",
                    },
                    {
                      name: "get_scheduling_link",
                      label:
                        "Share a connected Cal.com or Calendly scheduling link",
                    },
                    {
                      name: "check_calendar_availability",
                      label: "Check connected Google Calendar availability",
                    },
                    {
                      name: "sync_calendar_appointment",
                      label: "Sync a confirmed appointment to Google Calendar",
                    },
                  ].map((tool) => (
                    <label className="checkbox-label" key={tool.name}>
                      <input
                        type="checkbox"
                        checked={config.tools.some(
                          (x: Row) => x.name === tool.name,
                        )}
                        onChange={(e) =>
                          setConfig({
                            ...config,
                            tools: e.target.checked
                              ? [
                                  ...config.tools,
                                  {
                                    name: tool.name,
                                    schema_revision: "1",
                                    timeout_ms: 15000,
                                    side_effecting: ![
                                      "search_products",
                                      "check_appointments",
                                      "get_scheduling_link",
                                      "check_calendar_availability",
                                    ].includes(tool.name),
                                  },
                                ]
                              : config.tools.filter(
                                  (x: Row) => x.name !== tool.name,
                                ),
                          })
                        }
                      />
                      {tool.label}
                    </label>
                  ))}
                  <h3 style={{ fontSize: 14 }}>Your HTTP tools</h3>
                  {(ctx.data.tools || [])
                    .filter((t) => t.enabled)
                    .map((t) => (
                      <label className="checkbox-label" key={t.id}>
                        <input
                          type="checkbox"
                          checked={config.tools.some(
                            (x: Row) => x.tool_id === t.id,
                          )}
                          onChange={(e) =>
                            setConfig({
                              ...config,
                              tools: e.target.checked
                                ? [
                                    ...config.tools,
                                    {
                                      name: t.name,
                                      schema_revision: String(t.revision),
                                      timeout_ms: t.timeout_seconds * 1000,
                                      side_effecting: t.side_effecting,
                                      tool_id: t.id,
                                    },
                                  ]
                                : config.tools.filter(
                                    (x: Row) => x.tool_id !== t.id,
                                  ),
                            })
                          }
                        />
                        {t.name} · revision {t.revision}
                      </label>
                    ))}
                  <button className="btn" onClick={() => ctx.go("tools")}>
                    Manage HTTP tools
                    <ArrowUpRight size={13} />
                  </button>
                  <div className="notice">
                    Model-driven actions use the selected LLM. Requests can wait
                    for results or run as durable background actions. The
                    execution history records their actual outcome.
                  </div>
                </div>
              )}
              {tab === "versions" && (
                <div className="stack">
                  {versions.map((v) => (
                    <div className="source-item" key={v.id}>
                      <div className="row between">
                        <strong>Version {v.version}</strong>
                        <Badge
                          value={
                            v.id === item.published_version_id
                              ? "published"
                              : "archived"
                          }
                        />
                      </div>
                      <p>{when(v.created_at)}</p>
                      <div className="mono muted">
                        {v.config_hash.slice(0, 24)}
                      </div>
                      <button
                        className="btn small"
                        style={{ marginTop: 12 }}
                        onClick={() => {
                          setConfig(structuredClone(v.config));
                          setTab("instructions");
                          ctx.notify(
                            "Version copied into editor. Save and publish to restore it.",
                          );
                        }}
                      >
                        Copy to draft
                      </button>
                    </div>
                  ))}
                  {!versions.length && (
                    <Empty
                      title="Not published yet"
                      text="Validated publication creates an immutable version here."
                    />
                  )}
                </div>
              )}
            </div>
          </Panel>
          <div className="stack">
            <Panel title="Ready to talk?">
              <div className="panel-body stack">
                <div
                  className="voice-orb"
                  style={{ width: 75, height: 75, margin: "20px auto" }}
                />
                <h3
                  style={{ fontSize: 17, textAlign: "center", marginTop: 15 }}
                >
                  {config.name}
                </h3>
                <p className="small-text muted" style={{ textAlign: "center" }}>
                  Review your greeting, then try a conversation in the voice
                  lab.
                </p>
                <button
                  className="btn primary"
                  disabled={!item.published_version_id}
                  onClick={() => ctx.go("voice?agent=" + item.id)}
                >
                  <Play size={13} />
                  Test published agent
                </button>
                {!item.published_version_id && (
                  <p className="field-note">
                    Publish your first version to unlock testing.
                  </p>
                )}
              </div>
            </Panel>
            <Panel title="Connect a website">
              <div className="panel-body">
                <button className="btn" onClick={() => ctx.go("widget")}>
                  Website knowledge & widget <Globe size={13} />
                </button>
              </div>
            </Panel>
            <Panel title="Publication keeps calls consistent">
              <div className="panel-body small-text muted">
                Draft changes stay in the editor. Existing calls keep their
                pinned agent and knowledge versions. New calls use the version
                you publish.
                <hr className="divider" />
                <div className="row between">
                  <span>Current state</span>
                  <Badge
                    value={item.published_version_id ? "published" : "draft"}
                  />
                </div>
              </div>
            </Panel>
          </div>
        </div>
      </>
    );
  return (
    <>
      <Header
        eyebrow="A VOICE FOR EVERY PURPOSE"
        title="Meet your team of agents."
        description="Grounded in your business. Tuned to the conversation."
      >
        <button className="btn" onClick={() => ctx.go("templates")}>
          Explore templates
          <ArrowUpRight size={13} />
        </button>
        <button className="btn primary" onClick={create}>
          <Plus size={14} />
          Create agent
        </button>
      </Header>
      <div className="resource-grid">
        {(ctx.data.agents || []).map((a) => (
          <section className="resource-card" key={a.id}>
            <Link href={"/app/agents/" + a.id} style={{ display: "block" }}>
              <div className="card-top">
                <span className="resource-icon">
                  <Bot size={20} />
                </span>
                <Badge value={a.published_version_id ? "published" : "draft"} />
              </div>
              <h3>{a.name}</h3>
              <p>{a.draft_config.greeting}</p>
              <div className="card-bottom">
                <span>
                  {ctx.capabilities.voice_provider === "sarvam"
                    ? "Sarvam voice"
                    : "Fish Audio"}{" "}
                  ·{" "}
                  {ctx.capabilities.voice_model ||
                    ctx.capabilities.model ||
                    "Connected model"}
                </span>
                <ArrowUpRight size={14} />
              </div>
            </Link>
            <div style={{ marginTop: 16 }}>
              <AgentDeleteButton ctx={ctx} agent={a} />
            </div>
          </section>
        ))}
      </div>
      {!(ctx.data.agents || []).length && (
        <Panel>
          <Empty
            title="Your first agent is a name away"
            text="Create a draft, connect knowledge and publish a version you can test."
            action={
              <button className="btn primary" onClick={create}>
                Create your first agent
                <Plus size={13} />
              </button>
            }
          />
        </Panel>
      )}
    </>
  );
}

export function Calls({ ctx }: Props) {
  const [detail, setDetail] = useState<Row | null>(null),
    [search, setSearch] = useState("");
  async function open(id: string) {
    try {
      setDetail(await api(ctx.base + "/calls/" + id));
    } catch (e) {
      ctx.notify((e as Error).message);
    }
  }
  function outbound() {
    ctx.form({
      title: "Place a test call",
      description:
        "Simulation creates a clearly labelled local call and uses development credits. Live mode requires configured providers and an allowed controlled destination.",
      fields: [
        {
          key: "agent_id",
          label: "Published agent",
          options: (ctx.data.agents || [])
            .filter((a) => a.published_version_id)
            .map((a) => ({ value: a.id, label: a.name })),
          required: true,
        },
        {
          key: "destination",
          label: "Destination · E.164",
          required: true,
          value: "+91",
        },
        {
          key: "mode",
          label: "Call mode",
          value: "simulation",
          options: [
            { value: "simulation", label: "Simulation — no telephone call" },
            ...(ctx.capabilities.telephony
              ? [{ value: "live", label: "Live phone call" }]
              : []),
          ],
        },
        {
          key: "number_id",
          label: "Originating number",
          options: [
            { value: "", label: "None — simulation only" },
            ...(ctx.data.numbers || [])
              .filter((n) => n.status === "active")
              .map((n) => ({ value: n.id, label: n.e164 })),
          ],
        },
        {
          key: "budget_minor",
          label: "Maximum budget · minor units (100 = ₹1)",
          type: "number",
          value: 500,
          min: 1,
          required: true,
        },
      ],
      submit: "Dispatch test",
      action: async (values) => {
        await command(
          ctx.base + "/calls/outbound",
          { ...values, number_id: values.number_id || null },
          "POST",
          true,
        );
        ctx.notify("Test dispatched");
        await ctx.refresh();
      },
    });
  }
  return (
    <>
      <Header
        eyebrow="EVERY CONVERSATION, IN CONTEXT"
        title="Call history."
        description="Listen to the details. Learn from what happened."
      >
        <button className="btn" onClick={() => ctx.go("voice")}>
          <Radio size={13} />
          Browser voice lab
        </button>
        <button className="btn primary" onClick={outbound}>
          <Phone size={13} />
          Test outbound
        </button>
      </Header>
      <div className="toolbar">
        <div className="searchbox">
          <Search size={14} />
          <input
            aria-label="Search calls"
            placeholder="Search agent or destination…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>
      <Panel>
        <Table
          rows={(ctx.data.calls || []).filter((c) =>
            (c.agent_name + " " + c.destination)
              .toLowerCase()
              .includes(search.toLowerCase()),
          )}
          columns={[
            { label: "AGENT", render: (r) => <strong>{r.agent_name}</strong> },
            {
              label: "CHANNEL",
              render: (r) => (
                <>
                  {r.direction} · {r.transport}
                  <span className="cell-sub">
                    <Badge value={r.mode} />
                  </span>
                </>
              ),
            },
            {
              label: "DESTINATION",
              render: (r) => r.destination || "Browser session",
            },
            {
              label: "STATUS",
              render: (r) => (
                <>
                  <Badge value={r.state} />
                  {r.failure_code && (
                    <span className="cell-sub">{r.failure_code}</span>
                  )}
                </>
              ),
            },
            {
              label: "DURATION",
              render: (r) => (r.connected_ms / 1000).toFixed(0) + "s",
            },
            { label: "STARTED", render: (r) => when(r.created_at) },
            {
              label: "",
              render: (r) => (
                <button className="table-action" onClick={() => open(r.id)}>
                  Details
                  <ArrowUpRight size={12} />
                </button>
              ),
            },
          ]}
        />
      </Panel>
      {detail && (
        <Dialog
          title={detail.agent_name + " · Call details"}
          close={() => setDetail(null)}
        >
          <div className="stack">
            <div className="row">
              <Badge value={detail.state} />
              <Badge value={detail.mode} />
              <span className="muted small-text">
                {Math.round(detail.connected_ms / 1000)} connected seconds
              </span>
            </div>
            {detail.failure_code && (
              <div className="error">{detail.failure_code}</div>
            )}
            <div className="mono code">{detail.id}</div>
            <CallLatency timing={detail.voice_timing} />
            <h3 className="section-title">Transcript</h3>
            {detail.turns.map((turn: Row) => (
              <div
                key={turn.id}
                className={
                  "chat-bubble " + (turn.speaker === "user" ? "user" : "")
                }
              >
                <strong style={{ fontSize: 9, textTransform: "uppercase" }}>
                  {turn.speaker}
                  {turn.interrupted ? " · interrupted" : ""}
                </strong>
                <div>{turn.text_content}</div>
              </div>
            ))}
            {!detail.turns.length && (
              <p className="small-text muted">No transcript was captured.</p>
            )}
            <h3 className="section-title">Analysis</h3>
            <div className="notice">
              {detail.analysis.summary || "Analysis is not available yet."}
              {detail.analysis.disposition && (
                <div>
                  Disposition: {detail.analysis.disposition} · Lead:{" "}
                  {detail.analysis.is_lead ? "yes" : "no"}
                </div>
              )}
            </div>
            {!["completed", "failed", "canceled", "busy", "no_answer"].includes(
              detail.state,
            ) && (
              <button
                className="btn danger"
                onClick={() =>
                  run(
                    ctx,
                    () => command(ctx.base + "/calls/" + detail.id + "/stop"),
                    "Stop requested",
                  )
                }
              >
                Stop call
              </button>
            )}
          </div>
        </Dialog>
      )}
    </>
  );
}

export function Commerce({
  ctx,
  widget = false,
}: Props & { widget?: boolean }) {
  const [tab, setTab] = useState(widget ? "widget" : "products"),
    [installation, setInstallation] = useState(""),
    [search, setSearch] = useState("");
  const installs = ctx.data.installations || [],
    stores = ctx.data.stores || [];
  useEffect(() => {
    if (!installation && installs[0]) setInstallation(installs[0].public_id);
  }, [installs, installation]);
  if (widget) return <WebsiteAssistants ctx={ctx} />;
  function addStore() {
    ctx.form({
      title: "Connect a store",
      fields: [
        { key: "name", label: "Store name", required: true },
        {
          key: "website_url",
          label: "Website",
          type: "url",
          value: "",
          required: true,
        },
      ],
      action: async (values) => {
        await command(ctx.base + "/stores", values);
        await ctx.refresh();
        ctx.notify("Store connected");
      },
    });
  }
  function addProduct() {
    if (!stores.length) {
      addStore();
      return;
    }
    ctx.form({
      title: "Add a product",
      fields: [
        {
          key: "store_id",
          label: "Store",
          options: stores.map((x) => ({ value: x.id, label: x.name })),
          required: true,
        },
        { key: "title", label: "Product title", required: true },
        {
          key: "canonical_url",
          label: "Canonical product URL",
          type: "url",
          required: true,
        },
        {
          key: "price_minor",
          label: "Price in minor units · 99900 = ₹999",
          type: "number",
          min: 0,
          required: true,
        },
        { key: "currency", label: "Currency", value: "INR", required: true },
        {
          key: "availability",
          label: "Availability",
          options: [
            { value: "unknown", label: "Unknown" },
            { value: "in_stock", label: "In stock" },
            { value: "out_of_stock", label: "Out of stock" },
          ],
        },
        { key: "description", label: "Description", type: "textarea" },
      ],
      action: async (values) => {
        await command(ctx.base + "/products", values);
        await ctx.refresh();
        ctx.notify("Product saved");
      },
    });
  }
  function addWidget(existing?: Row) {
    ctx.form({
      title: existing
        ? "Edit widget installation"
        : "Create a widget installation",
      description:
        "The public ID identifies this installation. Server credentials are never included in your embed.",
      fields: [
        {
          key: "name",
          label: "Installation name",
          required: true,
          value: existing?.name || "",
        },
        {
          key: "agent_id",
          label: "Agent",
          value: existing?.agent_id,
          options: (ctx.data.agents || [])
            .filter((a) => a.published_version_id)
            .map((a) => ({ value: a.id, label: a.name })),
          required: true,
        },
        {
          key: "origins",
          label: "Allowed origins · comma separated",
          value: existing?.allowed_origins.join(", ") || window.location.origin,
          required: true,
        },
        {
          key: "preset",
          label: "Appearance",
          value: existing?.theme?.preset || "minimal",
          options: ["minimal", "classic", "bubble", "panel", "compact"].map(
            (x) => ({ value: x, label: x }),
          ),
        },
        {
          key: "voice_enabled",
          label: "Offer a voice conversation",
          type: "checkbox",
          value: existing?.theme?.voice_enabled || false,
          note: "Visitors can choose microphone access. Voice becomes available when the agent’s speech services are connected.",
        },
        {
          key: "enabled",
          label: "Installation enabled",
          type: "checkbox",
          value: existing?.enabled ?? true,
        },
      ],
      action: async (values) => {
        const created = await command(
          ctx.base + "/installations" + (existing ? "/" + existing.id : ""),
          {
            name: values.name,
            agent_id: values.agent_id,
            allowed_origins: values.origins
              .split(",")
              .map((x: string) => x.trim()),
            theme: {
              preset: values.preset,
              accent_color: "#00a88e",
              voice_enabled: values.voice_enabled,
            },
            enabled: values.enabled,
          },
          existing ? "PUT" : "POST",
        );
        setInstallation(created.public_id);
        await ctx.refresh();
        ctx.notify("Installation created");
      },
    });
  }
  return (
    <>
      <Header
        eyebrow={
          widget
            ? "A CONVERSATION AT EVERY TOUCHPOINT"
            : "REAL PRODUCTS. RELIABLE ANSWERS."
        }
        title={
          widget
            ? "Meet your website’s helpful side."
            : "Your product knowledge, organized."
        }
        description={
          widget
            ? "Grounded answers, unique product recommendations and a real path to your team."
            : "Structured prices, availability and provenance — ready for your agents."
        }
      >
        <button className="btn" onClick={addStore}>
          <Globe size={13} />
          Connect store
        </button>
        <button
          className="btn primary"
          onClick={widget ? () => addWidget() : addProduct}
        >
          <Plus size={14} />
          {widget ? "Create installation" : "Add product"}
        </button>
      </Header>
      <div className="tabs">
        {["products", "stores", "scan jobs", "widget"].map((t) => (
          <button
            key={t}
            className={"tab " + (tab === t ? "active" : "")}
            onClick={() => setTab(t)}
          >
            {t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>
      {tab === "products" && (
        <>
          <div className="toolbar">
            <div className="searchbox">
              <Search size={14} />
              <input
                aria-label="Search products"
                placeholder="Search your catalog…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <span className="muted small-text">
              {(ctx.data.products || []).length} unique products
            </span>
          </div>
          <Panel>
            <Table
              rows={(ctx.data.products || []).filter((p) =>
                p.title.toLowerCase().includes(search.toLowerCase()),
              )}
              columns={[
                {
                  label: "PRODUCT",
                  render: (r) => (
                    <>
                      <strong>{r.title}</strong>
                      <span className="cell-sub">
                        {r.description.slice(0, 65)}
                      </span>
                    </>
                  ),
                },
                {
                  label: "PRICE",
                  render: (r) => money(r.price_minor, r.currency),
                },
                {
                  label: "AVAILABILITY",
                  render: (r) => <Badge value={r.availability} />,
                },
                {
                  label: "SOURCE",
                  render: (r) =>
                    r.provenance.synthetic
                      ? "Synthetic fixture"
                      : r.provenance.source || "Manual",
                },
                {
                  label: "",
                  render: (r) => (
                    <a
                      className="table-action"
                      href={r.canonical_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Product page
                      <ArrowUpRight size={12} />
                    </a>
                  ),
                },
                {
                  label: "",
                  render: (r) => (
                    <button
                      className="btn subtle"
                      aria-label={"Archive " + r.title}
                      onClick={() =>
                        run(
                          ctx,
                          () =>
                            api(ctx.base + "/products/" + r.id, {
                              method: "DELETE",
                            }),
                          "Product archived",
                        )
                      }
                    >
                      <Trash2 size={12} />
                    </button>
                  ),
                },
              ]}
            />
          </Panel>
        </>
      )}
      {tab === "stores" && (
        <div className="resource-grid">
          {stores.map((store) => (
            <section className="resource-card" key={store.id}>
              <div className="resource-icon">
                <ShoppingBag size={18} />
              </div>
              <h3>{store.name}</h3>
              <p>{store.website_url}</p>
              <div className="card-bottom">
                <span>
                  {
                    (ctx.data.products || []).filter(
                      (p) => p.store_id === store.id,
                    ).length
                  }{" "}
                  products
                </span>
                <button
                  className="btn small"
                  onClick={() =>
                    run(
                      ctx,
                      () =>
                        command(ctx.base + "/stores/" + store.id + "/scans"),
                      "Catalog scan queued",
                    )
                  }
                >
                  <RefreshCw size={11} />
                  Scan catalog
                </button>
              </div>
            </section>
          ))}
          {!stores.length && (
            <Panel>
              <Empty
                title="Connect your first store"
                text="Scan public product structured data or add products manually."
                action={
                  <button className="btn" onClick={addStore}>
                    Connect store
                  </button>
                }
              />
            </Panel>
          )}
        </div>
      )}
      {tab === "scan jobs" && (
        <Panel
          title="Catalog scans"
          note="Jobs keep running independently of your browser."
        >
          <Table
            rows={(ctx.data.jobs || []).filter((j) => j.kind === "catalog")}
            columns={[
              { label: "STARTED", render: (r) => when(r.created_at) },
              {
                label: "PROGRESS",
                render: (r) => (
                  <>
                    {r.completed_items} / {r.total_items} pages
                    <span className="cell-sub">{r.phase}</span>
                  </>
                ),
              },
              { label: "STATUS", render: (r) => <Badge value={r.state} /> },
              {
                label: "RESULT",
                render: (r) => (
                  <>
                    {r.result.imported_or_updated ?? "—"} imported/updated
                    {r.error && <span className="cell-sub">{r.error}</span>}
                  </>
                ),
              },
              {
                label: "",
                render: (r) =>
                  r.state === "failed" ? (
                    <button
                      className="table-action"
                      onClick={() =>
                        run(
                          ctx,
                          () => command(ctx.base + "/jobs/" + r.id + "/retry"),
                          "Retry queued",
                        )
                      }
                    >
                      Retry
                    </button>
                  ) : null,
              },
            ]}
          />
        </Panel>
      )}
      {tab === "widget" && (
        <div className="split">
          <div className="stack">
            <Panel title="Installations">
              <div className="panel-body stack">
                {installs.length ? (
                  <label>
                    Test installation
                    <select
                      value={installation}
                      onChange={(e) => setInstallation(e.target.value)}
                    >
                      {installs.map((i) => (
                        <option key={i.id} value={i.public_id}>
                          {i.name}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : (
                  <Empty
                    title="Make your first connection"
                    text="Publish an agent and create an installation to preview its chat."
                    action={
                      <button className="btn" onClick={() => addWidget()}>
                        Create installation
                      </button>
                    }
                  />
                )}
                {installation && (
                  <>
                    <div className="row">
                      <Badge
                        value={
                          installs.find((i) => i.public_id === installation)
                            ?.enabled
                            ? "active"
                            : "disabled"
                        }
                      />
                      <button
                        className="btn small"
                        onClick={() =>
                          addWidget(
                            installs.find((i) => i.public_id === installation),
                          )
                        }
                      >
                        Edit installation
                      </button>
                      <button
                        className="btn subtle small"
                        onClick={async () => {
                          const selected = installs.find(
                            (i) => i.public_id === installation,
                          );
                          if (selected)
                            run(
                              ctx,
                              () =>
                                api(
                                  ctx.base + "/installations/" + selected.id,
                                  { method: "DELETE" },
                                ),
                              "Installation disabled",
                            );
                        }}
                      >
                        Disable
                      </button>
                    </div>
                    <label>
                      Embed snippet
                      <pre className="code mono">
                        {embedSnippet(
                          window.location.origin,
                          installs.find(
                            (i) => i.public_id === installation,
                          ) || { public_id: installation },
                        )}
                      </pre>
                    </label>
                    <button
                      className="btn"
                      onClick={() =>
                        navigator.clipboard
                          .writeText(
                            embedSnippet(
                              window.location.origin,
                              installs.find(
                                (i) => i.public_id === installation,
                              ) || { public_id: installation },
                            ),
                          )
                          .then(() => ctx.notify("Snippet copied"))
                          .catch(() =>
                            ctx.notify(
                              "Clipboard unavailable; select the snippet to copy.",
                            ),
                          )
                      }
                    >
                      <Copy size={13} />
                      Copy embed
                    </button>
                    <p className="field-note">
                      The widget ID and publishable key are public. Add your
                      site’s exact origin to the installation before embedding.
                    </p>
                    <div className="notice">
                      A widget authentication error stays inside the widget. It
                      does not sign you out of this dashboard.
                    </div>
                  </>
                )}
              </div>
            </Panel>
          </div>
          <Panel
            title="Live preview"
            note={
              ctx.capabilities.llm
                ? "Uses your connected model"
                : "Deterministic development answers · no LLM request"
            }
          >
            {installation ? (
              <WidgetChat
                dashboardPreview
                key={installation}
                publicId={installation}
                publicKey={
                  installs.find((i) => i.public_id === installation)?.theme
                    ?.publishable_key || ""
                }
              />
            ) : (
              <Empty
                title="Your chat will appear here"
                text="Select or create an installation to begin."
              />
            )}
          </Panel>
        </div>
      )}
    </>
  );
}

export function Campaigns({ ctx }: Props) {
  const [selected, setSelected] = useState<Row | null>(null),
    [attempts, setAttempts] = useState<Row[]>([]);
  function create() {
    const versions = (ctx.data.agents || []).filter(
      (a) => a.published_version_id,
    );
    ctx.form({
      title: "Create a calling campaign",
      description:
        "Start with simulation and controlled contacts. Contact import deduplicates phone numbers; repeated Start does not redial completed contacts.",
      fields: [
        { key: "name", label: "Campaign name", required: true },
        {
          key: "agent_version_id",
          label: "Published agent",
          options: versions.map((a) => ({
            value: a.published_version_id,
            label: a.name,
          })),
          required: true,
        },
        {
          key: "contacts",
          label: "Contacts · one +country-code number per line",
          type: "textarea",
          required: true,
        },
        {
          key: "timezone",
          label: "Timezone",
          value: "Asia/Kolkata",
          required: true,
        },
        {
          key: "budget_minor",
          label: "Campaign budget · minor units",
          type: "number",
          value: 1000,
          min: 1,
          required: true,
        },
      ],
      submit: "Create draft",
      action: async (values) => {
        const { contacts, ...body } = values;
        const result = await command(ctx.base + "/campaigns", {
          ...body,
          mode: "simulation",
          concurrency: 1,
          max_attempts: 1,
        });
        await command(ctx.base + "/campaigns/" + result.id + "/contacts", {
          dry_run: false,
          contacts: contacts
            .split("\n")
            .filter((x: string) => x.trim())
            .map((x: string) => ({ phone: x.trim() })),
        });
        await ctx.refresh();
        ctx.notify("Campaign draft and contacts saved");
      },
    });
  }
  async function inspectCampaign(row: Row) {
    setSelected(row);
    try {
      setAttempts(
        (await api(ctx.base + "/campaigns/" + row.id + "/attempts")).items,
      );
    } catch (e) {
      ctx.notify((e as Error).message);
    }
  }
  return (
    <>
      <Header
        eyebrow="THE RIGHT CONVERSATION, AT SCALE"
        title="Make every outreach count."
        description="Controlled dispatch, durable attempts and a clear view of what happened."
      >
        <button className="btn primary" onClick={create}>
          <Plus size={14} />
          Create campaign
        </button>
      </Header>
      <div className="notice" style={{ marginBottom: 22 }}>
        The current UI creates simulation campaigns with concurrency 1 and one
        attempt per contact. No telephone network is contacted. Live routing and
        expanded retry policies remain behind their validation gates.
      </div>
      <Panel>
        <Table
          rows={ctx.data.campaigns || []}
          columns={[
            {
              label: "CAMPAIGN",
              render: (r) => (
                <>
                  <strong>{r.name}</strong>
                  <span className="cell-sub">
                    {r.timezone} · {r.contacts.length} contacts
                  </span>
                </>
              ),
            },
            { label: "MODE", render: (r) => <Badge value={r.mode} /> },
            { label: "STATE", render: (r) => <Badge value={r.state} /> },
            {
              label: "RESULTS",
              render: (r) => (
                <>
                  {r.completed_contacts || 0} completed ·{" "}
                  {r.failed_contacts || 0} failed
                </>
              ),
            },
            {
              label: "",
              render: (r) => (
                <div className="row">
                  {["draft", "paused"].includes(r.state) && (
                    <button
                      className="btn small"
                      onClick={() =>
                        run(
                          ctx,
                          () =>
                            command(ctx.base + "/campaigns/" + r.id + "/start"),
                          "Campaign start accepted",
                        )
                      }
                    >
                      <Play size={11} />
                      Start
                    </button>
                  )}
                  {["running", "scheduled"].includes(r.state) && (
                    <button
                      className="btn small"
                      onClick={() =>
                        run(
                          ctx,
                          () =>
                            command(ctx.base + "/campaigns/" + r.id + "/pause"),
                          "Campaign paused",
                        )
                      }
                    >
                      <Pause size={11} />
                      Pause
                    </button>
                  )}
                  <button
                    className="table-action"
                    onClick={() => inspectCampaign(r)}
                  >
                    Attempts
                    <ArrowUpRight size={12} />
                  </button>
                </div>
              ),
            },
          ]}
        />
      </Panel>
      {selected && (
        <Dialog
          title={selected.name + " · Attempts"}
          close={() => setSelected(null)}
        >
          <Table
            rows={attempts}
            columns={[
              { label: "ATTEMPT", render: (r) => r.attempt_index },
              { label: "STATE", render: (r) => <Badge value={r.state} /> },
              { label: "OUTCOME", render: (r) => r.outcome || "Pending" },
              {
                label: "CALL",
                render: (r) => (
                  <span className="mono">{r.call_id?.slice(0, 8) || "—"}</span>
                ),
              },
            ]}
          />
          <button
            style={{ marginTop: 20 }}
            className="btn"
            onClick={() => inspectCampaign(selected)}
          >
            <RefreshCw size={12} />
            Refresh attempts
          </button>
        </Dialog>
      )}
    </>
  );
}

export function InboxPage({ ctx }: Props) {
  return <LiveInbox ctx={ctx} />;
}

export function Leads({ ctx }: Props) {
  function widgetEvidence(row: Row): Row | null {
    try {
      const value = JSON.parse(row.evidence);
      return value.source === "widget_email_form" ? value : null;
    } catch {
      return null;
    }
  }
  function add() {
    ctx.form({
      title: "Record a contact",
      description:
        "Keep the evidence behind a lead. Silence or a greeting alone does not qualify interest.",
      fields: [
        ...nameFields,
        { key: "email", label: "Email", type: "email" },
        { key: "phone", label: "Phone · E.164" },
        {
          key: "stage",
          label: "Stage",
          options: ["new", "qualified", "contacted", "won", "lost"].map(
            (x) => ({ value: x, label: x }),
          ),
        },
        {
          key: "evidence",
          label: "Interest / source evidence",
          type: "textarea",
          required: true,
        },
      ],
      action: async (body) => {
        await command(ctx.base + "/leads", body);
        await ctx.refresh();
        ctx.notify("Contact saved");
      },
    });
  }
  return (
    <>
      <Header
        eyebrow="PEOPLE, NOT JUST NUMBERS"
        title="Your next conversation starts here."
        description="Contacts and interest with the context to follow through."
      >
        <button className="btn primary" onClick={add}>
          <Plus size={14} />
          Add contact
        </button>
      </Header>
      <Panel>
        <Table
          rows={ctx.data.leads || []}
          columns={[
            { label: "NAME", render: (r) => <strong>{r.name}</strong> },
            {
              label: "CONTACT",
              render: (r) => <>{r.email || r.phone || "—"}</>,
            },
            { label: "STAGE", render: (r) => <Badge value={r.stage} /> },
            {
              label: "PROMOTIONAL EMAIL",
              render: (r) =>
                widgetEvidence(r)
                  ? r.email_verified && r.marketing_opt_in
                    ? "Opted in"
                    : "No opt-in"
                  : "Not recorded",
            },
            {
              label: "EVIDENCE",
              render: (r) => (
                <span
                  style={{
                    maxWidth: 350,
                    display: "block",
                    whiteSpace: "normal",
                  }}
                >
                  {widgetEvidence(r) ? (
                    <>
                      Email shared through website chat ·{" "}
                      {r.email_verified ? "verified" : "unverified"}
                      <br />
                      <Link
                        href={
                          "/app/inbox?conversation=" +
                          widgetEvidence(r)?.conversation_id
                        }
                      >
                        View conversation ↗
                      </Link>
                    </>
                  ) : (
                    r.evidence
                  )}
                </span>
              ),
            },
            { label: "ADDED", render: (r) => when(r.created_at) },
          ]}
        />
      </Panel>
    </>
  );
}

export { default as Billing } from "./billing";

export function Developer({ ctx }: Props) {
  const [tab, setTab] = useState("keys"),
    [secret, setSecret] = useState<string | null>(null);
  function addKey() {
    ctx.form({
      title: "Create a scoped API key",
      description:
        "The secret is shown once. Keep it on your server, never in a widget snippet.",
      fields: [
        ...nameFields,
        {
          key: "scopes",
          label: "Scopes · comma separated",
          value: "kb:read,calls:read,billing:read",
          required: true,
        },
        {
          key: "expires_at",
          label: "Expires at · optional",
          type: "datetime-local",
          value: "",
        },
        {
          key: "requests_per_minute",
          label: "Requests per minute · 1 to 600",
          type: "number",
          value: "60",
          required: true,
        },
      ],
      action: async (values) => {
        const result = await command(ctx.base + "/keys", {
          name: values.name,
          scopes: values.scopes.split(",").map((x: string) => x.trim()),
          expires_at: values.expires_at
            ? new Date(values.expires_at).toISOString()
            : null,
          requests_per_minute: Number(values.requests_per_minute),
        });
        setSecret(result.secret);
        await ctx.refresh();
      },
    });
  }
  function addHook(existing?: Row) {
    ctx.form({
      title: existing ? "Edit webhook endpoint" : "Create a webhook endpoint",
      description:
        "Deliveries are signed and retried with a stable semantic event ID.",
      fields: [
        {
          key: "url",
          label: "Public HTTPS endpoint",
          type: "url",
          value: existing?.url || "",
          required: true,
        },
        {
          key: "events",
          label: "Events · comma separated",
          value:
            existing?.event_types.join(",") ||
            "call.completed,ticket.created,job.completed",
          required: true,
        },
        {
          key: "enabled",
          label: "Deliver events to this endpoint",
          type: "checkbox",
          value: existing?.enabled ?? true,
        },
      ],
      action: async (values) => {
        const result = await command(
          ctx.base + "/webhooks" + (existing ? "/" + existing.id : ""),
          {
            url: values.url,
            events: values.events.split(",").map((x: string) => x.trim()),
            enabled: values.enabled,
          },
          existing ? "PUT" : "POST",
        );
        if (result.signing_secret) setSecret(result.signing_secret);
        await ctx.refresh();
      },
    });
  }
  return (
    <>
      <Header
        eyebrow="MAKE IT PART OF YOUR STACK"
        title="Built to connect."
        description="Scoped access, signed events and an API you can inspect."
      >
        <a
          href="/backend/docs"
          target="_blank"
          rel="noreferrer"
          className="btn"
        >
          <Code2 size={13} />
          Interactive API docs
        </a>
        <button
          className="btn primary"
          onClick={tab === "keys" ? addKey : () => addHook()}
        >
          <Plus size={14} />
          {tab === "keys" ? "Create API key" : "Add webhook"}
        </button>
      </Header>
      <div className="tabs">
        {["keys", "webhooks", "deliveries"].map((t) => (
          <button
            key={t}
            className={"tab " + (tab === t ? "active" : "")}
            onClick={() => setTab(t)}
          >
            {t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>
      <Panel>
        {tab === "keys" ? (
          <Table
            rows={ctx.data.keys || []}
            columns={[
              {
                label: "KEY",
                render: (r) => (
                  <>
                    <strong>{r.name}</strong>
                    <span className="cell-sub mono">{r.prefix}…</span>
                  </>
                ),
              },
              {
                label: "SCOPES",
                render: (r) => (
                  <span
                    style={{
                      maxWidth: 350,
                      display: "block",
                      whiteSpace: "normal",
                    }}
                  >
                    {r.scopes.join(", ")}
                  </span>
                ),
              },
              {
                label: "LAST USED",
                render: (r) =>
                  r.last_used_at ? when(r.last_used_at) : "Never",
              },
              {
                label: "EXPIRES",
                render: (r) =>
                  r.expires_at ? when(r.expires_at) : "No expiry",
              },
              {
                label: "LIMIT",
                render: (r) => `${r.requests_per_minute} / min`,
              },
              {
                label: "STATUS",
                render: (r) => (
                  <Badge
                    value={
                      r.revoked_at
                        ? "revoked"
                        : r.expires_at && Date.parse(r.expires_at) <= Date.now()
                          ? "expired"
                          : "active"
                    }
                  />
                ),
              },
              {
                label: "",
                render: (r) =>
                  !r.revoked_at && (
                    <button
                      className="table-action"
                      onClick={() =>
                        run(
                          ctx,
                          () =>
                            api(ctx.base + "/keys/" + r.id, {
                              method: "DELETE",
                            }),
                          "Key revoked",
                        )
                      }
                    >
                      Revoke
                    </button>
                  ),
              },
            ]}
          />
        ) : tab === "webhooks" ? (
          <Table
            rows={ctx.data.webhooks || []}
            columns={[
              {
                label: "ENDPOINT",
                render: (r) => <span className="mono">{r.url}</span>,
              },
              { label: "EVENTS", render: (r) => r.event_types.join(", ") },
              {
                label: "MANAGE",
                render: (r) => (
                  <div className="row">
                    <button className="btn small" onClick={() => addHook(r)}>
                      Edit
                    </button>
                    <button
                      className="btn subtle small"
                      disabled={!r.enabled}
                      onClick={() =>
                        run(
                          ctx,
                          () =>
                            api(ctx.base + "/webhooks/" + r.id, {
                              method: "DELETE",
                            }),
                          "Webhook disabled",
                        )
                      }
                    >
                      Disable
                    </button>
                    <button
                      className="btn subtle small"
                      onClick={() =>
                        ctx.form({
                          title: "Rotate signing secret",
                          description:
                            "Update your receiver with the new secret. Pending deliveries will use it immediately.",
                          fields: [
                            {
                              key: "confirm",
                              label: "I will update my receiver",
                              type: "checkbox",
                              required: true,
                            },
                          ],
                          action: async () => {
                            const result = await command(
                              ctx.base + "/webhooks/" + r.id + "/rotate-secret",
                            );
                            setSecret(result.signing_secret);
                          },
                        })
                      }
                    >
                      Rotate secret
                    </button>
                  </div>
                ),
              },
              {
                label: "STATUS",
                render: (r) => (
                  <Badge value={r.enabled ? "active" : "disabled"} />
                ),
              },
            ]}
          />
        ) : (
          <Table
            rows={ctx.data.deliveries || []}
            columns={[
              {
                label: "EVENT",
                render: (r) => (
                  <>
                    <strong>{r.event_type}</strong>
                    <span className="cell-sub mono">
                      {r.event_id.slice(0, 12)}
                    </span>
                  </>
                ),
              },
              { label: "ATTEMPTS", render: (r) => r.attempt },
              { label: "HTTP", render: (r) => r.http_status || "—" },
              { label: "STATE", render: (r) => <Badge value={r.state} /> },
              {
                label: "",
                render: (r) => (
                  <button
                    className="table-action"
                    onClick={() =>
                      run(
                        ctx,
                        () =>
                          command(ctx.base + "/deliveries/" + r.id + "/replay"),
                        "Replay queued",
                      )
                    }
                  >
                    Replay
                  </button>
                ),
              },
            ]}
          />
        )}
      </Panel>
      {secret && (
        <Dialog title="Save this secret now" close={() => setSecret(null)}>
          <div className="stack">
            <p className="small-text muted">
              This value will not be shown again. Store it privately.
            </p>
            <pre className="code mono">{secret}</pre>
            <button
              className="btn primary"
              onClick={() =>
                navigator.clipboard
                  .writeText(secret)
                  .then(() => ctx.notify("Secret copied"))
                  .catch(() =>
                    ctx.notify(
                      "Clipboard unavailable; select the text to copy.",
                    ),
                  )
              }
            >
              <Copy size={13} />
              Copy secret
            </button>
          </div>
        </Dialog>
      )}
    </>
  );
}

export function WorkspaceSettings({
  ctx,
  team = false,
}: Props & { team?: boolean }) {
  const [values, setValues] = useState<Row | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    api(ctx.base + "/settings")
      .then(setValues)
      .catch((e) => setError(e.message));
  }, [ctx.base]);
  const caps = ctx.capabilities;
  return (
    <>
      <Header
        eyebrow="THE WAY YOU WORK"
        title={
          team
            ? "A shared workspace. A connected team."
            : "Make the workspace yours."
        }
        description={
          team
            ? "Memberships and permissions that keep access in context."
            : "Business context and the infrastructure behind your conversations."
        }
      />
      <div className="tabs">
        <button
          className={"tab " + (!team ? "active" : "")}
          onClick={() => ctx.go("settings")}
        >
          Business & infrastructure
        </button>
        <button
          className={"tab " + (team ? "active" : "")}
          onClick={() => ctx.go("team")}
        >
          Team members
        </button>
      </div>
      {team ? (
        <Panel title="Workspace members">
          <Table
            rows={ctx.data.members || []}
            columns={[
              {
                label: "MEMBER",
                render: (r) => (
                  <>
                    <strong>{r.name}</strong>
                    <span className="cell-sub">{r.email}</span>
                  </>
                ),
              },
              { label: "ROLE", render: (r) => <Badge value={r.role} /> },
              { label: "JOINED", render: (r) => when(r.created_at) },
            ]}
          />
          <div className="panel-body notice">
            Team invitation and role-management flows are pending
            implementation. This screen shows persisted memberships; it does not
            send invitations.
          </div>
        </Panel>
      ) : (
        <div className="split">
          <Panel title="Business profile">
            {values && (
              <form
                className="panel-body"
                onSubmit={async (e) => {
                  e.preventDefault();
                  setBusy(true);
                  setError("");
                  try {
                    await command(ctx.base + "/settings", values, "PUT");
                    await ctx.refresh();
                    ctx.notify("Business settings saved");
                  } catch (e) {
                    setError((e as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <label>
                  Business name
                  <input
                    value={values.business_name || ""}
                    onChange={(e) =>
                      setValues({ ...values, business_name: e.target.value })
                    }
                    required
                  />
                </label>
                <label>
                  Industry
                  <input
                    value={values.industry || ""}
                    onChange={(e) =>
                      setValues({ ...values, industry: e.target.value })
                    }
                  />
                </label>
                <label>
                  Timezone
                  <input
                    value={values.timezone || ""}
                    onChange={(e) =>
                      setValues({ ...values, timezone: e.target.value })
                    }
                    required
                  />
                  <span className="field-note">
                    Use an IANA name, for example Asia/Kolkata.
                  </span>
                </label>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={values.notifications_enabled}
                    onChange={(e) =>
                      setValues({
                        ...values,
                        notifications_enabled: e.target.checked,
                      })
                    }
                  />
                  Enable workspace notifications
                </label>
                {error && <div className="error">{error}</div>}
                <button className="btn primary" disabled={busy}>
                  {busy ? "Saving…" : "Save business settings"}
                </button>
              </form>
            )}
          </Panel>
          <div className="stack">
            <Panel
              title="Your chosen infrastructure"
              note="Status reflects configuration, not a completed live health check."
            >
              <div className="panel-body">
                {[
                  {
                    name: "Transactional data",
                    detail:
                      caps.database === "postgresql"
                        ? "Supabase PostgreSQL"
                        : "SQLite development fallback",
                    ready: caps.database === "postgresql",
                  },
                  {
                    name: "Object storage",
                    detail:
                      caps.object_storage === "azure"
                        ? "Azure Blob Storage"
                        : "Local development fallback",
                    ready: caps.object_storage === "azure",
                  },
                  {
                    name: "Knowledge retrieval",
                    detail: caps.retrieval || "Loading",
                    ready: caps.retrieval === "qdrant-hybrid",
                  },
                  {
                    name: "Embeddings",
                    detail: "text-embedding-3-small · 1,536 dimensions",
                    ready: caps.retrieval === "qdrant-hybrid",
                  },
                  {
                    name: "Reasoning",
                    detail: caps.model,
                    ready: caps.llm,
                  },
                  {
                    name: "Voice replies",
                    detail: caps.voice_model || caps.model,
                    ready: caps.live_voice,
                  },
                  {
                    name: "Speech generation",
                    detail:
                      (caps.voice_provider === "sarvam"
                        ? "Sarvam "
                        : "Fish Audio ") + caps.tts_model,
                    ready: caps.tts,
                  },
                  {
                    name: "Live recognition",
                    detail: caps.stt_model || "Recognition provider",
                    ready: caps.stt,
                  },
                  {
                    name: "Telephone network",
                    detail:
                      caps.telephony_providers?.join(" / ") || "Plivo / Twilio",
                    ready: caps.telephony,
                  },
                ].map((item) => (
                  <div className="provider-row" key={item.name}>
                    <div>
                      <strong>{item.name}</strong>
                      <small>{item.detail}</small>
                    </div>
                    <Badge value={item.ready ? "configured" : "needs_setup"} />
                  </div>
                ))}
              </div>
            </Panel>
            <div className="notice">
              Server credentials belong in the private .env file or deployment
              secret store. They are never returned to this browser. Supabase is
              configured on this server; provider keys stay private and are
              never returned in these status checks.
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export function Connections({ ctx }: Props) {
  const [detail, setDetail] = useState<Row | null>(null);
  const names: Record<
    string,
    { mark: string; description: string; setup: string }
  > = {
    google_calendar: {
      mark: "G",
      description: "Availability and confirmed appointments.",
      setup:
        "Google OAuth application, callback URL, token storage and booking reconciliation must be implemented and tested before this connection becomes active.",
    },
    hubspot: {
      mark: "H",
      description: "Bring conversation context to your CRM.",
      setup:
        "HubSpot OAuth/private-app access and remote contact mapping are required. Local lead capture is available; remote CRM sync is not enabled.",
    },
    whatsapp: {
      mark: "W",
      description: "Continue conversations on WhatsApp.",
      setup:
        "Requires a WhatsApp Business account, approved sender/templates and verified delivery callbacks. No messages are sent by this release.",
    },
    sms: {
      mark: "S",
      description: "A timely message, on the right channel.",
      setup:
        "Requires an approved SMS sender and applicable India DLT configuration. Sending is disabled until provider integration tests pass.",
    },
    mcp: {
      mark: "M",
      description: "Connect reviewed tools to your agents.",
      setup:
        "Review allowed tools and server/network access before adding MCP credentials. Arbitrary model-generated tools are not permitted.",
    },
  };
  return (
    <>
      <Header
        eyebrow="GOOD TOGETHER"
        title="Connect the rest of your business."
        description="Real connection states. No pretend setup success."
      />
      <div className="resource-grid">
        {(ctx.data.connections || []).map((connection) => (
          <section
            className="resource-card integration-card"
            key={connection.id}
          >
            <div className="card-top">
              <div className="logo-mark">
                {names[connection.provider]?.mark || "↗"}
              </div>
              <Badge value={connection.state} />
            </div>
            <h3>{connection.name}</h3>
            <p>{names[connection.provider]?.description}</p>
            <button className="btn small" onClick={() => setDetail(connection)}>
              Connection requirements
              <ArrowUpRight size={12} />
            </button>
          </section>
        ))}
      </div>
      {detail && (
        <Dialog title={detail.name} close={() => setDetail(null)}>
          <div className="stack">
            <Badge value={detail.state} />
            <p className="small-text muted">{names[detail.provider]?.setup}</p>
            <div className="notice">
              This external adapter is not connected. The application will not
              claim a booking, message delivery or remote sync without provider
              confirmation.
            </div>
          </div>
        </Dialog>
      )}
    </>
  );
}

export function Appointments({ ctx }: Props) {
  const [bookings, setBookings] = useState<Row[]>([]);
  const localAppointments = (ctx.data.appointments || []).filter(
    (row) =>
      ["local", "canceled"].includes(row.state) &&
      !bookings.some((booking) => booking.appointment_id === row.id),
  );
  useEffect(() => {
    api(ctx.base + "/scheduling-bookings")
      .then((result) => setBookings(result.items))
      .catch(() => {});
  }, [ctx.base, ctx.data.appointments]);
  async function refreshBooking(booking: Row) {
    try {
      await command(
        ctx.base + "/scheduling-bookings/" + booking.booking_id + "/refresh",
        {},
      );
      setBookings((await api(ctx.base + "/scheduling-bookings")).items);
      await ctx.refresh();
      ctx.notify("Booking status checked");
    } catch (error) {
      ctx.notify(
        error instanceof Error
          ? error.message
          : "Could not check booking status",
      );
    }
  }
  function create() {
    ctx.form({
      title: "Record a local appointment",
      description:
        "This saves a workspace appointment and checks local slot overlap. To book through Cal.com or Calendly, enable scheduling on your agent.",
      fields: [
        { key: "title", label: "Appointment title", required: true },
        {
          key: "start",
          label: "Start · local time",
          type: "datetime-local",
          required: true,
        },
        {
          key: "end",
          label: "End · local time",
          type: "datetime-local",
          required: true,
        },
        {
          key: "timezone",
          label: "Display timezone",
          value: ctx.workspace.timezone,
          required: true,
        },
      ],
      submit: "Record local booking",
      action: async (values) => {
        await command(
          ctx.base + "/appointments",
          {
            ...values,
            start: new Date(values.start).toISOString(),
            end: new Date(values.end).toISOString(),
          },
          "POST",
          true,
        );
        await ctx.refresh();
        ctx.notify("Local appointment recorded");
      },
    });
  }
  return (
    <>
      <Header
        eyebrow="MAKE TIME FOR THE NEXT STEP"
        title="Appointments."
        description="Scheduled conversations, with the timezone in plain view."
      >
        <button className="btn primary" onClick={create}>
          <Plus size={14} />
          Record appointment
        </button>
      </Header>
      <Panel
        title="Agent booking requests"
        className="section-gap booking-history"
      >
        <Table
          rows={bookings}
          columns={[
            { label: "MEETING", render: (row) => <strong>{row.event}</strong> },
            {
              label: "PROVIDER",
              render: (row) =>
                row.provider === "calcom" ? "Cal.com" : "Calendly",
            },
            {
              label: "START",
              render: (row) => (
                <>
                  {new Date(row.start).toLocaleString("en-IN", {
                    day: "numeric",
                    month: "short",
                    hour: "2-digit",
                    minute: "2-digit",
                    timeZone: row.timezone,
                  })}
                  <span className="cell-sub">{row.timezone}</span>
                </>
              ),
            },
            {
              label: "STATUS",
              render: (row) => (
                <>
                  <Badge value={row.state} />
                  {row.message && (
                    <span className="cell-sub">{row.message}</span>
                  )}
                </>
              ),
            },
            {
              label: "",
              render: (row) => (
                <div className="row">
                  {[
                    "submitting",
                    "unknown",
                    "pending_approval",
                    "confirmed",
                  ].includes(row.state) && (
                    <button
                      className="table-action"
                      onClick={() => refreshBooking(row)}
                    >
                      Check status
                    </button>
                  )}
                  {row.manage_url && (
                    <a
                      className="table-action"
                      href={row.manage_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Manage at provider <ArrowUpRight size={12} />
                    </a>
                  )}
                </div>
              ),
            },
          ]}
        />
      </Panel>
      {(!bookings.length || localAppointments.length > 0) && (
        <Panel title="Workspace appointments">
          <Table
            rows={localAppointments}
            columns={[
              {
                label: "APPOINTMENT",
                render: (r) => <strong>{r.title}</strong>,
              },
              { label: "START", render: (r) => when(r.start_at) },
              { label: "END", render: (r) => when(r.end_at) },
              { label: "TIMEZONE", render: (r) => r.timezone },
              { label: "STATUS", render: (r) => <Badge value={r.state} /> },
              {
                label: "",
                render: (r) =>
                  r.state !== "canceled" && (
                    <button
                      className="table-action"
                      onClick={() =>
                        run(
                          ctx,
                          () =>
                            command(
                              ctx.base + "/appointments/" + r.id + "/cancel",
                            ),
                          "Appointment canceled",
                        )
                      }
                    >
                      Cancel
                    </button>
                  ),
              },
            ]}
          />
        </Panel>
      )}
    </>
  );
}

export function Numbers({ ctx }: Props) {
  const [hook, setHook] = useState<Row | null>(null);
  const [requestingTrial, setRequestingTrial] = useState(false);
  const trial = ctx.summary.phone_trial;
  async function startTrial() {
    if (requestingTrial) return;
    setRequestingTrial(true);
    try {
      await command(ctx.base + "/phone-trial", {});
      await ctx.refresh();
      ctx.notify("We’re assigning your seven-day trial number.");
    } catch (error) {
      ctx.notify(
        error instanceof Error
          ? error.message
          : "Your trial could not start. Please try again.",
      );
    } finally {
      setRequestingTrial(false);
    }
  }
  function testTrial() {
    ctx.form({
      title: "Try your agent on the phone",
      description: `Your assigned number is ${trial.number}. Each test can last up to ${trial.seconds_per_call} seconds and uses one trial call.`,
      fields: [
        {
          key: "agent_id",
          label: "Published agent",
          required: true,
          options: (ctx.data.agents || [])
            .filter((a) => a.published_version_id)
            .map((a) => ({ value: a.id, label: a.name })),
        },
        {
          key: "destination",
          label: "Verified test destination",
          required: true,
          options: (trial.destinations || []).map((phone: string) => ({
            value: phone,
            label: phone,
          })),
        },
      ],
      submit: "Call my test number",
      action: async (values) => {
        await command(
          ctx.base + "/calls/outbound",
          {
            ...values,
            mode: "live",
            number_id: trial.number_id,
            budget_minor: 1,
          },
          "POST",
          true,
        );
        await ctx.refresh();
        ctx.notify("Test call queued. Your phone will ring shortly.");
      },
    });
  }
  function register() {
    ctx.form({
      title: "Register an owned phone number",
      description:
        "This does not buy a number. The worker checks ownership and voice capability using configured Plivo or Twilio credentials. Without credentials it remains unverified.",
      fields: [
        {
          key: "provider",
          label: "Carrier",
          value: "plivo",
          options: [
            { value: "plivo", label: "Plivo" },
            { value: "twilio", label: "Twilio" },
          ],
        },
        { key: "e164", label: "Owned number · E.164", required: true },
        {
          key: "can_inbound",
          label: "Request inbound verification",
          type: "checkbox",
          value: true,
        },
        {
          key: "can_outbound",
          label: "Request outbound verification",
          type: "checkbox",
          value: true,
        },
      ],
      submit: "Register and verify",
      action: async (values) => {
        await command(ctx.base + "/numbers", values);
        await ctx.refresh();
        ctx.notify("Number registered");
      },
    });
  }
  function route(number: Row) {
    ctx.form({
      title: "Attach an inbound agent",
      fields: [
        {
          key: "agent_id",
          label: "Published agent",
          options: (ctx.data.agents || [])
            .filter((x) => x.published_version_id)
            .map((x) => ({ value: x.id, label: x.name })),
          required: true,
        },
      ],
      action: async (values) => {
        await command(
          ctx.base + "/numbers/" + number.id + "/route",
          values,
          "PUT",
        );
        await ctx.refresh();
        ctx.notify("Inbound route saved");
      },
    });
  }
  return (
    <>
      <Header
        eyebrow="A DIRECT LINE TO YOUR BUSINESS"
        title="Your phone numbers."
        description="Owned numbers, verified capabilities and one clear inbound route."
      >
        <button className="btn primary" onClick={register}>
          <Plus size={14} />
          Register owned number
        </button>
      </Header>
      {trial?.offer_visible && !trial.number_id && (
        <Panel title="Your seven-day phone trial" className="phone-trial-panel">
          <div className="stack phone-trial-body" aria-live="polite">
            <p>{trial.message}</p>
            {trial.status === "not_assigned" ? (
              <div>
                <button
                  className="btn primary"
                  disabled={
                    !trial.can_request ||
                    requestingTrial ||
                    !["owner", "admin"].includes(ctx.workspace.role)
                  }
                  onClick={startTrial}
                >
                  <Phone size={14} />{" "}
                  {requestingTrial
                    ? "Starting your trial…"
                    : "Start free phone trial"}
                </button>
              </div>
            ) : (
              <div className="row">
                <Badge value={trial.status} />
                <button
                  className="btn"
                  onClick={() => run(ctx, ctx.refresh, "Trial status updated")}
                >
                  <RefreshCw size={14} /> Check status
                </button>
              </div>
            )}
            <p className="small-text">
              We assign your number automatically. Trial calls use a limited
              allowance and approved test destinations.
            </p>
            {!["owner", "admin"].includes(ctx.workspace.role) && (
              <p className="small-text">
                Ask your workspace owner or administrator to start the trial.
              </p>
            )}
          </div>
        </Panel>
      )}
      {trial?.number_id && (
        <Panel title="Your phone trial" className="phone-trial-panel">
          <div
            className="stack phone-trial-body"
            aria-label="Phone trial allowance"
          >
            <div className="row">
              <Badge value={trial.status} />
              <strong>{trial.number}</strong>
            </div>
            <p>{trial.message}</p>
            <p className="small-text">
              {trial.calls_remaining} of {trial.max_calls} calls remaining · Up
              to {trial.seconds_per_call} seconds per call
            </p>
            <p className="small-text">Ends {when(trial.expires_at)}</p>
            <div>
              <button
                className="btn primary"
                onClick={testTrial}
                disabled={
                  trial.status !== "active" ||
                  !trial.destinations?.length ||
                  !ctx.capabilities.telephony ||
                  !ctx.capabilities.live_voice ||
                  !(ctx.data.agents || []).some((a) => a.published_version_id)
                }
              >
                <Phone size={14} /> Make a trial call
              </button>
            </div>
            {trial.status === "active" && !ctx.capabilities.live_voice && (
              <p className="small-text">
                Your voice services need to be connected before a phone test.
              </p>
            )}
            {trial.status === "active" && !trial.destinations?.length && (
              <p className="small-text">
                Contact support to approve your verified test destination before
                calling.
              </p>
            )}
            <p className="small-text">
              For calls to your approved test numbers. Your workspace wallet is
              not charged for this allowance.
            </p>
          </div>
        </Panel>
      )}
      <div className="notice" style={{ marginBottom: 22 }}>
        Have your own number? Connect your carrier, then register the number
        here to use it with your agents.
      </div>
      <Panel>
        <Table
          rows={ctx.data.numbers || []}
          columns={[
            { label: "NUMBER", render: (r) => <strong>{r.e164}</strong> },
            { label: "PROVIDER", render: (r) => r.provider },
            {
              label: "CAPABILITIES",
              render: (r) => (
                <>
                  {r.can_inbound ? "Inbound " : ""}
                  {r.can_outbound ? "Outbound" : ""}
                </>
              ),
            },
            { label: "STATUS", render: (r) => <Badge value={r.status} /> },
            {
              label: "INBOUND AGENT",
              render: (r) =>
                (ctx.data.agents || []).find((a) => a.id === r.agent_id)
                  ?.name || "Not attached",
            },
            {
              label: "",
              render: (r) => (
                <div className="row">
                  <button
                    className="btn small"
                    disabled={!r.can_inbound || r.status !== "active"}
                    onClick={() => route(r)}
                  >
                    Attach agent
                  </button>
                  <button className="table-action" onClick={() => setHook(r)}>
                    Webhook URLs
                  </button>
                </div>
              ),
            },
          ]}
        />
      </Panel>
      {hook && (
        <Dialog
          title={hook.provider + " · Carrier webhooks"}
          close={() => setHook(null)}
        >
          <div className="stack">
            <p className="small-text">
              Paste these POST URLs into the owned number’s voice configuration.
              Carrier signatures are required.
            </p>
            {["answer", hook.provider === "twilio" ? "status" : "hangup"].map(
              (path) => (
                <label key={path}>
                  {path === "answer" ? "Incoming call" : "Call status"}
                  <div className="mono code">
                    {ctx.capabilities.public_webhook_origin +
                      "/v1/provider-webhooks/" +
                      hook.provider +
                      "/" +
                      path}
                  </div>
                  <button
                    className="btn small"
                    onClick={() =>
                      navigator.clipboard
                        .writeText(
                          ctx.capabilities.public_webhook_origin +
                            "/v1/provider-webhooks/" +
                            hook.provider +
                            "/" +
                            path,
                        )
                        .then(() => ctx.notify("Webhook URL copied"))
                    }
                  >
                    <Copy size={12} />
                    Copy URL
                  </button>
                </label>
              ),
            )}
            {!ctx.capabilities.public_webhook_origin?.startsWith(
              "https://",
            ) && (
              <div className="notice">
                Configure a public HTTPS MEDIA_PUBLIC_ORIGIN before connecting a
                real provider. This local URL is not externally reachable.
              </div>
            )}
            <a className="btn" href="/docs#phone">
              Carrier integration guide
              <ArrowUpRight size={13} />
            </a>
          </div>
        </Dialog>
      )}
    </>
  );
}

export function Templates({ ctx }: Props) {
  const templates = [
    {
      name: "Customer care",
      category: "SUPPORT",
      description:
        "Answer business questions, acknowledge missing knowledge and record support requests.",
      instructions:
        "Help customers using only connected business knowledge. Keep answers concise. When information is missing, explain the gap and offer a support ticket.",
    },
    {
      name: "Product guide",
      category: "COMMERCE",
      description:
        "Help a shopper find a fit with verified product prices and customization facts.",
      instructions:
        "Guide shoppers with verified catalog and knowledge facts. Never invent availability, discounts or return policies. Ask one useful clarification before making recommendations.",
    },
    {
      name: "Appointment assistant",
      category: "SCHEDULING",
      description:
        "Understand the request and collect details without inventing a confirmed booking.",
      instructions:
        "Help a customer understand appointment options. Do not promise availability or confirmation without a successful booking tool result. Offer a recorded follow-up request when the calendar is disconnected.",
    },
  ];
  async function use(template: Row) {
    try {
      const result = await command(ctx.base + "/agents", {
        name: template.name,
      });
      const config = {
        ...result.draft_config,
        instructions: template.instructions,
      };
      await command(
        ctx.base + "/agents/" + result.id + "/draft",
        { expected_revision: result.draft_revision, config },
        "PUT",
      );
      await ctx.refresh();
      ctx.go("agents/" + result.id);
    } catch (e) {
      ctx.notify((e as Error).message);
    }
  }
  return (
    <>
      <Header
        eyebrow="A USEFUL PLACE TO BEGIN"
        title="A head start for your next agent."
        description="Original starting points. Make them specific to your business before publishing."
      />
      <div className="resource-grid">
        {templates.map((t) => (
          <section className="resource-card" key={t.name}>
            <div className="card-top">
              <span className="resource-icon">
                <AudioLines size={20} />
              </span>
              <span className="eyebrow muted" style={{ fontSize: 8 }}>
                {t.category}
              </span>
            </div>
            <h3>{t.name}</h3>
            <p>{t.description}</p>
            <button className="btn" onClick={() => use(t)}>
              Use this starting point
              <ArrowUpRight size={12} />
            </button>
          </section>
        ))}
      </div>
    </>
  );
}
