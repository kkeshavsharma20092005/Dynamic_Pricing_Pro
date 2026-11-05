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
    "Your ride is confirmed": "आपकी राइड पक्की हो गई", "accepted your ride and is on the way.": "ने आपकी राइड स्वीकार की है और आ रहे हैं।",
    "Call driver": "ड्राइवर को कॉल करें", "Got it": "ठीक है", "away": "दूर", "Trip": "यात्रा",
    "Fare": "किराया", "Distance": "दूरी", "Ride": "राइड",
    "Payment received": "भुगतान मिल गया", "Cash": "नकद", "QR payment (demo)": "QR भुगतान (डेमो)", "Pay": "भुगतान करें",
    "Demo": "डेमो", "QR code to pay for this ride": "इस राइड का भुगतान करने के लिए QR कोड",
    "Scan with your phone camera or Google Lens to pay": "भुगतान के लिए फ़ोन कैमरा या Google Lens से स्कैन करें",
    "Demo payment: no real money is charged.": "डेमो भुगतान: कोई असली पैसा नहीं कटता।",
    "Open payment page": "भुगतान पेज खोलें", "Cash received": "नकद मिल गया",
    "Thank you! Your ride is paid.": "धन्यवाद! आपकी राइड का भुगतान हो गया।", "Continue": "आगे बढ़ें",
    "Waiting for your payment…": "आपके भुगतान का इंतज़ार…", "Scan the QR code on your driver's phone to pay": "भुगतान के लिए ड्राइवर के फ़ोन पर QR कोड स्कैन करें",
    "Or pay cash to the driver.": "या ड्राइवर को नकद दें।", "Show this QR to the rider to collect the fare": "किराया लेने के लिए यह QR सवारी को दिखाएं",
    "How was your ride with": "आपकी राइड कैसी रही,", "Tap a star to rate": "रेटिंग देने के लिए स्टार दबाएं",
    "Terrible": "बहुत खराब", "Bad": "खराब", "Okay": "ठीक-ठाक", "Good": "अच्छी", "Excellent": "बहुत बढ़िया",
    "of 5 stars": "/ 5 स्टार", "Your rating": "आपकी रेटिंग", "Tell us more (optional)": "और बताएं (वैकल्पिक)",
    "Submit feedback": "फ़ीडबैक भेजें", "Skip": "छोड़ें", "Feedback is optional.": "फ़ीडबैक देना ज़रूरी नहीं है।",
    "Thank you for your feedback!": "आपके फ़ीडबैक के लिए धन्यवाद!", "It helps us keep Raahi rides safe and comfortable.": "इससे हम राही की राइड सुरक्षित और आरामदायक रखते हैं।",
    "Rate this trip": "इस यात्रा को रेटिंग दें", "Thanks for rating this trip": "रेटिंग देने के लिए धन्यवाद",
    "Safe driving": "सुरक्षित ड्राइविंग", "Polite driver": "विनम्र ड्राइवर", "Clean vehicle": "साफ़ गाड़ी", "On time": "समय पर",
    "Good route": "अच्छा रास्ता", "Driver was late": "ड्राइवर देर से आया", "Rash driving": "लापरवाह ड्राइविंग",
    "Rude behaviour": "बुरा व्यवहार", "Vehicle not clean": "गाड़ी साफ़ नहीं थी", "Fare issue": "किराये की समस्या",
    "Bike": "बाइक", "E-rickshaw": "ई-रिक्शा", "Auto": "ऑटो", "Cab": "कैब", "Shared cab (per seat)": "शेयर्ड कैब (प्रति सीट)",
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
    "One quick question": "एक छोटा सा सवाल", "How do you identify?": "आप खुद को क्या मानते हैं?",
    "Woman": "महिला", "Man": "पुरुष", "Other": "अन्य", "Prefer not to say": "बताना नहीं चाहते",
    "Women riders can turn on Women Raahi and ride only with women drivers.":
      "महिला सवारी Women Raahi चालू करके सिर्फ़ महिला ड्राइवरों के साथ यात्रा कर सकती हैं।",
    "Women drivers also get Women Raahi rides, booked by women who want a woman driver.":
      "महिला ड्राइवरों को Women Raahi राइड भी मिलती हैं, जो महिला ड्राइवर चाहने वाली महिलाएं बुक करती हैं।",
    "To change this later, contact Raahi support.": "बाद में बदलने के लिए राही सपोर्ट से संपर्क करें।",
    "Women Raahi": "Women Raahi", "Only women drivers": "सिर्फ़ महिला ड्राइवर",
    "On: your rides go only to women drivers": "चालू: आपकी राइड सिर्फ़ महिला ड्राइवरों को जाएगी",
    "Tap to ride only with women drivers": "सिर्फ़ महिला ड्राइवरों के साथ जाने के लिए टैप करें",
    "Finding a woman driver…": "महिला ड्राइवर खोज रहे हैं…",
    "Women Raahi is on": "Women Raahi चालू है", "Women Raahi is off": "Women Raahi बंद है",
    "Your ID is being checked": "आपकी आईडी की जांच हो रही है",
    "You can go online as soon as it is approved. We will tell you here.": "मंज़ूरी मिलते ही आप ऑनलाइन जा सकेंगे। हम आपको यहीं बताएंगे।",
    "Women Raahi turns on as soon as it is approved. We will tell you here.": "मंज़ूरी मिलते ही Women Raahi चालू हो जाएगा। हम आपको यहीं बताएंगे।",
    "Verify your ID to start driving": "ड्राइविंग शुरू करने के लिए आईडी वेरिफ़ाई करें",
    "Verify your ID for Women Raahi": "Women Raahi के लिए आईडी वेरिफ़ाई करें",
    "Every Raahi driver is checked before their first ride.": "हर राही ड्राइवर की पहली राइड से पहले जांच होती है।",
    "So that Women Raahi stays only for women, we check an ID once.": "Women Raahi सिर्फ़ महिलाओं के लिए रहे, इसलिए हम एक बार आईडी जांचते हैं।",
    "Your last request was not approved:": "आपका पिछला अनुरोध मंज़ूर नहीं हुआ:",
    "ID document": "आईडी दस्तावेज़", "Aadhaar (masked)": "आधार (मास्क्ड)", "Voter ID": "वोटर आईडी", "Passport": "पासपोर्ट", "Driving licence": "ड्राइविंग लाइसेंस",
    "For Aadhaar, upload the masked Aadhaar, with only the last 4 digits showing.": "आधार के लिए मास्क्ड आधार अपलोड करें, जिसमें सिर्फ़ आख़िरी 4 अंक दिखें।",
    "Photo of your vehicle's RC": "आपकी गाड़ी की आरसी की फ़ोटो",
    "The registration certificate. Its number must match the plate above.": "रजिस्ट्रेशन सर्टिफ़िकेट। इसका नंबर ऊपर दिए नंबर प्लेट से मेल खाना चाहिए।",
    "Photo of your ID": "आपकी आईडी की फ़ोटो", "Photo of your driving licence": "आपके ड्राइविंग लाइसेंस की फ़ोटो",
    "A selfie": "एक सेल्फ़ी", "Your face, clearly, in good light.": "आपका चेहरा, साफ़ और अच्छी रोशनी में।",
    "I agree that Raahi checks these documents. They are deleted as soon as the check is done.":
      "मैं सहमत हूं कि राही इन दस्तावेज़ों की जांच करे। जांच पूरी होते ही इन्हें हटा दिया जाता है।",
    "Vehicle number plate": "गाड़ी का नंबर प्लेट", "As painted on your vehicle.": "जैसा आपकी गाड़ी पर लिखा है।",
    "Enter your vehicle's number plate, like JK02 AB 1234.": "अपनी गाड़ी का नंबर डालें, जैसे JK02 AB 1234।",
    "Check the number plate before you get in": "बैठने से पहले नंबर प्लेट जांच लें",
    "Thank you for submitting your documents": "दस्तावेज़ भेजने के लिए धन्यवाद",
    "We will tell you the result by email and SMS:": "हम आपको नतीजा ईमेल और SMS से बताएंगे:",
    "We will tell you the result by SMS and here in the app.": "हम आपको नतीजा SMS से और यहीं ऐप में बताएंगे।",
    "It usually takes a few hours.": "आम तौर पर इसमें कुछ घंटे लगते हैं।", "OK": "ठीक है",
    "Thank you for registering with Raahi": "राही के साथ रजिस्टर करने के लिए धन्यवाद",
    "You are approved as a Raahi driver.": "आप राही ड्राइवर के रूप में मंज़ूर हो गए हैं।",
    "You can now drive with Raahi.": "अब आप राही के साथ गाड़ी चला सकते हैं।",
    "Your vehicle": "आपकी गाड़ी", "Start driving": "ड्राइविंग शुरू करें",
    "Choose your location and tap Go online to start getting rides.": "अपनी लोकेशन चुनें और राइड पाने के लिए ऑनलाइन जाएं पर टैप करें।",
    "We have also sent this to": "हमने यह जानकारी यहां भी भेजी है:",
    "Send for checking": "जांच के लिए भेजें", "Add all the photos first.": "पहले सभी फ़ोटो जोड़ें।",
    "That photo could not be read. Try another.": "यह फ़ोटो पढ़ी नहीं जा सकी। दूसरी आज़माएं।",
    "Verify your ID once to turn this on": "इसे चालू करने के लिए एक बार आईडी वेरिफ़ाई करें",
    "ID check pending. It turns on once approved.": "आईडी जांच बाकी है। मंज़ूरी के बाद चालू होगा।",
    "You are verified. Women Raahi is ready.": "आप वेरिफ़ाइड हैं। Women Raahi तैयार है।",
    "You are verified. You can go online now.": "आप वेरिफ़ाइड हैं। अब आप ऑनलाइन जा सकते हैं।",
    "Your ID check was not approved.": "आपकी आईडी जांच मंज़ूर नहीं हुई।", "Close": "बंद करें",
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

