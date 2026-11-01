'use strict';
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=v=>Number.isFinite(v)?v.toLocaleString('ja-JP'):'—';
const pct=v=>Number.isFinite(v)?`${v.toFixed(1)}%`:'未算定';
const yen=v=>Number.isFinite(v)?`${Math.round(v).toLocaleString('ja-JP')}円`:'未算定';
let latest=null;
function empty(message){return `<div class="empty">${esc(message)}</div>`;}
function stat(label,value,foot){return `<article class="stat"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(foot)}</small></article>`;}
function renderResearch(d){
 const s=d.source||{};
 $('period').textContent=typeof s.period==='string'?s.period:JSON.stringify(s.period||'期間未確認');
 $('stats').innerHTML=stat('公式結果の収録',num(s.official_races),'レース')+stat('保存予想',num(s.predictions),'件 / 外れも検証対象')+stat('結果と照合できた予想',num(s.matched_races),'レース')+stat('検証した買い方',num((d.strategies||[]).length),'方式 / 過去データへの仮適用');
 $('scope').textContent='競馬場の配当分布は公式結果、買い方の成績は保存予想と照合できたレースが対象です。対象範囲・欠損による偏りがあります。';
 $('strategyRows').innerHTML=(d.strategies||[]).map(v=>`<tr><td><strong>${esc(v.name)}</strong></td><td>${num(v.races)}R</td><td>${num(v.hits)}R</td><td>${pct(v.hit_rate)}</td><td>${yen(v.stake)}</td><td>${pct(v.roi)}</td></tr>`).join('')||'<tr><td colspan="6">照合できたデータがありません。</td></tr>';
 $('venueCards').innerHTML=(d.venues||[]).filter(v=>v.track!=='門別').map(v=>`<article class="card"><p class="eyebrow">${num(v.races)} RACES</p><h3>${esc(v.track)}</h3><div class="number">${yen(v.median_trio_payout)}</div><p class="muted">三連複払戻の中央値（100円あたり）</p><dl><dt>三連複1万円以上の割合</dt><dd>${pct(v.high_payout_rate)}</dd><dt>Bot照合数</dt><dd>${num(v.bot_races)}R</dd><dt>Bot的中率</dt><dd>${pct(v.bot_hit_rate)}</dd><dt>Bot回収率</dt><dd>${pct(v.bot_roi)}</dd></dl><small class="muted">過去の標本。今後の収益性は未確認。</small></article>`).join('')||empty('競馬場別の分析データはまだありません。');
 $('markCards').innerHTML=(d.marks||[]).map(v=>`<article class="mark"><strong>${esc(v.mark)}</strong><b>${pct(v.top3_rate)}</b><small>3着以内 ${num(v.top3)} / ${num(v.n)}</small></article>`).join('')||empty('印ごとの照合データはまだありません。');
 $('researchNotes').innerHTML=(d.limitations||[]).map((v,i)=>`<article class="note"><p class="eyebrow">NOTE ${String(i+1).padStart(2,'0')}</p><p>${esc(v)}</p></article>`).join('');
 if(d.notes) $('researchNotes').innerHTML+=(d.notes||[]).map(v=>`<article class="note"><h3>${esc(v.title||'調査メモ')}</h3><p>${esc(v.text||v)}</p></article>`).join('');
 const sources=[...(d.sources||[])];if(s.url)sources.unshift({title:'分析元データ',url:s.url});
 $('sources').innerHTML=sources.filter(v=>/^https?:\/\//.test(v.url||'')).map(v=>`<a href="${esc(v.url)}" target="_blank" rel="noopener noreferrer">${esc(v.title||v.url)} ↗</a>`).join('');
 $('freshness').textContent=`分析更新：${d.generated_at?new Date(d.generated_at).toLocaleString('ja-JP',{timeZone:'Asia/Tokyo'}):'不明'}（日本時間）`;
}
function makeTickets(marks,axisIndex){const unique=[...new Map(marks.filter(m=>Number.isInteger(Number(m.number))&&Number(m.number)>0).map(m=>[Number(m.number),m])).values()];if(unique.length<5)return[];const axis=Number(unique[axisIndex].number),others=unique.filter(m=>Number(m.number)!==axis).slice(0,4).map(m=>Number(m.number)),out=[];for(let i=0;i<others.length;i++)for(let j=i+1;j<others.length;j++)out.push([axis,others[i],others[j]].sort((a,b)=>a-b));return out;}
function futureRace(r,now){if(r.track==='門別'||!/^\d{4}-\d{2}-\d{2}$/.test(r.date||'')||!/^\d{1,2}:\d{2}$/.test(r.time||''))return false;const time=r.time.padStart(5,'0');const at=Date.parse(`${r.date}T${time}:00+09:00`);return Number.isFinite(at)&&at>now&&!['finished','cancelled','canceled'].includes(r.status)&&!r.result?.settled;}
function renderPicks(){const now=Date.now(),axis=Number($('axis').value);const races=(latest?.races||[]).filter(r=>futureRace(r,now));$('pickCards').innerHTML=races.map(r=>{const tickets=makeTickets(r.marks||[],axis);if(tickets.length!==6)return '';const a=r.marks[axis];return `<article class="card"><p class="eyebrow">${esc(r.date)} / ${esc(r.time)} 発走</p><h3>${esc(r.track)} ${esc(r.race)}</h3><p>軸：${esc(a.label)} ${esc(a.number)} ${esc(a.name)}</p><div class="tickets">${tickets.map(t=>t.join('−')).join(' / ')}</div><p>三連複6点 · 各100円 · 計600円</p><p class="muted">保存印からの仮組成。最新の出走取消・オッズ・馬場は未確認。的中確率と期待収益は未算定。</p></article>`;}).join('')||empty('発走前の有効な予想データがありません。過去のレースを今日の候補として表示しません。');}
async function getJSON(path){const r=await fetch(path,{cache:'no-store'});if(!r.ok)throw new Error(`${path}: ${r.status}`);return r.json();}
async function load(){ $('refresh').disabled=true;$('error').hidden=true;const results=await Promise.allSettled([getJSON('research.json'),getJSON('latest.json')]);if(results[0].status==='fulfilled')renderResearch(results[0].value);else{$('error').hidden=false;$('error').textContent='研究データを取得できませんでした。接続状態を確認して更新してください。';$('freshness').textContent='分析データ未取得';}if(results[1].status==='fulfilled')latest=results[1].value;else latest=null;renderPicks();$('refresh').disabled=false;}
$('refresh').addEventListener('click',load);$('axis').addEventListener('change',renderPicks);setInterval(renderPicks,60000);
let installPrompt;window.addEventListener('beforeinstallprompt',e=>{e.preventDefault();installPrompt=e;$('install').hidden=false;});$('install').addEventListener('click',async()=>{if(installPrompt){await installPrompt.prompt();installPrompt=null;$('install').hidden=true;}});
if('serviceWorker'in navigator)navigator.serviceWorker.register('./sw.js').catch(()=>{});
load();
