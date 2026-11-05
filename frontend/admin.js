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
      datasets: [{ data: rows.map(r => +r.profit_vs_fixed_pct.toFixed(1)), backgroundColor: "#111111", borderRadius: 4, maxBarThickness: 18 }],
    },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: false, animation: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => `${c.parsed.x >= 0 ? "+" : ""}${c.parsed.x}% vs. fixed fares` } } },
      scales: {
        x: { title: { display: true, text: "Profit change (%)", color: "#6b6b6b" }, ticks: { color: "#6b6b6b" }, grid: { color: "#eeeeee" } },
        y: { ticks: { color: "#111111" }, grid: { display: false } },
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

// ------------------------------------------------------------------ business model
const VEHICLE_NAMES = { bike: "Bike", erickshaw: "E-rickshaw", auto: "Auto", cab: "Cab", shared: "Shared cab (per seat)" };
const money = n => (n < 0 ? "−" : "") + "₹" + Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const signed = n => el("span", { class: n < 0 ? "loss" : "profit" }, money(n));
let business = null, sampleVehicle = "cab";

function flowRow(label, value, kind = "") {
  return el("div", { class: "flow-row " + kind }, el("span", {}, label), typeof value === "number" ? money(value) : value);
}

// One ride, top to bottom: what the rider pays, and who ends up with each part of it.
function renderFlow() {
  const e = business.sample_10km[sampleVehicle];
  fill($("biz-sample-pick"), Object.keys(business.sample_10km).map(v => el("button", {
    type: "button", class: "chip", "aria-pressed": String(v === sampleVehicle),
    onclick: () => { sampleVehicle = v; renderFlow(); },
  }, VEHICLE_NAMES[v] || v)));
  fill($("biz-flow"),
    el("div", { class: "muted" }, `A 10 km ${(VEHICLE_NAMES[sampleVehicle] || sampleVehicle).toLowerCase()} trip at the normal fare`),
    flowRow("Rider pays", e.fare, "total"),
    flowRow(`GST (${business.assumptions.gst_pct}%, to government)`, -e.gst, "sub"),
    flowRow("Net fare", e.net_fare),
    flowRow(`Raahi commission (${e.commission_pct}%)`, e.commission, "sub"),
    flowRow("Driver payout", e.driver_payout, "sub"),
    flowRow("Driver fuel, incl. drive to pickup", -e.driver_fuel, "sub"),
    flowRow("Driver takes home", signed(e.driver_net), "total"),
    el("div", { class: "muted", style: "margin-top:8px" }, "Raahi's side of the same ride"),
    flowRow("Commission earned", e.commission),
    flowRow(`Payment processing (${business.assumptions.payment_pct}%)`, -e.payment_fee, "sub"),
    flowRow("Trip insurance", -e.insurance, "sub"),
    flowRow("Operations (support, maps, servers)", -e.ops, "sub"),
    flowRow(`Raahi profit (${e.margin_pct}% of fare)`, signed(e.profit), "total"));
}

function renderBusinessTotals() {
  const s = business.totals;
  const tile = (label, value, note) => el("div", { class: "card" }, el("div", { class: "muted" }, label),
    el("div", { class: "stat" }, value), note && el("div", { class: "muted" }, note));
  fill($("biz-totals"),
    tile("Completed rides", s.rides.toLocaleString("en-IN")),
    tile("Gross bookings", money(s.fare), "What riders paid"),
    tile("Raahi revenue", money(s.commission), "Commission"),
    tile("Raahi costs", money(s.platform_costs), "Payments, insurance, operations"),
    tile("Net profit", signed(s.profit), `${s.margin_pct}% of bookings`),
    tile("Profit per ride", signed(s.avg_profit), `Average fare ${money(s.avg_fare)}`),
    tile("Drivers took home", money(s.driver_net), `After ${money(s.driver_fuel)} fuel`),
    tile("GST collected", money(s.gst)),
    tile("Dynamic pricing effect", signed(s.pricing_effect), "Fares vs. the plain fare card"),
    tile("Loss-making rides", s.loss_rides.toLocaleString("en-IN")));
}

function renderBusinessVehicles() {
  const rows = Object.entries(business.by_vehicle);
  fill($("biz-vehicles"),
    el("thead", {}, el("tr", {}, el("th", {}, "Vehicle"), ["Rides", "Bookings", "Revenue", "Profit", "Per ride", "Margin"].map(h => el("th", { class: "num" }, h)))),
    el("tbody", {}, rows.length ? rows.map(([, s]) => el("tr", {},
      el("td", {}, s.label), el("td", { class: "num" }, String(s.rides)), el("td", { class: "num" }, money(s.fare)),
      el("td", { class: "num" }, money(s.commission)), el("td", { class: "num" }, signed(s.profit)),
      el("td", { class: "num" }, signed(s.avg_profit)), el("td", { class: "num" }, `${s.margin_pct}%`)))
      : el("tr", {}, el("td", { colSpan: 7, class: "muted" }, "No completed rides yet."))));
}

// [heading, value, numeric column, is money]
const RIDE_COLUMNS = [
  ["#", r => r.id], ["Trip", r => r.trip], ["Vehicle", r => r.label], ["Status", r => r.status.replace("_", " ")],
  ["km", r => r.km, true], ["×", r => r.multiplier.toFixed(2), true],
  ["Fare", r => r.economics.fare, true, true], ["GST", r => r.economics.gst, true, true],
  ["Commission", r => r.economics.commission, true, true], ["Driver payout", r => r.economics.driver_payout, true, true],
  ["Driver fuel", r => r.economics.driver_fuel, true, true], ["Driver net", r => r.economics.driver_net, true, true],
  ["Raahi costs", r => r.economics.platform_costs, true, true], ["Profit", r => r.economics.profit, true, true],
  ["Margin", r => `${r.economics.margin_pct}%`, true],
];

function renderBusinessRides() {
  fill($("biz-rides"),
    el("thead", {}, el("tr", {}, RIDE_COLUMNS.map(([h, , num]) => el("th", { class: num ? "num" : "" }, h)))),
    el("tbody", {}, business.rides.length ? business.rides.map(r => el("tr", { class: r.counted ? "" : "not-counted" },
      RIDE_COLUMNS.map(([h, value, num, isMoney]) => {
        const v = value(r);
        return el("td", { class: num ? "num" : "" }, h === "Profit" ? signed(v) : isMoney ? money(v) : String(v));
      })))
      : el("tr", {}, el("td", { colSpan: RIDE_COLUMNS.length, class: "muted" }, "No rides yet. Book one from the customer app."))));

  $("biz-export").onclick = () => {
    const cell = v => `"${String(v).replace(/"/g, '""')}"`;
    const csv = [RIDE_COLUMNS.map(([h]) => cell(h)).join(","),
      ...business.rides.map(r => RIDE_COLUMNS.map(([, value]) => cell(value(r))).join(","))].join("\n");
    const link = el("a", { href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })), download: "raahi_ride_profit.csv" });
    link.click();
    URL.revokeObjectURL(link.href);
  };
}

