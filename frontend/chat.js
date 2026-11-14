// The booking assistant. It works in the rider app and drives the same map and trip screen.
const SPEECH_LANG = { en: "en-IN", hinglish: "hi-IN", hi: "hi-IN", ur: "ur-IN" };
const VOICE_LANGUAGES = [["en", "English"], ["hi", "हिंदी"], ["ur", "اردو"]];
// Only Sarvam hears these two, so they are offered once the server says Sarvam is on.
const SARVAM_ONLY_LANGUAGES = [["doi", "डोगरी"], ["ks", "کٲشُر"]];
const CHAT_EXAMPLES = ["Bharat Nagar to Roop Nagar", "मुझे मेरी लोकेशन से कटरा जाना है", "مجھے جموں سے کٹرہ جانا ہے", "Jammu ke mandir dikhao"];
const RECORD_LIMIT_MS = 15000;     // Sarvam's quick API takes up to 30 seconds; a request needs far less
const SILENCE_MS = 1400;           // this long a pause after speaking ends the recording
const NO_SPEECH_MS = 7000;         // give up if nothing is said for this long

// Two ways to listen and speak. With SARVAM_API_KEY set on the server, the app records the
// rider, the server sends the recording to Sarvam AI (Hindi, Urdu, Dogri, Kashmiri, English),
// and Sarvam reads Hindi and English replies aloud. Otherwise, or whenever Sarvam fails, the
// browser's own speech features are used, as before.
function makeVoice({ onInterim, onFinal, onState }) {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const canRecord = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
  const sarvam = { on: false, speaks: [] };
  let listening = null;
  let playing = null;

  // Cloud and neural voices sound far more like a person than the older local ones.
  function voiceFor(tag) {
    const prefix = tag.slice(0, 2);
    const score = v => (/natural|neural/i.test(v.name) ? 4 : 0) + (/online|google/i.test(v.name) ? 2 : 0)
      + (v.lang.replace("_", "-") === tag ? 1 : 0);
    return speechSynthesis.getVoices().filter(v => v.lang.startsWith(prefix)).sort((a, b) => score(b) - score(a))[0];
  }

  // Records until the rider stops talking, taps the mic again, or the time limit.
  async function record(langHint) {
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      toast("Please allow the microphone for this site.");
      return;
    }
    const recorder = new MediaRecorder(stream);
    const chunks = [];
    let heardSpeech = false;
    let quietSince = Date.now();
    const started = Date.now();
    const audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const analyser = audioContext.createAnalyser();
    audioContext.createMediaStreamSource(stream).connect(analyser);
    const samples = new Float32Array(analyser.fftSize);
    const stop = () => recorder.state === "recording" && recorder.stop();
    const watch = setInterval(() => {
      analyser.getFloatTimeDomainData(samples);
      const level = Math.sqrt(samples.reduce((sum, v) => sum + v * v, 0) / samples.length);
      const now = Date.now();
      if (level > 0.02) { heardSpeech = true; quietSince = now; }
      if ((heardSpeech && now - quietSince > SILENCE_MS) || (!heardSpeech && now - started > NO_SPEECH_MS)
          || now - started > RECORD_LIMIT_MS) stop();
    }, 100);
    recorder.ondataavailable = event => event.data.size && chunks.push(event.data);
    recorder.onstop = async () => {
      clearInterval(watch);
      stream.getTracks().forEach(track => track.stop());
      audioContext.close();
      listening = null;
      onState(false);
      if (!heardSpeech) { toast("I didn't hear anything. Please try again."); return; }
      const audio = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      onInterim("…");
      try {
        const response = await fetch(`/api/voice/listen?lang=${encodeURIComponent(langHint)}`, {
          method: "POST", body: audio,
          headers: { "Content-Type": audio.type.split(";")[0], Authorization: "Bearer " + token() },
        });
        const data = await response.json().catch(() => null);
        // Out of Sarvam credits, over today's limit or Sarvam down: carry on with the browser's
        // free speech for the rest of this visit, so voice never costs money or stops working.
        if ((response.status === 503 || response.status === 429) && Recognition) {
          sarvam.on = false;
          sarvam.speaks = [];
          onInterim("");
          toast("Switched to the browser's free voice. Tap 🎤 and speak again.");
          return;
        }
        if (!response.ok) throw new Error((data && data.detail) || "Voice isn't working right now.");
        onInterim("");
        if (data.text) onFinal(data.text);
        else toast("I couldn't make out the words. Please try again.");
      } catch (e) {
        onInterim("");
        toast(e.message);
      }
    };
    listening = { stop };
    onState(true);
    recorder.start();
  }

  function browserListen(lang) {
    const recognition = new Recognition();
    recognition.lang = SPEECH_LANG[lang] || "hi-IN";
    recognition.interimResults = true;
    recognition.onresult = event => {
      const result = event.results[event.results.length - 1];
      if (result.isFinal) onFinal(result[0].transcript.trim());
      else onInterim(result[0].transcript);
    };
    recognition.onerror = event => {
      if (event.error === "not-allowed" || event.error === "service-not-allowed") toast("Please allow the microphone for this site.");
      else if (event.error === "no-speech") toast("I didn't hear anything. Please try again.");
      else if (event.error !== "aborted") toast(`Voice input failed: ${event.error}`);
    };
    recognition.onend = () => { listening = null; onState(false); };
    listening = recognition;
    onState(true);
    recognition.start();
  }

  // False when this device has no voice for the language, such as Urdu on many computers.
  function browserSpeak(text, lang, onDone) {
    if (!("speechSynthesis" in window)) return false;
    const tag = SPEECH_LANG[lang] || "en-IN";
    // Roman Hindi is in Latin letters, so an Indian English voice can still read it.
    const voice = voiceFor(tag) || (lang === "hinglish" ? voiceFor("en-IN") : null);
    if (!voice) return false;
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = tag;
    utterance.voice = voice;
    utterance.rate = 1;
    utterance.pitch = 1;
    utterance.onend = () => onDone && onDone();
    speechSynthesis.cancel();
    speechSynthesis.speak(utterance);
    return true;
  }

  function stopSpeaking() {
    if (playing) { playing.pause(); playing = null; }
    if ("speechSynthesis" in window) speechSynthesis.cancel();
  }

  async function sarvamSpeak(text, lang, onDone) {
    const reply = await api("/voice/speak", { method: "POST", body: { text: text.slice(0, 1500), lang } });
    if (!reply.audio) throw new Error("no Sarvam voice for this language");
    stopSpeaking();
    playing = new Audio(`data:${reply.type};base64,${reply.audio}`);
    playing.onended = () => { playing = null; onDone && onDone(); };
    await playing.play();
  }

  return {
    sarvam,
    get canListen() { return (sarvam.on && canRecord) || !!Recognition; },
    get canSpeak() { return sarvam.on || "speechSynthesis" in window; },
    // Asks the server once whether Sarvam is set up.
    async check() {
      try {
        const status = await api("/voice/status");
        sarvam.on = !!status.sarvam;
        sarvam.speaks = status.speak || [];
      } catch {
        sarvam.on = false;
      }
      return sarvam.on;
    },
    listen(lang, langHint = "unknown") {
      if (listening) { listening.stop(); return; }
      stopSpeaking();
      if (sarvam.on && canRecord) record(langHint);
      else if (Recognition) browserListen(lang);
    },
    // False when no voice is available for the language, so the reply stays text only.
    speak(text, lang, onDone) {
      if (sarvam.on && sarvam.speaks.includes(lang)) {
        sarvamSpeak(text, lang, onDone).catch(() => browserSpeak(text, lang, onDone));
        return true;
      }
      return browserSpeak(text, lang, onDone);
    },
    stopSpeaking,
  };
}

