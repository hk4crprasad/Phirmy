"use client";
import { useEffect, useState } from "react";
import { Trash2, Archive, RefreshCw } from "lucide-react";
import { api, command, Row, when } from "@/lib/api";
import { Dialog, Panel, Badge, StudioContext } from "./ui";

export default function AgentDeleteButton({
  ctx,
  agent,
}: {
  ctx: StudioContext;
  agent: Row;
}) {
  const [open, setOpen] = useState(false),
    [preview, setPreview] = useState<Row | null>(null),
    [confirmation, setConfirmation] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [showAll, setShowAll] = useState(false);
  useEffect(() => {
    if (!open) return;
    let active = true;
    setPreview(null);
    setShowAll(false);
    setConfirmation("");
    setError("");
    api(ctx.base + "/agents/" + agent.id + "/deletion-preview")
      .then((result) => {
        if (active) setPreview(result);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [open, ctx.base, agent.id]);
  if (!["owner", "admin"].includes(ctx.workspace.role)) return null;
  async function remove(archive = false) {
    setBusy(true);
    setError("");
    try {
      await command(
        ctx.base + "/agents/" + agent.id + (archive ? "/archive" : "/delete"),
        archive ? {} : { confirmation },
      );
      setOpen(false);
      ctx.go(archive ? "agents" : "operations");
      await ctx.refresh();
      ctx.notify(
        archive
          ? "Agent archived; its history is preserved."
          : "Agent disabled. Track permanent data deletion in Operations.",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <button
        className="btn subtle"
        aria-label={"Delete agent " + agent.name}
        onClick={() => setOpen(true)}
      >
        <Trash2 size={15} />
        Delete agent
      </button>
      {open && (
        <Dialog
          title="Delete agent and data"
          close={() => {
            if (!busy) setOpen(false);
          }}
        >
          <div className="stack" style={{ gap: 20 }}>
            <p>
              Permanently delete <strong>{agent.name}</strong> and its
              exclusively owned data. Its widgets will stop working immediately.
              This cannot be undone.
            </p>
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
            {!preview && !error && <p role="status">Checking related data…</p>}
            {preview && (
              <>
                <dl
                  style={{
                    display: "grid",
                    gridTemplateColumns: "minmax(0,1fr) auto",
                    gap: "8px 20px",
                    margin: 0,
                  }}
                >
                  {Object.entries(preview.counts)
                    .filter(([, count]) => showAll || Number(count) > 0)
                    .map(([key, count]) => (
                      <div key={key} style={{ display: "contents" }}>
                        <dt>
                          {(
                            {
                              kb_ids: "Knowledge bases",
                              installations: "Widgets",
                              websites: "Website assistants",
                              versions: "Published versions",
                              bookings: "Booking records",
                              stores: "Product stores",
                            } as Row
                          )[key] ||
                            key.charAt(0).toUpperCase() +
                              key.slice(1).replaceAll("_", " ")}
                        </dt>
                        <dd style={{ margin: 0 }}>{String(count)}</dd>
                      </div>
                    ))}
                </dl>
                <button
                  type="button"
                  className="text-button"
                  style={{ textAlign: "left" }}
                  onClick={() => setShowAll(!showAll)}
                >
                  {showAll
                    ? "Show affected categories only"
                    : "Show all data categories"}
                </button>
                <div className="notice">
                  <strong>Kept safe</strong>
                  <p>
                    Shared knowledge ({preview.shared_knowledge_preserved}),
                    workspace resources, billing and audit records, and phone
                    numbers are preserved. Numbers are unassigned. External
                    meetings and previously exported data are not deleted.
                  </p>
                </div>
                {!!preview.blockers.length && (
                  <div className="error" role="alert">
                    {preview.blockers.join(" ")}
                  </div>
                )}
                <label>
                  Type the agent name to confirm
                  <input
                    aria-label="Agent name to confirm deletion"
                    value={confirmation}
                    onChange={(e) => setConfirmation(e.target.value)}
                    autoComplete="off"
                    spellCheck={false}
                    disabled={busy}
                  />
                </label>
                <p className="muted">
                  Storage and search-index cleanup runs as a background task. If
                  a provider is unavailable, Operations shows the failure and
                  lets an owner retry.
                </p>
              </>
            )}
            <div
              className="row"
              style={{ justifyContent: "flex-end", flexWrap: "wrap" }}
            >
              <button
                className="btn"
                disabled={busy}
                onClick={() => setOpen(false)}
              >
                Cancel
              </button>
              <button
                className="btn"
                disabled={busy}
                onClick={() => remove(true)}
              >
                <Archive size={14} />
                Archive instead
              </button>
              <button
                className="btn"
                style={{ background: "var(--danger)", color: "var(--white)" }}
                disabled={
                  busy ||
                  !preview ||
                  !!preview.blockers.length ||
                  confirmation !== agent.name
                }
                onClick={() => remove()}
              >
                <Trash2 size={14} />
                {busy ? "Submitting…" : "Delete permanently"}
              </button>
            </div>
          </div>
        </Dialog>
      )}
    </>
  );
}

export function AgentDeletionJobs({ ctx }: { ctx: StudioContext }) {
  const [jobs, setJobs] = useState<Row[]>([]),
    [error, setError] = useState("");
  useEffect(() => {
    let active = true,
      timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const result = await api(ctx.base + "/jobs");
        if (active) {
          setJobs(
            result.items.filter((job: Row) => job.kind === "agent_delete"),
          );
          setError("");
        }
      } catch (e) {
        if (active) setError((e as Error).message);
      } finally {
        if (active) timer = setTimeout(load, 2500);
      }
    }
    load();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [ctx.base]);
  return (
    <Panel
      title="Agent data deletion"
      note="Confirmed deletions continue after you leave this page."
    >
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {!jobs.length && !error && (
        <p className="muted">No agent deletion tasks.</p>
      )}
      {jobs.map((job) => (
        <div
          key={job.id}
          style={{ padding: "16px 0", borderBottom: "1px solid var(--line)" }}
        >
          <div className="row between">
            <strong>Deletion {job.id.slice(0, 8)}</strong>
            <Badge value={job.state} />
          </div>
          <p>
            {job.state === "completed"
              ? "Agent and owned data deleted."
              : job.phase.replaceAll("_", " ")}
          </p>
          <small className="muted">{when(job.created_at)}</small>
          {job.error && (
            <p className="error" role="alert">
              {job.error}
            </p>
          )}
          {job.state === "failed" &&
            ["owner", "admin"].includes(ctx.workspace.role) && (
              <button
                className="btn small"
                onClick={async () => {
                  try {
                    await command(ctx.base + "/jobs/" + job.id + "/retry", {});
                    ctx.notify("Deletion retry queued");
                    setJobs((old) =>
                      old.map((row) =>
                        row.id === job.id
                          ? { ...row, state: "queued", error: null }
                          : row,
                      ),
                    );
                  } catch (e) {
                    setError((e as Error).message);
                  }
                }}
              >
                <RefreshCw size={14} />
                Retry deletion
              </button>
            )}
        </div>
      ))}
    </Panel>
  );
}
