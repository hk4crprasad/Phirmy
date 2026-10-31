"use client";
import Link from "next/link";
import {
  AudioLines,
  Bot,
  BookOpen,
  Phone,
  ArrowUpRight,
  Plus,
  Ticket,
  Check,
} from "lucide-react";
import { command, Row } from "@/lib/api";
import { Header, Panel, Empty, Badge, Table, StudioContext } from "./ui";
import QuickStart from "./quick-start";
import ProductTour from "./product-tour";
type Props = { ctx: StudioContext; pending?: boolean };
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
export default function Dashboard({ ctx, pending = false }: Props) {
  const stats = [
    {
      title: "Total conversations",
      value: ctx.summary.calls || 0,
      note: "All voice sessions",
      icon: Phone,
    },
    {
      title: "Published agents",
      value: ctx.summary.published_agents || 0,
      note: (ctx.summary.agents || 0) + " agents in your workspace",
      icon: Bot,
    },
    {
      title: "Connected minutes",
      value: Math.round((ctx.summary.connected_seconds || 0) / 60),
      note: "Actual connected session time",
      icon: AudioLines,
    },
    {
      title: "Open support tickets",
      value: ctx.summary.open_tickets || 0,
      note: "Waiting for your team",
      icon: Ticket,
    },
  ];
  const daily = ctx.summary.daily_calls || [],
    max = Math.max(...daily.map((x: Row) => x.count), 1);
  return (
    <>
      <Header
        eyebrow="YOUR CONVERSATION WORKSPACE"
        title={
          "A little more connected, " +
          ((ctx.user?.name || "there").trim().split(/\s+/)[0] || "there") +
          "."
        }
        description="Your agents, conversations and next possibilities. All in one place."
      >
        <button className="btn" onClick={() => ctx.go("knowledge")}>
          <BookOpen size={14} />
          Add knowledge
        </button>
        <button className="btn primary" onClick={() => ctx.go("agents")}>
          <Plus size={15} />
          Create agent
        </button>
      </Header>
      {!pending && <QuickStart ctx={ctx} />}
      <div className="stats-grid">
        {stats.map((stat) => (
          <div className="stat" key={stat.title}>
            <div className="stat-top">
              {stat.title}
              <span className="stat-icon">
                <stat.icon size={13} />
              </span>
            </div>
            <div className="stat-value">{stat.value.toLocaleString()}</div>
            <div className="stat-note">{stat.note}</div>
          </div>
        ))}
      </div>
      {pending ? (
        <div className="workspace-page-loading" role="status">
          <p>Loading recent activity…</p>
          <div className="skeleton" />
        </div>
      ) : (
        <div className="dashboard-grid">
          <div className="stack">
            <Panel
              title="Conversation activity"
              note="A view of the last 14 days"
              action={<span className="badge">Voice sessions</span>}
            >
              <div className="activity-chart">
                {daily.map((day: Row, i: number) => (
                  <div
                    key={day.date}
                    className={
                      "chart-bar " + (i === daily.length - 1 ? "today" : "")
                    }
                    title={day.date + ": " + day.count + " calls"}
                    style={{ height: Math.max((day.count / max) * 142, 2) }}
                  >
                    <span>{new Date(day.date).getDate()}</span>
                  </div>
                ))}
                {!daily.some((d: Row) => d.count) && (
                  <div className="chart-empty">
                    Your first conversation starts the story.
                  </div>
                )}
              </div>
            </Panel>
            <Panel
              title="Recent conversations"
              note="Every call has a story. Pick up the details."
              action={
                <Link href="/app/calls" className="table-action">
                  View all
                  <ArrowUpRight size={12} />
                </Link>
              }
            >
              <Table
                rows={(ctx.data.calls || []).slice(0, 4)}
                empty="Ready for your first conversation"
                columns={[
                  {
                    label: "AGENT",
                    render: (r) => <strong>{r.agent_name}</strong>,
                  },
                  {
                    label: "CHANNEL",
                    render: (r) => (
                      <>
                        {r.transport}
                        <span className="cell-sub">{r.mode}</span>
                      </>
                    ),
                  },
                  { label: "STATUS", render: (r) => <Badge value={r.state} /> },
                  {
                    label: "DURATION",
                    render: (r) => Math.round(r.connected_ms / 1000) + "s",
                  },
                ]}
              />
            </Panel>
          </div>
          <div className="stack">
            <section className="panel getting-started">
              <div className="eyebrow">FROM ZERO TO HELLO</div>
              <h2>
                Your first agent.
                <br />
                Three small steps.
              </h2>
              <p>
                Give it context. Give it a voice.
                <br />
                Then see where the conversation goes.
              </p>
              {[
                {
                  label: "Connect your knowledge",
                  done: (ctx.data.knowledge || []).some(
                    (x) => x.status === "ready",
                  ),
                  to: "knowledge",
                },
                {
                  label: "Publish your first agent",
                  done: (ctx.summary.published_agents || 0) > 0,
                  to: "agents",
                },
                {
                  label: "Start a test conversation",
                  done: (ctx.summary.calls || 0) > 0,
                  to: "voice",
                },
              ].map((step, i) => (
                <div className="setup-step" key={step.label}>
                  <span className={"step-circle " + (step.done ? "done" : "")}>
                    {step.done ? <Check size={10} /> : i + 1}
                  </span>
                  {step.label}
                  <Link href={"/app/" + step.to}>
                    <ArrowUpRight size={13} />
                  </Link>
                </div>
              ))}
            </section>
            <ProductTour card />
            <Panel
              title="Your agents"
              action={
                <Link href="/app/agents" className="table-action">
                  <ArrowUpRight size={13} />
                </Link>
              }
            >
              {(ctx.data.agents || []).length ? (
                (ctx.data.agents || []).slice(0, 3).map((agent) => (
                  <Link
                    href={"/app/agents/" + agent.id}
                    key={agent.id}
                    className="agent-line"
                  >
                    <span className="agent-avatar">
                      <AudioLines size={17} />
                    </span>
                    <div>
                      <strong>{agent.name}</strong>
                      <small>
                        {ctx.capabilities.voice_provider === "sarvam"
                          ? "Sarvam voice"
                          : "Fish Audio"}{" "}
                        ·{" "}
                        {ctx.capabilities.voice_model ||
                          ctx.capabilities.model ||
                          "Connected model"}
                      </small>
                    </div>
                    <Badge
                      value={agent.published_version_id ? "published" : "draft"}
                    />
                  </Link>
                ))
              ) : (
                <Empty
                  title="A voice of your own"
                  text="Create an agent or try a clearly labelled sample."
                  action={
                    <button
                      className="btn small"
                      onClick={() =>
                        run(
                          ctx,
                          () => command(ctx.base + "/fixtures"),
                          "Synthetic sample loaded",
                        )
                      }
                    >
                      Load sample workspace
                      <ArrowUpRight size={12} />
                    </button>
                  }
                />
              )}
            </Panel>
          </div>
        </div>
      )}
    </>
  );
}
