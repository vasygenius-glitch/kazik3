// Карточные игры: Блэкджек, Баккара, Видео-покер.
import { h, S, api, fmt, fx, sleep, sfx, haptic, busy, clear } from './core.js';
import { betPanel, pcard, banner, celebrate, outcome } from './ui.js';

function syncCards(box, cards, { delay = 0, gap = 260 } = {}) {
  const have = box.children.length;
  let k = 0;
  cards.forEach((c, i) => {
    const el = box.children[i];
    if (!el) { box.append(pcard(c, { deal: true, delay: delay + k * gap })); k++; setTimeout(() => sfx.card(), delay + (k - 1) * gap); }
    else if (el.classList.contains('down') && c !== '??') el.flipTo(c);
  });
  while (box.children.length > cards.length) box.lastChild.remove();
  return Math.max(0, cards.length - have);
}

// ───────────── Блэкджек ─────────────
export function blackjack(root, opts) {
  const dealerHand = h('div', { class: 'hand' }), dScore = h('span', { class: 'score' }, '—');
  const hands = h('div', { class: 'row', style: { justifyContent: 'center', gap: '22px', alignItems: 'flex-start' } });
  const felt = h('div', { class: 'felt stage', style: { padding: '16px 8px 18px', minHeight: '360px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', gap: '10px' } },
    h('div', { class: 'col', style: { alignItems: 'center', gap: '8px' } }, h('div', { class: 'row' }, h('span', { class: 'felt-title' }, 'Дилер'), dScore), dealerHand),
    h('div', { html: '<svg viewBox="0 0 300 54" style="width:100%;height:46px"><path id="arc" d="M20 10 Q150 62 280 10" fill="none"/><text font-family="Unbounded" font-weight="700" font-size="9.5" letter-spacing="1.4" fill="rgba(243,234,219,.42)"><textPath href="#arc" startOffset="50%" text-anchor="middle">БЛЭКДЖЕК 3:2 · ДИЛЕР ДО 17</textPath></text></svg>' }),
    hands);
  const ban = banner(felt);
  const bet = betPanel('bj');
  const deal = h('button', { class: 'btn red big wide', onclick: () => busy(deal, start) }, 'Раздать');
  const acts = h('div', { class: 'actions hidden' });
  const btn = (txt, act, cls = '') => h('button', { class: 'btn ' + cls, onclick: (e) => busy(e.currentTarget, () => act_(act)) }, txt);
  const bHit = btn('Ещё', 'hit', 'red'), bStand = btn('Хватит', 'stand', 'gold'), bDbl = btn('Удвоить', 'double'), bSplit = btn('Сплит', 'split');
  acts.append(bHit, bStand, bDbl, bSplit);
  root.append(felt, acts, bet.el, deal);
  root.style.setProperty('--cw', Math.min(68, Math.floor((innerWidth - 60) / 5)) + 'px');

  function handBox(i) {
    while (hands.children.length <= i) {
      const sc = h('span', { class: 'score' }, '—');
      const w = h('div', { class: 'col', style: { alignItems: 'center', gap: '8px', transition: 'opacity .3s' } }, h('div', { class: 'hand' }), h('div', { class: 'row' }, sc, h('span', { class: 'felt-title bet' })));
      hands.append(w);
    }
    return hands.children[i];
  }
  function scoreTag(el, score, soft, res, cards) {
    el.textContent = cards.length ? (soft && score < 21 && res == null ? `${score - 10}/${score}` : String(score)) : '—';
    el.className = 'score' + (score > 21 ? ' bust' : '') + (res === 'bj' ? ' bj' : '');
  }
  function playing(on) {
    acts.classList.toggle('hidden', !on); deal.classList.toggle('hidden', on); bet.lock(on);
  }
  async function render(v, animate = true) {
    if (v.hands.length > 1 && hands.children.length === 1) {
      hands.children[0].querySelector('.hand').replaceChildren();
      root.style.setProperty('--cw', Math.min(52, Math.floor((innerWidth - 80) / 6)) + 'px');
    }
    let added = 0;
    v.hands.forEach((hd, i) => {
      const box = handBox(i);
      added += syncCards(box.querySelector('.hand'), hd.cards, { delay: added * 260 });
      scoreTag(box.querySelector('.score'), hd.score, hd.soft, hd.res, hd.cards);
      box.querySelector('.bet').textContent = fmt(hd.bet) + (hd.dbl ? ' ×2' : '');
      box.style.opacity = v.done || i === v.cur ? 1 : 0.45;
    });
    while (hands.children.length > v.hands.length) hands.lastChild.remove();
    if (!v.done) {
      added += syncCards(dealerHand, v.dealer, { delay: added * 260 });
      dScore.textContent = v.dscore; dScore.className = 'score';
      bDbl.classList.toggle('off', !v.can?.double); bSplit.classList.toggle('off', !v.can?.split);
      playing(true);
      return;
    }
    // Раскрытие дилера: переворот закрытой карты и добор по одной.
    await sleep(animate ? 300 + added * 260 : 0);
    const hidden = dealerHand.children[1];
    if (hidden?.classList.contains('down')) { hidden.flipTo(v.dealer[1]); await sleep(animate ? 520 : 0); }
    for (let i = dealerHand.children.length; i < v.dealer.length; i++) {
      dealerHand.append(pcard(v.dealer[i], { deal: true })); sfx.card(); await sleep(animate ? 480 : 0);
    }
    if (!dealerHand.children.length) syncCards(dealerHand, v.dealer);
    dScore.textContent = v.dscore; dScore.className = 'score' + (v.dscore > 21 ? ' bust' : '');
    const names = { bj: 'Блэкджек!', win: 'Победа', push: 'Ничья', lose: 'Дилер выиграл', bust: 'Перебор' };
    const res = v.hands.length === 1 ? v.hands[0].res : (v.payout > v.wager ? 'win' : v.payout === v.wager ? 'push' : 'lose');
    const oc = outcome(v);
    ban.show(names[res] || oc.title, v.payout > v.wager ? '+' + fmt(v.payout - v.wager) : v.payout === v.wager ? 'ставка возвращена' : '−' + fmt(v.wager), oc.kind, 2600);
    celebrate(v, felt);
    playing(false);
  }
  async function start() {
    ban.hide(); clear(dealerHand); clear(hands);
    root.style.setProperty('--cw', Math.min(68, Math.floor((innerWidth - 60) / 5)) + 'px');
    const v = await api('play/bj', { action: 'start', bet: bet.get() });
    haptic('light');
    await render(v);
  }
  async function act_(action) {
    haptic('light');
    const v = await api('play/bj', { action });
    await render(v);
  }
  if (opts.resume) render({ ...opts.resume, done: false }, false);
  return { destroy: bet.destroy };
}

