# Python × GeminiではじめてのAIエージェント

ChatGPTやGeminiに文章を書いてもらったことがあれば、次は「書いた文章を、自分のPCのファイルにしてもらう」ところまで試してみませんか。

この作品では、AIが架空の記事候補から1つを選び、短い企画メモを保存します。最初はAPIキーなしで動きを確かめ、そのあとGeminiにつなぎます。コードを先に理解し切る必要はありません。ここでいうモデルは依頼に応じて文章や使う道具の選択を返すAIです。

## できあがるもの

実行すると、`outputs` フォルダーにMarkdownファイルができます。Markdownは見出しを `#` などで表すテキスト形式です。Windowsのメモ帳や普段のエディターでも読めます。

```markdown
# 初心者向けのタスク整理企画メモ

> 架空データによる練習用下書き。人間による確認が必要です。

【目的】
架空のタスク一覧を整理する手順を学ぶための企画です。
```

これは [保存した実モデルの出力](samples/live-output.md) の一部を短く示した例です。実行ごとに文章や選ばれる候補は変わります。入力は [架空の2候補](samples/candidates.json)。実在の顧客情報は使いません。

> 教材コードは公開リポジトリから取得できます。APIキーは同梱していないので、まずはキー不要のmockで試してください。

## 一緒に動かす

### 1. Pythonとファイルを用意する

この手順はWindowsのPowerShell向けです。PowerShellは短いコマンドを入力してプログラムを動かす画面です。スタートメニューから開けます。

Pythonが入っているか、次を入力してEnterを押します。

```powershell
python --version
```

