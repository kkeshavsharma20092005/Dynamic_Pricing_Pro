// The booking assistant. It works in the rider app and drives the same map and trip screen.
const SPEECH_LANG = { en: "en-IN", hinglish: "hi-IN", hi: "hi-IN", ur: "ur-IN" };
const VOICE_LANGUAGES = [["en", "English"], ["hi", "हिंदी"], ["ur", "اردو"]];
const CHAT_EXAMPLES = ["Bharat Nagar to Roop Nagar", "मुझे मेरी लोकेशन से कटरा जाना है", "مجھے جموں سے کٹرہ جانا ہے", "Jammu ke mandir dikhao"];

// Both voice features are built into the browser, so this adds no dependency. Listening
// exists only in some browsers, which usually send the audio to their speech service.
function makeVoice({ onInterim, onFinal, onState }) {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let listening = null;

  // Cloud and neural voices sound far more like a person than the older local ones.
  function voiceFor(tag) {
    const prefix = tag.slice(0, 2);
    const score = v => (/natural|neural/i.test(v.name) ? 4 : 0) + (/online|google/i.test(v.name) ? 2 : 0)
      + (v.lang.replace("_", "-") === tag ? 1 : 0);
    return speechSynthesis.getVoices().filter(v => v.lang.startsWith(prefix)).sort((a, b) => score(b) - score(a))[0];
  }

  return {
    canListen: !!Recognition,
    canSpeak: "speechSynthesis" in window,
    listen(lang) {
      if (listening) { listening.stop(); return; }
      speechSynthesis?.cancel();
      const recognition = new Recognition();
      recognition.lang = SPEECH_LANG[lang];
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
    },
    // False when this device has no voice for the language, such as Urdu on many computers.
    speak(text, lang, onDone) {
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
    },
    stopSpeaking() { speechSynthesis?.cancel(); },
  };
}

const warnedNoVoice = {};
let chatPinHandler = null;

function setupChat() {
  let voiceLang = lang() === "hi" ? "hi" : "en";
  let speakReplies = true;
  let greeted = false;
  const voice = makeVoice({
    onInterim: text => { input.value = text; },
    onFinal: text => { input.value = ""; if (text) send(text, undefined, {}, true); },
    onState: on => {
      micButton.classList.toggle("listening", on);
      micButton.setAttribute("aria-pressed", String(on));
      input.placeholder = on ? "Listening… सुन रहा हूं… سن رہا ہوں…" : "English, हिंदी, اردو…";
    },
  });
  const languagePicker = el("select", {
    class: "voice-lang", "aria-label": "Language you will speak",
    onchange: event => { voiceLang = event.target.value; },
  }, VOICE_LANGUAGES.map(([code, label]) => el("option", { value: code, selected: code === voiceLang }, label)));
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
  const micButton = el("button", { type: "button", class: "mic", "aria-label": "Speak your request", title: "Speak", onclick: () => voice.listen(voiceLang) }, "🎤");
  const input = el("input", { placeholder: "English, हिंदी, اردو…", maxLength: 500, "aria-label": "Message the assistant", dir: "auto" });
  const sheet = el("section", { id: "assistant", class: "assistant hidden", "aria-label": "Booking assistant" },
    el("header", { class: "assistant-head" },
      el("div", {}, el("strong", {}, "Ride assistant"), el("div", { class: "muted" }, "English · हिंदी · اردو")),
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

  function askForLocation(reply) {
    if (!navigator.geolocation) {
      bubble(t("Location isn't available in this browser."));
      if (reply.failed_buttons) chips(reply.failed_buttons);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      pos => send("", null, { location: { lat: pos.coords.latitude, lon: pos.coords.longitude }, target: reply.need_location }),
      () => {
        bubble(t("I couldn't get your location. Please allow location access, or tell me your area."));
        if (reply.failed_buttons) chips(reply.failed_buttons);
      },
      { enableHighAccuracy: true, timeout: 12000 });
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
    const carryOn = fromVoice && reply.listen && voice.canListen ? () => voice.listen(voiceLang) : null;
    const spoke = voice.speak(reply.speech || reply.text, reply.lang, carryOn);
    if (!spoke && !warnedNoVoice[reply.lang]) {
      warnedNoVoice[reply.lang] = true;
      log.append(el("div", { class: "muted chat-note" }, "This device has no voice for this language, so replies in it are text only."));
    }
  }

  function showReply(reply, fromVoice) {
    bubble(reply.text);
    // Roman Hindi is spoken Hindi, so the microphone should listen for Hindi.
    const heard = reply.lang === "hinglish" ? "hi" : reply.lang;
    if ([...languagePicker.options].some(o => o.value === heard)) {
      voiceLang = heard;
      languagePicker.value = heard;
    }
    say(reply, fromVoice);
    if (reply.note) log.append(el("div", { class: "muted chat-note", dir: "auto" }, reply.note));
    if (reply.call) location.href = `tel:+91${reply.call}`;
    if (reply.temples) temples(reply.temples.map(photoById).filter(Boolean));
    if (reply.buttons) chips(reply.buttons);
    log.scrollTop = log.scrollHeight;
  }

  async function send(text, shown, extra = {}, fromVoice = false) {
    // Earlier suggestions no longer fit once the conversation has moved on.
    log.querySelectorAll(".chat-chips").forEach(box => box.remove());
    if (shown !== null) bubble(shown || text, true);
    const waiting = el("div", { class: "msg typing", "aria-label": "Typing" }, el("span"), el("span"), el("span"));
    log.append(waiting);
    log.scrollTop = log.scrollHeight;
    try {
      const reply = await api("/chat", { method: "POST", body: { message: text, ...extra } });
      waiting.remove();
      showReply(reply, fromVoice);
      if (reply.need_location) askForLocation(reply);
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
      if (reply.ride) showRide(reply.ride);
      else if (reply.refresh) api("/rides/active").then(r => r ? showRide(r) : resetBooking()).catch(() => {});
    } catch (e) {
      waiting.remove();
      bubble(e.message);
    }
  }

  if (!voice.canListen) {
    micButton.classList.add("hidden");
    log.append(el("div", { class: "muted chat-note" }, "Voice input isn't available in this browser. Chrome or Edge support it."));
  }
  // Voices load late in some browsers; asking now makes them ready for the first reply.
  if (voice.canSpeak) speechSynthesis.getVoices();
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
