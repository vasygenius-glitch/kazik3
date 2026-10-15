// «Зал»: игрок, кто сейчас в Казике, живые столы, доход, огонёк, задания, лента.
import { h, S, api, on, fmt, fmtc, fx, left, ago, now, avatar, stack, sheet, busy, ticker, sfx, haptic, toast, burst, clear, plural } from './core.js';
import { ecoArt, tileArt, SPORE } from './art.js';
import { money, ACT_LABEL, events } from './ui.js';

export function levelRing(me, size = 'l') {
  const px = { m: 44, l: 64, xl: 86 }[size] || 64, R = px / 2 + 4, C = 2 * Math.PI * R;
  const k = Math.max(0, Math.min(1, (me.xp - me.xp_lo) / Math.max(1, me.xp_hi - me.xp_lo)));
  const ring = h('svg:svg', { class: 'ring', viewBox: `0 0 ${px + 10} ${px + 10}` },
    h('svg:circle', { cx: px / 2 + 5, cy: px / 2 + 5, r: R, fill: 'none', stroke: '#2e2822', 'stroke-width': 3 }),
    h('svg:circle', { cx: px / 2 + 5, cy: px / 2 + 5, r: R, fill: 'none', stroke: '#e7b54a', 'stroke-width': 3, 'stroke-linecap': 'round',
      'stroke-dasharray': C, 'stroke-dashoffset': C * (1 - k), transform: `rotate(-90 ${px / 2 + 5} ${px / 2 + 5})` }));
  return h('div', { class: 'av-wrap' }, avatar(me, size), ring, h('span', { class: 'lvl-chip' }, me.level));
}

function xpBar(me) {
  const k = Math.max(0, Math.min(1, (me.xp - me.xp_lo) / Math.max(1, me.xp_hi - me.xp_lo)));
  return [h('div', { class: 'xp' }, h('i', { style: { width: (k * 100).toFixed(1) + '%' } })),
    h('div', { class: 'xp-txt' }, h('span', null, `Уровень ${me.level}`), h('span', null, `${fmt(me.xp - me.xp_lo)} / ${fmt(me.xp_hi - me.xp_lo)} XP`))];
}

