/** Exercise the shipped TypeScript connection with deterministic browser boundaries. */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../apps/web/src/lib/voice-connection.ts", import.meta.url), "utf8");
const helperSource = await readFile(new URL("../apps/web/src/lib/transcript-stream.ts", import.meta.url), "utf8");
const helperOutput = ts.transpileModule(helperSource, {
  compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
}).outputText;
const helperUrl = "data:text/javascript;base64," + Buffer.from(helperOutput).toString("base64");
const { TranscriptStream } = await import(helperUrl);
let { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
});
outputText = outputText.replace('"./transcript-stream"', JSON.stringify(helperUrl));
const micSource = await readFile(new URL("../apps/web/src/lib/microphone.ts", import.meta.url), "utf8");
const micOutput = ts.transpileModule(micSource, { compilerOptions: { module: ts.ModuleKind.ES2022 } }).outputText;
outputText = outputText.replace('"./microphone"', JSON.stringify("data:text/javascript;base64," + Buffer.from(micOutput).toString("base64")));
const { VoiceConnection } = await import("data:text/javascript;base64," + Buffer.from(outputText).toString("base64"));

const partial = new TranscriptStream();
const patch = (values = {}) => ({ type: "server.transcript.delta", speaker: "assistant", turn_id: "synthetic-turn", epoch: 0, ...values });
assert.equal(partial.consume(patch({ seq: 0, retain: 0, delta: "Hello 🌿" })).text, "Hello 🌿");
assert.equal(partial.consume(patch({ seq: 0, retain: 0, delta: "duplicate" })), null);
assert.equal(partial.consume(patch({ seq: 1, retain: 7, delta: "!" })).text, "Hello 🌿!");
assert.equal(partial.consume(patch({ seq: 2, retain: 6, delta: "world" })).text, "Hello world");
assert.equal(partial.consume(patch({ seq: 4, retain: 0, delta: "gap" })), null);
assert.equal(partial.consume(patch({ seq: 5, retain: 0, delta: "untrusted continuation" })), null);
const final = { type: "server.transcript", speaker: "assistant", turn_id: "synthetic-turn", epoch: 0, text: "Final authoritative transcript", final: true };
assert.equal(partial.consume(final).text, final.text);
assert.equal(partial.consume(final), null);
assert.equal(partial.clear(2), true);
assert.equal(partial.clear(1), false);
assert.equal(partial.consume(patch({ seq: 0, retain: 0, delta: "old epoch" })), null);
assert.equal(partial.consume(patch({ epoch: 2, seq: 0, retain: 1, delta: "bad retain" })), null);
const sockets = [], requests = [], errors = [], states = [], transcripts = [];
let tracksStopped = 0, audioClosed = 0;
const node = () => ({ connect() {}, disconnect() {}, gain: { value: 0 } });
class Audio {
  audioWorklet = { async addModule() {} };
  destination = {};
  async resume() {}
  async close() { audioClosed++; }
  createMediaStreamSource() { return node(); }
  createGain() { return node(); }
}
class Socket {
  static OPEN = 1;
  readyState = 1;
  sent = [];
  closed = false;
  constructor() { sockets.push(this); }
  send(data) { this.sent.push(JSON.parse(data)); }
  deliver(message) { this.onmessage({ data: JSON.stringify(message) }); }
  close() {
    if (this.closed) return;
    this.closed = true;
    this.readyState = 3;
    this.onclose?.();
  }
}
Object.defineProperty(globalThis, "navigator", { configurable: true, value: {
  mediaDevices: { async getUserMedia() { return { getTracks: () => [{ stop() { tracksStopped++; } }] }; } },
} });
globalThis.window = { location: { hostname: "localhost" } };
globalThis.document = {};
globalThis.AudioContext = Audio;
globalThis.AudioWorkletNode = class { port = {}; connect() {} disconnect() {} };
globalThis.WebSocket = Socket;
globalThis.fetch = async (path) => {
  requests.push(path);
  return { ok: true, async json() { return { call_id: "synthetic-call", session_token: "synthetic-token", media_url: "ws://localhost/media" }; } };
};
const connection = new VoiceConnection("synthetic-installation", "synthetic-capability", {
  state: (state) => states.push(state), error: (message) => errors.push(message),
  transcript: (...args) => transcripts.push(args),
});
try {
  await connection.start();
  const socket = sockets[0];
  socket.onopen();
  assert.equal(socket.sent[0].transcript_mode, "delta-v1");
  socket.deliver({ type: "server.ready" });
  socket.deliver({ type: "server.error", code: "model_incomplete", retryable: false });
  assert.equal(socket.closed, false, "An incomplete answer must allow a follow-up in the same call");
  assert.equal(requests.filter((path) => path.endsWith("/stop")).length, 0);
  assert.match(errors[0], /shorter follow-up/);
  assert.equal(states.at(-1), "listening");
  socket.deliver({ type: "server.transcript", speaker: "user", turn_id: "synthetic-user-turn", text: "Synthetic follow-up", final: true });
  assert.deepEqual(transcripts.at(-1), ["user", "Synthetic follow-up", true]);
  socket.deliver({ type: "server.error", code: "generation_failed", retryable: true });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(socket.closed, true, "Other fatal provider failures retain existing cleanup behavior");
  assert.equal(tracksStopped, 1);
  assert.equal(audioClosed, 1);
  assert.equal(requests.filter((path) => path.endsWith("/stop")).length, 1);
  console.log(JSON.stringify({ transcript_patches: "passed", unicode_revisions: "passed", sequence_and_epoch_fencing: "passed", incomplete_followup: "passed", fatal_cleanup: "passed", microphone_stopped: true, audio_closed: true }));
} finally {
  await connection.stop();
}

