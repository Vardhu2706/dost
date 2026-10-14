const btn = document.getElementById("btn");
const statusEl = document.getElementById("status");
const timerEl = document.getElementById("timer");
const avatar = document.querySelector(".avatar");

let ws, micCtx, playCtx, stream, node, tick, startedAt;
let nextTime = 0;
let sources = [];
let outRate = 24000;

function setStatus(s) { statusEl.textContent = s; }

function playPcm16(buf) {
  const i16 = new Int16Array(buf, 0, buf.byteLength >> 1);
  const f32 = new Float32Array(i16.length);
  for (let i = 0; i < i16.length; i++) f32[i] = i16[i] / 32768;
  const ab = playCtx.createBuffer(1, f32.length, outRate);
  ab.copyToChannel(f32, 0);
  const src = playCtx.createBufferSource();
  src.buffer = ab;
  src.connect(playCtx.destination);
  const t = Math.max(playCtx.currentTime + 0.02, nextTime);
  src.start(t);
  nextTime = t + ab.duration;
  sources.push(src);
  src.onended = () => { sources = sources.filter((s) => s !== src); };
}

function clearPlayback() {
  sources.forEach((s) => { try { s.stop(); } catch (e) {} });
  sources = [];
  nextTime = 0;
}

async function start() {
  btn.disabled = true;
  setStatus("Calling…");
  stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
  });
  micCtx = new AudioContext();
  await micCtx.audioWorklet.addModule("/static/worklet.js");
  node = new AudioWorkletNode(micCtx, "pcm-worklet");
  micCtx.createMediaStreamSource(stream).connect(node);
  playCtx = new AudioContext();

  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/call${location.search}`);
  ws.binaryType = "arraybuffer";
  ws.onopen = () => {
    ws.send(JSON.stringify({ type: "start", number: document.getElementById("number").value.trim() }));
    node.port.onmessage = (e) => { if (ws.readyState === 1) ws.send(e.data); };
    startedAt = Date.now();
    tick = setInterval(() => {
      const s = Math.floor((Date.now() - startedAt) / 1000);
      timerEl.textContent = String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
    }, 500);
    setStatus("Connected");
    avatar.classList.add("live");
    btn.textContent = "Hang up";
    btn.className = "hangup";
    btn.disabled = false;
  };
  ws.onmessage = (e) => {
    if (typeof e.data === "string") {
      const m = JSON.parse(e.data);
      if (m.type === "hello") outRate = m.sample_rate;
      else if (m.type === "clear") clearPlayback();
    } else {
      playPcm16(e.data);
    }
  };
  ws.onclose = stop;
}

function stop() {
  clearInterval(tick);
  clearPlayback();
  try { if (ws && ws.readyState === 1) { ws.send("hangup"); ws.close(); } } catch (e) {}
  if (stream) stream.getTracks().forEach((t) => t.stop());
  if (micCtx) micCtx.close();
  if (playCtx) playCtx.close();
  stream = micCtx = playCtx = ws = null;
  avatar.classList.remove("live");
  btn.textContent = "Call";
  btn.className = "call";
  btn.disabled = false;
  setStatus("Call ended");
}

btn.onclick = () => {
  if (ws) stop();
  else start().catch((err) => { setStatus("Could not start: " + err.message); btn.disabled = false; });
};
