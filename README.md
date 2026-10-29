# Yuruhuwa Lab Projects

PythonとAIを使った、小さく動かせる作品をまとめています。各作品のフォルダーに、コード、実行手順、テスト、サンプルを置きます。

| 作品 | できること | 始める場所 |
| --- | --- | --- |
| Python × Gemini 最小AIエージェント | 架空の記事候補を読み、企画メモをMarkdownで保存する | [一緒に動かす](projects/python-gemini-minimal-agent/README.md) |

コードに慣れていなくても、最初はAPIキー不要の模擬実行から試せます。Gemini APIを使う前に、無料枠の対象と上限を確認する手順があります。

## フォルダー構成

```text
projects/
└── python-gemini-minimal-agent/
    ├── README.md
    ├── agent.py
    ├── config.json
    ├── requirements.txt
    ├── tests/
    ├── samples/
    ├── assets/
    └── verification/
```

実装の正本はこの作品集で管理します。記事本文・ブランド・記事サムネイル・編集記録は、別の非公開リポジトリ [note-content-workbench](https://github.com/caprice1026-disc/note-content-workbench) に置きます。作品集もprivateで運用します。URLを知っているだけではアクセスできません。

設計・実装・検証を分け、実際に試した条件と未確認の点を記録します。学習用の出力を、実務導入や収益の実績として扱いません。
