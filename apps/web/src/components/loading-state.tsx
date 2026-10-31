import { AudioLines } from "lucide-react";

export function LoadingMark() {
  return (
    <span className="loading-mark" aria-hidden="true">
      {[0, 1, 2, 3, 4].map((n) => (
        <i key={n} style={{ "--bar": n } as React.CSSProperties} />
      ))}
    </span>
  );
}

export default function LoadingState({
  label = "Getting things ready…",
  workspace = false,
}: {
  label?: string;
  workspace?: boolean;
}) {
  return (
    <div
      className={
        "loading-state " + (workspace ? "loading-workspace" : "loading-page")
      }
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <div className="loading-brand">
        <AudioLines size={23} />
        <span>
          voice<strong>studio</strong>
        </span>
      </div>
      <div className="loading-center">
        <LoadingMark />
        <h1>{label}</h1>
        <p>Your next conversation is on its way.</p>
      </div>
      {workspace && (
        <div className="loading-preview" aria-hidden="true">
          <div className="skeleton loading-heading" />
          <div className="loading-cards">
            {[0, 1, 2, 3].map((n) => (
              <div className="loading-card" key={n}>
                <span className="skeleton" />
                <span className="skeleton" />
              </div>
            ))}
          </div>
          <div className="skeleton loading-panel" />
        </div>
      )}
    </div>
  );
}
