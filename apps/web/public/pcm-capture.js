/* Stateful low-pass resampling before decimation, delivered in 20 ms PCM16 frames. */
class PCMCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.phase = 0;
    this.output = [];
    this.ring = new Float32Array(63);
    this.index = 0;
    const cutoff = Math.min(0.45, 7200 / sampleRate),
      taps = 63;
    this.coefficients = Array.from({ length: taps }, (_, i) => {
      const x = i - (taps - 1) / 2;
      const sinc =
        x === 0
          ? 2 * cutoff
          : Math.sin(2 * Math.PI * cutoff * x) / (Math.PI * x);
      return sinc * (0.54 - 0.46 * Math.cos((2 * Math.PI * i) / (taps - 1)));
    });
    const sum = this.coefficients.reduce((a, b) => a + b, 0);
    this.coefficients = this.coefficients.map((x) => x / sum);
  }
  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel) return true;
    for (const sample of channel) {
      this.ring[this.index] = sample;
      this.index = (this.index + 1) % this.ring.length;
      this.phase += 16000;
      if (this.phase >= sampleRate) {
        this.phase -= sampleRate;
        let value = 0;
        for (let i = 0; i < this.ring.length; i++)
          value +=
            this.ring[(this.index + i) % this.ring.length] *
            this.coefficients[i];
        this.output.push(Math.round(Math.max(-1, Math.min(1, value)) * 32767));
        if (this.output.length === 320) {
          const pcm = new Int16Array(this.output);
          this.port.postMessage(pcm.buffer, [pcm.buffer]);
          this.output = [];
        }
      }
    }
    return true;
  }
}
registerProcessor("pcm-capture", PCMCapture);
