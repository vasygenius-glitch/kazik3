// Иллюстрации: всё нарисовано вручную простыми SVG-формами, без стоковых иконок.
const S = (vb, body, extra = '') => `<svg viewBox="${vb}" xmlns="http://www.w3.org/2000/svg" ${extra}>${body}</svg>`;

// Сыроежка: гладкая красная шляпка, кремовая ножка.
export const russula = (x = 0, y = 0, k = 1, cap = '#e2493b') => `<g transform="translate(${x} ${y}) scale(${k})">
  <path d="M6 30c0-13 11-22 26-22s26 9 26 22c0 2-2 3-4 3H10c-2 0-4-1-4-3z" fill="${cap}"/>
  <path d="M13 25c3-7 10-11 19-11" stroke="#fff" stroke-opacity=".35" stroke-width="3" fill="none" stroke-linecap="round"/>
  <path d="M10 33h44c-3 2-8 3-22 3s-19-1-22-3z" fill="#000" opacity=".18"/>
  <path d="M24 34h16l2 17c0 3-4 5-10 5s-10-2-10-5z" fill="#f3eadb"/>
  <path d="M27 38h3l-1 14h-3z" fill="#fff" opacity=".55"/></g>`;
// Мухомор: тёмно-красный в белых пятнах и с юбочкой — сразу отличим.
export const amanita = (x = 0, y = 0, k = 1) => `<g transform="translate(${x} ${y}) scale(${k})">
  <path d="M4 31c0-15 12-25 28-25s28 10 28 25c0 2-2 3-4 3H8c-2 0-4-1-4-3z" fill="#c2261f"/>
  <circle cx="20" cy="18" r="3.6" fill="#fbf3e4"/><circle cx="34" cy="13" r="3" fill="#fbf3e4"/><circle cx="46" cy="21" r="3.8" fill="#fbf3e4"/>
  <circle cx="13" cy="27" r="2.4" fill="#fbf3e4"/><circle cx="29" cy="25" r="2.6" fill="#fbf3e4"/><circle cx="52" cy="29" r="2" fill="#fbf3e4"/>
  <path d="M23 34h18l1 18c0 3-4 5-10 5s-10-2-10-5z" fill="#f3eadb"/>
  <path d="M20 40c4 3 20 3 24 0l-1 5c-4 2-18 2-22 0z" fill="#e2d4bc"/></g>`;
export const CUR = S('0 0 64 64', russula(0, 2), 'class="cur"');
export const LOGO = S('0 0 64 64', russula(0, 3) + '<circle cx="47" cy="12" r="5" fill="#e7b54a"/>', 'class="brand-mark"');
export const SPORE = S('0 0 64 64', russula(0, 0, 1, '#e7b54a'));

export const icons = {
  hall: S('0 0 24 24', '<path d="M3 11.5 12 4l9 7.5" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="M5.5 10v9.5h13V10" stroke="currentColor" stroke-width="2" fill="none" stroke-linejoin="round"/><path d="M9 14.5c0-1.8 1.4-3 3-3s3 1.2 3 3h-6z" fill="currentColor"/><path d="M11.2 14.5h1.6v3.2h-1.6z" fill="currentColor"/>'),
  games: S('0 0 24 24', '<rect x="3.5" y="5" width="10" height="14" rx="2.2" stroke="currentColor" stroke-width="2" fill="none" transform="rotate(-8 8.5 12)"/><rect x="10.5" y="5" width="10" height="14" rx="2.2" stroke="currentColor" stroke-width="2" fill="var(--bg)" transform="rotate(8 15.5 12)"/><path d="M15.6 9.8c1.6 1.2 2.4 2.1 2.4 3.1 0 .9-.7 1.5-1.5 1.5-.4 0-.7-.1-.9-.4.1.8.3 1.3.7 1.8h-1.9c.4-.5.6-1 .7-1.8-.2.3-.5.4-.9.4-.8 0-1.5-.6-1.5-1.5 0-1 .8-1.9 2.4-3.1z" fill="currentColor"/>'),
  top: S('0 0 24 24', '<path d="M8.5 20v-8h7v8M3 20v-5h5.5M15.5 20v-6.5H21V20M2 20h20" stroke="currentColor" stroke-width="2" fill="none" stroke-linejoin="round" stroke-linecap="round"/><path d="m12 3.2 1.1 2.3 2.5.3-1.8 1.7.5 2.5-2.3-1.2-2.3 1.2.5-2.5-1.8-1.7 2.5-.3z" fill="currentColor"/>'),
  me: S('0 0 24 24', '<circle cx="12" cy="8.5" r="4" stroke="currentColor" stroke-width="2" fill="none"/><path d="M4.5 20.5c.8-4 3.8-6 7.5-6s6.7 2 7.5 6" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/>'),
  back: S('0 0 24 24', '<path d="M15 5l-7 7 7 7" stroke="currentColor" stroke-width="2.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'),
  info: S('0 0 24 24', '<circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2" fill="none"/><path d="M12 11v6M12 7.5v.5" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>'),
  sound: S('0 0 24 24', '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" fill="currentColor"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18 6a8.5 8.5 0 0 1 0 12" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/>'),
  crown: S('0 0 26 18', '<path d="M2 16 1 4l6.5 5L13 1l5.5 8L25 4l-1 12z" fill="#e7b54a" stroke="#7a5414" stroke-width="1.2" stroke-linejoin="round"/>'),
};

