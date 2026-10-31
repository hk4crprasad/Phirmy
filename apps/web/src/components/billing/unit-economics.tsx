"use client";
import { useState } from "react";
import { money, Row } from "@/lib/api";
import { Badge, Table } from "../ui";

export function UnitEconomics({ report }: { report: Row }) {
  const [selected, setSelected] = useState(report.default_model);
  const model =
    report.models.find((row: Row) => row.id === selected) || report.models[0];
  const cost = (plan: Row, channel: string) => {
    const scenario = plan.scenarios.find((row: Row) => row.channel === channel);
    return (
      <>
        <span>{money(scenario.allowance_cost_micro_minor / 1e6)}</span>
        {scenario.cost_exceeds_price && <Badge value="Above plan price" />}
        {scenario.cost_exceeds_spend_cap && (
          <small>Spend cap stops full allowance</small>
        )}
      </>
    );
  };
  return (
    <details className="stack unit-economics">
      <summary>DRAFT plan unit economics and allowance risk</summary>
      <p>{report.assumptions.notes}</p>
      <p>{report.basis}</p>
      <label>
        Cost scenario model
        <select
          value={model.id}
          onChange={(event) => setSelected(event.target.value)}
        >
          {report.models.map((row: Row) => (
            <option value={row.id} key={row.id}>
              {row.id}
            </option>
          ))}
        </select>
      </label>
      <p>
        Per chat turn: {money(model.unit_cost_micro_minor.chat_turn / 1e6)} ·
        Browser voice / minute:{" "}
        {money(model.unit_cost_micro_minor.browser_voice_minute / 1e6)} · Phone
        / minute: {money(model.unit_cost_micro_minor.phone_voice_minute / 1e6)}
      </p>
      <Table
        rows={model.plans}
        columns={[
          {
            label: "Plan / monthly price",
            render: (row) => (
              <>
                {row.name} · {money(row.monthly_price_minor)}
                {row.quote_required && (
                  <small>Quote required; price remains DRAFT</small>
                )}
              </>
            ),
          },
          { label: "Chat allowance", render: (row) => cost(row, "chat") },
          {
            label: "Browser voice allowance",
            render: (row) => cost(row, "browser_voice"),
          },
          {
            label: "Phone allowance",
            render: (row) => cost(row, "phone_voice"),
          },
          {
            label: "Chat + browser + knowledge",
            render: (row) => cost(row, "chat_and_browser_voice"),
          },
          {
            label: "Chat + phone + knowledge",
            render: (row) => cost(row, "chat_and_phone_voice"),
          },
        ]}
      />
      <p>
        Workload assumptions: {report.assumptions.chat_input_tokens_per_turn}{" "}
        input / {report.assumptions.chat_output_tokens_per_turn} output tokens
        per chat turn; {report.assumptions.voice_turns_per_minute} voice turns
        per minute at {report.assumptions.voice_input_tokens_per_turn} input /{" "}
        {report.assumptions.voice_output_tokens_per_turn} output tokens each;{" "}
        {report.assumptions.voice_tts_utf8_bytes_per_minute} speech UTF-8 bytes
        per minute; {report.assumptions.crawl_embedding_tokens_per_page}{" "}
        embedding tokens per crawled page. Free is a subsidy. Custom needs a
        quote. A loss flag does not approve a price.
      </p>
    </details>
  );
}
