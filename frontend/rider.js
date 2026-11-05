let map, places = [], pickup = null, dropoff = null, quote = null, chosen = null;
let ride = null, addMessage = null, liveStarted = false, quoteRun = 0;
const layers = { pickup: null, dropoff: null, route: null, driver: null, nearby: [] };
const panel = () => $("panel");
const VEHICLE_ICON = { bike: "🛵", erickshaw: "🛺", auto: "🛺", cab: "🚕", shared: "🚐" };
const STEPS = ["searching", "accepted", "arrived", "in_progress", "completed"];

// ---------- Women Raahi: women riders can ride with women drivers only, in a pink theme.
// The choice is remembered on this device for this account until she turns it off.
let me = null, womenMode = false;
const womenKey = () => `raahi_women_raahi_${me.id}`;
const canUseWomenMode = () => !!me && me.gender === "female";
const isVerified = () => !!me && me.kyc === "approved";
const isWomenMode = () => canUseWomenMode() && isVerified() && womenMode;   // chat.js reads this too

// The first time she turns it on, she verifies her ID in a sheet over the dashboard.
function openWomenKyc() {
  const close = () => { sheet.remove(); renderBooking(); };
  const sheet = el("div", { class: "gender-backdrop", onclick: event => { if (event.target === sheet) close(); } },
    el("section", { class: "gender-sheet kyc-sheet", role: "dialog", "aria-modal": "true", "aria-label": t("Verify your ID for Women Raahi") },
      el("button", { type: "button", class: "assistant-close kyc-close", "aria-label": t("Close"), onclick: close }, "×"),
      kycPanel(me, saved => {
        me = saved;
        sheet.remove();
        renderBooking();
        kycThanks(me);
      })));
  document.body.append(sheet);
  sheet.querySelector("select, button").focus();
}

function applyWomenMode() {
  document.body.classList.toggle("women-mode", isWomenMode());
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = isWomenMode() ? "#ffe4ee" : "#ffffff";
}

function womenToggle() {
  if (!canUseWomenMode()) return null;
  const on = isWomenMode();
  const subtitle = on ? "On: your rides go only to women drivers"
    : me.kyc === "pending" ? "ID check pending. It turns on once approved."
    : isVerified() ? "Tap to ride only with women drivers" : "Verify your ID once to turn this on";
  return el("button", {
    type: "button", id: "women-raahi", class: "women-toggle" + (on ? " on" : ""), "aria-pressed": String(on),
    onclick: () => {
      if (!isVerified()) {
        if (me.kyc === "pending") toast(t("ID check pending. It turns on once approved."));
        else openWomenKyc();
        return;
      }
      womenMode = !womenMode;
      localStorage.setItem(womenKey(), womenMode ? "1" : "0");
      applyWomenMode();
      toast(t(womenMode ? "Women Raahi is on" : "Women Raahi is off"));
      renderBooking();
    },
  },
    el("span", { class: "women-icon", "aria-hidden": "true" }, "🌸"),
    el("span", { class: "women-text" }, el("strong", {}, t("Women Raahi")),
      el("span", {}, t(subtitle))),
    el("span", { class: "women-switch", "aria-hidden": "true" }));
}

const womenBadge = () => el("span", { class: "tag women" }, "🌸 " + t("Women Raahi") + " · " + t("Only women drivers"));

// Pickup: a black dot with a white ring. Drop-off: a black square.
const DROP_ICON = L.divIcon({ className: "pin-drop", iconSize: [16, 16] });
function marker(key, point) {
  if (layers[key]) layers[key].remove();
  if (!point) { layers[key] = null; return; }
  layers[key] = key === "dropoff"
    ? L.marker([point.lat, point.lon], { icon: DROP_ICON, keyboard: false }).addTo(map)
    : L.circleMarker([point.lat, point.lon], { radius: 8, color: "#fff", weight: 3, fillColor: "#111", fillOpacity: 1 }).addTo(map);
}

function drawRoute(path) {
  if (layers.route) layers.route.remove();
  layers.route = path ? L.polyline(path, routeStyle(path)).addTo(map) : null;
  if (layers.route) map.fitBounds(layers.route.getBounds(), { padding: [30, 30] });
}

