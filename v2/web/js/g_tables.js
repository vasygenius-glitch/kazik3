// Общие столы чата: Краш, Рулетка, Складчина и Дуэли. Все видят один раунд.
import { h, S, api, on, now, fmt, fmtc, fx, left, clamp, prefs, sfx, haptic, busy, toast, avatar, sheet, ticker, setPoll, burst } from './core.js';
import { SPORE, COIN_HEADS, COIN_TAILS, amanita } from './art.js';
import { betPanel, banner, celebrate, events, ringTimer } from './ui.js';

const PAL = ['#e2493b', '#e7b54a', '#8fbf6a', '#7fb2c4', '#c99ad0', '#e9a178', '#d9c27a', '#86b8c4', '#e3877a', '#a3c9a8', '#b7a6e0', '#e0b25e'];
const isMe = (p) => !!(p && S.me && p.h && p.h === S.me.h);
const who = (p) => (isMe(p) ? 'Ты' : p?.name || 'Игрок');
const row = (p, right, cls = '') => h('div', { class: 'brow ' + cls + (isMe(p) ? ' me' : '') },
  avatar(p, 's'), h('div', { class: 'grow ellipsis' }, who(p)), right);
const BOOM = `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">${amanita(0, 4)}</svg>`;
const empty = (text) => h('div', { class: 'empty', style: { padding: '14px 4px' } }, text);

// Общий каркас: подписка на опрос, адаптивная частота, уборка.
function table(scope, every, onData) {
  let dead = false, cur = every;
  const offs = [on('poll', (d) => { if (!dead && d[scope]) onData(d[scope], d); })];
  return {
    dead: () => dead,
    rate(ms) { if (!dead && ms !== cur) { cur = ms; setPoll(scope === 'duels' ? 'duels' : scope, ms, scope === 'duels' ? 'duel' : scope); } },
    add(fn) { offs.push(fn); },
    destroy() { dead = true; offs.forEach((f) => f()); },
  };
}

// ───────────────────────── Краш ─────────────────────────
const CRASH_BET = 7;
const GRID = [1.5, 2, 3, 5, 10, 20, 50, 100, 200, 500, 1000];

