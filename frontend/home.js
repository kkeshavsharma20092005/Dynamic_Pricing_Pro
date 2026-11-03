const REGION_FILTERS = [["all", "All of J&K"], ["temple", "Jammu temples"], ["JMU", "Jammu"], ["KSH", "Kashmir"], ["HIL", "Hills"]];
const SLIDE_MS = 5000;
let slide = 0, timer = null, slides = [];

function showSlide(index) {
  slide = (index + PHOTOS.length) % PHOTOS.length;
  slides.forEach((node, i) => node.classList.toggle("on", i === slide));
  [...$("dots").children].forEach((dot, i) => dot.setAttribute("aria-current", String(i === slide)));
  const photo = PHOTOS[slide];
  fill($("caption"), el("strong", {}, photo.title), ` · ${photo.tagline} `, creditLink(photo));
}

function play() {
  stop();
  if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
    timer = setInterval(() => showSlide(slide + 1), SLIDE_MS);
  }
}
function stop() { clearInterval(timer); }

function renderGrid(photos) {
  fill($("grid"), photos.map(photo => el("a", { class: "dest-card", href: `/ride?to=${encodeURIComponent(photo.place)}` },
    el("img", { src: photo.src, alt: photo.title, loading: "lazy" }),
    el("span", { class: "dest-overlay" }, el("strong", {}, photo.title), el("span", {}, photo.tagline)))));
}

(async function init() {
  await loadPhotos();
  const places = await fetch("/api/places").then(r => r.json()).catch(() => []);
  const regionOf = photo => (places.find(p => p.name === photo.place) || {}).region;

  slides = PHOTOS.map((photo, i) => el("div", { class: "slide", style: `background-image:url('${photo.src}')`, role: "img", "aria-label": photo.title }));
  fill($("slides"), slides);
  fill($("dots"), PHOTOS.map((photo, i) => el("button", {
    type: "button", class: "dot-btn", "aria-label": `Show ${photo.title}`, onclick: () => { showSlide(i); play(); },
  })));
  $("prev").onclick = () => { showSlide(slide - 1); play(); };
  $("next").onclick = () => { showSlide(slide + 1); play(); };
  $("hero").addEventListener("mouseenter", stop);
  $("hero").addEventListener("mouseleave", play);
  showSlide(0);
  play();

  const chips = REGION_FILTERS.map(([code, label]) => el("button", {
    type: "button", class: "chip", "aria-pressed": String(code === "all"),
    onclick: event => {
      chips.forEach(c => c.setAttribute("aria-pressed", String(c === event.currentTarget)));
      renderGrid(code === "all" ? PHOTOS : code === "temple" ? PHOTOS.filter(p => p.category === "temple") : PHOTOS.filter(p => regionOf(p) === code));
    },
  }, label));
  fill($("filters"), chips);
  renderGrid(PHOTOS);

  fill($("credits"), PHOTOS.map(photo => el("li", {},
    `${photo.title}: `, creditLink(photo))));

  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
})();
