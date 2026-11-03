let map, places = [], online = false, position = null, ride = null, offer = null, offerTimer = null;
let addMessage = null, liveStarted = false, routeLine = null, self_marker = null;
const panel = () => $("panel");

function showPosition() {
  if (!position) return;
  if (!self_marker) self_marker = L.circleMarker([position.lat, position.lon], { radius: 8, color: "#fff", weight: 2, fillColor: "#34d399", fillOpacity: 1 }).addTo(map);
  else self_marker.setLatLng([position.lat, position.lon]);
}

async function sendState(nextOnline) {
  await api("/driver/state", { method: "POST", body: { online: nextOnline, lat: position && position.lat, lon: position && position.lon } });
  online = nextOnline;
}

function render() {
  if (ride) return renderRide();
  if (offer) return renderOffer();
  const error = el("div", { class: "error", role: "alert" });
  const select = el("select", { id: "start-place", onchange: async () => {
    const place = places.find(p => p.name === select.value);
    if (!place) return;
    position = { lat: place.lat, lon: place.lon };
    showPosition();
    map.setView([place.lat, place.lon], 12);
    if (online) await sendState(true).catch(e => { error.textContent = e.message; });
  } }, el("option", { value: "" }, t("Choose a place")), places.map(p => el("option", { value: p.name }, p.name)));

  fill(panel(),
    photoBanner(photoById("patnitop"), online ? "Ready for riders" : "Start your shift"),
    el("div", { class: "status" + (online ? " pulse" : ""), role: "status" }, online ? "You are online. Waiting for rides." : "You are offline."),
    el("div", {}, el("label", { htmlFor: "start-place" }, "Your location"), select),
    el("button", { type: "button", class: "secondary", onclick: () => {
      navigator.geolocation && navigator.geolocation.getCurrentPosition(p => {
        position = { lat: p.coords.latitude, lon: p.coords.longitude };
        showPosition();
        map.setView([position.lat, position.lon], 13);
      }, e => { error.textContent = e.message; });
    } }, t("Use my location")),
    el("button", { type: "button", class: online ? "secondary" : "", onclick: async () => {
      try { await sendState(!online); toast(online ? "You are online" : "You are offline"); render(); } catch (e) { error.textContent = e.message; }
    } }, online ? "Go offline" : "Go online"),
    error,
    el("h3", { class: "section" }, t("Your trips")), driverHistory(),
  );
}

function driverHistory() {
  const list = el("div", {}, "…");
  api("/rides").then(rides => {
    const done = rides.filter(r => r.status === "completed");
    const earned = done.reduce((sum, r) => sum + r.fare, 0);
    list.replaceChildren(
      el("div", { class: "muted" }, `${done.length} completed · ${rupees(earned)} in fares`),
      ...rides.slice(0, 10).map(r => el("div", { class: "history-item" },
        `${r.pickup.name} → ${r.dropoff.name}`,
        el("div", { class: "muted" }, `${rupees(r.fare)} · ${t(STATUS_TEXT[r.status])}`))));
  }).catch(() => list.replaceChildren());
  return list;
}

function renderOffer() {
  let left = offer.seconds;
  const count = el("span", {}, String(left));
  const bar = el("div", { class: "progress-bar shrink", style: `animation-duration:${offer.seconds}s` });
  clearInterval(offerTimer);
  offerTimer = setInterval(() => { left -= 1; count.textContent = String(Math.max(left, 0)); }, 1000);
  const answer = async action => {
    clearInterval(offerTimer);
    const current = offer;
    offer = null;
    try {
      const result = await api(`/rides/${current.ride.id}/${action}`, { method: "POST" });
      if (action === "accept") { ride = result; }
    } catch (e) { toast(e.message); }
    render();
  };
  fill(panel(),
    photoBanner(photoFor(offer.ride.dropoff.name, offer.ride.region), offer.ride.dropoff.name),
    el("div", { class: "status pulse", role: "alert" }, "New ride request · ", count, "s"),
    el("div", { class: "progress" }, bar),
    el("div", {}, `${offer.ride.pickup.name} → ${offer.ride.dropoff.name}`),
    el("div", { class: "muted" }, `${offer.ride.km} km · ${rupees(offer.ride.fare)} · ${offer.ride.quote.label}`),
    el("div", { class: "row" },
      el("button", { type: "button", class: "secondary", onclick: () => answer("decline") }, "Decline"),
      el("button", { type: "button", onclick: () => answer("accept") }, "Accept")),
  );
}

