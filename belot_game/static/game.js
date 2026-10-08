// Клиент за масата: пита сървъра за състоянието и рисува лобито или играта.
const CODE = window.ROOM_CODE;
const BASE = window.BASE || '';   // префикс, когато белотът е вграден в друг сайт (напр. "/belot")
const TOKEN_KEY = 'belot_token_' + CODE;
const SUIT_SYM = {C: '♣', D: '♦', H: '♥', S: '♠'};
const CONTRACTS = ['C', 'D', 'H', 'S', 'NT', 'AT'];
const CONTRACT_NAME = {C: 'Спатия', D: 'Каро', H: 'Купа', S: 'Пика', NT: 'Без коз', AT: 'Всичко коз'};
const BID_TEXT = {pass: 'Пас', double: 'Контра', redouble: 'Реконтра'};

const app = document.getElementById('app');
let st = null, lastVersion = -1, mode = null, busy = false, inviteUrl = '';
// На тъч екран първото докосване вдига картата, второто я играе – против случайни ходове.
const TOUCH = matchMedia('(hover: none)').matches;
let selected = null, menuOpen = false, sideOpen = false;
let seenTrick = null;   // картите във взятката при предишното рисуване (null = още не е рисувано)

function store(key, val) {
  try { if (val === undefined) return localStorage.getItem(key); localStorage.setItem(key, val); } catch (e) { return null; }
}
let token = store(TOKEN_KEY) || '';

const esc = s => String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const rank = c => c.slice(0, -1);
const suit = c => c.slice(-1);
const meSeat = () => (st && st.me !== null ? st.me : 0);
const rel = seat => (seat - meSeat() + 4) % 4;      // 0 долу, 1 дясно, 2 горе, 3 ляво
const seatName = i => (st.seats[i] ? st.seats[i].name : 'Място ' + (i + 1));
const teamLabel = t => st.me === null ? 'Отбор ' + (t + 1) : (t === st.me % 2 ? 'Ние' : 'Те');
const teamCls = t => st.me === null ? (t ? 'them' : 'us') : (t === st.me % 2 ? 'us' : 'them');
const fmtLog = s => esc(s).replace(/\{p(\d)\}/g, (_, i) => '<b>' + esc(seatName(+i)) + '</b>');

function contractLabel(c, withName = true) {
  if (!c) return '';
  if (SUIT_SYM[c]) return `<span class="sym s-${c}">${SUIT_SYM[c]}</span>` + (withName ? ' ' + CONTRACT_NAME[c] : '');
  return CONTRACT_NAME[c];
}

function cardHtml(c, extra = '', style = '') {
  const r = rank(c), s = suit(c);
  const face = 'JQKA'.includes(r);
  const corner = cls => `<div class="corner ${cls}">${r}<small>${SUIT_SYM[s]}</small></div>`;
  return `<div class="card s-${s} ${extra}" data-card="${c}" ${style ? `style="${style}"` : ''}>
    ${corner('')}${corner('br')}
    <div class="center ${face ? 'face' : ''}">${face ? `<span>${r}</span><span>${SUIT_SYM[s]}</span>` : SUIT_SYM[s]}</div></div>`;
}


function toast(msg) {
  const t = document.createElement('div');
  t.className = 'toast'; t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2800);
}

async function act(type, payload = {}) {
  if (busy) return;
  busy = true;
  try {
    const r = await fetch(`${BASE}/api/rooms/${CODE}/action`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({type, token, ...payload}),
    });
    const d = await r.json();
    if (d.error) { toast(d.error); return; }
    if (d.token && d.token !== token) { token = d.token; store(TOKEN_KEY, token); }
    apply(d);
  } catch (e) { toast('Няма връзка със сървъра.'); }
  finally { busy = false; }
}

async function poll() {
  try {
    const r = await fetch(`${BASE}/api/rooms/${CODE}/state?token=${encodeURIComponent(token)}`);
    if (r.status === 404) { app.innerHTML = '<div class="lobby"><h1>Няма такава маса.</h1><a href="' + BASE + '/" style="color:var(--gold)">Към началото</a></div>'; return; }
    apply(await r.json());
  } catch (e) { /* временно без връзка – опитваме пак */ }
  setTimeout(poll, st && st.game ? 500 : 1000);   // по-рядко = по-леко за 1 процес в PythonAnywhere
}

