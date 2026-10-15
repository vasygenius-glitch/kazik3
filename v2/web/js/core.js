// Ядро: DOM, API, состояние, форматирование, звук, вибрация, тосты, празднования.
export const tg = window.Telegram?.WebApp;
const SVGNS = 'http://www.w3.org/2000/svg';

export function h(tag, props, ...kids) {
  const svg = tag.startsWith('svg:');
  const el = svg ? document.createElementNS(SVGNS, tag.slice(4)) : document.createElement(tag);
  if (props) for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === 'class') svg ? el.setAttribute('class', v) : (el.className = v);
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k === 'html') el.innerHTML = v; // только для наших SVG-шаблонов
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'value') el.value = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
export const clear = (el) => { while (el.firstChild) el.firstChild.remove(); return el; };
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
export const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

// ── события ──
const subs = {};
export function on(evt, fn) { (subs[evt] ||= new Set()).add(fn); return () => subs[evt].delete(fn); }
export function emit(evt, data) { subs[evt]?.forEach((fn) => { try { fn(data); } catch (e) { console.error(e); } }); }

// ── состояние ──
export const S = { me: null, cfg: null, chat: null, balance: 0, timers: {}, tasks: [], fire: null, online: [], feed: [],
  tables: {}, active: {}, off: 0, rtt: 1e9, screen: 'lobby' };
export const now = () => Date.now() / 1000 + S.off;

// ── форматирование ──
export function fmt(n) {
  n = Math.trunc(Number(n) || 0);
  const s = Math.abs(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, '\u2009');
  return (n < 0 ? '−' : '') + s;
}
export function fmtc(n) {
  n = Number(n) || 0; const a = Math.abs(n), sg = n < 0 ? '−' : '';
  const f = (v, u) => sg + (v >= 100 ? Math.round(v) : (Math.round(v * 10) / 10)).toString().replace('.', ',') + u;
  if (a >= 1e12) return f(a / 1e12, ' трлн'); if (a >= 1e9) return f(a / 1e9, ' млрд');
  if (a >= 1e6) return f(a / 1e6, ' млн'); if (a >= 1e4) return f(a / 1e3, ' тыс');
  return sg + fmt(a);
}
export const fx = (x) => 'x' + (Math.round(x * 100) / 100).toString().replace('.', ',');
export function plural(n, one, few, many) {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many; if (b > 1 && b < 5) return few; if (b === 1) return one; return many;
}
export function left(sec) {
  sec = Math.max(0, Math.ceil(sec));
  const hh = Math.floor(sec / 3600), mm = Math.floor((sec % 3600) / 60), ss = sec % 60;
  if (hh) return `${hh} ч ${mm} мин`; if (mm) return `${mm}:${String(ss).padStart(2, '0')}`; return `${ss} с`;
}
export function ago(ts) {
  const d = Math.max(0, now() - ts);
  if (d < 60) return 'только что'; if (d < 3600) return `${Math.floor(d / 60)} мин назад`;
  if (d < 86400) return `${Math.floor(d / 3600)} ч назад`; return `${Math.floor(d / 86400)} дн назад`;
}

