# noteのスクショ振り返り：保存と比較をPythonへ分けた例

画像入力とローカルファイル操作に対応したAI環境で使う教材です。AIが画像を転記し、Pythonが検査・保存・差の計算を行い、本人が記事の採否を決めます。既存の運用リポジトリから役割を取り出して再実装しています。

Pythonの標準ライブラリだけを使用します。検証した実行環境はPython 3.10.9 / Windowsです。外部パッケージ、追加のAPIキー、サーバー、MCPは不要です。Python自体の導入手順やAI環境の利用料はこの例に含みません。別のOS・Python版・新規AIセッションは未検証です。

## できること

たとえば前回の表示回数が1,000、今回が1,200なら、比較結果に差の200を返します。AIが書いた考察と次の記事候補も保存し、次回は前の仮説と本人の判断を読み出せます。集計期間が違う場合は「1日の増加」とせず、観測値の差として警告を添えます。

記事で紹介した普段の流れは、本人が公開 → 1日待つ → URLとアクセス画面をAIへ渡す → 振り返りと候補を保存 → 本人が候補を選ぶ → 本文とサムネイルを作る、という順です。この教材は、そのうち保存・比較・記録の読み出しを担当します。画像の転記、本文の確認、考察、記事や画像の制作は別途AIエージェントへ依頼します。

## ファイルを用意する

