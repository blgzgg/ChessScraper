import sqlite3
import os

# Path resolution — db.py lives in the project root, the schema lives in ../db/
_THIS_DIR    = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH  = os.path.normpath(os.path.join(_THIS_DIR, "..", "db", "chessdb.sql"))
DB_PATH = os.environ.get(
    "CHESSDB_PATH",
    os.path.normpath(os.path.join(_THIS_DIR, "..", "db", "chessdb.sqlite"))
)


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL mode reduces file growth from rollback journals and gives better
    # concurrent read performance. Safe to call every connection — SQLite
    # only switches modes when the DB is otherwise idle.
    conn.execute("PRAGMA journal_mode = WAL")
    # Trade durability for size: PRAGMA synchronous=NORMAL is still safe
    # against crashes (sync at COMMIT) but skips some intermediate fsyncs
    # during long batch writes.
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def vacuum_db():
    """Reclaim space from deleted/replaced rows.

    SQLite databases grow as rows are inserted but don't shrink automatically
    when rows are deleted or when INSERT OR IGNORE skips duplicates. Running
    VACUUM rebuilds the file from scratch in canonical form. Worth doing
    after a parsing run that wrote a lot of new rows.

    Cannot be run inside a transaction — we open a fresh connection with
    isolation_level=None to force autocommit mode.
    """
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()


def init_db():
    """Initialize the database by executing the schema in chessdb.sql.

    The schema file lives in ../db/chessdb.sql relative to this file.
    All CREATE statements use IF NOT EXISTS so this is idempotent.
    """
    if not os.path.isfile(SCHEMA_PATH):
        raise FileNotFoundError(
            f"Schema file not found at {SCHEMA_PATH}. "
            "Make sure ../db/chessdb.sql exists relative to db.py."
        )

    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    conn = get_connection()
    try:
        conn.executescript(schema_sql)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Player helpers
# ---------------------------------------------------------------------------

def _get_player_id(conn, username: str):
    """Return the integer player-id for a username, or None if not found."""
    row = conn.execute(
        'SELECT "player-id" FROM Player WHERE name = ?',
        (username.lower(),)
    ).fetchone()
    return row[0] if row else None