// ───────────── Баккара ─────────────
export function baccarat(root) {
  const pHand = h('div', { class: 'hand' }), bHand = h('div', { class: 'hand' });
  const pScore = h('span', { class: 'score' }, '—'), bScore = h('span', { class: 'score' }, '—');
  const zone = (name, hand, sc) => h('div', { class: 'col grow', style: { alignItems: 'center', gap: '10px' } }, h('div', { class: 'row' }, h('span', { class: 'felt-title' }, name), sc), hand);
  const felt = h('div', { class: 'felt stage', style: { padding: '20px 8px', minHeight: '250px', display: 'flex', gap: '6px', alignItems: 'center' } },
    zone('Игрок', pHand, pScore), h('div', { style: { width: '1px', alignSelf: 'stretch', background: 'rgba(243,234,219,.12)' } }), zone('Банкир', bHand, bScore));
  root.style.setProperty('--cw', Math.min(56, Math.floor((innerWidth - 70) / 6)) + 'px');
  const ban = banner(felt);
  let side = 'player';
  const c = S.cfg.baccarat;
  const picks = h('div', { class: 'picks', style: { gridTemplateColumns: '1fr 1fr 1fr' } });
  const pick = (id, name) => h('button', { class: 'pick' + (id === side ? ' on' : ''), onclick: (e) => { side = id; [...picks.children].forEach((b) => b.classList.remove('on')); e.currentTarget.classList.add('on'); sfx.chip(); haptic('select'); } },
    h('b', null, name), h('span', null, fx(c[id])));
  picks.append(pick('player', 'Игрок'), pick('tie', 'Ничья'), pick('banker', 'Банкир'));
  const bet = betPanel('baccarat');
  const go = h('button', { class: 'btn red big wide', onclick: () => busy(go, play) }, 'Раздать');
  root.append(felt, picks, bet.el, go);
  async function play() {
    ban.hide(); clear(pHand); clear(bHand); pScore.textContent = bScore.textContent = '—';
    pScore.className = bScore.className = 'score';
    const r = await api('play/baccarat', { bet: bet.get(), side });
    const seq = [['p', 0], ['b', 0], ['p', 1], ['b', 1]];
    if (r.player[2]) seq.push(['p', 2]);
    if (r.banker[2]) seq.push(['b', 2]);
    const val = (cd) => (cd[0] === 'A' ? 1 : 'TJQK'.includes(cd[0]) ? 0 : Number(cd[0]));
    const run = { p: [], b: [] };
    for (const [who, i] of seq) {
      const cd = who === 'p' ? r.player[i] : r.banker[i];
      run[who].push(cd);
      (who === 'p' ? pHand : bHand).append(pcard(cd, { deal: true, dy: -40, dx: who === 'p' ? 80 : -80 }));
      sfx.card();
      (who === 'p' ? pScore : bScore).textContent = run[who].reduce((a, x) => a + val(x), 0) % 10;
      await sleep(i === 2 ? 650 : 420);
    }
    const win = r.result;
    pScore.className = 'score' + (win === 'player' ? ' bj' : ''); bScore.className = 'score' + (win === 'banker' ? ' bj' : '');
    const names = { player: 'Игрок', banker: 'Банкир', tie: 'Ничья' };
    const oc = outcome(r);
    ban.show(win === 'tie' ? 'Ничья ' + r.ps + ':' + r.bs : `${names[win]} ${Math.max(r.ps, r.bs)}:${Math.min(r.ps, r.bs)}`, r.payout > r.bet ? '+' + fmt(r.payout - r.bet) : r.payout === r.bet ? 'возврат' : '−' + fmt(r.bet), oc.kind, 2600);
    celebrate(r, felt);
  }
  return { destroy: bet.destroy };
}

