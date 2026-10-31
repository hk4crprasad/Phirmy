import Link from "next/link";
import { AudioLines, ArrowUpRight, ArrowLeft } from "lucide-react";
import "./docs.css";
import ThemeSwitcher from "@/components/theme-switcher";
export const metadata = {
  title: "Phirmy · Developer documentation",
  description:
    "Connect your models, HTTP tools, knowledge, browser audio, Twilio and Plivo.",
};
const snippets = {
  session: `curl -X POST "$API/v1/workspaces/$WORKSPACE/voice/sessions" \\\n  -H "X-API-Key: $STUDIO_KEY" \\\n  -H 'Content-Type: application/json' \\\n  -d '{"agent_id":"AGENT_ID","mode":"simulation","variables":{"customer_name":"Alex"}}'`,
  model: `OPENAI_API_KEY=your_private_key\nOPENAI_MODEL=gpt-5.6-luna\nOPENAI_BASE_URL=https://api.openai.com/v1\nOPENAI_API_STYLE=auto\nOPENAI_TOKEN_PARAMETER=auto\nOPENAI_REASONING_EFFORT=auto`,
  tool: `curl -X POST "$API/v1/workspaces/$WORKSPACE/tools" \\\n  -H "X-API-Key: $STUDIO_KEY" \\\n  -H 'Content-Type: application/json' \\\n  -d '{\n    "name":"lookup_order",\n    "description":"Look up an order when the caller asks about its status.",\n    "method":"POST",\n    "url":"https://your-business.example/api/orders/lookup",\n    "arguments":{"type":"object","properties":{"order_id":{"type":"string"}},"required":["order_id"],"additionalProperties":false},\n    "body_template":{"order_id":"{{order_id}}"},\n    "headers":{"Authorization":"Bearer YOUR_BUSINESS_TOKEN"},\n    "timeout_seconds":15,\n    "execution_mode":"wait_for_result",\n    "error_handling":"hide",\n    "side_effecting":false\n  }'`,
  attach: `curl -X PUT "$API/v1/workspaces/$WORKSPACE/tools/$TOOL/access" \\\n  -H "X-API-Key: $STUDIO_KEY" -H 'Content-Type: application/json' \\\n  -d '{"agent_ids":["AGENT_ID"]}'\n# Publish the updated agent draft before starting a new session.`,
  test: `curl -X POST "$API/v1/workspaces/$WORKSPACE/tools/$TOOL/test" \\\n  -H "X-API-Key: $STUDIO_KEY" -H 'Idempotency-Key: test-order-123' \\\n  -H 'Content-Type: application/json' \\\n  -d '{"arguments":{"order_id":"ORD-123"},"mock":false}'`,
  knowledge: `curl -X POST "$API/v1/workspaces/$WORKSPACE/knowledge" \\\n  -H "X-API-Key: $STUDIO_KEY" -H 'Content-Type: application/json' \\\n  -d '{"name":"My business","website_url":"https://your-business.example","max_pages":20}'\n# The response is a job. Poll GET /jobs/{id} until completed or failed.`,
  browser: `// Your server creates a short-lived session. Never expose STUDIO_KEY.\nconst session = await fetch('/your-server/voice-session', {method:'POST'}).then(r => r.json());\nconst ws = new WebSocket(session.media_url);\nws.onopen = () => ws.send(JSON.stringify({\n  type:'client.start', session_token:session.session_token\n}));\nws.onmessage = event => {\n  if (typeof event.data !== 'string') return;\n  const message = JSON.parse(event.data);\n  if (message.type === 'server.ready') {\n    // Simulation only. Live mode sends framed PCM after ready.\n    ws.send(JSON.stringify({type:'client.text',text:'How can I book?'}));\n  }\n  console.log(message);\n};`,
  webhook: `# Configure your provider's owned number with these public URLs:\n# Twilio (POST, signed by Twilio):\nhttps://YOUR_API/v1/provider-webhooks/twilio/answer\nhttps://YOUR_API/v1/provider-webhooks/twilio/status\n\n# Plivo (POST, V3 signatures):\nhttps://YOUR_API/v1/provider-webhooks/plivo/answer\nhttps://YOUR_API/v1/provider-webhooks/plivo/hangup`,
  events: `curl -X POST "$API/v1/workspaces/$WORKSPACE/webhooks" \\\n  -H "X-API-Key: $STUDIO_KEY" -H 'Content-Type: application/json' \\\n  -d '{"url":"https://your-business.example/voice-events","events":["call.completed","ticket.created"],"enabled":true}'\n# Store the returned signing_secret privately. It is returned once.`,
};
const Code = ({ children }: { children: string }) => (
  <pre>
    <code>{children}</code>
  </pre>
);
export default function Docs() {
  return (
    <main className="developer-docs">
      <header>
        <Link href="/" className="brand">
          <AudioLines size={24} />
          Phirmy<span className="docs-label">Developers</span>
        </Link>
        <div className="docs-actions">
          <ThemeSwitcher />
          <Link href="/app">
            Open workspace
            <ArrowUpRight size={14} />
          </Link>
        </div>
      </header>
      <div className="docs-layout">
        <aside>
          <div>BUILD WITH PHIRMY</div>
          {[
            ["start", "Quick start"],
            ["accounts", "Accounts & sessions"],
            ["widgets", "Website widgets"],
            ["connections", "Calendars & contacts"],
            ["models", "Models & token limits"],
            ["tools", "Custom HTTP tools"],
            ["knowledge", "Knowledge ingestion"],
            ["voice", "Browser voice"],
            ["phone", "Phone providers"],
            ["events", "Event webhooks"],
            ["errors", "Errors & retries"],
          ].map(([id, title]) => (
            <a href={"#" + id} key={id}>
              {title}
            </a>
          ))}
          <a href="/backend/docs" target="_blank" rel="noreferrer">
            Interactive API reference
            <ArrowUpRight size={12} />
          </a>
        </aside>
        <article>
          <section id="start">
            <p className="docs-eyebrow">YOUR BUSINESS, CONNECTED</p>
            <h1>
              A voice agent that can
              <br />
              do the next thing.
            </h1>
            <p className="docs-intro">
              Use your model, your knowledge and your HTTP endpoints. The
              platform handles the conversation, scoped execution and the record
              of what happened.
            </p>
            <h2>Start a session</h2>
            <p>
              Create and publish an agent in your workspace. Create a scoped API
              key under Developers. Keep it on your server.
            </p>
            <Code>{snippets.session}</Code>
            <p>
              The response contains a short-lived session token, call ID and
              media URL. Simulation uses the real session and persistence path
              without contacting a phone or speech provider.
            </p>
          </section>
          <section id="accounts">
            <h2>One account. Your devices under control.</h2>
            <p>
              Sign in with Google or verify your email after password signup.
              Profile lets you update your details, connect Google and sign out
              other devices. Email links expire and can only be used once.
            </p>
            <p>
              Dashboard access uses short-lived HttpOnly JWT cookies and
              rotating refresh cookies. Browser mutations also need the current
              <code> X-CSRF-Token</code> and an allowed Origin. The web client
              refreshes expired access automatically. Server integrations use
              scoped API keys instead of dashboard cookies.
            </p>
            <p>
              Self-hosting requires Google OAuth and SMTP configuration before
              those sign-in methods can serve real users. The Google callback is
              <code> /backend/v1/auth/google/callback</code> on your app host.
            </p>
          </section>
          <section id="widgets">
            <h2>Put your published agent on a website.</h2>
            <p>
              Open Chat widget and enter your website URL. Choose a new or
              existing agent; public pages, products and policies connect
              through a background crawl. Confirm your exact website origins in
              Appearance, then copy the generated widget ID and publishable-key
              script into your site. Add context with
              <code> data-variables</code>; missing required values are
              collected before the conversation starts. Keep private credentials
              in tool settings rather than website variables.
            </p>
            <p>
              Widget sessions use a short-lived capability bound to their
              installation, publishable key and origin. History resumes across
              page navigation without dashboard cookies. The assistant
              recognizes indexed current pages and can open a permitted page or
              scroll to an indexed section when a visitor asks. Optional voice
              needs HTTPS, microphone permission and configured speech services.
              Disable the installation to revoke public use. Workspace turn and
              voice limits apply across conversations.
            </p>
          </section>
          <section id="connections">
            <h2>Connect your calendar and calling workflow.</h2>
            <p>
              Integrations stores encrypted credentials per workspace. Connect
              Google Calendar to check availability and sync a confirmed local
              appointment. An appointment is only on Google after remote sync
              succeeds. For Cal.com or Calendly, use the OAuth Connect button to
              authorize your account (or connect with an API key/personal
              token), choose a meeting type and enable booking in your agent’s
              Actions tab. Select its booking platform, then publish. During a
              call, the agent checks live availability, collects details and
              reads them back before asking for confirmation. Only an accepted
              provider result confirms the booking. Calendly requires Standard
              or above and Scheduling API permissions.
            </p>
            <p>
              Appointments shows booking requests and their latest checked
              status. Pending approval and uncertain submissions stay
              unconfirmed. Use Check status to reconcile a request, and Manage
              at provider to change or cancel it. A lost response never triggers
              another automatic booking.
            </p>
            <p>
              Contacts previews CSV imports, exports your address book and
              records permission to call. Additional CSV columns become contact
              variables. Select contacts with permission to create a campaign
              draft, then review it before starting. Real calling requires an
              activated carrier and verified owned number. No draft creation
              places a phone call.
            </p>
          </section>
          <section id="models">
            <h2>Bring your model</h2>
            <p>
              The server default supports the official OpenAI endpoint or a
              compatible host. Changing the environment requires an API restart.
            </p>
            <Code>{snippets.model}</Code>
            <table>
              <thead>
                <tr>
                  <th>Protocol</th>
                  <th>Output cap</th>
                  <th>Sampling</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Responses</td>
                  <td>max_output_tokens</td>
                  <td>Omitted by default</td>
                </tr>
                <tr>
                  <td>Chat Completions</td>
                  <td>max_completion_tokens</td>
                  <td>Omitted by default</td>
                </tr>
                <tr>
                  <td>Legacy / compatible Chat</td>
                  <td>max_tokens, if documented</td>
                  <td>Only when explicitly supported</td>
                </tr>
              </tbody>
            </table>
            <p>
              Support varies by model and reasoning mode. Open Models → Add
              model, supply the exact model ID, HTTPS base URL, key and provider
              documentation URL. Review its parameter rules, run the streaming
              test, and save. Select the profile on your agent and publish.
            </p>
            <p>
              Profiles store a documentation source and test evidence. A new key
              creates a new profile; disabling a profile prevents further use.
              The platform only negotiates a rejected token or temperature
              parameter before any text has streamed. It never replays a turn
              after emitting output.
            </p>
            <a
              href="https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create"
              target="_blank"
              rel="noreferrer"
            >
              Official parameter reference ↗
            </a>
          </section>
          <section id="tools">
            <h2>Your API becomes an agent tool.</h2>
            <p>
              Create a workspace tool, declare its argument schema and describe
              when to call it. Import cURL in the editor or create the
              definition through the API.
            </p>
            <Code>{snippets.tool}</Code>
            <p>
              cURL import is a parser. It never runs a shell, command
              substitution or local-file uploads. Headers are encrypted and
              write-only. Public URLs are validated and pinned to public IP
              addresses when connecting; redirects are not followed.
            </p>
            <h3>Templating</h3>
            <p>
              Use <code>{"{{order_id}}"}</code> for a declared argument and{" "}
              <code>{"{{system.call_id}}"}</code> for server context. Dotted
              paths read nested values. A placeholder occupying an entire JSON
              value preserves its type; values are JSON-encoded safely. URL
              placeholders are percent-encoded and cannot change the host.
            </p>
            <h3>Access and publishing</h3>
            <Code>{snippets.attach}</Code>
            <p>
              Tools have immutable revisions. Editing creates a new revision;
              reattach and publish to use it. Active calls keep their published
              definitions. Disabling a tool is an immediate revocation for all
              agents.
            </p>
            <h3>Test the endpoint</h3>
            <Code>{snippets.test}</Code>
            <p>
              A real test makes a real request. Set <code>mock:true</code> to
              use the stored mock without external traffic. The result includes
              HTTP status, elapsed time, a bounded response and an actual
              execution state. Headers and known credential values are redacted.
            </p>
            <table>
              <thead>
                <tr>
                  <th>Execution</th>
                  <th>Behavior</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>wait_for_result</td>
                  <td>
                    The model receives the persisted endpoint result before
                    continuing.
                  </td>
                </tr>
                <tr>
                  <td>background</td>
                  <td>
                    A durable job runs the request. Its result is visible in
                    execution history.
                  </td>
                </tr>
                <tr>
                  <td>fire_and_forget</td>
                  <td>
                    The conversation receives acceptance, not a completion
                    claim. The job remains auditable.
                  </td>
                </tr>
              </tbody>
            </table>
            <p>
              Use stable idempotency keys for operator requests. Network
              timeouts become <code>unknown</code>; reconcile before repeating a
              side effect. The endpoint receives an execution ID and
              Idempotency-Key that it can use for deduplication. Responses are
              limited to 64 KiB.
            </p>
          </section>
          <section id="knowledge">
            <h2>Ground answers in your business.</h2>
            <Code>{snippets.knowledge}</Code>
            <p>
              Website jobs follow internal links and sitemap indexes, respect
              robots permissions and crawl delays, normalize URLs and preserve
              source revisions. Structured product offers, variants and
              specifications become searchable evidence. TXT, PDF and DOCX
              uploads are also supported. Published knowledge snapshots stay
              active while a recrawl builds; an indexing failure preserves the
              previous snapshot.
            </p>
            <p>
              Website assistants connect successful snapshots automatically and
              can refresh on a schedule. Existing calls and conversations retain
              their pinned knowledge; unpublished draft edits remain
              unpublished. Manually created knowledge can also be selected on an
              agent and published. Qdrant queries filter workspace and snapshot
              identity. Credentials for Qdrant, embeddings and Azure remain
              server-side.
            </p>
            <p>
              Static extraction and guarded JavaScript rendering are available.
              Blocked pages, third-party-dependent applications and image-only
              PDFs may remain incomplete. Check page limits, exclusions and
              crawl notices; discovered content does not guarantee complete
              website coverage.
            </p>
          </section>
          <section id="voice">
            <h2>Connect the conversation.</h2>
            <Code>{snippets.browser}</Code>
            <p>
              Listen for <code>server.ready</code> before audio input. Incoming
              frames use a 32-byte NTV1 header followed by mono PCM16 at 16 kHz.
              Server output uses the same header and mono PCM16 at 24 kHz. Input
              frames must be at most 200 ms. The bundled{" "}
              <code>/pcm-capture.js</code> worklet handles browser capture and
              resampling.
            </p>
            <p>
              <code>server.clear</code> advances the playback epoch. Stop old
              scheduled audio and discard frames from earlier epochs. Text
              events include turn state, partial/final transcripts, errors and
              session end. Send <code>client.stop</code> to end a session.
              Permanent API/provider keys never belong in browser code.
            </p>
            <p>
              Browser and telephone voice use Sarvam: Saaras v4 recognition,
              Sarvam-105B Conversations with tools, and Bulbul v4 Flash speech.
              Configure SARVAM_API_KEY on the server. Text chat keeps its
              selected GPT model. Opt-in recordings use separate
              caller/assistant channels, announce recording in the greeting, and
              expire according to the published retention setting.
            </p>
          </section>
          <section id="phone">
            <h2>Twilio and Plivo.</h2>
            <Code>{snippets.webhook}</Code>
            <p>
              Register an account-owned number, verify its capabilities, attach
              a published agent, and configure the provider’s signed POST
              callbacks. Set an exact public HTTPS media origin with WebSocket
              support.
            </p>
            <p>
              Twilio uses bidirectional Connect/Stream with mu-law 8 kHz media,
              stream IDs, signed forms and clear events. Plivo uses its own
              signed callbacks and negotiated Stream protocol. These are
              distinct adapters; a generic webhook does not make an arbitrary
              carrier media-compatible.
            </p>
            <p>
              Outbound admission requires a verified number, a controlled
              destination allowlist, live credentials and a budget reservation.
              Callback retries settle the canonical call once. Live tariffs
              remain unpriced testing until a production tariff and provider
              reconciliation are configured.
            </p>
          </section>
          <section id="events">
            <h2>Tell your systems what happened.</h2>
            <Code>{snippets.events}</Code>
            <p>
              Event deliveries are recorded transactionally, signed and retried
              with backoff. Inspect failures under Developers and replay
              intentionally. Read X-Studio-Timestamp, X-Studio-Signature and
              X-Studio-Event. The signature is v1= followed by the hex
              HMAC-SHA256 of timestamp + a period + the exact raw request body,
              using your signing secret. Compare in constant time, reject
              timestamps older than five minutes, and deduplicate by
              X-Studio-Event. Parse JSON after verification.
            </p>
            <p>
              Tool endpoints execute actions during a conversation. Event
              webhooks report persisted events. Carrier webhooks admit and
              update phone calls. Keep these three contracts distinct.
            </p>
          </section>
          <section id="errors">
            <h2>Design around actual outcomes.</h2>
            <table>
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Meaning</th>
                </tr>
              </thead>
              <tbody>
                {[
                  [
                    "401 / 403",
                    "Missing credentials, invalid signature, wrong origin or insufficient scope.",
                  ],
                  [
                    "404 / 410",
                    "Resource unavailable in this workspace, or an expired capability.",
                  ],
                  [
                    "409",
                    "Conflicting idempotency key, unavailable state, budget or booking conflict.",
                  ],
                  [
                    "422",
                    "Invalid arguments, incompatible model settings or unsupported endpoint configuration.",
                  ],
                  ["429", "Rate limit reached. Back off before retrying."],
                  [
                    "502 / unknown",
                    "The provider rejected the request or its outcome needs reconciliation.",
                  ],
                ].map(([code, text]) => (
                  <tr key={code}>
                    <td>{code}</td>
                    <td>{text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p>
              Do not retry side effects with a new identity after an unknown
              network outcome. A queued action, generated promise or nonempty
              configuration flag is not proof of delivery.
            </p>
          </section>
          <footer>
            Phirmy developer guide · API v0.1{" "}
            <Link href="/app/developers">
              Manage keys
              <ArrowUpRight size={13} />
            </Link>
          </footer>
        </article>
      </div>
    </main>
  );
}
