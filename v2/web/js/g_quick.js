// Быстрые игры: Слоты, Кости, Напёрстки, КНБ против ИИ.
import { h, S, api, fmt, fx, sleep, sfx, haptic, busy, clamp } from './core.js';
import { sym, SYMS, ORACLE, russula } from './art.js';
import { betPanel, banner, celebrate, outcome } from './ui.js';

const SYM_H = 82;
const rnd = (a) => a[Math.floor(Math.random() * a.length)];
const symEl = (k) => h('div', { class: 'sym', html: sym[k] });
const signed = (n) => (n > 0 ? '+' + fmt(n) : n < 0 ? '−' + fmt(-n) : 'в ноль');

// ───────────── Слоты ─────────────
export function slots(root) {
  const strips = [], reels = [];
  const win = h('div', { class: 'slot-win' });
  for (let i = 0; i < 3; i++) {
    const strip = h('div', { class: 'strip' });
    for (let j = 0; j < 3; j++) strip.append(symEl(rnd(SYMS)));
    const reel = h('div', { class: 'reel' }, strip);
    strips.push(strip); reels.push(reel); win.append(reel);
  }
  const line = h('div', { class: 'payline' });
  win.append(line);
  const lamps = h('div', { class: 'slot-lamps' }, Array.from({ length: 9 }, () => h('i')));
  const machine = h('div', { class: 'slot stage' }, lamps, win);
  const ban = banner(machine);
  const bet = betPanel('slots');
  const go = h('button', { class: 'btn red big wide', onclick: () => busy(go, spin) }, 'Крутить');
  root.append(machine, bet.el, go);

  async function spin() {
    ban.hide(); line.classList.remove('on');
    const r = await api('play/slots', { bet: bet.get() });
    machine.classList.add('spinning'); haptic('light');
    const durs = [950, 1350, 1750];
    r.reels.forEach((col, i) => {
      const strip = strips[i];
      const prev = [...strip.children].slice(0, 3).map((el) => el.cloneNode(true));
      const n = 14 + i * 5;
      strip.replaceChildren(...col.map(symEl), ...Array.from({ length: n }, () => symEl(rnd(SYMS))), ...prev);
      strip.style.transition = 'none';
      strip.style.transform = `translateY(${-(n + 3) * SYM_H}px)`;
      strip.style.filter = 'blur(1.6px)';
      void strip.offsetHeight;
      strip.style.transition = `transform ${durs[i]}ms cubic-bezier(.17,.84,.3,1.04)`;
      strip.style.transform = 'translateY(0)';
      setTimeout(() => { strip.style.filter = ''; sfx.tick(); haptic('light'); }, durs[i] - 160);
    });
    let ticks = 0;
    const iv = setInterval(() => { if (ticks++ < 14) sfx.tick(); }, 110);
    await sleep(durs[2] + 80);
    clearInterval(iv);
    machine.classList.remove('spinning');
    // повторная сборка ленты: только видимые 3 символа
    r.reels.forEach((col, i) => { strips[i].style.transition = 'none'; strips[i].replaceChildren(...col.map(symEl)); strips[i].style.transform = 'translateY(0)'; });
    if (r.payout > 0) line.classList.add('on');
    const names = { three: 'Три в ряд!', pair: 'Пара', two_shrooms: 'Две сыроежки', one_shroom: 'Сыроежка', none: 'Мимо' };
    const oc = outcome(r);
    ban.show(r.payout ? (r.kind === 'three' && r.reels[0][1] === 'shroom' ? 'ДЖЕКПОТ!' : names[r.kind]) : 'Мимо', r.payout ? signed(r.payout - r.bet) + ' · ' + fx(r.mult) : '−' + fmt(r.bet), r.payout > r.bet ? 'win' : oc.kind, 1800);
    celebrate(r, machine);
  }
  return { destroy: bet.destroy };
}

