const WEATHER = ["Clear", "Cloudy", "Rainy", "Stormy", "Snowy"];
const STRATEGY_NAMES = {
  fixed: "Fixed fares", rule: "Rule-based surge", ml: "Demand model",
  bandit: "Learning bandit", oracle: "Oracle (upper bound)",
};
const PRESETS = [
  { label: "Kashmir snowfall", region: "KSH", values: { temperature: -2, precipitation: 6, weather_condition: "Snowy", road_closed: false } },
  { label: "NH-44 closed", region: "HIL", values: { temperature: 2, precipitation: 9, weather_condition: "Stormy", road_closed: true } },
  { label: "Peak Amarnath Yatra", region: "KSH", values: { temperature: 24, precipitation: 0, weather_condition: "Clear", road_closed: false, pilgrim_override: 1 } },
  { label: "Vaishno Devi rush", region: "JMU", values: { temperature: 26, precipitation: 0, weather_condition: "Clear", road_closed: false, pilgrim_override: 1 } },
  { label: "Evening rush everywhere", region: "ALL", values: { hour_override: 18 } },
];
const PREVIEW_TRIPS = [
  { label: "Jammu, 4 km", pickup: { lat: 32.7100, lon: 74.8600 }, dropoff: { lat: 32.6891, lon: 74.8374 } },
  { label: "Srinagar, 10 km", pickup: { lat: 34.0700, lon: 74.8100 }, dropoff: { lat: 34.1253, lon: 74.8806 } },
  { label: "Jammu to Srinagar", pickup: { lat: 32.7266, lon: 74.8570 }, dropoff: { lat: 34.0700, lon: 74.8100 } },
];
const lastPreview = {};
let conditions = null;

// Shows the effect of a change at once, as the cab fare on three sample trips.
async function refreshPreview() {
  const cards = await Promise.all(PREVIEW_TRIPS.map(async trip => {
    try {
      const q = await api("/quote", { method: "POST", body: { pickup: trip.pickup, dropoff: trip.dropoff } });
      const cab = q.options.find(o => o.vehicle === "cab");
      const before = lastPreview[trip.label];
      lastPreview[trip.label] = cab.fare;
      const change = before && before !== cab.fare
        ? el("span", { class: "muted" }, ` ${cab.fare > before ? "▲" : "▼"} from ${rupees(before)}`) : null;
      return el("div", { class: "card" }, el("div", { class: "muted" }, `Cab · ${trip.label}`),
        el("div", {}, el("span", { class: "stat" }, rupees(cab.fare)), change),
        el("div", { class: "muted" }, `×${cab.multiplier}${cab.fair_capped ? " · at fair-price limit" : ""}`));
    } catch (e) {
      lastPreview[trip.label] = null;
      return el("div", { class: "card" }, el("div", { class: "muted" }, `Cab · ${trip.label}`), el("div", { class: "error" }, e.message));
    }
  }));
  fill($("preview"), cards);
}

async function renderRivalRates() {
  fill($("rival-rates"), Object.entries(conditions.rival_rates).map(([rival, data]) =>
    el("div", { class: "card stack" }, el("h3", {}, `${data.label} (assumed)`),
      Object.entries(data.cards).map(([vehicle, card]) => {
        const base = el("input", { type: "number", min: 0, max: 1000, value: card.base, "aria-label": `${data.label} ${vehicle} base fare` });
        const perKm = el("input", { type: "number", min: 0, max: 200, step: 0.5, value: card.per_km, "aria-label": `${data.label} ${vehicle} rate per km` });
        return el("form", { class: "row rate-row", onsubmit: async event => {
          event.preventDefault();
          try {
            await api(`/admin/rival-rates/${rival}/${vehicle}`, { method: "PUT", body: { base: +base.value, per_km: +perKm.value } });
            toast(`${data.label} ${vehicle} rate saved`);
            await refreshPreview();
          } catch (e) { toast(e.message); }
        } }, el("span", { class: "rate-name" }, vehicle), el("span", { class: "muted" }, "₹ base"), base, el("span", { class: "muted" }, "₹/km"), perKm,
          el("button", { type: "submit", class: "secondary" }, "Save"));
      }))));
}

