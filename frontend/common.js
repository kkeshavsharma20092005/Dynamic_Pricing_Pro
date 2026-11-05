// Shared by the rider, driver and admin pages. User-written text (names, chat) always goes
// through textContent via el(), never innerHTML, so it cannot inject markup.
// Each app keeps its own login, so a rider, driver and admin can be signed in side by side.
// The session lives in sessionStorage: it survives a reload (or a server that is waking up)
// but ends when the tab or browser closes, so coming back to the app asks for credentials.
let TOKEN_KEY = "raahi_token_rider";
const SESSION = sessionStorage;
const useAccount = role => {
  TOKEN_KEY = `raahi_token_${role}`;
  localStorage.removeItem(TOKEN_KEY);   // older versions kept a 7-day login on the device
};
const LANG_KEY = "raahi_lang";

const STRINGS = {
  hi: {
    "Log in": "लॉग इन", "Create account": "खाता बनाएं", "Mobile number": "मोबाइल नंबर",
    "Password": "पासवर्ड", "Your name": "आपका नाम", "Log out": "लॉग आउट",
    "New here? Create an account": "नए हैं? खाता बनाएं", "Have an account? Log in": "खाता है? लॉग इन करें",
    "Pickup": "पिकअप", "Drop-off": "ड्रॉप", "Choose a place": "जगह चुनें",
    "Use my location": "मेरी लोकेशन", "Tap the map to set a pin": "मैप पर टैप करके जगह चुनें",
    "See fares": "किराया देखें", "Book": "बुक करें", "Cancel ride": "राइड रद्द करें",
    "Why this fare": "यह किराया क्यों", "Normal fare": "सामान्य किराया",
    "Fair-price limit applied": "उचित मूल्य सीमा लागू", "saved": "बचत",
    "Finding a driver…": "ड्राइवर खोज रहे हैं…", "Driver is on the way": "ड्राइवर आ रहा है",
    "Driver has arrived": "ड्राइवर पहुंच गया", "On the trip": "यात्रा जारी है",
    "Trip completed": "यात्रा पूरी हुई", "Ride cancelled": "राइड रद्द हुई",
    "Call": "कॉल करें", "Send": "भेजें", "Message": "संदेश", "Your trips": "आपकी यात्राएं",
    "Book another ride": "एक और राइड बुक करें", "Demo driver": "डेमो ड्राइवर",
    "You are offline. Fares and booking need a connection.": "आप ऑफ़लाइन हैं। किराया और बुकिंग के लिए नेटवर्क चाहिए।",
    "Demo payment: pay the driver directly": "डेमो भुगतान: ड्राइवर को सीधे दें",
    "Calling is simulated for demo drivers.": "डेमो ड्राइवर के लिए कॉल सिम्युलेटेड है।",
    "No trips yet.": "अभी कोई यात्रा नहीं।",
    "Type your area, lane or landmark": "अपना इलाका, गली या लैंडमार्क लिखें", "Search": "खोजें",
    "Pin near": "पिन पास में", "Map pin": "मैप पिन",
    "Not found. Try a nearby landmark, or tap the spot on the map.": "नहीं मिला। पास का लैंडमार्क लिखें, या मैप पर जगह टैप करें।",
    "I couldn't get your location. Please allow location access, or tell me your area.": "आपकी लोकेशन नहीं मिल पाई। लोकेशन की अनुमति दें, या अपना इलाका बताएं।",
    "Location isn't available in this browser.": "इस ब्राउज़र में लोकेशन उपलब्ध नहीं है।",
    "Your ride across Jammu & Kashmir, in your own language.": "जम्मू-कश्मीर में आपकी सवारी, आपकी अपनी भाषा में।",
    "Go online and start earning across Jammu & Kashmir.": "ऑनलाइन जाइए और जम्मू-कश्मीर में कमाई शुरू कीजिए।",
    "Run fares and conditions across Jammu & Kashmir.": "जम्मू-कश्मीर में किराये और हालात संभालिए।",
    "From Jammu's temples to Kashmir's meadows": "जम्मू के मंदिरों से कश्मीर की वादियों तक",
    "Drive every road of Jammu & Kashmir": "जम्मू-कश्मीर की हर सड़क पर चलाइए",
    "Keep Raahi moving across the valley": "राही को पूरे इलाके में चलाते रहिए",
    "Customer": "ग्राहक", "Driver": "ड्राइवर", "Admin": "एडमिन", "Account type": "खाते का प्रकार",
    "Show": "दिखाएं", "Hide": "छिपाएं", "Show password": "पासवर्ड दिखाएं",
    "Swap": "बदलें", "left": "बाकी", "Book again": "फिर बुक करें",
    "Finding": "खोज", "Coming": "आ रहा", "Arrived": "पहुंचा", "On trip": "यात्रा", "Done": "पूरी",
    "Popular destinations": "लोकप्रिय जगहें", "Price comparison": "किराये की तुलना",
    "Confirmed fare": "पक्का किराया", "Estimate": "अनुमान", "Our pick": "हमारा सुझाव",
    "Check real fare": "असली किराया देखें",
    "Connecting to Raahi…": "राही से जुड़ रहे हैं…",
    "The server is waking up. You stay signed in.": "सर्वर चालू हो रहा है। आप साइन इन रहेंगे।",
    "Your ride is in progress": "आपकी राइड जारी है",
    "Forgot password": "पासवर्ड भूल गए", "Forgot password?": "पासवर्ड भूल गए?", "Set a new password": "नया पासवर्ड बनाएं",
    "Email me a code": "ईमेल पर कोड भेजें", "Save new password": "नया पासवर्ड सेव करें",
    "Email (for password reset)": "ईमेल (पासवर्ड रीसेट के लिए)", "Code from your email": "ईमेल में आया कोड",
    "New password": "नया पासवर्ड", "Back to log in": "लॉग इन पर वापस", "Didn't get it? Send a new code": "कोड नहीं मिला? नया कोड भेजें",
    "Enter your mobile number. We will email a 6-digit code to the address on your account.":
      "अपना मोबाइल नंबर डालें। हम आपके खाते के ईमेल पर 6 अंकों का कोड भेजेंगे।",
    "Account created. Log in with your mobile number and password.": "खाता बन गया। अपने मोबाइल नंबर और पासवर्ड से लॉग इन करें।",
    "Password changed. Log in with your new password.": "पासवर्ड बदल गया। नए पासवर्ड से लॉग इन करें।",
    "Help": "मदद", "Help during your ride": "राइड के दौरान मदद", "Emergency numbers and Raahi support": "आपातकालीन नंबर और राही सपोर्ट",
    "Close help": "मदद बंद करें", "Police & emergency": "पुलिस और आपातकाल", "Ambulance": "एम्बुलेंस", "Women helpline": "महिला हेल्पलाइन",
    "Share trip details": "यात्रा की जानकारी भेजें", "Ask the assistant": "असिस्टेंट से पूछें", "Report a problem": "समस्या बताएं",
    "I feel unsafe": "मैं असुरक्षित महसूस कर रहा/रही हूं", "Problem with the driver": "ड्राइवर से समस्या", "Problem with the rider": "सवारी से समस्या",
    "Wrong route or stop": "गलत रास्ता या जगह", "Vehicle problem or breakdown": "गाड़ी खराब या समस्या", "Fare or payment": "किराया या भुगतान",
    "Something else": "कुछ और", "Add details (optional)": "जानकारी लिखें (वैकल्पिक)", "Send to Raahi support": "राही सपोर्ट को भेजें",
    "Sending…": "भेज रहे हैं…", "Raahi support has your request and will contact you shortly.": "राही सपोर्ट को आपका अनुरोध मिल गया है, वे जल्द संपर्क करेंगे।",
    "Trip details copied. Paste them to someone you trust.": "यात्रा की जानकारी कॉपी हो गई। इसे किसी भरोसेमंद को भेजें।",
    "Estimates use assumed rates, not live Rapido or Uber prices, and exclude their surge.":
      "अनुमान मानी गई दरों पर हैं, Rapido या Uber के लाइव किराये नहीं, और इनमें उनका सर्ज शामिल नहीं।",
  },
};

