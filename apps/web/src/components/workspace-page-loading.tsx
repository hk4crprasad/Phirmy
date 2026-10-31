export function WorkspacePageLoading({
  label = "Loading page…",
}: {
  label?: string;
}) {
  return (
    <section className="workspace-page-loading" role="status" aria-busy="true">
      <h1>{label}</h1>
      <p>Your navigation is ready. This page is loading.</p>
      <div
        className="skeleton workspace-placeholder-heading"
        aria-hidden="true"
      />
      <div className="loading-cards" aria-hidden="true">
        {[0, 1, 2].map((n) => (
          <div className="skeleton" key={n} />
        ))}
      </div>
    </section>
  );
}
