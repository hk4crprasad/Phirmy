import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { legalDocuments, legalPolicy } from "@/lib/legal";

type Props = { params: Promise<{ document: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { document } = await params;
  const policy = Object.hasOwn(legalDocuments, document)
    ? legalDocuments[document]
    : undefined;
  return {
    title: policy
      ? `${policy.title} · Phirmy`
      : "Document not found · Phirmy",
    description: policy
      ? `${policy.title}. Version ${legalPolicy.version}. ${legalPolicy.notice}`
      : undefined,
  };
}

export default async function LegalPage({ params }: Props) {
  const { document } = await params;
  if (!Object.hasOwn(legalDocuments, document)) notFound();
  const policy = legalDocuments[document];
  return (
    <main className="legal-page">
      <Link href="/">Phirmy</Link>
      <article>
        <p className="eyebrow">
          {legalPolicy.status} · Version {legalPolicy.version}
        </p>
        <h1>{policy.title}</h1>
        <p className="notice" role="note">
          {legalPolicy.notice}
        </p>
        {policy.sections.map((section) => (
          <section key={section.title}>
            <h2>{section.title}</h2>
            <p>{section.body}</p>
          </section>
        ))}
      </article>
      <nav aria-label="Legal documents">
        {Object.entries(legalDocuments).map(([id, value]) => (
          <Link
            key={id}
            href={`/legal/${id}`}
            aria-current={id === document ? "page" : undefined}
          >
            {value.title}
          </Link>
        ))}
      </nav>
    </main>
  );
}