function apply(d) {
  st = d;
  // Прерисуваме и когато табелата с играта изчезне – тогава версията не се сменя
  const key = d.version + (d.game && d.game.announce ? '+a' : '') + (d.game && d.game.claim_show ? '+c' : '');
  if (key === lastVersion && mode) return;
  lastVersion = key;
  render();
}

function render() {
  if (!st.game) renderLobby(); else renderGame();
}

// ---------- лоби ----------
async function computeInvite() {
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
  inviteUrl = location.origin + BASE + '/r/' + CODE;
  let note = 'Прати този линк на другите играчи.';
  if (local) {
    try {
      const info = await (await fetch(BASE + '/api/info')).json();
      if (info.lan_ip) inviteUrl = `http://${info.lan_ip}${location.port ? ":" + location.port : ""}${BASE}/r/${CODE}`;
    } catch (e) {}
    note = 'Този линк работи за хора в същата мрежа (Wi-Fi). За игра през интернет пусни <code>python run.py --tunnel</code>.';
  }
  const inp = document.getElementById('invite');
  if (inp) { inp.value = inviteUrl; document.getElementById('invite-note').innerHTML = note; }
}

function renderLobby() {
  if (mode !== 'lobby') {
    mode = 'lobby';
    app.innerHTML = `<div class="lobby">
      <div><a href="${BASE}/" class="muted" style="text-decoration:none">← Белот</a>
      <h1>Маса <span class="code-badge">${CODE}</span></h1></div>
      <div id="notice"></div>
      <section class="box">
        <h2>Покани приятели</h2>
        <div class="invite"><input id="invite" readonly><button id="copy">Копирай</button></div>
        <div class="muted" id="invite-note" style="font-size:13px"></div>
      </section>
      <section class="box">
        <h2>Твоето име</h2>
        <input id="name" maxlength="20" placeholder="Име" value="${esc(store('belot_name') || '')}">
      </section>
      <div class="seat-grid" id="seats"></div>
      <div id="start-row"></div>
    </div>`;
    document.getElementById('copy').onclick = () => {
      const inp = document.getElementById('invite');
      inp.select();
      (navigator.clipboard ? navigator.clipboard.writeText(inp.value) : Promise.reject()).then(
        () => toast('Линкът е копиран.'), () => document.execCommand('copy'));
    };
    document.getElementById('name').addEventListener('input', e => store('belot_name', e.target.value));
    computeInvite();
  }
  document.getElementById('notice').innerHTML = st.notice ? `<div class="notice">${fmtLog(st.notice)}</div>` : '';
  // Отборите: места 0 и 2 срещу 1 и 3. Подреждаме ги по двойки.
  const order = [0, 2, 1, 3];
  document.getElementById('seats').innerHTML = order.map(i => {
    const s = st.seats[i];
    const mine = st.me === i;
    let body, actions = '';
    if (!s) {
      body = '<div class="who muted">Свободно място</div>';
      actions = `<button data-sit="${i}" class="primary">Седни тук</button>`;
      if (st.is_host) actions += `<button data-bot="${i}" class="ghost">+ Бот</button>`;
    } else {
      body = `<div class="who">${esc(s.name)}${mine ? ' (ти)' : ''}${s.host ? ' <span class="muted">· домакин</span>' : ''}</div>
              <div class="muted" style="font-size:13px">${s.bot ? 'Бот' : (s.online ? 'На линия' : 'Няма връзка')}</div>`;
      if (mine) actions = '<button data-leave="1" class="ghost">Стани</button>';
      if (s.bot && st.is_host) actions = `<button data-unbot="${i}" class="ghost">Махни бота</button>`;
    }
    return `<div class="seat-box team${i % 2} ${mine ? 'mine' : ''}">
      <div class="muted" style="font-size:12px">Отбор ${i % 2 + 1} · място ${i + 1}</div>${body}
      <div class="actions">${actions}</div></div>`;
  }).join('');
  const full = st.seats.every(Boolean);
  document.getElementById('start-row').innerHTML = st.is_host
    ? `<button class="primary" id="start" ${full ? '' : 'disabled'} style="width:100%;padding:12px">Започни играта</button>
       ${full ? '' : '<p class="muted" style="text-align:center">Нужни са 4 играчи. Празните места може да се попълнят с ботове.</p>'}`
    : `<p class="muted" style="text-align:center">${st.me === null ? 'Избери си място.' : 'Изчакай домакина да започне играта.'}</p>`;

  document.querySelectorAll('[data-sit]').forEach(b => b.onclick = () => {
    const name = document.getElementById('name').value.trim();
    if (!name) { toast('Първо въведи име.'); document.getElementById('name').focus(); return; }
    act('sit', {seat: +b.dataset.sit, name});
  });
  document.querySelectorAll('[data-bot]').forEach(b => b.onclick = () => act('add_bot', {seat: +b.dataset.bot}));
  document.querySelectorAll('[data-unbot]').forEach(b => b.onclick = () => act('remove_bot', {seat: +b.dataset.unbot}));
  document.querySelectorAll('[data-leave]').forEach(b => b.onclick = () => act('leave'));
  const start = document.getElementById('start');
  if (start) start.onclick = () => act('start');
}

