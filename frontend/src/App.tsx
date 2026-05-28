import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Database,
  ExternalLink,
  FileText,
  FolderOpen,
  History,
  Loader2,
  Search,
} from "lucide-react";

type Connection = {
  config_path: string | null;
  db_path: string | null;
  root_linking_enabled: boolean;
  mode: string;
  warnings: string[];
  roots: Record<string, string>;
  summary?: Record<string, number>;
};

type DistributionStatus = {
  enabled: boolean;
  launcher_mode: string;
  settings_path: string | null;
  shared_config_path: string | null;
  shared_db_path: string | null;
  local_cached_db_path: string | null;
  copy_policy: string | null;
  cache_fresh: boolean;
  last_copied_at_utc: string | null;
  error: string | null;
};

type StatusPayload = {
  searchdb_importable: boolean;
  searchdb_root: string;
  default_profile: {
    available: boolean;
    config_path: string;
    db_path: string;
  };
  connection: Connection;
  distribution: DistributionStatus;
};

type SearchResult = {
  rank: number;
  document_id: number;
  chunk_id: number;
  display_path: string;
  chunk_index: number;
  fts_score: number;
  metadata_score: number;
  final_score: number;
  snippet: string | null;
  ranking_reasons: string[];
  can_open_file: boolean;
  document: DocumentMeta;
};

type SearchPayload = {
  run_id: number;
  query_text: string;
  query_type: string;
  top_k: number;
  search_mode: string;
  ranking_profile: string;
  status: string;
  error_message: string | null;
  warnings: string[];
  results: SearchResult[];
};

type DocumentMeta = {
  document_id: number;
  source_root: string;
  normalized_path: string;
  display_path: string;
  archive_path: string | null;
  extension: string;
  mime_type: string | null;
  size_bytes: number;
  mtime_utc: string;
  sha256: string | null;
  is_archive_member: number;
  authority_level: number;
  manual_importance: number;
  known_noise: number;
  label_rationale: string | null;
  can_open_file?: boolean;
};

type ChunkDetail = {
  chunk_id: number;
  document_id: number;
  version_id: number;
  chunk_index: number;
  title: string | null;
  source_section: string | null;
  text_body: string;
  char_start: number | null;
  char_end: number | null;
  token_estimate: number | null;
  extraction_kind: string;
  language_hint: string | null;
  document: DocumentMeta;
};

type RunSummary = {
  run_id: number;
  query_text: string;
  query_type: string;
  top_k: number;
  ranking_profile: string;
  status: string;
  started_at_utc: string;
  finished_at_utc: string | null;
  result_count: number;
};

