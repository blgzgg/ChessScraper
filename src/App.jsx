import { useState, useEffect, useRef, useMemo } from 'react'
import chessLogo from './assets/ChessLogo.png'
import chessLogoRotate from './assets/ChessLogo-Rotate.png'
import './App.css'

const API_BASE = "http://127.0.0.1:5000"

// Empty filter state — used both as the React initial value and as the
// "no filters applied" reference when comparing applied vs draft filters.
const EMPTY_FILTERS = { dateFrom: "", dateTo: "", opponent: "", result: "", color: "" }

function App() {
  const [input, setInput] = useState('')
  const [graphURL, setGraphURL] = useState(null)
  const [weightedGraphURL, setWeightedGraphURL] = useState(null)
  const [survivalGraphURL, setSurvivalGraphURL] = useState(null)
  const [stats, setStats] = useState(null)
  const [pieceStats, setPieceStats] = useState(null)
  const [opponentsList, setOpponentsList] = useState([])
  const [appliedFilters, setAppliedFilters] = useState(EMPTY_FILTERS)
  const [refetching, setRefetching] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [progress, setProgress] = useState(null)
  // progress shape: { stage, current, total, message } | null

  const eventSourceRef = useRef(null)
  // Track the username we last successfully searched for, so filter-driven
  // refetches can use it without depending on whatever's in the input box now.
  const searchedUsernameRef = useRef("")

  // -------------------------------------------------------------------
  // Fetch the opponents list for the autocomplete. Optional filters
  // narrow the result so the dropdown reflects whichever filters are
  // currently applied to the graphs (faceted search style).
  // -------------------------------------------------------------------
  const fetchOpponents = async (username, filters) => {
    const res = await fetch(`${API_BASE}/opponents`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username,
        date_from: filters.dateFrom,
        date_to:   filters.dateTo,
        result:    filters.result,
        color:     filters.color,
        // NB: opponent filter intentionally excluded so the dropdown
        // shows alternatives the user could pivot to
      }),
    })
    if (!res.ok) throw new Error("Failed to fetch opponents")
    const payload = await res.json()
    setOpponentsList(payload.opponents || [])
  }

  // -------------------------------------------------------------------
  // Fetch the two KDR graphs (filtered if filters are non-empty)
  // -------------------------------------------------------------------
  const fetchGraphs = async (username, filters) => {
    const body = JSON.stringify({
      username,
      date_from: filters.dateFrom,
      date_to:   filters.dateTo,
      opponent:  filters.opponent,
      result:    filters.result,
      color:     filters.color,
    })

    const [graphRes, weightedRes, survivalRes] = await Promise.all([
      fetch(`${API_BASE}/generate_plotly_graph`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      }),
      fetch(`${API_BASE}/generate_weighted_plotly_graph`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      }),
      fetch(`${API_BASE}/generate_survival_plotly_graph`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      }),
    ])

    if (!graphRes.ok)    throw new Error("Failed to fetch plotly graph")
    if (!weightedRes.ok) throw new Error("Failed to fetch weighted plotly graph")
    if (!survivalRes.ok) throw new Error("Failed to fetch survival plotly graph")

    const [blob, weightedBlob, survivalBlob] = await Promise.all([
      graphRes.blob(),
      weightedRes.blob(),
      survivalRes.blob(),
    ])
    const htmlURL     = URL.createObjectURL(blob)
    const weightedURL = URL.createObjectURL(weightedBlob)
    const survivalURL = URL.createObjectURL(survivalBlob)

    setGraphURL(prev => {
      if (prev) URL.revokeObjectURL(prev)
      return htmlURL
    })
    setWeightedGraphURL(prev => {
      if (prev) URL.revokeObjectURL(prev)
      return weightedURL
    })
    setSurvivalGraphURL(prev => {
      if (prev) URL.revokeObjectURL(prev)
      return survivalURL
    })
  }

  // -------------------------------------------------------------------
  // Apply / clear filters — refetches graphs but leaves stats + piece
  // board untouched (they reflect lifetime data, not filtered).
  // -------------------------------------------------------------------
  const handleApplyFilters = async (newFilters) => {
    const username = searchedUsernameRef.current
    if (!username) return
    setRefetching(true)
    setError('')
    try {
      await fetchGraphs(username, newFilters)
      setAppliedFilters(newFilters)
    } catch (err) {
      console.error(err)
      setError(err.message || "Failed to apply filters")
    } finally {
      setRefetching(false)
    }
  }

  const handleClearFilters = () => handleApplyFilters(EMPTY_FILTERS)

  // -------------------------------------------------------------------
  // Initial search — runs the SSE parse, then fetches everything.
  // -------------------------------------------------------------------
  const handleSubmit = (e) => {
    e.preventDefault()
    if (!input.trim()) return

    setLoading(true)
    setError('')
    setStats(null)
    setPieceStats(null)
    setOpponentsList([])
    setAppliedFilters(EMPTY_FILTERS)   // new search → reset filter state
    setProgress({ stage: "init", current: 0, total: 0, message: "Starting…" })

    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }

    const username = input.trim()
    searchedUsernameRef.current = username
    const es = new EventSource(`${API_BASE}/parse_progress?username=${encodeURIComponent(username)}`)
    eventSourceRef.current = es

    es.addEventListener("progress", (evt) => {
      try {
        setProgress(JSON.parse(evt.data))
      } catch (err) {
        console.error("Bad progress payload:", err)
      }
    })

    es.addEventListener("done", async (evt) => {
      try {
        setProgress(JSON.parse(evt.data))
      } catch { /* ignore */ }

      es.close()
      eventSourceRef.current = null

      try {
        // Graphs (initial, no filters yet)
        await fetchGraphs(username, EMPTY_FILTERS)

        // Stats + piece board (lifetime — never filtered) plus the initial
        // unfiltered opponents list, all in parallel.
        const [statsRes, pieceRes] = await Promise.all([
          fetch(`${API_BASE}/player_stats`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username }),
          }),
          fetch(`${API_BASE}/piece_stats`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username }),
          }),
          fetchOpponents(username, EMPTY_FILTERS),
        ])
        if (!statsRes.ok)  throw new Error("Failed to fetch player stats")
        if (!pieceRes.ok)  throw new Error("Failed to fetch piece stats")

        setStats(await statsRes.json())
        setPieceStats((await pieceRes.json()).piece_stats || {})
      } catch (err) {
        console.error(err)
        setError(err.message || "Failed to load results")
      } finally {
        setLoading(false)
      }
    })

    es.addEventListener("error", (evt) => {
      let message = "Connection lost while parsing"
      if (evt.data) {
        try {
          message = JSON.parse(evt.data).message || message
        } catch { /* ignore */ }
      }
      setError(message)
      es.close()
      eventSourceRef.current = null
      setLoading(false)
    })
  }

  // Cleanup on unmount: close stream + revoke any blob URLs
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) eventSourceRef.current.close()
      if (graphURL) URL.revokeObjectURL(graphURL)
      if (weightedGraphURL) URL.revokeObjectURL(weightedGraphURL)
      if (survivalGraphURL) URL.revokeObjectURL(survivalGraphURL)
    }
  }, [graphURL, weightedGraphURL, survivalGraphURL])

  // Refetch the opponents autocomplete whenever the applied filters change,
  // so the dropdown narrows to opponents matching the current view. Skipped
  // on initial mount (before any search has happened) since the opponent
  // filter itself isn't part of the dependency, and the graphs/opponents
  // are co-updated inside handleApplyFilters anyway — but for date/result/
  // color changes we do want a fresh list.
  useEffect(() => {
    const username = searchedUsernameRef.current
    if (!username) return
    fetchOpponents(username, appliedFilters).catch((err) => {
      console.error("Failed to refresh opponents list:", err)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appliedFilters])

  return (
    <div className="app-container">
      {/* Header */}
      <header className="header">
        <h1>ChessScraper</h1>
        <img id="chesslogorotate" src={chessLogoRotate} width="30" height="30" alt="ChessScraper Logo" style={{ margin: 'auto 0' }} />
      </header>

      {/* Content Box */}
      <div className="content-box">
        <img id="chesslogo" src={chessLogo} width="300" alt="ChessScraper Logo" />
        Welcome to ChessScraper

        {/* Input Area */}
        <form className="input-area" onSubmit={handleSubmit}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Enter Chess.com Username..."
          />
          <button type="submit" disabled={loading}>
            {loading ? "Parsing…" : "Submit"}
          </button>
        </form>
        {error && <p className="error-text">{error}</p>}

        {/* Progress bar — visible while parsing */}
        {loading && progress && <ProgressBar progress={progress} />}
      </div>

      {/* Dynamic Area */}
      <div className="content-box">
        <div className="dynamic-area">

          {/* Stats Overview Card (lifetime — not affected by filters) */}
          {stats && <StatsCard stats={stats} />}

          {/* Per-piece stats board (lifetime) */}
          {pieceStats && Object.keys(pieceStats).length > 0 && (
            <PieceBoard pieceStats={pieceStats} />
          )}

          {/* Filter bar — only shown once we have graphs to filter */}
          {graphURL && (
            <FilterBar
              appliedFilters={appliedFilters}
              opponentsList={opponentsList}
              onApply={handleApplyFilters}
              onClear={handleClearFilters}
              busy={refetching}
            />
          )}

          {/* KDR Graph */}
          {graphURL ? (
            <div className={`graph-card ${refetching ? "graph-card-busy" : ""}`}>
              <object
                data={graphURL}
                type="text/html"
                style={{ width: '100%', height: '420px', border: 'none' }}
              >
                <img src={graphURL} alt="KDR Graph" style={{ maxWidth: '100%' }} />
              </object>
            </div>
          ) : (
            !stats && !loading && <p className="placeholder">No data yet</p>
          )}

          {/* Weighted KDR Graph */}
          {weightedGraphURL && (
            <div className={`graph-card ${refetching ? "graph-card-busy" : ""}`}>
              <object
                data={weightedGraphURL}
                type="text/html"
                style={{ width: '100%', height: '420px', border: 'none' }}
              >
                <img src={weightedGraphURL} alt="Weighted KDR Graph" style={{ maxWidth: '100%' }} />
              </object>
            </div>
          )}

          {/* Survival Rate Graph */}
          {survivalGraphURL && (
            <div className={`graph-card ${refetching ? "graph-card-busy" : ""}`}>
              <object
                data={survivalGraphURL}
                type="text/html"
                style={{ width: '100%', height: '420px', border: 'none' }}
              >
                <img src={survivalGraphURL} alt="Survival Rate Graph" style={{ maxWidth: '100%' }} />
              </object>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}


/* ------------------------------------------------------------------ */
/* Filter bar                                                          */
/* ------------------------------------------------------------------ */

function FilterBar({ appliedFilters, opponentsList, onApply, onClear, busy }) {
  // Local "draft" state — mirrors what the user is typing. Only applied
  // when they click Apply, so we don't refetch on every keystroke.
  const [draft, setDraft] = useState(appliedFilters)
  const [expanded, setExpanded] = useState(false)

  // Keep draft in sync if applied filters change externally (e.g. after
  // a fresh search resets to empty)
  useEffect(() => { setDraft(appliedFilters) }, [appliedFilters])

  const hasActiveFilter =
    !!appliedFilters.dateFrom ||
    !!appliedFilters.dateTo   ||
    !!appliedFilters.opponent ||
    !!appliedFilters.result   ||
    !!appliedFilters.color

  const draftDirty =
    draft.dateFrom !== appliedFilters.dateFrom ||
    draft.dateTo   !== appliedFilters.dateTo   ||
    draft.opponent !== appliedFilters.opponent ||
    draft.result   !== appliedFilters.result   ||
    draft.color    !== appliedFilters.color

  const handleSubmit = (e) => {
    e.preventDefault()
    onApply(draft)
  }

  return (
    <div className="filter-bar">
      <div className="filter-bar-header">
        <button
          type="button"
          className="filter-toggle"
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
        >
          <span className="filter-toggle-icon">{expanded ? "▾" : "▸"}</span>
          Filters
          {hasActiveFilter && <span className="filter-active-dot" aria-label="filters active" />}
        </button>

        {/* Compact summary of active filters when collapsed */}
        {!expanded && hasActiveFilter && (
          <div className="filter-summary">
            {appliedFilters.dateFrom && <span className="filter-chip">From {appliedFilters.dateFrom}</span>}
            {appliedFilters.dateTo   && <span className="filter-chip">To {appliedFilters.dateTo}</span>}
            {appliedFilters.opponent && <span className="filter-chip">vs {appliedFilters.opponent}</span>}
            {appliedFilters.result   && <span className="filter-chip">{titleCase(appliedFilters.result)}s</span>}
            {appliedFilters.color    && <span className="filter-chip">As {titleCase(appliedFilters.color)}</span>}
            <button type="button" className="filter-clear-inline" onClick={onClear} disabled={busy}>
              Clear
            </button>
          </div>
        )}
      </div>

      {expanded && (
        <form className="filter-form" onSubmit={handleSubmit}>
          <div className="filter-field">
            <label htmlFor="filter-date-from">From</label>
            <input
              id="filter-date-from"
              type="date"
              value={draft.dateFrom}
              onChange={(e) => setDraft({ ...draft, dateFrom: e.target.value })}
              max={draft.dateTo || undefined}
            />
          </div>

          <div className="filter-field">
            <label htmlFor="filter-date-to">To</label>
            <input
              id="filter-date-to"
              type="date"
              value={draft.dateTo}
              onChange={(e) => setDraft({ ...draft, dateTo: e.target.value })}
              min={draft.dateFrom || undefined}
            />
          </div>

          <div className="filter-field filter-field-grow">
            <label htmlFor="filter-opponent">Opponent</label>
            <input
              id="filter-opponent"
              type="text"
              list="opponent-suggestions"
              placeholder="Username (partial match)"
              value={draft.opponent}
              onChange={(e) => setDraft({ ...draft, opponent: e.target.value })}
            />
            {/* The browser-native <datalist> shows the most-frequently-played
                opponents as type-ahead suggestions, but typing anything else
                still works since the field accepts free text */}
            <datalist id="opponent-suggestions">
              {opponentsList.slice(0, 100).map((o) => (
                <option key={o.name} value={o.name}>
                  {o.games} game{o.games === 1 ? "" : "s"}
                </option>
              ))}
            </datalist>
          </div>

          <div className="filter-field">
            <label htmlFor="filter-result">Result</label>
            <select
              id="filter-result"
              value={draft.result}
              onChange={(e) => setDraft({ ...draft, result: e.target.value })}
            >
              <option value="">Any</option>
              <option value="win">Wins</option>
              <option value="loss">Losses</option>
              <option value="draw">Draws</option>
            </select>
          </div>

          <div className="filter-field">
            <label htmlFor="filter-color">Color</label>
            <select
              id="filter-color"
              value={draft.color}
              onChange={(e) => setDraft({ ...draft, color: e.target.value })}
            >
              <option value="">Any</option>
              <option value="white">White</option>
              <option value="black">Black</option>
            </select>
          </div>

          <div className="filter-actions">
            <button
              type="submit"
              className="filter-apply"
              disabled={busy || !draftDirty}
            >
              {busy ? "Applying…" : "Apply"}
            </button>
            <button
              type="button"
              className="filter-clear"
              onClick={onClear}
              disabled={busy || !hasActiveFilter}
            >
              Clear
            </button>
          </div>
        </form>
      )}
    </div>
  )
}


/* ------------------------------------------------------------------ */
/* Progress bar                                                       */
/* ------------------------------------------------------------------ */

function ProgressBar({ progress }) {
  const { stage, current, total, message } = progress

  const isParsing = stage === "parsing" && total > 0
  const pct = isParsing ? Math.min(100, Math.round((current / total) * 100)) : 0

  return (
    <div className="progress-wrapper">
      <div className="progress-meta">
        <span className="progress-message">
          {message || stageLabel(stage)}
        </span>
        {isParsing && (
          <span className="progress-counter">
            {current} / {total}  ·  {pct}%
          </span>
        )}
      </div>
      <div className={`progress-track ${isParsing ? "" : "indeterminate"}`}>
        <div
          className="progress-fill"
          style={isParsing ? { width: `${pct}%` } : undefined}
        />
      </div>
    </div>
  )
}

function stageLabel(stage) {
  switch (stage) {
    case "init":              return "Initializing…"
    case "fetching_archives": return "Fetching archive list…"
    case "fetching_games":    return "Downloading games…"
    case "parsing":           return "Parsing games…"
    case "done":              return "Finished"
    default:                  return "Working…"
  }
}

function titleCase(s) {
  if (!s) return ""
  return s.charAt(0).toUpperCase() + s.slice(1)
}


/* ------------------------------------------------------------------ */
/* Stats overview card                                                 */
/* ------------------------------------------------------------------ */

function StatsCard({ stats }) {
  const {
    name,
    profile_pic_url,
    profile_url,
    total_captures,
    total_deaths,
    total_games,
    current_kdr,
    current_elo,
    weighted_kdr,
  } = stats

  return (
    <div className="stats-card">
      <a
        className="stats-profile-link"
        href={profile_url}
        target="_blank"
        rel="noopener noreferrer"
        title="View profile on Chess.com"
      >
        <h2 className="stats-name">
          {name}
          <span className="stats-external-icon" aria-hidden="true">↗</span>
        </h2>

        {profile_pic_url ? (
          <img
            className="stats-avatar"
            src={profile_pic_url}
            alt={`${name}'s avatar`}
          />
        ) : (
          <div className="stats-avatar stats-avatar-fallback">
            {name?.[0]?.toUpperCase() ?? "?"}
          </div>
        )}
      </a>

      <ul className="stats-list">
        <li>
          <span className="stats-label">Current ELO</span>
          <span className="stats-value">{current_elo}</span>
        </li>
        <li>
          <span className="stats-label">Current KDR</span>
          <span className="stats-value">
            {Number(current_kdr).toFixed(2)}
          </span>
        </li>
        <li>
          <span className="stats-label">
            Weighted KDR
            <InfoIcon><WeightedKdrInfo /></InfoIcon>
          </span>
          <span className="stats-value">
            {Number(weighted_kdr ?? 0).toFixed(2)}
          </span>
        </li>
        <li>
          <span className="stats-label">Total Games</span>
          <span className="stats-value">{total_games}</span>
        </li>
        <li>
          <span className="stats-label">Total Captures</span>
          <span className="stats-value">{total_captures}</span>
        </li>
        <li>
          <span className="stats-label">Total Deaths</span>
          <span className="stats-value">{total_deaths}</span>
        </li>
      </ul>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Per-piece stats board                                               */
/* ------------------------------------------------------------------ */

const PIECE_INFO = {
  1:  { glyph: "♖", name: "Rook (a1)",   value: 5, color: "white" },
  2:  { glyph: "♘", name: "Knight (b1)", value: 3, color: "white" },
  3:  { glyph: "♗", name: "Bishop (c1)", value: 3, color: "white" },
  4:  { glyph: "♕", name: "Queen (d1)",  value: 9, color: "white" },
  5:  { glyph: "♔", name: "King (e1)",   value: 0, color: "white" },
  6:  { glyph: "♗", name: "Bishop (f1)", value: 3, color: "white" },
  7:  { glyph: "♘", name: "Knight (g1)", value: 3, color: "white" },
  8:  { glyph: "♖", name: "Rook (h1)",   value: 5, color: "white" },
  9:  { glyph: "♙", name: "Pawn (a2)", value: 1, color: "white" },
  10: { glyph: "♙", name: "Pawn (b2)", value: 1, color: "white" },
  11: { glyph: "♙", name: "Pawn (c2)", value: 1, color: "white" },
  12: { glyph: "♙", name: "Pawn (d2)", value: 1, color: "white" },
  13: { glyph: "♙", name: "Pawn (e2)", value: 1, color: "white" },
  14: { glyph: "♙", name: "Pawn (f2)", value: 1, color: "white" },
  15: { glyph: "♙", name: "Pawn (g2)", value: 1, color: "white" },
  16: { glyph: "♙", name: "Pawn (h2)", value: 1, color: "white" },
  17: { glyph: "♟", name: "Pawn (a7)", value: 1, color: "black" },
  18: { glyph: "♟", name: "Pawn (b7)", value: 1, color: "black" },
  19: { glyph: "♟", name: "Pawn (c7)", value: 1, color: "black" },
  20: { glyph: "♟", name: "Pawn (d7)", value: 1, color: "black" },
  21: { glyph: "♟", name: "Pawn (e7)", value: 1, color: "black" },
  22: { glyph: "♟", name: "Pawn (f7)", value: 1, color: "black" },
  23: { glyph: "♟", name: "Pawn (g7)", value: 1, color: "black" },
  24: { glyph: "♟", name: "Pawn (h7)", value: 1, color: "black" },
  25: { glyph: "♜", name: "Rook (a8)",   value: 5, color: "black" },
  26: { glyph: "♞", name: "Knight (b8)", value: 3, color: "black" },
  27: { glyph: "♝", name: "Bishop (c8)", value: 3, color: "black" },
  28: { glyph: "♛", name: "Queen (d8)",  value: 9, color: "black" },
  29: { glyph: "♚", name: "King (e8)",   value: 0, color: "black" },
  30: { glyph: "♝", name: "Bishop (f8)", value: 3, color: "black" },
  31: { glyph: "♞", name: "Knight (g8)", value: 3, color: "black" },
  32: { glyph: "♜", name: "Rook (h8)",   value: 5, color: "black" },
}

function buildBoardLayout() {
  const board = Array.from({ length: 8 }, () => Array(8).fill(null))
  for (let c = 0; c < 8; c++) board[0][c] = 25 + c
  for (let c = 0; c < 8; c++) board[1][c] = 17 + c
  for (let c = 0; c < 8; c++) board[6][c] = 9 + c
  for (let c = 0; c < 8; c++) board[7][c] = 1 + c
  return board
}

const BOARD_LAYOUT = buildBoardLayout()
const FILE_LABELS = ["a", "b", "c", "d", "e", "f", "g", "h"]
const RANK_LABELS = ["8", "7", "6", "5", "4", "3", "2", "1"]
const KING_IDS = new Set([5, 29])

const HEATMAP_METRICS = [
  { key: "kdr",           label: "KDR" },
  { key: "weighted_kdr",  label: "Weighted KDR" },
  { key: "first_bloods",  label: "First Bloods" },
  { key: "survival_rate", label: "Survival Rate" },
  { key: "captures",      label: "Total Captures" },
]

function computeHeatmap(pieceStats, metric) {
  const entries = Object.entries(pieceStats).filter(
    ([pid]) => !KING_IDS.has(Number(pid))
  )
  const result = {}
  if (entries.length === 0) return result

  if (metric === "kdr" || metric === "weighted_kdr") {
    const values = entries.map(([, s]) => Number(s[metric] ?? 1))
    const maxDeviation = Math.max(
      ...values.map((v) => Math.abs(v - 1)),
      0.5
    )
    for (const [pid, s] of entries) {
      const v = Number(s[metric] ?? 1)
      const dev = (v - 1) / maxDeviation
      result[pid] = {
        intensity: Math.min(1, Math.abs(dev)),
        sign: v > 1 ? "good" : v < 1 ? "bad" : "neutral",
      }
    }
  } else if (metric === "survival_rate") {
    for (const [pid, s] of entries) {
      const v = Number(s.survival_rate ?? 0)
      result[pid] = {
        intensity: Math.abs(v - 0.5) * 2,
        sign: v > 0.5 ? "good" : v < 0.5 ? "bad" : "neutral",
      }
    }
  } else {
    const values = entries.map(([, s]) => Number(s[metric] ?? 0))
    const maxVal = Math.max(...values, 1)
    for (const [pid, s] of entries) {
      const v = Number(s[metric] ?? 0)
      result[pid] = {
        intensity: v / maxVal,
        sign: v > 0 ? "good" : "neutral",
      }
    }
  }

  return result
}

function PieceBoard({ pieceStats }) {
  const [hovered, setHovered]               = useState(null)
  const [heatmapEnabled, setHeatmapEnabled] = useState(true)
  const [heatmapMetric, setHeatmapMetric]   = useState("kdr")

  const heatmap = useMemo(
    () => computeHeatmap(pieceStats, heatmapMetric),
    [pieceStats, heatmapMetric]
  )

  const handleEnter = (pieceId, evt) => {
    if (!pieceStats[pieceId]) return
    const rect = evt.currentTarget.getBoundingClientRect()
    setHovered({
      pieceId,
      squareTop:    rect.top,
      squareBottom: rect.bottom,
      squareCenter: rect.left + rect.width / 2,
    })
  }

  const handleLeave = () => setHovered(null)

  return (
    <div className="piece-board-wrapper">
      <h2 className="piece-board-title">Per-Piece Stats</h2>
      <p className="piece-board-subtitle">
        Hover over a piece you've played to see its lifetime performance
      </p>

      <div className="heatmap-controls">
        <label className="heatmap-toggle">
          <input
            type="checkbox"
            checked={heatmapEnabled}
            onChange={(e) => setHeatmapEnabled(e.target.checked)}
          />
          <span>Heatmap</span>
        </label>
        <select
          className="heatmap-select"
          value={heatmapMetric}
          onChange={(e) => setHeatmapMetric(e.target.value)}
          disabled={!heatmapEnabled}
        >
          {HEATMAP_METRICS.map((m) => (
            <option key={m.key} value={m.key}>{m.label}</option>
          ))}
        </select>
      </div>

      <div className="piece-board">
        {BOARD_LAYOUT.map((row, rowIdx) => (
          <div key={rowIdx} className="piece-board-row">
            <div className="rank-label">{RANK_LABELS[rowIdx]}</div>
            {row.map((pieceId, colIdx) => {
              const isLight = (rowIdx + colIdx) % 2 === 0
              const info = PIECE_INFO[pieceId]
              const hasData = pieceStats[pieceId] !== undefined
              const heatData = heatmapEnabled && hasData ? heatmap[pieceId] : null
              return (
                <div
                  key={colIdx}
                  className={`piece-square ${isLight ? "light" : "dark"} ${hasData ? "has-data" : "no-data"}`}
                  onMouseEnter={(e) => handleEnter(pieceId, e)}
                  onMouseLeave={handleLeave}
                >
                  {heatData && heatData.intensity > 0.05 && (
                    <span
                      className={`heatmap-aura heatmap-${heatData.sign}`}
                      style={{
                        opacity: 0.55 + heatData.intensity * 0.45,
                        transform: `translate(-50%, -50%) scale(${0.75 + heatData.intensity * 0.55})`,
                      }}
                    />
                  )}
                  {info && (
                    <span className={`piece-glyph piece-${info.color}`}>
                      {info.glyph}
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        ))}
        <div className="piece-board-row file-row">
          <div className="rank-label" />
          {FILE_LABELS.map((f) => (
            <div key={f} className="file-label">{f}</div>
          ))}
        </div>
      </div>

      {hovered && pieceStats[hovered.pieceId] && (
        <PieceTooltip
          piece={PIECE_INFO[hovered.pieceId]}
          stats={pieceStats[hovered.pieceId]}
          squareTop={hovered.squareTop}
          squareBottom={hovered.squareBottom}
          squareCenter={hovered.squareCenter}
        />
      )}
    </div>
  )
}

function PieceTooltip({ piece, stats, squareTop, squareBottom, squareCenter }) {
  const ESTIMATED_TOOLTIP_HEIGHT = 290
  const placeAbove = squareTop >= ESTIMATED_TOOLTIP_HEIGHT + 16

  const style = placeAbove
    ? { left: squareCenter, top: squareTop - 12,    transform: "translate(-50%, -100%)" }
    : { left: squareCenter, top: squareBottom + 12, transform: "translate(-50%, 0)" }

  return (
    <div className="piece-tooltip" style={style}>
      <div className="piece-tooltip-header">
        <span className={`piece-tooltip-glyph piece-${piece.color}`}>
          {piece.glyph}
        </span>
        <div>
          <div className="piece-tooltip-name">{piece.name}</div>
          <div className="piece-tooltip-meta">Value: {piece.value}</div>
        </div>
      </div>
      <ul className="piece-tooltip-list">
        <li>
          <span>KDR</span>
          <span>{Number(stats.kdr ?? 0).toFixed(2)}</span>
        </li>
        <li>
          <span>Weighted KDR</span>
          <span>{Number(stats.weighted_kdr ?? 0).toFixed(2)}</span>
        </li>
        <li>
          <span>Captures</span>
          <span>{stats.captures ?? 0}</span>
        </li>
        <li>
          <span>Deaths</span>
          <span>{stats.deaths ?? 0}</span>
        </li>
        <li>
          <span>First Bloods</span>
          <span>{stats.first_bloods ?? 0}</span>
        </li>
        <li>
          <span>Survival Rate</span>
          <span>{Math.round((stats.survival_rate ?? 0) * 100)}%</span>
        </li>
        <li>
          <span>Games Played</span>
          <span>{stats.games_played ?? 0}</span>
        </li>
      </ul>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Info icon + popup explaining weighted KDR                          */
/* ------------------------------------------------------------------ */

function InfoIcon({ children }) {
  const [open, setOpen] = useState(false)

  return (
    <>
      <button
        type="button"
        className="info-icon"
        onClick={(e) => {
          e.stopPropagation()
          setOpen(true)
        }}
        aria-label="More info"
      >
        i
      </button>
      {open && (
        <div className="info-popup-overlay" onClick={() => setOpen(false)}>
          <div className="info-popup" onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              className="info-popup-close"
              onClick={() => setOpen(false)}
              aria-label="Close"
            >
              ×
            </button>
            {children}
          </div>
        </div>
      )}
    </>
  )
}

function WeightedKdrInfo() {
  return (
    <>
      <h3>Weighted KDR</h3>
      <p>
        Weighted KDR uses a measurement of the relative weighted material
        value of the chess pieces captured divided by the weighted material
        value of the pieces lost.
      </p>
      <h4>Values</h4>
      <ul className="info-piece-values">
        <li><span className="vp-glyph">♕</span> Queen — <b>9</b></li>
        <li><span className="vp-glyph">♖</span> Rook — <b>5</b></li>
        <li><span className="vp-glyph">♗</span> Bishop — <b>3</b></li>
        <li><span className="vp-glyph">♘</span> Knight — <b>3</b></li>
        <li><span className="vp-glyph">♙</span> Pawn — <b>1</b></li>
        <li><span className="vp-glyph">♔</span> King — <b>N/A</b></li>
      </ul>
    </>
  )
}

export default App