export function crash(root) {
  const g = S.cfg?.crash?.growth || 0.07;
  const cv = h('canvas');
  const c2 = cv.getContext('2d');
  const multEl = h('div', { class: 'c-mult wait' }, 'x1,00');
  const stateEl = h('div', { class: 'c-state' }, 'Подключаемся к столу…');
  const rocket = h('div', { class: 'c-rocket', html: SPORE });
  const pops = h('div', { class: 'c-pops' });
  const barI = h('i');
  const stage = h('div', { class: 'crash' }, cv, rocket, multEl, stateEl, pops, h('div', { class: 'pbar c-bar' }, barI));
  const ban = banner(stage);
  const hist = h('div', { class: 'chist' });
  const bet = betPanel('crash');

  let autoOn = prefs.get('crash_auto_on', false), autoVal = prefs.get('crash_auto', 2);
  const autoIn = h('input', { inputmode: 'decimal', enterkeyhint: 'done', 'aria-label': 'Автовывод' });
  const showAuto = () => { autoIn.value = String(autoVal).replace('.', ','); };
  autoIn.addEventListener('focus', () => setTimeout(() => autoIn.select(), 0));
  autoIn.addEventListener('blur', () => {
    const x = parseFloat(String(autoIn.value).replace(',', '.'));
    autoVal = clamp(Number.isFinite(x) ? Math.round(x * 100) / 100 : 2, 1.01, 1000);
    prefs.set('crash_auto', autoVal); showAuto();
  });
  autoIn.addEventListener('keydown', (e) => { if (e.key === 'Enter') autoIn.blur(); });
  const autoT = h('button', { class: 'toggle' + (autoOn ? ' on' : ''), 'aria-label': 'Автовывод', onclick: () => {
    autoOn = !autoOn; prefs.set('crash_auto_on', autoOn); autoT.classList.toggle('on', autoOn); sfx.tap(); haptic('select');
  } });
  showAuto();
  const autoBox = h('div', { class: 'card tight autobox' },
    h('div', { class: 'grow' }, h('div', { class: 'ab-t' }, 'Автовывод'), h('div', { class: 'ab-s' }, 'заберёт сам на нужном множителе')),
    h('div', { class: 'betval', style: { width: '96px', flex: 'none' } }, h('span', { class: 'dim num' }, 'x'), autoIn), autoT);
  const btn = h('button', { class: 'btn red big wide', onclick: () => busy(btn, act) }, 'Поставить');
  const cnt = h('span', { class: 'more' });
  const list = h('div', { class: 'card bets' });
  root.append(stage, hist, btn, bet.el, autoBox, h('div', { class: 'label' }, 'Игроки раунда', cnt), list);

  let v = null, queued = false, lastRid = '', endShown = '', winShown = '', seen = new Set(), raf = 0, lastT = performance.now();
  const stars = Array.from({ length: 36 }, () => ({ x: Math.random(), y: Math.random(), s: Math.random() * 1.5 + 0.4 }));
  const T = table('crash', 1000, (cv_) => update(cv_));

  const mNow = () => {
    if (!v) return 1;
    if (v.phase === 'run') return Math.max(1, Math.floor(Math.exp(g * Math.max(0, now() - v.start)) * 100) / 100);
    if (v.phase === 'end') return v.point || 1;
    return 1;
  };
  const mine = () => v?.me;
  const active = () => v?.phase === 'run' && mine() && mine().cash == null && !mine().lost;

  function setText(el, t) { if (el.textContent !== t) el.textContent = t; }

  function draw(tms) {
    raf = requestAnimationFrame(draw);
    const dt = Math.min(0.05, (tms - lastT) / 1000); lastT = tms;
    const W = cv.clientWidth, H = cv.clientHeight; if (!W) return;
    const dpr = Math.min(2, devicePixelRatio || 1);
    if (cv.width !== Math.round(W * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
    const c = c2; c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, W, H);
    const phase = v?.phase || 'idle', m = mNow();
    const t = phase === 'run' ? Math.max(0, now() - v.start) : phase === 'end' ? Math.log(Math.max(1, v.point || 1)) / g : 0;
    // звёздная пыль: скорость растёт вместе с множителем
    const speed = phase === 'run' ? 0.05 + Math.min(0.9, Math.log(m) * 0.16) : 0.008;
    c.fillStyle = '#f3eadb';
    for (const s of stars) {
      s.x -= speed * dt * s.s; if (s.x < 0) { s.x += 1; s.y = Math.random(); }
      c.globalAlpha = 0.12 + 0.3 * (s.s / 1.9);
      c.fillRect(s.x * W, s.y * (H - 40), s.s, s.s);
    }
    c.globalAlpha = 1;
    const pl = 12, pb = 30, pt = 30, pr = 30;
    const TT = Math.max(9, t * 1.18), MM = Math.max(2, 1 + (m - 1) * 1.3);
    const X = (ti) => pl + (ti / TT) * (W - pl - pr);
    const Y = (mi) => H - pb - ((mi - 1) / (MM - 1)) * (H - pb - pt);
    c.font = '700 10px Unbounded, sans-serif'; c.textBaseline = 'middle'; c.lineWidth = 1;
    for (const gm of GRID.filter((x) => x < MM * 0.96).slice(-4)) {
      const y = Y(gm);
      c.strokeStyle = 'rgba(243,234,219,.07)'; c.setLineDash([3, 5]);
      c.beginPath(); c.moveTo(pl, y); c.lineTo(W - 8, y); c.stroke(); c.setLineDash([]);
      c.fillStyle = 'rgba(243,234,219,.32)'; c.fillText(fx(gm), pl + 2, y - 9);
    }
    let tipX = X(0), tipY = Y(1), ang = -Math.PI / 4;
    if (phase === 'run' || phase === 'end') {
      const n = 70, red = phase === 'end';
      const path = () => {
        c.beginPath();
        for (let i = 0; i <= n; i++) {
          const ti = (t * i) / n, x = X(ti), y = Y(Math.min(m, Math.exp(g * ti)));
          i ? c.lineTo(x, y) : c.moveTo(x, y);
        }
      };
      tipX = X(t); tipY = Y(m);
      path(); c.lineTo(tipX, H - pb); c.lineTo(X(0), H - pb); c.closePath();
      const grd = c.createLinearGradient(0, tipY, 0, H - pb);
      const col = red ? '226,73,59' : '231,181,74';
      grd.addColorStop(0, `rgba(${col},.34)`); grd.addColorStop(1, `rgba(${col},0)`);
      c.fillStyle = grd; c.fill();
      path(); c.strokeStyle = red ? '#e2493b' : '#f1c879'; c.lineWidth = 3.4; c.lineCap = 'round'; c.lineJoin = 'round';
      c.shadowColor = red ? 'rgba(226,73,59,.6)' : 'rgba(241,200,121,.55)'; c.shadowBlur = 14; c.stroke(); c.shadowBlur = 0;
      const t0 = Math.max(0, t - 0.4);
      ang = Math.atan2(tipY - Y(Math.exp(g * t0)), tipX - X(t0));
    }
    if (phase !== 'end') {
      const bob = phase === 'run' ? 0 : Math.sin(tms / 380) * 3;
      rocket.style.transform = `translate(${tipX}px,${tipY + bob}px) rotate(${ang + Math.PI / 2}rad)`;
    }
    // подписи
    if (phase === 'run') {
      multEl.classList.remove('wait');
      setText(multEl, fx(m));
      multEl.style.color = m >= 10 ? 'var(--gold)' : m >= 2 ? '#f6dca0' : '';
      const me = mine();
      setText(stateEl, me ? (me.cash != null ? `Ты забрал ${fx(me.cash)} · +${fmt(me.payout - me.amount)}` : `Твоя ставка ${fmt(me.amount)} → ${fmt(Math.floor(me.amount * m))}`) : 'Спора летит!');
      barI.style.width = '0%';
    } else if (phase === 'bet') {
      const rest = Math.max(0, v.bet_end - now());
      multEl.classList.add('wait'); multEl.style.color = '';
      setText(multEl, rest.toFixed(1).replace('.', ',') + ' с');
      setText(stateEl, mine() ? 'Ставка принята · ждём взлёт' : 'Приём ставок — до взлёта');
      barI.style.width = clamp((rest / CRASH_BET) * 100, 0, 100) + '%';
    } else if (phase === 'end') {
      multEl.classList.remove('wait'); multEl.style.color = '';
      setText(multEl, fx(v.point || 1));
      setText(stateEl, 'Улетела! Следующий раунд скоро');
      barI.style.width = '0%';
    } else {
      multEl.classList.add('wait'); setText(multEl, 'x1,00'); setText(stateEl, 'Готовим новый раунд…'); barI.style.width = '0%';
    }
    if (active()) setText(btn, 'Забрать ' + fmt(Math.floor(mine().amount * m)));
  }

  function sync() {
    const ph = v?.phase || 'idle', me = mine();
    let label, cls;
    if (active()) { label = 'Забрать'; cls = 'gold'; }
    else if (ph === 'bet' && !me) { label = queued ? 'Ставим…' : 'Поставить ' + fmt(bet.get()); cls = 'red'; }
    else if (ph === 'bet' && me) { label = 'Ставка в игре · ' + fmt(me.amount); cls = 'ghost'; }
    else { label = queued ? 'Отменить · ждём раунд' : 'В следующий раунд'; cls = queued ? 'ghost' : 'red soft'; }
    btn.className = 'btn big wide ' + cls + (btn.classList.contains('busy') ? ' busy' : '');
    if (!active()) setText(btn, label);
    bet.lock(ph === 'bet' && !!me);
  }

  function pop(b) {
    const r = rocket.getBoundingClientRect(), s = stage.getBoundingClientRect();
    const el = h('div', { class: 'c-pop', style: { left: clamp(r.left - s.left - 30, 6, s.width - 120) + 'px', top: clamp(r.top - s.top, 30, s.height - 40) + 'px' } },
      avatar(b, 's'), h('b', null, fx(b.cash)));
    pops.append(el); setTimeout(() => el.remove(), 1900);
  }

  function showWin(cash, payout, amount, evs) {
    if (winShown === v?.rid) return;
    winShown = v?.rid;
    ban.show('+' + fmt(payout - amount), 'забрал на ' + fx(cash), 'win', 2400);
    celebrate({ wager: amount, payout, events: evs }, stage);
  }

  function renderList() {
    const bets = [...(v?.bets || [])].sort((a, b) => (b.cash != null) - (a.cash != null) || b.payout - a.payout || b.amount - a.amount);
    const bank = bets.reduce((a, b) => a + b.amount, 0);
    cnt.textContent = bets.length ? `${bets.length} · банк ${fmtc(bank)}` : '';
    list.replaceChildren(...(bets.length ? bets.slice(0, 40).map((b) => row(b,
      h('span', { class: 'b-amt' }, b.cash != null ? `${fx(b.cash)} · +${fmtc(b.payout - b.amount)}` : fmtc(b.amount)),
      b.cash != null ? 'cashed' : b.lost ? 'lost' : '')) : [empty('Пока никто не поставил. Будь первым — все в чате увидят твой полёт.')]));
  }
  function renderHist() {
    hist.replaceChildren(...(v?.history || []).map((x) => h('span', { class: x < 2 ? 'lo' : x < 10 ? 'mid' : 'hi' }, fx(x))));
  }

  function update(nv) {
    if (!nv || T.dead()) return;
    const prev = v; v = nv;
    if (nv.rid !== lastRid) {
      lastRid = nv.rid; seen = new Set();
      stage.classList.remove('boom'); rocket.classList.remove('gone');
      if (prev) ban.hide();
      if (queued && nv.phase === 'bet' && !nv.me) { queued = false; placeBet().catch(() => {}); }
    }
    if (nv.phase === 'end' && endShown !== nv.rid) {
      endShown = nv.rid;
      const live = prev && prev.rid === nv.rid && prev.phase === 'run';
      rocket.classList.add('gone');
      if (live) {
        stage.classList.remove('boom'); void stage.offsetWidth; stage.classList.add('boom'); sfx.boom(); haptic(nv.me ? 'heavy' : 'light');
        const r = rocket.getBoundingClientRect(); burst(r.left, r.top, 12, BOOM);
      }
      if (nv.me?.lost && live) {
        ban.show('Улетела на ' + fx(nv.point), '−' + fmt(nv.me.amount), 'lose', 2600);
        events(nv.me.events);
      }
    }
    for (const b of nv.bets || []) {
      const key = b.h || b.name;
      if (b.cash != null && !seen.has(key)) {
        seen.add(key);
        if (prev && prev.rid === nv.rid) { pop(b); if (!isMe(b)) sfx.coin(); }
      }
    }
    if (nv.me && nv.me.cash != null && prev && prev.rid === nv.rid) showWin(nv.me.cash, nv.me.payout, nv.me.amount);
    T.rate(nv.phase === 'run' ? 450 : 1000);
    renderList(); renderHist(); sync();
  }

  async function placeBet() {
    const r = await api('crash', { bet: bet.get(), auto: autoOn ? autoVal : null });
    sfx.chip(); haptic('medium');
    update(r.crash);
  }
  async function cashout() {
    const r = await api('crash', { action: 'cash' });
    if (v?.me) Object.assign(v.me, { cash: r.cash, payout: r.payout });
    showWin(r.cash, r.payout, v?.me?.amount || 0, r.events);
    sync();
  }
  async function act() {
    if (active()) return cashout();
    if (v?.phase === 'bet' && !mine()) return placeBet();
    if (v?.phase === 'bet' && mine()) return;
    queued = !queued; sfx.tap(); haptic('select');
    if (queued) toast('Ставка уйдёт в начале следующего раунда', '', 2200);
    sync();
  }

  raf = requestAnimationFrame(draw);
  T.add(on('balance', () => sync()));
  bet.el.addEventListener('click', () => setTimeout(sync, 0));
  bet.el.addEventListener('focusout', () => setTimeout(sync, 0));
  return { poll: { scope: 'crash', every: 1000 }, destroy() { T.destroy(); cancelAnimationFrame(raf); bet.destroy(); } };
}

// ───────────────────────── Рулетка ─────────────────────────
const R_BET = 18;
const OUTS = [['low', null, '1–18', 'x2'], ['even', null, 'Чёт', 'x2'], ['red', null, 'Красное', 'x2'], ['black', null, 'Чёрное', 'x2'],
  ['odd', null, 'Нечёт', 'x2'], ['high', null, '19–36', 'x2'], ['dozen', 1, '1–12', 'x3'], ['dozen', 2, '13–24', 'x3'], ['dozen', 3, '25–36', 'x3'],
  ['col', 1, 'Колонка 1', '1, 4, 7…'], ['col', 2, 'Колонка 2', '2, 5, 8…'], ['col', 3, 'Колонка 3', '3, 6, 9…']];
const BET_NAME = { red: 'красное', black: 'чёрное', odd: 'нечёт', even: 'чёт', low: '1–18', high: '19–36' };

export function roulette(root) {
  const order = S.cfg.roulette.order, red = new Set(S.cfg.roulette.red);
  const col = (n) => (n === 0 ? 'gr' : red.has(n) ? 'rd' : 'bk');
  const N = order.length, seg = 360 / N, C = 150;
  const P = (r, a) => [C + r * Math.sin((a * Math.PI) / 180), C - r * Math.cos((a * Math.PI) / 180)];
  let pockets = '';
  order.forEach((n, i) => {
    const a0 = (i - 0.5) * seg, a1 = (i + 0.5) * seg;
    const [x0, y0] = P(138, a0), [x1, y1] = P(138, a1), [x2, y2] = P(98, a1), [x3, y3] = P(98, a0);
    const fill = n === 0 ? '#2f7a52' : red.has(n) ? '#b3341f' : '#1f1a17';
    const [tx, ty] = P(122, i * seg);
    pockets += `<path d="M${x0} ${y0}A138 138 0 0 1 ${x1} ${y1}L${x2} ${y2}A98 98 0 0 0 ${x3} ${y3}Z" fill="${fill}" stroke="#c9a46a" stroke-opacity=".35" stroke-width=".8"/>`
      + `<text x="${tx}" y="${ty}" transform="rotate(${i * seg} ${tx} ${ty})" text-anchor="middle" dominant-baseline="central" font-family="Unbounded,sans-serif" font-weight="700" font-size="11" fill="#f3eadb">${n}</text>`;
  });
  let spokes = '';
  for (let i = 0; i < 8; i++) { const [x, y] = P(92, i * 45); spokes += `<line x1="${C}" y1="${C}" x2="${x}" y2="${y}" stroke="#7a5a33" stroke-width="3" stroke-linecap="round"/>`; }
  const wheelSvg = `<svg viewBox="0 0 300 300" xmlns="http://www.w3.org/2000/svg">
    <defs><radialGradient id="rw" cx="50%" cy="45%" r="60%"><stop offset="0" stop-color="#7a4f2a"/><stop offset="1" stop-color="#3b2414"/></radialGradient>
    <radialGradient id="rb" cx="50%" cy="40%" r="60%"><stop offset="0" stop-color="#3a2f25"/><stop offset="1" stop-color="#16110d"/></radialGradient></defs>
    <circle cx="150" cy="150" r="149" fill="url(#rw)"/><circle cx="150" cy="150" r="141" fill="#2a1c12"/>
    <g class="wheel" style="transform-origin:150px 150px">${pockets}<circle cx="150" cy="150" r="97" fill="url(#rb)"/>${spokes}<circle cx="150" cy="150" r="16" fill="#c9a46a"/></g>
    <g class="ballrot" style="transform-origin:150px 150px"><g class="balldrop"><circle cx="150" cy="44" r="6" fill="#fbf5ea"/><circle cx="148" cy="42" r="2" fill="#fff"/></g></g></svg>`;
  const wb = h('div', { class: 'wheelbox' });
  wb.innerHTML = wheelSvg;
  const wheel = wb.querySelector('.wheel'), ballrot = wb.querySelector('.ballrot'), balldrop = wb.querySelector('.balldrop');
  const hNum = h('div', { class: 'h-num' }, '—'), hSub = h('div', { class: 'h-sub' }, '');
  const hub = h('div', { class: 'hubc' }, h('div', null, hNum, hSub));
  const timer = ringTimer(100, 'var(--gold)');
  wb.append(h('div', { class: 'ptr', html: '<svg viewBox="0 0 22 26"><path d="M11 25L1 3c-.6-1.4.4-3 2-3h16c1.6 0 2.6 1.6 2 3z" fill="#f3eadb"/><circle cx="11" cy="7" r="3" fill="#e2493b"/></svg>' }), hub, timer.el);
  const stage = h('div', { class: 'roul stage' }, wb);
  const ban = banner(stage);
  const rhist = h('div', { class: 'rhist' });

  const spots = {};
  const spotKey = (k, v) => k + ':' + (v ?? '');
  const chipEl = (key) => { const c = h('span', { class: 'mychip hidden' }); spots[key] = { chip: c }; return c; };
  const board = h('div', { class: 'board' });
  const mkCell = (n) => {
    const key = spotKey('n', n);
    const el = h('button', { class: 'cell ' + col(n), onclick: () => place('n', n, el) }, String(n), chipEl(key));
    spots[key].el = el; return el;
  };
  board.append(mkCell(0));
  for (let n = 1; n <= 36; n++) board.append(mkCell(n));
  const outs = h('div', { class: 'outs' }, OUTS.map(([k, val, name, sub]) => {
    const key = spotKey(k, val);
    const el = h('button', { class: 'obet' + (k === 'red' ? ' rd' : k === 'black' ? ' bk' : ''), onclick: () => place(k, val, el) }, name, h('small', null, sub), chipEl(key));
    spots[key].el = el; return el;
  }));
  const bet = betPanel('roulette', { label: 'Фишка' });
  const myLine = h('div', { class: 'muted', style: { fontSize: '13px' } });
  const repeatBtn = h('button', { class: 'btn ghost sm hidden', onclick: () => busy(repeatBtn, repeat) }, 'Повторить');
  const cnt = h('span', { class: 'more' });
  const list = h('div', { class: 'card bets' });
  root.append(stage, rhist, h('div', { class: 'row' }, h('div', { class: 'grow' }, myLine), repeatBtn), board, outs, bet.el,
    h('div', { class: 'label' }, 'За столом', cnt), list);

  let v = null, rid = '', spun = '', shown = '', wheelRot = 0, ballRot = 0, lastList = [];
  const T = table('roulette', 1500, (x) => update(x));

  function setRot(el, deg, dur, ease) {
    el.style.transition = dur ? `transform ${dur}s ${ease}` : 'none';
    el.style.transform = `rotate(${deg}deg)`;
  }
  function spinTo(n, dur) {
    const i = order.indexOf(n);
    const wTarget = Math.ceil(wheelRot / 360) * 360 + 360 * (dur > 2 ? 4 : 1) + ((360 - i * seg) % 360);
    const bTarget = Math.floor(ballRot / 360) * 360 - 360 * (dur > 2 ? 7 : 2);
    balldrop.style.transition = 'none'; balldrop.style.transform = 'translateY(-37px)'; void balldrop.getBoundingClientRect();
    setRot(wheel, wTarget, dur, 'cubic-bezier(.14,.62,.16,1)');
    setRot(ballrot, bTarget, dur, 'cubic-bezier(.06,.55,.12,1)');
    balldrop.style.transition = `transform .7s cubic-bezier(.5,0,.7,1.6) ${Math.max(0, dur * 0.7)}s`;
    balldrop.style.transform = 'translateY(0)';
    wheelRot = wTarget; ballRot = bTarget;
    let k = 0;
    const iv = setInterval(() => { if (k++ > dur * 7 || T.dead()) clearInterval(iv); else sfx.tick(); }, 140);
  }
  function placeStatic(n) {
    const i = order.indexOf(n);
    wheelRot = (360 - i * seg) % 360; ballRot = 0;
    setRot(wheel, wheelRot, 0); setRot(ballrot, 0, 0);
    balldrop.style.transition = 'none'; balldrop.style.transform = 'translateY(0)';
  }

  function hubText() {
    if (!v) return;
    if (v.phase === 'bet') {
      const rest = Math.max(0, v.t_next - now());
      hNum.textContent = Math.ceil(rest); hNum.className = 'h-num';
      hSub.textContent = 'ставки'; timer.set(rest / R_BET); timer.el.style.opacity = 1;
    } else {
      timer.el.style.opacity = 0;
      if (v.phase === 'show' || (v.phase === 'spin' && v.spin_end && now() >= v.spin_end)) {
        hNum.textContent = v.result; hNum.className = 'h-num c-' + col(v.result);
        hSub.textContent = v.result === 0 ? 'зеро' : red.has(v.result) ? 'красное' : 'чёрное';
      } else if (v.phase === 'spin') { hNum.textContent = '•••'; hNum.className = 'h-num'; hSub.textContent = 'шарик летит'; }
      else { hNum.textContent = '—'; hNum.className = 'h-num'; hSub.textContent = 'ждём игроков'; }
    }
  }
  const stopTick = ticker(hubText);
  T.add(stopTick);

  function renderChips() {
    const sum = {};
    for (const [k, val, a] of v?.me?.list || []) { const key = spotKey(k, val); sum[key] = (sum[key] || 0) + a; }
    for (const [key, s] of Object.entries(spots)) {
      const a = sum[key] || 0;
      s.chip.classList.toggle('hidden', !a);
      if (a) s.chip.textContent = fmtc(a).replace(' тыс', 'к').replace(' млн', 'м');
    }
    const total = Object.values(sum).reduce((a, b) => a + b, 0);
    myLine.textContent = total ? `Твои фишки: ${fmt(total)}` : v?.phase === 'bet' ? 'Нажми на число или сектор, чтобы поставить фишку' : 'Ставки закрыты — следующий раунд скоро';
    repeatBtn.classList.toggle('hidden', !(v?.phase === 'bet' && !total && lastList.length));
    repeatBtn.textContent = 'Повторить ' + fmtc(lastList.reduce((a, x) => a + x[2], 0));
  }
  function renderList() {
    const bets = [...(v?.bets || [])].sort((a, b) => (b.payout ?? 0) - (a.payout ?? 0) || b.total - a.total);
    cnt.textContent = bets.length ? String(bets.length) : '';
    list.replaceChildren(...(bets.length ? bets.slice(0, 40).map((b) => {
      const done = b.payout != null;
      const right = done ? (b.payout > 0 ? `+${fmtc(b.payout - b.total)}` : `−${fmtc(b.total)}`) : fmtc(b.total);
      const tags = h('div', { class: 'btags' }, b.chips.slice(-4).map(([k, val]) => h('span', { class: 'bt ' + (k === 'n' ? col(val) : k === 'red' ? 'rd' : k === 'black' ? 'bk' : '') }, k === 'n' ? String(val) : k === 'dozen' ? `${val}-я 12` : k === 'col' ? `кол.${val}` : BET_NAME[k])));
      return h('div', { class: 'brow' + (isMe(b) ? ' me' : '') + (done ? (b.payout > 0 ? ' cashed' : ' lost') : '') }, avatar(b, 's'),
        h('div', { class: 'grow', style: { minWidth: 0 } }, h('div', { class: 'ellipsis' }, who(b)), tags), h('span', { class: 'b-amt' }, right));
    }) : [empty('Стол пуст. Поставь фишку — раунд увидит весь чат.')]));
  }
  function renderHist() {
    rhist.replaceChildren(...(v?.history || []).map((n) => h('span', { class: 'cell ' + col(n) }, String(n))));
  }
  function highlight(n) {
    Object.values(spots).forEach((s) => s.el.classList.remove('hit'));
    if (n == null) return;
    const keys = [spotKey('n', n)];
    if (n) {
      keys.push(spotKey(red.has(n) ? 'red' : 'black'), spotKey(n % 2 ? 'odd' : 'even'), spotKey(n <= 18 ? 'low' : 'high'),
        spotKey('dozen', Math.floor((n - 1) / 12) + 1), spotKey('col', ((n - 1) % 3) + 1));
    }
    keys.forEach((k) => spots[k]?.el.classList.add('hit'));
  }

  function update(nv) {
    if (!nv || T.dead()) return;
    const prev = v; v = nv;
    if (nv.rid !== rid) {
      if (prev?.me?.list?.length && prev.rid !== nv.rid) lastList = prev.me.list;
      rid = nv.rid; highlight(null);
      if (prev) ban.hide();
    }
    if (nv.phase === 'spin' && spun !== nv.rid) {
      spun = nv.rid;
      const dur = clamp((nv.spin_end || now()) - now(), 0.6, 7);
      spinTo(nv.result, dur);
      haptic('light');
    } else if (nv.phase === 'show' && spun !== nv.rid) {
      spun = nv.rid; placeStatic(nv.result);
    } else if (!prev && nv.history?.length && nv.phase === 'bet') placeStatic(nv.history[0]);
    if (nv.phase === 'show' && shown !== nv.rid) {
      shown = nv.rid;
      highlight(nv.result);
      if (nv.me && nv.me.payout != null && prev) {
        const wager = nv.me.list.reduce((a, x) => a + x[2], 0), pay = nv.me.payout;
        const net = pay - wager;
        ban.show(net > 0 ? '+' + fmt(net) : net === 0 ? 'В ноль' : '−' + fmt(-net), `выпало ${nv.result}`, net > 0 ? 'win' : net === 0 ? '' : 'lose', 2600);
        celebrate({ wager, payout: pay }, wb);
      } else if (prev) sfx.tap();
    }
    T.rate(nv.phase === 'spin' ? 700 : 1500);
    renderChips(); renderList(); renderHist(); hubText();
  }

  async function place(kind, value, el) {
    if (v?.phase !== 'bet') { toast('Ставки закрыты — дождись следующего раунда', '', 2000); haptic('warning'); return; }
    el.classList.remove('bump'); void el.offsetWidth; el.classList.add('bump');
    sfx.chip(); haptic('light');
    const r = await api('roulette', { kind, value, bet: bet.get() }).catch(() => null);
    if (r) update(r.roulette);
  }
  async function repeat() {
    for (const [k, val, a] of lastList) {
      if (v?.phase !== 'bet') break;
      const r = await api('roulette', { kind: k, value: val, bet: a }).catch(() => null);
      if (!r) break;
      sfx.chip(); update(r.roulette);
    }
  }

  return { poll: { scope: 'roulette', every: 1500 }, destroy() { T.destroy(); bet.destroy(); } };
}

// ───────────────────────── Складчина ─────────────────────────
const POT_COUNT = 30;
export function jackpot(root) {
  const R = 80, CIRC = 2 * Math.PI * R;
  const segs = h('svg:g', { transform: 'rotate(-90 100 100)' });
  const svg = h('svg:svg', { viewBox: '0 0 200 200' },
    h('svg:circle', { cx: 100, cy: 100, r: R, fill: 'none', stroke: '#25201b', 'stroke-width': 28 }), segs);
  const needle = h('div', { class: 'needle', html: '<svg viewBox="0 0 200 200"><path d="M100 30L91 4h18z" fill="#f3eadb" stroke="#12100e" stroke-width="2"/></svg>' });
  const tot = h('div', { class: 'p-tot num' }, '0'), sub = h('div', { class: 'p-sub' }, '');
  const pcIn = h('div', null, tot, sub);
  const pc = h('div', { class: 'pc' }, pcIn);
  const avs = h('div', { class: 'pavs' });
  const timer = ringTimer(100, 'var(--gold)');
  const box = h('div', { class: 'potbox' }, svg, avs, needle, pc, timer.el);
  const stage = h('div', { class: 'pot stage' }, box);
  const ban = banner(stage);
  const myLine = h('div', { class: 'muted', style: { fontSize: '13px', textAlign: 'center' } });
  const bet = betPanel('jackpot', { label: 'Вклад' });
  const btn = h('button', { class: 'btn red big wide', onclick: () => busy(btn, put) }, 'Скинуться');
  const cnt = h('span', { class: 'more' });
  const list = h('div', { class: 'card bets' });
  const histBox = h('div', { class: 'card bets' });
  root.append(stage, myLine, bet.el, btn, h('div', { class: 'label' }, 'Участники', cnt), list, h('div', { class: 'label' }, 'Прошлые складчины'), histBox);

  let v = null, rot = 0, drawing = false, revealed = '', segEls = new Map();
  const T = table('jackpot', 1500, (x) => update(x));
  const colorOf = (i) => PAL[i % PAL.length];

  function renderDonut(dim) {
    const ps = v?.players || [];
    let acc = 0;
    const keep = new Set();
    ps.forEach((p, i) => {
      const key = p.h || p.name; keep.add(key);
      let el = segEls.get(key);
      if (!el) { el = h('svg:circle', { class: 'seg', cx: 100, cy: 100, r: R, fill: 'none', 'stroke-width': 28 }); el.style.strokeDasharray = `0 ${CIRC}`; el.style.strokeDashoffset = String(-acc * CIRC); segs.append(el); segEls.set(key, el); }
      const len = Math.max(0, p.share * CIRC - (ps.length > 1 ? 1.6 : 0)), off = -acc * CIRC;
      el.setAttribute('stroke', colorOf(i));
      requestAnimationFrame(() => { el.style.strokeDasharray = `${len} ${CIRC}`; el.style.strokeDashoffset = String(off); });
      el.classList.toggle('dim', !!dim && dim !== key);
      p._mid = acc + p.share / 2; p._c = colorOf(i);
      acc += p.share;
    });
    for (const [k, el] of segEls) if (!keep.has(k)) { el.remove(); segEls.delete(k); }
    avs.replaceChildren(...ps.filter((p) => p.share >= 0.07).map((p) => {
      const a = p._mid * 2 * Math.PI;
      const el = avatar(p, 's');
      el.classList.add('pav'); el.style.left = 50 + 40 * Math.sin(a) + '%'; el.style.top = 50 - 40 * Math.cos(a) + '%';
      el.style.boxShadow = `0 0 0 2.5px ${p._c}`;
      return el;
    }));
  }
  function center() {
    if (!v) return;
    const ps = v.players || [];
    if (v.winner && revealed === v.rid) return;
    pcIn.replaceChildren(tot, sub);
    tot.textContent = fmtc(v.total);
    timer.el.style.opacity = v.phase === 'count' ? 1 : 0;
    if (v.phase === 'count') { const rest = Math.max(0, v.t_next - now()); sub.textContent = 'розыгрыш через ' + left(rest); timer.set(rest / POT_COUNT); }
    else if (v.phase === 'draw') sub.textContent = 'крутим стрелку…';
    else sub.textContent = ps.length ? 'ждём второго участника' : 'банк пуст — начни первым';
  }
  T.add(ticker(center));
  function winnerCenter() {
    const w = v.winner;
    pcIn.replaceChildren(h('div', { class: 'pwin' }, avatar(w, 'm'), h('div', { class: 'ellipsis', style: { maxWidth: '110px', fontWeight: 700 } }, who(w)), h('div', { class: 'p-tot num', style: { fontSize: '17px' } }, '+' + fmtc(v.prize))));
  }
  function reveal(quiet = false) {
    if (!v?.winner || revealed === v.rid) return;
    revealed = v.rid;
    drawing = false;
    renderDonut(v.winner.h || v.winner.name);
    winnerCenter();
    const meIn = !!v.me;
    if (quiet) return;
    if (isMe(v.winner)) { ban.show('Банк твой!', '+' + fmt(v.prize - (v.me?.amount || 0)), 'win', 3200); celebrate({ wager: v.me?.amount || 1, payout: v.prize }, box); }
    else if (meIn) { ban.show('Не повезло', `банк забрал(а) ${v.winner.name}`, 'lose', 2600); sfx.lose(); haptic('warning'); }
    else sfx.coin();
  }

  function spin() {
    const target = Math.ceil(rot / 360) * 360 + 360 * 6 + (v.ticket || 0) * 360;
    const dur = clamp(v.t_next - now() - 0.2, 0.8, 6.8);
    needle.style.transition = `transform ${dur}s cubic-bezier(.12,.75,.15,1)`;
    needle.style.transform = `rotate(${target}deg)`;
    rot = target; drawing = true;
    let k = 0; const iv = setInterval(() => { if (k++ > dur * 6 || T.dead()) clearInterval(iv); else sfx.tick(); }, 160);
    setTimeout(() => { if (!T.dead()) reveal(); }, dur * 1000 + 80);
  }

  function update(nv) {
    if (!nv || T.dead()) return;
    const prev = v; v = nv;
    if (nv.phase === 'draw' && !drawing && revealed !== nv.rid) spin();
    if (nv.phase === 'done' && !drawing) {
      const cold = !prev || prev.rid !== nv.rid || (prev.phase !== 'done' && prev.phase !== 'draw');
      if (cold) { needle.style.transition = 'none'; rot = (nv.ticket || 0) * 360; needle.style.transform = `rotate(${rot}deg)`; }
      reveal(!prev);
    }
    if (prev && nv.rid !== prev.rid) { drawing = false; ban.hide(); segEls.forEach((el) => el.remove()); segEls.clear(); needle.style.transition = 'none'; rot = 0; needle.style.transform = 'rotate(0deg)'; }
    if (!drawing && nv.phase !== 'done') renderDonut(); else if (nv.phase === 'draw') renderDonut();
    center();
    const ps = nv.players || [];
    cnt.textContent = ps.length ? `${ps.length} · банк ${fmtc(nv.total)}` : '';
    list.replaceChildren(...(ps.length ? ps.map((p, i) => h('div', { class: 'prow' + (isMe(p) ? ' me' : '') },
      h('i', { class: 'sw', style: { background: colorOf(i) } }), avatar(p, 's'), h('div', { class: 'grow ellipsis' }, who(p)),
      h('span', { class: 'num dim', style: { fontSize: '12px' } }, fmtc(p.amount)), h('span', { class: 'p-pc' }, Math.round(p.share * 1000) / 10 + '%'))) : [empty('Пока пусто. Скинься первым — шанс 100%, пока не придёт второй.')]));
    const me = nv.me, share = me && nv.total ? me.amount / nv.total : 0;
    myLine.textContent = me ? `Твой вклад ${fmt(me.amount)} · шанс ${Math.round(share * 1000) / 10}%` : 'Шанс забрать банк = твоя доля. 3% банка — в фонд лиги.';
    const open = nv.phase === 'open' || nv.phase === 'count';
    btn.textContent = open ? (me ? 'Докинуть ' + fmt(bet.get()) : 'Скинуться ' + fmt(bet.get())) : 'Идёт розыгрыш…';
    btn.classList.toggle('ghost', !open); btn.classList.toggle('red', open);
    histBox.replaceChildren(...((nv.history || []).length ? nv.history.slice(0, 8).map((x) => row(x, h('span', { class: 'b-amt gold' }, '+' + fmtc(x.prize)))) : [empty('Здесь появятся победители.')]));
    T.rate(nv.phase === 'draw' ? 900 : 1500);
  }

  async function put() {
    if (!(v?.phase === 'open' || v?.phase === 'count')) return;
    const r = await api('jackpot', { bet: bet.get() });
    sfx.chip(); haptic('medium');
    const rr = box.getBoundingClientRect(); burst(rr.left + rr.width / 2, rr.top + rr.height / 2, 8, SPORE);
    update(r.jackpot);
  }
  const relabel = () => setTimeout(() => v && update(v), 0);
  bet.el.addEventListener('click', relabel); bet.el.addEventListener('focusout', relabel);
  return { poll: { scope: 'jackpot', every: 1500 }, destroy() { T.destroy(); bet.destroy(); } };
}

// ───────────────────────── Дуэли ─────────────────────────
function coinSheet(d, meWon) {
  const heads = d.side === 'heads';
  const a = { h: d.h, name: d.name }, b = { h: d.opp_h, name: d.opp_name };
  sheet((box, close) => {
    const coin = h('div', { class: 'coin' }, h('div', { class: 'side heads', html: COIN_HEADS }), h('div', { class: 'side tails', html: COIN_TAILS }));
    const res = h('div', { class: 'duel-res' }, 'Монетка в воздухе…');
    const pa = h('div', { class: 'dp' + (heads ? ' w' : '') }, avatar(a, 'l'), h('b', { class: 'ellipsis' }, who(a)), h('small', { html: COIN_HEADS }));
    const pb = h('div', { class: 'dp' + (!heads ? ' w' : '') }, avatar(b, 'l'), h('b', { class: 'ellipsis' }, who(b)), h('small', { html: COIN_TAILS }));
    box.append(h('h3', { style: { textAlign: 'center' } }, 'Дуэль на ' + fmt(d.amount)), h('div', { class: 'duelvs' }, pa, h('div', { class: 'vs' }, 'VS'), pb), coin, res,
      h('button', { class: 'btn ghost wide', onclick: close }, 'Закрыть'));
    const turns = 6;
    const total = turns * 360 + (heads ? 0 : 180);
    coin.style.setProperty('--half', `${total / 2}deg`);
    coin.style.setProperty('--turn', `${total}deg`);
    requestAnimationFrame(() => coin.classList.add('flip'));
    sfx.roll(); haptic('medium');
    setTimeout(() => {
      [pa, pb].forEach((x) => x.classList.add('done'));
      res.textContent = meWon ? `Победа! +${fmt(d.prize - d.amount)}` : `Банк забирает ${d.winner_name}`;
      res.className = 'duel-res ' + (meWon ? 'win' : meWon === false ? 'lose' : '');
      if (meWon != null) celebrate({ wager: d.amount, payout: meWon ? d.prize : 0 }, coin);
    }, 2250);
  });
}

export function duels(root, opts = {}) {
  let target = '';
  const bet = betPanel('duel', { label: 'Сумма вызова' });
  const picker = h('div', { class: 'tpick' });
  const make = h('button', { class: 'btn red big wide', onclick: () => busy(make, create) }, 'Бросить вызов');
  const list = h('div', { class: 'card bets' });
  const cnt = h('span', { class: 'more' });
  root.append(
    h('div', { class: 'card duel-hero' }, h('div', { class: 'coin mini' }, h('div', { class: 'side heads', html: COIN_HEADS }), h('div', { class: 'side tails', html: COIN_TAILS })),
      h('div', { class: 'grow' }, h('b', null, 'Один на один'), h('div', { class: 'muted', style: { fontSize: '12.5px' } }, 'Монетка 50/50. Победитель забирает обе ставки минус 3% в фонд лиги.'))),
    h('div', { class: 'label' }, 'Кого вызвать'), picker, bet.el, make, h('div', { class: 'label' }, 'Вызовы в чате', cnt), list);

  let rows = [], seenDone = null, prompted = false;
  const T = table('duels', 3000, (x) => update(x));
  function renderPicker() {
    const people = (S.online || []).filter((p) => !isMe(p)).slice(0, 20);
    if (target && !people.some((p) => p.h === target)) target = '';
    const chip = (p) => h('button', { class: 'tp' + ((p ? p.h : '') === target ? ' on' : ''), onclick: () => { target = p ? p.h : ''; sfx.tap(); haptic('select'); renderPicker(); } },
      p ? avatar(p, 's') : h('div', { class: 'av s any' }, '∗'), h('span', { class: 'ellipsis' }, p ? p.name : 'Любой'));
    picker.replaceChildren(chip(null), ...people.map(chip));
    make.textContent = target ? `Вызвать ${people.find((p) => p.h === target)?.name || ''} на ${fmt(bet.get())}` : `Открытый вызов на ${fmt(bet.get())}`;
  }
  let clocks = [];
  function render() {
    clocks = [];
    const open = rows.filter((d) => d.state === 'open');
    cnt.textContent = open.length ? `${open.length} открыто` : '';
    list.replaceChildren(...(rows.length ? rows.map((d) => {
      let right;
      if (d.state === 'open' && d.mine) right = h('button', { class: 'btn xs ghost', onclick: (e) => busy(e.currentTarget, () => cancel(d)) }, 'Отменить');
      else if (d.state === 'open' && d.locked) right = h('span', { class: 'dim', style: { fontSize: '12px' } }, 'не тебе');
      else if (d.state === 'open') right = h('button', { class: 'btn xs red', onclick: (e) => busy(e.currentTarget, () => accept(d)) }, 'Принять');
      else if (d.state === 'busy') right = h('span', { class: 'dim' }, 'монетка…');
      else right = h('span', { class: 'b-amt ' + (d.winner_h === S.me?.h ? 'moss' : '') }, '🏆 ' + (d.winner_h === S.me?.h ? 'ты' : d.winner_name));
      const pre = d.target_name ? `вызов для ${d.for_me ? 'тебя' : d.target_name} · ` : 'открытый вызов · ';
      const subTxt = d.state === 'done' ? `${who({ h: d.h, name: d.name })} vs ${who({ h: d.opp_h, name: d.opp_name })}` : pre + left(d.expires - now());
      const subEl = h('div', { class: 'muted ellipsis', style: { fontSize: '12px' } }, subTxt);
      if (d.state === 'open') clocks.push(() => { subEl.textContent = pre + left(d.expires - now()); });
      return h('div', { class: 'duel' + (d.state === 'done' ? ' past' : '') + (d.for_me && d.state === 'open' ? ' forme' : '') }, avatar(d, 'm'),
        h('div', { class: 'grow', style: { minWidth: 0 } }, h('div', { class: 'ellipsis', style: { fontWeight: 600 } }, who(d)), subEl),
        h('div', { class: 'col', style: { alignItems: 'flex-end', gap: '5px' } }, h('span', { class: 'd-amt num' }, fmtc(d.amount)), right));
    }) : [empty('Вызовов нет. Брось первый — он появится в ленте зала у всех.')]));
  }
  T.add(ticker(() => clocks.forEach((f) => f())));

  function update(list_) {
    if (T.dead()) return;
    rows = list_ || [];
    if (seenDone === null) seenDone = new Set(rows.filter((d) => d.state === 'done').map((d) => d.id));
    for (const d of rows) {
      if (d.state === 'done' && !seenDone.has(d.id)) {
        seenDone.add(d.id);
        if (d.mine) coinSheet(d, d.winner_h === S.me?.h);
      }
    }
    if (opts.accept && !prompted) {
      prompted = true;
      const d = rows.find((x) => x.id === opts.accept);
      if (d && d.state === 'open' && !d.mine && !d.locked) confirmAccept(d);
      else if (d) toast('Этот вызов уже неактуален', '', 2200);
    }
    render(); renderPicker();
  }
  function confirmAccept(d) {
    sheet((box, close) => {
      box.append(h('h3', null, 'Принять вызов?'), h('div', { class: 'row', style: { margin: '6px 0 14px' } }, avatar(d, 'm'),
        h('div', { class: 'grow' }, h('b', null, d.name), h('div', { class: 'muted', style: { fontSize: '13px' } }, 'ставит ' + fmt(d.amount) + ' · монетка 50/50'))),
      h('button', { class: 'btn red big wide', onclick: (e) => busy(e.currentTarget, async () => { await accept(d); close(); }) }, 'Принять за ' + fmt(d.amount)));
    });
  }
  async function create() {
    const r = await api('duel', { action: 'create', bet: bet.get(), target: target || undefined });
    sfx.chip(); haptic('medium');
    toast(target ? 'Вызов отправлен — ждём ответа' : 'Вызов брошен! Его видит весь чат', 'gold', 2600);
    update(r.duels);
  }
  async function accept(d) {
    const r = await api('duel', { action: 'accept', id: d.id });
    seenDone?.add(r.duel.id);
    update(r.duels);
    coinSheet(r.duel, r.win);
    events(r.events);
  }
  async function cancel(d) {
    const r = await api('duel', { action: 'cancel', id: d.id });
    sfx.tap();
    update(r.duels);
  }
  bet.el.addEventListener('click', () => setTimeout(renderPicker, 0));
  bet.el.addEventListener('focusout', () => setTimeout(renderPicker, 0));
  T.add(on('poll', () => renderPicker()));
  renderPicker();
  return { poll: { scope: 'duels', every: 3000 }, destroy() { T.destroy(); bet.destroy(); } };
}