async function refreshStats() {
  const o = await api("/admin/overview");
  const tile = (label, value) => el("div", { class: "card" }, el("div", { class: "muted" }, label), el("div", { class: "stat" }, value));
  $("stats").replaceChildren(
    tile("Completed rides", o.completed.toLocaleString("en-IN")),
    tile("Fares, completed", rupees(o.fares)),
    tile("Cancelled", o.cancelled.toLocaleString("en-IN")),
    tile("Riders", (o.users.rider || 0).toLocaleString("en-IN")),
    tile("Drivers online", o.drivers_online.toLocaleString("en-IN")),
    tile("Recent fares at limit", `${o.rides_capped} of ${o.recent.length}`));

  $("recent").replaceChildren(
    el("thead", {}, el("tr", {}, ["Trip", "Rider", "Driver", "Vehicle", "Status"].map(h => el("th", {}, h)),
      el("th", { class: "num" }, "Fare"), el("th", { class: "num" }, "Multiplier"))),
    el("tbody", {}, o.recent.map(r => el("tr", {},
      el("td", {}, `${r.pickup.name} → ${r.dropoff.name}`),
      el("td", {}, r.rider ? r.rider.name : ""),
      el("td", {}, r.driver ? r.driver.name + (r.driver.simulated ? " (demo)" : "") : "—"),
      el("td", {}, r.quote.label),
      el("td", {}, r.status.replace("_", " ")),
      el("td", { class: "num" }, rupees(r.fare)),
      el("td", { class: "num" }, "×" + r.quote.multiplier.toFixed(2))))));
}

function regionCard(code, data) {
  const id = name => `${code}-${name}`;
  const temp = el("input", { id: id("temp"), type: "number", min: -30, max: 55, step: 0.5, value: data.temperature });
  const precip = el("input", { id: id("precip"), type: "number", min: 0, max: 100, step: 0.5, value: data.precipitation });
  const weather = el("select", { id: id("weather") }, WEATHER.map(w => el("option", { value: w, selected: w === data.weather_condition }, w)));
  const closed = el("input", { id: id("closed"), type: "checkbox", checked: data.road_closed, style: "width:auto" });
  const hour = el("input", { id: id("hour"), type: "number", min: 0, max: 23, placeholder: "Live clock", value: data.hour_override ?? "" });
  const pilgrim = el("input", { id: id("pilgrim"), type: "number", min: 0, max: 1, step: 0.1, placeholder: "Calendar", value: data.pilgrim_override ?? "" });
  const note = el("div", { class: "muted", role: "status" });
  return el("form", { class: "card stack", onsubmit: async event => {
    event.preventDefault();
    try {
      await api(`/admin/conditions/${code}`, { method: "PUT", body: {
        temperature: +temp.value, precipitation: +precip.value, weather_condition: weather.value,
        road_closed: closed.checked,
        hour_override: hour.value === "" ? null : +hour.value,
        pilgrim_override: pilgrim.value === "" ? null : +pilgrim.value,
      } });
      note.textContent = "Saved. New quotes use these conditions.";
      await refreshPreview();
    } catch (e) { note.textContent = e.message; }
  } },
    el("h3", {}, data.name),
    el("div", { class: "row" },
      el("div", {}, el("label", { htmlFor: temp.id }, "Temp °C"), temp),
      el("div", {}, el("label", { htmlFor: precip.id }, "Precip mm/h"), precip)),
    el("div", {}, el("label", { htmlFor: weather.id }, "Weather"), weather),
    el("div", { class: "row" },
      el("div", {}, el("label", { htmlFor: hour.id }, "Hour override"), hour),
      el("div", {}, el("label", { htmlFor: pilgrim.id }, "Yatra 0-1"), pilgrim)),
    el("label", { style: "display:flex;gap:8px;align-items:center" }, closed, "Roads closed"),
    el("button", { type: "submit" }, "Save"), note);
}

async function saveRegion(code, values) {
  const { name, ...current } = conditions.regions[code];
  await api(`/admin/conditions/${code}`, { method: "PUT", body: { ...current, ...values } });
}

async function refreshConditions() {
  conditions = await api("/admin/conditions");
  $("regions").replaceChildren(...Object.entries(conditions.regions).map(([code, data]) => regionCard(code, data)));

  const normal = el("input", { id: "cap-normal", type: "number", min: 1, max: 1.4, step: 0.05, value: conditions.caps.normal });
  const hardship = el("input", { id: "cap-hardship", type: "number", min: 1, max: 1.4, step: 0.05, value: conditions.caps.hardship });
  $("caps").replaceChildren(
    el("div", {}, el("label", { htmlFor: normal.id }, "Normal limit ×"), normal),
    el("div", {}, el("label", { htmlFor: hardship.id }, "Hardship limit ×"), hardship),
    el("button", { type: "submit" }, "Save"));
  $("caps").onsubmit = async event => {
    event.preventDefault();
    try {
      await api("/admin/caps", { method: "PUT", body: { normal: +normal.value, hardship: +hardship.value } });
      $("caps-note").textContent = "Saved.";
      await refreshPreview();
    } catch (e) { $("caps-note").textContent = e.message; }
  };
}