// ---------- игра ----------
function seatBubble(g, seat) {
  if (g.phase === 'bidding') {
    const mine = g.bids.filter(b => b[0] === seat);
    if (!mine.length) return '';
    const a = mine[mine.length - 1][1];
    return `<div class="bubble bid">${BID_TEXT[a] || contractLabel(a)}</div>`;
  }
  if (g.phase !== 'playing') return '';
  // Анонсите се виждат през първите две ръце; белотът – и по-късно, докато се вижда изиграната карта
  let items = g.tricks_won[0] + g.tricks_won[1] <= 1 ? [...g.announced[seat]] : [];
  if (belotVisible(g, seat) && !items.includes('Белот')) items.push('Белот');
  if (!items.length) return '';
  return `<div class="decls">${items.map(a => `<div class="bubble decl">${esc(a)}</div>`).join('')}</div>`;
}

function belotVisible(g, seat) {
  const cards = g.trick.length ? g.trick : (g.last_trick ? g.last_trick.cards : []);
  return (g.belots || []).some(([s, su]) =>
    s === seat && cards.some(([ps, c]) => ps === seat && suit(c) === su && 'KQ'.includes(rank(c))));
}

function statusText(g) {
  if (g.claim_show) return `${esc(seatName(g.claim_show.seat))} свали картите!`;
  if (g.phase === 'bidding') {
    return g.turn === st.me ? 'Твой ред е да обявиш.' : `Обявява ${esc(seatName(g.turn))}…`;
  }
  if (g.phase === 'playing') {
    if (g.announce) return 'Започва играта…';
    if (g.trick.length === 4) return `Взятката е за ${esc(seatName(g.trick_win))}.`;
    if (g.turn !== st.me) return `Играе ${esc(seatName(g.turn))}…`;
    if (!TOUCH) return 'Твой ред е – избери карта.';
    return selected ? 'Докосни я пак, за да я изиграеш.' : 'Твой ред е – докосни карта.';
  }
  return '';
}

