// Общие игровые компоненты: панель ставки, карты, баннер результата, празднования.
import { h, S, fmt, fmtc, fx, prefs, clamp, sfx, haptic, toast, burst, bigWin, on } from './core.js';
import { CUR, CARD_BACK, SPORE } from './art.js';

export const cur = () => h('span', { class: 'cur', html: CUR });
export const money = (n, cls = '') => h('span', { class: 'num ' + cls }, fmt(n), ' ', cur());

export function betPanel(game, { label = 'Ставка', onChange } = {}) {
  const min = S.cfg?.min_bet || 10, max = S.cfg?.max_bet || 1e9;
  const cap = () => Math.max(min, Math.min(max, S.balance));
  let value = clamp(prefs.get('bet_' + game, Math.max(min, Math.min(1000, Math.floor(S.balance / 20) || min))), min, max);
  const input = h('input', { inputmode: 'numeric', enterkeyhint: 'done', 'aria-label': label });
  const show = () => { input.value = fmt(value); onChange?.(value); };
  const set = (v) => { value = clamp(Math.floor(v) || min, min, max); prefs.set('bet_' + game, value); show(); sfx.chip(); haptic('select'); };
  input.addEventListener('focus', () => { input.value = String(value); setTimeout(() => input.select(), 0); });
  input.addEventListener('blur', () => set(Number(String(input.value).replace(/\D/g, '')) || min));
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') input.blur(); });
  const stepv = (dir) => { const mag = Math.pow(10, Math.max(1, Math.floor(Math.log10(Math.max(value, 10))) - (dir < 0 && /^10*$/.test(String(value)) ? 1 : 0))); set(dir > 0 ? value + mag : value - mag); };
  const chip = (txt, fn) => h('button', { onclick: fn }, txt);
  const el = h('div', { class: 'betbox' },
    h('div', { class: 'betlbl' }, h('span', null, label), h('span', null, 'Баланс: ', fmtc(S.balance))),
    h('div', { class: 'betrow' },
      h('button', { class: 'step', onclick: () => stepv(-1), 'aria-label': 'Меньше' }, '−'),
      h('div', { class: 'betval' }, h('span', { class: 'cur', html: CUR }), input),
      h('button', { class: 'step', onclick: () => stepv(1), 'aria-label': 'Больше' }, '+')),
    h('div', { class: 'chips' },
      chip('Мин', () => set(min)), chip('½', () => set(value / 2)), chip('×2', () => set(value * 2)),
      chip('10%', () => set(cap() * 0.1)), chip('Всё', () => set(cap()))));
  const bal = el.querySelector('.betlbl span:last-child');
  const off = on('balance', ({ v }) => { bal.textContent = 'Баланс: ' + fmtc(v); });
  show();
  return { el, get: () => value, set, destroy: off, lock(v) { el.style.opacity = v ? .5 : 1; el.style.pointerEvents = v ? 'none' : ''; } };
}

const SUIT = { s: '♠', h: '♥', d: '♦', c: '♣' };
const RANK = { T: '10', J: 'J', Q: 'Q', K: 'K', A: 'A' };
export function pcard(code, { down = false, deal = false, dx = 120, dy = -160, delay = 0 } = {}) {
  const hidden = !code || code === '??';
  const r = hidden ? '' : (RANK[code[0]] || code[0]), s = hidden ? '' : SUIT[code[1]];
  const red = !hidden && (code[1] === 'h' || code[1] === 'd');
  const el = h('div', { class: 'pcard' + (down || hidden ? ' down' : '') + (deal ? ' deal' : ''),
    style: { '--dx': dx + 'px', '--dy': dy + 'px', animationDelay: delay + 'ms' } },
    h('div', { class: 'in' },
      h('div', { class: 'face' + (red ? ' r' : '') },
        h('div', { class: 'cr' }, r, h('i', null, s)), h('div', { class: 'pip' }, s), h('div', { class: 'cr b' }, r, h('i', null, s))),
      h('div', { class: 'back', html: CARD_BACK })));
  el.flipTo = (c) => {
    const nr = RANK[c[0]] || c[0], ns = SUIT[c[1]], nred = c[1] === 'h' || c[1] === 'd';
    const face = el.querySelector('.face'); face.classList.toggle('r', nred);
    face.querySelectorAll('.cr').forEach((x) => { x.firstChild.textContent = nr; x.querySelector('i').textContent = ns; });
    face.querySelector('.pip').textContent = ns;
    requestAnimationFrame(() => el.classList.remove('down'));
    sfx.card();
  };
  return el;
}

