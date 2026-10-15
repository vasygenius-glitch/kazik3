// Тихая охота: поле 5×5, сыроежки и мухоморы. Каждая находка повышает множитель.
import { h, S, api, fmt, fx, sleep, sfx, haptic, busy, prefs, burst } from './core.js';
import { russula, amanita, SPORE } from './art.js';
import { betPanel, banner, celebrate } from './ui.js';

const CELLS = 25;
const COUNTS = [1, 3, 5, 10, 20];
const svg = (body) => `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">${body}</svg>`;
const LEAF = svg('<path d="M14 46c2-18 16-30 36-32-1 20-13 34-32 35l-4 5-3-2 4-5z" fill="#2c3b1e"/><path d="M19 45c7-9 15-16 26-25" stroke="#5e7a3e" stroke-width="2.4" fill="none" stroke-linecap="round"/>');
const FOUND = svg(russula(0, 4));
const BAD = svg(amanita(0, 4));

export function minesMult(m, k) {
  let x = S.cfg?.rtp ?? 0.97;
  for (let i = 0; i < k; i++) x *= (CELLS - i) / (CELLS - m - i);
  return Math.floor(x * 100 + 1e-7) / 100;
}

export function mines(root, opts = {}) {
  let m = COUNTS.includes(prefs.get('mines_m', 3)) ? prefs.get('mines_m', 3) : 3;
  let game = null; // {bet, mines, open: []}
  let pending = false;

  const cells = [];
  const grid = h('div', { class: 'mines' });
  for (let i = 0; i < CELLS; i++) {
    const c = h('button', { class: 'mcell', 'aria-label': 'Клетка ' + (i + 1), onclick: () => pick(i) },
      h('div', { class: 'in' }, h('div', { class: 'fr', html: LEAF }), h('div', { class: 'bk' })));
    cells.push(c); grid.append(c);
  }
  const stage = h('div', { class: 'stage' }, grid);
  const ban = banner(stage);

  const vMult = h('b', { class: 'num' }, '—'), vNext = h('b', { class: 'num' }, '—'), vChance = h('b', { class: 'num' }, '—');
  const stats = h('div', { class: 'stats mstats' },
    h('div', { class: 'stat' }, vMult, h('span', null, 'множитель')),
    h('div', { class: 'stat' }, vNext, h('span', null, 'следующая')),
    h('div', { class: 'stat' }, vChance, h('span', null, 'шанс сыроежки')));
  const ladder = h('div', { class: 'ladder' });

  const seg = h('div', { class: 'segpick' });
  const segBtns = COUNTS.map((n) => h('button', { class: n === m ? 'on' : '', onclick: () => setM(n) }, h('span', { html: svg(amanita(0, 4)), class: 'segico' }), String(n)));
  seg.append(...segBtns);
  const segWrap = h('div', { class: 'col', style: { gap: '7px' } }, h('div', { class: 'betlbl' }, h('span', null, 'Мухоморов на поле'), h('span', null, 'больше — дороже каждая находка')), seg);

  const bet = betPanel('mines');
  const startBtn = h('button', { class: 'btn red big wide', onclick: () => busy(startBtn, start) }, 'Начать охоту');
  const cashBtn = h('button', { class: 'btn gold big grow', onclick: () => busy(cashBtn, cash) }, 'Забрать');
  const randBtn = h('button', { class: 'btn ghost big', style: { width: '68px', flex: 'none' }, 'aria-label': 'Случайная клетка', onclick: randomPick }, '🎲');
  const playRow = h('div', { class: 'row hidden' }, randBtn, cashBtn);

  root.append(stage, stats, ladder, segWrap, bet.el, startBtn, playRow);

  function setM(n) {
    if (game) return;
    m = n; prefs.set('mines_m', n);
    segBtns.forEach((b, i) => b.classList.toggle('on', COUNTS[i] === n));
    sfx.chip(); haptic('select');
    renderInfo();
  }

  function renderLadder(k) {
    const mm = game ? game.mines : m, max = CELLS - mm;
    ladder.replaceChildren();
    for (let i = 1; i <= Math.min(max, 24); i++) {
      ladder.append(h('span', { class: i === k ? 'now' : i === k + 1 ? 'next' : '' }, fx(minesMult(mm, i))));
    }
    const target = ladder.children[Math.max(0, k - 2)];
    if (target) ladder.scrollTo({ left: target.offsetLeft - ladder.offsetLeft, behavior: 'smooth' });
  }

  function renderInfo() {
    const mm = game ? game.mines : m, k = game ? game.open.length : 0;
    const left = CELLS - mm - k, closed = CELLS - k;
    vMult.textContent = k ? fx(minesMult(mm, k)) : '—';
    vNext.textContent = left > 0 ? fx(minesMult(mm, k + 1)) : '—';
    vChance.textContent = left > 0 ? Math.round((left / closed) * 100) + '%' : '—';
    renderLadder(k);
    if (game) {
      const pay = Math.floor(game.bet * minesMult(mm, k));
      cashBtn.textContent = k ? 'Забрать ' + fmt(pay) : 'Найди сыроежку';
      cashBtn.disabled = !k;
      cashBtn.style.opacity = k ? 1 : 0.55;
    }
  }

  function resetField() {
    cells.forEach((c) => { c.className = 'mcell'; c.querySelector('.bk').innerHTML = ''; });
  }

  function setPlaying(on) {
    startBtn.classList.toggle('hidden', on);
    playRow.classList.toggle('hidden', !on);
    bet.lock(on);
    seg.style.opacity = on ? 0.5 : 1; seg.style.pointerEvents = on ? 'none' : '';
    cells.forEach((c) => c.classList.toggle('live', on && !c.classList.contains('open')));
  }

  function openCell(i, good, { ghost = false, boom = false } = {}) {
    const c = cells[i];
    c.querySelector('.bk').innerHTML = good ? FOUND : BAD;
    c.classList.remove('live');
    c.classList.add('open');
    if (ghost) c.classList.add('ghost', good ? 'safe' : 'bad');
    if (boom) c.classList.add('boom');
  }

  function apply(v) {
    game = { bet: v.bet, mines: v.mines, open: [...v.open] };
    resetField();
    v.open.forEach((i) => openCell(i, true));
    setPlaying(true);
    renderInfo();
  }

  async function revealAll(v, picked) {
    const field = new Set(v.field || []);
    const rest = [];
    for (let i = 0; i < CELLS; i++) if (!picked.has(i) && i !== v.boom) rest.push(i);
    rest.sort(() => Math.random() - 0.5);
    for (const i of rest) { openCell(i, !field.has(i), { ghost: true }); await sleep(18); }
  }

  async function start() {
    ban.hide();
    const v = await api('play/mines', { action: 'start', bet: bet.get(), mines: m });
    haptic('medium'); sfx.chip();
    grid.classList.remove('shake'); grid.classList.add('fresh');
    setTimeout(() => grid.classList.remove('fresh'), 500);
    apply(v);
  }

  async function pick(i) {
    if (!game || pending || cells[i].classList.contains('open')) return;
    pending = true;
    const c = cells[i];
    c.classList.add('wait');
    let v;
    try { v = await api('play/mines', { action: 'pick', cell: i }); } catch { c.classList.remove('wait'); pending = false; return; }
    c.classList.remove('wait');
    if (v.boom != null) {
      openCell(i, false, { boom: true });
      sfx.boom(); haptic('error');
      grid.classList.remove('shake'); void grid.offsetWidth; grid.classList.add('shake');
      const picked = new Set(game.open);
      game = null; setPlaying(false);
      await sleep(380);
      await revealAll(v, picked);
      ban.show('Мухомор!', '−' + fmt(v.wager), 'lose', 2400);
      celebrate(v, grid);
      vMult.textContent = 'x0'; vNext.textContent = '—'; vChance.textContent = '—';
      pending = false;
      return;
    }
    openCell(i, true);
    sfx.coin(); haptic('light');
    const r = c.getBoundingClientRect();
    burst(r.left + r.width / 2, r.top + r.height / 2, 7, SPORE);
    game.open = [...v.open];
    if (v.done) await finish(v); else renderInfo();
    pending = false;
  }

  function randomPick() {
    if (!game || pending) return;
    const free = cells.map((c, i) => (c.classList.contains('open') ? -1 : i)).filter((i) => i >= 0);
    if (free.length) { sfx.tap(); pick(free[Math.floor(Math.random() * free.length)]); }
  }

  async function finish(v) {
    const picked = new Set(game?.open || v.open);
    game = null; setPlaying(false);
    renderInfo();
    vMult.textContent = fx(v.mult || (v.wager ? v.payout / v.wager : 0)); vNext.textContent = '—'; vChance.textContent = '—';
    await revealAll(v, picked);
    ban.show('+' + fmt(v.payout - v.wager), fx(v.payout / v.wager) + ' · ' + picked.size + ' ' + (picked.size === 1 ? 'сыроежка' : picked.size < 5 ? 'сыроежки' : 'сыроежек'), 'win', 2600);
    celebrate(v, grid);
  }

  async function cash() {
    if (!game || !game.open.length || pending) return;
    pending = true;
    try {
      const v = await api('play/mines', { action: 'cash' });
      await finish(v);
    } finally { pending = false; }
  }

  if (opts.resume) apply(opts.resume); else renderInfo();
  return { destroy: bet.destroy };
}
