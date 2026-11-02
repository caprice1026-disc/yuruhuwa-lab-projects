# GPUなしのWindowsからVast.ai×ComfyUIで画像を1枚保存する

Vast.aiで借りたGPUにComfyUIを用意し、青いマグカップの画像をWindowsへ保存する教材です。ComfyUIは画像生成の処理をつないで実行するソフトです。手元のPCは接続と保存を担当するので、画像生成用のGPUは要りません。

教材の閲覧とコード取得は無料ですが、Vast.aiのGPU・ディスク・通信には料金がかかります。紹介リンクは含めていません。

## できあがるものと検証範囲

成功時は `outputs/<日時と識別子>/image.png` に768×1024のPNGが1枚できます。同じフォルダーに生成条件、受付番号、画像のSHA-256が残ります。SHA-256はファイルの内容を照合するための値です。

```text
outputs/<run-id>/
  image.png
  workflow.api.json
  job.json
  result.json
```

これは出力構成の例です。今回の青いマグカップ画像はまだ実GPUで生成していません。新規コードはWindowsのローカルテストと模擬HTTPサーバーで検証しました。参考実装には2026-10-27のRealVisXL V5.0・RTX 3090の生成成功記録がありますが、今回の手順全体の成功を示すものではありません。[検証記録](verification/README.md)で範囲を分けています。

## 一緒に動かす

### 1. 料金と終了方法を先に確認する