[作品集リポジトリ](https://github.com/caprice1026-disc/yuruhuwa-lab-projects)のCode → Download ZIPで取得して展開し、`projects/note-screenshot-feedback-workflow/`を開きます。Gitを使う場合は次の手順でも取得できます。

```sh
git clone https://github.com/caprice1026-disc/yuruhuwa-lab-projects.git
cd yuruhuwa-lab-projects/projects/note-screenshot-feedback-workflow
```

このフォルダーには実行用の`feedback.py`、エージェント向けの`AGENTS.md`、架空の入力見本`fixtures/`、動作確認用の`tests/`があります。追加パッケージのインストールは不要です。

## 架空データで動かす

このフォルダーを作業場所にして実行します。`python` が別のPythonを指す場合は使用する実行ファイルに読み替えてください。

```sh
python -X utf8 -B feedback.py --db local-only/demo.db ingest fixtures/before.json
python -X utf8 -B feedback.py --db local-only/demo.db ingest fixtures/current.json
python -X utf8 -B feedback.py --db local-only/demo.db compare demo-before demo-current
python -X utf8 -B feedback.py --db local-only/demo.db review fixtures/review-before.json
python -X utf8 -B feedback.py --db local-only/demo.db review fixtures/review-current.json
python -X utf8 -B feedback.py --db local-only/demo.db decision review-current candidate-howto --choice defer --instruction "教材の動作確認として保留する" --scope "記事は作成しない"
python -X utf8 -B feedback.py --db local-only/demo.db context demo
python -X utf8 -B feedback.py --db local-only/demo.db ingest fixtures/current.json
python -X utf8 -B -m unittest discover -s tests -v
```

比較の合計差はimpressions=200、page_views=12、likes=2。期間がずれ、タイムゾーンも不明なため警告が出ます。最後のingestはduplicateを返し、観測は増えません。reviewは同じID・同じ内容なら重複追加しません。decisionは判断の履歴として呼び出すたびに1行追加します。

fixturesの観測と考察はすべて架空です。上の保留コマンドはデモの操作であり、本人からの実際の承認ではありません。

## 自分の画面で使う

デモと実データは別のDBにします。`--db` を省略すると `local-only/feedback.db` に保存します。`local-only/` はGitの対象外です。

AIへAGENTS.mdとREADME.mdを読ませ、画像を添えて次のように依頼します。

```text
この画面から1回分の観測を記録してください。
accountは自分用の固定IDを使い、入力はlocal-only/へ保存してください。
前回のcontextがあれば読み、今回との差・前回仮説の評価・候補を保存してください。
記事の作成は、候補を選んで依頼するまで待ってください。
```

Codex向けの指示ファイル名はAGENTS.mdです。別の環境では指示の読み込み方を確認してください。初回は「適用中の指示と実行する手順を説明して」と頼み、正しいフォルダーを参照しているか確かめます。

記事URL・公開日時・流入経路は、この版の観測JSONに専用項目を設けていません。たとえば`local-only/今回の観測ID-notes.md`へ、対象の記事・集計期間・画面の更新時刻とともに保存し、AIにJSONと一緒に読ませます。形式化しているのはインプレッション・PV・スキです。流入元の差の計算やURLからの自動取得は実装していません。

自分の記録を始めるときの依頼には、次の情報を添えます。

```text
公開して1日後の振り返りです。
記事URL：自分の記事のURL
公開日時：分かる範囲で記入
添付：合計、記事別、流入元の画面。期間と更新時刻も含める。

数値は観測JSONへ、URLと流入元は同じ観測IDのメモへ保存してください。
初回なら基準を残し、前回があればcontextを読み、今回と比較してください。
候補を2〜3件示し、私が選んで作成を頼むまでは記事を書かないでください。
```

候補を採用するときは、対象と作成範囲を本人が伝え、エージェントが実際の依頼文を`decision`へ記録します。本文とサムネイルは記事を管理する場所に保存します。文章の推敲にYomiyasuを使う場合は、利用環境で導入済みのスキルを明示して依頼してください。この教材にはYomiyasu本体や画像生成機能は同梱していません。

### 観測JSON

`fixtures/current.json` が全項目を含む見本です。キーの欠落・未知のキー・重複キーはエラーにします。

| 項目 | 意味 |
| --- | --- |
| schema_version | この例では1 |
| id / account | 観測ID / 固定のアカウントID。半角小文字・数字・_・-で1〜64文字 |
| period_start / period_end | 画面上の集計期間。YYYY-MM-DD |
| updated_at | 画面上の更新日時。YYYY-MM-DDTHH:MM:SS。現在時刻で補わない |
| timezone | 表示されたUTCオフセット、または不明ならnull。例：+09:00 |
| source | 画像名・出典メモ。内容の正しさをプログラムが検証する項目ではない |
| articles_complete | 全記事と集計時刻を確認できた場合にtrue |
| totals / articles | 表示・PV・スキ。各値は0以上の整数かnull。記事IDは継続して同じ値 |

合計照合はarticles_completeがtrueで、全行と合計が既知の指標だけ実行します。見切れた行や未知値を0として補完しません。全体と記事別の更新時刻が違う画面は、1回の完全な観測としてまとめないでください。

### 保存と比較のルール

- 同一観測のキーはschema_version・account・期間・表示更新時刻・timezone。ファイル名や入力IDが変わっても、同じキーと値なら既存IDを返します。
- 同じ観測キーで値が違えば保存を拒否します。不完全な観測を後から補う場合も黙って上書きしません。訂正機能はこの例にはありません。
- SQLiteのsnapshotsに観測、reviewsに考察、decisionsに本人の判断を保存します。書き込みが失敗した際はトランザクションをロールバックします。
- compareは同じaccount・timezone表記で、更新時刻の古い順に指定します。null同士のtimezoneは表示時刻による暫定比較で、経過時間を出しません。timezoneが違えば保留します。
- 期間が違っても差は計算しますが、常にobserved_differenceと表示します。記事が片方にない・指標がnullなら、その差もnullです。負の差はそのまま残します。

### 考察と判断

reviewは観測IDと結び付け、facts / hypotheses / candidates / applied_changesを分けます。同じ仮説IDのclaimは変えず、statusと根拠を更新します。別の主張になったら新IDを作ります。

contextはアカウントを指定して読むため、別アカウントの記録を混ぜません。直近2観測を表示時刻順に選び、比較できなければheldと理由を返します。仮説は各IDの最後の評価をまとめ、今回触れなかった仮説も前の評価のまま残します。last_review_idから評価の古さを確認できます。decisionsは記録順に返る履歴で、現在の判断は実際の本人の依頼と照合してください。

decisionには対象review・候補ID・approve/defer/decline・本人の文言・範囲を渡します。空の文言や存在しない候補は拒否します。ただし、入力した人を認証する機能はありません。AIが架空の承認文を書かないようAGENTS.mdで指示し、実際の会話を人が確認する運用です。decisionを保存しても本文生成・公開は実行されません。

## 確認範囲と限界

テストは重複、衝突、未知値、合計、期間差、仮説の引き継ぎ、判断の必須項目などを確認します。画像読取の正確さ、仮説の妥当性、アクセス増加は検証できません。誤った数値でも形式と合計が正しければ通るため、原本との照合が必要です。

1人で手動実行する小規模な例です。DBの暗号化、認証、競合時の再試行、スキーマ移行、訂正履歴、常駐実行、公開稿の自動取得・差分比較は実装していません。DBへの直接変更を防ぐものでもありません。

参照： [Python sqlite3](https://docs.python.org/3.10/library/sqlite3.html)、[SQLite transactions](https://www.sqlite.org/lang_transaction.html)、[OpenAI AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)。

## 困ったとき

- `python`を実行できない場合は、Pythonが導入済みか確認してください。Windowsでは`py -3`、macOSなどでは`python3`というコマンド名の場合もあります。ここで動作確認したのはWindowsのPython 3.10.9です。
- `expected keys`は入力項目の不足・追加を示します。`fixtures/`と項目を照合し、流入元など追加情報は別のメモへ保存してください。
- `same observation has conflicting values`は、同じ時刻・期間の既存記録と値が異なることを示します。原本を確認し、別の時刻に見せかけて登録しないでください。この例には訂正機能がありません。
- デモをもう一度最初から試す場合は、すべてのコマンドの`--db`を新しいファイル名にそろえて実行します。既存の実データを削除する必要はありません。

実行した検査と未検証の範囲は[検証記録](verification/README.md)にまとめています。