function renderGame() {
  mode = 'game';
  const g = st.game;
  const myTeam = st.me === null ? 0 : st.me % 2;
  const other = 1 - myTeam;

  const seatsHtml = [0, 1, 2, 3].map(i => {
    const p = rel(i);
    const s = st.seats[i];
    const turn = (g.phase === 'bidding' || g.phase === 'playing') && g.turn === i && g.trick.length < 4;
    const backs = p === 0 ? '' : `<div class="backs">${'<div class="back"></div>'.repeat(g.counts[i])}</div>`;
    return `<div class="seat pos${p}">
      ${p === 2 || p === 1 || p === 3 ? '' : seatBubble(g, i)}
      ${p === 2 ? backs : ''}
      <div class="nameplate team${(i % 2 === myTeam) ? 0 : 1} ${turn ? 'turn' : ''}">
        ${g.dealer === i ? '<span class="dealer" title="Раздава">Р</span>' : ''}
        ${s && !s.online ? '<span class="off" title="Няма връзка"></span>' : ''}
        ${esc(seatName(i))}
      </div>
      ${p !== 0 ? seatBubble(g, i) : ''}
      ${p === 1 || p === 3 ? backs : ''}
    </div>`;
  }).join('');

  // Новохвърлените карти (които не са били на масата при предишното рисуване) излитат от играча
  const trickKeys = g.trick.map(([s, c]) => s + ':' + c);
  const fresh = seenTrick === null ? new Set() : new Set(trickKeys.filter(k => !seenTrick.has(k)));
  seenTrick = new Set(trickKeys);
  const tb = document.querySelector('.table')?.getBoundingClientRect() || {width: 800, height: 420};
  const from = {0: [0, tb.height * 0.6], 1: [tb.width * 0.42, 0], 2: [0, -tb.height * 0.42], 3: [-tb.width * 0.42, 0]};
  const trickHtml = g.trick.map(([seat, c]) => {
    const p = rel(seat), win = g.trick_win === seat ? 'win' : '';
    if (!fresh.has(seat + ':' + c)) return cardHtml(c, `t${p} ${win}`);
    const [ox, oy] = from[p];
    const spin = (Math.random() < 0.5 ? -1 : 1) * (300 + Math.random() * 120);
    return cardHtml(c, `t${p} ${win} fly`, `--ox:${ox.toFixed(0)}px;--oy:${oy.toFixed(0)}px;--spin:${spin.toFixed(0)}deg`);
  }).join('');

  const legal = new Set(g.legal);
  const myTurnPlay = g.phase === 'playing' && !g.announce && g.turn === st.me && g.trick.length < 4;
  const banner = g.announce ? `<div class="announce-banner">
      <div class="muted">Играе се</div>
      <div class="announce-contract">${contractLabel(g.contract)}${g.multiplier === 2 ? ' <span class="mult">контра</span>' : g.multiplier === 4 ? ' <span class="mult">реконтра</span>' : ''}</div>
      <div>обявено от <b>${esc(seatName(g.bidder))}</b></div>
    </div>` : '';
  if (!myTurnPlay || !legal.has(selected)) selected = null;
  const n = g.hand.length;
  const handHtml = g.hand.map((c, i) => {
    let cls = g.phase === 'playing' ? (myTurnPlay ? (legal.has(c) ? 'legal' : 'illegal') : '') : '';
    if (c === selected) cls += ' selected';
    const off = i - (n - 1) / 2;   // ветрило: завъртане и лека дъга
    return cardHtml(c, cls, `--rot:${(off * 3).toFixed(1)}deg;--arc:${(off * off * 1.4).toFixed(1)}px`);
  }).join('');

  let bidPanel = '';
  if (g.phase === 'bidding' && st.me !== null) {
    const opts = new Set(g.bid_options);
    const mineTurn = g.turn === st.me;
    bidPanel = `<div class="bid-panel">
      ${CONTRACTS.map(c => `<button data-bid="${c}" class="${SUIT_SYM[c] ? 'suit-btn s-' + c : ''}" ${mineTurn && opts.has(c) ? '' : 'disabled'}>${SUIT_SYM[c] ? `<span class="sym-big">${SUIT_SYM[c]}</span> ${CONTRACT_NAME[c]}` : CONTRACT_NAME[c]}</button>`).join('')}
      <button data-bid="double" class="double" ${mineTurn && opts.has('double') ? '' : 'disabled'}>Контра</button>
      <button data-bid="redouble" class="double" ${mineTurn && opts.has('redouble') ? '' : 'disabled'}>Реконтра</button>
      <button data-bid="pass" class="primary" ${mineTurn ? '' : 'disabled'}>Пас</button>
    </div>`;
  }

  const mult = g.multiplier === 2 ? ' ×2' : g.multiplier === 4 ? ' ×4' : '';
  const contractPill = g.contract
    ? `<span class="contract-pill">${g.phase === 'bidding' ? 'Обява' : 'Игра'}: <b>${contractLabel(g.contract)}${mult}</b> · ${esc(seatName(g.bidder))}</span>`
    : (g.phase === 'bidding' ? '<span class="contract-pill muted">Обявяване…</span>' : '');

  const tricksText = `${g.tricks_won[myTeam]} – ${g.tricks_won[other]}`;
  const historyRows = g.history.map(h =>
    `<tr><td>${contractLabel(h.contract, false)}</td><td class="us">${h.points[myTeam]}</td><td class="them">${h.points[other]}</td></tr>`).join('');

  const lastTrick = g.last_trick
    ? `<div><h3>Последна взятка · ${esc(seatName(g.last_trick.winner))}</h3>
       <div class="last-trick">${g.last_trick.cards.map(([, c]) => cardHtml(c, 'small')).join('')}</div></div>` : '';

  app.innerHTML = `<div class="game">
    <div class="main">
      <div class="topbar">
        <div class="score"><span class="us">${teamLabel(myTeam)} ${g.scores[myTeam]}</span><span class="muted">:</span><span class="them">${g.scores[other]} ${teamLabel(other)}</span></div>
        ${contractPill}
        ${g.phase === 'playing' ? `<span class="muted desk-only">Взятки: ${tricksText}</span>` : ''}
        ${g.hanging ? `<span class="muted desk-only">Висящи: ${g.hanging}</span>` : ''}
        <span class="spacer"></span>
        ${st.me !== null ? '<button class="danger desk-only" data-ui="end">Прекрати играта</button>' : ''}
        <span class="code-badge desk-only">${CODE}</span>
        <button class="ghost mob-only menu-btn" data-ui="menu" aria-label="Меню">☰</button>
        ${menuOpen ? `<div class="menu">
          <div class="muted" style="font-size:13px">Маса <b class="code-badge">${CODE}</b>
            ${g.phase === 'playing' ? `<br>Взятки: ${tricksText}` : ''}${g.hanging ? `<br>Висящи: ${g.hanging}` : ''}</div>
          <button data-ui="side">Резултати и ход на играта</button>
          ${st.me !== null ? '<button class="danger" data-ui="end">Прекрати играта</button>' : ''}
        </div>` : ''}
      </div>
      <div class="table-wrap"><div class="table ${g.claim_show ? 'claim-shake' : ''}" ${g.claim_show ? `style="--e:${claimElapsed(g.claim_show).toFixed(2)}s"` : ''}>${seatsHtml}<div class="trick">${trickHtml}</div>${banner}${claimAnimation(g)}</div></div>
      <div class="hand-area">
        <div class="status-line">${statusText(g)}</div>
        ${g.can_claim ? '<button class="primary claim-btn" id="claim">Свали картите – всички ръце са твои</button>' : ''}
        ${bidPanel}
        <div class="hand ${myTurnPlay ? 'myturn' : ''}">${handHtml}</div>
      </div>
    </div>
    <aside class="side ${sideOpen ? 'open' : ''}">
      <button class="ghost mob-only side-close" data-ui="side-close">✕ Затвори</button>
      <div class="history"><h3>Резултати</h3>
        <table><tr><th></th><th class="us">${teamLabel(myTeam)}</th><th class="them">${teamLabel(other)}</th></tr>${historyRows}
        <tr><th>Общо</th><th class="us">${g.scores[myTeam]}</th><th class="them">${g.scores[other]}</th></tr></table>
        <div class="muted" style="font-size:12px;margin-top:4px">Играта е до 151 точки.</div>
      </div>
      ${lastTrick}
      <div><h3>Ход на играта</h3><div class="log">${g.log.slice().reverse().map(l => `<div>${fmtLog(l)}</div>`).join('')}</div></div>
    </aside>
  </div>
  ${renderModal(g, myTeam, other)}`;

  document.querySelectorAll('[data-bid]').forEach(b => b.onclick = () => act('bid', {bid: b.dataset.bid}));
  if (myTurnPlay) {
    document.querySelectorAll('.hand .card.legal').forEach(el => el.onclick = () => {
      const c = el.dataset.card;
      if (TOUCH && selected !== c) { selected = c; renderGame(); return; }
      selected = null;
      act('play', {card: c});
    });
  }
  const nb = document.getElementById('next-hand');
  if (nb) nb.onclick = () => act('next_hand');
  const cl = document.getElementById('claim');
  if (cl) cl.onclick = () => act('claim');
  const ng = document.getElementById('new-game');
  if (ng) ng.onclick = () => act('new_game');
  const tl = document.getElementById('to-lobby');
  if (tl) tl.onclick = () => act('to_lobby');
  const ui = {
    end: () => {
      menuOpen = false;
      if (confirm('Да прекратя ли играта за всички? Резултатът ще бъде изгубен и масата се връща в лобито.')) act('end_game');
    },
    menu: () => { menuOpen = !menuOpen; },
    side: () => { sideOpen = true; menuOpen = false; },
    'side-close': () => { sideOpen = false; },
  };
  document.querySelectorAll('[data-ui]').forEach(b => b.onclick = e => {
    e.stopPropagation();
    ui[b.dataset.ui]();
    if (st.game) renderGame();
  });
}

