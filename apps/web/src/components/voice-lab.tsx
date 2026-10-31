"use client";
import { useState, useRef, useEffect } from "react";
import {
  Play,
  Square,
  Mic,
  Send,
  AudioLines,
  ArrowUpRight,
} from "lucide-react";
import { command, Row } from "@/lib/api";
import { Header, Panel, Badge, Empty, StudioContext } from "./ui";
import { TranscriptStream } from "@/lib/transcript-stream";
import { checkMicrophone, microphoneError } from "@/lib/microphone";

export default function VoiceLab({ ctx }: { ctx: StudioContext }) {
  const agents = (ctx.data.agents || []).filter((a) => a.published_version_id);
  const [agent, setAgent] = useState(""),
    [mode, setMode] = useState("simulation"),
    [state, setState] = useState("idle"),
    [turns, setTurns] = useState<Row[]>([]),
    [partial, setPartial] = useState<Row | null>(null),
    [input, setInput] = useState(""),
    [error, setError] = useState(""),
    [callId, setCallId] = useState(""),
    [seconds, setSeconds] = useState(0),
    [variables, setVariables] = useState<Row>({});
  const socket = useRef<WebSocket | null>(null),
    audio = useRef<AudioContext | null>(null),
    stream = useRef<MediaStream | null>(null),
    worklet = useRef<AudioWorkletNode | null>(null),
    sources = useRef<Set<AudioBufferSourceNode>>(new Set()),
    nextPlay = useRef(0),
    epoch = useRef(0),
    sequence = useRef(0),
    started = useRef(0),
    active = useRef(false);
  const transcripts = useRef(new TranscriptStream());
  useEffect(() => {
    if (!agent && agents[0]) {
      const parameter = new URLSearchParams(window.location.search).get(
        "agent",
      );
      setAgent(agents.find((a) => a.id === parameter)?.id || agents[0].id);
    }
  }, [agents, agent]);
  useEffect(() => {
    if (!active.current) return;
    const timer = setInterval(
      () =>
        setSeconds(Math.floor((performance.now() - started.current) / 1000)),
      1000,
    );
    return () => clearInterval(timer);
  }, [state]);
  useEffect(
    () => () => {
      socket.current?.close();
      clearAudio();
      stream.current?.getTracks().forEach((t) => t.stop());
      audio.current?.close();
    },
    [],
  );
  function clearAudio() {
    for (const source of sources.current) {
      try {
        source.stop();
      } catch {}
    }
    sources.current.clear();
    nextPlay.current = 0;
  }
  async function cleanup() {
    active.current = false;
    clearAudio();
    worklet.current?.disconnect();
    worklet.current = null;
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    if (audio.current) {
      await audio.current.close().catch(() => {});
      audio.current = null;
    }
  }
  function inputFrame(pcm: ArrayBuffer) {
    const ws = socket.current;
    if (!ws || ws.readyState !== WebSocket.OPEN || !active.current) return;
    if (ws.bufferedAmount > 128000) {
      setError(
        "Audio connection is too slow; stopping rather than accumulating delayed speech.",
      );
      ws.close();
      return;
    }
    const out = new ArrayBuffer(32 + pcm.byteLength),
      view = new DataView(out);
    new Uint8Array(out, 0, 4).set([78, 84, 86, 49]);
    view.setUint8(4, 1);
    view.setUint8(5, 1);
    view.setUint8(6, 1);
    view.setUint32(8, 16000, true);
    view.setUint32(12, sequence.current++, true);
    view.setUint32(16, epoch.current, true);
    view.setUint32(20, pcm.byteLength, true);
    view.setBigUint64(
      24,
      BigInt(Math.round((performance.now() - started.current) * 1000)),
      true,
    );
    new Uint8Array(out, 32).set(new Uint8Array(pcm));
    ws.send(out);
  }
  async function start() {
    setError("");
    setState("connecting");
    setTurns([]);
    setPartial(null);
    setSeconds(0);
    sequence.current = 0;
    epoch.current = 0;
    transcripts.current = new TranscriptStream();
    try {
      if (mode === "live") {
        checkMicrophone();
        // Unlock playback from the click, before awaiting microphone permission
        // (mobile browsers can expire transient activation during that prompt).
        audio.current = new AudioContext();
        await audio.current.resume();
        stream.current = await navigator.mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        });
        await audio.current.audioWorklet.addModule("/pcm-capture.js");
      }
      const session = await command(ctx.base + "/voice/sessions", {
        agent_id: agent,
        mode,
        variables,
      });
      setCallId(session.call_id);
      const url = new URL(session.media_url);
      if (["localhost", "127.0.0.1"].includes(url.hostname))
        url.hostname = window.location.hostname;
      const ws = new WebSocket(url);
      socket.current = ws;
      ws.binaryType = "arraybuffer";
      ws.onopen = () =>
        ws.send(
          JSON.stringify({
            type: "client.start",
            session_token: session.session_token,
            transcript_mode: "delta-v1",
          }),
        );
      ws.onmessage = (event) => {
        if (event.data instanceof ArrayBuffer) {
          const header = new DataView(event.data);
          if (event.data.byteLength < 32) return;
          const frameEpoch = header.getUint32(16, true);
          if (frameEpoch < epoch.current) return;
          const rate = header.getUint32(8, true),
            length = header.getUint32(20, true);
          if (
            header.getUint32(0, true) !== 0x3156544e ||
            header.getUint8(4) !== 1 ||
            header.getUint8(5) !== 2 ||
            header.getUint8(6) !== 1 ||
            rate !== 24000 ||
            length !== event.data.byteLength - 32 ||
            !length ||
            length % 2
          )
            return;
          const pcm = new Int16Array(event.data, 32),
            context = audio.current;
          if (!context) return;
          const buffer = context.createBuffer(1, pcm.length, rate),
            channel = buffer.getChannelData(0);
          for (let i = 0; i < pcm.length; i++) channel[i] = pcm[i] / 32768;
          const source = context.createBufferSource();
          source.buffer = buffer;
          source.connect(context.destination);
          const at = Math.max(context.currentTime + 0.025, nextPlay.current);
          if (at - context.currentTime > 1) {
            setError(
              "Audio playback couldn’t keep up. Start a new microphone test.",
            );
            ws.close();
            return;
          }
          source.start(at);
          nextPlay.current = at + buffer.duration;
          sources.current.add(source);
          source.onended = () => sources.current.delete(source);
          return;
        }
        const message = JSON.parse(event.data);
        if (message.type === "server.ready") {
          active.current = true;
          started.current = performance.now();
          setState("listening");
          if (mode === "live" && audio.current && stream.current) {
            const input = audio.current.createMediaStreamSource(stream.current);
            const node = new AudioWorkletNode(audio.current, "pcm-capture");
            worklet.current = node;
            node.port.onmessage = (e) => inputFrame(e.data);
            input.connect(node);
            const silent = audio.current.createGain();
            silent.gain.value = 0;
            node.connect(silent);
            silent.connect(audio.current.destination);
          }
        }
        if (message.type === "server.turn_state") setState(message.state);
        const transcript = transcripts.current.consume(message);
        if (transcript) {
          if (transcript.final) {
            setTurns((old) => [
              ...old,
              { role: transcript.role, text: transcript.text },
            ]);
            setPartial(null);
          } else setPartial({ role: transcript.role, text: transcript.text });
        }
        if (message.type === "server.clear") {
          if (!transcripts.current.clear(message.epoch)) return;
          epoch.current = message.epoch;
          clearAudio();
          setPartial(null);
        }
        if (message.type === "server.error") {
          setError(message.message);
          if (!active.current) {
            ws.close();
          }
        }
        if (message.type === "server.ended") {
          setState("ended");
          cleanup();
          ctx.refresh();
        }
      };
      ws.onerror = () =>
        setError(
          "The media connection failed. Confirm the media server is reachable.",
        );
      ws.onclose = () => {
        cleanup();
        setState("ended");
        ctx.refresh();
      };
    } catch (e) {
      setError(mode === "live" ? microphoneError(e) : (e as Error).message);
      setState("idle");
      await cleanup();
    }
  }
  function stop() {
    socket.current?.send(
      JSON.stringify({ type: "client.stop", reason: "user_stop" }),
    );
    setState("ending");
  }
  function send(event: React.FormEvent) {
    event.preventDefault();
    if (!input.trim() || socket.current?.readyState !== WebSocket.OPEN) return;
    socket.current.send(
      JSON.stringify({ type: "client.text", text: input.trim() }),
    );
    setInput("");
  }
  const running = !["idle", "ended"].includes(state);
  return (
    <>
      <Header
        eyebrow="LISTEN. TEST. MAKE IT BETTER."
        title="Find your agent’s voice."
        description="Test the published version, inspect the transcript and learn from the conversation."
      >
        <button className="btn" onClick={() => ctx.go("calls")}>
          Call history
          <ArrowUpRight size={13} />
        </button>
      </Header>
      {!agents.length ? (
        <Panel>
          <Empty
            title="Publish an agent first"
            text="A published configuration gives your test a stable voice and knowledge snapshot."
            action={
              <button className="btn primary" onClick={() => ctx.go("agents")}>
                Go to agents
              </button>
            }
          />
        </Panel>
      ) : (
        <div className="split">
          <Panel title="Voice lab" action={<Badge value={state} />}>
            <div className="panel-body">
              <div className="form-grid">
                <label>
                  Published agent
                  <select
                    disabled={running}
                    value={agent}
                    onChange={(e) => setAgent(e.target.value)}
                  >
                    {agents.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Test mode
                  <select
                    disabled={running}
                    value={mode}
                    onChange={(e) => setMode(e.target.value)}
                  >
                    <option value="simulation">
                      Text simulation · no provider audio
                    </option>
                    <option
                      value="live"
                      disabled={!ctx.capabilities.live_voice}
                    >
                      Live microphone ·{" "}
                      {ctx.capabilities.voice_provider === "sarvam"
                        ? "Sarvam"
                        : "Fish + Deepgram"}
                    </option>
                  </select>
                </label>
              </div>
              {(
                agents.find((a) => a.id === agent)?.draft_config?.variables ||
                []
              ).map((v: Row) => (
                <label style={{ marginTop: 14 }} key={v.name}>
                  {v.name}
                  {v.required ? " · required" : ""}
                  <input
                    disabled={running}
                    value={variables[v.name] ?? v.default ?? ""}
                    onChange={(e) =>
                      setVariables({ ...variables, [v.name]: e.target.value })
                    }
                  />
                </label>
              ))}
              <div className="voice-stage">
                <div className={"voice-orb " + (running ? "active" : "")} />
                <h2>{agents.find((a) => a.id === agent)?.name}</h2>
                <p>
                  {running
                    ? state === "thinking"
                      ? "Finding the right words…"
                      : state === "speaking"
                        ? "Your agent is responding."
                        : state === "connecting"
                          ? "Opening a secure session…"
                          : "Listening to the conversation."
                    : mode === "simulation"
                      ? "A text simulation exercises the real conversation and persistence path."
                      : "Use your microphone for a live provider conversation."}
                </p>
                <div
                  style={{
                    fontSize: 25,
                    fontFamily: "Manrope",
                    margin: "22px 0",
                  }}
                >
                  {Math.floor(seconds / 60)
                    .toString()
                    .padStart(2, "0")}
                  :{(seconds % 60).toString().padStart(2, "0")}
                </div>
                <div className="row" style={{ justifyContent: "center" }}>
                  {running ? (
                    <>
                      <button
                        className="btn"
                        onClick={() =>
                          socket.current?.send(
                            JSON.stringify({ type: "client.interrupt" }),
                          )
                        }
                      >
                        Interrupt
                      </button>
                      <button
                        className="btn primary"
                        onClick={stop}
                        disabled={state === "ending"}
                      >
                        <Square size={12} />
                        End session
                      </button>
                    </>
                  ) : (
                    <button className="btn primary" onClick={start}>
                      <Play size={13} />
                      {mode === "live"
                        ? "Start microphone test"
                        : "Start simulation"}
                    </button>
                  )}
                </div>
              </div>
              {error && (
                <div className="error" role="alert">
                  {error}
                </div>
              )}
              {!ctx.capabilities.live_voice && (
                <div className="notice">
                  {ctx.capabilities.voice_provider === "sarvam"
                    ? "Connect your Sarvam account to enable live audio."
                    : "Connect the voice providers to enable live audio."}{" "}
                  Simulation uses text and does not capture microphone audio.
                </div>
              )}
              {callId && (
                <div className="mono muted" style={{ marginTop: 15 }}>
                  Call {callId}
                </div>
              )}
            </div>
          </Panel>
          <div className="stack">
            <Panel
              title="Live transcript"
              note="Saved turns remain available after the session."
            >
              <div className="chat-log" style={{ height: 390 }}>
                {turns.map((turn, i) => (
                  <div
                    className={
                      "chat-bubble " + (turn.role === "user" ? "user" : "")
                    }
                    key={i}
                  >
                    {turn.text}
                  </div>
                ))}
                {partial && (
                  <div
                    className={
                      "chat-bubble " + (partial.role === "user" ? "user" : "")
                    }
                    style={{ opacity: 0.7 }}
                  >
                    {partial.text}
                  </div>
                )}
                {!turns.length && !partial && (
                  <Empty
                    title="The conversation begins here"
                    text="Start a session, then type a turn or speak in live mode."
                  />
                )}
              </div>
              <form className="chat-compose" onSubmit={send}>
                <input
                  aria-label="Voice lab text turn"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder="Type a test turn…"
                  disabled={!running || state === "connecting"}
                  required
                />
                <button
                  className="btn primary"
                  aria-label="Send test turn"
                  disabled={!running}
                >
                  <Send size={14} />
                </button>
              </form>
            </Panel>
            <div className="notice">
              The first voice session is a quality test, not a latency
              benchmark. A greeting without user turns is recorded as no
              engagement and never qualifies a lead.
            </div>
          </div>
        </div>
      )}
    </>
  );
}
