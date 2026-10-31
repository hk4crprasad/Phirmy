import Link from "next/link";
import { ArrowRight, AudioLines, BookOpen } from "lucide-react";
import ThemeSwitcher from "./theme-switcher";

export default function PageMissing() {
  return (
    <main className="missing-page">
      <header className="state-header">
        <Link href="/" className="state-brand" aria-label="Phirmy home">
          <AudioLines size={24} />
          Phirmy
        </Link>
        <ThemeSwitcher />
      </header>
      <section className="missing-content">
        <div className="missing-art" aria-hidden="true">
          <span>4</span>
          <div className="missing-orbit">
            <AudioLines size={46} strokeWidth={1.2} />
            <i />
            <i />
          </div>
          <span>4</span>
        </div>
        <span className="eyebrow muted">A SMALL DETOUR</span>
        <h1>This page is off the map.</h1>
        <p>
          The link may have moved, or the address might need another look. Let’s
          get you back to your conversations.
        </p>
        <div className="state-actions">
          <Link href="/app" className="btn primary">
            Open workspace
            <ArrowRight size={16} />
          </Link>
          <Link href="/" className="btn">
            Back to home
          </Link>
        </div>
        <Link href="/docs" className="missing-docs">
          <BookOpen size={15} />
          Looking for the developer guide?
        </Link>
      </section>
      <footer className="state-footer">
        Your knowledge. Your voice. A clearer way forward.
      </footer>
    </main>
  );
}