// ───────────── Кости ─────────────
const PIPS = { 1: [5], 2: [1, 9], 3: [1, 5, 9], 4: [1, 3, 7, 9], 5: [1, 3, 5, 7, 9], 6: [1, 3, 4, 6, 7, 9] };
const FACE_ROT = { 1: [0, 0], 6: [0, 180], 2: [0, -90], 5: [0, 90], 3: [90, 0], 4: [-90, 0] };
function dieEl() {
  const cube = h('div', { class: 'die' });
  for (let n = 1; n <= 6; n++) {
    const f = h('div', { class: 'f f' + n });
    for (let p = 1; p <= 9; p++) f.append(PIPS[n].includes(p) ? h('i', { style: n === 1 ? { background: '#c8372b', width: '18px', height: '18px' } : null }) : h('s'));
    cube.append(f);
  }
  return cube;
}
export function dice(root) {
  const d1 = dieEl(), d2 = dieEl();
  const box = h('div', { class: 'dicebox' }, h('div', { style: { position: 'relative' } }, d1, h('div', { class: 'dshadow' })), h('div', { style: { position: 'relative' } }, d2, h('div', { class: 'dshadow' })));
  const sum = h('div', { class: 'num', style: { textAlign: 'center', fontSize: '15px', color: 'var(--muted)', marginTop: '-6px', paddingBottom: '14px' } }, 'Сумма: —');
  const stage = h('div', { class: 'felt stage', style: { background: 'radial-gradient(120% 90% at 50% 20%,#4a3d2c,#3d3326 50%,#2c241b)', borderColor: '#57472f' } }, box, sum);
  const ban = banner(stage);
  let pick = 'hi', turns = 0;
  const picks = h('div', { class: 'picks' });
  for (const [id, d] of Object.entries(S.cfg.dice)) {
    picks.append(h('button', { class: 'pick' + (id === pick ? ' on' : ''), onclick: (e) => { pick = id; [...picks.children].forEach((b) => b.classList.remove('on')); e.currentTarget.classList.add('on'); sfx.chip(); haptic('select'); } },
      h('b', null, d.label), h('span', null, fx(d.mult))));
  }
  const bet = betPanel('dice');
  const go = h('button', { class: 'btn red big wide', onclick: () => busy(go, roll) }, 'Бросить');
  root.append(stage, picks, bet.el, go);
  const setFace = (cube, n, k) => { const [x, y] = FACE_ROT[n]; cube.style.transform = `rotateX(${k * 360 + x + (k ? 720 : 0)}deg) rotateY(${k * 360 + y + (k ? 360 : 0)}deg) rotateZ(${k ? (Math.random() * 30 - 15) : 0}deg)`; };
  setFace(d1, 5, 0); setFace(d2, 2, 0);
  async function roll() {
    ban.hide();
    const r = await api('play/dice', { bet: bet.get(), pick });
    turns += 1; sfx.roll(); haptic('medium');
    setFace(d1, r.dice[0], turns); setFace(d2, r.dice[1], turns + 0.5 > turns ? turns : turns);
    await sleep(1250);
    sum.textContent = `Сумма: ${r.sum}${r.dice[0] === r.dice[1] ? ' · дубль' : ''}`;
    const oc = outcome(r);
    ban.show(r.payout ? 'Угадал!' : 'Мимо', r.payout ? '+' + fmt(r.payout - r.bet) : '−' + fmt(r.bet), oc.kind, 1800);
    celebrate(r, stage);
  }
  return { destroy: bet.destroy };
}