// ── символы слотов ──
export const sym = {
  berry: S('0 0 64 64', '<path d="M30 12c-6-6-15-5-19 0 6 3 12 3 19 0zM33 12c5-7 14-7 19-2-6 4-13 4-19 2z" fill="#5e8a40"/><path d="M32 12v10" stroke="#3f6a2a" stroke-width="3" stroke-linecap="round"/><circle cx="22" cy="34" r="11" fill="#c8302a"/><circle cx="42" cy="34" r="11" fill="#d93b30"/><circle cx="32" cy="47" r="11" fill="#b8271f"/><circle cx="18" cy="30" r="3" fill="#fff" opacity=".55"/><circle cx="38" cy="30" r="3" fill="#fff" opacity=".55"/><circle cx="28" cy="43" r="3" fill="#fff" opacity=".5"/>'),
  acorn: S('0 0 64 64', '<path d="M17 30c0 15 7 26 15 26s15-11 15-26z" fill="#c98a45"/><path d="M22 34c1 9 4 15 8 18" stroke="#fff" stroke-opacity=".3" stroke-width="3" fill="none" stroke-linecap="round"/><path d="M12 30c0-10 9-16 20-16s20 6 20 16c0 2-2 3-4 3H16c-2 0-4-1-4-3z" fill="#6b4224"/><path d="M18 22l6 9M26 18l6 13M36 18l-4 13M44 22l-6 9" stroke="#4d2e17" stroke-width="2"/><path d="M32 14c0-4 2-7 6-8" stroke="#4d2e17" stroke-width="3.5" fill="none" stroke-linecap="round"/>'),
  bell: S('0 0 64 64', '<path d="M32 8c-10 0-16 8-16 18v10l-5 9h42l-5-9V26c0-10-6-18-16-18z" fill="#e7b54a"/><path d="M22 24c1-6 5-10 10-11" stroke="#fff" stroke-opacity=".5" stroke-width="3.5" fill="none" stroke-linecap="round"/><path d="M11 45h42v4H11z" fill="#b0832a"/><circle cx="32" cy="53" r="5" fill="#b0832a"/><circle cx="32" cy="7" r="3" fill="#b0832a"/>'),
  gem: S('0 0 64 64', '<path d="M18 12h28l11 14-25 30L7 26z" fill="#4fb3b8"/><path d="M7 26h50L32 56z" fill="#2f8e96"/><path d="M18 12l6 14h16l6-14M24 26l8 30 8-30" stroke="#d8f4f2" stroke-width="2" fill="none" stroke-linejoin="round" opacity=".8"/><path d="M20 16l-6 8" stroke="#fff" stroke-width="3" stroke-linecap="round" opacity=".7"/>'),
  seven: S('0 0 64 64', '<path d="M12 10h40v9L32 56H19l19-35H22v6H12z" fill="#e2493b" stroke="#7b2216" stroke-width="3" stroke-linejoin="round"/><path d="M16 14h30" stroke="#ffb9a6" stroke-width="3" stroke-linecap="round" opacity=".7"/>'),
  shroom: S('0 0 64 64', russula(0, 2) + '<path d="M50 6l2 4 4 1-4 2-2 4-2-4-4-2 4-1z" fill="#e7b54a"/>'),
};
export const SYMS = Object.keys(sym);