// ───────────── Видео-покер ─────────────
export function poker(root, opts) {
  const pay = S.cfg.poker;
  const table = h('div', { class: 'card tight', style: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '3px 14px', fontSize: '12.5px' } });
  const payRows = {};
  for (const [k, name, m] of pay) {
    payRows[k] = h('div', { class: 'row', style: { gap: '6px', padding: '3px 6px', borderRadius: '8px', transition: 'background .2s' } }, h('span', { class: 'grow ellipsis muted' }, name), h('b', { class: 'num gold', style: { fontSize: '12px' } }, fx(m)));
    table.append(payRows[k]);
  }
  const row = h('div', { class: 'row', style: { justifyContent: 'center', gap: '6px', padding: '10px 0 30px' } });
  const stage = h('div', { class: 'felt stage', style: { padding: '24px 8px 10px', background: 'radial-gradient(120% 90% at 50% 20%,#1d4a47,#123634 50%,#0d2826)', borderColor: '#24504c' } },
    h('div', { class: 'felt-title', style: { marginBottom: '4px' } }, 'Нажми на карты, которые оставить'), row);
  root.style.setProperty('--cw', Math.min(70, Math.floor((innerWidth - 70) / 5)) + 'px');
  const ban = banner(stage);
  const bet = betPanel('poker');
  const go = h('button', { class: 'btn red big wide', onclick: () => busy(go, act) }, 'Раздать');
  root.append(table, stage, bet.el, go);
  let state = null, hold = [false, false, false, false, false];
  function mark(rank) { for (const [k, el] of Object.entries(payRows)) el.style.background = k === rank ? 'rgba(231,181,74,.18)' : ''; }
  function layout(cards, flipAll) {
    if (!row.children.length || flipAll) {
      clear(row);
      cards.forEach((c, i) => {
        const el = pcard(c, { down: true, deal: true, dy: -120, dx: 0, delay: i * 90 });
        el.append(h('span', { class: 'held-tag' }, 'ДЕРЖУ'));
        el.addEventListener('click', () => { if (!state) return; hold[i] = !hold[i]; el.classList.toggle('held', hold[i]); sfx.chip(); haptic('select'); });
        row.append(el);
        setTimeout(() => el.flipTo(c), 450 + i * 110);
      });
    }
  }
  async function act() {
    if (!state) {
      ban.hide(); hold = [false, false, false, false, false]; mark(null);
      const v = await api('play/poker', { action: 'deal', bet: bet.get() });
      state = v; layout(v.hand, true); bet.lock(true);
      go.textContent = 'Менять'; go.classList.replace('red', 'gold');
      setTimeout(() => { mark(v.rank); }, 1000);
      return;
    }
    const v = await api('play/poker', { action: 'draw', hold });
    let k = 0;
    v.hand.forEach((c, i) => {
      const el = row.children[i];
      if (!hold[i]) { el.classList.add('down'); setTimeout(() => el.flipTo(c), 380 + k++ * 140); }
      el.classList.remove('held');
    });
    state = null; bet.lock(false);
    go.textContent = 'Раздать'; go.classList.replace('gold', 'red');
    await sleep(500 + k * 140);
    mark(v.rank);
    if (v.rank) [...row.children].forEach((el) => el.classList.add('win'));
    const oc = outcome(v);
    const sub = !v.payout ? '−' + fmt(v.wager) : v.payout === v.wager ? 'Ставка вернулась · x1' : '+' + fmt(v.payout - v.wager) + ' · ' + fx(v.payout / v.wager);
    ban.show(v.rank_name || 'Без комбинации', sub, v.payout > v.wager ? 'win' : oc.kind, 2600);
    celebrate(v, stage);
    setTimeout(() => [...row.children].forEach((el) => el.classList.remove('win')), 2600);
  }
  if (opts.resume) {
    state = opts.resume; layout(state.hand, true); bet.lock(true); go.textContent = 'Менять'; go.classList.replace('red', 'gold'); mark(state.rank);
  }
  return { destroy: bet.destroy };
}
