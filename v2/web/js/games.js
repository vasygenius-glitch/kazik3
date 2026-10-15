// Каталог игр и правила.
import { h, S, fmt, fx, sheet } from './core.js';
import { tileArt, sym } from './art.js';

export const GAMES = {
  crash: { name: 'Краш', sub: 'Общий стол · забери до взрыва', bg: '#16222b', glow: '#1b3140', mod: './g_tables.js', fn: 'crash', shared: true, rules: true, wide: true },
  bj: { name: 'Блэкджек', sub: 'Блэкджек 3:2 · дилер стоит на 17', bg: '#1e3b2f', mod: './g_cards.js', fn: 'blackjack', rules: true },
  slots: { name: 'Слоты', sub: 'Три сыроежки — x160', bg: '#5a1f1b', mod: './g_quick.js', fn: 'slots', rules: true },
  roulette: { name: 'Рулетка', sub: 'Общий стол · европейская', bg: '#1f3a2c', mod: './g_tables.js', fn: 'roulette', shared: true, rules: true },
  mines: { name: 'Тихая охота', sub: 'Сыроежки или мухоморы', bg: '#2d3b1f', mod: './g_mines.js', fn: 'mines', rules: true },
  dice: { name: 'Кости', sub: 'Больше, меньше, семь, дубль', bg: '#3d3326', mod: './g_quick.js', fn: 'dice', rules: true },
  cups: { name: 'Напёрстки', sub: 'Где сыроежка? до x4,8', bg: '#4a2f1f', mod: './g_quick.js', fn: 'cups', rules: true },
  jackpot: { name: 'Складчина', sub: 'Общий банк · шанс = доля', bg: '#4a3510', mod: './g_tables.js', fn: 'jackpot', shared: true, rules: true },
  baccarat: { name: 'Баккара', sub: 'Игрок, Банкир или Ничья', bg: '#1b2638', mod: './g_cards.js', fn: 'baccarat', rules: true },
  poker: { name: 'Видео-покер', sub: 'Jacks or Better · до x250', bg: '#123634', mod: './g_cards.js', fn: 'poker', rules: true },
  rps: { name: 'КНБ против ИИ', sub: 'Оракул учится на тебе', bg: '#6b4a1a', mod: './g_quick.js', fn: 'rps', rules: true },
  duel: { name: 'Дуэли', sub: 'Один на один · монетка', bg: '#2a2c33', mod: './g_tables.js', fn: 'duels', shared: true, rules: true },
};

export function mountGames(page, { openGame }) {
  const grid = h('div', { class: 'tiles' });
  const counts = {};
  for (const [id, g] of Object.entries(GAMES)) {
    const flag = g.shared ? h('span', { class: 'flag' }, h('i', { class: 'live-dot' }), 'общий стол') : null;
    counts[id] = flag;
    grid.append(h('button', { class: 'tile' + (g.wide ? ' wide' : ''), style: { background: g.bg }, onclick: () => openGame(id) },
      h('div', { class: 'art', html: tileArt[id] }), flag, h('div', { class: 'tn' }, g.name), h('div', { class: 'ts' }, g.sub)));
  }
  page.append(h('div', { class: 'label' }, 'Игры', h('span', { class: 'more' }, 'честные шансы · казино берёт ~3%')), grid,
    h('div', { class: 'card', style: { marginTop: '14px' } }, h('div', { class: 'row' }, h('div', { style: { fontSize: '26px' } }, '🧾'),
      h('div', { class: 'grow muted', style: { fontSize: '13px' } }, 'Каждая ставка даёт опыт, кешбэк, продвигает задания дня и лигу недели. Исход считается только на сервере.'))));
  return {};
}