function clearNearby() {
  layers.nearby.forEach(m => m.remove());
  layers.nearby = [];
}

async function showNearby() {
  clearNearby();
  if (!pickup) return;
  const drivers = await api(`/nearby?lat=${pickup.lat}&lon=${pickup.lon}`).catch(() => []);
  layers.nearby = drivers.map(d => L.circleMarker([d.lat, d.lon],
    { radius: 5, color: "#fff", fillColor: d.simulated ? "#8a8a8a" : "#12805c", fillOpacity: 1, weight: 2 }).addTo(map));
}

async function withAddress(point) {
  const found = await api(`/address/reverse?lat=${point.lat}&lon=${point.lon}`).catch(() => null);
  return { ...point, name: found ? found.name : null };
}

// Search by area, lane or landmark. It runs on submit, as the map service's rules require.
function addressSearch(id, onPick) {
  const results = el("div", { class: "stack address-results" });
  const input = el("input", { id, placeholder: t("Type your area, lane or landmark"), maxLength: 120, autocomplete: "street-address", dir: "auto" });
  const form = el("form", { class: "row", onsubmit: async event => {
    event.preventDefault();
    const q = input.value.trim();
    if (q.length < 2) return;
    fill(results, el("div", { class: "skeleton short" }));
    const anchor = pickup || dropoff;
    const near = anchor ? `&near_lat=${anchor.lat}&near_lon=${anchor.lon}` : "";
    try {
      const found = await api(`/address?q=${encodeURIComponent(q)}${near}`);
      fill(results, found.length
        ? found.map(r => el("button", {
            type: "button", class: "address-option",
            onclick: () => {
              onPick({ lat: r.lat, lon: r.lon, name: r.name });
              // With both ends set, the route takes over framing the map.
              if (!(pickup && dropoff)) map.flyTo([r.lat, r.lon], 14, { duration: .8 });
            },
          }, el("strong", {}, r.name), r.detail && el("span", { class: "muted" }, r.detail),
             r.approx && el("span", { class: "muted" }, `${t("Pin near")} ${r.area}`)))
        : el("div", { class: "error" }, t("Not found. Try a nearby landmark, or tap the spot on the map.")));
    } catch (e) { fill(results, el("div", { class: "error" }, e.message)); }
  } }, input, el("button", { type: "submit", class: "secondary", style: "flex:0 0 76px" }, t("Search")));
  return el("div", { class: "stack" }, form, results);
}

function placeSelect(id, label, current, onPick) {
  const select = el("select", { id, onchange: () => {
    const place = places.find(p => p.name === select.value);
    if (place) onPick({ lat: place.lat, lon: place.lon, name: place.name });
  } },
    el("option", { value: "" }, current && !places.some(p => p.name === current.name)
      ? current.name || `${current.lat.toFixed(3)}, ${current.lon.toFixed(3)}` : t("Choose a place")),
    places.map(p => el("option", { value: p.name, selected: current && current.name === p.name }, p.name)));
  return el("div", {}, el("label", { htmlFor: id }, t(label)), select);
}

const setPickup = p => { pickup = p; quote = null; marker("pickup", p); showNearby(); renderBooking(); };
const setDropoff = p => { dropoff = p; quote = null; marker("dropoff", p); renderBooking(); };

// Two cards can share a place, so only the first of them shows as chosen.
const isChosen = photo => !!dropoff && PHOTOS.find(p => p.place === dropoff.name) === photo;

function destinationScroller() {
  return el("div", {},
    el("h3", {}, t("Popular destinations")),
    el("div", { class: "scroller" }, PHOTOS.map(photo => {
      const place = places.find(p => p.name === photo.place);
      return el("button", {
        type: "button", class: "dest" + (isChosen(photo) ? " active" : ""),
        "aria-pressed": String(isChosen(photo)),
        onclick: () => {
          setDropoff({ lat: place.lat, lon: place.lon, name: place.name });
          if (!pickup) map.flyTo([place.lat, place.lon], 10, { duration: 1 });
        },
      },
        el("img", { src: photo.src, alt: photo.title, loading: "lazy" }),
        el("span", { class: "dest-name" }, photo.title));
    })));
}