const NEXT_STEP = {
  accepted: ["arrived", "I have arrived"],
  arrived: ["in_progress", "Start trip"],
  in_progress: ["completed", "Complete trip"],
};

function renderRide() {
  if (routeLine) routeLine.remove();
  routeLine = L.polyline(ride.path, { color: "#2dd4bf", weight: 4, dashArray: "6 6" }).addTo(map);
  map.fitBounds(routeLine.getBounds(), { padding: [30, 30] });

  const finished = ride.status === "completed" || ride.status === "cancelled";
  const step = NEXT_STEP[ride.status];
  const existing = !finished ? $("chat-area") : null;
  const chatArea = existing || el("div", { id: "chat-area", class: "stack" });
  fill(panel(),
    photoBanner(photoFor(ride.dropoff.name, ride.region), ride.dropoff.name),
    el("div", { class: "status", role: "status" }, t(STATUS_TEXT[ride.status])),
    el("div", {}, `${ride.pickup.name} → ${ride.dropoff.name}`),
    el("div", { class: "muted" }, `${ride.km} km · ${rupees(ride.fare)} · ${ride.quote.label}`),
    ride.rider && el("div", { class: "row", style: "align-items:center" },
      el("strong", {}, ride.rider.name),
      ride.rider.phone && el("a", { href: `tel:+91${ride.rider.phone}` }, el("button", { type: "button", class: "secondary" }, t("Call")))),
    step && el("button", { type: "button", onclick: () =>
      api(`/rides/${ride.id}/advance/${step[0]}`, { method: "POST" }).then(r => { ride = r; toast(t(STATUS_TEXT[r.status])); render(); }).catch(e => toast(e.message)) }, step[1]),
    ["accepted", "arrived"].includes(ride.status) && el("button", { type: "button", class: "danger", onclick: () =>
      api(`/rides/${ride.id}/cancel`, { method: "POST" }).then(r => { ride = r; render(); }).catch(e => toast(e.message)) }, t("Cancel ride")),
    !finished && chatArea,
    finished && el("button", { type: "button", onclick: () => {
      ride = addMessage = null;
      if (routeLine) { routeLine.remove(); routeLine = null; }
      render();
    } }, "Back to waiting"),
  );
  if (!finished && !existing) addMessage = renderChat(chatArea, ride, "driver");
}

function onLive(event) {
  if (event.type === "connected") {
    api("/rides/active").then(active => { if (active) { ride = active; render(); } }).catch(() => {});
    if (online) sendState(true).catch(() => {});
  } else if (event.type === "offer") {
    offer = event;
    render();
  } else if (event.type === "offer_gone") {
    if (offer && offer.ride.id === event.ride_id) { offer = null; clearInterval(offerTimer); render(); }
  } else if (event.type === "ride") {
    if (ride && ride.id === event.ride.id) { ride = event.ride; render(); }
    if (offer && offer.ride.id === event.ride.id && event.ride.status !== "searching") { offer = null; clearInterval(offerTimer); render(); }
  } else if (event.type === "message" && ride && ride.id === event.message.ride_id && addMessage) {
    addMessage(event.message);
    if (event.message.sender !== "driver") toast("💬 " + event.message.body);
  }
}

async function start() {
  hideAuth();
  $("app").classList.remove("hidden");
  showLogout();
  map = map || makeMap();
  map.invalidateSize();
  places = await api("/places");
  render();
  if (!liveStarted) { liveStarted = true; connectLive(onLive); }
}

const vehicleField = () => [{
  key: "vehicle", label: "Vehicle",
  input: el("select", { id: "auth-vehicle" },
    [["bike", "Bike"], ["erickshaw", "E-rickshaw"], ["auto", "Auto"], ["cab", "Cab"], ["shared", "Shared cab"]]
      .map(([value, label]) => el("option", { value }, label))),
}];

(async function init() {
  useAccount("driver");
  setupShell("Raahi Driver");
  await loadPhotos();
  if (token()) {
    const me = await api("/me").catch(() => null);
    if (me && me.role === "driver") return start();
  }
  showAuthPhoto("patnitop");
  renderAuth($("auth-form"), "driver", start, vehicleField);
})();