**画像をPCに保存してからDestroyします。Stopだけではストレージ料金が続きます。** Destroyは借りた環境と中のデータを削除する操作です。ブラウザーやPowerShellを閉じてもレンタルは終了しません。[Vast.aiの終了操作](https://docs.vast.ai/guides/instances/manage-instances)を先に開いておいてください。

料金はGPU、ストレージ、送受信の合計で、ホストごとに違います。約6.94GBのモデルに加え、実行環境の取得にも時間と通信量が必要です。生成処理の秒数だけで総額を計算しないでください。[公式料金説明](https://docs.vast.ai/guides/instances/pricing)で内訳を確認できます。

使い始める前に、時間単価・ストレージ容量と単価・送受信単価・終了時刻をメモします。スマートフォンなどで終了時刻のアラームを設定してください。この教材には予算の強制停止や自動Destroyはありません。残高や自動入金を予算上限の代わりにしないでください。

### 2. Windowsに教材を用意する

Windows 10/11のPowerShell、Python 3.10以降、OpenSSHクライアントの `ssh`・`scp`・`ssh-keygen` を使います。PowerShellはスタートメニューから開けます。

```powershell
python --version
Get-Command ssh, scp, ssh-keygen
```

不足する場合は [Python公式](https://www.python.org/downloads/windows/)と [WindowsのOpenSSH案内](https://learn.microsoft.com/windows-server/administration/openssh/openssh_install_firstuse)を参照してください。Gitがあれば次を実行します。既に同名フォルダーがあれば、新しく作った作業場所で取得してください。

```powershell
git clone https://github.com/caprice1026-disc/yuruhuwa-lab-projects.git
Set-Location yuruhuwa-lab-projects/projects/vast-comfyui-first-image
python -X utf8 generate.py plan
python -X utf8 setup_remote.py
```

Gitがなければ [作品集](https://github.com/caprice1026-disc/yuruhuwa-lab-projects)のCode → Download ZIPから取得し、展開した `projects/vast-comfyui-first-image` を開きます。エクスプローラーのアドレスバーに `powershell` と入力すると、そのフォルダーで作業できます。

上の2つのPythonコマンドは実行予定を表示するだけです。通信・GPU起動・モデル取得はしません。Windows側に追加Pythonパッケージは不要です。

### 3. アカウントとSSH公開鍵を準備する

[Vast.ai公式](https://cloud.vast.ai/)で利用条件を読み、本人が登録・メール認証・入金を行います。2026-11-02に確認した [Quickstart](https://docs.vast.ai/guides/get-started/quickstart)では最低入金額は5 USDです。入金額と今回の使用料は別です。実際の購入画面、自動入金、保存済みカードの扱いも確認してください。

SSHは遠くのPCを暗号化した通信で操作する仕組みです。専用の鍵を作る場合は、Windowsで次を実行します。既存ファイルがあると停止するので、上書きせず既存鍵の利用か別名を選んでください。

```powershell
$keyPath = Join-Path $env:USERPROFILE '.ssh/vast-first-image_ed25519'
New-Item -ItemType Directory -Force (Split-Path $keyPath) | Out-Null
if ((Test-Path $keyPath) -or (Test-Path "$keyPath.pub")) { throw '同名の鍵があります。上書きしないでください。' }
ssh-keygen -t ed25519 -f "$keyPath" -C 'vast-first-image'
Get-Content "$keyPath.pub"
```

作成時はパスフレーズを設定します。Vast.aiのKeysに登録するのは末尾が `.pub` の公開鍵だけです。拡張子のない秘密鍵を、GPU側・チャット・GitHubへ送らないでください。鍵はGPUを借りる前に登録します。[公式SSH手順](https://docs.vast.ai/guides/instances/connect/ssh)に詳細があります。この教材ではVast.ai APIキーを使いません。

### 4. GPUを1台借りる

最初にTemplatesで実行環境を保存し、次にSearchでGPUを探します。[公式Quickstart](https://docs.vast.ai/guides/get-started/quickstart)もこの順序で案内しています。

**Templates：テンプレートを作成・保存する**

作成・編集画面では次の項目を設定します。公開テンプレートにする必要はありません。

| 設定 | 値 |
| --- | --- |
| Image Path:Tag | `pytorch/pytorch:2.9.1-cuda12.8-cudnn9-runtime` |
| Launch Mode | `Interactive shell server, SSH` |
| On-start Script | 空欄 |
| 追加の公開ポート | 8188を追加しない。ComfyUIにはSSHトンネルで接続 |

`Create & Use` で保存してSearchへ進みます。既存の自分のテンプレートを編集した場合は `Save` で保存し、Searchでそのテンプレートを選んでください。[設定名と保存ボタンの説明](https://docs.vast.ai/guides/templates/template-settings)

**Search：GPUとレンタル条件を設定する**

Searchの上部・左側の条件欄で、次の値を指定します。選択中のテンプレートも確認してください。

| 検索・レンタル条件 | 値 |
| --- | --- |
| GPUの種類・メモリ・台数 | RTX 3090、24GB、1台 |
| CPUアーキテクチャ | x86_64 / AMD64 |
| ディスク容量のスライダー | 64GB。導入開始時に空き30GiB以上が必要 |
| レンタル方式 | On-demand |

候補のホスト情報で、CPUと対応CUDAバージョンを確認します。必要なのはCUDA 12.8以上に対応するホストです。公式の項目名 `cuda_vers` はホストのドライバーが対応する最大CUDAバージョンを指し、テンプレートのイメージ名とは別の情報です。対応バージョンを画面で確認できない候補は借りずに、公式案内やサポートで確かめてください。[検索項目の定義](https://docs.vast.ai/cli/reference/search-instances)

RTX 3090は過去の検証構成に合わせた選択で、最安・最小必要VRAMという意味ではありません。通信速度とホストの信頼性表示も確認します。別モデルや複数GPUへ自動で切り替える機能はありません。容量は作成後に変更できないため、Rent前に64GBになっているか見直してください。

**Searchの候補カード：料金を確認してRentする**

候補カードの価格にマウスを重ね、GPU・ストレージ・送受信の内訳を確認します。単価と終了予定を記録し、予算に合う候補だけRentします。予算に合わなければ、その日は借りずに終了して構いません。[候補カードとディスク設定の説明](https://docs.vast.ai/guides/instances/choosing/find-and-rent)

**Instances：対象IDとSSH接続情報を確認する**

起動後はInstancesで対象IDを控え、対象カードのSSHアイコン、または `Open Terminal Access` を開きます。そこに表示されたSSHコマンドからホスト・ポート・ユーザー名を読み取ります。準備中に重ねてRentを押すと、別のインスタンスが増えるので待ってください。[SSH情報の表示場所](https://docs.vast.ai/guides/instances/connect/ssh)

### 5. SSHで接続し、ComfyUIを用意する

Windowsの同じPowerShellで実行します。`Read-Host` は画面に出た値を入力するためのコマンドです。ポートは例の数字を使わず、対象インスタンスのSSH接続欄から読み取ってください。

```powershell
$keyPath = Join-Path $env:USERPROFILE '.ssh/vast-first-image_ed25519'
$sshHost = Read-Host 'Vast.aiに表示されたSSHホスト'
$sshPort = [int](Read-Host 'Vast.aiに表示されたSSHポート')
$sshUser = Read-Host 'Vast.aiに表示されたユーザー名（通常root）'
scp -i "$keyPath" -P $sshPort ./setup_remote.py ./model.json "${sshUser}@${sshHost}:/tmp/"
if ($LASTEXITCODE -ne 0) { throw '転送に失敗しました。接続情報を確認してください。' }
ssh -i "$keyPath" -p $sshPort -o ExitOnForwardFailure=yes -L 127.0.0.1:8188:127.0.0.1:8188 "${sshUser}@${sshHost}"
```

初回は接続先のホスト鍵を確認する表示が出ます。対象ホストとポートが管理画面の値と一致するか確かめ、信頼できる方法で得たフィンガープリントがあれば照合してください。ホスト鍵変更の警告は自動承認せず調べます。`StrictHostKeyChecking=no` で検査を無効にしないでください。

接続後はLinuxのコマンド画面です。ここから下はGPU側で実行します。`git --version` が失敗した場合だけ、次の `apt-get` 2行でGitを用意します。パッケージ取得には通信が発生します。

```bash
nvidia-smi
python --version
git --version
```

```bash
apt-get update
apt-get install -y git
```

GPUとPythonが想定どおりなら、次を実行します。ここで初めてComfyUIと約6.94GBのモデルをダウンロードします。

```bash
python /tmp/setup_remote.py --install
```

`Installation complete` が出たら、GPU側でComfyUIを起動します。

```bash
cd /workspace/vast-first-image/ComfyUI
/workspace/vast-first-image/.venv/bin/python main.py --listen 127.0.0.1 --port 8188 --disable-auto-launch
```

このSSH画面は開いたままにします。接続用のトンネルはWindowsの8188番とGPU側の8188番をつなぐ通路です。ComfyUIのポートをインターネットに直接公開しません。認証情報や個人資料をGPUへ置く必要はありません。

### 6. Windowsから1枚生成して保存する

SSHの画面は開いたまま、**Windowsで別のPowerShell**を開いてください。エクスプローラーで教材の `projects/vast-comfyui-first-image` を開き、アドレスバーに `powershell` と入力すると、そのフォルダーで新しい画面を開けます。GPU側のLinux画面には入力しません。

まずComfyUIの起動を確認します。次はSSHトンネル越しに `GET /system_stats` を読み、最大120秒待つコマンドです。生成依頼は送りません。

```powershell
python -X utf8 generate.py status --wait-seconds 120
```

成功時の表示例です。GPU名は接続先によって変わります。この例は説明用で、今回の実GPU実行結果ではありません。

```json
{
  "status": "ready",
  "endpoint": "/system_stats",
  "cuda_devices": ["cuda:0 NVIDIA GeForce RTX 3090"],
  "generation_submitted": false
}
```

`ready` と借りたGPU名を確認できたら、同じWindowsのPowerShellで次を実行します。起動確認だけではモデルの読み込みや画像生成の成功までは分かりません。時間切れやエラーなら生成に進まず、SSH画面のログ、トンネル、終了予定を確認してください。再確認には `status` を使えます。[ComfyUIの読み取りAPI](https://docs.comfy.org/development/comfyui-server/comms_routes)

```powershell
python -X utf8 generate.py generate
```

`prompt_id` は生成依頼の受付番号です。`Saved:` が出たら、そのパスの `image.png` をエクスプローラーから開き、画像が表示されることを確認します。PNGの構造・寸法・チェックサムはコードで検査しますが、意図した絵かどうかは人が確認します。青いマグカップやロゴなしの指定への追従は保証されません。

保存先を変える場合は、次のように指定できます。これも実行すれば新しい1枚を生成します。

```powershell
python -X utf8 generate.py generate --output-dir "$env:USERPROFILE/Pictures/VastImages"
```

結果待ちは既定で10分です。タイムアウト・Ctrl+C・通信切断はGPUや遠隔ジョブを停止する機能ではありません。受付後に失敗した場合は、同じコマンドをすぐに再実行せず、次の「困ったとき」を確認してください。

### 7. Destroyして終了を確認する

1. `image.png` がWindowsにあり、開けることを確認します。生成条件も残したければ、その実行フォルダーを保管してください。
2. Vast.aiのInstancesで控えたIDと一致するカードを開き、Destroyのごみ箱ボタンを押します。削除する対象を確認して確定してください。ほかの作業のGPUを選ばないでください。
3. ページを更新し、対象IDが稼働中・停止中の一覧から消えたことを確認します。表示が不明、Offline、削除失敗なら終了済みとは扱わず、状態を再確認し、解決しなければVast.aiのサポートへ連絡します。
4. BillingのChargesで該当期間と内訳を確認し、時刻と金額を手元に記録します。表示の反映を待って再確認してください。独立したVolumeなどを作った場合は、その請求も別途確認します。この教材では追加Volumeを作りません。

[料金明細の公式案内](https://docs.vast.ai/guides/reference/billing)では、入金履歴と使用料の明細が分かれています。入金額や残高差だけを1枚の生成費用と見なさず、[費用記録用CSV](samples/cost-record.csv)をコピーして使ってください。個人情報を含む明細はGitへ入れません。

## 仕組みとファイル

`generate.py generate` は標準ComfyUI APIへ1回だけ依頼し、履歴の成功を待ち、画像をWindowsへ取得します。GPUの契約や削除には触りません。[ComfyUIのAPI資料](https://docs.comfy.org/development/comfyui-server/comms_routes)に `/system_stats`・`/prompt`・`/history`・`/queue`・`/view` の役割があります。

| ファイル | 役割 |
| --- | --- |
| `workflow.api.json` | 追加ノードを使わない7ノードの処理。画像1枚、seed 42、32 steps |
| `model.json` | RealVisXL V5.0の配布先・固定revision・サイズ・SHA-256 |
| `setup_remote.py` | 専用Linuxコンテナの構築。既存インストールの上書きを拒否 |
| `generate.py` | 起動・履歴の読み取り確認、1回の生成依頼とPNG保存。HTTPリダイレクトとプロキシ経由通信を拒否 |
| `tests/` | GPU不要のテスト。成功、失敗、タイムアウト、破損画像などを検査 |

ComfyUIのcommitとモデルのrevisionを固定しています。Dockerはタグ指定で、Python依存関係すべての完全固定ではありません。将来の取得先・依存パッケージ・ホストの変更で手順が動かなくなる可能性があります。

## 困ったとき

| 状況 | 確認・対処 |
| --- | --- |
| `python` / `ssh` がない | 手順2の導入を完了し、PowerShellを開き直す |
| SSHが拒否される | 対象ID、ホスト、ポート、ユーザー、指定した秘密鍵と登録公開鍵の対応を確認 |
| 8188番が使われている | 既存アプリを確認。別のローカル番号ならSSHの左側を `127.0.0.1:8189` にし、`status`・`history`・`generate` の各コマンドに `--port 8189` を指定 |
| インストールが途中で止まる | エラーを確認。既存フォルダーは自動削除・上書きしない。予算内に直せなければDestroyして終了 |
| `SHA-256 mismatch` | 未完了の `.part` は読み込まれない。検査を省略せず、配布元と通信を確認 |
| メモリ不足・生成エラー | GPU側のログを確認。自動で大きなGPUを借りない。原因が分からなければDestroy |
| `Saved:` が出ない | SSH画面とComfyUIの状態を確認。受付番号があれば履歴を調べ、重複依頼を避ける |

### 受付番号から、待つか回収するかを判断する

SSHとComfyUIの画面を開いたまま、別のWindows PowerShellを教材フォルダーで開きます。まず上の `status` コマンドで接続を確認してください。失敗した実行で表示された `Run folder:` のフォルダーをエクスプローラーで開き、その中の `job.json` のパスをコピーします。別の実行の受付番号と取り違えないでください。

```powershell
$jobFile = Read-Host '今回の実行フォルダーにあるjob.jsonのフルパス（前後の引用符は外す）'
python -X utf8 generate.py history --job-file "$jobFile"
```

このコマンドは `job.json` の `prompt_id` を使い、`GET /history/<prompt_id>` を取得します。完了履歴がない場合は `GET /queue` も読みます。生成依頼、履歴削除、画像回収、Destroyは行いません。表示される `status` で次の行動を選びます。

| status | 次にすること |
| --- | --- |
| `running` / `queued` | 実行中／順番待ち。予算と終了予定に余裕があれば待ち、同じ `history` コマンドで再確認する |
| `succeeded` | GPU側の生成は成功。`images` に出たファイルを、次の手順でWindowsへ回収して開く |
| `failed` | 生成エラー。SSH画面のログを確認し、回収できる画像があるか確認する。今回は終えるならDestroy |
| `unknown` | 履歴とキューで確認できない。完了直後の読み取りのずれ、再起動、履歴消失などでも起こり得るため、未受付とは断定しない。ログと出力フォルダーを確認し、生成を再送しない |

`job.json` がない場合も、通信切断で受付結果を受け取れなかった可能性があります。生成を重ねず、SSH画面のログと出力フォルダーを確認してください。原因を調べ続けると料金は増えます。終了予定に達したら、回収できない画像があることを理解したうえでDestroyして終了します。

### 別のWindows PowerShellで画像を回収する

画像はGPU側の `/workspace/vast-first-image/ComfyUI/output/` にも保存されます。同じインスタンスが残っていれば、次のコマンドで出力フォルダーをコピーできます。**SSHでLinuxに接続している画面では実行しません。** Windowsで新しいPowerShellを教材フォルダーに開き、次の4変数を設定し直してください。新しい画面には前の画面の変数は引き継がれません。

Vast.aiのInstancesで同じ対象IDのSSH接続情報を開き、その値を入力します。秘密鍵の名前を変えて作成した場合は `$keyPath` も合わせてください。

```powershell
$keyPath = Join-Path $env:USERPROFILE '.ssh/vast-first-image_ed25519'
$sshHost = Read-Host '同じ対象インスタンスのSSHホスト'
$sshPort = [int](Read-Host '同じ対象インスタンスのSSHポート')
$sshUser = Read-Host '同じ対象インスタンスのユーザー名（通常root）'
New-Item -ItemType Directory -Force ./outputs/recovered | Out-Null
scp -i "$keyPath" -P $sshPort -r "${sshUser}@${sshHost}:/workspace/vast-first-image/ComfyUI/output" ./outputs/recovered/
if ($LASTEXITCODE -ne 0) { throw '回収に失敗しました。保存完了と判断せず接続情報と出力を確認してください。' }
```

`outputs/recovered/output/` のPNGを開いて確認し、手順7のDestroyへ進みます。まだ画像ができていない場合や、費用上限を優先して生成を中断する場合は、回収できないことを理解したうえで対象GPUをDestroyしてください。

## モデルと出典

RealVisXL V5.0の [作者ページ](https://huggingface.co/SG161222/RealVisXL_V5.0)はOpenRAIL++を表示しています。[SDXLのライセンス原文](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/blob/main/LICENSE.md)には用途制限と配布条件があります。利用・公開・商用利用の前に、配布元の最新条件と出力の権利を確認してください。重みのダウンロードが無料であることは、無条件の利用許可を意味しません。モデル本体や作者の画像は同梱していません。

参考実装と変更内容は [出典記録](NOTICE.md)、実測の出典と未検証範囲は [検証記録](verification/README.md)にあります。Museからの自動起動、画像回収、自動解放、再開処理は別の題材です。この教材だけで手動の終了確認まで進められるようにしています。

ローカルテストは次のコマンドで実行できます。

```powershell
python -X utf8 -m unittest discover -s tests -v
```