function renderBooking() {
  const error = el("div", { class: "error", role: "alert" });
  const results = el("div", { class: "stack" });
  map.off("click");
  map.on("click", async e => {
    const point = { lat: e.latlng.lat, lon: e.latlng.lng, name: null };
    if (chatPinHandler) {
      const handler = chatPinHandler;
      chatPinHandler = null;
      handler(point);
      return;
    }
    (pickup ? setDropoff : setPickup)(await withAddress(point));
  });

  const photo = dropoff && dropoff.name ? PHOTOS.find(p => p.place === dropoff.name) : null;
  fill(panel(),
    womenToggle(),
    photo && photoBanner(photo),
    destinationScroller(),
    placeSelect("pickup-select", "Pickup", pickup, setPickup),
    addressSearch("pickup-address", setPickup),
    el("div", { class: "row" },
      el("button", { type: "button", class: "secondary", onclick: () => {
        if (!navigator.geolocation) return;
        navigator.geolocation.getCurrentPosition(
          async pos => {
            setPickup(await withAddress({ lat: pos.coords.latitude, lon: pos.coords.longitude }));
            map.flyTo([pos.coords.latitude, pos.coords.longitude], 15);
          },
          e => toast(e.message));
      } }, t("Use my location")),
      el("button", { type: "button", class: "secondary", disabled: !(pickup && dropoff), onclick: () => {
        [pickup, dropoff] = [dropoff, pickup];
        marker("pickup", pickup);
        marker("dropoff", dropoff);
        quote = null;
        showNearby();
        renderBooking();
      } }, "⇅  " + t("Swap"))),
    placeSelect("dropoff-select", "Drop-off", dropoff, setDropoff),
    addressSearch("dropoff-address", setDropoff),
    !pickup && el("div", { class: "muted" }, t("Tap the map to set a pin")),
    error, results,
    el("h3", { class: "section" }, t("Your trips")), historyList(),
  );

  if (pickup && dropoff) loadQuote(results, error);
}

// Fares appear as soon as both ends are set. Only the latest request may draw, so a slow
// answer for an earlier choice cannot overwrite a newer one.
async function loadQuote(results, error) {
  const run = ++quoteRun;
  fill(results, el("div", { class: "skeleton" }), el("div", { class: "skeleton" }));
  try {
    const data = await api("/quote", { method: "POST", body: { pickup, dropoff } });
    if (run !== quoteRun) return;
    quote = data;
    chosen = quote.options.some(o => o.vehicle === chosen) ? chosen : quote.options[0].vehicle;
    drawRoute(quote.path);
    renderOptions(results, error, true);
    goScreen("fares");
  } catch (e) {
    if (run !== quoteRun) return;
    drawRoute(null);
    fill(results);
    error.textContent = e.message;
  }
}

function comparisonCard(option) {
  const rec = option.recommendation;
  const row = (id, name, fareNode, tag, link) => el("div", { class: "compare-row" + (rec.pick === id ? " picked" : "") },
    el("div", {}, el("strong", {}, name), " ", el("span", { class: "tag" + (tag === t("Estimate") ? " warn" : "") }, tag),
      rec.pick === id && rec.confident && el("span", { class: "tag good" }, t("Our pick"))),
    el("div", { class: "compare-fare" }, fareNode,
      link && el("a", { href: link, target: "_blank", rel: "noopener noreferrer", class: "muted", onclick: e => e.stopPropagation() }, t("Check real fare") + " ↗")));
  return el("div", { class: "card stack compare" },
    el("h3", {}, t("Price comparison")),
    row("raahi", "Raahi", rupees(option.fare), t("Confirmed fare")),
    option.rivals.map(r => row(r.id, r.label, `~${rupees(r.low)}-${rupees(r.high).slice(1)}`, t("Estimate"), r.url)),
    el("div", { class: "recommend" }, rec.message),
    option.rivals.length > 0 && el("div", { class: "muted" }, t("Estimates use assumed rates, not live Rapido or Uber prices, and exclude their surge.")));
}

