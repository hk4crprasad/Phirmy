"use client";
import { HumanTransfers } from "./human-transfers";
import { OperatorBilling } from "./billing/operator";
import { AgentDeletionJobs } from "./agent-deletion";
import { useState, useEffect } from "react";
import {
  ArrowUpRight,
  Plus,
  Copy,
  Download,
  ShieldCheck,
  Users,
  Wallet,
  Plug,
  RefreshCw,
  CalendarDays,
  CalendarClock,
  Phone,
  MessageSquare,
  ContactRound,
  type LucideIcon,
} from "lucide-react";
import { api, command, Row, money, when } from "@/lib/api";
import {
  Header,
  Panel,
  Table,
  Badge,
  Dialog,
  StudioContext,
  Field,
  Empty,
} from "./ui";
type Props = { ctx: StudioContext };
const roles = ["admin", "builder", "operator", "analyst", "billing"].map(
  (value) => ({ value, label: value[0].toUpperCase() + value.slice(1) }),
);
const get = (ctx: StudioContext, path: string) => api(ctx.base + path);
export function TeamPage({ ctx }: Props) {
  const [invites, setInvites] = useState<Row[]>([]),
    [link, setLink] = useState("");
  const refresh = () =>
    get(ctx, "/invitations")
      .then((r) => setInvites(r.items))
      .catch((e) => ctx.notify(e.message));
  useEffect(() => {
    refresh();
  }, [ctx.base]);
  function invite() {
    ctx.form({
      title: "Bring your team in",
      description:
        "Create a private invitation link. It can only be accepted once, by the invited email, within seven days.",
      fields: [
        { key: "email", label: "Work email", type: "email", required: true },
        { key: "role", label: "Role", options: roles, value: "operator" },
      ],
      submit: "Create invitation",
      action: async (values) => {
        const r = await command(ctx.base + "/invitations", values);
        setLink(r.accept_url);
        refresh();
      },
    });
  }
  function role(member: Row) {
    ctx.form({
      title: "Change team access",
      fields: [
        { key: "role", label: "Role", options: roles, value: member.role },
      ],
      action: async (values) => {
        await command(ctx.base + "/members/" + member.user_id, values, "PATCH");
        await ctx.refresh();
      },
    });
  }
  return (
    <>
      <Header
        title="Good work takes a team."
        description="Clear access. Private invitations. Shared context."
      >
        <button className="btn primary" onClick={invite}>
          <Plus size={14} />
          Invite teammate
        </button>
      </Header>
      <div className="stack">
        <Panel title="Your people">
          <Table
            rows={ctx.data.members || []}
            columns={[
              {
                label: "PERSON",
                render: (r) => (
                  <>
                    <strong>{r.name}</strong>
                    <span className="cell-sub">{r.email}</span>
                  </>
                ),
              },
              { label: "ROLE", render: (r) => <Badge value={r.role} /> },
              {
                label: "",
                render: (r) =>
                  r.role !== "owner" && r.user_id !== ctx.user.id ? (
                    <div className="row">
                      <button className="table-action" onClick={() => role(r)}>
                        Change access
                      </button>
                      <button
                        className="table-action"
                        onClick={async () => {
                          try {
                            await command(
                              ctx.base + "/members/" + r.user_id,
                              {},
                              "DELETE",
                            );
                            await ctx.refresh();
                          } catch (e) {
                            ctx.notify((e as Error).message);
                          }
                        }}
                      >
                        Remove
                      </button>
                    </div>
                  ) : null,
              },
            ]}
          />
        </Panel>
        <Panel title="Invitations">
          <Table
            rows={invites}
            empty="No pending invitations"
            columns={[
              { label: "EMAIL", render: (r) => <strong>{r.email}</strong> },
              { label: "ROLE", render: (r) => r.role },
              {
                label: "STATUS",
                render: (r) => (
                  <Badge
                    value={
                      new Date(r.expires_at) < new Date() &&
                      r.state === "pending"
                        ? "expired"
                        : r.state
                    }
                  />
                ),
              },
              {
                label: "",
                render: (r) =>
                  r.state === "pending" && (
                    <button
                      className="table-action"
                      onClick={async () => {
                        await command(
                          ctx.base + "/invitations/" + r.id,
                          {},
                          "DELETE",
                        );
                        refresh();
                      }}
                    >
                      Revoke
                    </button>
                  ),
              },
            ]}
          />
        </Panel>
      </div>
      {link && (
        <Dialog title="Their next step starts here" close={() => setLink("")}>
          <p className="small-text">
            Share this link privately with the person you invited.
          </p>
          <p className="mono code" style={{ margin: "18px 0" }}>
            {link}
          </p>
          <button
            className="btn primary"
            onClick={() =>
              navigator.clipboard
                .writeText(link)
                .then(() => ctx.notify("Invitation copied"))
            }
          >
            <Copy size={14} />
            Copy invitation
          </button>
        </Dialog>
      )}
    </>
  );
}
const definitions: Record<
  string,
  { icon: LucideIcon; description: string; fields: Field[] }