function renderBusinessForm() {
  const a = business.assumptions;
  const number = (id, value, max, step = 0.5) => el("input", { id, type: "number", min: 0, max, step, value });
  const field = (label, input) => el("div", {}, el("label", { htmlFor: input.id }, label), input);
  const general = {
    gst_pct: number("biz-gst", a.gst_pct, 28), payment_pct: number("biz-pay", a.payment_pct, 10, 0.1),
    insurance_per_ride: number("biz-ins", a.insurance_per_ride, 100), ops_per_ride: number("biz-ops", a.ops_per_ride, 200),
    pickup_km: number("biz-pickup", a.pickup_km, 20, 0.1),
  };
  const commission = Object.fromEntries(Object.entries(a.commission_pct).map(([v, x]) => [v, number(`biz-com-${v}`, x, 50)]));
  const fuel = Object.fromEntries(Object.entries(a.fuel_per_km).map(([v, x]) => [v, number(`biz-fuel-${v}`, x, 50, 0.1)]));
  const note = el("div", { class: "muted", role: "status" });
  const values = inputs => Object.fromEntries(Object.entries(inputs).map(([k, input]) => [k, +input.value]));

  fill($("biz-form"),
    el("h3", {}, "Business assumptions"),
    el("div", { class: "biz-form-grid" },
      field("GST %", general.gst_pct), field("Payment fee %", general.payment_pct),
      field("Insurance ₹/ride", general.insurance_per_ride), field("Operations ₹/ride", general.ops_per_ride),
      field("Drive to pickup, km", general.pickup_km)),
    el("div", { class: "muted" }, "Raahi commission % by vehicle"),
    el("div", { class: "biz-form-grid" }, Object.entries(commission).map(([v, input]) => field(VEHICLE_NAMES[v] || v, input))),
    el("div", { class: "muted" }, "Driver fuel or charging ₹/km by vehicle"),
    el("div", { class: "biz-form-grid" }, Object.entries(fuel).map(([v, input]) => field(VEHICLE_NAMES[v] || v, input))),
    el("div", { class: "row", style: "max-width:220px" }, el("button", { type: "submit" }, "Save")),
    note);
  $("biz-form").onsubmit = async event => {
    event.preventDefault();
    try {
      await api("/admin/business", { method: "PUT", body: { ...values(general), commission_pct: values(commission), fuel_per_km: values(fuel) } });
      note.textContent = "Saved. New rides use these rates; past rides keep theirs.";
      await refreshBusiness();
    } catch (e) { note.textContent = e.message; }
  };
}