function renderOptions(results, error, animate = false) {
  const current = quote.options.find(o => o.vehicle === chosen);
  const buttons = quote.options.map(o => {
    const selected = o.vehicle === chosen;
    const fare = el("span", {}, rupees(o.fare));
    if (animate) countUp(fare, o.fare);
    return el("button", {
      type: "button", class: "option" + (selected ? " selected" : ""), "aria-pressed": String(selected),
      onclick: () => { chosen = o.vehicle; renderOptions(results, error); },
    },
      el("div", { class: "option-head" },
        el("span", { class: "option-name" }, el("span", { class: "veh-icon", "aria-hidden": "true" }, VEHICLE_ICON[o.vehicle]), o.label), fare),
      el("div", { class: "muted" }, `${quote.km} km · ~${formatMinutes(quote.minutes)} · ×${o.multiplier}`),
      selected && o.fair_capped && el("span", { class: "tag warn" }, `${t("Fair-price limit applied")} · ${rupees(o.saved_by_cap)} ${t("saved")}`),
      selected && o.reasons.length > 0 && el("div", { class: "reasons" },
        el("div", { class: "muted" }, `${t("Why this fare")} (${t("Normal fare")} ${rupees(o.normal_fare)})`),
        o.reasons.map(r => el("div", { class: "reason" }, el("span", {}, r.factor),
          el("span", {}, (r.effect > 0 ? "+" : "−") + rupees(Math.abs(r.effect)))))));
  });
  fill(results,
    el("div", { class: "muted" }, `${weatherIcon(quote.weather)} ${quote.region_name} · ${quote.weather}${quote.road_closed ? " · road closure" : ""}. ${quote.routed ? "Road route and distance from OpenStreetMap." : "Distance is estimated."}`),
    buttons,
    comparisonCard(current),
    el("div", { class: "muted" }, t("Demo payment: pay the driver directly")),
    el("button", { type: "button", id: "book", onclick: async () => {
      askToNotify();
      try {
        showRide(await api("/rides", { method: "POST", body: { pickup, dropoff, vehicle: chosen, women_only: isWomenMode() } }));
        toast(t(isWomenMode() ? "Finding a woman driver…" : "Finding a driver…"));
      } catch (e) { error.textContent = e.message; }
    } }, `${t("Book")} · ${rupees(current.fare)}`));
}

function historyList() {
  const list = el("div", {}, el("div", { class: "muted" }, "…"));
  api("/rides").then(rides => {
    fill(list, rides.length ? rides.slice(0, 10).map(r =>
      el("div", { class: "history-item" },
        el("div", {}, `${r.pickup.name} → ${r.dropoff.name}`),
        el("div", { class: "muted" }, `${rupees(r.fare)} · ${t(STATUS_TEXT[r.status])} · ${new Date(r.created_at * 1000).toLocaleDateString("en-IN")}`
          + (r.feedback ? ` · ${"★".repeat(r.feedback.rating)}` : "")),
        el("button", { type: "button", class: "linkish", onclick: () => {
          setPickup(r.pickup);
          setDropoff(r.dropoff);
        } }, t("Book again"))))
      : el("div", { class: "muted" }, t("No trips yet.")));
  }).catch(() => fill(list));
  return list;
}

function stepper(status) {
  const reached = STEPS.indexOf(status);
  return el("ol", { class: "stepper", "aria-label": "Trip progress" },
    STEPS.map((step, i) => el("li", { class: i < reached ? "done" : i === reached ? "now" : "" },
      el("span", { class: "dot" }), el("span", { class: "step-name" }, t(STEP_NAMES[step])))));
}

