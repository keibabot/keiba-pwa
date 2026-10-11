# 高配当競馬Bot PWA

公開用PWAです。Bot本体・Secretsは別のprivate repositoryで管理し、このrepositoryには公開してよい画面と予想データだけを置きます。

## 現在の機能
- 今日の高配当候補をスマホ向けカードで表示
- `◉ ◎ ▲ ☆ △ ()` の印と馬名
- 高配当スコア
- 3連単12点
- 買い目コピー
- X投稿画面への導線
- ホーム画面追加対応
- Service Workerによるキャッシュ

## データ
`data/latest.json` はprivate側の競馬Botから更新する想定です。

## 公開
GitHub Pagesで公開する想定です。PagesのSourceはGitHub Actionsに設定してください。
