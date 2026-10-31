"use client";
import { useState } from "react";
import { Plus, ArrowUpRight, FlaskConical } from "lucide-react";
import { command, Row } from "@/lib/api";
import { Header, Panel, Table, Badge, Dialog, StudioContext } from "./ui";
const empty = {
  name: "",
  model: "",
  base_url: "https://api.openai.com/v1",
  api_key: "",
  api_style: "chat_completions",
  token_parameter: "max_completion_tokens",
  reasoning_effort: "",
  temperature: "",
  documentation_url:
    "https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create",
};
export default function ModelStudio({ ctx }: { ctx: StudioContext }) {
  const [editor, setEditor] = useState<Row | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [result, setResult] = useState<Row | null>(null);
  async function submit(save: boolean) {
    setBusy(true);
    setError("");
    try {
      const body = {
        ...editor,
        temperature:
          editor?.temperature === "" ? null : Number(editor?.temperature),
        reasoning_effort: editor?.reasoning_effort || null,
      };
      const r = await command(
        ctx.base + "/models" + (save ? "" : "/test"),
        body,
      );
      setResult(r);
      if (save) {
        setEditor(null);
        await ctx.refresh();
        ctx.notify("Model profile saved after streaming test");
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Header
        title="Your model. Your voice agent."
        description="Bring an OpenAI-compatible endpoint. Verify its documented settings before use."
      >
        <button
          className="btn primary"
          onClick={() => {
            setEditor({ ...empty });
            setError("");
            setResult(null);
          }}
        >
          <Plus size={14} />
          Add model
        </button>
      </Header>
      <Panel
        title="Server default"
        note="Configured privately through environment variables"
      >
        <div className="panel-body">
          <strong>{ctx.capabilities.model}</strong>
          <p className="field-note" style={{ marginTop: 10 }}>
            OPENAI_BASE_URL, OPENAI_MODEL and OPENAI_API_STYLE select the server
            default. Temperature is omitted unless explicitly configured in a
            documented profile.
          </p>
        </div>
      </Panel>
      <Panel className="section-gap" title="Custom profiles">
        <Table
          rows={ctx.data.models || []}
          columns={[
            {
              label: "PROFILE",
              render: (r) => (
                <>
                  <strong>{r.name}</strong>
                  <span className="cell-sub">{r.model}</span>
                </>
              ),
            },
            {
              label: "API",
              render: (r) => (
                <>
                  {r.api_style}
                  <span className="cell-sub">{r.token_parameter}</span>
                </>
              ),
            },
            {
              label: "VERIFICATION",
              render: (r) => (
                <>
                  <Badge value={r.research?.status} />
                  <span className="cell-sub">
                    {r.research?.probe?.first_token_ms} ms first token
                  </span>
                </>
              ),
            },
            {
              label: "",
              render: (r) => (
                <button
                  className="table-action"
                  onClick={async () => {
                    await command(ctx.base + "/models/" + r.id, {}, "DELETE");
                    await ctx.refresh();
                  }}
                >
                  Disable
                </button>
              ),
            },
          ]}
        />
      </Panel>
      <p className="field-note" style={{ marginTop: 20 }}>
        Select a saved profile in an agent’s Voice & behavior tab, then publish.
        Keys are encrypted, write-only, and never included in an agent
        configuration or browser embed.
      </p>
      {editor && (
        <Dialog title="Connect a model endpoint" close={() => setEditor(null)}>
          <div className="stack">
            {[
              { key: "name", label: "Profile name" },
              { key: "model", label: "Exact model ID" },
              {
                key: "base_url",
                label: "Base URL · including /v1 if required",
              },
              { key: "api_key", label: "API key", type: "password" },
              {
                key: "documentation_url",
                label: "Provider / model documentation URL",
              },
            ].map((field) => (
              <label key={field.key}>
                {field.label}
                <input
                  type={field.type || "text"}
                  value={editor[field.key]}
                  onChange={(e) =>
                    setEditor({ ...editor, [field.key]: e.target.value })
                  }
                />
              </label>
            ))}
            <div className="form-grid">
              <label>
                API protocol
                <select
                  value={editor.api_style}
                  onChange={(e) =>
                    setEditor({
                      ...editor,
                      api_style: e.target.value,
                      token_parameter:
                        e.target.value === "responses"
                          ? "max_output_tokens"
                          : "max_completion_tokens",
                    })
                  }
                >
                  <option value="chat_completions">Chat Completions</option>
                  <option value="responses">Responses</option>
                </select>
              </label>
              <label>
                Documented output cap
                <select
                  value={editor.token_parameter}
                  onChange={(e) =>
                    setEditor({ ...editor, token_parameter: e.target.value })
                  }
                >
                  {(editor.api_style === "responses"
                    ? ["max_output_tokens", "none"]
                    : ["max_completion_tokens", "max_tokens", "none"]
                  ).map((x) => (
                    <option key={x} value={x}>
                      {x === "none" ? "Omit parameter" : x}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Reasoning effort · optional
                <input
                  placeholder="Omit unless supported"
                  value={editor.reasoning_effort}
                  onChange={(e) =>
                    setEditor({ ...editor, reasoning_effort: e.target.value })
                  }
                />
              </label>
              <label>
                Temperature · optional
                <input
                  type="number"
                  min={0}
                  max={2}
                  step={0.1}
                  placeholder="Omitted by default"
                  value={editor.temperature}
                  onChange={(e) =>
                    setEditor({ ...editor, temperature: e.target.value })
                  }
                />
              </label>
            </div>
            <p className="field-note">
              The server reads the documentation URL and checks the selected
              parameter names. Review model-specific restrictions in that
              source. The connection test sends one small streaming turn with an
              inert tool schema.
            </p>
            {error && (
              <div className="error" role="alert">
                {error}
              </div>
            )}
            {result && (
              <pre className="mono code">{JSON.stringify(result, null, 2)}</pre>
            )}
            <div className="row">
              <button
                className="btn"
                disabled={busy}
                onClick={() => submit(false)}
              >
                <FlaskConical size={14} />
                Run test
              </button>
              <button
                className="btn primary"
                disabled={busy}
                onClick={() => submit(true)}
              >
                {busy ? "Checking…" : "Test and save"}
                <ArrowUpRight size={14} />
              </button>
            </div>
          </div>
        </Dialog>
      )}
    </>
  );
}
