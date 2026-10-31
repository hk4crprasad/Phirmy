import { Row } from "@/lib/api";
import { Badge, Table } from "./ui";

const ms = (value: number | null | undefined) =>
  value == null ? "—" : `${Math.round(value)} ms`;

export function CallLatency({ timing }: { timing?: Row }) {
  if (!timing?.items?.length)
    return (
      <p className="small-text muted">No voice timing sample was captured.</p>
    );
  return (
    <section className="stack">
      <h3 className="section-title">Voice response timing</h3>
      <p className="small-text muted">
        {timing.basis} Latest {timing.sample_limit} turn samples. Synthetic and
        live samples are kept separate.
      </p>
      {timing.summaries.map((summary: Row) => (
        <p key={summary.source}>
          <Badge value={summary.source} /> {summary.completed_stt_turns}/
          {summary.stt_turns} completed transcript turns · p50{" "}
          {ms(summary.final_transcript_to_first_audio_p50_ms)} · p95{" "}
          {ms(summary.final_transcript_to_first_audio_p95_ms)} ·{" "}
          {summary.interrupted_stt_turns} interrupted ·{" "}
          {summary.failed_stt_turns} failed
        </p>
      ))}
      <Table
        rows={timing.items}
        columns={[
          {
            label: "Turn",
            render: (row) => (
              <>
                {row.input_kind} · {row.status}
                <small>{row.source}</small>
              </>
            ),
          },
          {
            label: "Final transcript → first audio",
            render: (row) =>
              ms(row.durations_ms?.final_transcript_to_first_audio_ms),
          },
          {
            label: "Retrieval",
            render: (row) => ms(row.durations_ms?.retrieval_ms),
          },
          {
            label: "Model first token",
            render: (row) => ms(row.durations_ms?.llm_first_token_ms),
          },
          {
            label: "TTS first byte",
            render: (row) => ms(row.durations_ms?.tts_first_byte_ms),
          },
          {
            label: "Byte → audio sent",
            render: (row) => ms(row.durations_ms?.tts_byte_to_audio_sent_ms),
          },
        ]}
      />
    </section>
  );
}