// Permission failures create no provider session, and a fresh connection can retry.
const makeConnection = () => new VoiceConnection("synthetic-installation", "synthetic-capability", {
  state: (state) => states.push(state), error: (message) => errors.push(message), transcript() {},
});
for (const [name, message] of [["NotAllowedError", /site settings/], ["NotFoundError", /No microphone/], ["NotReadableError", /other apps/]]) {
  const before = requests.length;
  navigator.mediaDevices.getUserMedia = async () => { throw new DOMException("synthetic", name); };
  await makeConnection().start();
  assert.match(errors.at(-1), message);
  assert.equal(requests.length, before);
  assert.equal(states.at(-1), "ended");
}
let permissionResolve, prompts = 0, lateStopped = 0;
navigator.mediaDevices.getUserMedia = () => {
  prompts++;
  return new Promise((resolve) => { permissionResolve = resolve; });
};
const pending = makeConnection();
const pendingStart = pending.start();
await new Promise((resolve) => setImmediate(resolve));
await pending.start();
assert.equal(prompts, 1, "Repeated starts must not overlap permission requests");
const before = requests.length;
await pending.stop();
permissionResolve({ getTracks: () => [{ stop() { lateStopped++; } }] });
await pendingStart;
assert.equal(lateStopped, 1, "Closing during permission must stop the late microphone stream");
assert.equal(requests.length, before, "A canceled permission flow must not create a provider session");
let moduleResolve;
const BaseAudio = globalThis.AudioContext;
globalThis.AudioContext = class extends BaseAudio {
  constructor() { super(); this.audioWorklet = { addModule: () => new Promise((resolve) => { moduleResolve = resolve; }) }; }
};
navigator.mediaDevices.getUserMedia = async () => ({ getTracks: () => [{ stop() {} }] });
const loading = makeConnection();
const loadingStart = loading.start();
await new Promise((resolve) => setImmediate(resolve));
await loading.stop();
moduleResolve();
await loadingStart;
assert.equal(requests.length, before, "Closing during worklet loading must not create a provider session");
globalThis.AudioContext = BaseAudio;
document.featurePolicy = { allowsFeature: () => false };
await makeConnection().start();
assert.match(errors.at(-1), /website blocks microphone/);
assert.equal(requests.length, before);
delete document.featurePolicy;
console.log(JSON.stringify({ permission_denial: "passed", missing_microphone: "passed", device_busy: "passed", duplicate_start: "passed", close_during_permission: "passed", close_during_worklet: "passed", blocked_embedding_policy: "passed" }));
