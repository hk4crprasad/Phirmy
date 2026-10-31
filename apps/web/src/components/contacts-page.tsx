"use client";
import { useEffect, useRef, useState } from "react";
import {
  Plus,
  Upload,
  Download,
  Search,
  Phone,
  ArrowRight,
  Trash2,
  Pencil,
} from "lucide-react";
import { api, command, authenticatedFetch, Row } from "@/lib/api";
import { Header, Panel, Table, Badge, Dialog, StudioContext } from "./ui";

export default function ContactsPage({ ctx }: { ctx: StudioContext }) {
  const [rows, setRows] = useState<Row[]>([]),
    [search, setSearch] = useState(""),
    [total, setTotal] = useState(0),
    [offset, setOffset] = useState(0),
    [error, setError] = useState(""),
    [selected, setSelected] = useState<Set<string>>(new Set()),
    [preview, setPreview] = useState<Row | null>(null),
    [busy, setBusy] = useState(false);
  const file = useRef<HTMLInputElement>(null),
    pending = useRef<File | null>(null);
  async function load() {
    try {
      const r = await api(
        ctx.base +
          "/contacts?search=" +
          encodeURIComponent(search) +
          "&offset=" +
          offset,
      );
      setRows(r.items);
      setTotal(r.total);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    const timer = setTimeout(load, 200);
    return () => clearTimeout(timer);
  }, [ctx.base, search, offset]);
  const fields = (row: Row = {}) => [
    { key: "name", label: "Full name", value: row.name || "" },
    {
      key: "phone",
      label: "Phone · +country code",
      value: row.phone || "",
      required: true,
    },
    { key: "email", label: "Email", type: "email", value: row.email || "" },
    {
      key: "consent",
      label: "Permission to call",
      value: row.consent || "unknown",
      options: [
        { value: "unknown", label: "Not confirmed" },
        { value: "granted", label: "Permission granted" },
        { value: "revoked", label: "Permission revoked" },
      ],
    },
    {
      key: "consent_note",
      label: "How was permission obtained?",
      value: row.consent_note || "",
      note: "Required when permission is granted.",
    },
  ];
  function edit(row?: Row) {
    ctx.form({
      title: row ? "Edit contact" : "Add a contact",
      description:
        "Save contact details and record permission before adding someone to a calling campaign.",
      fields: fields(row),
      action: async (values) => {
        if (row)
          await command(
            ctx.base + "/contacts/" + row.id,
            { ...values, variables: row.variables || {} },
            "PUT",
          );
        else
          await command(ctx.base + "/contacts/import", {
            dry_run: false,
            contacts: [values],
          });
        await load();
        ctx.notify("Contact saved");
      },
    });
  }
  async function upload(dry: boolean) {
    if (!pending.current) return;
    setBusy(true);
    setError("");
    try {
      const data = new FormData();
      data.append("file", pending.current);
      const r = await api(ctx.base + "/contacts/import.csv?dry_run=" + dry, {
        method: "POST",
        body: data,
      });
      if (dry) setPreview(r);
      else {
        setPreview(null);
        pending.current = null;
        await load();
        ctx.notify(r.accepted + " contacts saved");
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function campaign() {
    ctx.form({
      title: "Make a calling campaign",
      description:
        selected.size +
        " selected contacts. You will review the draft before starting any calls.",
      fields: [
        { key: "name", label: "Campaign name", required: true },
        {
          key: "agent_version_id",
          label: "Published agent",
          required: true,
          options: (ctx.data.agents || [])
            .filter((a) => a.published_version_id)
            .map((a) => ({ value: a.published_version_id, label: a.name })),
        },
      ],
      submit: "Create draft",
      action: async (values) => {
        const c = await command(ctx.base + "/campaigns", {
          ...values,
          mode: "simulation",
          timezone: ctx.workspace.timezone,
          budget_minor: 1000,
        });
        await command(
          ctx.base + "/campaigns/" + c.id + "/contacts/from-addressbook",
          { contact_ids: Array.from(selected) },
        );
        await ctx.refresh();
        ctx.go("campaigns");
        ctx.notify("Campaign draft ready. No calls have been placed.");
      },
    });
  }
  return (
    <>
      <Header
        eyebrow="YOUR ADDRESS BOOK"
        title="Keep the right people close."
        description="Import contacts, record permission and move selected people into a campaign."
      >
        <button
          className="btn"
          disabled={busy}
          onClick={() => file.current?.click()}
        >
          <Upload size={15} />
          Import CSV
        </button>
        <button
          className="btn"
          onClick={async () => {
            try {
              const response = await authenticatedFetch(
                ctx.base + "/contacts/export.csv",
              );
              if (!response.ok) throw Error("Export could not finish");
              const url = URL.createObjectURL(await response.blob()),
                a = document.createElement("a");
              a.href = url;
              a.download = "contacts.csv";
              a.click();
              setTimeout(() => URL.revokeObjectURL(url), 1000);
            } catch (e) {
              setError((e as Error).message);
            }
          }}
        >
          <Download size={15} />
          Export
        </button>
        <button className="btn primary" onClick={() => edit()}>
          <Plus size={15} />
          Add contact
        </button>
      </Header>
      <input
        ref={file}
        type="file"
        accept=".csv,text/csv"
        hidden
        aria-label="Import contacts CSV"
        onChange={(e) => {
          pending.current = e.target.files?.[0] || null;
          e.target.value = "";
          upload(true);
        }}
      />
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      <Panel>
        <div className="contacts-toolbar">
          <label className="search-field">
            <Search size={16} />
            <input
              aria-label="Search contacts"
              placeholder="Search name, phone or email"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setOffset(0);
                setSelected(new Set());
              }}
            />
          </label>
          <span className="muted small-text">{total} contacts</span>
          <button className="btn" disabled={!selected.size} onClick={campaign}>
            <Phone size={14} />
            Create campaign ({selected.size})<ArrowRight size={14} />
          </button>
        </div>
        <Table
          rows={rows}
          empty="Add your first contact or import a CSV."
          columns={[
            {
              label: "",
              render: (r) => (
                <input
                  className="row-checkbox"
                  type="checkbox"
                  aria-label={"Select " + (r.name || r.phone)}
                  checked={selected.has(r.id)}
                  disabled={r.consent !== "granted"}
                  onChange={(e) => {
                    const next = new Set(selected);
                    if (e.target.checked) next.add(r.id);
                    else next.delete(r.id);
                    setSelected(next);
                  }}
                />
              ),
            },
            {
              label: "NAME",
              render: (r) => <strong>{r.name || "Unnamed contact"}</strong>,
            },
            {
              label: "PHONE",
              render: (r) => <span className="mono">{r.phone}</span>,
            },
            { label: "EMAIL", render: (r) => r.email || "—" },
            {
              label: "CALL PERMISSION",
              render: (r) => <Badge value={r.consent} />,
            },
            {
              label: "",
              render: (r) => (
                <div className="row">
                  <button
                    className="icon-button"
                    aria-label={"Edit " + (r.name || r.phone)}
                    onClick={() => edit(r)}
                  >
                    <Pencil size={15} />
                  </button>
                  <button
                    className="icon-button"
                    aria-label={"Archive " + (r.name || r.phone)}
                    onClick={async () => {
                      try {
                        await api(ctx.base + "/contacts/" + r.id, {
                          method: "DELETE",
                        });
                        setSelected((s) => {
                          const next = new Set(s);
                          next.delete(r.id);
                          return next;
                        });
                        load();
                      } catch (e) {
                        setError((e as Error).message);
                      }
                    }}
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              ),
            },
          ]}
        />
        <div className="contacts-pagination">
          <button
            className="btn small"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - 50))}
          >
            Previous
          </button>
          <span className="small-text muted">
            {total ? offset + 1 : 0}–{Math.min(offset + 50, total)} of {total}
          </span>
          <button
            className="btn small"
            disabled={offset + 50 >= total}
            onClick={() => setOffset(offset + 50)}
          >
            Next
          </button>
        </div>
      </Panel>
      <p className="field-note section-gap">
        CSV columns: phone, name, email, consent, consent_note, variables. Use
        +country-code numbers. Only contacts with recorded call permission can
        be selected for a campaign.
      </p>
      {preview && (
        <Dialog
          title="Review your contact import"
          close={() => setPreview(null)}
        >
          <div className="stack">
            <p>
              {preview.accepted} contacts · {preview.duplicates} duplicates
              removed · {preview.existing} already in your address book
            </p>
            {preview.errors?.length > 0 && (
              <div className="error" role="alert">
                {preview.errors.map((e: Row) => (
                  <p key={e.row}>
                    Row {e.row}: {e.message}
                  </p>
                ))}
              </div>
            )}
            <Table
              rows={preview.preview || []}
              columns={[
                { label: "NAME", render: (r) => r.name || "—" },
                { label: "PHONE", render: (r) => r.phone },
                {
                  label: "PERMISSION",
                  render: (r) => <Badge value={r.consent} />,
                },
              ]}
            />
            <p className="muted small-text">
              Existing permission revocations will be preserved. Preview shows
              up to 25 rows.
            </p>
            <button
              className="btn primary"
              disabled={busy || !!preview.errors?.length || !preview.accepted}
              onClick={() => upload(false)}
            >
              {busy ? "Importing…" : "Import " + preview.accepted + " contacts"}
              <ArrowRight size={15} />
            </button>
          </div>
        </Dialog>
      )}
    </>
  );
}
