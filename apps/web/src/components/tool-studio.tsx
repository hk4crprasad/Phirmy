"use client";
import { useState } from "react";
import {
  Plus,
  ArrowUpRight,
  RefreshCw,
  Search,
  Terminal,
  FlaskConical,
  ShieldCheck,
  Copy,
} from "lucide-react";
import { api, command, Row, when } from "@/lib/api";
import { Header, Panel, Table, Badge, Dialog, StudioContext } from "./ui";
const empty = {
  name: "",
  description: "",
  method: "POST",
  url: "",
  arguments: {
    type: "object",
    properties: {},
    required: [],
    additionalProperties: false,
  },
  body_template: {},
  timeout_seconds: 15,
  execution_mode: "wait_for_result",
  error_handling: "hide",
  side_effecting: true,
  approval_policy: "always_confirm",
  public_response_fields: [],
};
export default function ToolStudio({ ctx }: { ctx: StudioContext }) {
  const [editor, setEditor] = useState<Row | null>(null),
    [tab, setTab] = useState("content"),
    [curl, setCurl] = useState(""),
    [headers, setHeaders] = useState(""),
    [schema, setSchema] = useState("{}"),
    [body, setBody] = useState("{}"),
    [mock, setMock] = useState(""),
    [testArgs, setTestArgs] = useState("{}"),
    [testResult, setTestResult] = useState<Row | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [query, setQuery] = useState(""),
    [agents, setAgents] = useState<string[]>([]),
    [executions, setExecutions] = useState<Row[]>(
      ctx.data["tool-executions"] || [],
    );
  function open(row: Row) {
    setEditor(row);
    setSchema(JSON.stringify(row.arguments, null, 2));
    setBody(JSON.stringify(row.body_template || {}, null, 2));
    setMock(
      row.mock_response ? JSON.stringify(row.mock_response, null, 2) : "",
    );
    setHeaders("");
    setCurl("");
    setTab("content");
    setError("");
    setTestResult(null);
    setAgents(
      (ctx.data.agents || [])
        .filter((a) =>
          Boolean(
            a.draft_config?.tools?.some((t: Row) => t.tool_id === row.id),
          ),
        )
        .map((a) => a.id),
    );
  }
  async function parse() {
    setError("");
    try {
      const parsed = await command(ctx.base + "/tools/import-curl", {
        text: curl,
      });
      setEditor((old) => ({ ...old, ...parsed }));
      setSchema(JSON.stringify(parsed.arguments, null, 2));
      setBody(JSON.stringify(parsed.body_template || {}, null, 2));
      setHeaders(JSON.stringify(parsed.headers, null, 2));
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function save() {
    if (!editor) return;
    setBusy(true);
    setError("");
    try {
      const values = {
        name: editor.name,
        description: editor.description,
        method: editor.method,
        url: editor.url,
        arguments: JSON.parse(schema),
        body_template: body.trim() ? JSON.parse(body) : null,
        ...(headers.trim() ? { headers: JSON.parse(headers) } : {}),
        timeout_seconds: Number(editor.timeout_seconds),
        execution_mode: editor.execution_mode,
        error_handling: editor.error_handling,
        side_effecting: editor.side_effecting,
        approval_policy: editor.approval_policy || "always_confirm",
        public_response_fields: String(
          editor._responseFields ??
            (editor.public_response_fields || []).join(", "),
        )
          .split(",")
          .map((value: string) => value.trim())
          .filter(Boolean),
        mock_response: mock.trim() ? JSON.parse(mock) : null,
      };
      const row = await command(
        ctx.base + "/tools" + (editor.id ? "/" + editor.id : ""),
        values,
        editor.id ? "PUT" : "POST",
      );
      setEditor(row);
      await ctx.refresh();
      ctx.notify("Tool saved · revision " + row.revision);
      setTab("access");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function runTest(useMock: boolean) {
    if (!editor?.id) return;
    setBusy(true);
    setError("");
    try {
      setTestResult(
        await command(
          ctx.base + "/tools/" + editor.id + "/test",
          { arguments: JSON.parse(testArgs), mock: useMock },
          "POST",
          true,
        ),
      );
      setExecutions((await api(ctx.base + "/tool-executions")).items);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Header
        title="Give your agent a way to act."
        description="Your endpoints. Declared arguments. A result you can inspect."
      >
        <a className="btn" href="/docs#tools">
          Developer guide
          <ArrowUpRight size={13} />
        </a>
        <button className="btn primary" onClick={() => open({ ...empty })}>
          <Plus size={14} />
          Add HTTP tool
        </button>
      </Header>
      <div className="toolbar">
        <div className="searchbox">
          <Search size={14} />
          <input
            aria-label="Search tools"
            placeholder="Find a tool…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      </div>
      <div className="resource-grid">
        {(ctx.data.tools || [])
          .filter((x) => x.name.toLowerCase().includes(query.toLowerCase()))
          .map((tool) => (
            <button
              className="resource-card"
              style={{ textAlign: "left", color: "inherit" }}
              key={tool.id}
              onClick={() => open(tool)}
            >
              <div className="card-top">
                <span className="resource-icon">
                  <Terminal size={20} />
                </span>
                <Badge value={tool.enabled ? "enabled" : "disabled"} />
              </div>
              <h3>{tool.name}</h3>
              <p>{tool.description}</p>
              <div className="card-bottom">
                <span>
                  {tool.method} · revision {tool.revision}
                </span>
                <ArrowUpRight size={14} />
              </div>
            </button>
          ))}
      </div>
      <Panel
        className="section-gap"
        title="Execution history"
        note="Queued and accepted requests do not imply the action completed."
      >
        <Table
          rows={executions}
          columns={[
            {
              label: "TOOL",
              render: (r) => (
                <strong>
                  {(ctx.data.tools || []).find((x) => x.id === r.tool_id)
                    ?.name || r.tool_id.slice(0, 8)}
                </strong>
              ),
            },
            { label: "STATUS", render: (r) => <Badge value={r.state} /> },
            { label: "HTTP", render: (r) => r.result?.http_status || "—" },
            {
              label: "TIME",
              render: (r) =>
                r.elapsed_ms != null ? r.elapsed_ms + " ms" : "Pending",
            },
            { label: "DATE", render: (r) => when(r.created_at) },
          ]}
        />
      </Panel>
      {editor && (
        <Dialog
          title={
            editor.id ? editor.name + " · Tool studio" : "Connect an HTTP tool"
          }
          close={() => setEditor(null)}
        >
          <div className="tabs">
            {["content", "access", "test"].map((t) => (
              <button
                className={"tab " + (t === tab ? "active" : "")}
                key={t}
                disabled={t !== "content" && !editor.id}
                onClick={() => setTab(t)}
              >
                {t[0].toUpperCase() + t.slice(1)}
              </button>
            ))}
          </div>
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
          {tab === "content" && (
            <div className="stack">
              <details>
                <summary
                  style={{ cursor: "pointer", fontSize: 13, marginBottom: 14 }}
                >
                  Import a cURL request
                </summary>
                <label>
                  Request
                  <textarea
                    className="mono"
                    placeholder={
                      'curl -X POST https://api.example.com/orders -H "Content-Type: application/json" -d \'{"order_id":"{{order_id}}"}\''
                    }
                    value={curl}
                    onChange={(e) => setCurl(e.target.value)}
                  />
                </label>
                <button
                  type="button"
                  className="btn"
                  onClick={parse}
                  style={{ marginTop: 12 }}
                >
                  Parse request
                  <Terminal size={14} />
                </button>
                <p className="field-note" style={{ marginTop: 10 }}>
                  Import reads the command as configuration. It does not execute
                  shell commands or read local files.
                </p>
              </details>
              <label>
                Tool name
                <input
                  value={editor.name}
                  disabled={Boolean(editor.id)}
                  placeholder="lookup_order"
                  onChange={(e) =>
                    setEditor({ ...editor, name: e.target.value })
                  }
                />
              </label>
              <label>
                When should the agent use this tool?
                <textarea
                  value={editor.description}
                  onChange={(e) =>
                    setEditor({ ...editor, description: e.target.value })
                  }
                />
              </label>
              <div className="form-grid">
                <label>
                  Method
                  <select
                    value={editor.method}
                    onChange={(e) =>
                      setEditor({ ...editor, method: e.target.value })
                    }
                  >
                    {["GET", "POST", "PUT", "PATCH", "DELETE"].map((x) => (
                      <option key={x}>{x}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Timeout · seconds
                  <input
                    type="number"
                    min={1}
                    max={120}
                    value={editor.timeout_seconds}
                    onChange={(e) =>
                      setEditor({
                        ...editor,
                        timeout_seconds: Number(e.target.value),
                      })
                    }
                  />
                </label>
              </div>
              <label>
                Public endpoint URL
                <input
                  value={editor.url}
                  placeholder="https://api.example.com/orders/{{order_id}}"
                  onChange={(e) =>
                    setEditor({ ...editor, url: e.target.value })
                  }
                />
              </label>
              <label>
                Arguments · JSON Schema
                <textarea
                  className="mono"
                  value={schema}
                  onChange={(e) => setSchema(e.target.value)}
                />
              </label>
              <label>
                Request body · JSON template
                <textarea
                  className="mono"
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                />
              </label>
              <label>
                Headers · JSON object
                <textarea
                  className="mono"
                  value={headers}
                  placeholder={'{"Authorization":"Bearer YOUR_TOKEN"}'}
                  onChange={(e) => setHeaders(e.target.value)}
                />
                <span className="field-note">
                  Saved header values are write-only and encrypted. Leave blank
                  to preserve existing values.
                </span>
              </label>
              <div className="form-grid">
                <label>
                  Execution
                  <select
                    value={editor.execution_mode}
                    onChange={(e) =>
                      setEditor({ ...editor, execution_mode: e.target.value })
                    }
                  >
                    <option value="wait_for_result">Wait for result</option>
                    <option value="background">
                      Background · result on a later turn
                    </option>
                    <option value="fire_and_forget">
                      Fire and forget · audit only
                    </option>
                  </select>
                </label>
                <label>
                  Errors
                  <select
                    value={editor.error_handling}
                    onChange={(e) =>
                      setEditor({ ...editor, error_handling: e.target.value })
                    }
                  >
                    <option value="hide">Hide response details</option>
                    <option value="passthrough">
                      Return response to agent
                    </option>
                  </select>
                </label>
              </div>
              <label>
                Visitor confirmation policy
                <select
                  value={editor.approval_policy || "always_confirm"}
                  onChange={(event) =>
                    setEditor({
                      ...editor,
                      approval_policy: event.target.value,
                    })
                  }
                >
                  <option value="always_confirm">
                    Always request confirmation
                  </option>
                  <option value="approved_read_only">
                    Approved read-only GET lookup
                  </option>
                </select>
              </label>
              <label>
                Public response fields · comma separated
                <input
                  value={
                    editor._responseFields ??
                    (editor.public_response_fields || []).join(", ")
                  }
                  onChange={(event) =>
                    setEditor({
                      ...editor,
                      _responseFields: event.target.value,
                    })
                  }
                  placeholder="status, available"
                />
                <span className="field-note">
                  Only approved fields reach the assistant. Personal data and
                  credentials remain redacted. Approve automatic lookups only
                  when the endpoint cannot change data.
                </span>
              </label>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={editor.side_effecting}
                  onChange={(e) =>
                    setEditor({ ...editor, side_effecting: e.target.checked })
                  }
                />
                This request can change data or trigger an action
              </label>
              <label>
                Optional mock response · JSON
                <textarea
                  className="mono"
                  value={mock}
                  onChange={(e) => setMock(e.target.value)}
                  placeholder={'{"order_status":"example only"}'}
                />
              </label>
              <button className="btn primary" disabled={busy} onClick={save}>
                {busy ? "Saving…" : "Save tool"}
                <ArrowUpRight size={14} />
              </button>
            </div>
          )}
          {tab === "access" && (
            <div className="stack">
              <p className="small-text muted">
                Attach this revision to agent drafts. Publish those agents to
                activate it. Existing calls keep their published tool
                definitions.
              </p>
              {(ctx.data.agents || []).map((a) => (
                <label className="checkbox-label" key={a.id}>
                  <input
                    type="checkbox"
                    checked={agents.includes(a.id)}
                    onChange={(e) =>
                      setAgents(
                        e.target.checked
                          ? [...agents, a.id]
                          : agents.filter((x) => x !== a.id),
                      )
                    }
                  />
                  {a.name}
                </label>
              ))}
              <button
                className="btn primary"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await command(
                      ctx.base + "/tools/" + editor.id + "/access",
                      { agent_ids: agents },
                      "PUT",
                    );
                    await ctx.refresh();
                    ctx.notify("Agent drafts updated · publish to activate");
                  } catch (e) {
                    setError((e as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Save agent access
                <ShieldCheck size={14} />
              </button>
              <button
                className="table-action"
                onClick={async () => {
                  await command(ctx.base + "/tools/" + editor.id, {}, "DELETE");
                  setEditor(null);
                  await ctx.refresh();
                }}
              >
                Disable this tool for all agents
              </button>
            </div>
          )}
          {tab === "test" && (
            <div className="stack">
              <label>
                Test arguments · JSON
                <textarea
                  className="mono"
                  value={testArgs}
                  onChange={(e) => setTestArgs(e.target.value)}
                />
              </label>
              <p className="field-note">
                Send request makes a real HTTP request. Use mock to test the
                interface without contacting the endpoint.
              </p>
              <div className="row">
                <button
                  className="btn"
                  disabled={busy}
                  onClick={() => runTest(true)}
                >
                  <FlaskConical size={14} />
                  Use mock
                </button>
                <button
                  className="btn primary"
                  disabled={busy}
                  onClick={() => runTest(false)}
                >
                  Send request
                  <ArrowUpRight size={14} />
                </button>
              </div>
              {testResult && (
                <pre
                  className="mono code"
                  style={{ maxHeight: 320, overflow: "auto" }}
                >
                  {JSON.stringify(testResult, null, 2)}
                </pre>
              )}
            </div>
          )}
        </Dialog>
      )}
    </>
  );
}
