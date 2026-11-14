/* The grain: facet's night surface is a terminal in a night gallery, and the
   screen carries a fine grain, as the site draws it. A fixed canvas behind the
   content (z-index 0, the content sits at 1) is filled at a quarter of the
   viewport's resolution and scaled up without smoothing, so the grain stays a
   texture and never reads as noise over the text.

   Grey runs between 40 and 240, the alpha is 0.085 (22/255), and the field is
   redrawn every 90 ms. Under `prefers-reduced-motion: reduce` it is drawn once
   and stays still. */

const QUARTER = 4;
const MIN_GREY = 40;
const MAX_GREY = 240;
const ALPHA = 22;
const FRAME_MS = 90;

function fill(canvas) {
  const width = Math.max(1, Math.ceil(window.innerWidth / QUARTER));
  const height = Math.max(1, Math.ceil(window.innerHeight / QUARTER));
  if (canvas.width !== width) canvas.width = width;
  if (canvas.height !== height) canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const image = ctx.createImageData(width, height);
  const pixels = image.data;
  for (let index = 0; index < pixels.length; index += 4) {
    const grey = MIN_GREY + Math.random() * (MAX_GREY - MIN_GREY);
    pixels[index] = grey;
    pixels[index + 1] = grey;
    pixels[index + 2] = grey;
    pixels[index + 3] = ALPHA;
  }
  ctx.putImageData(image, 0, 0);
}

function mount() {
  if (document.querySelector(".grain")) return;
  const canvas = document.createElement("canvas");
  canvas.className = "grain";
  canvas.setAttribute("aria-hidden", "true");
  document.body.prepend(canvas);

  const still = window.matchMedia("(prefers-reduced-motion: reduce)");
  let timer = null;

  const animate = () => {
    window.clearInterval(timer);
    timer = null;
    fill(canvas);
    if (still.matches) return;
    timer = window.setInterval(() => fill(canvas), FRAME_MS);
  };

  animate();
  window.addEventListener("resize", animate);
  still.addEventListener("change", animate);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mount);
} else {
  mount();
}