const warnedNoVoice = {};
let chatPinHandler = null;
// Set by setupChat; rider.js calls it when a driver accepts the ride.
let announceDriver = null;
const DRIVER_ASSIGNED = {
  en: (name, eta) => `${name} is your driver and is on the way to your pickup location${eta ? `, about ${eta} min away` : ""}.`,
  hinglish: (name, eta) => `Aapko ${name} naam ka driver assign hua hai, aur woh aapki pickup location par aa rahe hain${eta ? `, lagbhag ${eta} minute mein` : ""}.`,
  hi: (name, eta) => `आपको ${name} नाम का ड्राइवर असाइन हुआ है, और वह आपकी पिकअप लोकेशन पर आ रहे हैं${eta ? `, लगभग ${eta} मिनट में` : ""}।`,
  ur: (name, eta) => `آپ کو ${name} نام کا ڈرائیور ملا ہے، اور وہ آپ کی پک اپ لوکیشن پر آ رہے ہیں${eta ? `، تقریباً ${eta} منٹ میں` : ""}۔`,
};
// Already allowed location? Then the app can answer "where should I pick you up?" by itself.
const locationAllowed = async () => {
  try {
    return navigator.permissions && (await navigator.permissions.query({ name: "geolocation" })).state === "granted";
  } catch {
    return false;
  }
};

