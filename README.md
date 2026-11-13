# Yuruhuwa Lab Projects

PythonとAIを使った、小さく動かせる作品をまとめています。各作品のフォルダーに、コード、実行手順、テスト、サンプルを置きます。

| 作品 | できること | 始める場所 |
| --- | --- | --- |
| noteのアクセス画面から続ける振り返り | AIが転記した数字をSQLiteへ保存し、前回比・仮説・記事候補・本人の判断を引き継ぐ。APIキー不要 | [使い方と架空データのデモ](projects/note-screenshot-feedback-workflow/README.md) |
| Python × Gemini 最小AIエージェント | 架空の記事候補を読み、企画メモをMarkdownで保存する | [一緒に動かす](projects/python-gemini-minimal-agent/README.md) |
| Vast.ai × ComfyUI はじめての画像生成 | Windowsから画像1枚を保存し、手動でDestroyする手順。ローカル検証済み・実GPU再検証は未実施 | [料金と実行手順](projects/vast-comfyui-first-image/README.md) |

noteの振り返り教材はPythonの標準ライブラリだけで動かせます。Geminiの作品も、最初はAPIキー不要の模擬実行から試せます。Gemini APIを使う前に、無料枠の対象と上限を確認する手順があります。

## フォルダー構成

```text
projects/
├── note-screenshot-feedback-workflow/  # 数値の保存・比較と振り返りの教材
├── python-gemini-minimal-agent/        # Geminiを使う最小エージェント
└── vast-comfyui-first-image/           # 画像生成の実行手順
```

実装の正本はこの作品集で管理します。記事本文・ブランド・記事サムネイル・編集記録は、別の非公開リポジトリ [note-content-workbench](https://github.com/caprice1026-disc/note-content-workbench) に置きます。作品集のコードは公開しています。APIキーやローカルの設定ファイルは含めません。

設計・実装・検証を分け、実際に試した条件と未確認の点を記録します。学習用の出力を、実務導入や収益の実績として扱いません。