def get_player(username: str):
    """Return the Player row as a dict, or None if not found."""
    conn = get_connection()
    row = conn.execute(
        'SELECT * FROM Player WHERE name = ?', (username.lower(),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_player(username: str, elo: int = 0):
    """Insert player if not present; update elo on conflict."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO Player(name, "current-elo")
        VALUES (?, ?)
        ON CONFLICT(name) DO UPDATE SET "current-elo" = excluded."current-elo"
    """, (username.lower(), elo))
    conn.commit()
    conn.close()


def update_player_stats(username: str, total_captures: int, total_deaths: int,
                        total_games: int, recent_month: str,
                        current_kdr: float = 0.0,
                        total_weighted_captures: int = 0,
                        total_weighted_deaths: int = 0,
                        weighted_kdr: float = 0.0):
    """Overwrite the aggregate stats and the latest-parsed-month marker."""
    conn = get_connection()
    conn.execute("""
        UPDATE Player
        SET "total-captures"           = ?,
            "total-deaths"             = ?,
            "total-games"              = ?,
            "current-kdr"              = ?,
            "total-weighted-captures"  = ?,
            "total-weighted-deaths"    = ?,
            "weighted-kdr"             = ?,
            "recent-parsed-month"      = ?
        WHERE name = ?
    """, (total_captures, total_deaths, total_games,
          current_kdr,
          total_weighted_captures, total_weighted_deaths, weighted_kdr,
          recent_month, username.lower()))
    conn.commit()
    conn.close()


def update_player_profile_pic(username: str, avatar_url: str):
    """Refresh the cached profile-picture URL for a player."""
    conn = get_connection()
    conn.execute("""
        UPDATE Player
        SET "profile-pic-url" = ?
        WHERE name = ?
    """, (avatar_url, username.lower()))
    conn.commit()
    conn.close()


def get_recent_parsed_month(username: str):
    """Return the archive-URL string of the last fully-parsed month, or None."""
    player = get_player(username)
    return player.get("recent-parsed-month") if player else None


# ---------------------------------------------------------------------------
# Game helpers
# ---------------------------------------------------------------------------

def game_exists(chess_uuid: str, player: str) -> bool:
    """Check whether this game has already been recorded for this player."""
    conn = get_connection()
    pid = _get_player_id(conn, player)
    if pid is None:
        conn.close()
        return False
    row = conn.execute(
        'SELECT 1 FROM Games WHERE "chess-uuid" = ? AND "player-id" = ?',
        (chess_uuid, pid)
    ).fetchone()
    conn.close()
    return row is not None


def insert_game(game_id: str, date: int, player: str, opponent: str,
                opponent_elo: int, user_elo: int, user_color: str,
                victory: int, captures: int, deaths: int,
                weighted_deaths: int = 0, weighted_captures: int = 0,
                total_moves: int = 0, url: str = ""):
    """Insert a single game and return its INTEGER game-id (the new PK).

    The `game_id` parameter is actually the chess.com UUID — we keep the
    name for backwards compatibility with the rest of the codebase. The
    function returns the integer rowid that the new Games row was assigned,
    which callers should use when inserting piece-stat rows.
    """
    conn = get_connection()
    pid = _get_player_id(conn, player)
    if pid is None:
        conn.close()
        raise ValueError(f"Player '{player}' not found in DB")

    cursor = conn.execute("""
        INSERT OR IGNORE INTO Games(
            "chess-uuid", "player-id", date, opponent,
            "opponent-elo", "user-elo", "user-color",
            victory,
            "total-captures", "total-deaths",
            "total-weighted-deaths", "total-weighted-captures", "total-moves",
            url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (game_id, pid, date, opponent,
          opponent_elo, user_elo, user_color,
          victory,
          captures, deaths, weighted_deaths, weighted_captures, total_moves,
          url))

    if cursor.rowcount == 0:
        # Already existed — look up the existing integer ID to return it
        existing = conn.execute(
            'SELECT "game-id" FROM Games WHERE "chess-uuid" = ? AND "player-id" = ?',
            (game_id, pid)
        ).fetchone()
        new_id = existing[0] if existing else None
    else:
        new_id = cursor.lastrowid

    conn.commit()
    conn.close()
    return new_id


def insert_games_batch(player: str, games: list):
    """Bulk-insert many games for one player and return a dict mapping
    chess-uuid → integer game-id.

    Each entry in `games` must be a dict with keys:
        chess_uuid, date, opponent, opponent_elo, user_elo, user_color,
        victory, captures, deaths, weighted_deaths, weighted_captures,
        total_moves, url

    This is dramatically faster than calling insert_game() in a loop because
    it amortizes the connection-open/transaction/commit overhead across all
    rows. For 1000 games, this is ~50× faster than per-row inserts.
    """
    if not games:
        return {}
    conn = get_connection()
    pid = _get_player_id(conn, player)
    if pid is None:
        conn.close()
        raise ValueError(f"Player '{player}' not found in DB")

    rows = [(
        g["chess_uuid"], pid, g["date"], g["opponent"],
        g["opponent_elo"], g["user_elo"], g["user_color"],
        g["victory"],
        g["captures"], g["deaths"],
        g.get("weighted_deaths", 0), g.get("weighted_captures", 0),
        g.get("total_moves", 0), g.get("url", ""),
    ) for g in games]

    conn.executemany("""
        INSERT OR IGNORE INTO Games(
            "chess-uuid", "player-id", date, opponent,
            "opponent-elo", "user-elo", "user-color",
            victory,
            "total-captures", "total-deaths",
            "total-weighted-deaths", "total-weighted-captures", "total-moves",
            url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()

    # Look up the integer IDs for all the UUIDs we just inserted (or that
    # were already there from a previous run). One round trip.
    uuids = [g["chess_uuid"] for g in games]
    placeholders = ",".join("?" * len(uuids))
    id_map = {}
    cur = conn.execute(
        f'SELECT "chess-uuid", "game-id" FROM Games '
        f'WHERE "player-id" = ? AND "chess-uuid" IN ({placeholders})',
        [pid] + uuids
    )
    for chess_uuid, gid in cur.fetchall():
        id_map[chess_uuid] = gid

    conn.close()
    return id_map


def get_all_games(username: str):
    """Return all game rows for a player ordered by date ascending.

    The returned dicts use the legacy field names where possible so the
    callers in scraper.py/api.py don't need to change. We expose the
    chess UUID as 'chess-uuid' and the integer ID as 'game-id-int' (which
    nothing currently reads but is available if needed).
    """
    conn = get_connection()
    rows = conn.execute("""
        SELECT g.*
        FROM Games g
        JOIN Player p ON p."player-id" = g."player-id"
        WHERE p.name = ?
        ORDER BY g.date ASC
    """, (username.lower(),)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_opponents(username: str, limit: int = 200,
                  date_from_epoch=None, date_to_epoch=None,
                  victory=None, color=None):
    """Return the list of opponents this player has faced.

    Optional filters narrow the result so the autocomplete dropdown matches
    whatever filters are already applied to the graphs:
      - date_from_epoch / date_to_epoch: Unix timestamps (inclusive)
      - victory:  1 (win) | 0 (loss) | -1 (draw) — None means any
      - color:    'white' | 'black'              — None means any

    The opponent filter itself is intentionally NOT a parameter: facet-style
    UIs typically exclude the active facet from its own options query so the
    user can browse alternatives.

    Ordered by frequency (most-played first). Each entry is
    {"name": str, "games": int}.
    """
    where_clauses = ['p.name = ?',
                     'g.opponent IS NOT NULL',
                     "g.opponent != ''"]
    params = [username.lower()]

    if date_from_epoch is not None:
        where_clauses.append('g.date >= ?')
        params.append(date_from_epoch)
    if date_to_epoch is not None:
        where_clauses.append('g.date <= ?')
        params.append(date_to_epoch)
    if victory is not None:
        where_clauses.append('g.victory = ?')
        params.append(victory)
    if color:
        where_clauses.append('g."user-color" = ?')
        params.append(color)

    where_sql = ' AND '.join(where_clauses)
    params.append(limit)

    conn = get_connection()
    rows = conn.execute(f"""
        SELECT g.opponent AS name, COUNT(*) AS games
        FROM Games g
        JOIN Player p ON p."player-id" = g."player-id"
        WHERE {where_sql}
        GROUP BY g.opponent
        ORDER BY games DESC, g.opponent ASC
        LIMIT ?
    """, params).fetchall()
    conn.close()
    return [{"name": r["name"], "games": r["games"]} for r in rows]


# ---------------------------------------------------------------------------
# Piece-stats helpers
# ---------------------------------------------------------------------------

def insert_piece_stats_batch(rows: list):
    """Bulk-insert piece stat rows. Each row is a tuple of:
        (game_id_int, piece_id, was_captured, turn_captured_on,
         captures, weighted_captures, first_blood)
    where game_id_int is the INTEGER game-id from the Games table (returned
    by insert_game).
    """
    if not rows:
        return
    conn = get_connection()
    conn.executemany("""
        INSERT OR IGNORE INTO "Player-Piece-Stats"(
            "game-id", "piece-id",
            "was-captured", "turn-captured-on",
            captures, "weighted-captures", "first-blood"
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()
    conn.close()


def get_piece_stats_aggregate(username: str):
    """Return aggregated per-piece stats for the player.

    Note on schema: per-piece rows are only stored when a piece had activity
    (made a capture, was captured, or scored first blood). Inactive pieces
    don't get rows. So:
      - captures / weighted_captures / first_bloods / deaths come from SUMs
        over the existing rows (absent rows contribute 0, which is correct)
      - games_played is derived from the Games table — count of games where
        the user played the matching color (white pieces 1-16 → user-color='white')
      - survival_count = games_played - deaths (a piece survived iff it wasn't captured)

    Output is a list of dicts, one per piece-id (1-32) where the player has any
    games matching that piece's color.
    """
    conn = get_connection()
    pid = _get_player_id(conn, username)
    if pid is None:
        conn.close()
        return []

    # First: how many games did the user play as each color?
    color_games = conn.execute("""
        SELECT "user-color" AS color, COUNT(*) AS n
        FROM Games
        WHERE "player-id" = ?
        GROUP BY "user-color"
    """, (pid,)).fetchall()
    games_white = 0
    games_black = 0
    for r in color_games:
        if r["color"] == "white":
            games_white = r["n"]
        elif r["color"] == "black":
            games_black = r["n"]

    # Second: aggregate piece rows by joining on the integer game-id
    rows = conn.execute("""
        SELECT
            pps."piece-id"                           AS piece_id,
            COALESCE(SUM(pps.captures), 0)           AS captures,
            COALESCE(SUM(pps."weighted-captures"),0) AS weighted_captures,
            COALESCE(SUM(pps."was-captured"), 0)     AS deaths,
            COALESCE(SUM(pps."first-blood"), 0)      AS first_bloods
        FROM "Player-Piece-Stats" pps
        JOIN Games g ON g."game-id" = pps."game-id"
        WHERE g."player-id" = ?
        GROUP BY pps."piece-id"
    """, (pid,)).fetchall()
    conn.close()

    by_pid = {r["piece_id"]: dict(r) for r in rows}

    out = []
    for piece_id in range(1, 33):
        is_white = piece_id <= 16
        games = games_white if is_white else games_black
        if games == 0:
            continue

        agg = by_pid.get(piece_id, {
            "captures": 0, "weighted_captures": 0,
            "deaths": 0, "first_bloods": 0,
        })
        captures    = agg["captures"]   or 0
        wcaptures   = agg["weighted_captures"] or 0
        deaths      = agg["deaths"]     or 0
        first_blood = agg["first_bloods"] or 0
        survived    = games - deaths

        kdr = (captures / deaths) if deaths > 0 else float(captures or 0)
        own_value = PIECE_VALUES_FOR_DB.get(piece_id, 0) or 1
        weighted_kdr = (wcaptures / (deaths * own_value)) if deaths > 0 else float(wcaptures or 0)
        survival_rate = (survived / games) if games > 0 else 0.0

        out.append({
            "piece_id":          piece_id,
            "captures":          captures,
            "weighted_captures": wcaptures,
            "deaths":            deaths,
            "first_bloods":      first_blood,
            "games_played":      games,
            "survival_count":    survived,
            "kdr":               kdr,
            "weighted_kdr":      weighted_kdr,
            "survival_rate":     survival_rate,
        })
    return out


# Local copy of piece values used by the aggregation query.
PIECE_VALUES_FOR_DB = {
    1: 5, 2: 3, 3: 3, 4: 9, 5: 0, 6: 3, 7: 3, 8: 5,
    9: 1, 10: 1, 11: 1, 12: 1, 13: 1, 14: 1, 15: 1, 16: 1,
    17: 1, 18: 1, 19: 1, 20: 1, 21: 1, 22: 1, 23: 1, 24: 1,
    25: 5, 26: 3, 27: 3, 28: 9, 29: 0, 30: 3, 31: 3, 32: 5,
}


# Archive-level caching helper


def filter_new_archives(username: str, archive_urls: list) -> list:
    """
    Given the full list of archive URLs for a player, return only the ones
    that haven't been fully parsed yet.

    Archive URLs look like:
        https://api.chess.com/pub/player/<name>/games/2023/04

    We store the URL of the last fully-parsed month in Player.recent-parsed-month.
    Everything strictly after that index is considered new.
    """
    recent = get_recent_parsed_month(username)
    if recent is None:
        return archive_urls          # first run — fetch everything

    try:
        idx = archive_urls.index(recent)
        return archive_urls[idx + 1:]
    except ValueError:
        # Stored URL not present (e.g. account re-created) — re-fetch all
        return archive_urls