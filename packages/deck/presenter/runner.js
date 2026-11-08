// Runner del presentador: se inyecta al final del HTML de la presentación.
// Cada <section class="slide"> de 1280×720 es una diapositiva.
(() => {
  const W = 1280, H = 720;
  const slides = [...document.querySelectorAll('section.slide')];
  const NOTES = window.__PZ_NOTES__ || [];
  const root = document.documentElement;
  const isPresenter = location.hash === '#presenter';
  root.classList.add(isPresenter ? 'pz-presenter' : 'pz-main');
  let cur = 0, partner = isPresenter ? window.opener : null, t0 = null;
  let ch = null; try { ch = new BroadcastChannel('pz-sync'); } catch (e) {}

  const $ = (tag, cls, parent) => { const e = document.createElement(tag); if (cls) e.className = cls; if (parent) parent.appendChild(e); return e; };
  const pad = n => String(n).padStart(2, '0');
  const fmtT = ms => { const s = Math.floor(ms / 1000); return pad(Math.floor(s / 60)) + ':' + pad(s % 60); };

  // ---------- ventana del presentador ----------
  let pv = null;
  if (isPresenter) {
    document.title = 'Presentador — ' + document.title;
    const grid = $('div', 'pz-grid', document.body);
    const cbox = $('div', 'pz-box pz-big', grid), cframe = $('div', 'pz-frame', cbox);
    const side = $('div', 'pz-side', grid);
    const nbox = $('div', 'pz-box pz-small', side), nframe = $('div', 'pz-frame', nbox);
    const clock = $('div', 'pz-clock', side), notes = $('div', 'pz-notes', side);
    const bar = $('div', 'pz-bar', grid);
    pv = { cbox, cframe, nbox, nframe, clock, notes, bar };
  }
  function fitFrames() {
    if (!pv) return;
    [[pv.cbox, pv.cframe], [pv.nbox, pv.nframe]].forEach(([b, f]) => { f.style.transform = 'scale(' + (b.clientWidth / W) + ')'; });
  }
  function fillFrame(frame, i) {
    frame.innerHTML = '';
    if (i < 0 || i >= slides.length) { const e = $('div', 'pz-end', frame); e.textContent = 'Fin'; return; }
    const c = slides[i].cloneNode(true); c.classList.add('pz-clone'); c.querySelectorAll('video').forEach(v => v.remove()); frame.appendChild(c);
  }

  // ---------- navegación ----------
  function show() {
    if (isPresenter) {
      fillFrame(pv.cframe, cur); fillFrame(pv.nframe, cur + 1); fitFrames();
      pv.notes.textContent = NOTES[cur] || 'Sin notas para esta diapositiva.';
      pv.bar.textContent = (cur + 1) + ' / ' + slides.length + '   ·   ← → navegar   ·   R reiniciar reloj   ·   B negro';
    } else {
      slides.forEach((s, i) => {
        const on = i === cur; s.classList.toggle('pz-cur', on);
        s.querySelectorAll('video').forEach(v => { if (on) { v.currentTime = 0; v.play().catch(() => {}); } else v.pause(); });
      });
      location.hash = '#' + (cur + 1);
    }
  }
  function go(i, remote) {
    i = Math.max(0, Math.min(slides.length - 1, i));
    if (i === cur && !remote && !isPresenter) return;
    cur = i; if (t0 === null) t0 = Date.now(); show();
    if (!remote) { const msg = { pz: cur }; try { (partner || window.opener || null)?.postMessage(msg, '*'); } catch (e) {} try { ch?.postMessage(msg); } catch (e) {} }
  }
  window.addEventListener('message', e => { if (e.data && typeof e.data.pz === 'number') { if (!isPresenter && e.source && !partner) partner = e.source; go(e.data.pz, true); } });
  ch && (ch.onmessage = e => { if (e.data && typeof e.data.pz === 'number') go(e.data.pz, true); });

  // ---------- ajuste a la ventana (modo principal) ----------
  function fit() {
    const s = Math.min(innerWidth / W, innerHeight / H);
    root.style.setProperty('--pz-s', s); root.style.setProperty('--pz-x', ((innerWidth - W * s) / 2) + 'px'); root.style.setProperty('--pz-y', ((innerHeight - H * s) / 2) + 'px');
    fitFrames();
  }
  addEventListener('resize', fit);

  // ---------- teclado y ratón ----------
  let num = '';
  addEventListener('keydown', e => {
    const k = e.key;
    if (['ArrowRight', 'ArrowDown', 'PageDown', ' ', 'Enter'].includes(k) && !num) { go(cur + 1); e.preventDefault(); }
    else if (['ArrowLeft', 'ArrowUp', 'PageUp', 'Backspace'].includes(k)) { go(cur - 1); e.preventDefault(); }
    else if (k === 'Home') go(0); else if (k === 'End') go(slides.length - 1);
    else if (/^[0-9]$/.test(k)) num += k;
    else if (k === 'Enter' || (num && k === 'Enter')) { go(parseInt(num, 10) - 1); num = ''; }
    else if (k === 'f' || k === 'F') { document.fullscreenElement ? document.exitFullscreen() : root.requestFullscreen?.(); }
    else if (k === 'b' || k === 'B' || k === '.') root.classList.toggle('pz-black');
    else if ((k === 'p' || k === 'P') && !isPresenter) {
      const w = window.open(location.href.split('#')[0] + '#presenter', 'pz-presenter', 'width=1180,height=720'); if (w) { partner = w; setTimeout(() => w.postMessage({ pz: cur }, '*'), 800); }
    }
    else if (k === 'r' || k === 'R') t0 = Date.now();
    if (num && k === 'Enter') { go(parseInt(num, 10) - 1); num = ''; }
  });
  if (!isPresenter) {
    addEventListener('click', () => go(cur + 1));
    let idle; const wake = () => { root.classList.remove('pz-idle'); clearTimeout(idle); idle = setTimeout(() => root.classList.add('pz-idle'), 2000); };
    addEventListener('mousemove', wake); wake();
    const hint = $('div', 'pz-hint', document.body); hint.textContent = '→ siguiente   ·   P presentador   ·   F pantalla completa   ·   B negro';
    setTimeout(() => hint.classList.add('pz-gone'), 3500);
  } else {
    setInterval(() => { pv.clock.textContent = (t0 === null ? '00:00' : fmtT(Date.now() - t0)) + '   ·   ' + new Date().toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' }); }, 500);
  }

  fit();
  const start = parseInt(location.hash.slice(1), 10);
  go(isNaN(start) ? 0 : start - 1, true);
  if (document.fonts?.ready) document.fonts.ready.then(() => { show(); fit(); });
})();
