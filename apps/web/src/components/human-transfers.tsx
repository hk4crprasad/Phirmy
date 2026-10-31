"use client";
import { useEffect, useRef, useState } from "react";
import { api, command, Row, when } from "@/lib/api";
import { Badge, Panel, StudioContext, Table } from "./ui";

export function HumanTransfers({ ctx }: { ctx: StudioContext }) {
  const [policy, setPolicy] = useState<Row | null>(null);
  const [review, setReview] = useState<Row | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [verified, setVerified] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const target = useRef(ctx.base);
  target.current = ctx.base;
  const [loadedBase, setLoadedBase] = useState("");
  async function reload() {
    const base = ctx.base;
    const outcomes = await Promise.allSettled([
      api(ctx.base + "/transfer-policy"),
      api("/v1/operator/transfers/" + ctx.workspace.id + "/policy"),
      api(ctx.base + "/call-transfers"),
    ]);
    if (target.current !== base) return;
    setLoadedBase(base);
    setPolicy(outcomes[0].status === "fulfilled" ? outcomes[0].value : null);
    setReview(outcomes[1].status === "fulfilled" ? outcomes[1].value : null);
    setRows(outcomes[2].status === "fulfilled" ? outcomes[2].value.items : []);
    setVerified(false);
  }
  useEffect(() => { void reload(); }, [ctx.base]);
  function configure() {
    ctx.form({
      title: "Staff destination for live transfer",
      description: "Use a staff number your team controls. Changes require fresh operator approval before any transfer. Callbacks remain manual inbox requests.",
      fields: [
        { key: "destination", label: "Staff phone with country code", required: true },
        { key: "label", label: "Team name read to the caller", value: policy?.label || "Support team", required: true },
        { key: "maximum_seconds", label: "Maximum staff-leg duration in seconds", type: "number", value: policy?.maximum_seconds || 120, min: 5, max: 300, required: true },
      ],
      submit: "Save for approval",
      action: async (values) => {
        await command(ctx.base + "/transfer-policy", { ...values, maximum_seconds: Number(values.maximum_seconds), enabled: true }, "PUT");
        await reload();
        ctx.notify("Staff destination saved; operator approval required");
      },
    });
  }
  async function approval(approved: boolean) {
    setBusy(true); setError("");
    try {
      await command("/v1/operator/transfers/" + ctx.workspace.id + "/approval", {
        revision: review?.revision, approved, verified_staff: verified,
      });
      await reload();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  if (loadedBase !== ctx.base || (!policy && !rows.length)) return null;
  return (
    <Panel title="Human transfer">
      {policy && <div className="panel-body">
        <p>Phone callers can request a confirmed transfer to your approved staff destination. A connection is shown as confirmed only after carrier evidence.</p>
        <p>{policy.configured ? `${policy.label} · ending ${policy.destination_last4} · up to ${policy.maximum_seconds}s` : "No staff destination configured."}</p>
        <Badge value={policy.approved ? "approved" : "needs_approval"} />
        {!policy.live_activation_enabled && <p className="field-note">Live transfer activation is off. You can prepare the destination and review prior requests.</p>}
        <button className="btn" onClick={configure}>Set staff destination</button>
        {review?.configured && <div className="notice">
          <p>Operator review: {review.destination} · {review.label}</p>
          <label className="checkbox-label"><input type="checkbox" checked={verified} onChange={(e) => setVerified(e.target.checked)} />I verified that this number belongs to the staff team.</label>
          <button className="btn" disabled={busy || !verified} onClick={() => approval(true)}>Approve destination</button>{" "}
          <button className="btn" disabled={busy || !review.approved} onClick={() => approval(false)}>Revoke approval</button>
        </div>}
        {error && <p role="alert">{error}</p>}
      </div>}
      <Table rows={rows} columns={[
        { label: "REQUESTED", render: (row) => when(row.created_at) },
        { label: "CARRIER", render: (row) => row.provider },
        { label: "STATE", render: (row) => <Badge value={row.state} /> },
        { label: "CONNECTION", render: (row) => row.connection_confirmed ? "Confirmed" : "Not confirmed" },
        { label: "STAFF LEG", render: (row) => row.child_bill_ms === null ? "Awaiting carrier duration" : `${row.child_bill_ms / 1000}s` },
      ]} />
    </Panel>
  );
}