function showRide(next) {
  const statusChanged = ride && ride.id === next.id && ride.status !== next.status;
  const sameChat = ride && ride.id === next.id && ride.driver && next.driver;
  ride = next;
  goScreen("ride");
  clearNearby();
  drawRoute(ride.path);
  marker("pickup", ride.pickup);
  marker("dropoff", ride.dropoff);
  // A driver accepting gets the "Ride confirmed" pop-up instead of a toast.
  if (statusChanged && ride.status !== "accepted") toast(t(STATUS_TEXT[ride.status]));

  const finished = ride.status === "completed" || ride.status === "cancelled";
  if (finished && layers.driver) { layers.driver.remove(); layers.driver = null; }

  const existingChat = sameChat && !finished ? $("chat-area") : null;
  const chatArea = existingChat || el("div", { id: "chat-area", class: "stack" });
  const driver = ride.driver;
  const photo = photoFor(ride.dropoff.name, ride.region);

  const statusText = ride.women_only && ride.status === "searching" ? "Finding a woman driver…" : STATUS_TEXT[ride.status];
  fill(panel(),
    photoBanner(photo, ride.dropoff.name),
    el("div", { class: "status" + (ride.status === "searching" ? " pulse" : ""), role: "status" }, t(statusText)),
    ride.women_only && womenBadge(),
    ride.status !== "cancelled" && stepper(ride.status),
    ride.status === "in_progress" && el("div", {},
      el("div", { class: "progress" }, el("div", { id: "trip-bar", class: "progress-bar" })),
      el("div", { id: "trip-eta", class: "muted" }, `~${formatMinutes(ride.minutes)} ${t("left")}`)),
    el("div", {}, `${ride.pickup.name} → ${ride.dropoff.name}`),
    el("div", { class: "muted" }, `${ride.km} km · ${rupees(ride.fare)} · ${VEHICLE_ICON[ride.vehicle]} ${ride.quote.label}`),
    driver && el("div", { class: "row driver-card" },
      el("div", {}, el("strong", {}, driver.name), " ",
        driver.simulated && el("span", { class: "tag" }, t("Demo driver")),
        driver.plate && el("div", { class: "plate-row" }, el("span", { class: "plate", "aria-label": `${t("Vehicle number plate")} ${driver.plate}` }, driver.plate),
          !finished && el("span", { class: "muted" }, t("Check the number plate before you get in")))),
      !finished && (driver.phone
        ? el("a", { href: `tel:+91${driver.phone}` }, el("button", { type: "button", class: "secondary" }, t("Call")))
        : el("button", { type: "button", class: "secondary", onclick: () => toast(t("Calling is simulated for demo drivers.")) }, t("Call")))),
    driver && !finished && chatArea,
    ride.quote.reasons.length > 0 && el("div", {},
      el("h3", {}, t("Why this fare")),
      ride.quote.reasons.map(r => el("div", { class: "reason" }, el("span", {}, r.factor),
        el("span", {}, (r.effect > 0 ? "+" : "−") + rupees(Math.abs(r.effect)))))),
    ["searching", "accepted", "arrived"].includes(ride.status) && el("button", {
      type: "button", class: "danger",
      onclick: () => api(`/rides/${ride.id}/cancel`, { method: "POST" }).then(showRide).catch(e => toast(e.message)),
    }, t("Cancel ride")),
    ride.status === "completed" && driver && (ride.feedback
      ? el("div", { class: "rated" }, el("span", { class: "stars-static", "aria-label": `${ride.feedback.rating} / 5` }, "★".repeat(ride.feedback.rating) + "☆".repeat(5 - ride.feedback.rating)),
          el("span", { class: "muted" }, t("Thanks for rating this trip")))
      : el("button", { type: "button", class: "secondary", onclick: () => showFeedback(ride) }, "★ " + t("Rate this trip"))),
    finished && el("button", { type: "button", onclick: resetBooking }, t("Book another ride")),
  );
  // Asked once, right when the trip ends. Skipping is fine: the button above stays.
  if (statusChanged && ride.status === "completed" && driver && !ride.feedback) setTimeout(() => showFeedback(ride), 600);
  if (driver && !finished && !existingChat) addMessage = renderChat(chatArea, ride, "rider");
  updateRideHelp(ride, "rider");
}

// ---------- "Ride confirmed" pop-up, shown once when a driver accepts
const initials = name => name.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join("");

function closeConfirmed() {
  const open = $("confirm-backdrop");
  if (open) open.remove();
}

