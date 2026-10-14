// Downsamples mic audio to 16 kHz PCM16 and posts 20 ms (320-sample) frames.
class PCMWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.pos = 0;
    this.out = new Int16Array(320);
    this.n = 0;
  }
  process(inputs) {
    const ch = inputs[0][0];
    if (!ch) return true;
    // Box-average each output sample's source window (cheap anti-alias).
    while (this.pos + this.ratio <= ch.length) {
      const a = Math.floor(this.pos), b = Math.max(a + 1, Math.floor(this.pos + this.ratio));
      let s = 0;
      for (let i = a; i < b; i++) s += ch[i];
      const v = Math.max(-1, Math.min(1, s / (b - a)));
      this.out[this.n++] = v < 0 ? v * 0x8000 : v * 0x7fff;
      if (this.n === 320) {
        this.port.postMessage(this.out.buffer.slice(0));
        this.n = 0;
      }
      this.pos += this.ratio;
    }
    this.pos -= ch.length;
    return true;
  }
}
registerProcessor("pcm-worklet", PCMWorklet);