// ---------- gender, asked once after the first login
// Women Raahi needs it: women riders can ask for women drivers only, and only drivers who
// said they are women get those rides. Saved once; changing it goes through support.
const GENDER_CHOICES = [["female", "Woman"], ["male", "Man"], ["other", "Other"], ["unspecified", "Prefer not to say"]];

function askGender(user) {
  if (user.gender || user.role === "admin") return Promise.resolve(user);
  return new Promise(resolve => {
    const error = el("div", { class: "error", role: "alert" });
    const choose = async (gender, button) => {
      error.textContent = "";
      sheet.querySelectorAll("button").forEach(b => { b.disabled = true; });
      try {
        const saved = await api("/me/gender", { method: "POST", body: { gender } });
        sheet.remove();
        resolve(saved);
      } catch (e) {
        error.textContent = e.message;
        sheet.querySelectorAll("button").forEach(b => { b.disabled = false; });
        button.focus();
      }
    };
    const sheet = el("div", { class: "gender-backdrop" },
      el("section", { class: "gender-sheet stack", role: "dialog", "aria-modal": "true", "aria-labelledby": "gender-title" },
        el("div", { class: "muted" }, t("One quick question")),
        el("h2", { id: "gender-title" }, t("How do you identify?")),
        el("p", { class: "muted" }, t(user.role === "driver"
          ? "Women drivers also get Women Raahi rides, booked by women who want a woman driver."
          : "Women riders can turn on Women Raahi and ride only with women drivers.")),
        el("div", { class: "gender-choices" }, GENDER_CHOICES.map(([value, label]) =>
          el("button", { type: "button", class: value === "female" ? "gender-female" : "secondary",
                         onclick: event => choose(value, event.currentTarget) }, t(label)))),
        error,
        el("div", { class: "muted" }, t("To change this later, contact Raahi support."))));
    document.body.append(sheet);
    sheet.querySelector("button").focus();
  });
}