export function banner(parent) {
  const t = h('div', { class: 'rb-t' }), s = h('div', { class: 'rb-s' });
  const el = h('div', { class: 'result-banner' }, t, s);
  parent.append(el);
  let timer = 0;
  return {
    show(title, sub = '', kind = '', ms = 2200) {
      t.textContent = title; s.textContent = sub; el.className = 'result-banner on ' + kind;
      clearTimeout(timer); if (ms) timer = setTimeout(() => el.classList.remove('on'), ms);
    },
    hide() { el.classList.remove('on'); },
  };
}

// Итог ставки: звук, вибрация, празднование, события уровня/ачивок.
export function celebrate(res, anchor) {
  const wager = res.wager ?? res.bet ?? 0, pay = res.payout ?? 0;
  const mult = wager ? pay / wager : 0;
  if (pay > wager) {
    if (mult >= 10 || pay - wager >= 100000) bigWin(mult, pay - wager, SPORE);
    else {
      sfx.win(); haptic('success');
      const r = anchor?.getBoundingClientRect?.();
      if (r) burst(r.left + r.width / 2, r.top + r.height / 2, mult >= 3 ? 22 : 12, SPORE);
    }
  } else if (pay === wager && wager) { sfx.tap(); haptic('light'); }
  else if (wager) { sfx.lose(); haptic('warning'); }
  events(res.events);
}
export function events(list) {
  for (const ev of list || []) {
    if (ev.type === 'level') { toast(`⭐ Новый уровень ${ev.level} · ${ev.title}`, 'gold', 4200); sfx.big(); }
    if (ev.type === 'ach') toast(`🏅 Достижение: «${ev.name}»`, 'gold', 4200);
  }
}
export function outcome(res) {
  const wager = res.wager ?? res.bet ?? 0, pay = res.payout ?? 0;
  if (pay > wager) return { title: '+' + fmt(pay - wager), sub: fx(pay / wager), kind: 'win' };
  if (pay === wager && wager) return { title: 'Возврат', sub: fmt(pay), kind: '' };
  return { title: '−' + fmt(wager), sub: 'мимо', kind: 'lose' };
}

export function ringTimer(size = 100, color = 'var(--gold)') {
  const r = size / 2 - 3, c = 2 * Math.PI * r;
  const arc = h('svg:circle', { cx: size / 2, cy: size / 2, r, fill: 'none', stroke: color, 'stroke-width': 3, 'stroke-linecap': 'round',
    'stroke-dasharray': c, 'stroke-dashoffset': 0 });
  const el = h('svg:svg', { class: 'ring-timer', viewBox: `0 0 ${size} ${size}` },
    h('svg:circle', { cx: size / 2, cy: size / 2, r, fill: 'none', stroke: 'rgba(243,234,219,.08)', 'stroke-width': 3 }), arc);
  return { el, set(k) { arc.setAttribute('stroke-dashoffset', String(c * (1 - clamp(k, 0, 1)))); } };
}

export const ACT_LABEL = { lobby: 'в зале', games: 'выбирает игру', top: 'смотрит топ', profile: 'в профиле', bj: 'за блэкджеком',
  slots: 'крутит слоты', roulette: 'у рулетки', crash: 'в краше', dice: 'бросает кости', cups: 'в напёрстках', mines: 'на тихой охоте',
  baccarat: 'за баккарой', poker: 'в видео-покере', rps: 'играет с ИИ', jackpot: 'в складчине', duel: 'на дуэлях', wheel: 'крутит колесо' };
