"use client";
import { useCallback, useEffect, useState } from "react";
import { api, APIError, command, money, Row, when } from "@/lib/api";
import { Badge, Dialog, Panel, StudioContext, Table } from "../ui";
import { UnitEconomics } from "./unit-economics";

export function OperatorBilling({ ctx }: { ctx: StudioContext }) {
  const [report, setReport] = useState<Row | null>(null);
  const [letters, setLetters] = useState<Row>({ webhooks: [], jobs: [] });
  const [economics, setEconomics] = useState<Row | null>(null);
  const [days, setDays] = useState("30"),
    [search, setSearch] = useState("");
  const [cursor, setCursor] = useState(""),
    [error, setError] = useState("");
  const [selected, setSelected] = useState<Row | null>(null);
  const [paused, setPaused] = useState(false),
    [cap, setCap] = useState("");
  const [reason, setReason] = useState(""),
    [busy, setBusy] = useState(false);
  const [orderId, setOrderId] = useState(""),
    [refund, setRefund] = useState("");
  const [refundKey, setRefundKey] = useState("");
  const refresh = useCallback(async () => {
    try {
      const [r, d, e] = await Promise.all([
        api(
          "/v1/operator/billing?" +
            new URLSearchParams({ days, after: cursor, search }),
        ),
        api("/v1/operator/billing/dead-letters"),
        api("/v1/operator/billing/unit-economics"),
      ]);
      setReport(r);
      setLetters(d);
      setEconomics(e);
    } catch (e) {
      if (e instanceof APIError && e.status === 403) {
        setReport(null);
        return;
      }
      setError((e as Error).message);
    }
  }, [days, cursor, search]);
  useEffect(() => {
    refresh();
  }, [refresh]);
  async function act(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await work();
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (!report) return error ? <p className="error">{error}</p> : null;
  function select(row: Row) {
    setSelected(row);
    setPaused(row.operator_paused);
    setCap(
      row.spend_cap_minor == null ? "" : String(row.spend_cap_minor / 100),
    );
    setReason("");
    setOrderId("");
    setRefund("");
    setRefundKey(crypto.randomUUID());
  }
  const columns = [
    {
      label: "Workspace",
      render: (r: Row) => (
        <button className="table-action" onClick={() => select(r)}>
          {r.name}
        </button>
      ),
    },
    {
      label: "Plan / spending",
      render: (r: Row) => (
        <>
          <span>{r.plan} </span>
          <Badge
            value={
              r.operator_paused
                ? "Paused by operator"
                : r.billing_blocked
                  ? "Billing review"
                  : "Open"
            }
          />
        </>
      ),
    },
    {
      label: "Net receipts",
      render: (r: Row) => money(r.recognized_receipts_minor),
    },
    {
      label: "Provider estimate",
      render: (r: Row) => money(r.provider_cost_micro_minor / 1e6),
    },
    {
      label: "Contribution",
      render: (r: Row) => money(r.contribution_micro_minor / 1e6),
    },
    {
      label: "Outstanding / unknown",
      render: (r: Row) => (
        <>
          {money(r.outstanding_cost_micro_minor / 1e6)} ·{" "}
          {r.unreported_usage_records} usage /{" "}
          {r.unreported_payment_fee_receipts} payment fees unreported
        </>
      ),
    },
  ];
  return (
    <Panel
      className="operator-billing"
      title="Operator billing"
      note="Restricted operator access · DRAFT estimates in INR"
    >
      <p>{report.basis}</p>
      {economics && <UnitEconomics report={economics} />}
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      <div className="row">
        <label>
          Window
          <select
            aria-label="Operator reporting window"
            value={days}
            onChange={(e) => {
              setDays(e.target.value);
              setCursor("");
            }}
          >
            <option value="7">7 days</option>
            <option value="30">30 days</option>
            <option value="90">90 days</option>
          </select>
        </label>
        <label>
          Find workspace
          <input
            aria-label="Find operator workspace"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setCursor("");
            }}
          />
        </label>
        <button className="btn" onClick={() => refresh()}>
          Refresh operator data
        </button>
      </div>
      <h3>Top provider consumers</h3>
      <Table
        rows={report.top_consumers}
        columns={columns}
        empty="No measured provider spending"
      />
      <h3>Workspaces</h3>
      <Table rows={report.items} columns={columns} />
      <div className="row">
        <button
          className="btn"
          disabled={!cursor}
          onClick={() => setCursor("")}
        >
          First page
        </button>
        <button
          className="btn"
          disabled={!report.next_cursor}
          onClick={() => setCursor(report.next_cursor)}
        >
          Next workspaces
        </button>
      </div>
      <h3>Webhook dead letters</h3>
      <p>
        Retries preserve the original encrypted receipt. Resolve missing
        identity, configuration or provider evidence before retrying.
      </p>
      <Table
        rows={letters.webhooks}
        empty="No failed webhook receipts"
        columns={[
          {
            label: "Receipt",
            render: (r) => <span className="mono">{r.id}</span>,
          },
          {
            label: "Failure",
            render: (r) => (
              <>
                {r.error_code} · {r.attempts} attempts
              </>
            ),
          },
          { label: "Received", render: (r) => when(r.created_at) },
          {
            label: "",
            render: (r) => (
              <button
                className="table-action"
                onClick={() =>
                  ctx.form({
                    title: "Retry billing receipt",
                    fields: [
                      {
                        key: "reason",
                        label: "Resolution evidence",
                        required: true,
                      },
                    ],
                    action: async (value: Row) =>
                      act(async () => {
                        await command(
                          `/v1/operator/billing/workspaces/${ctx.workspace.id}/webhooks/${r.id}/retry`,
                          value,
                        );
                        ctx.notify(
                          "Original receipt queued for reconciliation",
                        );
                      }),
                  })
                }
              >
                Review retry
              </button>
            ),
          },
        ]}
      />
      <h3>Failed financial jobs</h3>
      <Table
        rows={letters.jobs}
        empty="No failed financial jobs"
        columns={[
          { label: "Job", render: (r) => <span className="mono">{r.id}</span> },
          { label: "Kind", render: (r) => r.kind },
          {
            label: "Workspace",
            render: (r) => <span className="mono">{r.workspace_id}</span>,
          },
          { label: "Attempts", render: (r) => r.attempts },
          {
            label: "",
            render: (r) => (
              <button
                className="table-action"
                onClick={() =>
                  ctx.form({
                    title: "Retry financial job",
                    fields: [
                      {
                        key: "reason",
                        label: "Resolution evidence",
                        required: true,
                      },
                    ],
                    action: async (value: Row) =>
                      act(async () => {
                        await command(
                          `/v1/operator/billing/workspaces/${r.workspace_id}/jobs/${r.id}/retry`,
                          value,
                        );
                        ctx.notify(
                          "Original financial job queued for reconciliation",
                        );
                      }),
                  })
                }
              >
                Review retry
              </button>
            ),
          },
        ]}
      />
      {selected && (
        <Dialog
          title={"Spending controls · " + selected.name}
          close={() => setSelected(null)}
        >
          <div className="stack">
            <label>
              <input
                type="checkbox"
                checked={paused}
                onChange={(e) => setPaused(e.target.checked)}
              />{" "}
              Pause new spending and stop active provider streams at their next
              safety check
            </label>
            <label>
              Monthly provider cap (INR; blank uses plan default)
              <input
                type="number"
                min="0"
                step="0.01"
                value={cap}
                onChange={(e) => setCap(e.target.value)}
              />
            </label>
            <label>
              Reason / review evidence
              <textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                minLength={10}
                maxLength={500}
              />
            </label>
            <button
              className="btn primary"
              disabled={busy || reason.trim().length < 10}
              onClick={() =>
                act(async () => {
                  const minor =
                    cap === "" ? null : Math.round(Number(cap) * 100);
                  if (minor !== null && (!Number.isFinite(minor) || minor < 0))
                    throw Error("Enter a valid nonnegative cap.");
                  await command(
                    `/v1/operator/billing/workspaces/${selected.id}/control`,
                    { paused, spend_cap_minor: minor, reason },
                    "PUT",
                  );
                  setSelected(null);
                  ctx.notify("Spending controls saved and audited");
                })
              }
            >
              Save spending controls
            </button>
            <p>
              Resuming operator spending keeps payment reviews and unknown cost
              holds in force.
            </p>
            {selected.subscription_state === "refund_review" && (
              <>
                <p>
                  Reviewed subscription refunds cancel future billing. End
                  refunded coverage after the provider confirms cancellation and
                  all refunds settle.
                </p>
                <button
                  className="btn"
                  disabled={busy || reason.trim().length < 10}
                  onClick={() =>
                    act(async () => {
                      await command(
                        `/v1/operator/billing/workspaces/${selected.id}/resolve-refund-review`,
                        { reason },
                      );
                      setSelected(null);
                      ctx.notify(
                        "Refunded coverage ended; workspace moved to Free",
                      );
                    })
                  }
                >
                  End refunded coverage
                </button>
              </>
            )}
            {report.refunds_enabled && (
              <>
                <h3>Reviewed refund exception</h3>
                <p>
                  This can refund subscription fees or spent credit. Spent
                  credit creates an adjustment; subscription coverage enters
                  billing review.
                </p>
                <label>
                  Local payment receipt ID
                  <input
                    value={orderId}
                    onChange={(e) => {
                      setOrderId(e.target.value);
                      setRefundKey(crypto.randomUUID());
                    }}
                  />
                </label>
                <label>
                  Gross refund (INR)
                  <input
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={refund}
                    onChange={(e) => {
                      setRefund(e.target.value);
                      setRefundKey(crypto.randomUUID());
                    }}
                  />
                </label>
                <button
                  className="btn danger"
                  disabled={
                    busy ||
                    reason.trim().length < 10 ||
                    !orderId ||
                    Number(refund) <= 0
                  }
                  onClick={() =>
                    act(async () => {
                      await api(
                        `/v1/operator/billing/workspaces/${selected.id}/payments/${encodeURIComponent(orderId)}/refunds`,
                        {
                          method: "POST",
                          headers: { "Idempotency-Key": refundKey },
                          body: JSON.stringify({
                            amount_minor: Math.round(Number(refund) * 100),
                            reason,
                          }),
                        },
                      );
                      setSelected(null);
                      ctx.notify(
                        "Reviewed refund queued; provider confirmation is pending",
                      );
                    })
                  }
                >
                  Queue reviewed refund
                </button>
              </>
            )}
          </div>
        </Dialog>
      )}
    </Panel>
  );
}