// ───────────── Напёрстки ─────────────
const CUP_SVG = '<svg viewBox="0 0 84 120"><path d="M14 112 24 14h36l10 98z" fill="#a8632f"/><path d="M8 108h68v12H8z" rx="4" fill="#7a431d"/><path d="M22 10h40v10H22z" fill="#c98a45"/><path d="M32 24l-7 80" stroke="#fff" stroke-opacity=".22" stroke-width="5" stroke-linecap="round"/><path d="M58 24l6 78" stroke="#000" stroke-opacity=".15" stroke-width="6" stroke-linecap="round"/></svg>';
export function cups(root) {
  let count = 3, phase = 'idle', els = [], slots = [];
  const area = h('div', { class: 'cups' }, h('div', { class: 'cupsfloor' }));
  const hint = h('div', { class: 'felt-title', style: { textAlign: 'center', padding: '14px 0 0' } }, 'Сделай ставку и нажми «Играть»');
  const stage = h('div', { class: 'felt stage', style: { padding: '0 10px', background: 'radial-gradient(120% 90% at 50% 20%,#5a3a26,#4a2f1f 50%,#35210f)', borderColor: '#6b4428' } }, hint, area);
  const ban = banner(stage);
  const seg = h('div', { class: 'segpick' });
  const bet = betPanel('cups');
  const go = h('button', { class: 'btn red big wide', onclick: () => busy(go, startRound) }, 'Играть');
  for (const n of [3, 4, 5]) seg.append(h('button', { class: n === count ? 'on' : '', onclick: (e) => { if (phase !== 'idle') return; count = n; [...seg.children].forEach((b) => b.classList.remove('on')); e.currentTarget.classList.add('on'); build(); sfx.chip(); } },
    `${n} · ${fx(S.cfg.cups[n])}`));
  root.append(stage, seg, bet.el, go);
  function build() {
    area.querySelectorAll('.cupw').forEach((e) => e.remove());
    const W = area.clientWidth || innerWidth - 50, cw = Math.min(84, Math.floor(W / count) - 8);
    area.style.setProperty('--cupw', cw + 'px');
    slots = Array.from({ length: count }, (_, i) => Math.round((W / count) * i + (W / count - cw) / 2));
    els = slots.map((x, i) => {
      const el = h('div', { class: 'cupw', style: { left: x + 'px' } }, h('div', { class: 'ball', html: `<svg viewBox="0 0 64 64">${russula(0, 2)}</svg>` }), h('div', { class: 'cupi', html: CUP_SVG }));
      el.dataset.slot = i;
      el.addEventListener('click', () => choose(el));
      area.append(el);
      return el;
    });
  }
  requestAnimationFrame(build);
  async function startRound() {
    if (phase !== 'idle') return;
    if (S.balance < bet.get()) { api('play/cups', { bet: bet.get(), count, pick: 0 }).catch(() => {}); return; }
    phase = 'shuffle'; ban.hide(); bet.lock(true); go.classList.add('off');
    els.forEach((e) => e.classList.remove('lift', 'show', 'chosen'));
    hint.textContent = 'Сыроежка прячется…';
    const pos = els.map((_, i) => i);
    for (let k = 0; k < 6 + count; k++) {
      const a = Math.floor(Math.random() * count); let b = Math.floor(Math.random() * (count - 1)); if (b >= a) b++;
      [pos[a], pos[b]] = [pos[b], pos[a]];
      els[a].style.left = slots[pos[a]] + 'px'; els[b].style.left = slots[pos[b]] + 'px';
      sfx.tick(); await sleep(340);
    }
    els.forEach((e, i) => { e.dataset.slot = pos[i]; e.classList.add('pickable'); });
    hint.textContent = 'Где сыроежка?'; haptic('light');
    phase = 'pick';
  }
  async function choose(el) {
    if (phase !== 'pick') return;
    phase = 'wait';
    els.forEach((e) => e.classList.remove('pickable'));
    el.classList.add('chosen');
    const pick = Number(el.dataset.slot);
    let r;
    try { r = await api('play/cups', { bet: bet.get(), count, pick }); } catch { phase = 'idle'; bet.lock(false); go.classList.remove('off'); hint.textContent = 'Сделай ставку и нажми «Играть»'; return; }
    const ballEl = els.find((e) => Number(e.dataset.slot) === r.ball);
    ballEl.classList.add('show');
    el.classList.add('lift'); sfx.card();
    if (ballEl !== el) { await sleep(450); ballEl.classList.add('lift'); }
    hint.textContent = r.payout ? 'Нашёл!' : 'Не угадал';
    const oc = outcome(r);
    ban.show(r.payout ? 'Нашёл!' : 'Пусто', r.payout ? '+' + fmt(r.payout - r.bet) : '−' + fmt(r.bet), oc.kind, 1800);
    celebrate(r, stage);
    await sleep(1600);
    els.forEach((e) => e.classList.remove('lift', 'chosen'));
    await sleep(300);
    els.forEach((e) => e.classList.remove('show'));
    phase = 'idle'; bet.lock(false); go.classList.remove('off'); hint.textContent = 'Ещё раз?';
  }
  return { destroy: bet.destroy };
}

