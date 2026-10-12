const $ = (id) => document.getElementById(id);

let deferredInstallPrompt = null;

window.addEventListener('beforeinstallprompt', (event) => {
  event.preventDefault();
  deferredInstallPrompt = event;
  $('installButton').hidden = false;
});

$('installButton').addEventListener('click', async () => {
  if (!deferredInstallPrompt) return;
  deferredInstallPrompt.prompt();
  await deferredInstallPrompt.userChoice;
  deferredInstallPrompt = null;
  $('installButton').hidden = true;
});

$('refreshButton').addEventListener('click', () => loadData(true));

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

function formatUpdatedAt(iso) {
  if (!iso) return '更新時刻不明';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat('ja-JP', {
    month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit'
  }).format(d) + ' 更新';
}

function formatYen(value) {
  return Number(value || 0).toLocaleString('ja-JP') + '円';
}

function formatOdds(value) {
  const n = Number(value || 0);
  if (!n) return '-';
  return n.toLocaleString('ja-JP', { maximumFractionDigits: 1 }) + '倍';
}

function buildXText(race) {
  const marks = (race.marks || []).map((m) => `${m.label}${circledNumber(m.number)}${m.name}`).join('\n');
  let result = '';
  if (race.result?.settled) {
    const details = race.result.trifecta_combo && race.result.trifecta_odds
      ? `｜3連単 ${race.result.trifecta_combo} ${formatOdds(race.result.trifecta_odds)}`
      : '';
    result = `\n結果 ${race.result.hit ? '的中🎯' : '不的中'}｜払戻 ${formatYen(race.result.payout)}｜回収率 ${race.result.roi}%${details}`;
  }
  return `${race.track}${race.race} ${race.time} ${race.tier || ''}\n${marks}\n3連単12点｜高配当狙い${result}`;
}

function renderRace(race) {
  const tpl = $('raceTemplate').content.cloneNode(true);
  tpl.querySelector('.source-pill').textContent = race.source === 'JRA' ? 'JRA' : '地方';
  tpl.querySelector('.tier-pill').textContent = race.tier || '高配当候補';
  tpl.querySelector('.race-title').textContent = `${race.track}${race.race}`;
  tpl.querySelector('.race-time').textContent = `${race.time} 発走`;
  tpl.querySelector('.score').textContent = race.score ?? '-';
  tpl.querySelector('.bet').textContent = race.bet || '買い目準備中';

  if (race.odds_low != null || race.odds_high != null) {
    const odds = tpl.querySelector('.bet-odds');
    odds.hidden = false;
    const low = race.odds_low == null ? '-' : formatOdds(race.odds_low);
    const high = race.odds_high == null ? '-' : formatOdds(race.odds_high);
    odds.textContent = `予想時オッズ目安：下限 ${low} / 上限 ${high}`;
  }

  const marks = tpl.querySelector('.marks');
  for (const mark of race.marks || []) {
    const div = document.createElement('div');
    div.className = 'mark' + (mark.label === '()' ? ' bomb' : '');
    const odds = Number(mark.odds || 0) > 0 ? `<small>${escapeHtml(formatOdds(mark.odds))}</small>` : '';
    div.innerHTML = `<b>${escapeHtml(mark.label)}</b>${escapeHtml(circledNumber(mark.number))} ${escapeHtml(mark.name)}${odds}`;
    marks.appendChild(div);
  }

  if (race.result?.settled) {
    const pill = tpl.querySelector('.result-pill');
    pill.hidden = false;
    pill.textContent = race.result.hit ? '的中' : '不的中';
    pill.classList.add(race.result.hit ? 'hit' : 'miss');

    const box = tpl.querySelector('.result-box');
    box.hidden = false;
    box.classList.add(race.result.hit ? 'hit' : 'miss');
    box.querySelector('.result-status').textContent = race.result.hit ? '✅ 的中' : '❌ 不的中';
    box.querySelector('.result-stake').textContent = formatYen(race.result.stake);
    box.querySelector('.result-payout').textContent = formatYen(race.result.payout);
    box.querySelector('.result-roi').textContent = `${Number(race.result.roi || 0).toLocaleString('ja-JP')}%`;

    if (race.result.trifecta_combo) {
      const row = box.querySelectorAll('.result-detail')[0];
      row.hidden = false;
      row.querySelector('.result-combo').textContent = race.result.trifecta_combo;
    }
    if (Number(race.result.trifecta_odds || 0) > 0) {
      const row = box.querySelectorAll('.result-detail')[1];
      row.hidden = false;
      row.querySelector('.result-trifecta-odds').textContent = formatOdds(race.result.trifecta_odds);
    }
    if (Number(race.result.trifecta_payout || 0) > 0) {
      const row = box.querySelectorAll('.result-detail')[2];
      row.hidden = false;
      row.querySelector('.result-trifecta-payout').textContent = formatYen(race.result.trifecta_payout);
    }

    if (Number(race.result.best_odds || 0) > 0) {
      const odds = box.querySelector('.result-odds');
      odds.hidden = false;
      odds.textContent = `最高的中オッズ ${Number(race.result.best_odds).toFixed(1)}倍`;
    }
  }

  const x = tpl.querySelector('.x-share');
  x.href = 'https://x.com/intent/tweet?text=' + encodeURIComponent(buildXText(race));

  tpl.querySelector('.copy-bet').addEventListener('click', async (event) => {
    try {
      await navigator.clipboard.writeText(race.bet || '');
      event.currentTarget.textContent = 'コピー済み';
      setTimeout(() => event.currentTarget.textContent = '買い目コピー', 1400);
    } catch {
      event.currentTarget.textContent = 'コピー失敗';
    }
  });

  return tpl;
}

