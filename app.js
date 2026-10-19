const $ = (id) => document.getElementById(id);
const BUILD_VERSION = document.querySelector('meta[name="build-version"]')?.content || 'dev';

let deferredInstallPrompt = null;
let loadingData = false;

window.addEventListener('beforeinstallprompt', (event) => {
  event.preventDefault();
  deferredInstallPrompt = event;
  const install = $('installButton');
  if (install) install.hidden = false;
});

const installButton = $('installButton');
if (installButton) {
  installButton.addEventListener('click', async () => {
    if (!deferredInstallPrompt) return;
    deferredInstallPrompt.prompt();
    await deferredInstallPrompt.userChoice;
    deferredInstallPrompt = null;
    installButton.hidden = true;
  });
}

const refreshButton = $('refreshButton');
if (refreshButton) refreshButton.addEventListener('click', () => loadData());

function escapeHtml(value = '') {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function circledNumber(value) {
  const table = ['','①','②','③','④','⑤','⑥','⑦','⑧','⑨','⑩','⑪','⑫','⑬','⑭','⑮','⑯','⑰','⑱'];
  const n = Number(value);
  return table[n] || String(value || '');
}

function relativeAge(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const minutes = Math.max(0, Math.floor((Date.now() - d.getTime()) / 60000));
  if (minutes < 1) return 'たった今';
  if (minutes < 60) return `${minutes}分前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}時間前`;
  return `${Math.floor(hours / 24)}日前`;
}

function formatUpdatedAt(iso) {
  if (!iso) return '更新時刻不明';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const absolute = new Intl.DateTimeFormat('ja-JP', {
    month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit'
  }).format(d);
  const age = relativeAge(iso);
  return `${absolute} 更新${age ? `（${age}）` : ''}`;
}

function formatYen(value) {
  return Number(value || 0).toLocaleString('ja-JP') + '円';
}

function formatOdds(value) {
  const n = Number(value || 0);
  if (!n) return '-';
  return n.toLocaleString('ja-JP', { maximumFractionDigits: 1 }) + '倍';
}

function predictionRange(race) {
  const range = race.trifecta_odds_range;
  if (Array.isArray(range) && range.length === 2 && range[0] != null && range[1] != null) {
    return `${formatOdds(range[0])}〜${formatOdds(range[1])}`;
  }
  if (race.odds_snapshot?.status === 'unavailable') return '取得できず';
  if (race.odds_low != null || race.odds_high != null) {
    const low = race.odds_low == null ? '-' : formatOdds(race.odds_low);
    const high = race.odds_high == null ? '-' : formatOdds(race.odds_high);
    return `${low}〜${high}`;
  }
  return '—';
}

function buildXText(race) {
  const marks = (race.marks || []).map((m) => {
    const market = [];
    if (m.popularity) market.push(`${m.popularity}番人気`);
    if (Number(m.odds || 0) > 0) market.push(formatOdds(m.odds));
    return `${m.label}${circledNumber(m.number)}${m.name}${market.length ? ` ${market.join('・')}` : ''}`;
  }).join('\n');
  let result = '';
  if (race.result?.settled) {
    const details = race.result.trifecta_combo && race.result.trifecta_odds
      ? `｜3連単 ${race.result.trifecta_combo} ${formatOdds(race.result.trifecta_odds)}`
      : '';
    result = `\n結果 ${race.result.hit ? '的中🎯' : '不的中'}｜払戻 ${formatYen(race.result.payout)}｜回収率 ${race.result.roi}%${details}`;
  }
  return `${race.track}${race.race} ${race.time} ${race.tier || ''}\n${marks}\n3連単12点｜予想時 ${predictionRange(race)}${result}`;
}

function renderRace(race) {
  const template = $('raceTemplate');
  if (!template?.content) return document.createDocumentFragment();
  const tpl = template.content.cloneNode(true);

  const sourcePill = tpl.querySelector('.source-pill');
  const tierPill = tpl.querySelector('.tier-pill');
  const raceTitle = tpl.querySelector('.race-title');
  const raceTime = tpl.querySelector('.race-time');
  const score = tpl.querySelector('.score');
  const bet = tpl.querySelector('.bet');
  if (sourcePill) sourcePill.textContent = race.source === 'JRA' ? 'JRA' : '地方';
  if (tierPill) tierPill.textContent = race.tier || '高配当候補';
  if (raceTitle) raceTitle.textContent = `${race.track}${race.race}`;
  if (raceTime) raceTime.textContent = `${race.time} 発走`;
  if (score) score.textContent = race.score ?? '-';
  if (bet) bet.textContent = race.bet || '買い目準備中';

  const betOdds = tpl.querySelector('.bet-odds');
  if (betOdds) {
    betOdds.hidden = false;
    betOdds.textContent = `予想時3連単オッズ：${predictionRange(race)}`;
  }

  const marks = tpl.querySelector('.marks');
  if (marks) {
    for (const mark of race.marks || []) {
      const div = document.createElement('div');
      div.className = 'mark' + (mark.label === '()' ? ' bomb' : '');
      const market = [];
      if (mark.popularity) market.push(`${Number(mark.popularity)}番人気`);
      if (Number(mark.odds || 0) > 0) market.push(formatOdds(mark.odds));
      const marketHtml = market.length ? `<small>${escapeHtml(market.join('・'))}</small>` : '';
      div.innerHTML = `<b>${escapeHtml(mark.label)}</b>${escapeHtml(circledNumber(mark.number))} ${escapeHtml(mark.name)}${marketHtml}`;
      marks.appendChild(div);
    }
  }

  if (race.result?.settled) {
    const pill = tpl.querySelector('.result-pill');
    if (pill) {
      pill.hidden = false;
      pill.textContent = race.result.hit ? '的中' : '不的中';
      pill.classList.add(race.result.hit ? 'hit' : 'miss');
    }

    const box = tpl.querySelector('.result-box');
    if (box) {
      box.hidden = false;
      box.classList.add(race.result.hit ? 'hit' : 'miss');
      const status = box.querySelector('.result-status');
      const stake = box.querySelector('.result-stake');
      const payout = box.querySelector('.result-payout');
      const roi = box.querySelector('.result-roi');
      if (status) status.textContent = race.result.hit ? '✅ 的中' : '❌ 不的中';
      if (stake) stake.textContent = formatYen(race.result.stake);
      if (payout) payout.textContent = formatYen(race.result.payout);
      if (roi) roi.textContent = `${Number(race.result.roi || 0).toLocaleString('ja-JP')}%`;

      const detailRows = box.querySelectorAll('.result-detail');
      if (race.result.trifecta_combo && detailRows[0]) {
        detailRows[0].hidden = false;
        const el = detailRows[0].querySelector('.result-combo');
        if (el) el.textContent = race.result.trifecta_combo;
      }
      if (Number(race.result.trifecta_odds || 0) > 0 && detailRows[1]) {
        detailRows[1].hidden = false;
        const el = detailRows[1].querySelector('.result-trifecta-odds');
        if (el) el.textContent = formatOdds(race.result.trifecta_odds);
      }
      if (Number(race.result.trifecta_payout || 0) > 0 && detailRows[2]) {
        detailRows[2].hidden = false;
        const el = detailRows[2].querySelector('.result-trifecta-payout');
        if (el) el.textContent = formatYen(race.result.trifecta_payout);
      }

      if (Number(race.result.best_odds || 0) > 0) {
        const odds = box.querySelector('.result-odds');
        if (odds) {
          odds.hidden = false;
          odds.textContent = `最高的中オッズ ${Number(race.result.best_odds).toFixed(1)}倍`;
        }
      }
    }
  }

  const x = tpl.querySelector('.x-share');
  if (x) x.href = 'https://x.com/intent/tweet?text=' + encodeURIComponent(buildXText(race));

  const copyButton = tpl.querySelector('.copy-bet');
  if (copyButton) {
    copyButton.addEventListener('click', async (event) => {
      try {
        await navigator.clipboard.writeText(race.bet || '');
        event.currentTarget.textContent = 'コピー済み';
        setTimeout(() => event.currentTarget.textContent = '買い目コピー', 1400);
      } catch {
        event.currentTarget.textContent = 'コピー失敗';
      }
    });
  }

  return tpl;
}

function render(data) {
  if (!data || typeof data !== 'object') throw new Error('invalid data');
  const races = Array.isArray(data.races) ? data.races : [];
  const summary = data.summary || {};

  if ($('updatedAt')) $('updatedAt').textContent = formatUpdatedAt(data.generated_at);
  if ($('selectedCount')) $('selectedCount').textContent = summary.selected_count ?? races.length;
  if ($('jraCount')) $('jraCount').textContent = summary.jra_count ?? races.filter((x) => x.source === 'JRA').length;
  if ($('narCount')) $('narCount').textContent = summary.nar_count ?? races.filter((x) => x.source === 'NAR').length;
  if ($('maxScore')) $('maxScore').textContent = summary.max_score ?? (races.length ? Math.max(...races.map((x) => Number(x.score || 0))) : '-');
  if ($('liveBadge')) {
    const generated = Date.parse(data.generated_at || '');
    const stale = !Number.isFinite(generated) || Date.now() - generated > 15 * 60 * 1000;
    $('liveBadge').textContent = stale ? '更新が遅れています・更新時刻を確認' : (races.length ? '本日更新済み' : '本日の選抜待ち');
  }

  const settledCount = Number(summary.settled_count || 0);
  const resultSummary = $('resultSummary');
  if (resultSummary) {
    if (settledCount > 0) {
      resultSummary.hidden = false;
      if ($('settledCount')) $('settledCount').textContent = settledCount;
      if ($('hitCount')) $('hitCount').textContent = Number(summary.hit_count || 0);
      if ($('payoutTotal')) $('payoutTotal').textContent = Number(summary.payout || 0).toLocaleString('ja-JP');
      if ($('roiTotal')) $('roiTotal').textContent = summary.roi == null ? '-' : Number(summary.roi).toLocaleString('ja-JP');
    } else {
      resultSummary.hidden = true;
    }
  }

  const list = $('raceList');
  if (!list) return;
  list.innerHTML = '';

  if (!races.length) {
    list.innerHTML = `<div class="panel empty"><strong>まだ本日の勝負レースはありません</strong><span class="muted">Botが条件を満たしたレースを選ぶとここに表示されます。</span></div>`;
    return;
  }

  for (const race of races) list.appendChild(renderRace(race));
}

async function loadData() {
  if (loadingData) return;
  loadingData = true;
  try {
    if (refreshButton) refreshButton.disabled = true;
    const response = await fetch(`./data/latest.json?t=${Date.now()}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    render(data);
  } catch (error) {
    const list = $('raceList');
    if (list) list.innerHTML = `<div class="panel empty"><strong>データを読み込めませんでした</strong><span class="muted">${escapeHtml(error.message)}</span></div>`;
    if ($('updatedAt')) $('updatedAt').textContent = `読み込みエラー: ${error.message}`;
  } finally {
    loadingData = false;
    if (refreshButton) refreshButton.disabled = false;
  }
}

if ('serviceWorker' in navigator) {
  window.addEventListener('load', async () => {
    try {
      const reg = await navigator.serviceWorker.register(`./sw.js?v=${encodeURIComponent(BUILD_VERSION)}`);
      await reg.update();
    } catch {}
  });
}

loadData();

// Refresh an open PWA and immediately catch up after returning from the background.
setInterval(() => {
  if (document.visibilityState === 'visible') loadData();
}, 60000);
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') loadData();
});
window.addEventListener('online', () => loadData());
