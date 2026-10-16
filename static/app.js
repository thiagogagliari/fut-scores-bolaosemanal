const app = document.querySelector("#app");
const toastRegion = document.querySelector("#toast-region");
const state = { user: null, data: null, adminData: null, teams: [], tab: "picks", selectedMember: null, selectedHistory: null, selectedAdminRound: null, register: false };
let stateSyncTimer = null;
let stateSyncInProgress = false;
const pickSaveJobs = new Map();

document.addEventListener("load", (event) => {
  if (event.target.matches?.("[data-team-logo]")) {
    event.target.parentElement.classList.add("has-logo");
  }
}, true);
document.addEventListener("error", (event) => {
  if (event.target.matches?.("[data-team-logo]")) {
    event.target.parentElement.classList.remove("has-logo");
  }
}, true);

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.error || "Não foi possível concluir a solicitação.");
    error.status = response.status;
    throw error;
  }
  return payload;
}

function escapeText(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

const TEAM_PALETTES = {
  "Palmeiras": ["#087a45", "#e8fff2", "PAL"],
  "Flamengo": ["#d71935", "#fff0f2", "FLA"],
  "Corinthians": ["#e7eaf0", "#171b23", "COR"],
  "Ceará": ["#e8eaf0", "#10151d", "CEA"],
  "Fluminense": ["#7c193b", "#16805a", "FLU"],
  "São Paulo/SP": ["#e9e9ed", "#d22135", "SPF"],
  "Internacional": ["#d82032", "#fff0f0", "INT"],
  "Grêmio": ["#1283b3", "#151a24", "GRE"],
  "Santos": ["#f4f3ed", "#20242c", "SAN"],
  "Botafogo": ["#f2f3f5", "#131821", "BOT"],
  "Vasco da Gama": ["#f0f0f2", "#161a23", "VAS"],
  "Fortaleza": ["#174a9b", "#d91d36", "FOR"],
  "Cruzeiro": ["#1461bf", "#fff", "CRU"],
  "Atlético Mineiro": ["#f0f1f4", "#171b23", "CAM"],
  "Bahia": ["#1673c7", "#e22d3b", "BAH"],
  "Vitória/BA": ["#dc2537", "#f4f4f5", "VIT"],
  "RB Bragantino": ["#e32231", "#f0f2f5", "RBB"],
  "Juventude/RS": ["#16844a", "#f3f5f3", "JUV"],
  "Mirassol": ["#e1c530", "#16864f", "MIR"],
  "Arsenal": ["#e8243a", "#fff", "ARS"],
  "Chelsea": ["#1456ab", "#f3f6ff", "CHE"],
  "Liverpool": ["#cf1835", "#fff2e8", "LIV"],
  "Manchester City": ["#69c9ed", "#12305b", "MCI"],
  "Manchester Utd": ["#df2635", "#f4d34e", "MUN"],
  "Barcelona": ["#a82047", "#244a9a", "FCB"],
  "Real Madrid": ["#e8e8f1", "#353c83", "RMA"],
  "Juventus": ["#f0f1f3", "#171b22", "JUV"],
  "Milan": ["#d62436", "#171b22", "MIL"],
  "PSG": ["#17468e", "#eb3b52", "PSG"],
  "Brasil": ["#e3c92e", "#16854c", "BRA"],
};

function crestPalette(team) {
  if (TEAM_PALETTES[team]) return TEAM_PALETTES[team];
  let hash = 0;
  for (const char of team) hash = (hash * 31 + char.codePointAt(0)) >>> 0;
  const hue = hash % 360;
  const initials = team.normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .split(/[\s/.-]+/).filter(Boolean).slice(0, 3).map((part) => part[0]).join("").toUpperCase();
  return [`hsl(${hue} 62% 34%)`, `hsl(${hue} 80% 92%)`, initials];
}

function teamCrest(team, className = "team-badge") {
  const [primary, secondary, abbreviation] = crestPalette(team);
  const crestUrl = state.teams.find((item) => item.name === team)?.crestUrl;
  const safeUrl = typeof crestUrl === "string" && /^https?:\/\//i.test(crestUrl) ? crestUrl : "";
  return `<span class="team-crest-wrap ${className}${safeUrl ? " has-logo" : ""}" role="img" aria-label="Escudo do ${escapeText(team)}">
    ${safeUrl ? `<img class="team-logo" data-team-logo src="${escapeText(safeUrl)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : `<svg class="team-crest" viewBox="0 0 40 46" aria-hidden="true">
      <path d="M20 2 37 8v13c0 10.7-6.6 18.3-17 23C9.6 39.3 3 31.7 3 21V8L20 2Z" fill="${primary}" stroke="${secondary}" stroke-width="2.5"/>
      <path d="M7 11 20 6l13 5v9c0 8.4-4.9 14.9-13 19.2C11.9 34.9 7 28.4 7 20v-9Z" fill="none" stroke="${secondary}" stroke-opacity=".55" stroke-width="1"/>
      <text x="20" y="26" text-anchor="middle" fill="${secondary}" font-family="Arial,sans-serif" font-size="${abbreviation.length > 3 ? 9 : 11}" font-weight="800">${escapeText(abbreviation)}</text>
    </svg>`}</span>`;
}

function toast(message, isError = false) {
  const item = document.createElement("div");
  item.className = `toast${isError ? " error" : ""}`;
  item.textContent = message;
  toastRegion.append(item);
  window.setTimeout(() => item.remove(), 3600);
}

function renderAuth() {
  const register = state.register;
  app.innerHTML = `
    <main class="auth-page">
      <section class="auth-hero">
        <a class="brand" href="/">FUT<span>//</span>SCORES</a>
        <div class="hero-copy">
          <p class="eyebrow">A arquibancada é sua</p>
          <h1>Palpite.<br><span>Pontue.</span><br>Lidere.</h1>
          <p>Junte a galera, dê seus palpites e mostre quem realmente entende de futebol.</p>
          <div class="hero-points"><span><i></i> Rodadas semanais</span><span><i></i> Ranking ao vivo</span></div>
        </div>
      </section>
      <section class="auth-side">
        <form class="auth-card" id="auth-form">
          <p class="eyebrow">${register ? "Faça parte do bolão" : "Entre para jogar"}</p>
          <h2>${register ? "Entre para o time" : "A bola está rolando"}</h2>
          <div class="auth-tabs" role="tablist">
            <button type="button" data-mode="login" class="${register ? "" : "active"}">Entrar</button>
            <button type="button" data-mode="register" class="${register ? "active" : ""}">Criar cadastro</button>
          </div>
          ${register ? `<div class="field"><label for="name">Nome</label><input id="name" name="name" autocomplete="name" placeholder="Como a galera te chama?" required minlength="2" maxlength="60"></div>` : ""}
          <div class="field"><label for="email">E-mail</label><input id="email" name="email" type="email" autocomplete="email" placeholder="voce@email.com" required></div>
          <div class="field"><label for="password">Senha</label><input id="password" name="password" type="password" autocomplete="${register ? "new-password" : "current-password"}" placeholder="${register ? "Mínimo de 8 caracteres" : "Sua senha"}" required minlength="8"></div>
          ${register ? `<div class="field"><label for="team">Time do coração</label><select id="team" name="team" required><option value="">Escolha seu time</option>${state.teams.map((team) => `<option value="${escapeText(team.name)}">${escapeText(team.name)}</option>`).join("")}</select></div>` : ""}
          <button class="primary-button" type="submit">${register ? "Criar meu perfil" : "Entrar no bolão"} <span aria-hidden="true">→</span></button>
          ${register ? "" : `<p class="demo-note">Conta demo jogador: <strong>torcedor@futscores.com / torcida123</strong></p>`}
        </form>
      </section>
    </main>`;

  app.querySelectorAll("[data-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      state.register = button.dataset.mode === "register";
      renderAuth();
    });
  });
  app.querySelector("#auth-form").addEventListener("submit", submitAuth);
}

