# 高配当競馬Bot — 三連複研究室

研究用PWA: https://keibabot.github.io/keiba-pwa/

実購入なし。自動投票・SNS・Discord送信はありません。中央の実績は混ぜず、地方（門別・ばんえい除外）を検証します。

## 動作

非公開 `keiba-auto-bot` の **Trio paper research** が約15分間隔（日本時間9〜22時台）と夜間に実行します。旧main/recoveryワークフローは停止したままです。GitHub Actionsの開始時刻は保証されません。

1. 当日公式CSVを取得。公式ファイルの配信時刻・日付・列・重複を検証。
2. 発走60〜5分前、馬体重等を取得できたレースを推論し、入力許可リスト・モデル版・取得時刻・買い目を固定保存。
3. 非公開 `state` ブランチの `state/trio/ledger.jsonl` に追記。ハッシュ連鎖とGit履歴を保全。
4. 公式着順・全三連複払戻行を照合。空欄や返還不明は要照合、払戻未掲載は未確定。
5. state保存後、公開用の `latest.json` / `history.json` / `health.json` だけを一括更新。
6. Pagesが新画面を配備。JSONはオフラインキャッシュを使わず、古い候補は表示しない。

初回固定後の予想再生成はしません。結果訂正は追記します。日をまたいだ未確定は月次ファイルで再照合（同じ月は1日1取得以下）。原本ZIP・モデルは非公開state内に保存し、公式CSVを公開サイトに再配布しません。

## モデルと評価

- 7〜8月1,787Rで学習、9月910RでBrierにより選択。元の学習済みモデルを維持し、10月で再学習していません。
- 10月985Rの再現: 軸6点302的中・回収率96.97%、5頭BOX357的中・72.42%。各方式3,000円/R。
- **10月は既閲覧の事後評価**です。将来の収益性・確率校正は未確認。
- 新旧の共通165Rを同じ6,000円/Rで比較。新軸6点114.60%ですが標本選択・高配当依存があり、全985Rの収益性未達を覆しません。
- 各馬のモデル値は順位付けスコア。校正済み3着内確率・組合せ的中確率・期待値は未提供。
- 配備後の事前保存成績は別に集計します。2方式の仮予算を合算した購入ではありません。

## 再検証

Python 3.12 / `pip install -r requirements-research.txt`

```sh
python -m unittest discover -s tests -v
node tests/view-state.test.cjs
python -m research.audit --root . --predictions /private/trio_predictions.csv --out audit_report.json
python -m research.audit_snapshots --repo /private/keiba-auto-bot --ref <state-commit> --predictions /private/trio_predictions.csv --report audit_report.json
python -m research.live --state /private/state/trio --out .
```

`trio_model.py` の学習再現には `model_data/nar_202607.zip`〜09と `nar_202610.zip` が必要です。取得済み原本は非公開stateの `state/trio/training/` にあります。再取得せずコピーして検証できます。

詳細: [AUDIT.md](AUDIT.md)。運用スクリプト: `research/`。ブラウザの日付・鮮度境界: `view-state.js`。