// ── обложки игр ──
const card = (x, y, r, rank, suit, red) => `<g transform="translate(${x} ${y}) rotate(${r})"><rect x="-17" y="-24" width="34" height="48" rx="5" fill="#f6efe2" stroke="#d9ccb6"/><text x="-11" y="-9" font-family="Unbounded,sans-serif" font-weight="800" font-size="12" fill="${red ? '#c8372b' : '#1d1a17'}">${rank}</text><text x="0" y="12" text-anchor="middle" font-size="20" fill="${red ? '#c8372b' : '#1d1a17'}">${suit}</text></g>`;
const die = (x, y, r, pips, k = 1) => `<g transform="translate(${x} ${y}) rotate(${r}) scale(${k})"><rect x="-15" y="-15" width="30" height="30" rx="7" fill="#f6efe2" stroke="#d6c6aa"/>${pips.map(([a, b]) => `<circle cx="${a}" cy="${b}" r="3.2" fill="#2a1d17"/>`).join('')}</g>`;
const cup = (x, y, k = 1) => `<g transform="translate(${x} ${y}) scale(${k})"><path d="M-16 20 -11 -18h22l5 38z" fill="#a8632f"/><path d="M-19 20h38v6h-38z" fill="#7a431d"/><path d="M-12 -18h24v5h-24z" fill="#c98a45"/><path d="M-7 -10l-3 26" stroke="#fff" stroke-opacity=".25" stroke-width="3" stroke-linecap="round"/></g>`;
export const tileArt = {
  bj: S('0 0 120 92', card(48, 48, -12, 'A', '♠', false) + card(72, 46, 10, 'K', '♥', true) + '<circle cx="98" cy="74" r="10" fill="#e2493b" stroke="#f6efe2" stroke-width="3" stroke-dasharray="4 3"/>'),
  slots: S('0 0 120 92', '<rect x="14" y="14" width="92" height="64" rx="12" fill="#2a0f0c" stroke="#e7b54a" stroke-width="3"/><rect x="20" y="22" width="25" height="48" rx="6" fill="#f6efe2"/><rect x="48" y="22" width="25" height="48" rx="6" fill="#f6efe2"/><rect x="76" y="22" width="25" height="48" rx="6" fill="#f6efe2"/>' + russula(21, 33, .36) + russula(49, 33, .36) + russula(77, 33, .36) + '<path d="M16 46h88" stroke="#e7b54a" stroke-width="2" stroke-dasharray="3 3"/>'),
  roulette: S('0 0 120 92', '<circle cx="60" cy="46" r="38" fill="#2a2420" stroke="#c9922b" stroke-width="3"/>' + Array.from({ length: 12 }, (_, i) => { const a1 = (i / 12) * Math.PI * 2, a2 = ((i + 1) / 12) * Math.PI * 2; const p = (a, r) => `${60 + Math.cos(a) * r} ${46 + Math.sin(a) * r}`; return `<path d="M${p(a1, 34)} A34 34 0 0 1 ${p(a2, 34)} L${p(a2, 18)} A18 18 0 0 0 ${p(a1, 18)}z" fill="${i === 0 ? '#2f6b4b' : i % 2 ? '#a8321f' : '#1d1a17'}"/>`; }).join('') + '<circle cx="60" cy="46" r="15" fill="#c9922b"/><circle cx="60" cy="46" r="5" fill="#6b4d14"/><circle cx="84" cy="25" r="4.5" fill="#fff"/>'),
  crash: S('0 0 120 92', '<path d="M10 82h100M10 82V10" stroke="#2c4250" stroke-width="2"/><path d="M12 80C50 78 74 62 96 22" stroke="#e7b54a" stroke-width="4" fill="none" stroke-linecap="round"/><path d="M12 80C50 78 74 62 96 22V82H12z" fill="#e7b54a" opacity=".12"/>' + russula(84, 4, .45, '#e7b54a') + '<path d="M90 34l-6 8M98 34l-2 9" stroke="#e2493b" stroke-width="3" stroke-linecap="round"/>'),
  dice: S('0 0 120 92', die(44, 50, -14, [[-7, -7], [7, 7], [0, 0]], 1.25) + die(78, 42, 12, [[-7, -7], [7, -7], [-7, 7], [7, 7], [0, 0]], 1.25)),
  cups: S('0 0 120 92', cup(30, 50, .9) + cup(90, 50, .9) + `<g transform="translate(60 26) rotate(-12)">${cup(0, 0, .9)}</g>` + russula(48, 52, .38)),
  mines: S('0 0 120 92', Array.from({ length: 9 }, (_, i) => `<rect x="${24 + (i % 3) * 25}" y="${8 + Math.floor(i / 3) * 25}" width="22" height="22" rx="5" fill="${i === 4 ? '#efe3cc' : i === 2 ? '#5a1c15' : '#4d6236'}"/>`).join('') + russula(51, 36, .3) + amanita(76, 11, .3)),
  baccarat: S('0 0 120 92', card(42, 46, -8, '9', '♦', true) + card(78, 46, 8, '8', '♣', false) + '<rect x="44" y="76" width="32" height="10" rx="5" fill="#e7b54a"/>'),
  poker: S('0 0 120 92', [-24, -12, 0, 12, 24].map((r, i) => card(60 + r * 1.3, 52 + Math.abs(r) * .3, r, ['10', 'J', 'Q', 'K', 'A'][i], '♥', true)).join('')),
  rps: S('0 0 120 92', '<text x="34" y="62" font-size="40" text-anchor="middle">✊</text><text x="86" y="62" font-size="40" text-anchor="middle">✌️</text><text x="60" y="30" font-family="Unbounded" font-weight="800" font-size="12" fill="#f3eadb" text-anchor="middle" opacity=".8">VS</text>'),
  jackpot: S('0 0 120 92', '<circle cx="60" cy="46" r="34" fill="none" stroke="#e2493b" stroke-width="14" stroke-dasharray="70 220"/><circle cx="60" cy="46" r="34" fill="none" stroke="#e7b54a" stroke-width="14" stroke-dasharray="60 220" stroke-dashoffset="-70"/><circle cx="60" cy="46" r="34" fill="none" stroke="#8fbf6a" stroke-width="14" stroke-dasharray="84 220" stroke-dashoffset="-130"/><path d="M60 2l6 12h-12z" fill="#f3eadb"/>' + russula(46, 32, .45)),
  duel: S('0 0 120 92', '<circle cx="60" cy="46" r="32" fill="#e7b54a" stroke="#a9771f" stroke-width="4"/><circle cx="60" cy="46" r="24" fill="none" stroke="#a9771f" stroke-width="2" stroke-dasharray="3 3"/>' + russula(43, 28, .54)),
  wheel: S('0 0 120 92', '<circle cx="60" cy="48" r="38" fill="#e7b54a"/>' + Array.from({ length: 8 }, (_, i) => `<path d="M60 48 L${60 + Math.cos(i * Math.PI / 4) * 34} ${48 + Math.sin(i * Math.PI / 4) * 34} A34 34 0 0 1 ${60 + Math.cos((i + 1) * Math.PI / 4) * 34} ${48 + Math.sin((i + 1) * Math.PI / 4) * 34}z" fill="${['#e2493b', '#f6efe2', '#8fbf6a', '#f6efe2'][i % 4]}"/>`).join('') + '<circle cx="60" cy="48" r="8" fill="#6b4d14"/><path d="M60 4l7 12h-14z" fill="#f3eadb"/>'),
};

