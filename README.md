# PDF Workbench

**PDFをOCRにかけやすい領域へ分割し、外部のOCRソフトで作成した検索可能PDFを元のページ配置へ戻すためのGUIツール**です。分割位置をページごとに画面で調整できます。PDF Workbench自体はOCRを実行せず、特定のOCRエンジンを必須としません。

日本語 | [English](README.en.md)

初めて使う方は、[画像付きクイックスタート（日本語・説明用PDF付き）](docs/QUICK_START_JA.md)からお試しください。開発の背景と設計上の判断は[PDF Workbenchの開発経緯と設計思想](docs/DEVELOPMENT_BACKGROUND_JA.md)にまとめています。

## 主な機能

- PDFを開き、左側のサムネイルからページを選んで、ページごとの分割を編集します。
- 新規ページは「分割なし（1領域）」に相当するCustom splitから開始します。選択した領域を上下／左右に分け、赤い分割線をドラッグして位置を調整したり、分割線の削除・領域の統合を行ったりできます。
- 「頁全体を4分割」「分割なし（1領域）」は、後から自由に編集できるCustom splitの簡易設定です。旧来の固定式「上下2分割」「4分割」などを個別に選ぶUIではありません。
- 中央プレビューにフォーカスがある状態で⌘A（Windows/LinuxではCtrl+A）を押すと、そのページの全分割領域を選択できます。Escで複数選択を解除できます。領域の選択だけでは分割設定は変わりません。
- 領域に表示される番号でOCRへ出力する順番を確認できます。連続した番号の領域を選択して、順番を振り直すこともできます。
- 現在のページの設定を指定ページ・選択ページ・全ページへ反映できます。固定したページは、他ページからの一括設定で上書きされません。
- 左側で複数のサムネイルを選び、**選択中のページが中央にも表示されている場合**、中央で確定した手動編集の結果を、選択中の固定されていないページへ反映できます。選択しただけでは設定は変更されません。編集はUndo／Redoに対応します。
- 「自動分割」タブで、画像の余白から分割候補を探せます。現在の選択領域、現在ページ、指定範囲、選択ページに対応し、一括処理でも各ページの画像を個別に解析します。自動分割後は結果を確認し、必要な箇所を手動で修正してください。
- OCR用分割PDFと復元情報をまとめた「OCR Bundle」を作成・更新し、後から分割設定の編集を再開できます。外部OCRの結果PDFは、元のページサイズ・配置へ再構成できます。

元のPDFは、PDF Workbenchで開いて編集・書き出しを行っても変更されません。

## 動作環境とインストール

Python 3.10以降と、PyMuPDF・Pillow・PySide6が必要です。使用するOS・Pythonのバージョンに対応した依存ライブラリをインストールしてください。GitとPythonをあらかじめ用意してください。

**動作確認済み：macOS（Apple Silicon）および Windows 10 x64（Boot Camp）。Linuxは未検証です。** Windowsでは2026年9月26日にPython 3.13.15を使い、公開README記載のPowerShell手順によるインストール、GUI起動、主要な分割・Bundle操作、復元、自動テストを確認しました。Windows 11、Windows ARM64、ARM上のx64エミュレーション、Linuxは未検証です。現時点では、各OS向けのダブルクリックで起動できるアプリは配布しておらず、Pythonソースから起動します。

初回のみ、GitHubからソースコードを取得し、仮想環境へアプリ本体と必要なライブラリをインストールします。お使いのOSに対応する手順を選んでください。

### macOS（ターミナル・動作確認済み）

```bash
git clone https://github.com/brontelandscape54-ops/pdf-workbench-public.git
cd pdf-workbench-public
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
python3 -m pdf_workbench
```

最後の `python3 -m pdf_workbench` でGUIが開きます。閉じるときはウィンドウを終了してください。

### Windows（PowerShell・Windows 10 x64で動作確認済み）

```powershell
git clone https://github.com/brontelandscape54-ops/pdf-workbench-public.git
cd pdf-workbench-public
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pdf_workbench
```

`py -3` でPython 3.10以降の対応バージョンが選択される環境を想定しています。Windows用の手順では仮想環境内のPythonを直接呼び出すため、PowerShellで仮想環境を有効化する必要はありません。Windows 10 Home 64-bit（Boot Camp）とPython 3.13.15では、この手順からインストールとGUI起動を確認しています。

### 2回目以降にGUIを開く

ターミナル／PowerShellで、初回に取得した `pdf-workbench-public` フォルダへ移動し、お使いのOSに応じて以下を実行してください。**毎回のインストールは不要です。**

