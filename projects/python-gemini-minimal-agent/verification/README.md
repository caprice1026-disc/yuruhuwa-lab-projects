# 検証記録

## 移行前の実API確認

2026-10-27 15:29:02 UTC、Windows / Python 3.10.9 / google-genai 1.52.0で、gemini-3.5-flash-liteへのモデル要求2回、ツール2回、6.36秒でtask-list.md保存に成功した。架空データだけを使い、本人がFree Tierを確認した既存キーで認証した。実請求・残クォータは未照会。

[元の検証commit](https://github.com/caprice1026-disc/note-content-workbench/commit/33bea9edd41cb31263287f56649873f0f4171cce)と [引継ぎ記録](prior-live-result.json)を保持。既存成功を移行後の新しい実API実行として書き換えない。途中のHTTP 400はツール結果のContent.roleをuserへ直した後に解消した。

## 移行後の確認

コードの配置を作品直下へ変更し、サンプルの参照先を追従させた。Windowsの既存Python環境で20件の単体テスト成功、mockで2回ずつの呼出とMarkdown保存を確認。実APIの追加呼出は行っていない。

新規venvへのパッケージ導入、別OS/別Python版、実務効果・収益、無料請求・残量は未検証。これは信頼できるローカル作業用の教材で、攻撃的な別プロセスから隔離するOSサンドボックスではない。

文章の正確性と公開可否は、人間が出力と根拠を確認する。note投稿や販売設定は実装していない。
