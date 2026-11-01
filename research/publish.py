"""Publish derived paper data only, atomically, after private ledger commit."""
import base64
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

FILES = ('latest.json', 'history.json', 'health.json')

def main():
    token = os.environ.get('PWA_REPO_TOKEN', '').strip()
    if not token:
        raise RuntimeError('PWA_REPO_TOKEN is missing; private records saved, public publication failed')
    repo = 'keibabot/keiba-pwa'
    health = json.loads(Path('health.json').read_text())
    if health.get('run_id') != os.environ.get('GITHUB_RUN_ID') or (datetime.now(timezone.utc)-datetime.fromisoformat(health['checked_at'])).total_seconds() > 600:
        raise ValueError('refuse stale or unrelated collection output')
    api = f'https://api.github.com/repos/{repo}'
    def request(method, path, body=None):
        req = urllib.request.Request(api + path, data=json.dumps(body).encode() if body is not None else None,
            method=method, headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
            'Content-Type': 'application/json', 'X-GitHub-Api-Version':'2022-11-28'})
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.load(r)
    head = request('GET','/git/ref/heads/main')['object']['sha']
    commit = request('GET','/git/commits/'+head)
    tree = []
    for name in FILES:
        data = json.loads(Path(name).read_text())
        if name != 'health.json' and data.get('schema_version') != 2:
            raise ValueError('refuse nonresearch public payload')
        data['private_state_commit'] = os.environ['RESEARCH_STATE_COMMIT']
        blob = request('POST','/git/blobs',{'content':json.dumps(data,ensure_ascii=False),'encoding':'utf-8'})
        tree.append({'path':name,'mode':'100644','type':'blob','sha':blob['sha']})
    result = request('POST','/git/trees',{'base_tree':commit['tree']['sha'],'tree':tree})
    new = request('POST','/git/commits',{'message':'Record prospective trio research observations','tree':result['sha'],'parents':[head]})
    request('PATCH','/git/refs/heads/main',{'sha':new['sha'],'force':False})
    print('Published derived research data:',new['sha'])

if __name__ == '__main__':
    main()