// Докосване извън менюто го затваря.
document.addEventListener('click', e => {
  if (menuOpen && !e.target.closest('.menu')) { menuOpen = false; if (st && st.game) renderGame(); }
});

// ---------- анимация „Свали картите“ ----------
// Ръка грабва картите на свалилия и ги тръшва в средата, после се обръщат картите на другите.
// Времената са в CSS; --e казва колко е напреднала анимацията, за да не започва отначало
// при прерисуване или при отваряне на страницата по средата.
const claimStarts = {};
const SEAT_SPOT = {0: ['50%', '86%'], 1: ['86%', '50%'], 2: ['50%', '14%'], 3: ['14%', '50%']};
const HAND_FROM = {0: ['50%', '125%'], 1: ['125%', '50%'], 2: ['50%', '-25%'], 3: ['-25%', '50%']};
const HAND_TURN = {0: '0deg', 1: '-90deg', 2: '180deg', 3: '90deg'};   // ръката идва откъм играча
const REST_SPOT = {1: ['77%', '50%'], 2: ['50%', '19%'], 3: ['23%', '50%'], 0: ['50%', '81%']};

function claimElapsed(cs) {
  if (!(cs.id in claimStarts)) claimStarts[cs.id] = performance.now() - cs.elapsed * 1000;
  return (performance.now() - claimStarts[cs.id]) / 1000;
}