// ── хранилище настроек ──
export const prefs = {
  get(k, d) { try { const v = localStorage.getItem('kz_' + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem('kz_' + k, JSON.stringify(v)); } catch { /* приватный режим */ } },
};

// ── API ──
const params = new URLSearchParams(location.search);
export const chatToken = tg?.initDataUnsafe?.start_param || params.get('c') || params.get('tgWebAppStartParam') || '';
export class ApiErr extends Error { constructor(msg, code, status) { super(msg); this.code = code; this.status = status; } }

export async function api(path, body = {}, { quiet = false } = {}) {
  const headers = { 'Content-Type': 'application/json', 'X-Init-Data': tg?.initData || '', 'X-Chat': chatToken };
  const dev = params.get('dev');
  if (dev) headers['X-Dev-User'] = encodeURIComponent(dev);
  const t0 = Date.now();
  let res, data;
  try {
    res = await fetch('/api/v2/' + path, { method: 'POST', headers, body: JSON.stringify(body) });
    data = await res.json();
  } catch (e) {
    if (!quiet) toast('Нет связи с Казиком. Проверь интернет.', 'err');
    throw new ApiErr('network', 'network', 0);
  }
  const t1 = Date.now();
  if (typeof data.now === 'number') {
    const rtt = t1 - t0;
    if (rtt < S.rtt * 1.5 || Math.abs(data.now - (t0 + t1) / 2000 - S.off) > 2) {
      S.off = data.now - (t0 + t1) / 2000; S.rtt = Math.min(S.rtt, rtt);
    }
  }
  if (typeof data.balance === 'number') setBalance(data.balance);
  if (!data.ok) {
    if (!quiet) { toast(data.error || 'Ошибка', 'err'); haptic('error'); }
    throw new ApiErr(data.error || 'error', data.code || 'game', res.status);
  }
  return data;
}

export function setBalance(v) {
  const old = S.balance; S.balance = v;
  if (old !== v) emit('balance', { old, v });
}

// ── вибрация и звук ──
export function haptic(kind = 'light') {
  if (!prefs.get('haptics', true)) return;
  const hf = tg?.HapticFeedback; if (!hf || !tgv('6.1')) return;
  try {
    if (kind === 'success' || kind === 'error' || kind === 'warning') hf.notificationOccurred(kind);
    else if (kind === 'select') hf.selectionChanged();
    else hf.impactOccurred(kind);
  } catch { /* старые клиенты */ }
}
let actx = null;
function ac() {
  if (!prefs.get('sound', true)) return null;
  try { actx ||= new (window.AudioContext || window.webkitAudioContext)(); if (actx.state === 'suspended') actx.resume(); } catch { return null; }
  return actx;
}
function tone(f, d = 0.08, type = 'sine', vol = 0.12, when = 0, slide = 0) {
  const a = ac(); if (!a) return;
  const t = a.currentTime + when, o = a.createOscillator(), g = a.createGain();
  o.type = type; o.frequency.setValueAtTime(f, t); if (slide) o.frequency.exponentialRampToValueAtTime(Math.max(30, f + slide), t + d);
  g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(vol, t + 0.008); g.gain.exponentialRampToValueAtTime(0.0001, t + d);
  o.connect(g).connect(a.destination); o.start(t); o.stop(t + d + 0.02);
}
function noise(d = 0.05, vol = 0.08, when = 0, hp = 1800) {
  const a = ac(); if (!a) return;
  const len = Math.floor(a.sampleRate * d), buf = a.createBuffer(1, len, a.sampleRate), ch = buf.getChannelData(0);
  for (let i = 0; i < len; i++) ch[i] = (Math.random() * 2 - 1) * (1 - i / len);
  const src = a.createBufferSource(), f = a.createBiquadFilter(), g = a.createGain();
  f.type = 'highpass'; f.frequency.value = hp; g.gain.value = vol; src.buffer = buf;
  src.connect(f).connect(g).connect(a.destination); src.start(a.currentTime + when);
}
export const sfx = {
  tap: () => tone(520, 0.04, 'triangle', 0.06),
  chip: () => { noise(0.04, 0.09, 0, 2500); tone(1400, 0.03, 'square', 0.025); },
  card: () => noise(0.07, 0.07, 0, 1200),
  tick: () => tone(1800, 0.015, 'square', 0.03),
  win: () => [523, 659, 784, 1046].forEach((f, i) => tone(f, 0.16, 'triangle', 0.1, i * 0.08)),
  big: () => [392, 523, 659, 784, 1046, 1318].forEach((f, i) => tone(f, 0.22, 'triangle', 0.11, i * 0.07)),
  lose: () => { tone(220, 0.22, 'sawtooth', 0.05, 0, -120); },
  boom: () => { noise(0.4, 0.22, 0, 200); tone(90, 0.35, 'sine', 0.2, 0, -50); },
  coin: () => { tone(1320, 0.06, 'square', 0.04); tone(1760, 0.1, 'square', 0.035, 0.05); },
  roll: () => { for (let i = 0; i < 6; i++) noise(0.03, 0.06, i * 0.07, 900); },
};

// ── тосты ──
let toastBox = null;
export function toast(text, kind = '', ms = 3200) {
  toastBox ||= document.body.appendChild(h('div', { class: 'toasts' }));
  const el = h('div', { class: 'toast ' + kind }, text);
  toastBox.append(el);
  while (toastBox.children.length > 3) toastBox.firstChild.remove();
  setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 320); }, ms);
}

// ── аватарки: только картинка по анонимному хэндлу + инициалы ──
const PALETTE = ['#e9a178', '#d9c27a', '#9fc28a', '#86b8c4', '#c99ad0', '#e3877a', '#c7b299', '#a3c9a8', '#e0b25e', '#b7a6e0'];
export function initials(name) {
  const parts = String(name || '?').replace(/[^\p{L}\p{N}\s]/gu, '').trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] || '?') + (parts[1]?.[0] || '')).toUpperCase();
}
function hue(str) { let x = 0; for (const c of String(str)) x = (x * 31 + c.codePointAt(0)) >>> 0; return PALETTE[x % PALETTE.length]; }
const avFail = new Set();
export function avatar(p, size = '') {
  const el = h('div', { class: 'av ' + size, style: { '--c': hue(p?.h || p?.name) } }, initials(p?.name));
  if (p?.h && !avFail.has(p.h)) {
    const img = h('img', { alt: '', loading: 'lazy', decoding: 'async', src: '/api/v2/av/' + encodeURIComponent(p.h) });
    img.onload = () => img.classList.add('ok');
    img.onerror = () => { avFail.add(p.h); img.remove(); };
    el.append(img);
  }
  return el;
}
export function stack(people, max = 5, size = 's') {
  const el = h('div', { class: 'stack' });
  people.slice(0, max).forEach((p) => el.append(avatar(p, size)));
  if (people.length > max) el.append(h('span', { class: 'more' }, '+' + (people.length - max)));
  return el;
}

