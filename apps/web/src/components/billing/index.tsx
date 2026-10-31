"use client";
import { useCallback, useEffect, useState, useRef } from "react";
import { Download, RefreshCw, Wallet } from "lucide-react";
import { api, authenticatedFetch, command, money, Row, when } from "@/lib/api";
import { Badge, Dialog, Header, Panel, StudioContext, Table } from "../ui";
import { loadCheckout } from "./checkout";

type Review = { result: Row; amount: number; plan?: string; key: string };
const labels: Record<string, string> = {
  conversations: "Conversations",
  chat_turns: "Chat turns",
  voice_ms: "Voice minutes",
  crawl_pages: "Crawled pages",
  storage_bytes: "Stored files",
  seats: "Team seats",
  widgets: "Widgets",
};
function quantity(resource: string, value: number) {
  if (resource === "voice_ms")
    return (value / 60000).toLocaleString(undefined, {
      maximumFractionDigits: 1,
    });
  if (resource === "storage_bytes")
    return `${(value / 1000000).toLocaleString(undefined, { maximumFractionDigits: 1 })} MB`;
  return value.toLocaleString();
}

export default function Billing({ ctx }: { ctx: StudioContext }) {
  const [wallet, setWallet] = useState<Row>({}),
    [usage, setUsage] = useState<Row>({}),
    [profile, setProfile] = useState<Row>({});
  const [tariff, setTariff] = useState<Row>({}),
    [plans, setPlans] = useState<Row>({}),
    [orders, setOrders] = useState<Row[]>([]);
  const [invoices, setInvoices] = useState<Row[]>([]),
    [subscriptions, setSubscriptions] = useState<Row>({ items: [] });
  const [review, setReview] = useState<Review | null>(null),
    [amount, setAmount] = useState("1000"),
    [error, setError] = useState("");
  const [busy, setBusy] = useState(false),
    [waiting, setWaiting] = useState(false);
  const profileDirty = useRef(false);
  const canManage = ["owner", "admin", "billing"].includes(
    String(ctx.workspace.role),
  );
  const refresh = useCallback(async () => {
    const [w, u, p, t, c, o, i, s] = await Promise.all([
      api(ctx.base + "/wallet"),
      api(ctx.base + "/billing/usage"),
      api(ctx.base + "/billing/profile"),
      api(ctx.base + "/billing/tariff"),
      api("/v1/public/plans"),
      api(ctx.base + "/payments"),
      api(ctx.base + "/billing/invoices"),
      api(ctx.base + "/billing/subscriptions"),
    ]);
    setWallet(w);
    setUsage(u);
    if (!profileDirty.current) setProfile(p);
    setTariff(t);
    setPlans(c);
    setOrders(o.items);
    setInvoices(i.items);
    setSubscriptions(s);
  }, [ctx.base]);
  useEffect(() => {
    refresh().catch((e) => setError(e.message));
  }, [refresh]);
  useEffect(() => {
    if (!waiting && !invoices.some((x) => !x.download_ready)) return;
    let ticks = 0;
    const timer = window.setInterval(() => {
      if (++ticks > 24) {
        window.clearInterval(timer);
        setWaiting(false);
        return;
      }
      refresh().catch((e) => setError(e.message));
    }, 5000);
    return () => window.clearInterval(timer);
  }, [waiting, invoices.some((x) => !x.download_ready), refresh]);
  async function act(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function saveProfile() {
    return act(async () => {
      const saved = await command(
        ctx.base + "/billing/profile",
        profile,
        "PUT",
      );
      profileDirty.current = false;
      setProfile(saved);
      ctx.notify("Billing details saved");
    });
  }
  async function price(plan?: string) {
    await act(async () => {
      if (profileDirty.current)
        throw Error("Save billing details before reviewing a payment.");
      const minor = Math.round(Number(amount) * 100);
      if (
        !plan &&
        (!Number.isFinite(minor) || minor < 10000 || minor > 10000000)
      )
        throw Error("Enter INR 100 to INR 100,000.");
      const result = await api(
        ctx.base +
          "/billing/quote?" +
          (plan
            ? "purpose=subscription&plan_slug=" + encodeURIComponent(plan)
            : "amount_minor=" + minor),
      );
      setReview({
        result,
        amount: plan ? result.quote.requested_amount_minor : minor,
        plan,
        key: crypto.randomUUID(),
      });
    });
  }
  async function openSubscription(row: Row) {
    const Checkout = await loadCheckout();
    const checkout = new Checkout({
      key: subscriptions.key_id,
      subscription_id: row.provider_id,
      name: "Phirmy",
      description: "Monthly subscription",
      prefill: { name: profile.legal_name, email: profile.email },
      handler: async (proof: Row) => {
        setWaiting(true);
        await act(async () => {
          await command(
            ctx.base + "/billing/subscriptions/" + row.id + "/verify",
            {
              razorpay_subscription_id: proof.razorpay_subscription_id,
              razorpay_payment_id: proof.razorpay_payment_id,
              razorpay_signature: proof.razorpay_signature,
            },
          );
          await refresh();
          await ctx.refresh();
          ctx.notify(
            "Checkout verified. Plan access follows the captured payment.",
          );
        });
      },
      modal: { ondismiss: () => setWaiting(true) },
      theme: { color: "#242321" },
    });
    checkout.on?.("payment.failed", () => {
      setError(
        "Payment was not completed. No plan access was granted for this attempt.",
      );
      setWaiting(true);
    });
    checkout.open();
  }
  async function checkout() {
    if (!review) return;
    const selected = review;
    await act(async () => {
      const row = await api(
        ctx.base +
          (selected.plan ? "/billing/subscriptions" : "/payments/orders"),
        {
          method: "POST",
          headers: { "Idempotency-Key": selected.key },
          body: JSON.stringify(
            selected.plan
              ? {
                  plan_slug: selected.plan,
                  quote_token: selected.result.quote_token,
                }
              : {
                  amount_minor: selected.amount,
                  quote_token: selected.result.quote_token,
                },
          ),
        },
      );
      setWaiting(true);
      await refresh();
      if (selected.plan) {
        setReview(null);
        ctx.notify(
          "Subscription requested. Continue checkout when its status is ready.",
        );
        return;
      }
      const Checkout = await loadCheckout();
      const gateway = new Checkout({
        key: row.key_id,
        amount: row.amount_minor,
        currency: row.currency,
        order_id: row.provider_order_id,
        name: "Phirmy",
        description: "Wallet funding",
        prefill: { name: profile.legal_name, email: profile.email },
        handler: async (proof: Row) => {
          setWaiting(true);
          await act(async () => {
            const verified = await command(ctx.base + "/payments/verify", {
              razorpay_order_id: proof.razorpay_order_id,
              razorpay_payment_id: proof.razorpay_payment_id,
              razorpay_signature: proof.razorpay_signature,
            });
            await refresh();
            await ctx.refresh();
            ctx.notify(
              verified.state === "credited"
                ? "Payment verified; billing balance updated"
                : "Payment reconciled: " + verified.state,
            );
          });
        },
        modal: { ondismiss: () => setWaiting(true) },
        theme: { color: "#242321" },
      });
      gateway.on?.("payment.failed", () => {
        setError(
          "Payment was not completed. No credit was posted for this attempt.",
        );
        setWaiting(true);
      });
      gateway.open();
      setReview(null);
    });
  }
  function refund(row: Row) {
    const key = crypto.randomUUID();
    ctx.form({
      title: "Refund unspent credit",
      description:
        "Refunds return to the original payment method. The provider may take several working days. Amounts include the original GST.",
      fields: [
        {
          key: "amount",
          label: "Refund amount · INR",
          type: "number",
          min: 0.01,
          max: row.amount_minor / 100,
          value: row.amount_minor / 100,
          required: true,
        },
      ],
      submit: "Request refund",
      action: async (values) => {
        await api(ctx.base + "/payments/" + row.id + "/refunds", {
          method: "POST",
          headers: { "Idempotency-Key": key },
          body: JSON.stringify({
            amount_minor: Math.round(Number(values.amount) * 100),
          }),
        });
        await refresh();
        setWaiting(true);
        ctx.notify(
          "Refund requested. Balance changes when the provider confirms it.",
        );
      },
    });
  }
  function cancel(row: Row) {
    const key = crypto.randomUUID();
    ctx.form({
      title: "Cancel subscription renewal",
      description:
        "Already-paid coverage continues until its end date. The workspace then follows Free plan allowances.",
      fields: [],
      submit: "Cancel renewal",
      action: async () => {
        await api(ctx.base + "/billing/subscriptions/" + row.id + "/cancel", {
          method: "POST",
          headers: { "Idempotency-Key": key },
          body: JSON.stringify({ at_cycle_end: true }),
        });
        await refresh();
        setWaiting(true);
        ctx.notify("Cancellation requested");
      },
    });
  }
  async function download(row: Row) {
    await act(async () => {
      const response = await authenticatedFetch(
        ctx.base + "/billing/invoices/" + row.id + "/pdf",
      );
      if (!response.ok)
        throw Error("The invoice PDF is not ready. Refresh and try again.");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = row.number.replaceAll("/", "-") + ".pdf";
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
  }
  const draft = plans.status !== "APPROVED";
  return (
    <>
      <Header
        eyebrow="BILLING"
        title="Usage, plans and invoices."
        description="Plan allowances, available credit and verified payment records."
      >
        <button className="btn" onClick={() => act(refresh)} disabled={busy}>
          <RefreshCw size={14} />
          Refresh
        </button>
      </Header>
      {(draft || !plans.paid_activation_enabled) && (
        <div className="notice" role="status">
          Plan prices and business details require approval. Paid activation is
          disabled; DRAFT totals can be reviewed below.
        </div>
      )}
      {wallet.development_credit && (
        <div className="notice">
          This workspace includes synthetic development credit. It is separate
          from purchased funds.
        </div>
      )}
      {(usage.operator_paused || usage.billing_blocked) && (
        <div className="error" role="status">
          New workspace spending is paused. Review payment adjustments or
          contact the workspace owner.
        </div>
      )}
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      <div className="stats-grid">
        {[
          ["Wallet balance", wallet.balance_minor],
          ["Reserved for calls", wallet.reserved_minor],
          ["Payment holds", wallet.at_risk_minor],
          ["Available credit", wallet.available_minor],
        ].map(([label, value]) => (
          <div className="stat" key={String(label)}>
            <span className="stat-top">
              {label}
              <Wallet size={14} />
            </span>
            <div className="stat-value">
              {money(Number(value || 0), wallet.currency || "INR")}
            </div>
          </div>
        ))}
      </div>
      {!!wallet.billing_adjustment_minor && (
        <div className="notice">
          Billing adjustment awaiting resolution:{" "}
          {money(wallet.billing_adjustment_minor, wallet.currency || "INR")}.
          New funds first settle this adjustment.
        </div>
      )}
      <div className="stack">
        <Panel
          title={`${usage.plan || "Free"} plan usage`}
          note={
            usage.period_start
              ? `${when(usage.period_start)} – ${when(usage.period_end)}`
              : "Current billing period"
          }
        >
          {usage.development_allowance_multiplier > 1 && (
            <p>Development allowances are enabled for this environment.</p>
          )}
          {usage.plan === "free" && (
            <p>
              Free allowances are shared across workspaces created by the same
              account.
            </p>
          )}
          {usage.shared_free && (
            <details>
              <summary>Shared Free allowance across your workspaces</summary>
              <p>
                Resets monthly in UTC. Changing workspace timezone or ownership
                does not reset this pool.
              </p>
              <Table
                rows={Object.entries(labels).map(([id, name]) => ({
                  id,
                  name,
                }))}
                columns={[
                  { label: "Allowance", render: (row) => row.name },
                  {
                    label: "Measured across workspaces",
                    render: (row) =>
                      quantity(
                        row.id,
                        Number(usage.shared_free.usage[row.id] || 0),
                      ),
                  },
                  {
                    label: "Reserved",
                    render: (row) =>
                      quantity(
                        row.id,
                        Number(usage.shared_free.reserved[row.id] || 0),
                      ),
                  },
                  {
                    label: "Shared limit",
                    render: (row) =>
                      quantity(
                        row.id,
                        Number(usage.shared_free.included[row.id] || 0),
                      ),
                  },
                ]}
              />
              <p>
                Shared provider estimate:{" "}
                {money(usage.shared_free.provider_cost_micro_minor / 1e6)} of{" "}
                {money(usage.shared_free.spend_cap_minor)}. Pending
                reservations:{" "}
                {money(usage.shared_free.held_cost_micro_minor / 1e6)}.
              </p>
            </details>
          )}
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Allowance</th>
                  <th>Measured</th>
                  <th>Reserved</th>
                  <th>Limit</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(labels).map(([resource, label]) => (
                  <tr key={resource}>
                    <td>{label}</td>
                    <td>
                      {quantity(resource, Number(usage.usage?.[resource] || 0))}
                    </td>
                    <td>
                      {quantity(
                        resource,
                        Number(usage.reserved?.[resource] || 0),
                      )}
                    </td>
                    <td>
                      {quantity(
                        resource,
                        Number(usage.effective_included?.[resource] || 0),
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            Estimated provider spend:{" "}
            {money(
              Number(usage.estimated_provider_cost_micro_minor || 0) / 1000000,
            )}{" "}
            of {money(usage.provider_spend_cap_minor)}. Pending cost
            reservations:{" "}
            {money(Number(usage.held_cost_micro_minor || 0) / 1000000)}.
          </p>
          {!!usage.unreported_requests && (
            <p>
              Some requests await usage confirmation. Their reserved budget is
              retained while they are reconciled.
            </p>
          )}
          <p>
            Voice pricing:{" "}
            {tariff.voice_billing === "wallet"
              ? `${money(tariff.voice_retail_minor_per_minute)} per minute from wallet credit`
              : "Admitted minutes use the plan allowance"}
            . {tariff.status === "DRAFT" && "DRAFT terms."}
          </p>
        </Panel>
        <Panel
          title="Plans"
          note="GST and the complete payment total are shown before checkout."
        >
          <div className="billing-plan-grid">
            {(plans.items || []).map((plan: Row) => (
              <article className="billing-plan" key={plan.id}>
                <h3>
                  {plan.name} {draft && <Badge value="DRAFT" />}
                </h3>
                <strong>{money(plan.monthly_price_minor)} / month</strong>
                <p>
                  {plan.included.conversations.toLocaleString()} conversations ·{" "}
                  {quantity("voice_ms", plan.included.voice_ms)} voice minutes
                </p>
                <p>
                  {plan.included.crawl_pages} crawled pages ·{" "}
                  {quantity("storage_bytes", plan.included.storage_bytes)}
                </p>
                <p>
                  {plan.included.seats} seats · {plan.included.widgets} widgets
                </p>
                {plan.id === usage.plan ? (
                  <Badge value="current" />
                ) : plan.id === "free" ? (
                  <span>Free allowance</span>
                ) : plan.self_serve ? (
                  <button
                    className="btn"
                    disabled={busy || !canManage}
                    onClick={() => price(plan.id)}
                  >
                    Review {plan.name}
                  </button>
                ) : (
                  <span>Custom agreement required</span>
                )}
              </article>
            ))}
          </div>
        </Panel>
        <Panel
          title="Billing details"
          note="These details appear on your invoices. GSTIN checks validate format and checksum, without claiming government verification."
        >
          <form
            className="billing-profile"
            onSubmit={(e) => {
              e.preventDefault();
              saveProfile();
            }}
          >
            {[
              ["legal_name", "Billing name"],
              ["address", "Billing address"],
              ["state_code", "State code · two digits"],
              ["gstin", "GSTIN · optional"],
              ["email", "Billing email"],
            ].map(([key, label]) => (
              <label key={key}>
                {label}
                <input
                  aria-label={label}
                  required={key !== "gstin"}
                  type={key === "email" ? "email" : "text"}
                  maxLength={
                    key === "address"
                      ? 1000
                      : key === "state_code"
                        ? 2
                        : key === "gstin"
                          ? 15
                          : key === "email"
                            ? 254
                            : 160
                  }
                  disabled={!canManage}
                  value={String(profile[key] || "")}
                  onChange={(e) => {
                    profileDirty.current = true;
                    setProfile({ ...profile, [key]: e.target.value });
                  }}
                />
              </label>
            ))}
            <button className="btn primary" disabled={busy || !canManage}>
              Save billing details
            </button>
          </form>
        </Panel>
        <Panel
          title="Add wallet credit"
          note="Only captured, server-verified payments change your balance."
        >
          <div className="billing-topup">
            <label>
              Amount · INR
              <input
                aria-label="Top-up amount · INR"
                type="number"
                min="100"
                max="100000"
                step="0.01"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
              />
            </label>
            <button
              className="btn primary"
              disabled={busy || !canManage}
              onClick={() => price()}
            >
              Review top-up
            </button>
          </div>
        </Panel>
        <Panel title="Subscriptions">
          <Table
            rows={subscriptions.items || []}
            columns={[
              { label: "Plan", render: (r) => r.plan_slug },
              { label: "Status", render: (r) => <Badge value={r.state} /> },
              { label: "Paid through", render: (r) => when(r.paid_period_end) },
              {
                label: "Actions",
                render: (r) => (
                  <div className="actions">
                    {r.provider_id &&
                      ["created", "authenticated"].includes(r.state) && (
                        <button
                          className="btn"
                          disabled={
                            busy || !canManage || !plans.paid_activation_enabled
                          }
                          onClick={() => act(() => openSubscription(r))}
                        >
                          Continue checkout
                        </button>
                      )}
                    {r.state === "unknown" && (
                      <button
                        className="btn"
                        disabled={busy || !canManage}
                        onClick={() =>
                          act(async () => {
                            await command(
                              ctx.base +
                                "/billing/subscriptions/" +
                                r.id +
                                "/reconcile",
                            );
                            setWaiting(true);
                            await refresh();
                          })
                        }
                      >
                        Reconcile
                      </button>
                    )}
                    {!["cancelled", "completed", "expired"].includes(
                      r.state,
                    ) && (
                      <button
                        className="btn"
                        disabled={busy || !canManage}
                        onClick={() => cancel(r)}
                      >
                        Cancel renewal
                      </button>
                    )}
                  </div>
                ),
              },
            ]}
          />
        </Panel>
        <Panel title="Invoices and credit notes">
          <Table
            rows={invoices}
            columns={[
              {
                label: "Document",
                render: (r) => (
                  <>
                    <strong>{r.number}</strong>
                    <span className="cell-sub">
                      {r.kind.replaceAll("_", " ")}
                    </span>
                  </>
                ),
              },
              { label: "Status", render: (r) => <Badge value={r.status} /> },
              { label: "Tax", render: (r) => money(r.tax.tax_minor) },
              { label: "Total", render: (r) => money(r.tax.gross_minor) },
              {
                label: "PDF",
                render: (r) => (
                  <button
                    className="btn"
                    disabled={busy || !r.download_ready}
                    onClick={() => download(r)}
                  >
                    <Download size={14} />
                    {r.download_ready ? "Download" : "Preparing PDF"}
                  </button>
                ),
              },
              { label: "Emailed", render: (r) => when(r.emailed_at) },
            ]}
          />
        </Panel>
        <Panel title="Payment records">
          <Table
            rows={orders}
            columns={[
              {
                label: "Reference",
                render: (r) =>
                  r.provider_payment_id ||
                  r.provider_order_id ||
                  "Awaiting provider",
              },
              { label: "Status", render: (r) => <Badge value={r.state} /> },
              {
                label: "Credit / fee",
                render: (r) => money(r.net_minor ?? r.amount_minor),
              },
              { label: "Payment", render: (r) => money(r.amount_minor) },
              { label: "Date", render: (r) => when(r.created_at) },
              {
                label: "Refund",
                render: (r) =>
                  r.kind === "wallet" &&
                  ["credited", "partially_refunded"].includes(r.state) ? (
                    <button
                      className="btn"
                      disabled={busy || !canManage}
                      onClick={() => refund(r)}
                    >
                      Refund unspent credit
                    </button>
                  ) : null,
              },
            ]}
          />
        </Panel>
        <Panel title="Wallet ledger">
          <Table
            rows={ctx.data.ledger || []}
            columns={[
              { label: "Entry", render: (r) => r.description },
              { label: "Amount", render: (r) => money(r.amount_minor) },
              { label: "Date", render: (r) => when(r.created_at) },
            ]}
          />
        </Panel>
      </div>
      {review && (
        <Dialog
          title={review.plan ? "Review subscription" : "Review wallet funding"}
          close={() => !busy && setReview(null)}
        >
          <div className="billing-review">
            <p>{review.result.quote.description}</p>
            <Badge value={review.result.quote.price_status} />
            <dl>
              {[
                [
                  review.plan ? "Service amount before GST" : "Wallet credit",
                  review.result.quote.tax.net_minor,
                ],
                ["CGST", review.result.quote.tax.cgst_minor],
                ["SGST", review.result.quote.tax.sgst_minor],
                ["IGST", review.result.quote.tax.igst_minor],
                ["Total payment", review.result.quote.tax.gross_minor],
              ].map(([label, value]) => (
                <div key={String(label)}>
                  <dt>{label}</dt>
                  <dd>{money(Number(value))}</dd>
                </div>
              ))}
            </dl>
            <p>
              Bill to {review.result.quote.buyer.legal_name}, state{" "}
              {review.result.quote.buyer.state_code}.
            </p>
            {!review.result.checkout_enabled && (
              <p className="notice">
                DRAFT preview. Paid checkout is disabled until prices, invoice
                details and payment setup are approved.
              </p>
            )}
            <button
              className="btn primary"
              disabled={
                busy ||
                !review.result.checkout_enabled ||
                !canManage ||
                !plans.paid_activation_enabled
              }
              onClick={checkout}
            >
              {review.plan ? "Confirm subscription" : "Confirm payment"}
            </button>
            <button
              className="btn"
              disabled={busy}
              onClick={() => setReview(null)}
            >
              Close review
            </button>
          </div>
        </Dialog>
      )}
    </>
  );
}
