// «Топ» и «Профиль».
import { h, S, api, fmt, fmtc, fx, left, now, avatar, sheet, clear, prefs, ticker, sfx, haptic, plural } from './core.js';
import { icons, achBadge, ACH_ICON } from './art.js';
import { levelRing } from './lobby.js';

const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0) + '%';

function podium(rows, val) {
  const order = [rows[1], rows[0], rows[2]];
  const el = h('div', { class: 'podium' });
  order.forEach((r, i) => {
    const n = [2, 1, 3][i];
    if (!r) { el.append(h('div')); return; }
    el.append(h('button', { class: 'pod n' + n, onclick: () => playerSheet(r) },
      n === 1 ? h('div', { class: 'crown', html: icons.crown }) : null, avatar(r, n === 1 ? 'xl' : 'l'),
      h('div', { class: 'p-name ellipsis' }, r.name), h('div', { class: 'p-val' }, val(r)), h('div', { class: 'p-base' }, n)));
  });
  return el;
}

function lrow(r, pos, val, sub) {
  return h('button', { class: 'lrow' + (r.h === S.me.h ? ' mine' : ''), style: { width: '100%', textAlign: 'left' }, onclick: () => playerSheet(r) },
    h('span', { class: 'pos' }, pos), avatar(r, 'm'), h('div', { class: 'grow' }, h('div', { class: 'l-name ellipsis' }, r.name, r.badge ? ' ' + r.badge : '', r.vip ? ' 💎' : ''),
      sub ? h('div', { class: 'l-sub ellipsis' }, sub) : null), h('div', { class: 'l-val' }, val));
}

export function mountTop(page) {
  let tab = 'rich';
  const seg = h('div', { class: 'seg' });
  const body = h('div');
  const tabsDef = [['rich', 'Богачи'], ['league', 'Лига недели'], ['clans', 'Кланы']];
  for (const [id, name] of tabsDef) seg.append(h('button', { class: id === tab ? 'on' : '', onclick: (e) => { tab = id; [...seg.children].forEach((b) => b.classList.remove('on')); e.currentTarget.classList.add('on'); sfx.tap(); load(); } }, name));
  page.append(h('div', { class: 'label' }, 'Топ чата'), seg, body);
  let stopTick = null;
  async function load() {
    stopTick?.(); stopTick = null;
    let d;
    try { d = await api('top', { tab }); } catch { return; }
    clear(body);
    if (tab === 'rich') {
      const rows = d.rich || [];
      if (!rows.length) { body.append(h('div', { class: 'empty' }, 'Пока пусто')); return; }
      body.append(podium(rows, (r) => fmtc(r.balance)));
      const list = h('div', { class: 'card' });
      rows.slice(3).forEach((r, i) => list.append(lrow(r, i + 4, fmtc(r.balance), [`ур. ${r.level}`, r.clan ? `⚔ ${r.clan}` : null].filter(Boolean).join(' · '))));
      if (rows.length > 3) body.append(list);
      body.append(h('div', { class: 'empty' }, d.pos ? `Ты на ${d.pos} месте` : 'Тебя пока нет в топ-30 — время это исправить!'));
    } else if (tab === 'league') {
      const lg = d.league;
      const cd = h('span', { class: 'countdown' });
      stopTick = ticker(() => { cd.textContent = 'до конца недели ' + left(lg.ends - now()); });
      body.append(h('div', { class: 'card', style: { marginTop: '12px' } }, h('div', { class: 'pool' }, h('div', { style: { fontSize: '34px' } }, '🏆'),
        h('div', { class: 'grow' }, h('div', { class: 'muted', style: { fontSize: '12px' } }, 'Призовой фонд недели'), h('div', { class: 'p-amt num' }, fmt(lg.pool)), cd)),
      h('div', { class: 'prizes' }, lg.prizes.map((p, i) => h('div', null, h('small', null, ['1 место', '2 место', '3 место'][i]), fmtc(p)))),
      h('div', { class: 'dim', style: { fontSize: '12px', marginTop: '10px' } }, 'Фонд растёт с каждой ставки в чате (0,5% оборота) и комиссий дуэлей и складчины. Места — по чистому выигрышу за неделю.')));
      const rows = lg.rows || [];
      const val = (r) => h('span', { class: r.net >= 0 ? 'moss' : 'red' }, (r.net >= 0 ? '+' : '') + fmtc(r.net));
      if (rows.length) {
        const top3 = rows.filter((r) => r.net > 0).slice(0, 3);
        if (top3.length) body.append(podium(top3, (r) => '+' + fmtc(r.net)));
        const list = h('div', { class: 'card', style: { marginTop: top3.length ? 0 : '12px' } });
        rows.forEach((r, i) => { if (i >= top3.length) list.append(lrow(r, i + 1, val(r), `${fmt(r.games)} ${plural(r.games, 'ставка', 'ставки', 'ставок')} · оборот ${fmtc(r.wag)}`)); });
        if (list.children.length) body.append(list);
      } else body.append(h('div', { class: 'empty' }, 'На этой неделе ещё никто не играл. Первый выигрыш — и ты в лиге!'));
      if (lg.me) body.append(h('div', { class: 'empty' }, `Ты на ${lg.me.pos} месте: ${lg.me.net >= 0 ? '+' : ''}${fmt(lg.me.net)}`));
      if (lg.prev?.winners?.length) {
        const prev = h('div', { class: 'card' });
        lg.prev.winners.forEach((w, i) => prev.append(lrow(w, ['🥇', '🥈', '🥉'][i], '+' + fmtc(w.prize), `выиграл ${fmtc(w.net)}`)));
        body.append(h('div', { class: 'label' }, 'Победители прошлой недели'), prev);
      }
    } else {
      const rows = d.clans || [];
      if (!rows.length) { body.append(h('div', { class: 'empty' }, 'Кланов пока нет. Создать: /clan create в чате.')); return; }
      const list = h('div', { class: 'card', style: { marginTop: '12px' } });
      rows.forEach((c, i) => list.append(h('div', { class: 'lrow' + (c.name === d.mine ? ' mine' : '') }, h('span', { class: 'pos' }, i + 1),
        h('div', { class: 'av m', style: { '--c': '#3a3229', color: 'var(--cream)' } }, '⚔'),
        h('div', { class: 'grow' }, h('div', { class: 'l-name ellipsis' }, c.name), h('div', { class: 'l-sub' },
          `${c.members} ${plural(c.members, 'участник', 'участника', 'участников')} · казна ${fmtc(c.treasury)}`)),
        h('div', { class: 'l-val' }, h('div', null, fmtc(c.wag)), h('div', { class: 'l-sub ' + (c.net >= 0 ? 'moss' : 'red') }, (c.net >= 0 ? '+' : '') + fmtc(c.net))))));
      body.append(h('div', { class: 'dim', style: { fontSize: '12px', margin: '12px 2px 0' } }, 'Кланы недели — по обороту участников в Казике: сидеть в клане мало, надо играть.'), list);
    }
  }
  load();
  return { show: load };
}

