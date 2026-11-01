"""Recompute derived reports only when audit code changes, using private originals."""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from research.domain import atomic_json

def main():
    state=Path(sys.argv[1]).resolve()
    repo=Path(sys.argv[2]).resolve()
    files=['research/audit.py','research/audit_snapshots.py','trio_model.py','trio_engine.py']
    version=hashlib.sha256(b''.join(Path(f).read_bytes() for f in files)).hexdigest()
    meta=state/'audit_meta.json'
    saved=state/'audit_report.json'
    old=json.loads(meta.read_text()) if meta.exists() else {}
    if old.get('code_sha256')!=version or not saved.exists():
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'model_data').mkdir()
            for month in [7,8,9,10]:
                destination=root/('nar_202610.zip' if month==10 else f'model_data/nar_2026{month:02}.zip')
                shutil.copyfile(state/f'training/nar_2026{month:02}.zip',destination)
            shutil.copyfile(state/'model.pkl',root/'model_data/trio_model.pkl')
            predictions=repo/'state/nar/predictions.csv'
            subprocess.run([sys.executable,'-m','research.audit','--root',str(root),'--predictions',str(predictions),'--out','audit_report.json'],check=True)
            subprocess.run([sys.executable,'-m','research.audit_snapshots','--repo',str(repo),'--ref','HEAD','--predictions',str(predictions),'--report','audit_report.json'],check=True)
        report=json.loads(Path('audit_report.json').read_text())
        report['audit_code_sha256']=version
        atomic_json(saved,report)
        atomic_json(meta,{'code_sha256':version})
    shutil.copyfile(saved,'audit_report.json')
    print('Derived audit report ready',version)

if __name__=='__main__':
    main()
