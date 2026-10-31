"use client";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  MessageSquare,
  Radio,
  Send,
  UserRound,
  Bot,
  CheckCheck,
} from "lucide-react";
import { api, command, Row, when } from "@/lib/api";
import { Header, Panel, Badge, StudioContext } from "./ui";
import "./live-inbox.css";

export default function LiveInbox({ ctx }: { ctx: StudioContext }) {
  const queryId = useSearchParams().get("conversation") || "";
  const [tickets, setTickets] = useState<Row[]>(ctx.data.tickets || []);
  const [rows, setRows] = useState<Row[]>(ctx.data.conversations || []);
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<Row | null>(null);
  const [tab, setTab] = useState("conversations");
  const [text, setText] = useState(""),
    [error, setError] = useState(""),
    [pending, setPending] = useState(false);
  const messagesRoot = useRef<HTMLDivElement>(null);
  const followLatest = useRef(true);
  const end = useRef<HTMLDivElement>(null),
    generation = useRef(0),
    replyId = useRef("");
  const canReply =
    detail?.conversation.state === "human" &&
    detail?.conversation.assigned_user_id === ctx.user.id;
  useEffect(() => {
    followLatest.current = true;
    setSelected(queryId);
    setDetail(null);
    setRows(ctx.data.conversations || []);
  }, [ctx.base, queryId]);
  useEffect(() => {
    const scope = ++generation.current;
    let stopped = false,
      timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const [list, messages, supportTickets] = await Promise.all([
          api(ctx.base + "/conversations"),
          selected
            ? api(ctx.base + "/conversations/" + selected + "/messages")
            : Promise.resolve(null),
          tab === "tickets"
            ? api(ctx.base + "/tickets")
            : Promise.resolve(null),
        ]);
        if (stopped || scope !== generation.current) return;
        setRows(list.items);
        if (supportTickets) setTickets(supportTickets.items);
        setDetail(messages);
        setError("");
      } catch (e) {
        if (!stopped) setError((e as Error).message);
      } finally {
        if (!stopped) timer = setTimeout(load, 2000);
      }
    }
    load();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [ctx.base, selected, tab]);
  useEffect(() => {
    const root = messagesRoot.current;
    if (root && followLatest.current) root.scrollTop = root.scrollHeight;
  }, [detail?.items?.length, selected]);
  async function mode(value: string) {
    if (!selected) return;
    setPending(true);
    setError("");
    try {
      await command(
        ctx.base + "/conversations/" + selected + "/mode",
        { mode: value },
        "PATCH",
      );
      setDetail(
        await api(ctx.base + "/conversations/" + selected + "/messages"),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(false);
    }
  }
  async function reply(event: React.FormEvent) {
    event.preventDefault();
    if (!text.trim() || !canReply || pending) return;
    setPending(true);
    setError("");
    if (!replyId.current) replyId.current = crypto.randomUUID();
    try {
      await command(ctx.base + "/conversations/" + selected + "/messages", {
        text: text.trim(),
        client_message_id: replyId.current,
      });
      replyId.current = "";
      setText("");
      setDetail(
        await api(ctx.base + "/conversations/" + selected + "/messages"),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(false);
    }
  }
  return (
    <>
      <Header
        eyebrow="CONNECTED TO YOUR CUSTOMERS"
        title="Your live inbox."
        description="Follow conversations as they happen. Step in when a personal reply matters."
      />
      <div className="row between">
        <div className="tabs">
          <button
            className={"tab " + (tab === "conversations" ? "active" : "")}
            onClick={() => setTab("conversations")}
          >
            Conversations
          </button>
          <button
            className={"tab " + (tab === "tickets" ? "active" : "")}
            onClick={() => setTab("tickets")}
          >
            Support tickets
          </button>
        </div>
        <span className="live-inbox-indicator">
          <Radio size={14} /> Live updates · 2s
        </span>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {tab === "tickets" ? (
        <Panel>
          {tickets.map((ticket) => (
            <div key={ticket.id} className="live-ticket">
              <div>
                <strong>{ticket.subject}</strong>
                <p>{ticket.description}</p>
                <Badge value={ticket.state} />
              </div>
              <button
                className="btn"
                onClick={() => {
                  setTab("conversations");
                  setDetail(null);
                  setSelected(ticket.conversation_id);
                }}
              >
                Open conversation
              </button>
              <select
                aria-label={"Ticket state " + ticket.subject}
                value={ticket.state}
                onChange={async (event) => {
                  try {
                    await command(
                      ctx.base + "/tickets/" + ticket.id,
                      { state: event.target.value },
                      "PATCH",
                    );
                    await ctx.refresh();
                  } catch (e) {
                    setError((e as Error).message);
                  }
                }}
              >
                {["open", "pending", "resolved"].map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </div>
          ))}
          {!tickets.length && <p>No support requests waiting.</p>}
        </Panel>
      ) : (
        <div className="live-inbox-layout">
          <aside className="live-inbox-list" aria-label="Live conversations">
            {rows.map((row) => (
              <button
                key={row.id}
                disabled={pending}
                aria-pressed={selected === row.id}
                className={
                  "live-conversation " + (selected === row.id ? "active" : "")
                }
                onClick={() => {
                  followLatest.current = true;
                  setDetail(null);
                  setSelected(row.id);
                  setText("");
                  replyId.current = "";
                }}
              >
                <div className="row between">
                  <strong>{row.visitor?.email || "Website visitor"}</strong>
                  <Badge
                    value={
                      row.state === "human"
                        ? "Team"
                        : row.state === "resolved"
                          ? "Closed"
                          : "AI"
                    }
                  />
                </div>
                <p>{row.preview || "Conversation opened"}</p>
                <small>{when(row.created_at)}</small>
              </button>
            ))}
            {!rows.length && (
              <p className="live-inbox-empty">
                New website conversations will appear here.
              </p>
            )}
          </aside>
          <section className="live-inbox-thread" aria-label="Live conversation">
            {!selected ? (
              <div className="live-inbox-empty">
                <MessageSquare size={30} />
                <h2>A personal touch, when it matters.</h2>
                <p>Choose a conversation to see messages and join in.</p>
              </div>
            ) : !detail ? (
              <p className="live-inbox-empty">Loading conversation…</p>
            ) : (
              <>
                <header className="live-thread-header">
                  <div>
                    <strong>
                      {detail.visitor?.email || "Website visitor"}
                    </strong>
                    <p>
                      {detail.conversation.state === "human"
                        ? "AI paused · team is handling this chat"
                        : detail.conversation.state === "resolved"
                          ? "Conversation closed"
                          : "AI is responding"}
                    </p>
                    {detail.visitor?.email && (
                      <small>
                        {detail.visitor.marketing_opt_in
                          ? "Promotional email: opted in"
                          : "Promotional email: no opt-in"}{" "}
                        · Email unverified
                      </small>
                    )}
                  </div>
                  <div className="row">
                    {!canReply && detail.conversation.state !== "resolved" && (
                      <button
                        className="btn primary"
                        disabled={pending}
                        onClick={() => mode("human")}
                      >
                        <UserRound size={15} />
                        Take over
                      </button>
                    )}
                    {detail.conversation.state !== "open" && (
                      <button
                        className="btn"
                        disabled={pending}
                        onClick={() => mode("open")}
                      >
                        <Bot size={15} />
                        Return to AI
                      </button>
                    )}
                    {detail.conversation.state !== "resolved" && (
                      <button
                        className="btn subtle"
                        disabled={pending}
                        onClick={() => mode("resolved")}
                      >
                        <CheckCheck size={15} />
                        Resolve
                      </button>
                    )}
                  </div>
                </header>
                <div
                  className="live-thread-messages"
                  aria-live="polite"
                  ref={messagesRoot}
                  onScroll={() => {
                    const root = messagesRoot.current;
                    if (root)
                      followLatest.current =
                        root.scrollHeight - root.clientHeight - root.scrollTop <
                        48;
                  }}
                >
                  {detail.items.map((message: Row) => (
                    <article
                      key={message.id}
                      className={"live-thread-bubble " + message.role}
                    >
                      <small>
                        {message.role === "user"
                          ? "Visitor"
                          : message.role === "operator"
                            ? "Support team"
                            : "AI assistant"}{" "}
                        · {when(message.created_at)}
                        {message.metadata_data?.interrupted
                          ? " · interrupted"
                          : message.metadata_data?.streaming
                            ? " · typing…"
                            : ""}
                      </small>
                      <p>{message.text_content}</p>
                    </article>
                  ))}
                  {!detail.items.length && (
                    <p>Waiting for the visitor’s first message.</p>
                  )}
                  <div ref={end} />
                </div>
                <form className="live-thread-composer" onSubmit={reply}>
                  <textarea
                    aria-label="Reply to visitor"
                    placeholder={
                      canReply
                        ? "Write a personal reply…"
                        : "Take over to reply directly"
                    }
                    value={text}
                    maxLength={8000}
                    disabled={!canReply || pending}
                    onChange={(event) => {
                      setText(event.target.value);
                      replyId.current = "";
                    }}
                  />
                  <button
                    className="btn primary"
                    disabled={!canReply || !text.trim() || pending}
                  >
                    <Send size={16} />
                    Send reply
                  </button>
                </form>
              </>
            )}
          </section>
        </div>
      )}
    </>
  );
}