> = {
  hubspot: {
    icon: ContactRound,
    description: "Sync a contact to your CRM with a confirmed provider result.",
    fields: [
      {
        key: "access_token",
        label: "Private app access token",
        type: "password",
        required: true,
        note: "Needs contact read and write scopes.",
      },
    ],
  },
  google_calendar: {
    icon: CalendarDays,
    description:
      "Check calendar availability and save your local appointment remotely.",
    fields: [
      { key: "client_id", label: "OAuth client ID", required: true },
      {
        key: "client_secret",
        label: "OAuth client secret",
        type: "password",
        required: true,
      },
      {
        key: "refresh_token",
        label: "OAuth refresh token",
        type: "password",
        required: true,
      },
      {
        key: "calendar_id",
        label: "Calendar ID",
        value: "primary",
        required: true,
      },
    ],
  },
  sms: {
    icon: MessageSquare,
    description: "Send a consented follow-up through your Plivo sender.",
    fields: [
      { key: "auth_id", label: "Plivo auth ID", required: true },
      {
        key: "auth_token",
        label: "Plivo auth token",
        type: "password",
        required: true,
      },
      { key: "sender", label: "Approved sender", required: true },
    ],
  },
  calcom: {
    icon: CalendarClock,
    description:
      "Let your agent check Cal.com availability and book a meeting after the caller confirms.",
    fields: [
      {
        key: "api_key",
        label: "Cal.com API key",
        type: "password",
        required: true,
        note: "Allow reading event types and reading/creating bookings.",
      },
      {
        key: "booking_url",
        label: "Your Cal.com scheduling link",
        type: "url",
        required: true,
        note: "For example https://cal.com/your-name/meeting",
      },
    ],
  },
  calendly: {
    icon: CalendarClock,
    description:
      "Book meetings during calls with Calendly Standard or above and Scheduling API access.",
    fields: [
      {
        key: "access_token",
        label: "Calendly personal access token",
        type: "password",
        required: true,
        note: "Needs event_types:read, availability:read, scheduled_events:read and scheduled_events:write. Direct booking requires Standard or above.",
      },
      {
        key: "booking_url",
        label: "Your Calendly scheduling link",
        type: "url",
        required: true,
        note: "For example https://calendly.com/your-name/meeting",
      },
    ],
  },
  twilio: {
    icon: Phone,
    description:
      "Connect your own Twilio account, verify an owned number and route it to a published agent.",
    fields: [
      { key: "account_sid", label: "Account SID", required: true },
      {
        key: "auth_token",
        label: "Auth token",
        type: "password",
        required: true,
      },
    ],
  },
  plivo: {
    icon: Phone,
    description:
      "Connect your own Plivo account and manage the numbers you already own.",
    fields: [
      { key: "auth_id", label: "Auth ID", required: true },
      {
        key: "auth_token",
        label: "Auth token",
        type: "password",
        required: true,
      },
    ],
  },
};
export function IntegrationPage({ ctx }: Props) {
  const [actions, setActions] = useState<Row[]>([]);
  const [links, setLinks] = useState<Record<string, string>>({});
  useEffect(() => {
    for (const connection of ctx.data.connections || []) {
      if (
        connection.state === "connected" &&
        ["calcom", "calendly"].includes(connection.provider)
      )
        api(
          ctx.base + "/connections/" + connection.provider + "/scheduling-link",
        )
          .then((r) =>
            setLinks((old) => ({ ...old, [connection.provider]: r.url })),
          )
          .catch(() => {});
    }
  }, [ctx.base, ctx.data.connections]);
  useEffect(() => {
    get(ctx, "/connector-actions")
      .then((r) => setActions(r.items))
      .catch(() => {});
  }, [ctx.base]);
  const [oauthNotice, setOauthNotice] = useState("");
  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    const outcome = query.get("scheduling_oauth"),
      provider = query.get("provider");
    if (outcome && ["calcom", "calendly"].includes(provider || "")) {
      setOauthNotice(
        outcome === "connected"
          ? "Account authorized. Choose a meeting type, enable booking on your agent and publish."
          : "Authorization did not complete. Check the app registration, approval, scopes and workspace access, then reconnect.",
      );
      window.history.replaceState(null, "", window.location.pathname);
    }
  }, []);
  async function oauthConnect(row: Row) {
    try {
      const result = await command(
        ctx.base + "/connections/" + row.provider + "/oauth/start",
        {},
      );
      const destination = new URL(result.authorization_url);
      const expected =
        row.provider === "calcom"
          ? "https://app.cal.com"
          : "https://auth.calendly.com";
      if (destination.origin !== expected)
        throw Error("The scheduling authorization URL is invalid");
      window.location.assign(destination.href);
    } catch (e) {
      ctx.notify((e as Error).message);
    }
  }
  function connect(row: Row) {
    if (
      row.provider === "google_calendar" &&
      ctx.capabilities.google_calendar_oauth
    ) {
      window.location.assign(
        "/backend/v1/auth/google/start?purpose=calendar&workspace_id=" +
          encodeURIComponent(ctx.workspace.id),
      );
      return;
    }
    const definition = definitions[row.provider];
    ctx.form({
      title: "Connect " + row.name,
      description:
        "Credentials are encrypted on the server. A provider check must succeed before this connection becomes active.",
      fields: definition.fields,
      submit: "Verify connection",
      action: async (values) => {
        await command(
          ctx.base + "/connections/" + row.provider,
          { credentials: values },
          "PUT",
        );
        await ctx.refresh();
        ctx.notify("Connection verified");
      },
    });
  }
  async function configureBooking(row: Row) {
    try {
      const result = await api(
        ctx.base + "/connections/" + row.provider + "/event-types",
      );
      const supported = result.items.filter((event: Row) => event.supported);
      if (!supported.length) {
        ctx.notify(
          "No supported meeting types found. Use an active event without payment or recurring bookings.",
        );
        return;
      }
      ctx.form({
        title: "Call booking · " + row.name,
        description:
          "Choose the meeting your agents can book. Then enable Cal.com or Calendly booking in the agent’s Actions tab.",
        fields: [
          {
            key: "event_type_id",
            label: "Meeting type",
            required: true,
            options: supported.map((event: Row) => ({
              value: String(event.id),
              label: event.title + " · " + event.duration_minutes + " min",
            })),
          },
        ],
        submit: "Enable call booking",
        action: async (values) => {
          await command(
            ctx.base + "/connections/" + row.provider + "/booking-settings",
            values,
            "PUT",
          );
          await ctx.refresh();
          ctx.notify(
            "Call booking configured. Enable it on your agent and publish.",
          );
        },
      });
    } catch (error) {
      ctx.notify(
        error instanceof Error ? error.message : "Could not load meeting types",
      );
    }
  }
  function action(row: Row) {
    const provider = row.provider;
    const fields: Field[] =
      provider === "hubspot"
        ? [
            {
              key: "lead_id",
              label: "Contact to sync",
              required: true,
              options: (ctx.data.leads || []).map((x) => ({
                value: x.id,
                label: x.name + " · " + x.email,
              })),
            },
          ]
        : provider === "google_calendar"
          ? [
              {
                key: "appointment_id",
                label: "Appointment to sync",
                required: true,
                options: (ctx.data.appointments || [])
                  .filter((x) => x.state !== "canceled")
                  .map((x) => ({
                    value: x.id,
                    label: x.title + " · " + when(x.start_at),
                  })),
              },
            ]
          : [
              { key: "to", label: "Recipient · E.164", required: true },
              {
                key: "text",
                label: "Message",
                type: "textarea",
                required: true,
              },
              {
                key: "consent_confirmed",
                label: "This recipient agreed to receive this message",
                type: "checkbox",
                required: true,
              },
            ];
    ctx.form({
      title: provider === "sms" ? "Send a follow-up" : "Sync to " + row.name,
      fields,
      submit: provider === "sms" ? "Send message" : "Sync record",
      action: async (values) => {
        const result = await command(
          ctx.base + "/connections/" + provider + "/actions",
          {
            action:
              provider === "hubspot"
                ? "sync_lead"
                : provider === "google_calendar"
                  ? "sync_appointment"
                  : "send_sms",
            input: values,
          },
          "POST",
          true,
        );
        ctx.notify(result.result?.status || result.state);
        setActions((await get(ctx, "/connector-actions")).items);
      },
    });
  }
  return (
    <>
      <Header
        title="Make the next step happen."
        description="Connect your business tools. Every action keeps its result."
      />
      {oauthNotice && (
        <div className="notice" role="status">
          {oauthNotice}
        </div>
      )}
      <div className="resource-grid">
        {(ctx.data.connections || [])
          .filter((x) => definitions[x.provider])
          .map((row) => (
            <section className="resource-card integration-card" key={row.id}>
              <div className="card-top">
                <div className="logo-mark">
                  {(() => {
                    const Icon = definitions[row.provider].icon;
                    return <Icon size={24} />;
                  })()}
                </div>
                <Badge value={row.state} />
              </div>
              <h3>{row.name}</h3>
              <p>{definitions[row.provider].description}</p>
              {["calcom", "calendly"].includes(row.provider) &&
                row.scopes?.includes("bookings:write") && (
                  <p className="small-text">Call booking configured</p>
                )}
              {row.state === "connected" ? (
                <div className="row">
                  {["calcom", "calendly"].includes(row.provider) ? (
                    <>
                      <button
                        className="btn"
                        onClick={() => configureBooking(row)}
                      >
                        {row.scopes?.includes("bookings:write")
                          ? "Change meeting type"
                          : "Set up call booking"}
                        <CalendarClock size={13} />
                      </button>
                      <a
                        className={
                          "btn " + (!links[row.provider] ? "is-disabled" : "")
                        }
                        href={links[row.provider]}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Open scheduler
                        <ArrowUpRight size={13} />
                      </a>
                    </>
                  ) : (
                    <button
                      className="btn"
                      onClick={() =>
                        ["twilio", "plivo"].includes(row.provider)
                          ? ctx.go("numbers")
                          : action(row)
                      }
                    >
                      Use connection
                      <ArrowUpRight size={13} />
                    </button>
                  )}
                  <button
                    className="table-action"
                    onClick={async () => {
                      await command(
                        ctx.base + "/connections/" + row.provider,
                        {},
                        "DELETE",
                      );
                      ctx.refresh();
                    }}
                  >
                    Disconnect
                  </button>
                </div>
              ) : (
                <div className="stack">
                  {["calcom", "calendly"].includes(row.provider) && (
                    <>
                      <button
                        className="btn primary"
                        disabled={
                          !ctx.capabilities.scheduling_oauth?.[row.provider]
                        }
                        onClick={() => oauthConnect(row)}
                      >
                        Connect with {row.name}
                        <ArrowUpRight size={13} />
                      </button>
                      {!ctx.capabilities.scheduling_oauth?.[row.provider] && (
                        <p className="field-note">
                          OAuth app setup is pending. Use an API key below or
                          connect Google Calendar.
                        </p>
                      )}
                    </>
                  )}
                  <button className="btn" onClick={() => connect(row)}>
                    Connect
                    {["calcom", "calendly"].includes(row.provider) &&
                    ctx.capabilities.scheduling_oauth?.[row.provider]
                      ? " with API key"
                      : ""}
                    <ArrowUpRight size={13} />
                  </button>
                </div>
              )}
            </section>
          ))}
      </div>
      <Panel className="section-gap" title="Action history">
        <Table
          rows={actions}
          columns={[
            { label: "PROVIDER", render: (r) => <strong>{r.provider}</strong> },
            { label: "ACTION", render: (r) => r.action.replaceAll("_", " ") },
            {
              label: "RESULT",
              render: (r) => (
                <>
                  <Badge value={r.state} />
                  <span className="cell-sub">
                    {r.result.status || r.result.message || "Awaiting result"}
                  </span>
                </>
              ),
            },
            {
              label: "REMOTE ID",
              render: (r) => (
                <span className="mono">{r.result.remote_id || "—"}</span>
              ),
            },
          ]}
        />
      </Panel>
      <HumanTransfers ctx={ctx} />
      <p className="field-note" style={{ marginTop: 18 }}>
        Google Calendar can check availability and sync appointments. Cal.com
        and Calendly can book during calls after you choose a meeting type and
        enable scheduling on the agent. Calendly requires Standard or above.
        Carrier connections verify account access and still require an owned
        number and public call routing.
      </p>
    </>
  );
}
export { default as BillingPage } from "./billing";

