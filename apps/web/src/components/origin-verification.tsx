"use client";
import { useEffect, useState } from "react";
import { api, command, Row, when } from "@/lib/api";

export default function OriginVerification({
  base,
  origins,
}: {
  base: string;
  origins: string[];
}) {
  const [records, setRecords] = useState<Row[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [platforms, setPlatforms] = useState<string[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  async function refresh() {
    const result = await api(base + "/origins");
    setRecords(result.items);
    setPlatforms(result.platform_origins);
    setLoaded(true);
  }
  useEffect(() => {
    refresh().catch((e) => setError(e.message));
  }, [base]);
  async function run(origin: string, id?: string, method?: string) {
    setBusy(origin);
    setError("");
    try {
      await command(
        base + "/origins" + (id ? "/" + id + "/verify" : ""),
        id ? { method } : { origin },
      );
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  return (
    <section aria-label="Website ownership verification">
      <h3>Verify website ownership</h3>
      <p className="field-note">
        Every external website needs proof before it can start conversations.
        Add one DNS record, meta tag or well-known file, then check it here.
        Verification lasts 90 days.
      </p>
      {!loaded && !error && <p role="status">Loading website verification…</p>}
      {loaded &&
        origins.filter(Boolean).map((origin) => {
          let normalizedOrigin = origin;
          try {
            normalizedOrigin = new URL(origin).origin;
          } catch {}
          const record = records.find((r) => r.origin === normalizedOrigin);
          return (
            <div className="notice" key={origin} style={{ marginBottom: 12 }}>
              <strong>{origin}</strong>
              {platforms.includes(normalizedOrigin) ? (
                <p>Trusted platform preview origin</p>
              ) : record?.state === "verified" ? (
                <>
                  <p>Verified until {when(record.verified_until)}</p>
                  <button
                    type="button"
                    className="btn"
                    disabled={!!busy}
                    onClick={async () => {
                      setBusy(origin);
                      setError("");
                      try {
                        await api(base + "/origins/" + record.id, {
                          method: "DELETE",
                        });
                        await refresh();
                      } catch (e) {
                        setError((e as Error).message);
                      } finally {
                        setBusy("");
                      }
                    }}
                  >
                    Revoke website verification
                  </button>
                </>
              ) : record ? (
                <>
                  {Date.parse(record.challenge_expires_at) <= Date.now() && (
                    <button
                      type="button"
                      className="btn"
                      disabled={!!busy}
                      onClick={() => run(origin)}
                    >
                      Create fresh ownership challenge
                    </button>
                  )}
                  <p>Choose one proof:</p>
                  <details>
                    <summary>DNS TXT record</summary>
                    <p>
                      Name: <code>{record.dns.name}</code>
                    </p>
                    <p>
                      Value: <code>{record.dns.value}</code>
                    </p>
                    <button
                      type="button"
                      className="btn"
                      disabled={!!busy}
                      onClick={() => run(origin, record.id, "dns")}
                    >
                      Check DNS proof
                    </button>
                  </details>
                  <details>
                    <summary>HTML meta tag</summary>
                    <pre
                      style={{
                        whiteSpace: "pre-wrap",
                        overflowWrap: "anywhere",
                      }}
                    >
                      {record.meta_tag}
                    </pre>
                    <button
                      type="button"
                      className="btn"
                      disabled={!!busy}
                      onClick={() => run(origin, record.id, "meta")}
                    >
                      Check meta tag
                    </button>
                  </details>
                  <details>
                    <summary>Well-known file</summary>
                    <p>{record.file.url}</p>
                    <pre
                      style={{
                        whiteSpace: "pre-wrap",
                        overflowWrap: "anywhere",
                      }}
                    >
                      {record.file.content}
                    </pre>
                    <button
                      type="button"
                      className="btn"
                      disabled={!!busy}
                      onClick={() => run(origin, record.id, "file")}
                    >
                      Check verification file
                    </button>
                  </details>
                </>
              ) : (
                <button
                  type="button"
                  className="btn"
                  disabled={!!busy}
                  onClick={() => run(origin)}
                >
                  Create ownership challenge
                </button>
              )}
            </div>
          );
        })}
      {busy && <p role="status">Checking website ownership…</p>}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
