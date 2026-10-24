/* A minimal canvas plot: axes, a filled band and/or a line series (null = gap),
   one or two horizontal reference lines, device-pixel-ratio aware.
   mountPlot() redraws on resize and on a light/dark theme change. */

const MARGIN = { left: 46, right: 10, top: 10, bottom: 22 };

function token(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function colors() {
  return {
    ink: token("--ink"),
    muted: token("--muted"),
    accent: token("--accent"),
    line: token("--line"),
    ground: token("--ground"),
  };
}

/** The drawable box in CSS pixels; the backing store is scaled by dpr. */
function frame(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || canvas.parentElement?.clientWidth || 320;
  const height = canvas.clientHeight || 120;
  canvas.width = Math.max(1, Math.round(width * dpr));
  canvas.height = Math.max(1, Math.round(height * dpr));
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, width, height };
}

function geometry(width, height, spec) {
  const box = {
    left: MARGIN.left,
    top: MARGIN.top,
    width: width - MARGIN.left - MARGIN.right,
    height: height - MARGIN.top - MARGIN.bottom,
  };
  const xMax = spec.xMax > 0 ? spec.xMax : 1;
  const spanY = spec.yMax - spec.yMin || 1;
  return {
    ...box,
    xToPx: (value) => box.left + (value / xMax) * box.width,
    yToPx: (value) => box.top + box.height - ((value - spec.yMin) / spanY) * box.height,
    xMax,
  };
}

function drawAxes(ctx, geom, spec, pal) {
  ctx.strokeStyle = pal.line;
  ctx.lineWidth = 1;
  ctx.strokeRect(geom.left + 0.5, geom.top + 0.5, geom.width - 1, geom.height - 1);
  ctx.fillStyle = pal.muted;
  ctx.font = "10px ui-monospace, monospace";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  const ticks = spec.yTicks ?? [spec.yMin, (spec.yMin + spec.yMax) / 2, spec.yMax];
  for (const value of ticks) {
    const y = geom.yToPx(value);
    ctx.fillText(spec.fmtY ? spec.fmtY(value) : String(Math.round(value * 100) / 100), geom.left - 5, y);
  }
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  for (const value of [0, geom.xMax / 2, geom.xMax]) {
    ctx.fillText(`${Math.round(value * 10) / 10}s`, geom.xToPx(value), geom.top + geom.height + 5);
  }
}

function drawBand(ctx, geom, spec, pal) {
  const { min, max } = spec;
  if (!min || !max || min.length < 2) return;
  const count = Math.min(min.length, max.length);
  const step = geom.width / (count - 1);
  ctx.beginPath();
  for (let i = 0; i < count; i += 1) {
    const x = geom.left + i * step;
    const y = geom.yToPx(max[i]);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  for (let i = count - 1; i >= 0; i -= 1) {
    ctx.lineTo(geom.left + i * step, geom.yToPx(min[i]));
  }
  ctx.closePath();
  ctx.fillStyle = pal.accent;
  ctx.globalAlpha = 0.35;
  ctx.fill();
  ctx.globalAlpha = 0.9;
  ctx.strokeStyle = pal.accent;
  ctx.lineWidth = 1;
  ctx.stroke();
  ctx.globalAlpha = 1;
}

function drawLine(ctx, geom, spec, pal) {
  const values = spec.line;
  if (!values || values.length < 2) return;
  const count = values.length;
  const step = geom.width / (count - 1);
  const xAt = (i) => geom.left + i * step;
  const scale = spec.lineX ? (i) => geom.xToPx(spec.lineX(i)) : xAt;
  ctx.strokeStyle = spec.lineColor ?? pal.accent;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  let pen = false;
  for (let i = 0; i < count; i += 1) {
    const value = values[i];
    if (value === null || value === undefined) {
      pen = false;
      continue;
    }
    const x = scale(i);
    const y = geom.yToPx(value);
    if (pen) ctx.lineTo(x, y);
    else ctx.moveTo(x, y);
    pen = true;
  }
  ctx.stroke();
}

function drawRef(ctx, geom, value, label, style, pal) {
  if (value === null || value === undefined) return;
  const y = geom.yToPx(value);
  ctx.save();
  ctx.strokeStyle = style;
  ctx.setLineDash([5, 4]);
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(geom.left, y);
  ctx.lineTo(geom.left + geom.width, y);
  ctx.stroke();
  ctx.restore();
  if (label) {
    ctx.fillStyle = style;
    ctx.font = "10px ui-monospace, monospace";
    ctx.textAlign = "right";
    ctx.textBaseline = "bottom";
    ctx.fillText(label, geom.left + geom.width - 3, y - 2);
  }
}

/** Draw `spec` onto `canvas` once. See mountPlot for the spec factory. */
export function drawPlot(canvas, spec) {
  const { ctx, width, height } = frame(canvas);
  const pal = colors();
  ctx.clearRect(0, 0, width, height);
  const geom = geometry(width, height, spec);
  drawAxes(ctx, geom, spec, pal);
  if (spec.paint) spec.paint(ctx, geom, pal);
  drawBand(ctx, geom, spec, pal);
  drawLine(ctx, geom, spec, pal);
  drawRef(ctx, geom, spec.ref, spec.refLabel, spec.refColor ?? pal.muted, pal);
  drawRef(ctx, geom, spec.ref2, spec.ref2Label, spec.ref2Color ?? pal.accent, pal);
  if (spec.overlay) spec.overlay(ctx, geom, pal);
}

/** The x value (seconds, 0..xMax) at a click's clientX, for seek-on-click. */
export function valueAtX(canvas, clientX, xMax) {
  const width = canvas.clientWidth || canvas.parentElement?.clientWidth || 320;
  const boxWidth = width - MARGIN.left - MARGIN.right;
  const fraction = (clientX - canvas.getBoundingClientRect().left - MARGIN.left) / boxWidth;
  return Math.min(Math.max(fraction, 0), 1) * xMax;
}

/**
 * Draw and keep `specOf()` redrawn on canvas resize and theme change.
 *
 * spec: { min?, max?, line?, lineX?, lineColor?, ref?, refLabel?, ref2?,
 *         ref2Label?, refColor?, ref2Color?, xMax, yMin, yMax, yTicks?,
 *         fmtY?, paint?, overlay? } — x values are seconds, painted through
 * geom.xToPx / geom.yToPx.
 *
 * @returns {{redraw: () => void}}
 */
export function mountPlot(canvas, specOf) {
  const redraw = () => drawPlot(canvas, specOf());
  redraw();
  new ResizeObserver(redraw).observe(canvas);
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", redraw);
  return { redraw };
}