function statsGrid(p) {
  const st = p.stats || {};
  const cells = [
    ['Ставок', fmt(st.n)], ['Побед', pct(st.w, st.n)], ['Оборот', fmtc(st.wag)],
    ['Выиграно', fmtc(st.won)], ['Лучший куш', fmtc(st.best)], ['Лучший x', st.bestx ? fx(st.bestx) : '—'],
    ['Серия', fmt(st.bstreak)], ['Дуэлей', fmt(st.duels_won)], ['Кешбэк', fmtc(p.rake_total || 0)],
  ];
  return h('div', { class: 'stats' }, cells.map(([k, v]) => h('div', { class: 'stat' }, h('b', null, v), h('span', null, k))));
}

function achGrid(got) {
  const grid = h('div', { class: 'achs' });
  for (const [id, a] of Object.entries(S.cfg.ach)) {
    const has = got.includes(id);
    grid.append(h('button', { class: 'ach' + (has ? '' : ' locked'), onclick: () => { sfx.tap(); sheet((b) => b.append(h('h3', null, (ACH_ICON[id] || '🏅') + ' ' + a.name), h('p', null, a.desc + (has ? ' — получено!' : '')))); } },
      h('div', { style: { position: 'relative', width: '38px', height: '38px' } }, h('div', { html: achBadge(has) }),
        h('div', { style: { position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', fontSize: '17px' } }, ACH_ICON[id] || '🏅')),
      h('span', null, a.name)));
  }
  return grid;
}

export async function playerSheet(r) {
  if (!r?.h) return;
  let d;
  try { d = await api('profile', { h: r.h }); } catch { return; }
  const p = d.player;
  sheet((box) => {
    box.append(h('div', { class: 'phead' }, levelRing({ ...p, h: p.h, name: p.name }, 'l'), h('div', { class: 'me-name' }, p.name),
      h('div', { class: 'me-title' }, p.title, ' · уровень ', p.level, p.clan ? ` · ⚔ ${p.clan}` : '', p.prestige?.level ? ` · ${p.prestige.badge} ${p.prestige.name}` : '')),
    h('div', { class: 'num', style: { textAlign: 'center', fontSize: '22px', marginBottom: '14px' } }, fmt(p.balance), h('span', { class: 'muted', style: { fontSize: '13px', fontFamily: 'var(--fb)' } }, ' сыроежек')),
    statsGrid(p), h('div', { class: 'label' }, 'Достижения'), achGrid(p.ach || []));
  });
}

export function mountProfile(page) {
  async function load() {
    let d;
    try { d = await api('profile'); } catch { return; }
    S.me = d.me;
    const p = d.player, lg = d.legacy;
    clear(page);
    page.append(h('div', { class: 'card phead' }, levelRing(d.me, 'xl'), h('div', { class: 'me-name' }, d.me.name),
      h('div', { class: 'me-title' }, d.me.title, ' · уровень ', d.me.level),
      h('div', { class: 'xp', style: { width: '70%' } }, h('i', { style: { width: (((d.me.xp - d.me.xp_lo) / Math.max(1, d.me.xp_hi - d.me.xp_lo)) * 100) + '%' } })),
      h('div', { class: 'dim', style: { fontSize: '11.5px', marginTop: '6px' } }, `${fmt(d.me.xp)} XP · до следующего уровня ${fmt(d.me.xp_hi - d.me.xp)}`)),
    h('div', { class: 'label' }, 'Статистика V2'), statsGrid(p));
    if (p.games?.length) {
      const g = h('div', { class: 'card' });
      p.games.forEach((x) => g.append(h('div', { class: 'kv' }, h('span', { class: 'k' }, x.name), h('span', { class: 'dim', style: { fontSize: '12px' } }, `${fmt(x.n)} · побед ${pct(x.w, x.n)}`),
        h('span', { class: 'v num ' + (x.won - x.wag >= 0 ? 'moss' : 'red'), style: { fontSize: '13px' } }, (x.won - x.wag >= 0 ? '+' : '') + fmtc(x.won - x.wag)))));
      page.append(h('div', { class: 'label' }, 'По играм'), g);
    }
    page.append(h('div', { class: 'label' }, 'Достижения', h('span', { class: 'more' }, `${(p.ach || []).length} из ${Object.keys(S.cfg.ach).length}`)), achGrid(p.ach || []));
    if (p.hist?.length) {
      const hs = h('div', { class: 'card' });
      p.hist.forEach((x) => hs.append(h('div', { class: 'hist' }, h('div', { class: 'grow' }, h('div', null, x.name), h('div', { class: 'dim', style: { fontSize: '11.5px' } },
        new Date(x.ts * 1000).toLocaleString('ru-RU', { hour: '2-digit', minute: '2-digit', day: 'numeric', month: 'short' }), ' · ставка ', fmtc(x.bet))),
      h('div', { class: 'h-x ' + (x.pay > x.bet ? 'moss' : x.pay === x.bet ? 'muted' : 'red') }, (x.pay - x.bet >= 0 ? '+' : '−') + fmtc(Math.abs(x.pay - x.bet))))));
      page.append(h('div', { class: 'label' }, 'Последние ставки'), hs);
    }
    const kv = (k, v) => h('div', { class: 'kv' }, h('span', { class: 'k' }, k), h('span', { class: 'v' }, v));
    const legacy = h('div', { class: 'card' },
      kv('Баланс', fmt(lg.balance)), kv('Вклад в банке', lg.bank ? fmt(lg.bank) + (lg.bank_name ? ` · ${lg.bank_name}` : '') : '—'),
      kv('Престиж', lg.prestige.level ? `${lg.prestige.badge} ${lg.prestige.name} (${lg.prestige.level}/6)` : 'нет'),
      kv('Статус', [lg.vip ? '💎 VIP' : null, lg.banker ? '🏦 Банкир' : null].filter(Boolean).join(' · ') || 'обычный'),
      kv('Питомец', lg.pet ? lg.pet.name : 'нет'), kv('Клан', lg.clan ? '⚔ ' + lg.clan : 'нет'),
      kv('Бизнесы', lg.biz.length ? `${lg.biz.reduce((a, b) => a + b.count, 0)} шт.` : 'нет'), kv('Машины', lg.cars.length ? `${lg.cars.reduce((a, b) => a + b.count, 0)} шт.` : 'нет'),
      kv('Доход с имущества', '+' + fmt(lg.income) + ' за бонус'), kv('Мем-карточки', fmt(lg.cards)), lg.debts ? kv('Долги', fmt(lg.debts)) : null,
      kv('Кешбэк', `${String(d.me.rake_rate).replace('.', ',')}% от ставок`));
    if (lg.diseases?.length) legacy.append(h('div', { class: 'notice', style: { marginTop: '10px' } }, '🦠', h('div', null, lg.diseases.map((x) => h('div', null, h('b', null, x.name), ' — ', x.desc)))));
    if (lg.pet?.id === 'unicorn') legacy.append(h('div', { class: 'dim', style: { fontSize: '12px', marginTop: '8px' } }, '🦄 В V2 единорог не подкручивает шансы, а даёт +0,3% кешбэка — игры здесь честные.'));
    page.append(h('div', { class: 'label' }, 'Твоё хозяйство', h('span', { class: 'more' }, 'из основного бота')), legacy);
    const tog = (key, name) => {
      const t = h('button', { class: 'toggle' + (prefs.get(key, true) ? ' on' : ''), 'aria-label': name, onclick: () => { const v = !prefs.get(key, true); prefs.set(key, v); t.classList.toggle('on', v); if (v) { sfx.tap(); haptic('light'); } } });
      return h('div', { class: 'kv' }, h('span', { class: 'k' }, name), h('span', { class: 'v' }, t));
    };
    page.append(h('div', { class: 'label' }, 'Настройки'), h('div', { class: 'card' }, tog('sound', 'Звуки'), tog('haptics', 'Вибрация')),
      h('div', { class: 'empty' }, 'Казик V2 · ', S.chat?.title || ''));
  }
  load();
  return { show: load };
}