macOS：

```bash
./.venv/bin/python -m pdf_workbench
```

Windows（PowerShell）：

```powershell
.\.venv\Scripts\python.exe -m pdf_workbench
```

`requirements.txt` を使う場合、`python3 -m pip install -r requirements.txt` は依存ライブラリ（pytestを含む）を導入する手順であり、アプリ本体のインストールには別途 `python3 -m pip install -e .` が必要です。

## 基本の使い方

1. 「Open PDF…」から元PDFを開き、左のサムネイルで対象ページを選びます。手動編集と書き出しの設定は「手動・出力」タブにあります。
2. 中央のプレビューで領域を選び、「上下に分割（横線）」または「左右に分割（縦線）」で分割します。赤線をドラッグして、文字を切らない位置へ調整してください。必要に応じて4分割・1領域の簡易設定も使えます。
3. 中央プレビューの領域をすべて選ぶときは、中央をクリックして⌘A（Windows/LinuxはCtrl+A）を押します。領域の番号を確認します。複数領域のOCR順を変える場合は、連続した番号の領域を選び、「選択領域の順番を振り直す」で希望順にクリックします。操作は「Edit」メニューや⌘Zなどで戻せます。
4. 同じ版面のページへ手動設定を反映するには、左で対象サムネイルを複数選択し、その中の中央表示ページを編集します。「指定ページに現在の設定を反映」などの明示的なコピー操作も利用できます。固定中の他ページは一括変更の対象外です。
5. 自動判定を利用する場合は「自動分割」タブで対象と感度を指定し、結果をプレビューで確認・修正します。
6. 必要に応じて、分割境界の重なり、DPI、JPEG品質、カラー／グレースケール、元PDFの同梱の有無を設定します。新規起動時の書き出しはカラーが初期値です。
7. 「Export for OCR…」でOCR Bundleを書き出します。現行GUIでは、旧来の通常「Export PDF…」ボタンは表示していません。

ページ指定は `4,11-60/7` のような周期指定にも対応しています。固定中のページも、そのページを中央に表示して直接編集することはできます。

複数選択時の詳細な適用条件は [複数ページ編集の仕様](docs/multi-page-edit.md) を参照してください。

## OCR Bundleの作成・作業再開・復元

```text
元PDF
  ↓ PDF Workbench：「Export for OCR…」
元PDF名_ocr_bundle/
├── manifest.json
├── workspace.json
├── 元PDF名_split_for_ocr.pdf
└── README.txt
  ↓ 外部のOCRソフトで分割PDFを処理
検索可能なOCR結果PDF
  ↓ PDF Workbench：「Restore OCR Results…」
元のページ配置に戻した検索可能PDF
```

- **OCRにかける：** Bundle内の `*_split_for_ocr.pdf` を任意のOCRソフトで処理します。**ページ数やページ順を変えずに**検索可能PDFとして保存してください。
- **編集を再開する：** 「Open OCR Bundle…」でBundleのフォルダを選びます。元PDFの場所が変わっている場合は、参照するPDFを選び直します。元PDFの候補はBundle作成時のSHA-256と照合されます。古いBundleに `workspace.json` がない場合も、manifestから分割設定を読み込めますが、現在ページや固定状態などの未保存情報は復元されません。
- **既存のBundleを更新する：** 分割を編集した後、同じ保存先へ「Export for OCR…」を実行し、更新確認に同意します。PDF Workbenchが生成した分割PDFや設定ファイルは更新され、独自に追加したOCR結果PDFやメモ等は引き継がれます。ただし、**以前の分割PDFから作ったOCR結果が、更新後の分割情報に適合するとは限りません。** 分割数・配置・順序を変更した場合は、新しい分割PDFを再度OCRしてください。
- **元の配置へ戻す：** 「Restore OCR Results…」からBundleとOCR結果PDFを指定します。復元処理に元PDFそのものは不要です。外部OCRのPDFページ内容を再配置する方式で、復元時に意図的な再ラスタライズは行いません。検索可能なテキストが保持される範囲は、OCR結果と切り取り位置に左右されます。

### 復元できる条件と制約

分割後の各PDFページについて、ページ全体の一様な拡大縮小、DPI変更、再圧縮、グレースケール化などは、正規化したページ内の位置関係が保たれる場合に対応できます。一方、**OCRソフトがページの端を自動で切り取る、左右上下で異なる余白を付ける、ページを回転・任意の傾き補正をする、ページ数や順序を変える**場合、現行の復元方式には対応していません。