function showConfirmed(r) {
  const driver = r.driver;
  if (!driver) return;
  closeConfirmed();
  const eta = driver.to_pickup;
  const close = () => { backdrop.remove(); removeEventListener("keydown", onKey); };
  const onKey = e => { if (e.key === "Escape") close(); };
  const callButton = driver.phone
    ? el("a", { class: "confirm-action", href: `tel:+91${driver.phone}` }, el("span", { "aria-hidden": "true" }, "📞"), t("Call driver"))
    : el("button", { type: "button", class: "confirm-action", onclick: () => toast(t("Calling is simulated for demo drivers.")) },
        el("span", { "aria-hidden": "true" }, "📞"), t("Call driver"));
  const gotIt = el("button", { type: "button", class: "confirm-done", onclick: close }, t("Got it"));

  const backdrop = el("div", { id: "confirm-backdrop", class: "confirm-backdrop", onclick: e => { if (e.target === backdrop) close(); } },
    el("section", { class: "confirm-card", role: "dialog", "aria-modal": "true", "aria-labelledby": "confirm-title", "aria-describedby": "confirm-sub" },
      el("div", { class: "confirm-head" },
        el("div", { class: "confirm-check", "aria-hidden": "true" }, "✓"),
        el("h2", { id: "confirm-title" }, t("Your ride is confirmed")),
        el("p", { id: "confirm-sub" }, `${driver.name} ${t("accepted your ride and is on the way.")}`)),

      el("div", { class: "confirm-driver" },
        el("div", { class: "confirm-avatar", "aria-hidden": "true" }, initials(driver.name)),
        el("div", { class: "confirm-who" },
          el("strong", {}, driver.name),
          el("div", { class: "muted" }, `${VEHICLE_ICON[r.vehicle]} ${t(driver.vehicle)}`),
          driver.plate && el("span", { class: "plate confirm-plate", "aria-label": `${t("Vehicle number plate")} ${driver.plate}` }, driver.plate),
          driver.simulated && el("span", { class: "tag" }, t("Demo driver"))),
        eta && el("div", { class: "confirm-eta" },
          el("strong", {}, formatMinutes(eta.minutes)),
          el("span", {}, `${eta.km} km ${t("away")}`))),

      el("ol", { class: "confirm-trip", "aria-label": t("Trip") },
        el("li", { class: "from" }, el("span", { class: "muted" }, t("Pickup")), el("strong", {}, placeLabel(r.pickup))),
        el("li", { class: "to" }, el("span", { class: "muted" }, t("Drop-off")), el("strong", {}, placeLabel(r.dropoff)))),

      el("dl", { class: "confirm-facts" },
        el("div", {}, el("dt", {}, t("Fare")), el("dd", {}, rupees(r.fare))),
        el("div", {}, el("dt", {}, t("Distance")), el("dd", {}, `${r.km} km`)),
        el("div", {}, el("dt", {}, t("Ride")), el("dd", {}, `#${r.id}`))),
      el("div", { class: "muted confirm-note" }, t("Demo payment: pay the driver directly")),

      el("div", { class: "confirm-actions" },
        callButton,
        el("button", { type: "button", class: "confirm-action", onclick: () => {
          close();
          const input = document.querySelector("#chat-area input");
          if (input) input.focus();
        } }, el("span", { "aria-hidden": "true" }, "💬"), t("Message"))),
      gotIt));

  document.body.append(backdrop);
  addEventListener("keydown", onKey);
  gotIt.focus();
  if (navigator.vibrate) navigator.vibrate([120, 60, 120]);
  notifyInBackground(t("Your ride is confirmed"), `${driver.name} · ${t(driver.vehicle)}${eta ? ` · ${formatMinutes(eta.minutes)}` : ""}`);
}

// ---------- optional feedback after a completed trip
const RATING_WORDS = ["", "Terrible", "Bad", "Okay", "Good", "Excellent"];
const GOOD_TAGS = [["safe", "Safe driving"], ["polite", "Polite driver"], ["clean", "Clean vehicle"], ["on_time", "On time"], ["route", "Good route"]];
const BAD_TAGS = [["late", "Driver was late"], ["rash", "Rash driving"], ["rude", "Rude behaviour"], ["dirty", "Vehicle not clean"], ["fare", "Fare issue"], ["route", "Wrong route or stop"]];