export function OperationsPage({ ctx }: Props) {
  const [audit, setAudit] = useState<Row[]>([]),
    [recordings, setRecordings] = useState<Row[]>([]);
  useEffect(() => {
    get(ctx, "/audit")
      .then((r) => setAudit(r.items))
      .catch(() => {});
    get(ctx, "/recordings")
      .then((r) => setRecordings(r.items))
      .catch(() => {});
  }, [ctx.base]);
  return (
    <>
      <Header
        title="The details are all here."
        description="Exports, recording retention and a trail of workspace changes."
      />
      <div className="row" style={{ marginBottom: 24, flexWrap: "wrap" }}>
        {["calls", "leads", "tickets"].map((resource) => (
          <a
            className="btn"
            href={"/backend" + ctx.base + "/exports/" + resource}
            key={resource}
          >
            <Download size={14} />
            {resource[0].toUpperCase() + resource.slice(1)} CSV
          </a>
        ))}
      </div>
      <div className="stack">
        <OperatorBilling ctx={ctx} />
        <AgentDeletionJobs ctx={ctx} />
        <Panel
          title="Call recordings"
          note="Recording is opt-in on each published agent. Audio expires according to its retention setting."
        >
          <Table
            rows={recordings}
            empty="No retained recordings"
            columns={[
              {
                label: "CALL",
                render: (r) => (
                  <span className="mono">{r.call_id.slice(0, 8)}</span>
                ),
              },
              { label: "EXPIRES", render: (r) => when(r.expires_at) },
              {
                label: "AUDIO",
                render: (r) => (
                  <audio
                    controls
                    preload="none"
                    style={{ height: 32, maxWidth: 240 }}
                    src={
                      "/backend" + ctx.base + "/recordings/" + r.id + "/audio"
                    }
                  />
                ),
              },
              {
                label: "",
                render: (r) => (
                  <button
                    className="table-action"
                    onClick={async () => {
                      await command(
                        ctx.base + "/recordings/" + r.id,
                        {},
                        "DELETE",
                      );
                      setRecordings((old) => old.filter((x) => x.id !== r.id));
                      ctx.notify("Recording deleted");
                    }}
                  >
                    Delete
                  </button>
                ),
              },
            ]}
          />
        </Panel>
        <Panel title="Audit trail">
          <Table
            rows={audit}
            columns={[
              { label: "CHANGE", render: (r) => <strong>{r.action}</strong> },
              { label: "DATE", render: (r) => when(r.created_at) },
              {
                label: "RESOURCE",
                render: (r) => (
                  <span className="mono">{r.resource_id || "—"}</span>
                ),
              },
            ]}
          />
        </Panel>
      </div>
    </>
  );
}
