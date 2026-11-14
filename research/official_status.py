"""Supplement missing CSV finish statuses from official result HTML, never infer them."""
import argparse,json,hashlib,urllib.request,re
from pathlib import Path
from datetime import datetime,timezone
from bs4 import BeautifulSoup
from research.domain import atomic_json
CODES={'盛岡':10,'水沢':11,'浦和':18,'船橋':19,'大井':20,'川崎':21,'金沢':22,'笠松':23,'名古屋':24,'園田':27,'姫路':28,'高知':31,'佐賀':32}
def parse(raw):
    soup=BeautifulSoup(raw,'html.parser');out={}
    for tr in soup.select('tr'):
        cells=tr.find_all('td',recursive=False)
        if len(cells)!=16 or not tr.select_one('td.horseName'):continue
        n=cells[2].get_text(strip=True);name=cells[3].get_text(strip=True)
        status=cells[0].get_text(strip=True) or cells[11].get_text(strip=True)
        if n.isdigit() and status in ('中止','取消','除外'):
            if n in out:raise ValueError('duplicate status horse')
            out[n]={'name':name,'status':status}
    return out
def enrich(state,key,horses):
    path=Path(state)/'official_status'/f'{key}.json'
    if not path.exists():return horses
    info=json.loads(path.read_text());out=[]
    for h in horses:
        row=dict(h);v=info['statuses'].get(str(int(h['馬番'])))
        if v and v['name']==h['馬名'] and not str(h.get('着順','')).strip():
            row['着順']=v['status'];row['status_source']={k:info[k] for k in ('url','fetched_at','sha256')}
        out.append(row)
    return out
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--state',type=Path,required=True);ap.add_argument('--key',required=True);ap.add_argument('--html',type=Path)
    a=ap.parse_args();day,track,race=a.key.split('|');code=CODES[track];url=f'https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/RaceMarkTable?k_raceDate={day[:4]}/{day[4:6]}/{day[6:]}&k_raceNo={int(race)}&k_babaCode={code}'
    path=a.state/'official_status'/f'{a.key}.json';now=datetime.now(timezone.utc)
    if not a.html and path.exists() and json.loads(path.read_text())['fetched_at'][:10]==now.date().isoformat():return
    if a.html:raw=a.html.read_bytes()
    else:
        with urllib.request.urlopen(url,timeout=30) as r:raw=r.read(2000000)
    soup=BeautifulSoup(raw,'html.parser');text=soup.get_text(' ',strip=True)
    if f'{day[:4]}年{int(day[4:6])}月{int(day[6:])}日' not in text or track not in text:raise ValueError('公式結果の日付・場を照合できません')
    if not re.search(r'(第\s*'+str(int(race))+r'\s*競走|\b'+str(int(race))+r'R\b)',text):raise ValueError('公式レース番号の照合不能')
    atomic_json(path,{'key':a.key,'url':url,'fetched_at':now.isoformat(),'sha256':hashlib.sha256(raw).hexdigest(),'statuses':parse(raw)})
    print(a.key,parse(raw))
if __name__=='__main__':main()