function showFeedback(r) {
  if (!r.driver || r.feedback || $("feedback-backdrop")) return;
  closeConfirmed();
  let rating = 0;
  const tags = new Set();
  const close = () => { backdrop.remove(); removeEventListener("keydown", onKey); };
  const onKey = e => { if (e.key === "Escape") close(); };

  const word = el("div", { class: "rating-word", "aria-live": "polite" }, t("Tap a star to rate"));
  const tagBox = el("div", { class: "help-topics feedback-tags" });
  const comment = el("textarea", { rows: 2, maxLength: 500, placeholder: t("Tell us more (optional)"), "aria-label": t("Tell us more (optional)") });
  const error = el("div", { class: "error", role: "alert" });
  const submit = el("button", { type: "button", class: "confirm-done", disabled: true, onclick: send }, t("Submit feedback"));
  const stars = [1, 2, 3, 4, 5].map(n => el("button", {
    type: "button", class: "star", role: "radio", "aria-checked": "false", "aria-label": `${n} ${t("of 5 stars")}`,
    onclick: () => choose(n),
  }, "★"));

  function choose(n) {
    const goodBefore = rating >= 4;
    rating = n;
    stars.forEach((s, i) => { s.classList.toggle("on", i < n); s.setAttribute("aria-checked", String(i + 1 === n)); });
    word.textContent = t(RATING_WORDS[n]);
    if (goodBefore !== (n >= 4) || !tagBox.childElementCount) tags.clear();
    fill(tagBox, (n >= 4 ? GOOD_TAGS : BAD_TAGS).map(([key, label]) => el("button", {
      type: "button", class: "chip" + (tags.has(key) ? " on" : ""), "aria-pressed": String(tags.has(key)),
      onclick: e => {
        tags.has(key) ? tags.delete(key) : tags.add(key);
        e.currentTarget.classList.toggle("on", tags.has(key));
        e.currentTarget.setAttribute("aria-pressed", String(tags.has(key)));
      },
    }, t(label))));
    submit.disabled = false;
  }

  async function send() {
    submit.disabled = true;
    error.textContent = "";
    try {
      const result = await api(`/rides/${r.id}/feedback`, { method: "POST", body: { rating, tags: [...tags], comment: comment.value } });
      fill(card, el("div", { class: "confirm-head" },
        el("div", { class: "confirm-check", "aria-hidden": "true" }, "✓"),
        el("h2", {}, t("Thank you for your feedback!")),
        el("p", {}, t("It helps us keep Raahi rides safe and comfortable."))));
      if (ride && ride.id === r.id) showRide({ ...ride, feedback: result.feedback });
      setTimeout(close, 1800);
    } catch (e) { error.textContent = e.message; submit.disabled = false; }
  }

  const card = el("section", { class: "confirm-card", role: "dialog", "aria-modal": "true", "aria-labelledby": "feedback-title" },
    el("div", { class: "confirm-head" },
      el("div", { class: "confirm-avatar feedback-avatar", "aria-hidden": "true" }, initials(r.driver.name)),
      el("h2", { id: "feedback-title" }, `${t("How was your ride with")} ${r.driver.name}?`),
      el("p", {}, `${placeLabel(r.pickup)} → ${placeLabel(r.dropoff)} · ${rupees(r.fare)}`)),
    el("div", { class: "stars", role: "radiogroup", "aria-label": t("Your rating") }, stars),
    word, tagBox, comment, error,
    el("div", { class: "confirm-actions" },
      el("button", { type: "button", class: "confirm-action", onclick: close }, t("Skip")),
      submit),
    el("div", { class: "muted confirm-note" }, t("Feedback is optional.")));
  const backdrop = el("div", { id: "feedback-backdrop", class: "confirm-backdrop", onclick: e => { if (e.target === backdrop) close(); } }, card);
  document.body.append(backdrop);
  addEventListener("keydown", onKey);
  stars[4].focus();
}

// When the tab is in the background, a system notification says the same thing.
function notifyInBackground(title, body) {
  if (!document.hidden || !("Notification" in window) || Notification.permission !== "granted") return;
  const options = { body, icon: "/static/icons/icon-192.png", tag: "raahi-ride" };
  if (navigator.serviceWorker) {
    navigator.serviceWorker.ready.then(reg => reg.showNotification(title, options)).catch(() => {});
  } else {
    try { new Notification(title, options); } catch { /* not supported on this browser */ }
  }
}