const STEP_NAMES = { searching: "Finding", accepted: "Coming", arrived: "Arrived", in_progress: "On trip", completed: "Done" };
const REGION_PHOTO = { JMU: "raghunath-temple", KSH: "dal-lake", HIL: "patnitop" };
let PHOTOS = [];

const lang = () => localStorage.getItem(LANG_KEY) || "en";
const t = text => (STRINGS[lang()] && STRINGS[lang()][text]) || text;
const rupees = n => "₹" + Math.round(n).toLocaleString("en-IN");
const $ = id => document.getElementById(id);

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value !== undefined && value !== null && value !== false) {
      if (key in node && key !== "list") node[key] = value;
      else node.setAttribute(key, value);
    }
  }
  return fill(node, ...children);
}

// replaceChildren would print a skipped `condition && el(...)` as the word "false".
function fill(node, ...children) {
  node.replaceChildren(...children.flat().filter(c => c !== null && c !== undefined && c !== false));
  return node;
}

const token = () => SESSION.getItem(TOKEN_KEY);

// Who is signed in on this device, for this app. Only a 401 means "signed out": a server
// that is still waking up (Render's free plan takes up to a minute) or a dropped mobile
// connection must not throw the user back to the login page with a valid session.
async function signedInUser(role) {
  if (!token()) return null;
  const note = $("auth-form");
  for (let attempt = 0; attempt < 40; attempt++) {
    try {
      const response = await fetch("/api/me", { headers: { Authorization: "Bearer " + token() } });
      if (response.status === 401) { SESSION.removeItem(TOKEN_KEY); return null; }
      if (response.ok) {
        const me = await response.json();
        return me.role === role ? me : null;
      }
    } catch { /* offline or server starting: wait and try again */ }
    if (note) fill(note, el("div", { class: "center stack" }, el("div", { class: "status pulse" }, t("Connecting to Raahi…")),
      el("div", { class: "muted" }, t("The server is waking up. You stay signed in."))));
    await new Promise(resolve => setTimeout(resolve, 3000));
  }
  return null;
}