function claimAnimation(g) {
  const cs = g.claim_show;
  if (!cs) return '';
  const e = claimElapsed(cs).toFixed(2);
  const p = rel(cs.seat);
  const [sx, sy] = SEAT_SPOT[p], [hx, hy] = HAND_FROM[p];
  const mine = cs.hands[cs.seat].map(c => cardHtml(c)).join('');
  const rest = [0, 1, 2, 3].filter(s => s !== cs.seat && cs.hands[s].length).map((s, i) => {
    const [rx, ry] = REST_SPOT[rel(s)];
    return `<div class="claim-rest" style="left:${rx};top:${ry};--i:${i}">${cs.hands[s].map(c => cardHtml(c, 'small')).join('')}</div>`;
  }).join('');
  return `<div class="claim-anim" style="--e:${e}s;--sx:${sx};--sy:${sy};--hx:${hx};--hy:${hy};--hr:${HAND_TURN[p]}">
    <div class="claim-fan">
      <div class="claim-label">${esc(seatName(cs.seat))} свали картите!</div>
      <div class="claim-cards">${mine}</div>
    </div>
    <div class="claim-hand" aria-hidden="true">✋</div>
    ${rest}
  </div>`;
}

function renderModal(g, myTeam, other) {
  const r = g.hand_result;
  if (g.claim_show) return '';            // точките – след анимацията
  if (!r || (g.phase !== 'hand_over' && g.phase !== 'game_over')) return '';
  const row = (label, arr) => `<tr><td>${label}</td><td class="us">${arr[myTeam]}</td><td class="them">${arr[other]}</td></tr>`;
  const declNote = [myTeam, other].map(t => r.decl_text[t].length ? `${teamLabel(t)}: ${r.decl_text[t].map(esc).join(', ')}` : '').filter(Boolean).join('<br>');
  let footer;
  if (g.phase === 'game_over') {
    const won = st.me !== null && g.winner === st.me % 2;
    footer = `<h2 style="text-align:center">${st.me === null ? teamLabel(g.winner) + ' печели!' : (won ? '🏆 Победа!' : 'Загуба')}</h2>
      <p style="text-align:center" class="muted">Краен резултат ${g.scores[myTeam]} : ${g.scores[other]}</p>
      ${st.is_host ? '<button class="primary" id="new-game">Нова игра</button>' : '<p class="muted" style="text-align:center">Домакинът може да започне нова игра.</p>'}
      ${st.me !== null ? '<button class="ghost" id="to-lobby">Към лобито</button>' : ''}`;
  } else {
    footer = st.me !== null ? '<button class="primary" id="next-hand">Следващо раздаване</button>' : '';
  }
  return `<div class="overlay"><div class="modal">
    <h2>Край на раздаването</h2>
    <div class="muted">${contractLabel(r.contract)}${r.multiplier > 1 ? (r.multiplier === 2 ? ' · контра' : ' · реконтра') : ''} · обявено от ${esc(seatName(r.bidder))}${r.capot !== null ? ' · <b>Капо!</b>' : ''}</div>
    <table>
      <tr><th></th><th class="us">${teamLabel(myTeam)}</th><th class="them">${teamLabel(other)}</th></tr>
      ${row('Карти', r.cards)}${row('Анонси', r.decl)}${row('Общо', r.raw)}
      <tr class="total"><td>Точки</td><td class="us">+${r.points[myTeam]}</td><td class="them">+${r.points[other]}</td></tr>
    </table>
    ${declNote ? `<div class="muted" style="font-size:13px">${declNote}</div>` : ''}
    <div>${esc(r.note)}</div>
    ${footer}
  </div></div>`;
}

poll();
