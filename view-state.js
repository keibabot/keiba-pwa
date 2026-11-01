(function(root){
 'use strict';
 const jstDate=now=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(now));
 const excluded=track=>['門別','帯広ば','帯広'].includes(track);
 function freshness(data,now){
  if(!data||data.schema_version!==2)return {ok:false,label:'当日データ未接続',reason:'研究パイプラインの初回データを待っています。'};
  if(data.date!==jstDate(now))return {ok:false,label:'日付が古いデータ',reason:'過去のレースを今日の予想には表示しません。'};
  if(data.health?.status!=='ok')return {ok:false,label:'取得失敗・要確認',reason:data.health?.error||'更新状態が正常ではありません。'};
  for(const value of [data.generated_at,data.health.checked_at,data.health.source_at]){
   const age=now-Date.parse(value||'');
   if(!Number.isFinite(age)||age< -60000||age>35*60000)return {ok:false,label:'更新が止まっています',reason:'35分以上更新がないため、今日の候補表示を停止しています。固定済み記録は履歴に残っています。'};
  }
  return {ok:true,label:'研究データ更新中',reason:'約15分間隔の取得。GitHub Actionsの遅延があります。'};
 }
 function eligible(r,now){
  const start=Date.parse(r.scheduled_start||''),fixed=Date.parse(r.fixed_at||''),source=Date.parse(r.source_at||'');
  return !excluded(r.track)&&r.paper_only===true&&r.date===jstDate(now)&&Number.isFinite(start)&&Number.isFinite(fixed)&&Number.isFinite(source)&&fixed<start-300000&&source<=fixed+60000&&fixed-source<=600000&&start>now&&!['settled','review_required'].includes(r.result?.status);
 }
 const api={jstDate,excluded,freshness,eligible};
 if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.KeibaView=api;
})(typeof globalThis!=='undefined'?globalThis:this);