// ───────────── КНБ против ИИ ─────────────
const HANDS = { rock: '✊', scissors: '✌️', paper: '✋' };
const NAMES = { rock: 'Камень', scissors: 'Ножницы', paper: 'Бумага' };
export function rps(root) {
  const meter = h('i', { style: { width: '0%' } });
  const readTxt = h('div', { class: 'muted', style: { fontSize: '12.5px' } }, 'Пока не раскусил. Сыграй пару раундов.');
  const score = { win: 0, lose: 0, draw: 0 };
  const scoreEl = h('div', { class: 'num', style: { fontSize: '13px' } });
  const showScore = () => { scoreEl.textContent = `${score.win} : ${score.lose}` + (score.draw ? ` · ничьих ${score.draw}` : ''); };
  showScore();
  const oracle = h('div', { class: 'card' }, h('div', { class: 'oracle' }, h('div', { html: ORACLE }),
    h('div', { class: 'grow' }, h('div', { class: 'row' }, h('b', { class: 'fd', style: { fontSize: '14px' } }, 'Грибной оракул'), h('span', { class: 'grow' }), scoreEl),
      readTxt, h('div', { class: 'meter' }, meter))));
  const you = h('div', { class: 'hand' }, '✊'), ai = h('div', { class: 'hand' }, '✊');
  const arena = h('div', { class: 'rps' }, h('div', { class: 'side' }, you, h('div', { class: 'who' }, 'Ты')), h('div', { class: 'vs' }, 'VS'),
    h('div', { class: 'side ai' }, ai, h('div', { class: 'who' }, 'Оракул')));
  const stage = h('div', { class: 'felt stage', style: { background: 'radial-gradient(120% 90% at 50% 20%,#7a5a26,#6b4a1a 50%,#4a320f)', borderColor: '#86602a' } }, arena);
  const ban = banner(stage);
  const bet = betPanel('rps');
  const moves = h('div', { class: 'moves' });
  let busyFlag = false;
  for (const m of Object.keys(HANDS)) moves.append(h('button', { class: 'move', onclick: () => play(m) }, HANDS[m], h('span', null, NAMES[m])));
  root.append(oracle, stage, moves, bet.el);
  async function play(move) {
    if (busyFlag) return; busyFlag = true; ban.hide();
    you.textContent = '✊'; ai.textContent = '✊';
    arena.classList.remove('shake'); void arena.offsetWidth; arena.classList.add('shake');
    sfx.tap(); haptic('light');
    let r;
    try { [r] = await Promise.all([api('play/rps', { bet: bet.get(), move }), sleep(900)]); } catch { arena.classList.remove('shake'); busyFlag = false; return; }
    arena.classList.remove('shake');
    you.textContent = HANDS[move]; ai.textContent = HANDS[r.ai];
    score[r.outcome] += 1; showScore();
    meter.style.width = clamp(r.read, 0, 100) + '%';
    readTxt.textContent = r.read ? `Угадывает твой ход с уверенностью ${r.read}%` : 'Пока не раскусил. Играй хаотично!';
    const t = { win: 'Ты победил!', lose: 'Оракул угадал', draw: 'Ничья' }[r.outcome];
    ban.show(t, r.outcome === 'win' ? '+' + fmt(r.payout - r.bet) : r.outcome === 'draw' ? 'ставка возвращена' : '−' + fmt(r.bet), outcome(r).kind, 1600);
    celebrate(r, stage);
    busyFlag = false;
  }
  return { destroy: bet.destroy };
}
