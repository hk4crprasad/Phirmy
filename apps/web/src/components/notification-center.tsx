"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Bell, CheckCheck, X, Inbox } from "lucide-react";
import { api, command, Row, when } from "@/lib/api";

export default function NotificationCenter({ base }: { base: string }) {
  const [open, setOpen] = useState(false),
    [items, setItems] = useState<Row[]>([]),
    [unread, setUnread] = useState(0),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true);
  const root = useRef<HTMLDivElement>(null),
    trigger = useRef<HTMLButtonElement>(null);
  const requestVersion = useRef(0);
  const appliedVersion = useRef(0);
  const currentBase = useRef(base);
  currentBase.current = base;
  async function load() {
    if (base !== currentBase.current) return;
    const version = ++requestVersion.current,
      scope = base;
    setLoading(true);
    try {
      const r = await api(base + "/notifications");
      if (version < appliedVersion.current || scope !== currentBase.current)
        return;
      appliedVersion.current = version;
      setItems(r.items);
      setUnread(r.unread);
      setError("");
    } catch (e) {
      if (version === requestVersion.current && scope === currentBase.current)
        setError((e as Error).message);
    } finally {
      if (version === requestVersion.current && scope === currentBase.current)
        setLoading(false);
    }
  }
  useEffect(() => {
    setItems([]);
    setUnread(0);
    setError("");
    setOpen(false);
    load();
    const timer = setInterval(() => {
      if (!document.hidden) load();
    }, 5000);
    return () => {
      clearInterval(timer);
      requestVersion.current++;
    };
  }, [base]);
  useEffect(() => {
    if (!open) return;
    load();
    const outside = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    const escape = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);
  return (
    <div className="notification-center" ref={root}>
      <button
        ref={trigger}
        className="icon-button"
        aria-label={
          unread ? "Notifications, " + unread + " unread" : "Notifications"
        }
        aria-expanded={open}
        aria-controls="notification-panel"
        onClick={() => setOpen(!open)}
      >
        <Bell size={19} />
        {unread > 0 && (
          <span className="notification-count">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>
      {open && (
        <section
          id="notification-panel"
          className="notification-panel"
          aria-label="Notifications"
        >
          <div className="notification-heading">
            <h2>Notifications</h2>
            <button
              className="icon-button"
              aria-label="Close notifications"
              onClick={() => {
                setOpen(false);
                trigger.current?.focus();
              }}
            >
              <X size={17} />
            </button>
          </div>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {loading && !items.length ? (
            <div className="notification-empty" role="status">
              Loading notifications…
            </div>
          ) : error && !items.length ? (
            <div className="notification-empty">
              <button className="btn" onClick={load}>
                Retry notifications
              </button>
            </div>
          ) : items.length ? (
            <>
              <button
                className="btn subtle small"
                onClick={async () => {
                  try {
                    await command(base + "/notifications/read", { all: true });
                    await load();
                  } catch (e) {
                    setError((e as Error).message);
                  }
                }}
              >
                <CheckCheck size={14} />
                Mark all as read
              </button>
              <div className="notification-list">
                {items.map((item) => (
                  <Link
                    key={item.id}
                    href={item.href}
                    className={
                      "notification-item " + (!item.read ? "unread" : "")
                    }
                    onClick={() => {
                      command(base + "/notifications/read", { ids: [item.id] })
                        .then(load)
                        .catch(() => {});
                      setOpen(false);
                    }}
                  >
                    <strong>{item.title}</strong>
                    <p>{item.description}</p>
                    <small>{when(item.created_at)}</small>
                  </Link>
                ))}
              </div>
            </>
          ) : (
            <div className="notification-empty">
              <Inbox size={25} />
              <strong>You’re all caught up.</strong>
              <p>
                Updates about agents, conversations and tasks will appear here.
              </p>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