// ---------- ID check (KYC)
// Every driver, and every woman rider who turns on Women Raahi, uploads an ID and a selfie
// once. An admin reviews them; the images are deleted after the review.
const KYC_DOCUMENTS = [["aadhaar", "Aadhaar (masked)"], ["voter", "Voter ID"], ["passport", "Passport"], ["licence", "Driving licence"]];

// Phone photos are several MB. A 1280 px JPEG is plenty to read an ID, and uploads fast.
async function shrinkImage(file, max = 1280) {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, max / Math.max(bitmap.width, bitmap.height));
  const canvas = el("canvas", { width: Math.round(bitmap.width * scale), height: Math.round(bitmap.height * scale) });
  canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.82);
}

// Shown once the documents are sent: what happens next, and where the answer will arrive.
function kycThanks(user) {
  const close = () => { sheet.remove(); };
  const ok = el("button", { type: "button", onclick: close }, t("OK"));
  const sheet = el("div", { class: "gender-backdrop", onclick: event => { if (event.target === sheet) close(); } },
    el("section", { class: "gender-sheet stack kyc-thanks", role: "alertdialog", "aria-modal": "true",
                    "aria-labelledby": "kyc-thanks-title", "aria-describedby": "kyc-thanks-body" },
      el("div", { class: "kyc-thanks-icon" + (user.role === "rider" ? " women" : ""), "aria-hidden": "true" }, "✓"),
      el("h2", { id: "kyc-thanks-title" }, t("Your ID is being checked")),
      el("div", { id: "kyc-thanks-body", class: "stack" },
        el("p", {}, t("Thank you for submitting your documents")),
        user.email
          ? el("p", { class: "muted" }, t("We will tell you the result by email and SMS:"), el("br"),
              el("strong", {}, user.email), el("br"), el("strong", {}, `+91 ${user.phone}`))
          : el("p", { class: "muted" }, t("We will tell you the result by SMS and here in the app."), " ", el("strong", {}, `+91 ${user.phone}`)),
        el("p", { class: "muted" }, t("It usually takes a few hours."))),
      ok));
  addEventListener("keydown", function onKey(event) {
    if (event.key === "Escape") { close(); removeEventListener("keydown", onKey); }
  });
  document.body.append(sheet);
  ok.focus();
}