function render(data) {
  const races = data.races || [];
  const summary = data.summary || {};

  $('updatedAt').textContent = formatUpdatedAt(data.generated_at);
  $('selectedCount').textContent = summary.selected_count ?? races.length;
  $('jraCount').textContent = summary.jra_count ?? races.filter((x) => x.source === 'JRA').length;
  $('narCount').textContent = summary.nar_count ?? races.filter((x) => x.source === 'NAR').length;
  $('maxScore').textContent = summary.max_score ?? (races.length ? Math.max(...races.map((x) => Number(x.score || 0))) : '-');
  $('liveBadge').textContent = races.length ? '本日更新済み' : '本日の選抜待ち';

  const settledCount = Number(summary.settled_count || 0);
  const resultSummary = $('resultSummary');
  if (settledCount > 0) {
    resultSummary.hidden = false;
    $('settledCount').textContent = settledCount;
    $('hitCount').textContent = Number(summary.hit_count || 0);
    $('payoutTotal').textContent = Number(summary.payout || 0).toLocaleString('ja-JP');
    $('roiTotal').textContent = summary.roi == null ? '-' : Number(summary.roi).toLocaleString('ja-JP');
  } else {
    resultSummary.hidden = true;
  }

  const list = $('raceList');
  list.innerHTML = '';

  if (!races.length) {
    list.innerHTML = `<div class="panel empty"><strong>まだ本日の勝負レースはありません</strong><span class="muted">Botが条件を満たしたレースを選ぶとここに表示されます。</span></div>`;
    return;
  }

  for (const race of races) list.appendChild(renderRace(race));
}

async function loadData(force = false) {
  try {
    $('refreshButton').disabled = true;
    const suffix = `?t=${Date.now()}`;
    const response = await fetch(`./data/latest.json${suffix}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  } catch (error) {
    $('raceList').innerHTML = `<div class="panel empty"><strong>データを読み込めませんでした</strong><span class="muted">オフラインか、まだ初回データが生成されていない可能性があります。</span></div>`;
    $('updatedAt').textContent = `読み込みエラー: ${error.message}`;
  } finally {
    $('refreshButton').disabled = false;
  }
}

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('./sw.js'));
}

loadData();