async function submitAuth(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const payload = Object.fromEntries(form.entries());
  try {
    const result = await api(state.register ? "/api/register" : "/api/login", {
      method: "POST", body: JSON.stringify(payload),
    });
    state.user = result.user;
    state.register = false;
    state.data = await api("/api/state");
    if (state.user.role === "admin") {
      state.adminData = await api("/api/admin");
      state.tab = "admin";
    } else {
      state.tab = "picks";
      startStateSync();
    }
    renderApp();
    toast(`Bem-vindo(a), ${result.user.name}!`);
  } catch (error) {
    toast(error.message, true);
  }
}

function initials(name) {
  return name.split(/\s+/).slice(0, 2).map((part) => part[0] || "").join("").toUpperCase();
}

function formatKickoff(iso) {
  const date = new Date(iso);
  return `${date.toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit" })} · ${date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
}

function formatCurrency(cents) {
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL",
  }).format(cents / 100);
}

function renderRoundHero() {
  const round = state.data.round;
  const matches = Array.isArray(round.matches) ? round.matches : [];
  const matchCount = round.matchCount ?? matches.length;
  const paidCount = round.paidCount ?? 0;
  const fee = `R$ ${(round.prizeCents / 100).toFixed(2).replace(".", ",")}`;
  const userPaid = `R$ ${(round.userPaidCents / 100).toFixed(2).replace(".", ",")}`;
  const totalCollected = `R$ ${(round.totalCollectedCents / 100).toFixed(2).replace(".", ",")}`;
  const paid = round.paymentPaid;
  return `
    <section class="round-hero${paid ? " payment-paid" : ""}">
      <div><p class="eyebrow">${escapeText(round.dateRange)}</p><h1>${escapeText(round.name)}</h1>
      <p class="round-subtitle">${matchCount} jogos · ${matches.filter((match) => match.pick).length} / ${matchCount} palpites · ${paidCount} participante(s) confirmado(s)</p>
      <p class="round-eligibility${paid ? " eligible" : " ineligible"}">${paid ? "Você está confirmado(a) e concorrendo nesta rodada." : "Pagamento pendente: seus palpites não entram na disputa nem na classificação."}</p></div>
      <aside class="fee-card" data-fee-card><p class="fee-caption">Valor do bolão desta semana</p>
        <div class="fee-main"><strong>${fee}</strong><span class="fee-pill${paid ? " paid" : ""}">${paid ? "Pago" : "Pendente"}</span></div>
        <div class="fee-details"><span>Você pagou: <strong>${userPaid}</strong></span><span>Acumulado: <strong>${totalCollected}</strong></span></div>
      </aside>
    </section>`;
}

function renderRoundParticipants() {
  const round = state.data.round;
  const participants = Array.isArray(round.participants) ? round.participants : [];
  const { paymentDeadline, paymentOpen } = round;
  if (!round.id || !participants.length) return "";
  const deadlineLabel = paymentDeadline
    ? new Date(paymentDeadline).toLocaleString("pt-BR", {
      day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
    })
    : "aguardando o primeiro jogo";
  return `<section class="panel round-participants">
    <div class="panel-heading"><div><h2>Quem está concorrendo</h2>
      <span class="subtle">${state.data.round.paidCount} pagamento(s) confirmado(s) · prazo: ${deadlineLabel}${paymentOpen ? "" : " · encerrado"}</span></div></div>
    <div class="round-participant-list">${participants.map((participant) => `
      <div class="round-participant">
        <span><strong>${escapeText(participant.name)}</strong><small>${escapeText(participant.team)}</small></span>
        <b class="${participant.paid ? "participant-paid" : "participant-pending"}">${participant.paid ? "Confirmado · concorrendo" : "Pendente · fora da disputa"}</b>
      </div>`).join("")}</div>
  </section>`;
}

function renderRules() {
  return `<aside class="panel rule-card"><h3>✳ &nbsp;Regra do jogo</h3>
    <div class="rule-row"><span class="rule-value">10</span><span>Placar exato</span></div>
    <div class="rule-row"><span class="rule-value">3</span><span>Vencedor / empate</span></div>
    <div class="rule-row"><span class="rule-value">1</span><span>Gols do vencedor</span></div>
    <div class="rule-row"><span class="rule-value">1</span><span>Gols do perdedor</span></div>
    <div class="rule-row"><span class="rule-value">1</span><span>Diferença de gols</span></div>
  </aside>`;
}

function renderMatches() {
  const matches = state.data.round.matches;
  if (!matches.length) return `<p class="empty-note">Ainda não há jogos para esta rodada.</p>`;
  return `<div class="match-list">${matches.map((match) => {
    const started = match.started;
    const locked = state.data.round.status === "finished" || started;
    const [homePick, awayPick] = match.pick || ["", ""];
    const exactPick = match.pick !== null && match.homeResult !== null &&
      match.awayResult !== null && match.pick[0] === match.homeResult &&
      match.pick[1] === match.awayResult;
    const resultLine = match.homeResult !== null && match.awayResult !== null
      ? !state.data.round.eligible
        ? `Placar final ${match.homeResult} × ${match.awayResult} · fora da disputa por falta de pagamento confirmado`
        : `Placar final ${match.homeResult} × ${match.awayResult} · ${match.pickPoints ?? 0} ponto(s) neste jogo${exactPick ? " · Placar exato!" : ""}`
      : match.pick ? "Placar e pontos serão exibidos após o resultado oficial."
        : "Você não enviou palpite para este jogo.";
    const pickStatus = match.pick
      ? "Palpite salvo"
      : locked ? "Sem palpite neste jogo"
        : "Preencha os dois placares para salvar";
    return `<article class="match-card${exactPick ? " exact-hit" : ""}" data-match-id="${match.id}">
      <div class="match-meta"><span>${formatKickoff(match.startsAt)}</span><span class="match-status">${state.data.round.status === "finished" ? "Rodada encerrada" : locked ? "Palpite fechado" : "Palpite aberto"}</span></div>
      <div class="match-row">
        <div class="team">${teamCrest(match.home)}<span>${escapeText(match.home)}</span></div>
        <input class="score-input" type="number" min="0" max="20" inputmode="numeric" aria-label="Palpite de gols do ${escapeText(match.home)}" value="${homePick}" ${locked ? "disabled" : ""}>
        <span class="score-separator">×</span>
        <input class="score-input" type="number" min="0" max="20" inputmode="numeric" aria-label="Palpite de gols do ${escapeText(match.away)}" value="${awayPick}" ${locked ? "disabled" : ""}>
        <div class="team"><span>${escapeText(match.away)}</span>${teamCrest(match.away)}</div>
      </div><p class="pick-save-status${match.pick ? " saved" : ""}" data-pick-status aria-live="polite">${pickStatus}</p>
      <p class="match-points">${escapeText(resultLine)}</p></article>`;
  }).join("")}</div>`;
}

function renderFinishedRoundAnnouncement() {
  const finishedRound = state.data.finishedRound;
  if (!finishedRound) return "";
  const champions = finishedRound.winners;
  const championNames = champions.map((winner) => winner.name).join(", ");
  const heading = finishedRound.isWinner
    ? "🏆 Você é campeão da rodada!"
    : champions.length
      ? `Rodada encerrada · campeão(ões): ${championNames}`
      : "Rodada encerrada";
  const summary = finishedRound.isWinner
    ? `Parabéns! Você marcou ${finishedRound.userPoints} pontos, com ${finishedRound.userExact} placar(es) exato(s), e receberá ${formatCurrency(finishedRound.userPayoutCents)}.`
    : champions.length
      ? `Você marcou ${finishedRound.userPoints} pontos e acertou ${finishedRound.userExact} placar(es) exato(s). ${championNames} ${champions.length === 1 ? "fez" : "fizeram"} a maior pontuação; compare os palpites jogo a jogo.`
      : "Nenhum participante enviou palpites nesta rodada.";

  return `<section class="round-result-announcement" role="status" aria-live="polite">
    <div class="round-result-heading"><div><p class="eyebrow">${escapeText(finishedRound.dateRange)}</p>
      <h2>${escapeText(heading)}</h2><p>${escapeText(finishedRound.name)} · ${summary}</p></div>
      <span class="round-result-pool">Prêmio total <strong>${formatCurrency(finishedRound.poolCents)}</strong></span>
    </div>
    ${finishedRound.isWinner && finishedRound.userVerificationCode ? `<div class="winner-verification" role="note">
      <span>Código de confirmação do campeão</span>
      <strong>${escapeText(finishedRound.userVerificationCode)}</strong>
      <small>Informe este código ao administrador do torneio para confirmar sua vitória.</small>
    </div>` : ""}
    ${champions.length ? `<div class="round-winners">${champions.map((winner) => `
      <div class="round-winner"><strong>${winner.id === state.user.id ? "Você — campeão" : escapeText(winner.name)}</strong>
        <span>${winner.points} pontos · ${winner.exact} placar(es) exato(s)</span>
        <b>Recebe ${formatCurrency(winner.payoutCents)}</b></div>`).join("")}</div>` : ""}
    <div class="round-result-matches">${finishedRound.matches.map((match) => {
      const exactClass = match.userExact ? " exact-hit" : "";
      const userPick = match.userPick
        ? `${match.userPick[0]} × ${match.userPick[1]}`
        : "Sem palpite";
      const championPicks = match.winnerPicks
        .filter((winner) => !finishedRound.isWinner || winner.userId !== state.user.id)
        .map((winner) => {
          const pick = winner.pick ? `${winner.pick[0]} × ${winner.pick[1]}` : "Sem palpite";
          return `<div class="round-result-pick${winner.exact ? " exact-pick" : ""}">
            <span>${escapeText(winner.name)}</span><strong>${pick}</strong>
            <small>${winner.points} pt${winner.exact ? " · Placar exato" : ""}</small></div>`;
        }).join("");
      return `<article class="round-result-match${exactClass}">
        <div class="round-result-match-title"><strong>${escapeText(match.home)} × ${escapeText(match.away)}</strong>
          <span>Final ${match.homeResult} × ${match.awayResult}</span></div>
        <div class="round-result-picks">
          <div class="round-result-pick${match.userExact ? " exact-pick" : ""}">
            <span>Seu palpite</span><strong>${userPick}</strong>
            <small>${match.userPoints} pt${match.userExact ? " · Placar exato" : ""}</small></div>
          ${championPicks}</div></article>`;
    }).join("")}</div>
  </section>`;
}

function renderPicks() {
  const round = state.data.round;
  const openMatches = round.matches.filter((match) => round.status === "active" && !match.started);
  const completed = openMatches.filter((match) => match.pick).length;
  const progress = openMatches.length ? Math.round(completed / openMatches.length * 100) : 0;
  const progressLabel = round.status === "finished"
    ? "Rodada encerrada"
    : openMatches.length
      ? `${completed} de ${openMatches.length} jogos com palpite salvo`
      : "Não há jogos abertos para palpites";
  return `<div class="content-grid">
    <section class="panel">
      <div class="panel-heading pick-panel-heading"><div><h2>Meus palpites</h2><span class="subtle">Cada jogo é salvo automaticamente quando os dois placares forem preenchidos.</span>
        <div class="pick-progress">
          <progress class="pick-progress-bar" data-pick-progress-bar max="100" value="${progress}" aria-label="Progresso dos palpites">${progress}%</progress>
          <small data-pick-progress-label>${progressLabel}</small>
        </div>
      </div></div>
    ${renderMatches()}</section>${renderRules()}</div>`;
}

function renderCompare() {
  const other = state.data.standings.find((member) => member.id === state.selectedMember);
  if (!other) return `<section class="panel compare-panel"><div class="panel-heading"><h2>Comparação</h2></div><div class="compare-content">Selecione alguém na classificação.</div></section>`;
  return `<section class="panel compare-panel"><div class="panel-heading"><h2>Comparação · ${escapeText(other.name)}</h2></div>
    <div class="compare-content"><p><strong>${escapeText(other.team)}</strong> · ${other.points} pontos acumulados</p>
    ${state.data.round.matches.map((match) => {
      const started = match.started;
      const otherPick = (match.otherPicks || []).find((item) => item.userId === other.id);
      const ownText = match.pick ? `${match.pick[0]} × ${match.pick[1]}` : "Sem palpite";
      const otherText = !started ? "Oculto até o início" : otherPick ? `${otherPick.pick[0]} × ${otherPick.pick[1]}` : "Sem palpite";
      const resultText = match.homeResult !== null && match.awayResult !== null
        ? `Placar ${match.homeResult} × ${match.awayResult} · Você: ${match.pickPoints ?? 0} pt · ${escapeText(other.name)}: ${otherPick?.points ?? 0} pt`
        : started ? "Aguardando resultado oficial" : "A pontuação aparece após o resultado";
      return `<div class="compare-row"><strong>${escapeText(match.home)} – ${escapeText(match.away)}</strong><span>Você: ${ownText}</span><span>${escapeText(other.name)}: ${otherText}</span><small>${resultText}</small></div>`;
    }).join("")}</div></section>`;
}

function renderStandings() {
  return `<section class="panel">
    <div class="panel-heading"><div><h2>Classificação</h2><span class="subtle">O ranking do bolão</span></div></div>
    <div class="standings-list">${state.data.standings.map((member, index) => `<div class="standing-row">
      <span class="standing-rank">${index + 1}</span>${teamCrest(member.team, "standing-crest")}
      <div class="standing-copy"><strong>${escapeText(member.name)}${member.id === state.user.id ? " (você)" : ""}</strong><small>${escapeText(member.team)} · ${member.exact} exato(s)</small></div>
      <span class="standing-points">${member.points}</span>
      <button class="compare-button${member.id === state.selectedMember ? " selected" : ""}" data-compare="${member.id}" ${member.id === state.user.id ? "disabled" : ""}>Comparar</button>
    </div>`).join("")}</div></section>`;
}

function renderHistory() {
  const history = state.data.history;
  const active = history.find((round) => round.id === state.selectedHistory) || history[0];
  return `<div class="history-stats">
    <div class="stat-card"><span>Rodadas</span><strong>${state.data.summary.rounds}</strong></div>
    <div class="stat-card"><span>Vitórias</span><strong>${state.data.summary.wins}</strong></div>
    <div class="stat-card"><span>Pontos</span><strong>${state.data.summary.points}</strong></div>
    <div class="stat-card"><span>Melhor</span><strong>#${state.data.summary.rank || "—"}</strong></div>
    <div class="stat-card"><span>Prêmios pagos no bolão</span><strong>${formatCurrency(state.data.summary.totalPayoutCents || 0)}</strong></div>
  </div>
  <section class="panel history-table"><div class="panel-heading"><h2>Histórico do bolão</h2></div>
    ${history.length ? `<div class="history-row history-header"><strong>Rodada</strong><strong>Seus pontos</strong><strong>Posição</strong><strong>Placar exato</strong><strong>Prêmios pagos</strong></div>${history.map((round) => `<div class="history-row"><div><strong>${escapeText(round.name)}</strong><small>${escapeText(round.dateRange)}</small></div><span>${round.points} pts</span><span>#${round.rank || state.data.summary.rank || "—"}</span><span class="exact-count">${round.exact} exato(s)</span><span class="history-payout">${formatCurrency(round.paidOutCents || 0)}${round.payouts?.length ? `<small>${round.payouts.map((payout) => `${escapeText(payout.name)} · ${formatCurrency(payout.amountCents)}`).join("<br>")}</small>` : ""}</span></div>`).join("")}` : `<p class="empty-note">Suas rodadas encerradas vão aparecer aqui.</p>`}</section>
  ${active ? `<section class="panel history-detail"><div class="panel-heading"><div><h2>Detalhe completo</h2><span class="subtle">${escapeText(active.name)} · ${escapeText(active.dateRange)}</span></div><span class="history-round-payout">Pago aos campeões: <strong>${formatCurrency(active.paidOutCents || 0)}</strong></span></div>
    <div class="history-detail-list">${active.matches.map((match) => `<div class="history-match"><span>${escapeText(match.home)} × ${escapeText(match.away)}</span><strong>${match.homeResult} – ${match.awayResult}</strong></div>`).join("")}</div></section>` : ""}`;
}

function renderAdmin() {
  const rounds = state.adminData.rounds;
  const members = state.adminData.members;
  const selected = rounds.find((round) => round.id === state.selectedAdminRound) || rounds[0];
  if (selected) state.selectedAdminRound = selected.id;
  const paidCount = selected ? selected.paidUserIds.length : 0;
  const unpaidPickers = selected
    ? selected.participants.filter((member) => member.hasPicks && !member.paid)
    : [];
  const paymentDeadline = selected?.paymentDeadline
    ? new Date(selected.paymentDeadline).toLocaleString("pt-BR", {
      day: "2-digit", month: "2-digit", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    })
    : "primeiro jogo ainda não cadastrado";
  const payoutReport = rounds.length ? `
    <section class="panel admin-round-panel payout-report">
      <div class="panel-heading"><div><h2>Relatório financeiro do bolão</h2><span class="subtle">Valores efetivamente entregues aos campeões</span></div></div>
      <div class="payout-report-totals">
        <span>Arrecadado em todas as rodadas <strong>${formatCurrency(state.adminData.totalCollectedCents || 0)}</strong></span>
        <span>Prêmios efetivamente pagos <strong>${formatCurrency(state.adminData.totalPaidOutCents || 0)}</strong></span>
      </div>
      <div class="payout-report-list">${rounds.map((round) => `<article class="payout-report-round">
        <div class="payout-report-round-heading"><strong>${escapeText(round.name)}</strong><span>${escapeText(round.dateRange)}</span></div>
        <div class="payout-report-values"><span>Arrecadado <b>${formatCurrency(round.totalCollectedCents || 0)}</b></span>
          <span>Prêmio calculado <b>${formatCurrency(round.calculatedPrizeCents || 0)}</b></span>
          <span>Pago <b>${formatCurrency(round.paidOutCents || 0)}</b></span></div>
        ${round.payoutWinners?.length ? `<div class="payout-report-winners">${round.payoutWinners.map((winner) => `<label class="payout-report-winner">
          <span><strong>${escapeText(winner.name)}</strong><small>Prêmio: ${formatCurrency(winner.dueCents)}${winner.paidAt ? ` · Entregue: ${new Date(winner.paidAt).toLocaleDateString("pt-BR")}` : " · Aguardando entrega"}</small></span>
          <span class="payout-confirm-state">${winner.paidCents ? `Pago ${formatCurrency(winner.paidCents)}` : "Não pago"}</span>
          <input type="checkbox" data-payout="${winner.userId}" data-payout-round="${round.id}" aria-label="Marcar prêmio de ${escapeText(winner.name)} como pago" ${winner.paidAt ? "checked" : ""}>
        </label>`).join("")}</div>` : `<p class="payout-report-empty">${round.status === "active" ? "Rodada em andamento." : "Sem campeões elegíveis com resultados completos."}</p>`}
      </article>`).join("")}</div>
    </section>` : "";
  const currency = (cents) => (cents / 100).toFixed(2);
  const teamOptions = (current = "") => `${current ? "" : `<option value="" selected disabled>Escolha um time</option>`}${state.teams.map((team) =>
    `<option value="${escapeText(team.name)}" ${team.name === current ? "selected" : ""}>${escapeText(team.name)}</option>`
  ).join("")}${current && !state.teams.some((team) => team.name === current) ? `<option value="${escapeText(current)}" selected>${escapeText(current)} (histórico)</option>` : ""}`;
  const roundList = rounds.length ? `
    <section class="panel admin-round-panel">
      <div class="panel-heading"><div><h2>Configurar rodada</h2><span class="subtle">Edite período, valor e status</span></div>
        <select class="admin-round-select" id="admin-round-select" aria-label="Escolher rodada">
          ${rounds.map((round) => `<option value="${round.id}" ${round.id === selected.id ? "selected" : ""}>${escapeText(round.name)} · ${round.status === "active" ? "Em andamento" : "Encerrada"}</option>`).join("")}
        </select>
      </div>
      <form class="admin-form admin-round-form" id="admin-round-form">
        <label>Nome da rodada<input name="name" maxlength="50" required value="${escapeText(selected.name)}"></label>
        <label>Período<input name="dateRange" maxlength="50" required value="${escapeText(selected.dateRange)}" placeholder="17/10 a 18/10"></label>
        <label>Valor do bolão (R$)<input name="prize" type="number" min="0" max="1000000" step="0.01" required value="${currency(selected.prizeCents)}"></label>
        <label>Status<select name="status"><option value="active" ${selected.status === "active" ? "selected" : ""}>Em andamento</option><option value="finished" ${selected.status === "finished" ? "selected" : ""}>Encerrada</option></select></label>
        <button class="save-button" type="submit">Salvar rodada</button>
        <button class="delete-button" type="button" data-delete-round="${selected.id}">Excluir rodada</button>
      </form>
    </section>
    <section class="panel admin-round-panel">
      <div class="panel-heading"><div><h2>Partidas de ${escapeText(selected.name)}</h2><span class="subtle">${selected.matches.length} partida(s) cadastrada(s)</span></div></div>
      <form class="admin-form admin-add-match" id="admin-match-form">
        <label>Mandante<select name="home" required>${teamOptions()}</select></label>
        <label>Visitante<select name="away" required>${teamOptions()}</select></label>
        <label>Data e horário<input name="startsAt" type="datetime-local" required></label>
        <button class="save-button" type="submit">Adicionar partida</button>
      </form>
      <div class="admin-match-list">${selected.matches.length ? selected.matches.map((match) => `
        <form class="admin-match-row" data-match-form="${match.id}">
          <div class="admin-match-top"><strong>${escapeText(match.home)} × ${escapeText(match.away)}</strong><span>${match.pickCount} palpite(s)</span></div>
          <div class="admin-match-controls">
            <label>Mandante<select name="home" required>${teamOptions(match.home)}</select></label>
            <label>Visitante<select name="away" required>${teamOptions(match.away)}</select></label>
            <label>Início<input name="startsAt" type="datetime-local" required value="${escapeText(datetimeLocalValue(match.startsAt))}"></label>
            <label>Resultado<input name="homeResult" type="number" min="0" max="20" value="${match.homeResult ?? ""}" placeholder="Casa"></label>
            <span class="score-separator">×</span>
            <label> <span class="visually-hidden">Gols visitante</span><input name="awayResult" type="number" min="0" max="20" value="${match.awayResult ?? ""}" placeholder="Fora"></label>
            <button class="save-button" type="submit">Salvar</button>
            <button class="delete-button" type="button" data-delete-match="${match.id}" aria-label="Excluir partida">Excluir</button>
          </div>
        </form>`).join("") : `<p class="empty-note">Esta rodada ainda não tem partidas.</p>`}</div>
    </section>
    <section class="panel admin-round-panel">
      <div class="panel-heading"><div><h2>Pagamentos e elegibilidade</h2><span class="subtle">${paidCount} de ${members.length} participantes confirmados · prazo: ${paymentDeadline}${selected.paymentOpen ? "" : " · encerrado"}</span></div></div>
      ${selected.championCodes?.length ? `<div class="champion-code-list">
        <strong>Códigos para validar os campeões</strong>
        <p>Confira o código apresentado pelo ganhador com o nome e a rodada abaixo.</p>
        ${selected.championCodes.map((champion) => `<div><span>${escapeText(champion.name)}</span><code>${escapeText(champion.code)}</code></div>`).join("")}
      </div>` : ""}
      ${unpaidPickers.length ? `<div class="payment-alert" role="alert">
        <strong>⚠ ${unpaidPickers.length} participante(s) palpitaram, mas ainda não pagaram</strong>
        <p>Sem pagamento confirmado antes do primeiro jogo, ficam fora da disputa e da classificação desta rodada.</p>
        <ul>${unpaidPickers.map((member) => `<li>${escapeText(member.name)} · ${member.pickCount} palpite(s)</li>`).join("")}</ul>
      </div>` : `<p class="payment-alert payment-alert-clear">Nenhum participante com palpites está aguardando confirmação de pagamento.</p>`}
      ${renderMemberList(members, selected)}
    </section>` : `<section class="panel"><p class="empty-note">Crie sua primeira rodada para começar a organizar o bolão.</p></section>`;
  return `<div class="admin-dashboard">
    <div class="history-stats">
      <div class="stat-card"><span>Rodadas</span><strong>${rounds.length}</strong></div>
      <div class="stat-card"><span>Participantes</span><strong>${members.length}</strong></div>
      <div class="stat-card"><span>Partidas na rodada</span><strong>${selected ? selected.matches.length : 0}</strong></div>
      <div class="stat-card"><span>Arrecadado nesta rodada</span><strong>${formatCurrency(selected?.totalCollectedCents || 0)}</strong></div>
      <div class="stat-card"><span>Prêmios já pagos</span><strong>${formatCurrency(state.adminData.totalPaidOutCents || 0)}</strong></div>
    </div>
    <section class="panel admin-round-panel">
      <div class="panel-heading"><div><h2>Times e escudos</h2><span class="subtle">${state.teams.length} time(s) disponíveis para o bolão</span><p class="team-logo-note">Cole o endereço direto de uma imagem (PNG, JPG ou SVG) para substituir o escudo com letras.</p></div></div>
      <form class="admin-form team-create-form" id="admin-create-team-form">
        <label>Nome do time<input name="name" required maxlength="60" placeholder="Nome do time"></label>
        <label>Link do escudo (imagem)<input name="crestUrl" type="url" maxlength="2048" placeholder="https://exemplo.com/escudo.png"></label>
        <button class="save-button" type="submit">Adicionar time</button>
      </form>
      <div class="admin-team-list">${state.teams.map((team) => `
        <form class="admin-team-row" data-team-form="${team.id}">
          ${teamCrest(team.name, "admin-crest")}
          <label>Nome<input name="name" required maxlength="60" value="${escapeText(team.name)}"></label>
          <label>URL da imagem<input name="crestUrl" type="url" maxlength="2048" value="${escapeText(team.crestUrl || "")}" placeholder="https://..."></label>
          <button class="save-button" type="submit">Salvar</button>
          <button class="delete-button" type="button" data-delete-team="${team.id}">Excluir</button>
        </form>`).join("") || `<p class="empty-note">Nenhum time cadastrado. Adicione times para liberar cadastros e partidas.</p>`}</div>
    </section>
    ${!selected ? `<section class="panel admin-round-panel"><div class="panel-heading"><div><h2>Participantes</h2><span class="subtle">${members.length} conta(s)</span></div></div>${renderMemberList(members, null)}</section>` : ""}
    <section class="panel admin-round-panel">
      <div class="panel-heading"><div><h2>Criar nova rodada</h2><span class="subtle">A rodada anterior será encerrada ao publicar a próxima</span></div></div>
      <form class="admin-form" id="admin-create-round-form">
        <label>Nome<input name="name" required maxlength="50" placeholder="Semana 3"></label>
        <label>Período<input name="dateRange" required maxlength="50" placeholder="24/10 a 25/10"></label>
        <label>Valor do bolão (R$)<input name="prize" type="number" min="0" max="1000000" step="0.01" required value="5.00"></label>
        <button class="save-button" type="submit">Criar rodada</button>
      </form>
    </section>
    ${payoutReport}
    ${roundList}
  </div>`;
}

function renderMemberList(members, selected) {
  return `<div class="admin-members">${members.map((member) => `<div class="admin-member-row${member.is_blocked ? " member-blocked" : ""}">
    ${teamCrest(member.team, "admin-crest")}
    <span class="admin-member-copy"><strong>${escapeText(member.name)}${member.is_blocked ? " · Bloqueado" : ""}</strong><small>${escapeText(member.email)} · ${escapeText(member.team)}</small></span>
    ${selected ? (() => {
      const participant = selected.participants.find((item) => item.id === member.id);
      const paid = selected.paidUserIds.includes(member.id);
      return `<span class="payment-state${paid ? " paid" : " unpaid"}">${paid
        ? "Pago · concorrendo"
        : participant?.hasPicks
          ? `Palpitou (${participant.pickCount}) · sem pagamento`
          : "Pendente · fora da disputa"}</span>
        <input type="checkbox" data-payment="${member.id}" aria-label="Confirmar pagamento de ${escapeText(member.name)}" ${paid ? "checked" : ""} ${!paid && !selected.paymentOpen ? "disabled" : ""}>`;
    })() : ""}
    <button class="member-action" type="button" data-block-member="${member.id}" data-blocked="${member.is_blocked ? "true" : "false"}">${member.is_blocked ? "Desbloquear" : "Bloquear"}</button>
    <button class="delete-button" type="button" data-delete-member="${member.id}">Excluir</button>
  </div>`).join("") || `<p class="empty-note">Ainda não há participantes cadastrados.</p>`}</div>`;
}

function datetimeLocalValue(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

function renderApp() {
  const activeNav = state.tab;
  const isAdmin = state.user.role === "admin";
  app.innerHTML = `
    <header class="app-header">
      <a class="brand" href="/">FUT<span>//</span>SCORES</a>
      <nav class="app-nav" aria-label="Navegação principal">
        <button data-tab="picks" class="${activeNav === "picks" ? "active" : ""}">Meus palpites</button>
        <button data-tab="ranking" class="${activeNav === "ranking" ? "active" : ""}">Classificação</button>
        <button data-tab="history" class="${activeNav === "history" ? "active" : ""}">◷ Histórico</button>
        ${isAdmin ? `<button data-tab="admin" class="${activeNav === "admin" ? "active" : ""}">Administração</button>` : ""}
      </nav>
      <div class="header-user"><span class="team-user-icon" title="${escapeText(`${state.user.name} · ${state.user.team}`)}">${teamCrest(state.user.team, "avatar-crest")}</span>
        <button class="icon-button" id="logout" aria-label="Sair" title="Sair">↪</button></div>
    </header>
    <main class="page-wrap">${activeNav === "admin" ? `<section class="admin-title"><p class="eyebrow">Painel de controle</p><h1>Administração</h1><p class="round-subtitle">Organize rodadas, jogos, placares e pagamentos.</p></section>${renderAdmin()}` : `${renderFinishedRoundAnnouncement()}${renderRoundHero()}
      ${activeNav === "picks" ? renderPicks() : activeNav === "ranking" ? `<div class="content-grid">${renderStandings()}<div>${renderRules()}${renderCompare()}</div></div>` : renderHistory()}${renderRoundParticipants()}`}
    </main>
    <footer class="footer"><span>Fut Scores</span><span>Feito para quem vive futebol ⚽</span></footer>`;

  app.querySelectorAll("[data-tab]").forEach((button) => button.addEventListener("click", () => {
    selectTab(button.dataset.tab);
  }));
  app.querySelector("#logout").addEventListener("click", logout);
  app.querySelectorAll(".match-card .score-input:not(:disabled)").forEach((input) => {
    input.addEventListener("input", () => scheduleMatchPickSave(input.closest(".match-card")));
  });
  app.querySelectorAll("[data-compare]").forEach((button) => button.addEventListener("click", () => {
    state.selectedMember = Number(button.dataset.compare);
    renderApp();
  }));
  if (isAdmin && activeNav === "admin") bindAdminEvents();
}

async function selectTab(tab) {
  if (tab === "admin" && state.user.role !== "admin") return;
  try {
    if (tab === "admin" && !state.adminData) state.adminData = await api("/api/admin");
    state.tab = tab;
    renderApp();
  } catch (error) {
    toast(error.message, true);
  }
}

function hasUnsubmittedPicks() {
  if (state.tab !== "picks" || !state.data) return false;
  return [...app.querySelectorAll(".match-card")].some((card) => {
    const match = state.data.round.matches.find((item) => item.id === Number(card.dataset.matchId));
    if (!match) return false;
    const inputs = [...card.querySelectorAll("input")];
    const baseline = match.pick || ["", ""];
    return inputs.some((input, index) => !input.disabled && input.value !== String(baseline[index] ?? ""));
  });
}

function updatePickProgress() {
  if (!state.data || state.tab !== "picks") return;
  const round = state.data.round;
  const progress = app.querySelector(".pick-progress");
  if (!progress) return;
  const openMatches = round.matches.filter(
    (match) => round.status === "active" && !match.started,
  );
  const openMatchIds = new Set(openMatches.map((match) => match.id));
  const complete = [...app.querySelectorAll(".match-card")].filter((card) => {
    if (!openMatchIds.has(Number(card.dataset.matchId))) return false;
    const inputs = [...card.querySelectorAll(".score-input")];
    return inputs.length === 2 && inputs.every((input) =>
      input.value !== "" && Number.isInteger(Number(input.value))
      && Number(input.value) >= 0 && Number(input.value) <= 20
    );
  }).length;
  const percent = openMatches.length ? Math.round(complete / openMatches.length * 100) : 0;
  progress.querySelector("[data-pick-progress-bar]").value = percent;
  progress.querySelector("[data-pick-progress-label]").textContent =
    openMatches.length ? `${complete} de ${openMatches.length} jogos com palpite preenchido` : (
      round.status === "finished"
        ? "Rodada encerrada"
        : "Não há jogos abertos para palpites"
    );
  const matchCount = round.matchCount ?? round.matches.length;
  const savedCount = round.matches.filter((match) => match.pick).length;
  const subtitle = app.querySelector(".round-hero .round-subtitle");
  if (subtitle) {
    subtitle.textContent = `${matchCount} jogos · ${savedCount} / ${matchCount} palpites · ${(round.paidCount ?? 0)} participante(s) confirmado(s)`;
  }
}

function scheduleMatchPickSave(card) {
  if (!card) return;
  const matchId = Number(card.dataset.matchId);
  const inputs = [...card.querySelectorAll(".score-input")];
  const status = card.querySelector("[data-pick-status]");
  const [home, away] = inputs.map((input) => input.value);
  const validPair = inputs.length === 2 && [home, away].every((score) =>
    score !== "" && Number.isInteger(Number(score)) && Number(score) >= 0 && Number(score) <= 20
  );
  updatePickProgress();

  let job = pickSaveJobs.get(matchId);
  if (!job) {
    job = { timer: null, inFlight: false, waiting: false };
    pickSaveJobs.set(matchId, job);
  }
  if (job.timer !== null) window.clearTimeout(job.timer);
  if (!validPair) {
    status.textContent = "Preencha os dois placares para salvar.";
    status.classList.remove("saved", "saving", "save-error");
    return;
  }

  const pick = { matchId, home: Number(home), away: Number(away) };
  const match = state.data.round.matches.find((item) => item.id === matchId);
  if (match?.pick && match.pick[0] === pick.home && match.pick[1] === pick.away) {
    status.textContent = "Palpite salvo";
    status.classList.add("saved");
    status.classList.remove("saving", "save-error");
    return;
  }

  status.textContent = "Salvando palpite...";
  status.classList.add("saving");
  status.classList.remove("saved", "save-error");
  job.timer = window.setTimeout(() => {
    job.timer = null;
    void persistMatchPick(card, job, pick);
  }, 300);
}

async function persistMatchPick(card, job, pick) {
  if (job.inFlight) {
    job.waiting = true;
    return;
  }
  job.inFlight = true;
  try {
    await api("/api/picks", {
      method: "PUT",
      body: JSON.stringify({ picks: [pick] }),
    });
    const match = state.data.round.matches.find((item) => item.id === pick.matchId);
    if (match) match.pick = [pick.home, pick.away];
    const inputs = [...card.querySelectorAll(".score-input")];
    const stillCurrent = inputs.length === 2
      && Number(inputs[0].value) === pick.home
      && Number(inputs[1].value) === pick.away;
    if (stillCurrent) {
      const status = card.querySelector("[data-pick-status]");
      status.textContent = "Palpite salvo";
      status.classList.add("saved");
      status.classList.remove("saving", "save-error");
    }
    updatePickProgress();
  } catch (error) {
    const status = card.querySelector("[data-pick-status]");
    status.textContent = `Falha ao salvar: ${error.message}`;
    status.classList.add("save-error");
    status.classList.remove("saving", "saved");
    toast(`Não foi possível salvar o palpite: ${error.message}`, true);
  } finally {
    job.inFlight = false;
    if (job.waiting) {
      job.waiting = false;
      const inputs = [...card.querySelectorAll(".score-input")];
      if (inputs.length === 2 && inputs.every((input) => input.value !== "")) {
        const latestPick = {
          matchId: pick.matchId,
          home: Number(inputs[0].value),
          away: Number(inputs[1].value),
        };
        if (latestPick.home !== pick.home || latestPick.away !== pick.away) {
          void persistMatchPick(card, job, latestPick);
        }
      }
    }
  }
}

function updateFeeCard() {
  const card = app.querySelector("[data-fee-card]");
  if (!card || !state.data) return;
  const { prizeCents, paymentPaid } = state.data.round;
  const userPaid = `R$ ${(state.data.round.userPaidCents / 100).toFixed(2).replace(".", ",")}`;
  const totalCollected = `R$ ${(state.data.round.totalCollectedCents / 100).toFixed(2).replace(".", ",")}`;
  const fee = `R$ ${(prizeCents / 100).toFixed(2).replace(".", ",")}`;
  card.closest(".round-hero").classList.toggle("payment-paid", paymentPaid);
  card.querySelector(".fee-main strong").textContent = fee;
  const status = card.querySelector(".fee-pill");
  status.classList.toggle("paid", paymentPaid);
  status.textContent = paymentPaid ? "Pago" : "Pendente";
  card.querySelector(".fee-details").innerHTML =
    `<span>Você pagou: <strong>${userPaid}</strong></span>` +
    `<span>Acumulado: <strong>${totalCollected}</strong></span>`;
}

async function syncUserState() {
  if (!state.user || state.user.role !== "player" || stateSyncInProgress) return;
  if (document.visibilityState === "hidden") return;
  stateSyncInProgress = true;
  try {
    const latest = await api("/api/state");
    if (JSON.stringify(latest) !== JSON.stringify(state.data)) {
      state.data = latest;
      state.user = latest.user;
      state.teams = latest.teams;
      state.pendingRender = true;
      updateFeeCard();
    }
    if (state.pendingRender && !hasUnsubmittedPicks()) {
      state.pendingRender = false;
      renderApp();
    }
  } catch (error) {
    if (error.status === 401) {
      stopStateSync();
      state.user = null;
      state.data = null;
      renderAuth();
    } else if (!state.syncErrorShown) {
      state.syncErrorShown = true;
      toast(`Não foi possível atualizar seus dados: ${error.message}`, true);
    }
  } finally {
    stateSyncInProgress = false;
  }
}

function startStateSync() {
  stopStateSync();
  state.syncErrorShown = false;
  stateSyncTimer = window.setInterval(syncUserState, 8000);
}

function stopStateSync() {
  if (stateSyncTimer !== null) window.clearInterval(stateSyncTimer);
  stateSyncTimer = null;
}

async function refreshAdmin(successMessage) {
  try {
    const [adminData, data, teams] = await Promise.all([
      api("/api/admin"), api("/api/state"), api("/api/teams"),
    ]);
    state.adminData = adminData;
    state.data = data;
    state.teams = teams.teams;
    renderApp();
    if (successMessage) toast(successMessage);
  } catch (error) {
    toast(error.message, true);
  }
}

function bindAdminEvents() {
  const roundSelect = app.querySelector("#admin-round-select");
  roundSelect?.addEventListener("change", () => {
    state.selectedAdminRound = Number(roundSelect.value);
    renderApp();
  });

  app.querySelector("#admin-create-team-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget).entries());
    try {
      await api("/api/admin/teams", {
        method: "POST",
        body: JSON.stringify(values),
      });
      await refreshAdmin("Time adicionado.");
    } catch (error) {
      toast(error.message, true);
    }
  });

  app.querySelectorAll("[data-team-form]").forEach((form) => form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(form).entries());
    try {
      await api(`/api/admin/teams/${form.dataset.teamForm}`, {
        method: "PUT",
        body: JSON.stringify(values),
      });
      await refreshAdmin("Time atualizado.");
    } catch (error) {
      toast(error.message, true);
    }
  }));

  app.querySelectorAll("[data-delete-team]").forEach((button) => button.addEventListener("click", async () => {
    if (!window.confirm("Excluir este time do catálogo? Cadastros e resultados antigos conservarão o nome.")) return;
    try {
      await api(`/api/admin/teams/${button.dataset.deleteTeam}`, { method: "DELETE" });
      await refreshAdmin("Time excluído do catálogo.");
    } catch (error) {
      toast(error.message, true);
    }
  }));

  app.querySelector("#admin-create-round-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget).entries());
    try {
      const result = await api("/api/admin/rounds", {
        method: "POST",
        body: JSON.stringify({
          name: values.name,
          dateRange: values.dateRange,
          prizeCents: Math.round(Number(values.prize) * 100),
        }),
      });
      state.selectedAdminRound = result.id;
      await refreshAdmin("Nova rodada criada.");
    } catch (error) {
      toast(error.message, true);
    }
  });

  app.querySelector("#admin-round-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget).entries());
    try {
      await api(`/api/admin/rounds/${state.selectedAdminRound}`, {
        method: "PUT",
        body: JSON.stringify({
          name: values.name,
          dateRange: values.dateRange,
          prizeCents: Math.round(Number(values.prize) * 100),
          status: values.status,
        }),
      });
      await refreshAdmin("Rodada atualizada.");
    } catch (error) {
      toast(error.message, true);
    }
  });

  app.querySelector("[data-delete-round]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    if (!window.confirm("Excluir esta rodada, suas partidas, palpites e pagamentos? Esta ação não pode ser desfeita.")) return;
    try {
      await api(`/api/admin/rounds/${button.dataset.deleteRound}`, { method: "DELETE" });
      state.selectedAdminRound = null;
      await refreshAdmin("Rodada excluída.");
    } catch (error) {
      toast(error.message, true);
    }
  });

  app.querySelector("#admin-match-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget).entries());
    try {
      await api(`/api/admin/rounds/${state.selectedAdminRound}/matches`, {
        method: "POST",
        body: JSON.stringify({ ...values, startsAt: new Date(values.startsAt).toISOString() }),
      });
      await refreshAdmin("Partida adicionada.");
    } catch (error) {
      toast(error.message, true);
    }
  });

  app.querySelectorAll("[data-match-form]").forEach((form) => form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(form).entries());
    const homeResult = values.homeResult === "" ? null : Number(values.homeResult);
    const awayResult = values.awayResult === "" ? null : Number(values.awayResult);
    try {
      await api(`/api/admin/matches/${form.dataset.matchForm}`, {
        method: "PUT",
        body: JSON.stringify({
          home: values.home,
          away: values.away,
          startsAt: new Date(values.startsAt).toISOString(),
          homeResult,
          awayResult,
        }),
      });
      await refreshAdmin("Partida e resultado atualizados.");
    } catch (error) {
      toast(error.message, true);
    }
  }));

  app.querySelectorAll("[data-delete-match]").forEach((button) => button.addEventListener("click", async () => {
    if (!window.confirm("Excluir esta partida e os palpites associados?")) return;
    try {
      await api(`/api/admin/matches/${button.dataset.deleteMatch}`, { method: "DELETE" });
      await refreshAdmin("Partida excluída.");
    } catch (error) {
      toast(error.message, true);
    }
  }));

  app.querySelectorAll("[data-payment]").forEach((checkbox) => checkbox.addEventListener("change", async () => {
    try {
      await api(`/api/admin/payments/${state.selectedAdminRound}/${checkbox.dataset.payment}`, {
        method: "PUT",
        body: JSON.stringify({ paid: checkbox.checked }),
      });
      await refreshAdmin("Pagamento atualizado.");
    } catch (error) {
      checkbox.checked = !checkbox.checked;
      toast(error.message, true);
    }
  }));

  app.querySelectorAll("[data-payout]").forEach((checkbox) => checkbox.addEventListener("change", async () => {
    try {
      await api(`/api/admin/payouts/${checkbox.dataset.payoutRound}/${checkbox.dataset.payout}`, {
        method: "PUT",
        body: JSON.stringify({ paid: checkbox.checked }),
      });
      await refreshAdmin(checkbox.checked ? "Prêmio registrado como entregue." : "Registro de entrega removido.");
    } catch (error) {
      checkbox.checked = !checkbox.checked;
      toast(error.message, true);
    }
  }));

  app.querySelectorAll("[data-block-member]").forEach((button) => button.addEventListener("click", async () => {
    const blocked = button.dataset.blocked !== "true";
    try {
      await api(`/api/admin/members/${button.dataset.blockMember}`, {
        method: "PUT",
        body: JSON.stringify({ blocked }),
      });
      await refreshAdmin(blocked ? "Participante bloqueado." : "Participante desbloqueado.");
    } catch (error) {
      toast(error.message, true);
    }
  }));

  app.querySelectorAll("[data-delete-member]").forEach((button) => button.addEventListener("click", async () => {
    if (!window.confirm("Excluir este participante e todos os palpites e pagamentos associados? Esta ação não pode ser desfeita.")) return;
    try {
      await api(`/api/admin/members/${button.dataset.deleteMember}`, { method: "DELETE" });
      await refreshAdmin("Participante excluído.");
    } catch (error) {
      toast(error.message, true);
    }
  }));
}

async function logout() {
  try {
    await api("/api/logout", { method: "POST", body: "{}" });
    stopStateSync();
    state.user = null;
    state.data = null;
    state.adminData = null;
    state.pendingRender = false;
    state.tab = "picks";
    state.selectedMember = null;
    renderAuth();
  } catch (error) {
    toast(error.message, true);
  }
}

async function start() {
  try {
    const [teams] = await Promise.all([api("/api/teams")]);
    state.teams = teams.teams;
    state.data = await api("/api/state");
    state.user = state.data.user;
    if (state.user.role === "admin") {
      state.adminData = await api("/api/admin");
      state.tab = "admin";
    } else {
      state.tab = "picks";
      startStateSync();
    }
    renderApp();
  } catch (error) {
    if (error.message !== "Entre na sua conta para continuar.") toast(error.message, true);
    renderAuth();
  }
}

window.addEventListener("focus", syncUserState);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") syncUserState();
});

start();
