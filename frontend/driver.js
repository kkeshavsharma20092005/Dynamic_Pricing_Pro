let paymentAskedFor = null;
let map, places = [], online = false, position = null, ride = null, offer = null, offerTimer = null;
let addMessage = null, liveStarted = false, routeLine = null, self_marker = null, me = null;
const panel = () => $("panel");

function showPosition() {
  if (!position) return;
  if (!self_marker) self_marker = L.circleMarker([position.lat, position.lon], { radius: 8, color: "#fff", weight: 3, fillColor: "#1a73e8", fillOpacity: 1 }).addTo(map);
  else self_marker.setLatLng([position.lat, position.lon]);
}

async function sendState(nextOnline) {
  await api("/driver/state", { method: "POST", body: { online: nextOnline, lat: position && position.lat, lon: position && position.lon } });
  online = nextOnline;
}

function render() {
  if (ride) return renderRide();
  if (offer) return renderOffer();
  if (me.kyc !== "approved") return renderKyc();
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
    me.plate && el("div", { class: "plate-row" }, el("span", { class: "muted" }, "Your vehicle"), el("span", { class: "plate" }, me.plate)),
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

// No ride offers until an admin has approved the driver's ID and licence.
function renderKyc() {
  fill(panel(),
    photoBanner(photoById("patnitop"), "Get verified to drive"),
    kycPanel(me, saved => { me = saved; render(); kycThanks(me); }));
}

function driverHistory() {
  const list = el("div", {}, "…");
  api("/rides").then(rides => {
    const done = rides.filter(r => r.status === "completed");
    const earned = done.reduce((sum, r) => sum + r.fare, 0);
    list.replaceChildren(
      el("div", { class: "muted" }, `${done.length} completed · ${rupees(earned)} in fares`),
      ...rides.slice(0, 10).map(r => el("div", { class: "history-item" },
        `${placeLabel(r.pickup)} → ${placeLabel(r.dropoff)}`,
        el("div", { class: "muted" }, `${rupees(r.fare)} · ${t(STATUS_TEXT[r.status])}${r.feedback ? ` · rider gave ${"★".repeat(r.feedback.rating)}` : ""}`))));
  }).catch(() => list.replaceChildren());
  return list;
}

function renderOffer() {
  // Counted against a fixed end time, so redrawing the screen never restarts the clock.
  const secondsLeft = () => Math.max(0, Math.ceil((offer.expires - Date.now()) / 1000));
  const count = el("span", {}, String(secondsLeft()));
  const bar = el("div", { class: "progress-bar shrink",
    style: `animation-duration:${offer.seconds}s;animation-delay:-${offer.seconds - secondsLeft()}s` });
  clearInterval(offerTimer);
  offerTimer = setInterval(() => { if (offer) count.textContent = String(secondsLeft()); }, 1000);
  const answer = async action => {
    clearInterval(offerTimer);
    const current = offer;
    offer = null;
    try {
      const result = await api(`/rides/${current.ride.id}/${action}`, { method: "POST" });
      if (action === "accept") {
        ride = result;
        toast(`✓ Ride accepted. ${result.rider ? result.rider.name + " has been told you are on the way." : ""}`);
      }
    } catch (e) { toast(e.message); }
    render();
  };
  const near = offer.to_pickup;
  fill(panel(),
    photoBanner(photoFor(offer.ride.dropoff.name, offer.ride.region), offer.ride.dropoff.name),
    el("div", { class: "status pulse", role: "alert" }, "New ride request · ", count, "s"),
    offer.ride.women_only && womenRideTag(),
    el("div", { class: "progress" }, bar),
    el("div", { class: "offer-card" },
      offer.ride.rider && el("strong", {}, `Rider: ${offer.ride.rider.name}`),
      near && el("div", { class: "offer-pickup" }, `📍 ${near.km} km to pickup · ~${formatMinutes(near.minutes)}`),
      el("div", {}, `${placeLabel(offer.ride.pickup)} → ${placeLabel(offer.ride.dropoff)}`),
      el("div", { class: "muted" }, `${offer.ride.km} km trip · ${rupees(offer.ride.fare)} · ${offer.ride.quote.label}`)),
    el("div", { class: "row" },
      el("button", { type: "button", class: "secondary", onclick: () => answer("decline") }, "Decline"),
      el("button", { type: "button", onclick: () => answer("accept") }, "Accept")),
  );
}

const womenRideTag = () => el("span", { class: "tag women" }, "🌸 " + t("Women Raahi"));

const NEXT_STEP = {
  accepted: ["arrived", "I have arrived"],
  arrived: ["in_progress", "Start trip"],
  in_progress: ["completed", "Complete trip"],
};

function renderRide() {
  if (routeLine) routeLine.remove();
  routeLine = L.polyline(ride.path, routeStyle(ride.path)).addTo(map);
  goScreen("ride");
  map.fitBounds(routeLine.getBounds(), { padding: [30, 30] });

  const finished = ride.status === "completed" || ride.status === "cancelled";
  const step = NEXT_STEP[ride.status];
  const existing = !finished ? $("chat-area") : null;
  const chatArea = existing || el("div", { id: "chat-area", class: "stack" });
  fill(panel(),
    photoBanner(photoFor(ride.dropoff.name, ride.region), ride.dropoff.name),
    el("div", { class: "status", role: "status" }, t(STATUS_TEXT[ride.status])),
    // Show this QR to the rider to collect the fare, or take cash and tap "Cash received".
    ride.status === "completed" && paymentCard(ride, { role: "driver", onCash: cashReceived }),
    ride.women_only && womenRideTag(),
    el("div", {}, `${placeLabel(ride.pickup)} → ${placeLabel(ride.dropoff)}`),
    el("div", { class: "muted" }, `${ride.km} km · ${rupees(ride.fare)} · ${ride.quote.label}`),
    ride.rider && el("div", { class: "row", style: "align-items:center" },
      el("strong", {}, ride.rider.name),
      ride.rider.phone && el("a", { href: `tel:+91${ride.rider.phone}` }, el("button", { type: "button", class: "secondary" }, t("Call")))),
    step && el("button", { type: "button", onclick: () =>
      api(`/rides/${ride.id}/advance/${step[0]}`, { method: "POST" }).then(r => { ride = r; toast(t(STATUS_TEXT[r.status])); render(); }).catch(e => toast(e.message)) }, step[1]),
    ["accepted", "arrived"].includes(ride.status) && el("button", { type: "button", class: "danger", onclick: () =>
      api(`/rides/${ride.id}/cancel`, { method: "POST" }).then(r => { ride = r; render(); }).catch(e => toast(e.message)) }, t("Cancel ride")),
    !finished && chatArea,
    finished && el("button", { type: "button", onclick: backToWaiting }, "Back to waiting"),
  );
  if (!finished && !existing) addMessage = renderChat(chatArea, ride, "driver");
  updateRideHelp(ride, "driver");
  // The trip has just ended: put the QR in front of the driver to show the rider.
  if (ride.status === "completed" && paymentDue(ride) && paymentAskedFor !== ride.id) {
    paymentAskedFor = ride.id;
    openPayment(ride, "driver", { onCash: cashReceived });
  }
}

function cashReceived() {
  api(`/rides/${ride.id}/cash`, { method: "POST" })
    .then(r => {
      const wasDue = paymentDue(ride);     // the live update may already have shown it
      ride = r;
      render();
      if (wasDue) showPaymentReceived(r);
    })
    .catch(e => toast(e.message));
}

function backToWaiting() {
  goScreen("waiting", { replace: true });
  ride = addMessage = null;
  closePayment();
  updateRideHelp(null);
  if (routeLine) { routeLine.remove(); routeLine = null; }
  render();
}

// Back during a live trip keeps the trip on screen; after it ends, returns to waiting.
function goBack() {
  if (ride && !["completed", "cancelled"].includes(ride.status)) {
    goScreen("ride");
    toast("Trip in progress. Finish or cancel it first.");
  } else if (ride) {
    backToWaiting();
  }
}

function onLive(event) {
  if (event.type === "connected") {
    api("/rides/active").then(active => { if (active) { ride = active; render(); } }).catch(() => {});
    if (online) sendState(true).catch(() => {});
  } else if (event.type === "offer") {
    offer = { ...event, expires: Date.now() + event.seconds * 1000 };
    render();
  } else if (event.type === "offer_gone") {
    if (offer && offer.ride.id === event.ride_id) { offer = null; clearInterval(offerTimer); render(); }
  } else if (event.type === "ride") {
    if (ride && ride.id === event.ride.id) {
      const justPaid = ride.payment && ride.payment.status === "due" && event.ride.payment && event.ride.payment.status === "paid";
      ride = event.ride;
      render();
      if (justPaid) showPaymentReceived(ride);
    }
    if (offer && offer.ride.id === event.ride.id && event.ride.status !== "searching") { offer = null; clearInterval(offerTimer); render(); }
  } else if (event.type === "message" && ride && ride.id === event.message.ride_id && addMessage) {
    addMessage(event.message);
    if (event.message.sender !== "driver") toast("💬 " + event.message.body);
  } else if (event.type === "kyc") {
    me = event.user;
    if (!ride && !offer) render();
    if (me.kyc === "approved") welcomeApproved();
    else toast(t("Your ID check was not approved."));
  }
}

// ---------- the welcome after approval
// Shown once per driver on this device: the moment the admin approves, or at the next login
// if the app was closed then. The same news also goes out by email and SMS.
const welcomedKey = () => `raahi_driver_welcomed_${me.id}`;

function welcomeApproved() {
  if (me.kyc !== "approved" || localStorage.getItem(welcomedKey())) return;
  localStorage.setItem(welcomedKey(), "1");
  const close = () => { sheet.remove(); removeEventListener("keydown", onKey); };
  const onKey = event => { if (event.key === "Escape") close(); };
  const go = el("button", { type: "button", onclick: close }, t("Start driving"));
  const sheet = el("div", { class: "gender-backdrop", onclick: event => { if (event.target === sheet) close(); } },
    el("section", { class: "gender-sheet stack kyc-thanks driver-welcome", role: "alertdialog", "aria-modal": "true",
                    "aria-labelledby": "welcome-title", "aria-describedby": "welcome-body" },
      el("div", { class: "welcome-badge", "aria-hidden": "true" }, "🎉"),
      el("h2", { id: "welcome-title" }, t("Thank you for registering with Raahi")),
      el("div", { id: "welcome-body", class: "stack" },
        el("p", { class: "welcome-approved" }, "✓ ", t("You are approved as a Raahi driver.")),
        el("p", {}, t("You can now drive with Raahi.")),
        me.plate && el("div", { class: "plate-row", style: "justify-content:center" },
          el("span", { class: "muted" }, t("Your vehicle")), el("span", { class: "plate" }, me.plate)),
        el("p", { class: "muted" }, t("Choose your location and tap Go online to start getting rides.")),
        me.email && el("p", { class: "muted" }, t("We have also sent this to"), " ", el("strong", {}, me.email))),
      go));
  addEventListener("keydown", onKey);
  document.body.append(sheet);
  go.focus();
}

async function start(user) {
  me = await askGender(user);
  hideAuth();
  goScreen("waiting", { replace: true });
  onBack(goBack);
  $("app").classList.remove("hidden");
  showLogout();
  map = map || makeMap();
  map.invalidateSize();
  places = await api("/places");
  render();
  welcomeApproved();     // approved while the app was closed
  if (!liveStarted) { liveStarted = true; connectLive(onLive); }
}

const vehicleField = () => [{
  key: "vehicle", label: "Vehicle",
  input: el("select", { id: "auth-vehicle" },
    [["bike", "Bike"], ["erickshaw", "E-rickshaw"], ["auto", "Auto"], ["cab", "Cab"], ["shared", "Shared cab"]]
      .map(([value, label]) => el("option", { value }, label))),
}];

(async function init() {
  showSplash();
  try {
    useAccount("driver");
    setupShell("Raahi Driver");
    await loadPhotos();
    const signedIn = await signedInUser("driver");
    if (signedIn) return await start(signedIn);
    fill($("auth-form"));
    showAuthPhoto("patnitop");
    renderAuth($("auth-form"), "driver", start, vehicleField);
  } finally {
    hideSplash();
  }
})();