// In-app screens get their own browser history entries, so the phone's Back button steps
// back inside the app (fares -> booking) instead of leaving it.
let backHandler = null;
function goScreen(name, { replace = false } = {}) {
  if (!replace && history.state && history.state.screen === name) return;
  history[replace ? "replaceState" : "pushState"]({ screen: name }, "");
}
const onBack = handler => { backHandler = handler; };
addEventListener("popstate", event => { if (backHandler) backHandler((event.state && event.state.screen) || null); });

async function loadPhotos() {
  PHOTOS = await fetch("/static/photos/photos.json").then(r => r.json()).catch(() => []);
}

const photoById = id => PHOTOS.find(p => p.id === id);
const photoFor = (placeName, region) => PHOTOS.find(p => p.place === placeName) || photoById(REGION_PHOTO[region]);
const formatMinutes = m => m >= 60 ? `${Math.floor(m / 60)} h ${Math.round(m % 60)} min` : `${Math.max(Math.round(m), 1)} min`;
const weatherIcon = w => ({ Clear: "☀️", Cloudy: "☁️", Rainy: "🌧️", Stormy: "⛈️", Snowy: "❄️" }[w] || "");

// These licences require naming the author and licence wherever a photo appears.
function creditLink(photo) {
  return el("a", { class: "credit", href: photo.source, target: "_blank", rel: "noopener noreferrer" },
    `Photo: ${photo.artist}, ${photo.license}`);
}

function photoBanner(photo, title) {
  if (!photo) return null;
  return el("div", { class: "banner-photo", style: `background-image:url('${photo.src}')`, role: "img", "aria-label": photo.title },
    el("div", { class: "banner-text" }, el("strong", {}, title || photo.title),
      // A fallback photo must not pass as a picture of the place named above it.
      title && !title.includes(photo.title) && photo.place !== title && el("span", { class: "credit" }, `Pictured: ${photo.title}`),
      creditLink(photo)));
}

function toast(message) {
  let host = $("toasts");
  if (!host) {
    host = el("div", { id: "toasts", "aria-live": "polite" });
    document.body.append(host);
  }
  const node = el("div", { class: "toast" }, message);
  host.append(node);
  setTimeout(() => node.remove(), 3500);
}