function setupChat() {
  let voiceLang = lang() === "hi" ? "hi" : "en";
  let replyLang = voiceLang;      // the language the assistant last replied in
  let idlePlaceholder = "English, हिंदी, اردو…";
  let speakReplies = true;
  let greeted = false;
  const voice = makeVoice({
    onInterim: text => { input.value = text; },
    onFinal: text => { input.value = ""; if (text) send(text, undefined, {}, true); },
    onState: on => {
      micButton.classList.toggle("listening", on);
      micButton.setAttribute("aria-pressed", String(on));
      input.placeholder = on ? "Listening… सुन रहा हूं… سن رہا ہوں…" : idlePlaceholder;
    },
  });
  const languagePicker = el("select", {
    class: "voice-lang", "aria-label": "Language you will speak",
    onchange: event => { voiceLang = event.target.value; pickedLanguage = true; },
  }, VOICE_LANGUAGES.map(([code, label]) => el("option", { value: code, selected: code === voiceLang }, label)));
  // Sarvam works out the language itself unless the rider chose one, which helps it tell
  // Dogri from Hindi.
  let pickedLanguage = false;
  const listenNow = () => voice.listen(voiceLang, pickedLanguage ? voiceLang : "unknown");
  const languagesLine = el("div", { class: "muted" }, "English · हिंदी · اردو");
  const speakerButton = el("button", {
    type: "button", class: "assistant-close", "aria-label": "Read replies aloud", "aria-pressed": "true", title: "Read replies aloud",
    onclick: () => {
      speakReplies = !speakReplies;
      speakerButton.textContent = speakReplies ? "🔊" : "🔇";
      speakerButton.setAttribute("aria-pressed", String(speakReplies));
      if (!speakReplies) voice.stopSpeaking();
    },
  }, "🔊");
  const log = el("div", { class: "chat-log", "aria-live": "polite" });
  const micButton = el("button", { type: "button", class: "mic", "aria-label": "Speak your request", title: "Speak", onclick: listenNow }, "🎤");
  const input = el("input", { placeholder: "English, हिंदी, اردو…", maxLength: 500, "aria-label": "Message the assistant", dir: "auto" });
  const sheet = el("section", { id: "assistant", class: "assistant hidden", "aria-label": "Booking assistant" },
    el("header", { class: "assistant-head" },
      el("div", {}, el("strong", {}, "Ride assistant"), languagesLine),
      el("div", { class: "voice-controls" }, languagePicker, speakerButton),
      el("button", { type: "button", class: "assistant-close", "aria-label": "Close assistant", onclick: () => toggle(false) }, "×")),
    log,
    el("form", { class: "row assistant-form", onsubmit: event => {
      event.preventDefault();
      const text = input.value.trim();
      input.value = "";
      if (text) send(text);
    } }, micButton, input, el("button", { type: "submit", style: "flex:0 0 66px" }, "Send")));
  const opener = el("button", { id: "assistant-open", type: "button", class: "assistant-open", "aria-label": "Open ride assistant", onclick: () => toggle(true) }, "💬");
  document.body.append(sheet, opener);

  function toggle(open) {
    sheet.classList.toggle("hidden", !open);
    opener.classList.toggle("hidden", open);
    if (open) {
      input.focus();
      if (!greeted) greet();
    }
  }

  function bubble(text, mine = false) {
    const node = el("div", { class: "msg" + (mine ? " mine" : ""), dir: "auto" }, text);
    log.append(node);
    log.scrollTop = log.scrollHeight;
    return node;
  }

  function chips(items, className = "chat-chips") {
    const box = el("div", { class: className }, items.map(item => el("button", {
      type: "button", class: "chip", dir: "auto",
      onclick: () => {
        box.remove();
        if (item.action === "location") {
          bubble(item.label, true);
          askForLocation({ need_location: item.target, failed_buttons: items.filter(i => i.action !== "location") });
        } else if (item.action === "map") pickOnMap(item);
        else if (item.action === "point") send("", item.label, { location: item.point, target: item.target });
        else send(item.send, item.label);
      },
    }, item.label)));
    log.append(box);
    log.scrollTop = log.scrollHeight;
  }

  function temples(list) {
    const box = el("div", { class: "scroller" }, list.map(photo => el("button", {
      type: "button", class: "dest", onclick: () => send(`to ${photo.place}`, photo.title),
    }, el("img", { src: photo.src, alt: photo.title }), el("span", { class: "dest-name" }, photo.title))));
    log.append(box, el("details", { class: "muted credit-line" }, el("summary", {}, "Photo credits"),
      list.map(p => el("div", {}, `${p.title}: `, creditLink(p)))));
    log.scrollTop = log.scrollHeight;
  }

  function askForLocation(reply, fromVoice = false) {
    if (!navigator.geolocation) {
      bubble(t("Location isn't available in this browser."));
      if (reply.failed_buttons) chips(reply.failed_buttons);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      pos => send("", null, { location: { lat: pos.coords.latitude, lon: pos.coords.longitude }, target: reply.need_location }, fromVoice),
      () => {
        // Asked by the app itself: fall back to the question it answered for the rider.
        if (reply.fallback) { showReply(reply.fallback, fromVoice); return; }
        bubble(t("I couldn't get your location. Please allow location access, or tell me your area."));
        if (reply.failed_buttons) chips(reply.failed_buttons);
      },
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 });
  }

  function pickOnMap(button) {
    bubble(button.prompt);
    toggle(false);
    chatPinHandler = point => {
      toggle(true);
      send("", "📍", { location: { lat: point.lat, lon: point.lon }, target: button.target });
    };
  }

  function say(reply, fromVoice) {
    if (!speakReplies || !voice.canSpeak) return;
    // Keep the conversation going by voice, except at "shall I book?", which needs a tap on
    // the mic, so background noise can't be heard as a yes.
    const carryOn = fromVoice && reply.listen && voice.canListen ? listenNow : null;
    const spoke = voice.speak(reply.speech || reply.text, reply.lang, carryOn);
    if (!spoke && !warnedNoVoice[reply.lang]) {
      warnedNoVoice[reply.lang] = true;
      log.append(el("div", { class: "muted chat-note" }, "This device has no voice for this language, so replies in it are text only."));
    }
  }

  // quiet: show the reply but don't read it or offer its buttons, because the app is about to
  // answer it itself (with the rider's location).
  function showReply(reply, fromVoice, quiet = false) {
    bubble(reply.text);
    if (reply.lang) replyLang = reply.lang;
    // Roman Hindi is spoken Hindi, so the microphone should listen for Hindi.
    const heard = reply.lang === "hinglish" ? "hi" : reply.lang;
    // The assistant replies to Dogri and Kashmiri in Hindi or Urdu; the rider still speaks their own.
    const keepPicked = pickedLanguage && (voiceLang === "doi" || voiceLang === "ks");
    if (!keepPicked && [...languagePicker.options].some(o => o.value === heard)) {
      voiceLang = heard;
      languagePicker.value = heard;
    }
    if (!quiet) say(reply, fromVoice);
    if (reply.note) log.append(el("div", { class: "muted chat-note", dir: "auto" }, reply.note));
    if (reply.call) location.href = `tel:+91${reply.call}`;
    if (reply.temples) temples(reply.temples.map(photoById).filter(Boolean));
    if (reply.buttons && !quiet) chips(reply.buttons);
    log.scrollTop = log.scrollHeight;
  }

  // Said aloud and shown when a driver accepts, so a rider who booked by voice hears it too.
  announceDriver = ride => {
    if (!greeted || !ride.driver) return;
    const minutes = ride.driver.to_pickup && Math.max(1, Math.round(ride.driver.to_pickup.minutes));
    const lang = DRIVER_ASSIGNED[replyLang] ? replyLang : "en";
    const text = DRIVER_ASSIGNED[lang](ride.driver.name, minutes);
    bubble(text);
    say({ text, lang }, false);
  };

  async function send(text, shown, extra = {}, fromVoice = false) {
    // Earlier suggestions no longer fit once the conversation has moved on.
    log.querySelectorAll(".chat-chips").forEach(box => box.remove());
    if (shown !== null) bubble(shown || text, true);
    const waiting = el("div", { class: "msg typing", "aria-label": "Typing" }, el("span"), el("span"), el("span"));
    log.append(waiting);
    log.scrollTop = log.scrollHeight;
    try {
      const reply = await api("/chat", { method: "POST", body: { message: text, ...extra,
        ...(typeof isWomenMode === "function" && isWomenMode() ? { women_only: true } : {}) } });
      waiting.remove();
      const autoLocate = reply.ask_location && await locationAllowed();
      // Finding the rider takes a few seconds on a phone, so say so instead of going quiet.
      showReply(autoLocate ? { ...reply, text: reply.locating_text || reply.text, buttons: null, listen: false } : reply,
                fromVoice);
      if (reply.need_location) askForLocation(reply, fromVoice);
      if (reply.cleared) resetBooking();
      if (!reply.ride && (reply.pickup || reply.dropoff)) {
        // The panel shows the same trip as the conversation, whichever one changed it.
        pickup = reply.pickup || null;
        dropoff = reply.dropoff || null;
        marker("pickup", pickup);
        marker("dropoff", dropoff);
        if (!(pickup && dropoff)) {
          drawRoute(null);
          const only = pickup || dropoff;
          map.flyTo([only.lat, only.lon], 14, { duration: .8 });
        }
        renderBooking();
      }
      if (autoLocate) askForLocation({ need_location: "pickup", failed_buttons: reply.buttons, fallback: reply }, fromVoice);
      if (reply.ride) showRide(reply.ride);
      else if (reply.refresh) api("/rides/active").then(r => r ? showRide(r) : resetBooking()).catch(() => {});
    } catch (e) {
      waiting.remove();
      bubble(e.message);
    }
  }

  voice.check().then(sarvamOn => {
    if (sarvamOn) {
      languagePicker.append(...SARVAM_ONLY_LANGUAGES.map(([code, label]) => el("option", { value: code }, label)));
      languagesLine.textContent = "English · हिंदी · اردو · डोगरी · کٲشُر";
      idlePlaceholder = "English, हिंदी, اردو, डोगरी…";
      input.placeholder = idlePlaceholder;
    }
    if (!voice.canListen) {
      micButton.classList.add("hidden");
      log.append(el("div", { class: "muted chat-note" }, "Voice input isn't available in this browser. Chrome or Edge support it."));
    }
  });
  // Voices load late in some browsers; asking now makes them ready for the first reply.
  if ("speechSynthesis" in window) speechSynthesis.getVoices();
  async function greet() {
    greeted = true;
    try {
      showReply(await api(`/chat/hello?lang=${lang()}`));
    } catch (e) {
      bubble(e.message);
    }
    chips(CHAT_EXAMPLES.map(text => ({ label: text, send: text })));
  }
}