export function mountLobby(page, { openGame }) {
  const meBox = h('div', { class: 'card' });
  const onlineBox = h('button', { class: 'card', style: { width: '100%', textAlign: 'left', display: 'block' }, onclick: showOnline });
  const tablesBox = h('div', { class: 'hscroll' });
  const ecoBox = h('div', { class: 'grid2' });
  const rakeBox = h('div', { class: 'card' });
  const fireBox = h('div', { class: 'card' });
  const tasksBox = h('div', { class: 'card' });
  const feedBox = h('div', { class: 'card' });
  const duelsBox = h('div');
  page.append(
    meBox,
    h('div', { class: 'label' }, h('span', { class: 'live' }, h('i', { class: 'live-dot' }), 'Сейчас в Казике')), onlineBox,
    h('div', { class: 'label' }, 'Живые столы', h('span', { class: 'more' }, 'общие для всего чата')), tablesBox, duelsBox,
    h('div', { class: 'label' }, 'Доход'), ecoBox, h('div', { style: { height: '10px' } }), rakeBox,
    h('div', { class: 'label' }, 'Огонёк активности'), fireBox,
    h('div', { class: 'label' }, 'Задания дня', h('span', { class: 'more' }, 'обновятся в 00:00 МСК')), tasksBox,
    h('div', { class: 'label' }, 'Лента чата'), feedBox);

  function renderMe() {
    const me = S.me;
    meBox.replaceChildren(h('div', { class: 'me' }, levelRing(me),
      h('div', { class: 'grow' }, h('div', { class: 'me-name ellipsis' }, me.name),
        h('div', { class: 'me-title' }, me.title, me.clan ? ` · ⚔ ${me.clan}` : '', me.vip ? ' · VIP' : ''), ...xpBar(me))));
    if (me.sick?.length) meBox.append(h('div', { class: 'notice', style: { marginTop: '12px' } }, '🦠',
      h('div', null, me.sick.map((s) => s.name).join(', '), h('div', { class: 'dim', style: { fontSize: '12px', marginTop: '2px' } }, me.sick[0].desc))));
  }

  function renderOnline() {
    const list = S.online || [];
    const others = list.filter((p) => p.h !== S.me.h);
    const names = others.slice(0, 2).map((p) => [h('b', null, p.name), ' ' + (ACT_LABEL[p.act] || '')]);
    const txt = others.length
      ? [names[0], names[1] ? [', ', names[1]] : null, others.length > 2 ? ` и ещё ${others.length - 2}` : '']
      : ['Пока только ты. Позови чат — вместе веселее!'];
    onlineBox.replaceChildren(h('div', { class: 'online' }, stack(list, 6, 'm'),
      h('div', { class: 'txt grow' }, h('div', { class: 'num', style: { fontSize: '15px', color: 'var(--cream)', marginBottom: '2px' } },
        `${list.length} ${plural(list.length, 'игрок', 'игрока', 'игроков')}`), h('div', { class: 'ellipsis' }, txt))));
  }

  function showOnline() {
    sheet((box) => {
      box.append(h('h3', null, 'Сейчас в Казике'), h('p', null, 'Только имена и аватарки — никаких ID.'));
      const ppl = h('div', { class: 'people' });
      for (const p of S.online) ppl.append(h('div', { class: 'person' }, avatar(p, 'm'), h('div', { class: 'grow' }, h('div', { class: 'ellipsis' }, p.name),
        h('div', { class: 'what' }, ACT_LABEL[p.act] || 'в зале')), p.h === S.me.h ? h('span', { class: 'tag' }, 'это ты') : null));
      box.append(ppl);
    });
  }

  // ── живые столы ──
  const crashBig = h('div', { class: 't-big' }), crashState = h('div', { class: 't-state' }), crashPl = h('span', { class: 't-players' });
  const roulBig = h('div', { class: 't-big' }), roulState = h('div', { class: 't-state' }), roulPl = h('span', { class: 't-players' });
  const potBig = h('div', { class: 't-big' }), potState = h('div', { class: 't-state' }), potPl = h('div');
  const duelBig = h('div', { class: 't-big' }), duelState = h('div', { class: 't-state' });
  const lt = (cls, art, name, big, st, foot, id) => h('button', { class: 'ltable ' + cls, onclick: () => openGame(id) },
    h('div', { class: 't-art', html: art }), h('div', null, h('div', { class: 't-name' }, name), st), h('div', null, big, h('div', { class: 't-foot' }, foot)));
  tablesBox.append(
    lt('t-crash', tileArt.crash, 'Краш', crashBig, crashState, crashPl, 'crash'),
    lt('t-roulette', tileArt.roulette, 'Рулетка', roulBig, roulState, roulPl, 'roulette'),
    lt('t-jackpot', tileArt.jackpot, 'Складчина', potBig, potState, potPl, 'jackpot'),
    lt('t-duel', tileArt.duel, 'Дуэли', duelBig, duelState, h('span', { class: 't-players' }, 'орёл или решка'), 'duel'));
  function tickTables() {
    const t = S.tables || {}, c = t.crash, r = t.roulette, j = t.jackpot;
    if (!c || c.phase === 'idle') { crashBig.textContent = 'x1,00'; crashState.textContent = 'ждёт пилотов'; }
    else if (c.phase === 'bet') { crashBig.textContent = left(c.bet_end - now()); crashState.textContent = 'приём ставок'; }
    else if (c.phase === 'run') { crashBig.textContent = fx(Math.floor(Math.exp(c.growth * Math.max(0, now() - c.start)) * 100) / 100); crashState.textContent = 'летит!'; }
    else { crashBig.textContent = fx(c.point || 1); crashState.textContent = 'улетело'; }
    crashPl.textContent = c?.players ? `${c.players} в раунде` : 'ставь первым';
    if (!r || r.phase === 'idle') { roulBig.textContent = '—'; roulState.textContent = 'стол свободен'; }
    else if (r.phase === 'bet') { roulBig.textContent = left(r.t_next - now()); roulState.textContent = 'делайте ставки'; }
    else if (r.phase === 'spin') { roulBig.textContent = '···'; roulState.textContent = 'шарик крутится'; }
    else { roulBig.textContent = String(r.result ?? '—'); roulState.textContent = 'выпало'; }
    roulPl.textContent = r?.players ? `${r.players} за столом` : (r?.history?.length ? 'были: ' + r.history.slice(0, 4).join(' · ') : 'европейская');
    potBig.textContent = j?.total ? fmtc(j.total) : '0';
    potState.textContent = !j || j.phase === 'open' ? (j?.players?.length ? 'ждём второго' : 'банк пуст') : j.phase === 'count' ? 'розыгрыш через ' + left(j.t_next - now()) : 'тянем билет…';
    potPl.replaceChildren(j?.players?.length ? stack(j.players, 4, 's') : h('span', { class: 't-players' }, 'кто первый?'));
    const n = t.duels || 0;
    duelBig.textContent = String(n); duelState.textContent = n ? plural(n, 'открытый вызов', 'открытых вызова', 'открытых вызовов') : 'вызовов нет';
  }

  function renderDuels(list) {
    clear(duelsBox);
    const open = (list || []).filter((d) => d.state === 'open' && !d.mine && !d.locked);
    if (!open.length) return;
    const box = h('div', { class: 'card', style: { marginTop: '10px' } });
    for (const d of open.slice(0, 3)) box.append(h('div', { class: 'duel' }, avatar(d, 'm'),
      h('div', { class: 'grow' }, h('div', { class: 'ellipsis' }, d.name, d.for_me ? ' вызывает тебя!' : ' бросил(а) вызов'),
        h('div', { class: 'd-amt' }, fmt(d.amount), ' ', h('span', { class: 'muted', style: { fontWeight: 500, fontFamily: 'var(--fb)' } }, 'сыроежек'))),
      h('button', { class: 'btn sm red', onclick: () => openGame('duel', { accept: d.id }) }, 'Принять')));
    duelsBox.append(box);
  }

  // ── доход ──
  const ecoCards = {};
  const ecoDefs = [
    ['bonus', 'Бонус', ecoArt.bonus, claimBonus], ['wheel', 'Колесо дня', ecoArt.wheel, () => wheelSheet()],
    ['work', 'Работа', ecoArt.work, () => doJob('work')], ['crime', 'Дело', ecoArt.crime, () => doJob('crime')],
  ];
  for (const [id, name, art, fn] of ecoDefs) {
    const sub = h('div', { class: 'e-sub' });
    const el = h('button', { class: 'eco', onclick: () => busy(el, fn) }, h('div', { class: 'e-ic', html: art }), h('div', null, h('div', { class: 'e-name' }, name), sub));
    ecoCards[id] = { el, sub };
    ecoBox.append(el);
  }
  function tickEco() {
    const labels = { bonus: 'Забрать доход', wheel: 'Крутить!', work: 'Выйти на смену', crime: 'Пойти на дело' };
    for (const id of Object.keys(ecoCards)) {
      const t = (S.timers?.[id] || 0) - now(), c = ecoCards[id];
      const ready = t <= 0 || (id === 'bonus' && S.me?.creator);
      c.el.classList.toggle('ready', ready);
      c.sub.textContent = ready ? labels[id] : 'через ' + left(t);
    }
  }
  function renderRake() {
    const amt = S.me.rake || 0;
    const btn = h('button', { class: 'btn sm gold' + (amt < 1 ? ' off' : ''), onclick: () => busy(btn, claimRake) }, 'Забрать');
    rakeBox.replaceChildren(h('div', { class: 'rake' }, h('div', { style: { width: '40px', height: '40px', flex: 'none' }, html: ecoArt.rake }),
      h('div', { class: 'grow' }, h('div', { class: 'muted', style: { fontSize: '12px' } }, `Кешбэк ${String(S.me.rake_rate).replace('.', ',')}% с каждой ставки`),
        h('div', { class: 'r-amt num' }, fmt(amt))), btn));
  }
  function renderFire() {
    const f = S.fire || { q: 0, step: 10, pct: 0, max_pct: 25, to_next: 10 };
    const steps = f.max_pct / 5, full = Math.floor(f.pct / 5);
    const segs = h('div', { class: 'fire' });
    for (let i = 0; i < steps; i++) {
      const w = i < full ? 100 : i === full ? ((f.q % f.step) / f.step) * 100 : 0;
      segs.append(h('i', null, h('b', { style: { width: w + '%' } })));
    }
    fireBox.replaceChildren(h('div', { class: 'row' }, h('div', { class: 'grow' },
      h('div', { class: 'num', style: { fontSize: '18px' } }, f.pct ? `+${f.pct}% к бонусу` : 'Огонёк не горит'),
      h('div', { class: 'muted', style: { fontSize: '12.5px', marginTop: '2px' } },
        f.pct >= f.max_pct ? 'Максимум! Забери бонус — сгорит часть огонька.' : `Ещё ${f.to_next} ${plural(f.to_next, 'ставка', 'ставки', 'ставок')} до +${f.pct + 5}%`)),
      h('div', { style: { fontSize: '30px' } }, f.pct ? '🔥' : '🪵')), segs);
  }
  function renderTasks() {
    clear(tasksBox);
    for (const t of S.tasks || []) {
      const done = t.p >= t.goal;
      const btn = t.claimed ? h('span', { class: 'moss num', style: { fontSize: '12px' } }, '✓ получено')
        : h('button', { class: 'btn xs ' + (done ? 'gold' : 'ghost off'), onclick: () => busy(btn, () => claimTask(t.id)) }, done ? 'Забрать' : '+' + fmtc(t.reward));
      tasksBox.append(h('div', { class: 'task' + (t.claimed ? ' done' : '') }, h('div', { class: 'grow' },
        h('div', { class: 't-txt' }, t.text), h('div', { class: 'bar' }, h('i', { style: { width: (Math.min(1, t.p / t.goal) * 100) + '%' } })),
        h('div', { class: 'dim', style: { fontSize: '11px', marginTop: '4px' } }, `${t.p} / ${t.goal}`)), btn));
    }
    if (!S.tasks?.length) tasksBox.append(h('div', { class: 'empty' }, 'Заданий нет'));
  }
  function renderFeed() {
    clear(feedBox);
    const list = (S.feed || []).slice(0, 12);
    if (!list.length) { feedBox.append(h('div', { class: 'empty' }, 'Тут появятся крупные выигрыши, дуэли и новые уровни игроков чата.')); return; }
    const fb = h('div', { class: 'feed' });
    for (const f of list) fb.append(h('div', { class: 'fitem' }, avatar(f, 's'), h('div', { class: 'grow f-txt' },
      h('div', { class: 'ellipsis' }, h('b', null, f.name), ' ', f.text), h('div', { class: 'f-time' }, ago(f.ts))),
      f.amount ? h('span', { class: 'f-amt' + (f.kind === 'win' || f.kind === 'wheel' ? '' : ' plain') }, (f.kind === 'win' || f.kind === 'wheel' ? '+' : '') + fmtc(f.amount)) : null));
    feedBox.append(fb);
  }

  async function claimBonus() {
    const d = await api('bonus');
    S.timers.bonus = d.next; S.fire = d.fire; tickEco(); renderFire();
    receiptSheet(d);
  }
  async function claimRake() {
    const d = await api('rake');
    S.me.rake = 0; renderRake(); sfx.coin(); haptic('success');
    toast(`Кешбэк +${fmt(d.amount)} сыроежек`, 'ok');
  }
  async function claimTask(id) {
    const d = await api('task', { id });
    S.tasks = d.tasks; renderTasks(); sfx.win(); haptic('success'); events(d.events);
    toast(`Задание выполнено: +${fmt(d.reward)} сыроежек`, 'ok');
  }
  async function doJob(kind) {
    const d = await api(kind);
    S.timers[kind] = d.next; tickEco();
    jobSheet(kind, d);
  }

  function renderAll() { renderMe(); renderOnline(); tickTables(); tickEco(); renderRake(); renderFire(); renderTasks(); renderFeed(); }
  renderAll();
  ticker(() => { if (page.classList.contains('on')) { tickTables(); tickEco(); } });
  on('poll', (d) => {
    if (S.screen !== 'lobby') return;
    renderOnline(); tickTables(); renderRake();
    if (d.feed) renderFeed(); if (d.fire) renderFire(); if (d.tasks) renderTasks(); if (d.duels) renderDuels(d.duels);
  });
  on('refresh', () => api('me', {}, { quiet: true }).then((d) => {
    Object.assign(S, { me: d.me, timers: d.timers, tasks: d.tasks, fire: d.fire, online: d.online, feed: d.feed, tables: d.tables });
    renderAll();
  }).catch(() => {}));
  return { show() { renderAll(); } };
}

