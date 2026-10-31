/** Reconstruct bounded delta-v1 streams, including revised STT hypotheses. */
export type TranscriptFrame = {
  role: string;
  text: string;
  final: boolean;
};
type Partial = { text: string; next: number };

export class TranscriptStream {
  private epoch = 0;
  private partial = new Map<string, Partial>();
  private invalid = new Set<string>();
  private completed = new Set<string>();

  clear(epoch: number) {
    if (!Number.isSafeInteger(epoch) || epoch < this.epoch) return false;
    this.epoch = epoch;
    this.partial.clear();
    this.invalid.clear();
    this.completed.clear();
    return true;
  }

  consume(message: Record<string, unknown>): TranscriptFrame | null {
    const { type, speaker, turn_id: id } = message;
    if (
      (type !== "server.transcript" && type !== "server.transcript.delta") ||
      (speaker !== "user" && speaker !== "assistant") ||
      typeof id !== "string" || !id || id.length > 128
    ) return null;
    const epoch = typeof message.epoch === "number" ? message.epoch : this.epoch;
    if (!Number.isSafeInteger(epoch) || epoch < this.epoch) return null;
    if (epoch > this.epoch) this.clear(epoch);
    const key = speaker + ":" + id;
    if (this.completed.has(key)) return null;
    if (type === "server.transcript") {
      if (typeof message.text !== "string" || message.text.length > 128000) return null;
      if (message.final === true) {
        this.partial.delete(key);
        this.invalid.delete(key);
        this.completed.add(key);
        if (this.completed.size > 64) this.completed.delete(this.completed.values().next().value!);
      }
      return { role: speaker, text: message.text, final: message.final === true };
    }
    if (this.invalid.has(key)) return null;
    const previous = this.partial.get(key) || { text: "", next: 0 };
    if (Number.isSafeInteger(message.seq) && Number(message.seq) < previous.next) return null;
    const chars = Array.from(previous.text);
    if (
      !Number.isSafeInteger(message.seq) || message.seq !== previous.next ||
      !Number.isSafeInteger(message.retain) || Number(message.retain) < 0 ||
      Number(message.retain) > chars.length || typeof message.delta !== "string" ||
      message.delta.length > 128000
    ) {
      this.partial.delete(key);
      this.invalid.add(key);
      if (this.invalid.size > 64) this.invalid.delete(this.invalid.values().next().value!);
      return null;
    }
    const text = chars.slice(0, Number(message.retain)).join("") + message.delta;
    if (text.length > 128000) return null;
    this.partial.set(key, { text, next: previous.next + 1 });
    if (this.partial.size > 4) this.partial.delete(this.partial.keys().next().value!);
    return { role: speaker, text, final: false };
  }
}
