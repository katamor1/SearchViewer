# SearchViewer

SearchDB の SQLite 検索結果を表示する、日本語UIのローカルビューアです。
AI検索、AI packet export、外部AI API 呼び出しは含めません。

## 配布用 exe

```powershell
scripts\build_exe.ps1
```

生成物:

- `dist\SearchViewer.exe`
- `dist\SearchViewerSettings.example.yaml`

配布時は `SearchViewer.exe` と同じフォルダに `SearchViewerSettings.yaml` を置きます。
起動すると exe 内部で `127.0.0.1` の空きポートに Web アプリを立ち上げ、既定ブラウザを自動で開きます。小さな起動窓から URL コピー、ブラウザ再オープン、終了ができます。

`SearchViewerSettings.yaml` の主な項目:

```yaml
shared_config_path: "\\\\server\\share\\SearchDB\\searchdb.local.yaml"
shared_db_path: "\\\\server\\share\\SearchDB\\searchdb.sqlite3"
searchdb_working_dir: "\\\\server\\share\\SearchDB"  # config内の相対パス解決が必要な場合
local_db_name: "searchdb.sqlite3"
copy_policy: "if_source_changed"
```

- 共有DBは直接検索に使わず、起動時に `%LOCALAPPDATA%\SearchViewer\cache\searchdb.sqlite3` へコピーして使います。
- 検索履歴と retrieval results は各PCのローカルコピーに書き込まれます。
- ファイルリンクは共有 config の root から実ファイルに解決できる場合だけ有効です。
- archive member は `zip::member` を表示し、クリック時は外側の archive ファイルを開きます。

## 開発実行

```powershell
py -m pip install -e .[dev]
cd frontend
$env:npm_config_strict_ssl = "false"  # npm TLS で失敗する環境だけ
npm install
npm run build
cd ..
py -m searchviewer
```

ブラウザで `http://127.0.0.1:8765` を開きます。

## 検証

```powershell
py -m pytest -q
npm --prefix frontend run build
scripts\build_exe.ps1
dist\SearchViewer.exe --smoke --settings packaging\SearchViewerSettings.example.yaml
```

`--smoke` は GUI を出さず、静的ファイル同梱、SearchDB import、設定ファイル parse を確認します。

## 既定動作

- 開発実行で設定ファイルを指定しない場合、存在すれば `C:\Users\stell\source\repos\SearchDB\tests\.tmp\local-docs-demo\searchdb.local.yaml` を既定profileとして使います。
- SearchDB の retrieval ロジックを直接呼び、`fts5_metadata_v1`、snippet、ranking reasons、run履歴を維持します。
- DBのみ接続も許可しますが、config、readiness guard、synonyms、ファイルroot解決が無効であることをUIに表示します。