function askToNotify() {
  if ("Notification" in window && Notification.permission === "default") Notification.requestPermission().catch(() => {});
}

function resetBooking() {
  closeConfirmed();
  const asking = $("feedback-backdrop");
  if (asking) asking.remove();
  goScreen("book", { replace: true });
  ride = quote = dropoff = pickup = addMessage = null;
  updateRideHelp(null);
  ["pickup", "dropoff", "driver"].forEach(k => marker(k, null));
  drawRoute(null);
  renderBooking();
}

function moveDriver(event) {
  if (!layers.driver) {
    layers.driver = L.marker([event.lat, event.lon], {
      icon: L.divIcon({ className: "vehicle-marker", html: VEHICLE_ICON[ride.vehicle], iconSize: [34, 34] }),
    }).addTo(map);
  } else layers.driver.setLatLng([event.lat, event.lon]);

  if (ride.status === "in_progress" && event.progress != null && $("trip-bar")) {
    $("trip-bar").style.width = `${Math.round(event.progress * 100)}%`;
    $("trip-eta").textContent = `~${formatMinutes(ride.minutes * (1 - event.progress))} ${t("left")}`;
  }
}

function onLive(event) {
  if (event.type === "connected") {
    api("/rides/active").then(active => { if (active) showRide(active); }).catch(() => {});
  } else if (event.type === "ride") {
    if (!ride || ride.id === event.ride.id) showRide(event.ride);
    if (["cancelled", "completed"].includes(event.ride.status)) closeConfirmed();
  } else if (event.type === "kyc") {
    me = event.user;
    // Approval turns Women Raahi on: that is what she was verifying for.
    if (me.kyc === "approved") { womenMode = true; localStorage.setItem(womenKey(), "1"); }
    applyWomenMode();
    toast(t(me.kyc === "approved" ? "You are verified. Women Raahi is ready." : "Your ID check was not approved."));
    if (!ride) renderBooking();
  } else if (event.type === "confirmed") {
    if (!ride || ride.id === event.ride.id) { showRide(event.ride); showConfirmed(event.ride); }
  } else if (event.type === "position" && ride && ride.id === event.ride_id) {
    moveDriver(event);
  } else if (event.type === "message" && ride && ride.id === event.message.ride_id && addMessage) {
    addMessage(event.message);
    if (event.message.sender !== "rider") toast("💬 " + event.message.body);
  }
}

// Back: from a live ride, stay (it is still happening); from a finished ride or the fares,
// return to choosing a trip. From the booking screen itself, Back leaves the app as usual.
function goBack(state) {
  if (ride && !["completed", "cancelled"].includes(ride.status)) {
    goScreen("ride");
    toast(t("Your ride is in progress"));
  } else if (ride) {
    resetBooking();
  } else if (state !== "fares" && dropoff) {
    dropoff = quote = null;
    marker("dropoff", null);
    drawRoute(null);
    renderBooking();
  }
}

async function start(user) {
  me = await askGender(user);
  womenMode = localStorage.getItem(womenKey()) === "1";
  applyWomenMode();
  hideAuth();
  goScreen("book", { replace: true });
  onBack(goBack);
  $("app").classList.remove("hidden");
  showLogout();
  map = map || makeMap();
  map.invalidateSize();
  places = await api("/places");

  // Arriving from a destination card on the home page.
  const wanted = places.find(p => p.name === new URLSearchParams(location.search).get("to"));
  if (wanted) setDropoff({ lat: wanted.lat, lon: wanted.lon, name: wanted.name });
  else renderBooking();
  if (!liveStarted) { liveStarted = true; connectLive(onLive); setupChat(); }
}

(async function init() {
  useAccount("rider");
  setupShell("Raahi");
  await loadPhotos();
  const signedIn = await signedInUser("rider");
  if (signedIn) return start(signedIn);
  fill($("auth-form"));
  showAuthPhoto("bahu-fort");
  renderAuth($("auth-form"), "rider", start);
})();
