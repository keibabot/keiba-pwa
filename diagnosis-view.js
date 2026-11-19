(async()=>{
const host=document.getElementById('diagnosis');if(!host)return;
try{
const r=await fetch('diagnosis.json',{cache:'no-store'});if(!r.ok)throw Error(r.status);const d=await r.json();
const title=document.createElement('h2');title.textContent='低回収率の原因診断';host.append(title);
const note=document.createElement('p');note.textContent=`集計 ${d.generated_at}。発走前保存の紙上予想。A:候補不足 / B:買い目・着順 / C:的中しても購入額以下 / D:要照合。見送りは別集計。`;host.append(note);
for(const [name,g] of Object.entries(d.diagnosis)){
 const p=document.createElement('p');p.textContent=`${name}: A ${g.counts.A||0} / B ${g.counts.B||0} / C ${g.counts.C||0} / D ${g.counts.D||0} / 購入額超の的中 ${g.counts.profitable_hit||0} / 見送り ${g.counts.skip||0}。回収率 ${g.metrics.roi_pct?.toFixed(2)??'未確定'}%`;host.append(p);
}
const detail=document.createElement('details'),s=document.createElement('summary');s.textContent='穴候補の事後比較と限界';detail.append(s);
for(const [name,g] of Object.entries(d.counterfactual)){const p=document.createElement('p');p.textContent=`${name}: ${g.all.hits}/${g.all.settled_races}的中、回収率 ${g.all.roi_pct?.toFixed(2)??'未確定'}%。事後再構成・未採用。対象差があるため全体の回収率だけで比較しません。`;detail.append(p);}
const p=document.createElement('p');p.textContent='選ばなかった馬を買えば改善するとは確認できません。条件は探索仮説。近走着差・展開・休養の根拠、予想時三連単オッズは不足。勝ち馬だけを抽出して条件を作っていません。';detail.append(p);host.append(detail);
}catch(e){host.textContent='原因診断データを取得できません。予想の編集・コピーは引き続き使えます。';}
})();
