"""Audit private legacy snapshots without publishing their raw contents."""
import argparse
import collections
import csv
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from research.domain import atomic_json

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--repo',required=True)
    ap.add_argument('--ref',required=True)
    ap.add_argument('--predictions',type=Path,required=True)
    ap.add_argument('--report',type=Path,required=True)
    args=ap.parse_args()
    def git(*argv):
        return subprocess.check_output(['git','-C',args.repo,*argv],text=True)
    commit=git('rev-parse',args.ref).strip()
    paths=git('ls-tree','-r','--name-only',commit,'state/features').splitlines()
    counts=collections.Counter()
    records={}
    for path in paths:
        data=json.loads(git('show',commit+':'+path))
        counts['snapshots']+=1
        try:
            capture=datetime.fromisoformat(data['captured_at'])
            start=datetime.fromisoformat(data['post_at'])
            counts['captured_before_start' if capture<start else 'captured_at_or_after_start']+=1
        except (KeyError,ValueError,TypeError):
            counts['unknown_timestamp']+=1
        fields=data['key'].split('|')
        records[(fields[1].replace('-',''),fields[2],int(re.sub(r'\D','',fields[3])))]=data
        for horse in data.get('entries',[]):
            for run in horse.get('recent_runs',[]):
                if run.get('date','')>=fields[1]:
                    counts['recent_run_same_day_or_future']+=1
    for row in csv.DictReader(args.predictions.open(encoding='utf-8-sig')):
        key=(row['date'].replace('-',''),row['track'],int(re.sub(r'\D','',row['race'])))
        if key in records:
            counts['predictions_with_snapshot']+=1
            counts['same_frozen_bet' if row['bet']==records[key].get('bet') else 'different_snapshot_bet']+=1
    report=json.loads(args.report.read_text())
    report['quality']['legacy_snapshot_audit']=dict(counts)
    report['quality']['legacy_snapshot_state_commit']=commit
    note=f"旧スナップショット{counts['snapshots']}件のうち発走前の記録時刻{counts['captured_before_start']}件、時刻不明{counts['unknown_timestamp']}件。予想CSVと照合できた{counts['predictions_with_snapshot']}件中{counts['different_snapshot_bet']}件で買い目が不一致。実購入・事前公開の完全な証明には使いません。"
    report['findings']=[v for v in report['findings'] if not v.startswith('旧スナップショット')]+[note]
    atomic_json(args.report,report)
    print(json.dumps(dict(counts),ensure_ascii=False))

if __name__=='__main__':
    main()
