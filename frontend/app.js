// frontend/app.js
const API_BASE = location.origin.replace(/\/$/, "");
const TOKEN = "dev-secret-change-me"; // ustaw to samo co APP_SECRET po stronie backendu

const store = {
  data: [],
  maxPoints: 12 * 60 * 60,
  ws: null,
  deviceId: "demo-1",
};

const el = {
  rr: document.getElementById("rr"),
  hr: document.getElementById("hr"),
  skin: document.getElementById("skin"),
  h2s: document.getElementById("h2s"),
  noise: document.getElementById("noise"),
  presence: document.getElementById("presence"),
  events: document.getElementById("events"),
  deviceId: document.getElementById("deviceId"),
  connectBtn: document.getElementById("connectBtn"),
  chartRR: document.getElementById("chart-rr"),
  chartHR: document.getElementById("chart-hr"),
  chartTemp: document.getElementById("chart-temp"),
  chartH2S: document.getElementById("chart-h2s"),
};

el.connectBtn.addEventListener("click", connect);

function connect() {
  store.deviceId = el.deviceId.value.trim();
  if (!store.deviceId) return;
  if (store.ws) store.ws.close(1000);

  const url = new URL(`/ws/app/${encodeURIComponent(store.deviceId)}`, API_BASE);
  url.searchParams.set("token", TOKEN);
  const ws = new WebSocket(url);
  store.ws = ws;

  ws.onopen = () => {
    console.log("WS open");
    store.ping = setInterval(() => ws.readyState === 1 && ws.send("ping"), 20000);
  };

  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (!msg.ts) return;
      const point = { ...msg, ts: new Date(msg.ts) };
      store.data.push(point);
      if (store.data.length > store.maxPoints) store.data.shift();
      renderKPIs(point);
      renderCharts();
      if (msg.event) pushEvent(msg);
    } catch (e) {}
  };

  ws.onclose = () => {
    console.log("WS closed");
    clearInterval(store.ping);
  };
}

function fmt(n, digits = 1) {
  return typeof n === "number" && !Number.isNaN(n) ? n.toFixed(digits) : "–";
}

function renderKPIs(p) {
  el.rr.textContent = fmt(p.respiration_rate, 0);
  el.hr.textContent = fmt(p.heart_rate, 0);
  el.skin.textContent = fmt(p.skin_temp_c, 1);
  el.h2s.textContent = fmt(p.h2s_level, 3);
  el.noise.textContent = fmt(p.noise_db, 0);
  el.presence.textContent = p.presence === true ? "Tak" : p.presence === false ? "Nie" : "–";
}

import * as Plot from "https://cdn.jsdelivr.net/npm/@observablehq/plot@0.6/+esm";

let plots = { rr: null, hr: null, temp: null, h2s: null };

function renderCharts() {
  const data = store.data;
  if (!data.length) return;

  const rr = data.filter(d => d.respiration_rate != null);
  const hr = data.filter(d => d.heart_rate != null);
  const temp = data.filter(d => d.skin_temp_c != null);
  const h2s = data.filter(d => d.h2s_level != null);
  const events = data.filter(d => d.event);

  const width = Math.min(900, document.body.clientWidth - 32);

  if (plots.rr) plots.rr.remove();
  plots.rr = Plot.plot({
    width,
    height: 180,
    x: { label: "czas" },
    y: { label: "oddechy/min" },
    marks: [
      Plot.line(rr, { x: "ts", y: "respiration_rate" }),
      Plot.dot(events, { x: "ts", y: () => (rr.length ? rr[rr.length-1].respiration_rate : 0), r: 4, title: d => d.event })
    ]
  });
  el.chartRR.replaceChildren(plots.rr);

  if (plots.hr) plots.hr.remove();
  plots.hr = Plot.plot({
    width, height: 180,
    x: { label: "czas" }, y: { label: "bpm" },
    marks: [ Plot.line(hr, { x: "ts", y: "heart_rate" }) ]
  });
  el.chartHR.replaceChildren(plots.hr);

  if (plots.temp) plots.temp.remove();
  plots.temp = Plot.plot({
    width, height: 180,
    x: { label: "czas" }, y: { label: "°C" },
    marks: [ Plot.line(temp, { x: "ts", y: "skin_temp_c" }) ]
  });
  el.chartTemp.replaceChildren(plots.temp);

  if (plots.h2s) plots.h2s.remove();
  plots.h2s = Plot.plot({
    width, height: 180,
    x: { label: "czas" }, y: { label: "H₂S (arb.)" },
    marks: [ Plot.line(h2s, { x: "ts", y: "h2s_level" }) ]
  });
  el.chartH2S.replaceChildren(plots.h2s);
}

function pushEvent(msg) {
  const li = document.createElement("li");
  li.textContent = `${new Date(msg.ts).toLocaleTimeString()} — ${msg.event}`;
  el.events.prepend(li);
}

connect();