// ── анимации чисел ──
export function roll(el, from, to, ms = 700, f = fmt) {
  const t0 = performance.now();
  cancelAnimationFrame(el._raf);
  const step = (t) => {
    const k = Math.min(1, (t - t0) / ms), e = 1 - Math.pow(1 - k, 3);
    el.textContent = f(Math.round(from + (to - from) * e));
    if (k < 1) el._raf = requestAnimationFrame(step);
  };
  el._raf = requestAnimationFrame(step);
}

// ── празднования ──
export function burst(x, y, count = 22, art) {
  const box = document.body.appendChild(h('div', { class: 'burst' }));
  for (let i = 0; i < count; i++) {
    const a = Math.random() * Math.PI * 2, d = 90 + Math.random() * 170;
    const el = h('i', { html: art, style: { left: x - 13 + 'px', top: y - 13 + 'px', '--x': Math.cos(a) * d + 'px',
      '--y': Math.sin(a) * d - 60 + 'px', '--r': (Math.random() * 720 - 360) + 'deg', '--t': (0.9 + Math.random() * 0.8) + 's' } });
    box.append(el);
  }
  setTimeout(() => box.remove(), 1900);
}
export function bigWin(mult, amount, art) {
  const el = document.body.appendChild(h('div', { class: 'bigwin' }, h('div', null,
    h('div', { class: 'bw-x' }, fx(mult)), h('div', { class: 'bw-a' }, '+' + fmt(amount)))));
  burst(innerWidth / 2, innerHeight / 2, 34, art);
  sfx.big(); haptic('success');
  setTimeout(() => el.remove(), 2300);
}

// ── нижние листы ──
export function sheet(build, { onClose } = {}) {
  const scrim = h('div', { class: 'scrim' });
  const box = h('div', { class: 'sheet' }, h('div', { class: 'grab' }));
  scrim.append(box);
  const close = () => {
    if (!scrim.isConnected) return;
    scrim.classList.remove('on'); setTimeout(() => scrim.remove(), 300);
    popBack(close); onClose?.();
  };
  scrim.addEventListener('click', (e) => { if (e.target === scrim) close(); });
  build(box, close);
  document.body.append(scrim);
  requestAnimationFrame(() => requestAnimationFrame(() => scrim.classList.add('on')));
  pushBack(close);
  return close;
}

// ── кнопка «Назад» Telegram: стек обработчиков ──
const backStack = [];
export const tgv = (v) => !!tg?.isVersionAtLeast?.(v);
function syncBack() {
  const bb = tg?.BackButton; if (!bb || !tgv('6.1')) return;
  backStack.length ? bb.show() : bb.hide();
}
export function pushBack(fn) { backStack.push(fn); syncBack(); }
export function popBack(fn) { const i = backStack.lastIndexOf(fn); if (i >= 0) backStack.splice(i, 1); syncBack(); }
export function goBack() { const fn = backStack[backStack.length - 1]; if (fn) fn(); }
if (tgv('6.1')) tg.BackButton.onClick(goBack);

// ── кнопка с ожиданием ──
export async function busy(btn, fn) {
  if (btn.classList.contains('busy')) return;
  btn.classList.add('busy');
  try { return await fn(); } finally { btn.classList.remove('busy'); }
}

// ── опрос сервера ──
let pollTimer = null, pollScope = 'lobby', pollEvery = 4000, pollScreen = 'lobby', pollBusy = false;
export function setPoll(scope, every, screen = scope) {
  pollScope = scope; pollEvery = every; pollScreen = screen; S.screen = screen;
  clearTimeout(pollTimer); pollTimer = setTimeout(pollNow, 30);
}
export async function pollNow() {
  clearTimeout(pollTimer);
  if (document.hidden) { pollTimer = setTimeout(pollNow, 2000); return; }
  if (!pollBusy) {
    pollBusy = true;
    const scope = pollScope;
    try {
      const d = await api('poll', { scope, screen: pollScreen }, { quiet: true });
      if (d.online) S.online = d.online;
      if (d.tables) S.tables = d.tables;
      if (d.feed) S.feed = d.feed;
      if (d.timers) S.timers = d.timers;
      if (d.tasks) S.tasks = d.tasks;
      if (d.fire) S.fire = d.fire;
      if (typeof d.rake === 'number' && S.me) S.me.rake = d.rake;
      emit('poll', d);
    } catch (e) { if (e.status === 401 || e.status === 403) emit('fatal', e); }
    pollBusy = false;
  }
  pollTimer = setTimeout(pollNow, pollEvery);
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) pollNow(); });

// ── таймер-тикер для обратных отсчётов ──
const tickers = new Set();
export function ticker(fn) { tickers.add(fn); fn(); return () => tickers.delete(fn); }
setInterval(() => tickers.forEach((fn) => { try { fn(); } catch (e) { console.error(e); } }), 500);