`Python 3.10...` のように表示されれば次へ進めます。この作品はPython 3.10以降を前提にしています。見つからなければ [Python公式のWindows向け案内](https://www.python.org/downloads/windows/)を確認し、導入後にPowerShellを開き直してください。

Gitを使う場合は、保存したい親フォルダーで次を実行します。既に取得したフォルダーがあれば、cloneを繰り返さずそのフォルダーを開きます。

```powershell
git clone https://github.com/caprice1026-disc/yuruhuwa-lab-projects.git
Set-Location yuruhuwa-lab-projects
```

Gitを使わない場合は、[作品集](https://github.com/caprice1026-disc/yuruhuwa-lab-projects)の緑色のCodeメニューからDownload ZIPを選び、取得したZIPを展開します。

取得後は次のように対象フォルダーからPowerShellを開きます。

1. エクスプローラーで作品集のフォルダーを開きます。README.mdとprojectsフォルダーが見える場所です。
2. 上部のアドレスバーをクリックし、`powershell` と入力してEnterを押します。その場所でPowerShellが開きます。
3. 次の `Get-Location` で、作品集のフォルダーが表示されることを確認します。

```powershell
Get-Location
Set-Location projects/python-gemini-minimal-agent
python -m venv .venv
.\.venv\Scripts\python.exe -X utf8 -m pip install -r requirements.txt
```

`pip install` は必要なライブラリを取得する処理で、ネット接続が必要です。`-X utf8` はPythonに文字コードをUTF-8として扱わせる指定です。Windowsでの文字コードエラーを避けるため、ここでは明示しています。通信なしで試せるのは、導入後のmock実行です。

`venv` は、この作品だけで使うPython環境を作る機能です。インストール先を分けられます。ここでは `.venv` 内のPythonを直接呼ぶため、Activate.ps1やPowerShellの実行ポリシー変更は不要です。

### 2. まず通信なしで試す

```powershell
.\.venv\Scripts\python.exe agent.py --mock
Get-Content -Encoding UTF8 outputs/weekly-report.md
```

`mock` は、AIの返答を決め打ちのデータで置き換える模擬実行です。ネット接続もAPIキーも使いません。次の表示と企画メモが出れば、読み込みから保存までを確かめられました。

```json
{"mode":"mock","model_calls":2,"tool_calls":2,"saved":"weekly-report.md","human_review_required":true}
```

`model_calls` はモデルへの要求回数、`tool_calls` はPythonが道具を実行した回数です。mockの成功は、実際のGeminiが動いたという意味ではありません。

### 3. APIキーと無料枠を確認する

APIを使うと、プログラムからサービスへ依頼を送り、返答を受け取れます。ここでは、ブラウザーで会話する代わりにPythonからGemini APIへ依頼を送ります。その認証に使う秘密がAPIキーです。

1. [Google公式のAPIキー案内](https://ai.google.dev/gemini-api/docs/api-key)からAI Studioを開きます。
2. 使うプロジェクトを確認して、既存のキーを使うか、公式手順で取得します。画面やキーの種類は変わるため、現在の公式説明を優先してください。
3. **そのキーのプロジェクトがFree Tierか**をAI Studioで確認します。確認できなければ、mockまでで止めます。
4. [公式料金表](https://ai.google.dev/gemini-api/docs/pricing)で、使うモデルのStandard入力・出力が無料枠の対象かを確認します。[公式rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)から、自分の上限・使用量も確認してください。

無料枠は無制限ではなく、対象モデルや利用条件があります。料金区分・地域・残量によって利用できる範囲も変わります。この作品は課金を有効にする手順を含まず、費用が必ずゼロになるとは保証しません。

無料サービスでは、入力・出力が製品改善や人間の確認に使われる場合があります。[利用規約](https://ai.google.dev/gemini-api/terms)を読み、まずは同梱の架空データだけで試してください。個人情報、顧客情報、機密へ置き換えないでください。

### 4. キーをローカルへ保存する

メモ帳で、次の1行を入力します。`replace_me` はメモ帳の中だけで、自分のAPIキーへ置き換えます。まだ保存しないで、次の手順へ進んでください。

```dotenv
GEMINI_API_KEY=replace_me
```

1. メモ帳の「名前を付けて保存」を開き、agent.pyがある作品フォルダーを選びます。
2. 「ファイルの種類」を「すべてのファイル」にし、ファイル名を `.env`、文字コードをUTF-8（BOMなし）にして保存します。
3. エクスプローラーで拡張子を表示し、名前が `.env` で、`.env.txt` になっていないことを確認します。`.env.txt` になった場合は、ファイル名を `.env` に直してから進めてください。

APIキーはパスワードのように扱い、チャット、記事、Gitへ貼り付けないでください。ファイルが `.env.txt` になっていないかも確認します。既に別の場所に `.env` がある場合は、コピーせず、その絶対パスを実行時に指定しても使えます。

この教材は `--env-file` で指定した `.env` からキーを読みます。Windowsの環境変数を設定するだけでは読み込まず、別の `.env` を自動で探すこともありません。このrepoは `.env` をGitから除外します。Gitで取得した場合は、内容を表示せずに次で確認できます。

```powershell
git check-ignore .env
git ls-files --error-unmatch .env 2>$null
```

前者で除外を確認し、後者が何も表示せず終了コード1なら未追跡です。後者でファイル名が出た場合は、pushする前に追跡状態を確認してください。

### 5. Geminiで1回試す

function callingは、モデルが使いたい関数と引数を返す仕組みです。関数は名前を付けてまとめた処理、引数はその処理へ渡す値です。実際の処理はPython側が確認してから実行します。

`config.json` の `model` で使うモデルを選びます。2026年10月31日に公式の料金表・モデル資料を再確認した選択肢は `gemini-3.5-flash-lite` と `gemini-3.1-flash-lite`。公式資料で無料枠とfunction calling対応を確認したモデルです。実APIで保存まで確認したのは3.5の方です。利用前に最新の提供条件を再確認してください。

mockの出力が残っている場合は、先に読んでから別名へ退避します。同じ名前を上書きしないためです。

```powershell
Move-Item -LiteralPath outputs/weekly-report.md -Destination outputs/weekly-report-reviewed-01.md
```

退避先も既にある場合は別の名前を選びます。Free Tierを確認できたら、次で実行します。

```powershell
$projectEnvPath = (Resolve-Path .env).Path
.\.venv\Scripts\python.exe agent.py --live --free-tier-confirmed --env-file $projectEnvPath
Get-ChildItem outputs
```

`--free-tier-confirmed` は、本人がFree Tierを確認したという申告です。料金を無料へ変更するオプションではありません。別の `.env` を使う場合は、`$projectEnvPath` にその絶対パスを指定します。コードは自動探索しません。

成功すると `mode: live` と保存先ファイル名が表示されます。`outputs` 内のファイルを開き、内容を読んでください。外部への投稿は行わず、人間が確認するところで終わります。途中で止めるときは `Ctrl+C` を使います。

## 仕組みを読む

流れは「候補を読む → AIが選ぶ → Markdownを保存する」です。モデルが使える道具は2つだけにしています。

| 道具 | Python側で行うこと |
| --- | --- |
| `list_candidates` | 同梱の架空候補を読む |
| `save_markdown` | 候補IDと本文を検査し、決めたoutputsフォルダーへ新規保存 |

function callingは、モデルが「この関数を、この引数で呼びたい」と返し、Python側が検査して実行する仕組みです。[公式ガイド](https://ai.google.dev/gemini-api/docs/function-calling)も参考にできます。

モデルへPythonの実行権限を渡すわけではありません。`eval` や任意コマンド実行は使わず、2つの名前だけを分岐で受け付けます。保存パスをモデルに決めさせず、候補IDからファイル名を作ります。既存ファイルの上書き、未許可ツール、範囲外の指定は停止します。

`config.json` のモデル・ツール呼出上限はそれぞれ最大3回。通常は2回ずつです。SDKのHTTP試行は1回、タイムアウトは30秒で、有料モデルへの自動切替もありません。これらは作品自身の制限で、Googleの無料クォータではありません。起動を繰り返せば利用量は累積します。

コードは `Settings` → `declarations` → `LocalTools.invoke` → `GeminiProvider` → `run_agent` の順に読むと追いやすくなっています。日本語コメントを手がかりに、まず保存部分だけを読んでみても構いません。

## 困ったとき

| 状況 | 確認するところ |
| --- | --- |
| Pythonが見つからない | Pythonの導入状態を確認し、PowerShellを開き直す |
| `UnicodeDecodeError`（cp932） | 導入コマンドの `-X utf8` を省いていないか |
| `ModuleNotFoundError` | `.venv` 内のPythonで依存を導入・実行しているか |
| `.env`が見つからない | 今いるフォルダー、絶対パス、`.env.txt`になっていないか。中身は表示しない |
| 同名ファイルがある | 保存済みの文章を読んで別名へ退避。上書きはしない |
| 401/403 | キーの有効性、対象プロジェクト、制限を本人が確認。キーを他人へ送らない |
| 429 | 利用上限などで停止。AI Studioの使用量・上限を確認し、繰り返し起動しない |
| 400/404 | 設定やモデルの提供状況を公式資料で確認。有料モデルへ勝手に切り替えない |
| 通信エラー | 回線と正規APIへの接続を確認。TLS検証を無効にしない |

[公式のエラー対処](https://ai.google.dev/gemini-api/docs/troubleshooting)も参照してください。エラーにはリクエスト形式の問題もあります。課金設定を変えれば解決すると決めつけないでください。

### テストを動かす

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

20件のテストは通信せず、実キーも使いません。保存順序、上書き防止、不正な引数、呼出上限、エラー時の停止などを確かめます。実モデルの文章品質や無料請求は、単体テストだけでは確認できません。

2026年10月31日は移動先を新しく取得した環境で、導入からmock、実際のGeminiでの保存まで確認しました。実APIの実行1回の中で、モデルへの要求2回・ツール実行2回により `task-list.md` を保存できました。2026年10月27日の過去の確認と、今回の環境・未確認の範囲は [検証記録](verification/README.md) に分けてまとめています。