// ── иконки дохода ──
export const ecoArt = {
  bonus: S('0 0 40 40', '<path d="M8 6h24v28l-4-3-4 3-4-3-4 3-4-3-4 3z" fill="#f4ecdc"/><path d="M12 13h16M12 18h12M12 23h14" stroke="#a39887" stroke-width="2" stroke-linecap="round"/><circle cx="29" cy="28" r="7" fill="#e7b54a"/><path d="M29 24.5v7M26.5 28h5" stroke="#6b4d14" stroke-width="2" stroke-linecap="round"/>'),
  wheel: S('0 0 40 40', '<circle cx="20" cy="21" r="15" fill="#e7b54a"/>' + Array.from({ length: 6 }, (_, i) => `<path d="M20 21 L${20 + Math.cos(i * Math.PI / 3) * 13} ${21 + Math.sin(i * Math.PI / 3) * 13} A13 13 0 0 1 ${20 + Math.cos((i + 1) * Math.PI / 3) * 13} ${21 + Math.sin((i + 1) * Math.PI / 3) * 13}z" fill="${i % 2 ? '#f6efe2' : '#e2493b'}"/>`).join('') + '<circle cx="20" cy="21" r="3.5" fill="#6b4d14"/><path d="M20 2l4 6h-8z" fill="#f3eadb"/>'),
  work: S('0 0 40 40', '<path d="M6 17h28l-3 17H9z" fill="#c98a45"/><path d="M6 17h28" stroke="#7a431d" stroke-width="3" stroke-linecap="round"/><path d="M13 17c0-6 3-10 7-10s7 4 7 10" stroke="#7a431d" stroke-width="2.5" fill="none"/><path d="M12 23l2 7M20 23v7M28 23l-2 7" stroke="#7a431d" stroke-width="2" stroke-linecap="round"/>' + russula(14, 6, .2)),
  crime: S('0 0 40 40', '<path d="M5 16c4-3 9-4 15-4s11 1 15 4c-1 7-5 11-9 11-3 0-4-3-6-3s-3 3-6 3c-4 0-8-4-9-11z" fill="#2a2420" stroke="#a39887" stroke-width="2"/><ellipse cx="13" cy="19" rx="3.5" ry="2.5" fill="#f3eadb"/><ellipse cx="27" cy="19" rx="3.5" ry="2.5" fill="#f3eadb"/>'),
  rake: S('0 0 40 40', '<ellipse cx="20" cy="29" rx="13" ry="5" fill="#b0832a"/><ellipse cx="20" cy="26" rx="13" ry="5" fill="#e7b54a"/><ellipse cx="20" cy="20" rx="13" ry="5" fill="#b0832a"/><ellipse cx="20" cy="17" rx="13" ry="5" fill="#e7b54a"/><path d="M30 7a9 9 0 0 1 2 8" stroke="#8fbf6a" stroke-width="2.5" fill="none" stroke-linecap="round"/><path d="M33 16l-1-4-3 3z" fill="#8fbf6a"/>'),
};