const queryTypes = ["spec_question", "defect_investigation", "impact_analysis", "corpus_cleanup"];
const queryTypeLabels: Record<string, string> = {
  spec_question: "仕様確認",
  defect_investigation: "不具合調査",
  impact_analysis: "影響調査",
  corpus_cleanup: "文書整理",
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

function formatScore(value: number): string {
  return value.toFixed(3);
}

function compactPath(path: string): string {
  if (path.length <= 84) {
    return path;
  }
  return `${path.slice(0, 34)}...${path.slice(-44)}`;
}

export function App() {
  const [status, setStatus] = useState<StatusPayload | null>(null);
  const [connection, setConnection] = useState<Connection | null>(null);
  const [configPath, setConfigPath] = useState("");
  const [dbPath, setDbPath] = useState("");
  const [query, setQuery] = useState("G71");
  const [queryType, setQueryType] = useState("spec_question");
  const [topK, setTopK] = useState(10);
  const [includePath, setIncludePath] = useState("");
  const [excludePath, setExcludePath] = useState("");
  const [since, setSince] = useState("");
  const [searchPayload, setSearchPayload] = useState<SearchPayload | null>(null);
  const [selected, setSelected] = useState<SearchResult | null>(null);
  const [detail, setDetail] = useState<ChunkDetail | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const allWarnings = useMemo(() => {
    return [
      ...(status?.distribution?.error ? [`配布設定: ${status.distribution.error}`] : []),
      ...(connection?.warnings ?? []),
      ...(searchPayload?.warnings ?? []),
    ].filter(Boolean);
  }, [connection, searchPayload, status]);

  useEffect(() => {
    void refreshStatus();
    void refreshRuns();
  }, []);

  async function refreshStatus() {
    const nextStatus = await api<StatusPayload>("/api/status");
    setStatus(nextStatus);
    setConnection(nextStatus.connection);
    setConfigPath(nextStatus.connection.config_path ?? nextStatus.default_profile.config_path);
    setDbPath(nextStatus.connection.db_path ?? nextStatus.default_profile.db_path);
  }

  async function refreshRuns() {
    const nextRuns = await api<RunSummary[]>("/api/runs").catch(() => []);
    setRuns(nextRuns);
  }

  async function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setMessage(null);
    try {
      const nextConnection = await api<Connection>("/api/connect", {
        method: "POST",
        body: JSON.stringify({
          config_path: configPath.trim() || null,
          db_path: dbPath.trim() || null,
        }),
      });
      setConnection(nextConnection);
      setMessage("接続しました");
      await refreshRuns();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }

  async function runSearch(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    setLoading(true);
    setMessage(null);
    try {
      const payload = await api<SearchPayload>("/api/search", {
        method: "POST",
        body: JSON.stringify({
          query,
          top_k: topK,
          query_type: queryType,
          include_path: includePath || null,
          exclude_path: excludePath || null,
          since: since || null,
        }),
      });
      setSearchPayload(payload);
      const first = payload.results[0] ?? null;
      setSelected(first);
      setDetail(null);
      if (first) {
        await loadChunk(first);
      }
      await refreshRuns();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }

  async function loadRun(runId: number) {
    setLoading(true);
    setMessage(null);
    try {
      const payload = await api<SearchPayload>(`/api/runs/${runId}`);
      setSearchPayload(payload);
      setQuery(payload.query_text);
      setQueryType(payload.query_type);
      setTopK(payload.top_k);
      const first = payload.results[0] ?? null;
      setSelected(first);
      setDetail(null);
      if (first) {
        await loadChunk(first);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }

  async function loadChunk(result: SearchResult) {
    setSelected(result);
    setMessage(null);
    try {
      const nextDetail = await api<ChunkDetail>(`/api/chunks/${result.chunk_id}`);
      setDetail(nextDetail);
    } catch (error) {
      setDetail(null);
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  async function openDocument(result: SearchResult) {
    if (!result.can_open_file) {
      return;
    }
    setMessage(null);
    try {
      await api(`/api/documents/${result.document_id}/open`, { method: "POST" });
      setMessage("ファイルを開きました");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>SearchViewer</h1>
          <p>{connection?.db_path ?? "データベース未接続"}</p>
        </div>
        <div className={`status-pill ${connection?.root_linking_enabled ? "ok" : "warn"}`}>
          <Database size={16} />
          {connection?.mode === "config" ? "Configモード" : "DBのみモード"}
        </div>
      </header>

      {allWarnings.length > 0 && (
        <section className="warning-band">
          <AlertTriangle size={18} />
          <div>{allWarnings[0]}</div>
        </section>
      )}

      {message && <section className="message-band">{message}</section>}

      <section className="workspace">
        <aside className="sidebar">
          <form className="control-section" onSubmit={connect}>
            <div className="section-title">
              <Database size={16} />
              接続
            </div>
            <label>
              Configパス
              <input value={configPath} onChange={(event) => setConfigPath(event.target.value)} />
            </label>
            <label>
              DBパス
              <input value={dbPath} onChange={(event) => setDbPath(event.target.value)} />
            </label>
            <button type="submit" disabled={loading}>
              {loading ? <Loader2 className="spin" size={16} /> : <FolderOpen size={16} />}
              接続
            </button>
            <div className="summary-grid">
              <span>文書数</span>
              <strong>{connection?.summary?.documents ?? "-"}</strong>
              <span>チャンク数</span>
              <strong>{connection?.summary?.chunks ?? "-"}</strong>
              <span>検索履歴</span>
              <strong>{connection?.summary?.retrieval_runs ?? "-"}</strong>
            </div>
            {status?.distribution?.launcher_mode === "distribution" && (
              <div className="distribution-box">
                <div>
                  <span>配布モード</span>
                  <strong>{status.distribution.enabled ? "有効" : "未設定"}</strong>
                </div>
                <div>
                  <span>共有DB</span>
                  <strong title={status.distribution.shared_db_path ?? undefined}>
                    {status.distribution.shared_db_path ? compactPath(status.distribution.shared_db_path) : "-"}
                  </strong>
                </div>
                <div>
                  <span>ローカルキャッシュ</span>
                  <strong title={status.distribution.local_cached_db_path ?? undefined}>
                    {status.distribution.local_cached_db_path
                      ? compactPath(status.distribution.local_cached_db_path)
                      : "-"}
                  </strong>
                </div>
                <div>
                  <span>最終コピー</span>
                  <strong>{status.distribution.last_copied_at_utc ?? "-"}</strong>
                </div>
              </div>
            )}
          </form>

          <form className="control-section" onSubmit={runSearch}>
            <div className="section-title">
              <Search size={16} />
              検索
            </div>
            <label>
              検索語
              <input value={query} onChange={(event) => setQuery(event.target.value)} />
            </label>
            <div className="inline-fields">
              <label>
                件数
                <input
                  min={1}
                  max={50}
                  type="number"
                  value={topK}
                  onChange={(event) => setTopK(Number(event.target.value))}
                />
              </label>
              <label>
                種別
                <select value={queryType} onChange={(event) => setQueryType(event.target.value)}>
                  {queryTypes.map((item) => (
                    <option key={item} value={item}>
                      {queryTypeLabels[item]} ({item})
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label>
              対象パス
              <input value={includePath} onChange={(event) => setIncludePath(event.target.value)} />
            </label>
            <label>
              除外パス
              <input value={excludePath} onChange={(event) => setExcludePath(event.target.value)} />
            </label>
            <label>
              更新日以降
              <input value={since} onChange={(event) => setSince(event.target.value)} placeholder="YYYY-MM-DD" />
            </label>
            <button type="submit" disabled={loading || !query.trim()}>
              {loading ? <Loader2 className="spin" size={16} /> : <Search size={16} />}
              検索
            </button>
          </form>

          <section className="control-section runs-section">
            <div className="section-title">
              <History size={16} />
              最近の検索
            </div>
            <div className="run-list">
              {runs.map((run) => (
                <button key={run.run_id} type="button" onClick={() => void loadRun(run.run_id)}>
                  <span>#{run.run_id}</span>
                  <strong>{run.query_text}</strong>
                  <small>{run.result_count}件</small>
                </button>
              ))}
            </div>
          </section>
        </aside>

        <section className="results-pane">
          <div className="pane-header">
            <div>
              <h2>{searchPayload ? `検索 #${searchPayload.run_id}` : "検索結果"}</h2>
              <p>
                {searchPayload
                  ? `${searchPayload.results.length}件 | ${searchPayload.ranking_profile}`
                  : "検索履歴が選択されていません"}
              </p>
            </div>
          </div>
          <div className="result-list">
            {(searchPayload?.results ?? []).map((result) => (
              <article
                className={`result-row ${selected?.chunk_id === result.chunk_id ? "selected" : ""}`}
                key={`${result.document_id}-${result.chunk_id}-${result.rank}`}
                onClick={() => void loadChunk(result)}
              >
                <div className="rank">{result.rank}</div>
                <div className="result-main">
                  <button
                    className={`path-link ${result.can_open_file ? "" : "disabled"}`}
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      void openDocument(result);
                    }}
                    disabled={!result.can_open_file}
                    title={result.display_path}
                  >
                    <FileText size={15} />
                    {compactPath(result.display_path)}
                    {result.can_open_file && <ExternalLink size={13} />}
                  </button>
                  <p>{result.snippet || "スニペットなし"}</p>
                  <div className="reason-list">
                    {result.ranking_reasons.map((reason) => (
                      <span key={reason}>{reason}</span>
                    ))}
                  </div>
                </div>
                <div className="score-block">
                  <strong>{formatScore(result.final_score)}</strong>
                  <span>FTS {formatScore(result.fts_score)}</span>
                  <span>メタ {formatScore(result.metadata_score)}</span>
                </div>
              </article>
            ))}
          </div>
        </section>

        <aside className="detail-pane">
          <div className="pane-header">
            <div>
              <h2>チャンク詳細</h2>
              <p>{detail?.document.display_path ?? "検索結果を選択してください"}</p>
            </div>
          </div>
          {detail ? (
            <div className="detail-content">
              <dl className="meta-grid">
                <dt>チャンク</dt>
                <dd>{detail.chunk_index}</dd>
                <dt>文書ID</dt>
                <dd>{detail.document.document_id}</dd>
                <dt>root</dt>
                <dd>{detail.document.source_root}</dd>
                <dt>更新日時</dt>
                <dd>{detail.document.mtime_utc}</dd>
                <dt>権威度</dt>
                <dd>{detail.document.authority_level}</dd>
                <dt>ノイズ</dt>
                <dd>{detail.document.known_noise}</dd>
              </dl>
              <pre>{detail.text_body}</pre>
            </div>
          ) : (
            <div className="empty-state">チャンクが選択されていません</div>
          )}
        </aside>
      </section>
    </main>
  );
}
