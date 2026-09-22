# OCR Bundle 保存形式とマイグレーション方針

## 互換性の基準（2026-09）

OCR Bundleの `manifest.json` は `format: "pdf-workbench-ocr-bundle"`,
`version: 1`、作業再開用の `workspace.json` は
`format: "pdf-workbench-workspace"`, `version: 1` を既存の基準とする。
アプリのバージョンや編集UIの変更だけでは、保存形式の番号を上げない。

両JSONは別々にバージョン管理する。manifestはOCR結果の再配置を担い、
workspaceは元PDFパス、現在頁、固定頁、UI設定などを担う。
manifestの座標・出力頁の対応はOCR復元との契約である。

`core/schema_migrations.py` はJSONごとに `SchemaSpec` と
`MIGRATIONS`（旧バージョン番号 → 次への変換関数）を用いる。
読込時にコピーして段階的に変換するため、古いBundleを開いた時点で
ディスク上のJSONを書き換えない。未知の将来バージョン、数字でない
バージョン、変換手順の欠落はエラーとし、推測して読まない。

## Custom splitへの移行と保存形式の変更を区別する

旧Bundleのmanifest v1では `split_mode: "four"`、
`"horizontal_2"`、`"none"`、`"custom"` が既存の有効な表現である。
現在のGUIはCustom splitを用いるが、これは**編集時の読み替え**であり、
manifest v1の定義自体の変更ではない。

`core/custom_presets.py:as_custom_settings` が、
固定分割を元の座標・重なり・OCR順を維持したCustom分割木へ変換する。
`core/workspace.py:settings_from_manifest` はこの変換を経て編集用設定を返す。
一方、OCR復元は保存済みmanifestの `pieces` をそのまま読み取る。
既存Bundleに保存されたOCR出力との対応を読み込み時に書き換えない。

## 今後保存形式を変更するときの手順

1. 実際のディスク上の変更がmanifestとworkspaceのどちらに必要か特定する。
2. 変更が必要な方の `FORMAT_VERSION` または `WORKSPACE_VERSION` を
   1だけ増やし、その形式の `MIGRATIONS[旧番号]` を実装する。
3. マイグレーションは元の辞書を改変せず、次バージョンの辞書を返す。
   復元に必要な情報・OCR順を欠落させない。
4. 移行前後の代表的な実データまたは固定fixtureをテストに残す。
   座標、OCR順、検索可能PDF復元、workspaceの固定頁と設定、
   不正なバージョンと未知の未来バージョンを検証する。
5. 新形式の書き出しと旧形式の読み込みを区別する。
   古いBundleの読み込みだけで元のファイルを上書きしない。
   更新書き出しには明示的な確認を要求し、元Bundleの保全を考慮する。

`version` を増やすだけ、または古い `version` を新しい値に
書き換えるだけではマイグレーションにならない。実際のフィールド変換と
互換性テストが必要である。