const P = (t) => h('p', null, t);
export function rules(id) {
  const c = S.cfg;
  sheet((box) => {
    box.append(h('h3', null, GAMES[id].name));
    if (id === 'slots') {
      box.append(P('Выигрыш считается по центральной линии.'));
      const t = h('div', { class: 'paytable' });
      for (const [k, m] of Object.entries(c.slots.three)) t.append(h('div', null, h('span', { html: sym[k] }), h('span', { html: sym[k] }), h('span', { html: sym[k] }), h('b', null, fx(m))));
      for (const [k, m] of Object.entries(c.slots.pair)) t.append(h('div', null, h('span', { html: sym[k] }), h('span', { html: sym[k] }), h('span', null, '·'), h('b', null, fx(m))));
      t.append(h('div', null, h('span', { html: sym.shroom }), h('span', { html: sym.shroom }), h('span', null, 'где угодно'), h('b', null, fx(c.slots.two_shrooms))));
      t.append(h('div', null, h('span', { html: sym.shroom }), h('span', null, 'одна на линии'), h('b', null, fx(c.slots.one_shroom))));
      box.append(t);
    } else if (id === 'bj') {
      box.append(P('Набери больше дилера, но не больше 21. Блэкджек с раздачи платит 3:2. Дилер добирает до 17 и стоит на всех 17.'),
        P('Удвоение — на любых двух картах. Сплит — пара одного ранга, один раз. Ничья возвращает ставку.'));
    } else if (id === 'crash') {
      box.append(P('Множитель растёт, пока спора не улетит. Нажми «Забрать» раньше — получишь ставку × множитель. Можно задать автовывод.'),
        P('Все игроки чата видят один и тот же раунд. Точка взрыва определяется сервером до взлёта: шанс дожить до x2 — 48,5%, до x10 — 9,7%.'));
    } else if (id === 'roulette') {
      box.append(P('Европейская рулетка с одним зеро. Ставки принимаются 18 секунд, затем шарик крутится для всего чата.'),
        P('Число — x36, дюжина и колонка — x3, цвет, чёт/нечет, 1–18/19–36 — x2. При зеро внешние ставки проигрывают.'));
    } else if (id === 'mines') {
      box.append(P('Поле 5×5. Выбери, сколько спрятать мухоморов. Каждая найденная сыроежка увеличивает множитель — забери выигрыш в любой момент.'),
        P('Нашёл мухомор — ставка сгорает. Чем больше мухоморов, тем быстрее растёт множитель.'));
    } else if (id === 'dice') {
      box.append(P('Бросаются два кубика. Выбери исход:'), h('div', { class: 'col' },
        Object.values(c.dice).map((d) => h('div', { class: 'kv' }, h('span', { class: 'k' }, d.label), h('span', { class: 'v num' }, fx(d.mult))))));
    } else if (id === 'cups') {
      box.append(P('Сыроежка прячется под одним из напёрстков. Угадай — получи множитель: 3 напёрстка ' + fx(c.cups[3]) + ', 4 — ' + fx(c.cups[4]) + ', 5 — ' + fx(c.cups[5]) + '.'));
    } else if (id === 'jackpot') {
      box.append(P('Игроки скидываются в общий банк. Шанс забрать всё — равен твоей доле. Розыгрыш стартует через 30 секунд после второго участника.'),
        P('3% банка уходит в призовой фонд лиги недели.'));
    } else if (id === 'baccarat') {
      box.append(P(`Ставь на руку Игрока (${fx(c.baccarat.player)}), Банкира (${fx(c.baccarat.banker)}) или Ничью (${fx(c.baccarat.tie)}). Карты добираются по классическим правилам. При ничьей ставки на Игрока и Банкира возвращаются.`));
    } else if (id === 'poker') {
      box.append(P('Получи 5 карт, оставь нужные и замени остальные один раз.'), h('div', { class: 'col' },
        c.poker.map(([, name, m]) => h('div', { class: 'kv' }, h('span', { class: 'k' }, name), h('span', { class: 'v num' }, fx(m))))));
    } else if (id === 'rps') {
      box.append(P('Грибной оракул запоминает твои ходы и пытается угадать следующий. Победа — ' + fx(c.rps) + ', ничья возвращает ставку.'),
        P('Чем предсказуемее ты играешь, тем чаще он побеждает. Будь хаотичным!'));
    } else if (id === 'duel') {
      box.append(P('Брось вызов на сумму — любой игрок чата может принять. Монетка решит: победитель забирает обе ставки минус 3% в фонд лиги.'),
        P('Можно вызвать конкретного игрока из тех, кто сейчас онлайн.'));
    }
    box.append(h('div', { class: 'dim', style: { fontSize: '12px', marginTop: '10px' } }, `Ставки: от ${fmt(c.min_bet)} до ${fmt(c.max_bet)}.`));
  });
}