async function refreshBusiness({ form = false } = {}) {
  business = await api("/admin/business");
  if (!business.sample_10km[sampleVehicle]) sampleVehicle = Object.keys(business.sample_10km)[0];
  renderBusinessTotals();
  renderFlow();
  renderBusinessVehicles();
  renderBusinessRides();
  if (form) renderBusinessForm();
}

// Help requests: user-written notes go in through el(), so they cannot inject markup.
async function refreshHelp() {
  const requests = await api("/admin/help");
  fill($("help-table"), requests.length
    ? [el("tr", {}, ["When", "Ride", "From", "Problem", "Details", "Status"].map(h => el("th", {}, h))),
       ...requests.map(h => el("tr", { class: h.topic === "safety" ? "help-urgent" : "" },
         el("td", {}, new Date(h.created_at * 1000).toLocaleString("en-IN")),
         el("td", {}, `#${h.ride_id} · ${h.route}`),
         el("td", {}, `${h.name} (${h.role}) `, el("a", { href: `tel:+91${h.phone}` }, `+91 ${h.phone}`)),
         el("td", {}, el("strong", {}, h.topic_label)),
         el("td", {}, h.note || "—"),
         el("td", {}, h.ride_status)))]
    : el("tr", {}, el("td", { class: "muted" }, "No help requests yet.")));
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
  await refreshBusiness({ form: true });
  await renderSimulation();
  await refreshHelp();
  connectLive(event => {
    if (event.type === "ride") { refreshStats().catch(() => {}); refreshBusiness().catch(() => {}); }
    if (event.type === "help") {
      toast(`🆘 ${event.help.topic_label}: ${event.help.name} (${event.help.role}), ride #${event.help.ride_id}`);
      refreshHelp().catch(() => {});
    }
  });
}

(async function init() {
  useAccount("admin");
  setupShell("Raahi Admin");
  await loadPhotos();
  if (await signedInUser("admin")) return start();
  fill($("auth-form"));
  showAuthPhoto("krimchi-temples");
  renderAuth($("auth-form"), "admin", start);
})();
