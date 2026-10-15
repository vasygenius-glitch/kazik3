// Точка входа: Telegram, оболочка, вкладки и слой игр.
import { h, $, tg, tgv, S, api, on, emit, setPoll, pushBack, popBack, fmt, roll, sfx, haptic, toast, ApiErr } from './core.js';
import { LOGO, CUR, icons } from './art.js';
import { mountLobby } from './lobby.js';
import { mountGames, GAMES, rules } from './games.js';
import { mountTop, mountProfile } from './screens.js';

const TABS = [
  { id: 'lobby', name: 'Зал', icon: icons.hall, scope: 'lobby', every: 4000 },
  { id: 'games', name: 'Игры', icon: icons.games, scope: 'games', every: 9000 },
  { id: 'top', name: 'Топ', icon: icons.top, scope: 'top', every: 12000 },
  { id: 'me', name: 'Профиль', icon: icons.me, scope: 'profile', every: 12000 },
];
const pages = {}, tabs = {};
let current = 'lobby', layer = null;

function setupTelegram() {
  if (!tg) return;
  try {
    tg.ready(); tg.expand();
    if (tgv('6.1')) { tg.setHeaderColor('#12100e'); tg.setBackgroundColor('#12100e'); }
    if (tgv('7.10')) tg.setBottomBarColor('#12100e');
    if (tgv('7.7')) tg.disableVerticalSwipes();
  } catch { /* старые клиенты */ }
}

function fatal(text, sub) {
  const boot = $('#boot') || document.body.appendChild(h('div', { class: 'boot', id: 'boot' }));
  boot.classList.remove('hidden');
  boot.replaceChildren(h('div', { class: 'boot-mark', html: LOGO.replace('class="brand-mark"', '') }),
    h('div', { class: 'boot-title' }, 'Казик'), h('div', { class: 'boot-sub' }, text),
    sub ? h('div', { class: 'boot-sub', style: { fontSize: '12.5px', color: 'var(--dim)' } }, sub) : null,
    tg ? h('button', { class: 'btn red', onclick: () => tg.close() }, 'Закрыть') : null);
}

function shell() {
  const bal = h('span', { class: 'num' }, fmt(S.balance));
  const pill = h('div', { class: 'balance' }, h('span', { class: 'cur', html: CUR }), bal);
  const top = h('header', { class: 'topbar' },
    h('div', { class: 'brand' }, h('div', { html: LOGO }),
      h('div', { class: 'brand-txt' }, h('div', { class: 'brand-name' }, 'Казик'), h('div', { class: 'brand-chat ellipsis' }, S.chat?.title || ''))),
    pill);
  on('balance', ({ old, v }) => {
    roll(bal, old, v, 650);
    pill.classList.remove('up', 'down'); void pill.offsetWidth;
    pill.classList.add(v > old ? 'up' : 'down');
    clearTimeout(pill._t); pill._t = setTimeout(() => pill.classList.remove('up', 'down'), 900);
  });
  const box = h('main', { class: 'pages' });
  const bar = h('nav', { class: 'tabbar' });
  for (const t of TABS) {
    pages[t.id] = h('section', { class: 'page' });
    box.append(pages[t.id]);
    tabs[t.id] = h('button', { class: 'tab', onclick: () => go(t.id) }, h('span', { class: 'cap' }), h('span', { html: t.icon }), t.name);
    bar.append(tabs[t.id]);
  }
  $('#app').replaceChildren(top, box, bar);
}

const mounted = {};
function go(id) {
  if (id === current && mounted[id]) { pages[id].scrollTo({ top: 0, behavior: 'smooth' }); return; }
  sfx.tap(); haptic('select');
  current = id;
  for (const t of TABS) { pages[t.id].classList.toggle('on', t.id === id); tabs[t.id].classList.toggle('on', t.id === id); }
  if (!mounted[id]) {
    mounted[id] = ({ lobby: mountLobby, games: mountGames, top: mountTop, me: mountProfile })[id](pages[id], { openGame });
  } else mounted[id].show?.();
  const t = TABS.find((x) => x.id === id);
  if (!layer) setPoll(t.scope, t.every);
}

export async function openGame(id, opts = {}) {
  const g = GAMES[id]; if (!g) return;
  if (layer) closeGame(true);
  sfx.tap(); haptic('light');
  const title = h('div', { class: 'lt ellipsis' }, g.name, h('div', { class: 'lsub' }, g.sub));
  const body = h('div', { class: 'lbody' });
  const el = h('div', { class: 'layer', style: { '--glow': g.glow || g.bg } },
    h('div', { class: 'lhead' }, h('button', { class: 'iconbtn', onclick: () => closeGame(), 'aria-label': 'Назад', html: icons.back }), title,
      g.rules ? h('button', { class: 'iconbtn', 'aria-label': 'Правила', html: icons.info, onclick: () => rules(id) }) : null),
    body);
  document.body.append(el);
  const close = () => closeGame();
  layer = { id, el, ctrl: null, close };
  pushBack(close);
  requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add('on')));
  try {
    const mod = await import(g.mod);
    if (layer?.el !== el) return;
    layer.ctrl = mod[g.fn](body, { id, ...opts }) || {};
    const p = layer.ctrl.poll || { scope: 'game', every: 15000 };
    setPoll(p.scope, p.every, id);
  } catch (e) {
    console.error(e); toast('Не удалось открыть игру', 'err');
  }
}

export function closeGame(instant = false) {
  if (!layer) return;
  const { el, ctrl, close } = layer;
  layer = null;
  popBack(close);
  try { ctrl?.destroy?.(); } catch (e) { console.error(e); }
  el.classList.remove('on');
  setTimeout(() => el.remove(), instant ? 0 : 340);
  const t = TABS.find((x) => x.id === current);
  setPoll(t.scope, t.every);
  emit('refresh');
}

async function boot() {
  setupTelegram();
  let d;
  try {
    d = await api('me', {}, { quiet: true });
  } catch (e) {
    const msg = e instanceof ApiErr && e.code !== 'game' && e.message !== 'network' ? e.message : null;
    if (e.status === 401 || !tg?.initData) return fatal('Открой Казик кнопкой из чата в Telegram.', 'Приложение работает только внутри Telegram.');
    return fatal(msg || 'Казик не отвечает. Попробуй открыть ещё раз через минуту.');
  }
  Object.assign(S, { me: d.me, cfg: d.cfg, chat: d.chat, timers: d.timers, tasks: d.tasks, fire: d.fire, online: d.online,
    feed: d.feed, tables: d.tables, active: d.active });
  S.balance = d.me.balance;
  shell();
  $('#boot')?.remove();
  go('lobby');
  on('fatal', (e) => { if (e.code === 'disabled' || e.code === 'not_member') fatal(e.message); });
  const resume = Object.keys(d.active || {})[0];
  if (resume) setTimeout(() => { toast('Есть незаконченная игра — продолжим!', 'gold'); openGame(resume, { resume: d.active[resume] }); }, 400);
}

boot();
