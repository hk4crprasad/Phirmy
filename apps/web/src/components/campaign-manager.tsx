"use client";
import { useState } from "react";
import {
  Plus,
  Play,
  Pause,
  Square,
  ArrowUpRight,
  RefreshCw,
} from "lucide-react";
import { api, command, Row, when, money } from "@/lib/api";
import { Header, Panel, Table, Badge, Dialog, StudioContext } from "./ui";
export default function CampaignManager({ ctx }: { ctx: StudioContext }) {
  const [selected, setSelected] = useState<Row | null>(null),
    [attempts, setAttempts] = useState<Row[]>([]);
  function create() {
    const versions = (ctx.data.agents || []).filter(
      (a) => a.published_version_id,
    );
    ctx.form({
      title: "Start a useful conversation",
      description:
        "Set a budget, a local calling window and a bounded retry policy. Only busy or unanswered calls are retried automatically.",
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
          key: "mode",
          label: "Mode",
          value: "simulation",
          options: [
            { value: "simulation", label: "Simulation · no phone calls" },
            ...(ctx.capabilities.telephony
              ? [
                  {
                    value: "live",
                    label: "Live · controlled destination allowlist",
                  },
                ]
              : []),
          ],
        },
        {
          key: "number_id",
          label: "Owned caller number",
          options: [
            { value: "", label: "Default caller" },
            ...(ctx.data.numbers || [])
              .filter((x) => x.status === "active" && x.can_outbound)
              .map((x) => ({ value: x.id, label: x.e164 })),
          ],
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
          value: ctx.workspace.timezone,
          required: true,
        },
        {
          key: "scheduled_at",
          label: "Start later · local time",
          type: "datetime-local",
        },
        {
          key: "concurrency",
          label: "Concurrent calls",
          type: "number",
          value: 1,
          min: 1,
          max: 8,
        },
        {
          key: "max_attempts",
          label: "Maximum attempts per contact",
          type: "number",
          value: 1,
          min: 1,
          max: 5,
        },
        {
          key: "retry_delay_seconds",
          label: "Retry delay · seconds",
          type: "number",
          value: 300,
          min: 30,
          max: 86400,
        },
        {
          key: "calling_hour_start",
          label: "Calling window starts · hour",
          type: "number",
          value: 9,
          min: 0,
          max: 23,
        },
        {
          key: "calling_hour_end",
          label: "Calling window ends · hour",
          type: "number",
          value: 21,
          min: 1,
          max: 24,
        },
        {
          key: "budget_minor",
          label: "Total campaign budget · minor units",
          type: "number",
          value: 1000,
          min: 1,
          required: true,
        },
      ],
      submit: "Create campaign draft",
      action: async (values) => {
        const { contacts, scheduled_at, number_id, ...body } = values;
        const result = await command(ctx.base + "/campaigns", {
          ...body,
          scheduled_at: scheduled_at
            ? new Date(scheduled_at).toISOString()
            : null,
          number_id: number_id || null,
        });
        const imported = await command(
          ctx.base + "/campaigns/" + result.id + "/contacts",
          {
            dry_run: false,
            contacts: contacts
              .split("\n")
              .filter((x: string) => x.trim())
              .map((x: string) => ({ phone: x.trim() })),
          },
        );
        await ctx.refresh();
        ctx.notify(
          imported.accepted +
            " contacts saved · " +
            imported.duplicates +
            " duplicates removed",
        );
      },
    });
  }
  async function inspect(row: Row) {
    setSelected(row);
    try {
      setAttempts(
        (await api(ctx.base + "/campaigns/" + row.id + "/attempts")).items,
      );
    } catch (e) {
      ctx.notify((e as Error).message);
    }
  }
  async function action(row: Row, commandName: string) {
    try {
      await command(ctx.base + "/campaigns/" + row.id + "/" + commandName);
      await ctx.refresh();
    } catch (e) {
      ctx.notify((e as Error).message);
    }
  }
  return (
    <>
      <Header
        title="The next conversation starts here."
        description="Scheduled outreach, controlled budgets and a record of every attempt."
      >
        <button className="btn primary" onClick={create}>
          <Plus size={14} />
          Create campaign
        </button>
      </Header>
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
                    {r.contacts.length} contacts · {r.timezone}
                  </span>
                </>
              ),
            },
            {
              label: "POLICY",
              render: (r) => (
                <>
                  {r.concurrency} at a time · {r.max_attempts} attempts
                  <span className="cell-sub">
                    {money(r.budget_minor)} total cap
                  </span>
                </>
              ),
            },
            {
              label: "STATUS",
              render: (r) => (
                <>
                  <Badge value={r.state} />
                  <span className="cell-sub">{r.mode}</span>
                </>
              ),
            },
            {
              label: "RESULTS",
              render: (r) => (
                <>
                  {r.completed_contacts || 0} complete ·{" "}
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
                      onClick={() => action(r, "start")}
                    >
                      <Play size={12} />
                      Start
                    </button>
                  )}
                  {["running", "scheduled"].includes(r.state) && (
                    <button
                      className="btn small"
                      onClick={() => action(r, "pause")}
                    >
                      <Pause size={12} />
                      Pause
                    </button>
                  )}
                  {!["completed", "canceled"].includes(r.state) && (
                    <button
                      className="table-action"
                      onClick={() => action(r, "cancel")}
                    >
                      <Square size={11} />
                      Cancel
                    </button>
                  )}
                  <button className="table-action" onClick={() => inspect(r)}>
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
                  <a
                    href={
                      "/backend" + ctx.base + "/calls/" + r.call_id + "/export"
                    }
                    className="table-action"
                  >
                    Transcript
                    <ArrowUpRight size={12} />
                  </a>
                ),
              },
            ]}
          />
          <button
            className="btn"
            style={{ marginTop: 16 }}
            onClick={() => inspect(selected)}
          >
            <RefreshCw size={13} />
            Refresh
          </button>
        </Dialog>
      )}
      <p className="field-note" style={{ marginTop: 20 }}>
        Calling windows apply to live outreach in the campaign’s timezone.
        Simulation exercises dispatch and accounting without contacting a phone
        network.
      </p>
    </>
  );
}