function renderPresets() {
  $("presets").replaceChildren(...PRESETS.map(p => el("button", {
    type: "button", class: "secondary", style: "flex:1 1 170px",
    onclick: async () => {
      const codes = p.region === "ALL" ? Object.keys(conditions.regions) : [p.region];
      await Promise.all(codes.map(code => saveRegion(code, p.values)));
      await refreshConditions();
      await refreshPreview();
      toast(`${p.label} applied`);
    },
  }, p.label)),
  el("button", { type: "button", class: "secondary", style: "flex:1 1 170px", onclick: async () => {
    await Promise.all(Object.keys(conditions.regions).map(code => saveRegion(code, {
      precipitation: 0, weather_condition: "Clear", road_closed: false, hour_override: null, pilgrim_override: null,
    })));
    await refreshConditions();
    await refreshPreview();
    toast("Conditions cleared");
  } }, "Clear all"));
}

async function renderSimulation() {
  let sim;
  try { sim = await api("/admin/simulation"); }
  catch (e) { $("sim-note").textContent = e.message; return; }

  $("sim-note").textContent = `${sim.market_hours.toLocaleString("en-IN")} market-hours, ${sim.seeds} seeded runs, ${sim.period[0].slice(0, 10)} to ${sim.period[1].slice(0, 10)}. ${sim.assumptions}`;
  const rows = Object.entries(sim.strategies).map(([key, r]) => ({ key, name: STRATEGY_NAMES[key], ...r }));
  const columns = [
    ["Strategy", r => r.name],
    ["Profit vs fixed", r => `${r.profit_vs_fixed_pct >= 0 ? "+" : ""}${r.profit_vs_fixed_pct.toFixed(1)}% ± ${r.profit_vs_fixed_pct_std.toFixed(1)}`],
    ["Below oracle", r => `${r.regret_vs_oracle_pct.toFixed(1)}%`],
    ["Rides", r => Math.round(r.rides).toLocaleString("en-IN")],
    ["Avg wait (min)", r => r.wait_min.toFixed(1)],
    ["Avg multiplier", r => "×" + r.avg_multiplier.toFixed(2)],
    ["Hours at limit", r => `${r.pct_hours_at_cap.toFixed(0)}%`],
  ];
  $("sim-table").replaceChildren(
    el("thead", {}, el("tr", {}, columns.map(([h], i) => el("th", { class: i ? "num" : "" }, h)))),
    el("tbody", {}, rows.map(r => el("tr", {}, columns.map(([, value], i) => el("td", { class: i ? "num" : "" }, value(r)))))));

  new Chart($("sim-chart"), {
    type: "bar",
    data: {
      labels: rows.map(r => r.name),
      datasets: [{ data: rows.map(r => +r.profit_vs_fixed_pct.toFixed(1)), backgroundColor: "#2dd4bf", borderRadius: 4, maxBarThickness: 18 }],
    },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: false, animation: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => `${c.parsed.x >= 0 ? "+" : ""}${c.parsed.x}% vs. fixed fares` } } },
      scales: {
        x: { title: { display: true, text: "Profit change (%)", color: "#a3a3a3" }, ticks: { color: "#a3a3a3" }, grid: { color: "#262626" } },
        y: { ticks: { color: "#f5f5f5" }, grid: { display: false } },
      },
    },
  });

  $("sim-export").onclick = () => {
    const csv = [columns.map(([h]) => h).join(","),
      ...rows.map(r => columns.map(([, value]) => `"${value(r)}"`).join(","))].join("\n");
    const link = el("a", { href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })), download: "strategy_comparison.csv" });
    link.click();
    URL.revokeObjectURL(link.href);
  };
}

async function start() {
  hideAuth();
  $("app").classList.remove("hidden");
  showLogout();
  fill($("admin-banner"), photoBanner(photoById("raghunath-temple"), "Operations across Jammu & Kashmir"));
  await refreshConditions();
  renderPresets();
  await renderRivalRates();
  await refreshPreview();
  await refreshStats();
  await renderSimulation();
  connectLive(event => { if (event.type === "ride") refreshStats().catch(() => {}); });
}

(async function init() {
  useAccount("admin");
  setupShell("Raahi Admin");
  await loadPhotos();
  if (token()) {
    const me = await api("/me").catch(() => null);
    if (me && me.role === "admin") return start();
  }
  showAuthPhoto("krimchi-temples");
  renderAuth($("auth-form"), "admin", start);
})();