分割時の領域の重なりは文字切れ軽減に役立ちますが、復元時には重複のない担当領域だけを残します。分割境界をまたぐOCRテキストは切れる可能性があるため、余白で分割することを推奨します。

`manifest.json` と `workspace.json` は別々に形式管理され、現時点ではいずれもversion 1です。以前の固定分割設定は、編集時にCustom splitへ読み替えます。古いBundleを開いただけでは保存済みのmanifestを書き換えません。詳しくは [保存形式と互換性](docs/bundle-schema-migrations.md) を参照してください。

**Bundleの共有時の注意：** `workspace.json` には元PDFのローカル絶対パスが記録されます。また、設定によっては `source/original.pdf` が同梱されます。他者へ渡す前にBundleの内容を確認し、個人情報や共有権限のない資料を含めないでください。

## 開発の経緯

開発上の課題と判断理由をまとめた[開発経緯と設計思想](docs/DEVELOPMENT_BACKGROUND_JA.md)も公開しています。

[ocr-pdf-cut-to-four](https://github.com/brontelandscape54-ops/ocr-pdf-cut-to-four) は、二段組などのPDFをOCRにかけやすいよう、各ページを固定の4領域へ分割する小型のコマンドラインツールです。2026年5月に以前の分割スクリプトを再発見し、再利用可能な形へ整理しました。

PDF Workbenchは、その**「OCRに先立ってページの分割・配置を調整する」発想を出発点**とし、GUIでのページ別・任意領域の分割、外部OCR後の元配置への復元へ発展させた別プロジェクトです。旧ツールのGit履歴をそのまま継承したものではありません。固定4分割のみで足りる用途には、元のCLIも別途残しています。

## テストと現状

編集可能な状態でインストール後、`python3 -m pip install 'pytest>=8,<9'` でテスト用依存ライブラリを導入し、`python3 -m pytest` を実行できます。GUIの操作確認にはデスクトップ環境が必要です。

2026年9月22日、公開版をmacOS（Apple Silicon）の独立した仮想環境へインストールし、Python 3.10.4・PyMuPDF 1.28.2・PySide6 6.11.2・Pillow 12.3.0・pytest 8.4.2で自動テスト **99件成功（非推奨API等に関する警告5件）** を確認しました。GUIの起動も確認しています。中央プレビューの⌘Aによる全領域選択は、開発版で実機操作を確認しました。公開版でもGUIを起動し、外部OCRを通した分割・復元を実施しています。

**Windows実機確認（2026年9月26日）：** Intel MacのBoot Camp上のWindows 10 Home 64-bit、Python 3.13.15、Git 2.55.0.windows.3で、README記載のPowerShell手順から新規仮想環境を作成し、PyMuPDF 1.28.2・PySide6 6.11.2・Pillow 12.3.0を導入してGUIを起動しました。PDF読込、手動分割、自動分割、`Export for OCR…`、`Open OCR Bundle…`、`Restore OCR Results…`を実機で確認し、pytest **99件すべて成功（4.23秒）** を確認しました。今回のWindows確認では、Windows上で外部OCRを実行して新規に作成した検索可能PDFについて、復元後の検索・コピー保持までを一連で検証したものではありません。

**外部OCRを含む実機検証（同日・個別事例）：** 画像化された縦書きの機関紙『泉』第26号（昭和58年11月1日、元の4ページ）を、領域の読み順を調整して分割し、外部OCRで処理した結果をWorkbenchで4ページへ復元しました。提示された復元PDFでは紙面画像と抽出可能なテキストが残り、特に3ページ目で、前回の復元PDFでは後半から始まっていた記事が見出し・「まえがき」から始まる順へ改善していました。使用したOCRソフト名・版は未記録です。元PDF・分割PDF・OCR結果PDF・復元PDFの4点を突き合わせた文字欠落／検索位置の精密な比較、OCR精度の定量評価、他の資料・OCRソフトでの互換性検証は**未実施**です。この記事の画像・OCRテキストは公開リポジトリには収録しません。

本ツールはOCR前処理・復元のための開発中のGUIであり、ページ削除・回転・PDF結合などの汎用PDF編集機能や、アプリ内部でのOCR実行は現行の提供範囲に含みません。

## ライセンス

PDF Workbenchの自作コードは **AGPL-3.0-or-later** を適用する方針です。正式なライセンス本文は公開版の `LICENSE` を参照してください。PyMuPDF・PySide6・Pillowにはそれぞれのライセンス条件が適用されます。ライブラリの再配布・組込みを行う場合は、採用した配布形態に応じて表示・提供条件を確認してください。