function countUp(node, target) {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const started = performance.now(), from = Math.round(target * 0.7);
  const frame = now => {
    const t01 = Math.min((now - started) / 500, 1);
    node.textContent = rupees(from + (target - from) * (1 - (1 - t01) ** 3));
    if (t01 < 1) requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

const AUTH_PHOTOS = ["bahu-fort", "krimchi-temples", "shiv-khori", "mansar-lake", "patnitop", "dal-lake", "gulmarg"];
const AUTH_SLIDE_MS = 6000;
let authTimer = null;

// The login page's background: J&K photos fading into one another, each with its credit.
function showAuthPhoto(first) {
  const photos = [first, ...AUTH_PHOTOS.filter(id => id !== first)].map(photoById).filter(Boolean);
  if (!photos.length) return;
  const slides = photos.map(photo => el("div", { class: "auth-slide", style: `background-image:url('${photo.src}')` }));
  $("auth").prepend(...slides);
  document.body.classList.add("auth-page");
  let index = 0;
  const show = () => {
    slides.forEach((slide, i) => slide.classList.toggle("on", i === index));
    fill($("auth-credit"), `${photos[index].title} · `, creditLink(photos[index]));
  };
  show();
  if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
    authTimer = setInterval(() => { index = (index + 1) % photos.length; show(); }, AUTH_SLIDE_MS);
  }
}

function hideAuth() {
  clearInterval(authTimer);
  document.body.classList.remove("auth-page");
  $("auth").classList.add("hidden");
}

const AUTH_ROLES = [["rider", "/ride", "Customer"], ["driver", "/driver", "Driver"], ["admin", "/admin", "Admin"]];
const AUTH_LINES = {
  rider: "Your ride across Jammu & Kashmir, in your own language.",
  driver: "Go online and start earning across Jammu & Kashmir.",
  admin: "Run fares and conditions across Jammu & Kashmir.",
};
const AUTH_HEADLINES = {
  rider: "From Jammu's temples to Kashmir's meadows",
  driver: "Drive every road of Jammu & Kashmir",
  admin: "Keep Raahi moving across the valley",
};

function authHero(role) {
  return el("div", { class: "auth-hero" },
    el("a", { class: "brand", href: "/" }, "Raahi"),
    el("h1", {}, t(AUTH_HEADLINES[role])),
    el("p", {}, t(AUTH_LINES[role])));
}

function passwordField(input) {
  const toggle = el("button", {
    type: "button", class: "password-toggle", "aria-label": t("Show password"), "aria-pressed": "false",
    onclick: () => {
      const showing = input.type === "text";
      input.type = showing ? "password" : "text";
      toggle.textContent = showing ? t("Show") : t("Hide");
      toggle.setAttribute("aria-pressed", String(!showing));
    },
  }, t("Show"));
  return el("div", { class: "password-field" }, input, toggle);
}

async function api(path, { method = "GET", body } = {}) {
  let response;
  try {
    response = await fetch("/api" + path, {
      method,
      headers: { "Content-Type": "application/json", ...(token() ? { Authorization: "Bearer " + token() } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error(t("You are offline. Fares and booking need a connection."));
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && token() && path !== "/login") {
      SESSION.removeItem(TOKEN_KEY);
      location.reload();
    }
    const detail = data && data.detail;
    throw new Error(typeof detail === "string" ? detail
      : Array.isArray(detail) ? detail[0].msg : "Something went wrong. Please try again.");
  }
  return data;
}

function connectLive(onEvent) {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  let socket, ping;
  const open = () => {
    socket = new WebSocket(`${scheme}://${location.host}/api/ws?token=${encodeURIComponent(token())}`);
    socket.onmessage = e => onEvent(JSON.parse(e.data));
    socket.onopen = () => { ping = setInterval(() => socket.send("ping"), 25000); onEvent({ type: "connected" }); };
    socket.onclose = () => { clearInterval(ping); setTimeout(open, 3000); };
  };
  open();
}

// A routed path follows the road and has many points; an estimate is a few straight legs.
const routeStyle = path => path && path.length > 4
  ? { color: "#111111", weight: 5, opacity: .9, lineCap: "round", lineJoin: "round" }
  : { color: "#111111", weight: 4, dashArray: "2 8", lineCap: "round" };

function makeMap(center = [33.6, 74.9], zoom = 8) {
  const map = L.map("map").setView(center, zoom);
  // OpenStreetMap's free standard tiles, toned down in app.css so roads and the route line
  // stand out the way they do in a ride app.
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);
  return map;
}

function setupShell(title) {
  const update = () => $("offline").classList.toggle("hidden", navigator.onLine);
  $("offline").textContent = t("You are offline. Fares and booking need a connection.");
  addEventListener("online", update);
  addEventListener("offline", update);
  update();
  $("title").textContent = title;
  $("lang").textContent = lang() === "en" ? "हिंदी" : "English";
  $("lang").onclick = () => { localStorage.setItem(LANG_KEY, lang() === "en" ? "hi" : "en"); location.reload(); };
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
}

function showLogout() {
  $("logout").textContent = t("Log out");
  $("logout").classList.remove("hidden");
  $("logout").onclick = () => { SESSION.removeItem(TOKEN_KEY); location.reload(); };
}

// role: the account type this page is for. extraFields: inputs shown only on sign-up.
// Modes: log in, create an account, ask for a reset code, set a new password with the code.
// Creating an account or a new password never signs in: the user logs in with it next.
const AUTH_TITLES = { login: "Log in", signup: "Create account", forgot: "Forgot password", reset: "Set a new password" };
const AUTH_BUTTONS = { login: "Log in", signup: "Create account", forgot: "Email me a code", reset: "Save new password" };

function renderAuth(root, role, onDone, extraFields = () => []) {
  let mode = "login", note = "", phoneValue = "";
  const canReset = role !== "admin";
  root.parentElement.insertBefore(authHero(role), root);
  let switched = false;
  const go = (next, message = "") => { mode = next; note = message; switched = true; draw(); };

  const draw = () => {
    root.replaceChildren();
    const error = el("div", { class: "error", role: "alert" });
    const name = el("input", { id: "auth-name", autocomplete: "name", required: true, minLength: 2 });
    const email = el("input", { id: "auth-email", type: "email", autocomplete: "email", required: true, maxLength: 254, placeholder: "name@gmail.com" });
    const phone = el("input", { id: "auth-phone", inputMode: "numeric", autocomplete: "tel-national", pattern: "[6-9][0-9]{9}", required: true, maxLength: 10, placeholder: "9xxxxxxxxx", value: phoneValue });
    const choosing = mode === "signup" || mode === "reset";
    const password = el("input", { id: "auth-password", type: "password", required: true, minLength: choosing ? 8 : 1, autocomplete: choosing ? "new-password" : "current-password" });
    const code = el("input", { id: "auth-code", inputMode: "numeric", autocomplete: "one-time-code", pattern: "[0-9]{6}", required: true, maxLength: 6, placeholder: "6-digit code" });
    const extras = mode === "signup" ? extraFields() : [];
    const submit = el("button", { type: "submit" }, t(AUTH_BUTTONS[mode]));

    const send = async () => {
      phoneValue = phone.value;
      if (mode === "login") {
        const result = await api("/login", { method: "POST", body: { phone: phone.value, password: password.value, role } });
        SESSION.setItem(TOKEN_KEY, result.token);
        onDone(result.user);
      } else if (mode === "signup") {
        const result = await api("/register", { method: "POST", body: {
          phone: phone.value, name: name.value, email: email.value, password: password.value, role,
          ...Object.fromEntries(extras.map(x => [x.key, x.input.value])) } });
        go("login", result.message);
      } else if (mode === "forgot") {
        go("reset", (await api("/password/forgot", { method: "POST", body: { phone: phone.value, role } })).message);
      } else {
        const result = await api("/password/reset", { method: "POST", body: { phone: phone.value, role, code: code.value, password: password.value } });
        go("login", result.message);
      }
    };

    const field = (id, label, input) => el("div", {}, el("label", { htmlFor: id }, t(label)), input);
    const form = el("form", {
      class: "center stack",
      onsubmit: async event => {
        event.preventDefault();
        error.textContent = "";
        submit.disabled = true;
        try { await send(); } catch (e) { error.textContent = e.message; } finally { submit.disabled = false; }
      },
    },
      (mode === "login" || mode === "signup") && el("nav", { class: "auth-roles", "aria-label": t("Account type") }, AUTH_ROLES.map(([key, href, label]) =>
        el("a", { href, class: key === role ? "on" : "", "aria-current": key === role ? "page" : null }, t(label)))),
      el("h2", {}, t(AUTH_TITLES[mode])),
      note && el("div", { class: "auth-note", role: "status" }, t(note)),
      mode === "forgot" && el("p", { class: "muted" }, t("Enter your mobile number. We will email a 6-digit code to the address on your account.")),
      mode === "signup" && field("auth-name", "Your name", name),
      field("auth-phone", "Mobile number", el("div", { class: "phone-field" }, el("span", {}, "+91"), phone)),
      mode === "signup" && field("auth-email", "Email (for password reset)", email),
      mode === "reset" && field("auth-code", "Code from your email", code),
      mode !== "forgot" && field("auth-password", mode === "reset" ? "New password" : "Password", passwordField(password)),
      mode === "login" && canReset && el("button", { type: "button", class: "linkish forgot-link", onclick: () => go("forgot") }, t("Forgot password?")),
      extras.map(x => el("div", {}, el("label", { htmlFor: x.input.id }, x.label), x.input)),
      error,
      submit,
      mode === "login" && role !== "admin" && el("button", { type: "button", class: "linkish", onclick: () => go("signup") }, t("New here? Create an account")),
      mode === "signup" && el("button", { type: "button", class: "linkish", onclick: () => go("login") }, t("Have an account? Log in")),
      (mode === "forgot" || mode === "reset") && el("div", { class: "auth-links" },
        mode === "reset" && el("button", { type: "button", class: "linkish", onclick: () => go("forgot") }, t("Didn't get it? Send a new code")),
        el("button", { type: "button", class: "linkish", onclick: () => go("login") }, t("Back to log in"))),
    );
    root.append(form);
    // Move focus only after a switch between modes, not on page load (it would open the phone keyboard).
    if (switched) (mode === "reset" ? code : mode === "signup" ? name : phone.value ? password : phone).focus({ preventScroll: true });
  };
  draw();
}

const STATUS_TEXT = {
  searching: "Finding a driver…", accepted: "Driver is on the way", arrived: "Driver has arrived",
  in_progress: "On the trip", completed: "Trip completed", cancelled: "Ride cancelled",
};

function renderChat(container, ride, viewerRole) {
  const log = el("div", { class: "chat", "aria-live": "polite" });
  const input = el("input", { placeholder: t("Message"), maxLength: 500, "aria-label": t("Message") });
  const form = el("form", {
    class: "row",
    onsubmit: async event => {
      event.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      await api(`/rides/${ride.id}/messages`, { method: "POST", body: { body: text } }).catch(e => toast(e.message));
    },
  }, input, el("button", { type: "submit", style: "flex:0 0 80px" }, t("Send")));
  container.replaceChildren(log, form);

  const add = message => {
    log.append(el("div", { class: "msg" + (message.sender === viewerRole ? " mine" : "") }, message.body));
    log.scrollTop = log.scrollHeight;
  };
  api(`/rides/${ride.id}/messages`).then(list => list.forEach(add)).catch(() => {});
  return add;
}

// ---------- help during a ride
// A red Help button stays on screen while a ride is live. It offers emergency numbers,
// sharing the trip with someone, and a report to Raahi support that admins see at once.
const HELP_TOPICS = {
  rider: [["safety", "I feel unsafe"], ["driver", "Problem with the driver"], ["route", "Wrong route or stop"],
          ["vehicle", "Vehicle problem or breakdown"], ["payment", "Fare or payment"], ["other", "Something else"]],
  driver: [["safety", "I feel unsafe"], ["rider", "Problem with the rider"], ["route", "Wrong route or stop"],
           ["vehicle", "Vehicle problem or breakdown"], ["payment", "Fare or payment"], ["other", "Something else"]],
};
const HELP_STATUSES = ["searching", "accepted", "arrived", "in_progress"];
const EMERGENCY_NUMBERS = [["112", "Police & emergency", true], ["108", "Ambulance", false], ["1091", "Women helpline", false]];
let helpRide = null, helpRole = "rider", helpUi = null;

// Call with the current ride whenever it changes, or null when there is none.
function updateRideHelp(ride, role) {
  helpRide = ride && HELP_STATUSES.includes(ride.status) ? ride : null;
  if (role) helpRole = role;
  if (!helpUi) helpUi = buildRideHelp();
  helpUi.opener.classList.toggle("hidden", !helpRide);
  helpUi.opener.classList.toggle("below-assistant", !!$("assistant-open"));
  if (!helpRide) helpUi.close();
}

const placeLabel = p => (p && p.name) || "Map pin";

async function shareTrip() {
  const r = helpRide;
  if (!r) return;
  const other = helpRole === "rider" ? r.driver : r.rider;
  const text = [`I'm on a Raahi ride: ${placeLabel(r.pickup)} → ${placeLabel(r.dropoff)}.`,
    other && `${helpRole === "rider" ? "Driver" : "Rider"}: ${other.name}${other.phone ? ` (+91 ${other.phone})` : ""}.`,
    `${r.quote.label} · ${rupees(r.fare)} · ride #${r.id}.`].filter(Boolean).join(" ");
  try {
    if (navigator.share) await navigator.share({ title: "My Raahi ride", text });
    else { await navigator.clipboard.writeText(text); toast(t("Trip details copied. Paste them to someone you trust.")); }
  } catch (e) {
    if (e.name !== "AbortError") toast(text);
  }
}

// The location helps support find the vehicle. It is optional and never blocks the request.
const currentPosition = () => new Promise(resolve => {
  if (!navigator.geolocation) return resolve(null);
  navigator.geolocation.getCurrentPosition(p => resolve({ lat: p.coords.latitude, lon: p.coords.longitude }),
    () => resolve(null), { timeout: 4000, maximumAge: 60000 });
});

function buildRideHelp() {
  const sheet = el("section", { id: "help-sheet", class: "help-sheet hidden", role: "dialog", "aria-labelledby": "help-title" });
  const opener = el("button", {
    id: "help-open", type: "button", class: "help-open hidden", "aria-label": t("Help during your ride"),
    onclick: () => open(),
  }, el("span", { "aria-hidden": "true" }, "🆘"), " ", t("Help"));
  document.body.append(sheet, opener);

  const close = () => sheet.classList.add("hidden");
  addEventListener("keydown", event => { if (event.key === "Escape" && !sheet.classList.contains("hidden")) close(); });

  function open() {
    draw();
    sheet.classList.remove("hidden");
    sheet.querySelector("a, button").focus();
  }

  function draw() {
    let topic = null;
    const status = el("div", { class: "help-status", role: "status" });
    const note = el("textarea", { id: "help-note", rows: 2, maxLength: 500, placeholder: t("Add details (optional)"), "aria-label": t("Add details (optional)") });
    const sendButton = el("button", { type: "button", disabled: true, onclick: async () => {
      sendButton.disabled = true;
      status.className = "help-status";
      status.textContent = t("Sending…");
      try {
        const where = await currentPosition();
        const result = await api(`/rides/${helpRide.id}/help`, { method: "POST", body: { topic, note: note.value, ...(where || {}) } });
        status.className = "help-status sent";
        status.textContent = "✓ " + t(result.message);
        note.value = "";
      } catch (e) {
        status.className = "help-status error";
        status.textContent = e.message;
      } finally { sendButton.disabled = !topic; }
    } }, t("Send to Raahi support"));
    const topics = HELP_TOPICS[helpRole].map(([key, label]) => el("button", {
      type: "button", class: "chip", "aria-pressed": "false",
      onclick: event => {
        topic = key;
        topics.forEach(b => b.setAttribute("aria-pressed", String(b === event.currentTarget)));
        topics.forEach(b => b.classList.toggle("on", b === event.currentTarget));
        sendButton.disabled = false;
      },
    }, t(label)));

    fill(sheet,
      el("header", { class: "assistant-head" },
        el("div", {}, el("strong", { id: "help-title" }, t("Help during your ride")),
          el("div", { class: "muted" }, t("Emergency numbers and Raahi support"))),
        el("button", { type: "button", class: "assistant-close", "aria-label": t("Close help"), onclick: close }, "×")),
      el("div", { class: "help-body stack" },
        el("div", { class: "help-calls" }, EMERGENCY_NUMBERS.map(([number, label, urgent]) =>
          el("a", { class: "help-call" + (urgent ? " urgent" : ""), href: `tel:${number}` },
            el("strong", {}, number), el("span", {}, t(label))))),
        el("div", { class: "row" },
          el("button", { type: "button", class: "secondary", onclick: shareTrip }, t("Share trip details")),
          helpRole === "rider" && $("assistant-open") && el("button", { type: "button", class: "secondary", onclick: () => {
            close();
            $("assistant-open").click();
          } }, t("Ask the assistant"))),
        el("h3", {}, t("Report a problem")),
        el("div", { class: "help-topics" }, topics),
        note, sendButton, status));
  }

  return { opener, close };
}
