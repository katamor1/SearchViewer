# SearchViewer

SearchDB の SQLite 検索結果を表示する、日本語UIのローカルビューアです。
AI検索、AI packet export、外部AI API 呼び出しは含めません。

## 配布用 exe

### 作成手順

ビルドは SearchViewer repo root で行います。SearchDB repo は `C:\Users\stell\source\repos\SearchDB` のように SearchViewer と同じ親フォルダに置いてください。PyInstaller spec は `..\SearchDB\src` から `searchdb` パッケージを同梱します。
SearchDB を別の場所に置く場合は、`-SearchDbSrc C:\path\to\SearchDB\src` を指定してください。

1. 前提ツールを確認します。

```powershell
py --version
npm --version
```

2. 必要なら frontend 依存を取得します。社内環境などで npm の TLS 検証に失敗する場合だけ `npm_config_strict_ssl=false` を指定します。

```powershell
cd frontend
$env:npm_config_strict_ssl = "false"  # 必要な環境だけ
npm install
cd ..
```

3. exe を作成します。

```powershell
scripts\build_exe.ps1
```

SearchDB repo が同じ親フォルダにない場合:

```powershell
scripts\build_exe.ps1 -SearchDbSrc C:\path\to\SearchDB\src
```

このスクリプトは次を順に実行します。

- repo内の `.venv-build` を作成し、そこで `py -m pip install -e .[dev]`
- `npm run build` in `frontend`
- `.venv-build\Scripts\python.exe -m PyInstaller --noconfirm packaging\searchviewer.spec`
- `packaging\SearchViewerSettings.example.yaml` を `dist` にコピー

Python / frontend 依存がすでに揃っている環境で再ビルドだけ行う場合は、次のように省略できます。

```powershell
scripts\build_exe.ps1 -SkipPythonInstall -SkipFrontendInstall
```

生成物:

- `dist\SearchViewer.exe`
- `dist\SearchViewerSettings.example.yaml`

4. smoke 確認を行います。

```powershell
dist\SearchViewer.exe --smoke --settings dist\SearchViewerSettings.example.yaml
```

実在する共有DBで起動前確認まで行う場合は、`SearchViewerSettings.yaml` を作成してからそのファイルを指定します。

```powershell
dist\SearchViewer.exe --smoke --settings path\to\SearchViewerSettings.yaml
```

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