// ── квитанция о доходах (как в /bonus) ──
function receiptSheet(d) {
  const r = d.receipt || {};
  const ln = (k, v, cls = '') => h('div', { class: 'ln ' + cls }, h('span', null, k), h('span', null, v));
  sfx.coin(); haptic('success');
  sheet((box, close) => {
    const rc = h('div', { class: 'receipt' }, h('h4', null, 'Квитанция о доходах'),
      h('div', { class: 'rc-sub' }, S.chat?.title || 'Казик', ' · ', new Date().toLocaleString('ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })),
      r.base ? ln('Ежедневный бонус', '+' + fmt(r.base), 'plus') : null,
      ln('Доход с бизнесов', '+' + fmt(r.business || 0)), ln('Доход с машин', '+' + fmt(r.car || 0)),
      r.meme_bonus ? ln('Бонус от карточек', '+' + fmt(r.meme_bonus), 'plus') : null,
      r.prestige_bonus ? ln(`Престиж ${r.prestige_badge || ''} ур. ${r.prestige_level}`, '+' + fmt(r.prestige_bonus), 'plus') : null,
      ln(`Налог (${r.tax_percent || 0}%)`, '−' + fmt(r.tax_amount || 0), 'minus'),
      r.luxury_tax ? ln('Налог на сверхкапитал', '−' + fmt(r.luxury_tax), 'minus') : null,
      d.boost ? ln(`🔥 Огонёк +${d.boost_pct}%`, '+' + fmt(d.boost), 'plus') : null,
      h('div', { class: 'tot' }, h('span', null, 'Итого'), h('span', null, fmt((r.total || 0) + (d.boost || 0)))),
      h('div', { class: 'stamp' }, 'Выплачено'));
    box.append(rc, d.boost ? null : h('p', { style: { textAlign: 'center' } }, 'Играй в казино: каждые 10 ставок разжигают огонёк +5% к следующему бонусу.'),
      h('button', { class: 'btn red wide', onclick: close }, 'Забрать'));
    setTimeout(() => { const b = rc.getBoundingClientRect(); burst(b.left + b.width / 2, b.top + 40, 16, SPORE); }, 500);
  });
}

// ── работа и дело с премией ──
function jobSheet(kind, d) {
  const good = kind === 'work' || d.ok_crime;
  good ? (sfx.coin(), haptic('success')) : (sfx.lose(), haptic('error'));
  sheet((box, close) => {
    const title = kind === 'work' ? `Ты ${d.job}` : d.text;
    box.append(h('h3', null, kind === 'work' ? '💼 Смена окончена' : (d.ok_crime ? '🥷 Дело сделано' : '🚔 Провал')),
      h('p', null, title + (kind === 'crime' ? ` · шанс был ${d.chance}%` : '')),
      h('div', { class: 'num', style: { fontSize: '34px', textAlign: 'center', margin: '6px 0 12px', color: d.amount >= 0 ? 'var(--gold)' : 'var(--red)' } },
        (d.amount >= 0 ? '+' : '') + fmt(d.amount)));
    if (d.notes?.length) box.append(h('div', { class: 'chipline', style: { marginBottom: '12px' } }, d.notes.map((n) => h('span', null, n))));
    if (d.game) box.append(premium(d.game, close)); else box.append(h('button', { class: 'btn wide', onclick: close }, 'Понятно'));
  });
}

function premium(g, close) {
  const wrap = h('div', { class: 'card' });
  const bar = h('i'); const timer = h('div', { class: 'timer' }, bar);
  const opts = h('div', { class: 'premium-opts' + (/^\d+$/.test(g.options[0]) ? ' num' : '') });
  let done = false;
  const t0 = performance.now();
  const anim = () => { if (done) return; const k = 1 - (performance.now() - t0) / (g.ttl * 1000); bar.style.width = Math.max(0, k * 100) + '%'; if (k > 0) requestAnimationFrame(anim); };
  requestAnimationFrame(anim);
  g.options.forEach((o, i) => {
    const b = h('button', { onclick: async () => {
      if (done) return; done = true;
      try {
        const r = await api('premium', { token: g.token, pick: i });
        opts.children[r.correct]?.classList.add('ok');
        if (!r.win) { b.classList.add('bad'); sfx.lose(); haptic('error'); toast('Премия сгорела', 'err'); }
        else { sfx.win(); haptic('success'); const rc = b.getBoundingClientRect(); burst(rc.left + rc.width / 2, rc.top, 14, SPORE); toast(`Премия +${fmt(r.bonus)}!`, 'ok'); }
        setTimeout(close, 1300);
      } catch { setTimeout(close, 900); }
    } }, o);
    opts.append(b);
  });
  wrap.append(h('div', { class: 'row' }, h('div', { class: 'grow' }, h('div', { class: 'num', style: { fontSize: '14px' } }, '🎮 Премия ', fmt(g.bonus)),
    h('div', { class: 'muted', style: { fontSize: '13px' } }, g.prompt))), opts, timer);
  return wrap;
}

// ── колесо дня ──
export function wheelSheet() {
  const segs = S.cfg.wheel, n = segs.length, R = 100;
  const colors = ['#f6efe2', '#e2493b', '#f6efe2', '#8fbf6a', '#f6efe2', '#e7b54a'];
  const parts = segs.map((m, i) => {
    const a0 = (i / n) * 2 * Math.PI - Math.PI / 2, a1 = ((i + 1) / n) * 2 * Math.PI - Math.PI / 2, am = (a0 + a1) / 2;
    const p = (a, r) => `${R + Math.cos(a) * r} ${R + Math.sin(a) * r}`;
    const fill = m >= 25 ? '#e7b54a' : m >= 10 ? '#e2493b' : colors[i % colors.length];
    const tx = R + Math.cos(am) * 70, ty = R + Math.sin(am) * 70;
    return `<path d="M${R} ${R}L${p(a0, 96)}A96 96 0 0 1 ${p(a1, 96)}z" fill="${fill}" stroke="#12100e" stroke-width="1.5"/>` +
      `<text x="${tx}" y="${ty}" transform="rotate(${(am * 180) / Math.PI + 90} ${tx} ${ty})" text-anchor="middle" dominant-baseline="middle" font-family="Unbounded" font-weight="800" font-size="15" fill="${fill === '#f6efe2' ? '#2a1d17' : '#fff7ee'}">×${m}</text>`;
  }).join('');
  const wheel = h('div', { class: 'w', html: `<svg viewBox="0 0 200 200"><circle cx="100" cy="100" r="99" fill="#2a2420"/>${parts}<circle cx="100" cy="100" r="18" fill="#2a2420" stroke="#e7b54a" stroke-width="3"/></svg>` });
  const ptr = h('div', { class: 'ptr', html: '<svg viewBox="0 0 28 34"><path d="M14 33 2 6a12 12 0 1 1 24 0z" fill="#f3eadb" stroke="#12100e" stroke-width="2"/><circle cx="14" cy="11" r="4" fill="#e2493b"/></svg>' });
  const res = h('div', { class: 'num', style: { fontSize: '30px', textAlign: 'center', minHeight: '40px', color: 'var(--gold)' } });
  sheet((box, close) => {
    const next = (S.timers.wheel || 0) - now();
    let spun = false;
    const btn = h('button', { class: 'btn red wide big' + (next > 0 ? ' off' : ''), onclick: () => (spun ? close() : busy(btn, spin)) }, next > 0 ? 'Через ' + left(next) : 'Крутить колесо');
    box.append(h('h3', null, 'Колесо дня'), h('p', null, 'Раз в 20 часов. Награда растёт с уровнем и престижем.'),
      h('div', { class: 'fwheel' }, wheel, ptr), res, btn);
    async function spin() {
      const d = await api('wheel');
      S.timers.wheel = d.next; btn.classList.add('off');
      const target = 360 * 7 + (360 - ((d.index + 0.5) / n) * 360) + (Math.random() * 16 - 8);
      wheel.style.transform = `rotate(${target}deg)`;
      sfx.roll();
      let last = 0;
      const t0 = performance.now();
      const tick = (t) => { if (t - last > 120 && t - t0 < 4600) { sfx.tick(); last = t; } if (t - t0 < 5200) requestAnimationFrame(tick); };
      requestAnimationFrame(tick);
      await new Promise((r) => setTimeout(r, 5300));
      res.textContent = `×${d.mult} = +${fmt(d.prize)}`;
      d.mult >= 10 ? sfx.big() : sfx.win(); haptic('success'); btn.classList.remove('off');
      const b = wheel.getBoundingClientRect(); burst(b.left + b.width / 2, b.top + b.height / 2, d.mult >= 10 ? 30 : 14, SPORE);
      spun = true; btn.textContent = 'Отлично!';
    }
  });
}