// Грибной оракул — ИИ в «Камень-ножницы-бумага».
export const ORACLE = S('0 0 64 64', russula(0, 0, 1, '#8b5cc7').replace('#8b5cc7', '#7d4fb3') + '<circle cx="25" cy="42" r="3" fill="#1d1a17"/><circle cx="39" cy="42" r="3" fill="#1d1a17"/><circle cx="26" cy="41" r="1" fill="#fff"/><circle cx="40" cy="41" r="1" fill="#fff"/><path d="M28 49c2 1.5 6 1.5 8 0" stroke="#1d1a17" stroke-width="2" fill="none" stroke-linecap="round"/>');

export const CARD_BACK = S('0 0 60 84', '<defs><pattern id="cb" width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><path d="M0 5h10" stroke="#c8473a" stroke-width="3"/></pattern></defs><rect width="60" height="84" fill="url(#cb)"/><circle cx="30" cy="42" r="15" fill="#a8321f" stroke="#f6efe2" stroke-width="2"/>' + russula(19, 30, .34, '#f6efe2'), 'preserveAspectRatio="xMidYMid slice"');

export const COIN_HEADS = S('0 0 64 64', russula(0, 4));
export const COIN_TAILS = S('0 0 64 64', amanita(0, 4));

export const ACH_ICON = { first: '🎟', bj: '🃏', crash10: '🚀', crash100: '🪐', mines10: '🍄', royal: '👑', zero: '0️⃣', slots: '🎰',
  pot: '🍯', duel10: '⚔️', million: '💰', streak7: '🔥', lvl10: '🎖', tasks: '🧺' };
export const achBadge = (got) => S('0 0 40 40', `<path d="M20 2l15 8.5v19L20 38 5 29.5v-19z" fill="${got ? '#3a2c10' : '#25201b'}" stroke="${got ? '#e7b54a' : '#41382f'}" stroke-width="2"/>`);
