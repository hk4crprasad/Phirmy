import type { Row } from "./api";
import { TranscriptStream } from "./transcript-stream";
import { checkMicrophone, microphoneError } from "./microphone";

type Events = {
  state: (state: string) => void;
  transcript: (role: string, text: string, final: boolean) => void;
  error: (message: string) => void;
  website?: (data: Row) => void;
};

/** Own every audio resource so ending/unmounting cannot leave the mic running. */
export class VoiceConnection {
  private socket: WebSocket | null = null;
  private audio: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private worklet: AudioWorkletNode | null = null;
  private sources = new Set<AudioBufferSourceNode>();
  private epoch = 0;
  private sequence = 0;
  private nextPlay = 0;
  private started = 0;
  private callId = "";
  private active = false;
  private stopped = false;
  private starting = false;
  private transcripts = new TranscriptStream();
  constructor(
    private publicId: string,
    private token: string,
    private events: Events,
    private pageUrl?: string,
  ) {}
  private async request(path: string, body: Row = {}) {
    const response = await fetch("/backend/v1/public" + path, {
      method: "POST",
      credentials: "omit",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + this.token,
      },
      body: JSON.stringify(body),
      keepalive: path.endsWith("/stop"),
    });
    const data = await response.json();
    if (!response.ok)
      throw Error(
        typeof data.detail === "string"
          ? data.detail
          : "The conversation could not start. Please try again.",
      );
    return data;
  }
  async start() {
    if (this.starting || this.stopped) return;
    this.starting = true;
    this.events.state("permission");
    try {
      checkMicrophone();
      this.audio = new AudioContext();
      await this.audio.resume();
      if (this.stopped) return;
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      if (this.stopped) {
        await this.release();
        return;
      }
      this.events.state("connecting");
      await this.audio.audioWorklet.addModule("/pcm-capture.js");
      if (this.stopped) return;
      const session = await this.request("/voice/sessions", {
        installation_public_id: this.publicId,
        page_url: this.pageUrl,
      });
      this.callId = session.call_id;
      if (this.stopped) {
        await this.stop();
        return;
      }
      const url = new URL(session.media_url);
      if (["localhost", "127.0.0.1"].includes(url.hostname))
        url.hostname = window.location.hostname;
      this.socket = new WebSocket(url);
      this.socket.binaryType = "arraybuffer";
      const socket = this.socket;
      const timeout = setTimeout(() => {
        if (!this.active) {
          this.events.error(
            "The voice connection timed out. Please try again.",
          );
          this.stop();
        }
      }, 12000);
      socket.onopen = () =>
        socket.send(
          JSON.stringify({
            type: "client.start",
            session_token: session.session_token,
            transcript_mode: "delta-v1",
          }),
        );
      socket.onmessage = (event) => {
        if (event.data instanceof ArrayBuffer) {
          this.play(event.data);
          return;
        }
        const message = JSON.parse(event.data);
        if (message.type === "server.ready") {
          clearTimeout(timeout);
          this.active = true;
          this.started = performance.now();
          if (!this.audio || !this.stream) return;
          const input = this.audio.createMediaStreamSource(this.stream),
            node = new AudioWorkletNode(this.audio, "pcm-capture"),
            silent = this.audio.createGain();
          this.worklet = node;
          silent.gain.value = 0;
          node.port.onmessage = (e) => this.send(e.data);
          input.connect(node);
          node.connect(silent);
          silent.connect(this.audio.destination);
          this.events.state("listening");
        }
        if (message.type === "server.website") this.events.website?.(message);
        if (message.type === "server.turn_state")
          this.events.state(message.state);
        const transcript = this.transcripts.consume(message);
        if (transcript)
          this.events.transcript(transcript.role, transcript.text, transcript.final);
        if (message.type === "server.clear") {
          if (!this.transcripts.clear(message.epoch)) return;
          this.epoch = message.epoch;
          this.clearAudio();
        }
        if (message.type === "server.error") {
          if (message.code === "model_incomplete") {
            this.events.error(
              "That answer stopped early. Please ask a shorter follow-up.",
            );
            this.events.state("listening");
            return;
          }
          this.events.error(
            message.code === "generation_failed"
              ? "The agent couldn’t finish that reply. Please try again."
              : "The voice conversation could not continue.",
          );
          this.stop();
        }
        if (message.type === "server.ended") this.stop();
      };
      socket.onerror = () => {
        this.events.error(
          "The voice connection failed. You can still use text chat.",
        );
        this.stop();
      };
      socket.onclose = () => {
        clearTimeout(timeout);
        this.active = false;
        this.release();
        if (!this.stopped) this.stop();
        this.events.state("ended");
      };
    } catch (error) {
      if (!this.stopped) this.events.error(microphoneError(error));
      await this.stop();
    }
  }
  private send(pcm: ArrayBuffer) {
    const socket = this.socket;
    if (!this.active || !socket || socket.readyState !== WebSocket.OPEN) return;
    if (socket.bufferedAmount > 128000) {
      this.events.error(
        "The connection is too slow for live audio. Please try again.",
      );
      this.stop();
      return;
    }
    const buffer = new ArrayBuffer(32 + pcm.byteLength),
      view = new DataView(buffer);
    new Uint8Array(buffer, 0, 4).set([78, 84, 86, 49]);
    view.setUint8(4, 1);
    view.setUint8(5, 1);
    view.setUint8(6, 1);
    view.setUint32(8, 16000, true);
    view.setUint32(12, this.sequence++, true);
    view.setUint32(16, this.epoch, true);
    view.setUint32(20, pcm.byteLength, true);
    view.setBigUint64(
      24,
      BigInt(Math.round((performance.now() - this.started) * 1000)),
      true,
    );
    new Uint8Array(buffer, 32).set(new Uint8Array(pcm));
    socket.send(buffer);
  }
  private play(frame: ArrayBuffer) {
    if (frame.byteLength < 32 || !this.audio) return;
    const view = new DataView(frame),
      length = view.getUint32(20, true),
      epoch = view.getUint32(16, true),
      rate = view.getUint32(8, true);
    if (
      view.getUint32(0, true) !== 0x3156544e ||
      view.getUint8(5) !== 2 ||
      epoch < this.epoch ||
      length !== frame.byteLength - 32 ||
      length % 2 ||
      rate !== 24000
    )
      return;
    if (epoch > this.epoch) {
      this.epoch = epoch;
      this.clearAudio();
    }
    const pcm = new Int16Array(frame, 32),
      buffer = this.audio.createBuffer(1, pcm.length, rate),
      data = buffer.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) data[i] = pcm[i] / 32768;
    const source = this.audio.createBufferSource();
    source.buffer = buffer;
    source.connect(this.audio.destination);
    const at = Math.max(this.audio.currentTime + 0.025, this.nextPlay);
    if (at - this.audio.currentTime > 1.5) {
      this.events.error("Audio playback fell behind. Please reconnect.");
      this.stop();
      return;
    }
    source.start(at);
    this.nextPlay = at + buffer.duration;
    this.sources.add(source);
    source.onended = () => this.sources.delete(source);
  }
  private clearAudio() {
    for (const source of this.sources) {
      try {
        source.stop();
      } catch {}
    }
    this.sources.clear();
    this.nextPlay = 0;
  }
  private async release() {
    this.active = false;
    this.clearAudio();
    this.worklet?.disconnect();
    this.worklet = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    const audio = this.audio;
    this.audio = null;
    if (audio) await audio.close().catch(() => {});
  }
  async stop() {
    this.stopped = true;
    this.active = false;
    if (this.socket?.readyState === WebSocket.OPEN)
      this.socket.send(JSON.stringify({ type: "client.stop" }));
    this.socket?.close();
    this.socket = null;
    await this.release();
    if (this.callId) {
      const id = this.callId;
      this.callId = "";
      await this.request("/voice/sessions/" + id + "/stop").catch(() => {});
    }
    this.events.state("ended");
  }
}
