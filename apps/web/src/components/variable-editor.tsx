"use client";
import { Plus, Trash2, Braces } from "lucide-react";
import { Row } from "@/lib/api";

export default function VariableEditor({
  value,
  onChange,
}: {
  value: Row[];
  onChange: (value: Row[]) => void;
}) {
  function update(index: number, patch: Row) {
    onChange(value.map((v, i) => (i === index ? { ...v, ...patch } : v)));
  }
  return (
    <section className="variable-editor">
      <div className="variable-heading">
        <div>
          <h3>
            <Braces size={16} />
            Conversation variables
          </h3>
          <p className="field-note">
            Personalize greetings, instructions and tool inputs with{" "}
            {"{{customer_name}}"}. Website values are public context; keep
            credentials in tool headers.
          </p>
        </div>
        <button
          type="button"
          className="btn small"
          disabled={value.length >= 30}
          onClick={() => {
            let name = "customer_name",
              number = 2;
            while (value.some((v) => v.name === name))
              name = "variable_" + number++;
            onChange([
              ...value,
              { name, description: "", required: false, default: null },
            ]);
          }}
        >
          <Plus size={14} />
          Add variable
        </button>
      </div>
      {!value.length && (
        <p className="muted small-text">
          No variables yet. Add one when a conversation needs context such as a
          customer name or order ID.
        </p>
      )}
      {value.map((v, index) => (
        <div className="variable-card" key={index}>
          <div className="variable-fields">
            <label>
              Name
              <input
                aria-label={"Variable name " + (index + 1)}
                value={v.name}
                onChange={(e) => update(index, { name: e.target.value })}
                pattern="[A-Za-z][A-Za-z0-9_]*"
                maxLength={60}
                placeholder="customer_name"
              />
            </label>
            <label>
              Default value
              <input
                value={v.default ?? ""}
                onChange={(e) =>
                  update(index, { default: e.target.value || null })
                }
                maxLength={2000}
                placeholder="Optional"
              />
            </label>
          </div>
          <label>
            Description
            <input
              value={v.description || ""}
              onChange={(e) => update(index, { description: e.target.value })}
              maxLength={500}
              placeholder="What should this value contain?"
            />
          </label>
          <div className="row variable-footer">
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={!!v.required}
                onChange={(e) => update(index, { required: e.target.checked })}
              />
              Require a value before starting
            </label>
            <button
              type="button"
              className="btn subtle"
              aria-label={"Remove variable " + v.name}
              onClick={() => onChange(value.filter((_, i) => i !== index))}
            >
              <Trash2 size={14} />
              Remove
            </button>
          </div>
        </div>
      ))}
    </section>
  );
}
