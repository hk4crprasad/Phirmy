"use client";
import { useState, useEffect, useRef, ReactNode } from "react";
import { X, Inbox, ArrowUpRight } from "lucide-react";
import { Row } from "@/lib/api";

export type Field = {
  key: string;
  label: string;
  type?: string;
  options?: { value: string; label: string }[];
  required?: boolean;
  value?: any;
  note?: string;
  min?: number;
  max?: number;
};
export type FormSpec = {
  title: string;
  description?: string;
  fields: Field[];
  submit?: string;
  action: (values: Row) => Promise<void>;
};
export type StudioContext = {
  workspace: Row;
  user: Row;
  data: Record<string, Row[]>;
  summary: Row;
  capabilities: Row;
  refresh: () => Promise<void>;
  base: string;
  go: (path: string) => void;
  notify: (message: string) => void;
  form: (spec: FormSpec) => void;
};
export function Header({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  children?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      <div className="heading-actions">{children}</div>
    </div>
  );
}
export function Panel({
  title,
  note,
  action,
  children,
  className = "",
}: {
  title?: string;
  note?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={"panel " + className}>
      {title && (
        <div className="panel-header">
          <div>
            <h2>{title}</h2>
            {note && <p>{note}</p>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}
export function Empty({
  title,
  text,
  action,
}: {
  title: string;
  text: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <Inbox size={27} strokeWidth={1.2} />
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  );
}
export function Badge({ value }: { value?: string }) {
  return (
    <span className={"badge " + (value || "")}>
      {(value || "unknown").replaceAll("_", " ")}
    </span>
  );
}
export function Table({
  columns,
  rows,
  empty,
  onRow,
}: {
  columns: { label: string; render: (row: Row) => ReactNode }[];
  rows: Row[];
  empty?: string;
  onRow?: (row: Row) => void;
}) {
  if (!rows.length)
    return (
      <Empty
        title={empty || "Nothing here yet"}
        text="Your records will appear here as you start using this workspace."
      />
    );
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((col, i) => (
              <th key={i}>{col.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.id ?? index}>
              {columns.map((col, i) => (
                <td key={i}>{col.render(row)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function Dialog({
  title,
  close,
  children,
  className = "",
}: {
  title: string;
  close: () => void;
  children: ReactNode;
  className?: string;
}) {
  const dialog = useRef<HTMLElement>(null);
  const onClose = useRef(close);
  onClose.current = close;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusable = () =>
      Array.from(
        dialog.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex="0"]',
        ) || [],
      ).filter((element) => element.getClientRects().length > 0);
    focusable()[0]?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose.current();
      }
      if (event.key !== "Tab") return;
      const items = focusable(),
        first = items[0],
        last = items.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", keydown);
    return () => {
      document.removeEventListener("keydown", keydown);
      document.body.style.overflow = overflow;
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <section
        ref={dialog}
        className={"modal " + className}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="modal-header">
          <h2>{title}</h2>
          <button
            className="btn subtle"
            onClick={close}
            aria-label="Close dialog"
          >
            <X size={18} />
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </section>
    </div>
  );
}
export function FormDialog({
  spec,
  close,
}: {
  spec: FormSpec;
  close: () => void;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const raw = new FormData(e.currentTarget),
      values: Row = {};
    for (const field of spec.fields) {
      const value = raw.get(field.key);
      values[field.key] =
        field.type === "number"
          ? Number(value)
          : field.type === "checkbox"
            ? Boolean(value)
            : value || "";
      if (field.required && field.type === "checkbox" && !value) {
        setError(field.label);
        setBusy(false);
        return;
      }
    }
    try {
      await spec.action(values);
      close();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog title={spec.title} close={close}>
      {spec.description && (
        <p className="muted small-text" style={{ marginBottom: 20 }}>
          {spec.description}
        </p>
      )}
      <form onSubmit={submit}>
        {spec.fields.map((field) => (
          <label
            key={field.key}
            className={field.type === "checkbox" ? "checkbox-label" : ""}
          >
            {field.type === "checkbox" ? (
              <>
                <input
                  aria-label={field.label}
                  name={field.key}
                  type="checkbox"
                  defaultChecked={field.value}
                />
                {field.label}
              </>
            ) : (
              <>
                {field.label}
                {field.type === "textarea" ? (
                  <textarea
                    aria-label={field.label}
                    name={field.key}
                    defaultValue={field.value}
                    required={field.required}
                  />
                ) : field.options ? (
                  <select
                    aria-label={field.label}
                    name={field.key}
                    defaultValue={field.value}
                    required={field.required}
                  >
                    {field.options.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    aria-label={field.label}
                    name={field.key}
                    type={field.type || "text"}
                    defaultValue={field.value}
                    required={field.required}
                    min={field.min}
                    max={field.max}
                  />
                )}
              </>
            )}
            {field.note && <span className="field-note">{field.note}</span>}
          </label>
        ))}
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        <div
          className="row"
          style={{ justifyContent: "flex-end", marginTop: 6 }}
        >
          <button type="button" className="btn" onClick={close}>
            Cancel
          </button>
          <button className="btn primary" disabled={busy}>
            {busy ? "Saving…" : spec.submit || "Save"}
            <ArrowUpRight size={14} />
          </button>
        </div>
      </form>
    </Dialog>
  );
}