function kycPanel(user, onSaved) {
  const driver = user.role === "driver";
  if (user.kyc === "pending") {
    return el("div", { class: "kyc stack" },
      el("div", { class: "status pulse", role: "status" }, t("Your ID is being checked")),
      el("p", { class: "muted" }, t(driver ? "You can go online as soon as it is approved. We will tell you here."
        : "Women Raahi turns on as soon as it is approved. We will tell you here.")));
  }
  const error = el("div", { class: "error", role: "alert" });
  const photos = {};
  const photoInput = (key, label, hint, capture) => {
    const preview = el("img", { class: "kyc-preview hidden", alt: "" });
    const input = el("input", { type: "file", accept: "image/*", capture, id: `kyc-${key}`, onchange: async () => {
      const file = input.files[0];
      if (!file) return;
      try {
        photos[key] = await shrinkImage(file);
        preview.src = photos[key];
        preview.classList.remove("hidden");
        error.textContent = "";
      } catch {
        delete photos[key];
        error.textContent = t("That photo could not be read. Try another.");
      }
    } });
    return el("div", { class: "kyc-photo" }, el("label", { htmlFor: input.id }, t(label)),
      hint && el("div", { class: "muted" }, t(hint)), input, preview);
  };
  const documentSelect = el("select", { id: "kyc-document" }, KYC_DOCUMENTS.map(([value, label]) => el("option", { value }, t(label))));
  const consent = el("input", { type: "checkbox", id: "kyc-consent" });
  const plate = el("input", { id: "kyc-plate", maxLength: 20, autocomplete: "off", autocapitalize: "characters",
                              placeholder: "JK02 AB 1234", value: user.plate || "", class: "plate-input" });
  const submit = el("button", { type: "submit" }, t("Send for checking"));
  const needed = driver ? ["id_image", "licence_image", "rc_image", "selfie"] : ["id_image", "selfie"];

  return el("form", { class: "kyc stack", onsubmit: async event => {
    event.preventDefault();
    error.textContent = "";
    if (driver && !/^[A-Za-z0-9 .-]{6,}$/.test(plate.value.trim())) {
      error.textContent = t("Enter your vehicle's number plate, like JK02 AB 1234.");
      plate.focus();
      return;
    }
    if (needed.some(key => !photos[key])) { error.textContent = t("Add all the photos first."); return; }
    submit.disabled = true;
    try {
      onSaved(await api("/kyc", { method: "POST", body: {
        document: documentSelect.value, id_image: photos.id_image, selfie: photos.selfie,
        licence_image: photos.licence_image || null, rc_image: photos.rc_image || null, plate: driver ? plate.value : null, consent: consent.checked } }));
    } catch (e) { error.textContent = e.message; } finally { submit.disabled = false; }
  } },
    el("h3", {}, t(driver ? "Verify your ID to start driving" : "Verify your ID for Women Raahi")),
    el("p", { class: "muted" }, t(driver ? "Every Raahi driver is checked before their first ride."
      : "So that Women Raahi stays only for women, we check an ID once.")),
    user.kyc === "rejected" && el("div", { class: "error", role: "alert" }, `${t("Your last request was not approved:")} ${user.kyc_note || ""}`),
    driver && el("div", {}, el("label", { htmlFor: "kyc-plate" }, t("Vehicle number plate")), plate,
      el("div", { class: "muted" }, t("As painted on your vehicle."))),
    el("div", {}, el("label", { htmlFor: "kyc-document" }, t("ID document")), documentSelect),
    el("div", { class: "muted" }, t("For Aadhaar, upload the masked Aadhaar, with only the last 4 digits showing.")),
    photoInput("id_image", "Photo of your ID", null, "environment"),
    driver && photoInput("licence_image", "Photo of your driving licence", null, "environment"),
    driver && photoInput("rc_image", "Photo of your vehicle's RC", "The registration certificate. Its number must match the plate above.", "environment"),
    photoInput("selfie", "A selfie", "Your face, clearly, in good light.", "user"),
    el("label", { class: "kyc-consent", htmlFor: "kyc-consent" }, consent,
      el("span", {}, t("I agree that Raahi checks these documents. They are deleted as soon as the check is done."))),
    error, submit);
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

// ---------- paying for a finished trip (demo)
// The QR opens Raahi's own payment page, not a UPI code, so scanning it never moves real money.
// Who shows the QR: with a real driver, the driver's phone (the rider scans it); with a demo
// driver there is no driver phone, so the rider's own screen shows it.
const paymentDue = r => !!(r && r.payment && r.payment.status === "due");
const qrOnThisScreen = (r, role) => role === "driver" || !!(r.driver && r.driver.simulated);

function paymentCard(ride, { role = "rider", onCash } = {}) {
  const p = ride.payment;
  if (!p) return null;
  if (p.status === "paid") {
    return el("div", { class: "pay-card paid", role: "status" },
      el("div", { class: "pay-tick", "aria-hidden": "true" }, "✓"),
      el("div", {}, el("strong", {}, t("Payment received")),
        el("div", { class: "muted" }, `${rupees(ride.fare)} · ${p.method === "cash" ? t("Cash") : t("QR payment (demo)")}`)));
  }
  if (!p.pay_path) return null;
  const head = el("div", { class: "pay-head" }, el("strong", {}, `${t("Pay")} ${rupees(ride.fare)}`), el("span", { class: "tag warn" }, t("Demo")));
  const demoNote = el("div", { class: "muted" }, t("Demo payment: no real money is charged."));
  if (!qrOnThisScreen(ride, role)) {
    // A real driver holds the QR: the rider scans it on the driver's phone.
    return el("div", { class: "pay-card" }, head,
      el("div", { class: "pay-wait" }, el("span", { class: "pay-spinner small", "aria-hidden": "true" }), t("Waiting for your payment…")),
      el("div", { class: "pay-hint" }, `📱 ${t("Scan the QR code on your driver's phone to pay")}`),
      el("div", { class: "muted" }, t("Or pay cash to the driver.")), demoNote);
  }
  return el("div", { class: "pay-card" }, head,
    el("img", { class: "pay-qr", src: `${p.pay_path}/qr.svg`, alt: t("QR code to pay for this ride"), width: 220, height: 220 }),
    el("div", { class: "pay-hint" }, role === "driver" ? t("Show this QR to the rider to collect the fare") : t("Scan with your phone camera or Google Lens to pay")),
    demoNote,
    el("a", { href: p.pay_path, target: "_blank", rel: "noopener", class: "linkish" }, t("Open payment page") + " ↗"),
    onCash && el("button", { type: "button", class: "secondary", onclick: onCash }, "💵 " + t("Cash received")));
}

function closePayment() {
  const open = $("pay-backdrop");
  if (open) open.remove();
}

// The trip has ended: a pop-up asks for the fare, with the QR where it belongs.
function openPayment(ride, role, options = {}) {
  closePayment();
  const card = paymentCard(ride, { role, ...options });
  if (!card) return;
  const backdrop = el("div", { id: "pay-backdrop", class: "confirm-backdrop", onclick: e => { if (e.target === backdrop) closePayment(); } },
    el("section", { class: "confirm-card", role: "dialog", "aria-modal": "true", "aria-labelledby": "pay-title" },
      el("div", { class: "confirm-head" },
        el("div", { class: "confirm-check", "aria-hidden": "true" }, "🏁"),
        el("h2", { id: "pay-title" }, t("Trip completed")),
        el("p", {}, `${placeLabel(ride.pickup)} → ${placeLabel(ride.dropoff)}`)),
      card,
      el("button", { type: "button", class: "confirm-action", onclick: closePayment }, t("Close"))));
  document.body.append(backdrop);
}

// Shown on both phones the moment the fare is paid. onDone runs when it closes.
function showPaymentReceived(ride, onDone) {
  closePayment();
  const old = $("paid-backdrop");
  if (old) old.remove();
  const method = ride.payment && ride.payment.method === "cash" ? t("Cash") : t("QR payment (demo)");
  let done = false;
  const next = () => { if (done) return; done = true; backdrop.remove(); if (onDone) onDone(); };
  const backdrop = el("div", { id: "paid-backdrop", class: "confirm-backdrop", onclick: e => { if (e.target === backdrop) next(); } },
    el("section", { class: "confirm-card", role: "alertdialog", "aria-labelledby": "paid-title" },
      el("div", { class: "confirm-head" },
        el("div", { class: "confirm-check", "aria-hidden": "true" }, "✓"),
        el("h2", { id: "paid-title" }, t("Payment received")),
        el("p", {}, `${rupees(ride.fare)} · ${method}`)),
      el("div", { class: "muted confirm-note" }, t("Thank you! Your ride is paid.")),
      el("button", { type: "button", class: "confirm-done", onclick: next }, t("Continue"))));
  document.body.append(backdrop);
  if (navigator.vibrate) navigator.vibrate(150);
  setTimeout(() => { if (backdrop.isConnected) next(); }, 3000);
}
