import utils
import requests
import json
from requests.adapters import HTTPAdapter
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import chess
import chess.pgn
import io
import db  # ← database layer


session = requests.Session()
adapter = HTTPAdapter(pool_connections=12, pool_maxsize=12)
session.mount("https://", adapter)

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36"
}

# All chess.com game URLs share this prefix. We strip it before storing in
# the DB and re-add it when serving links to the frontend, saving ~28 bytes
# per game across the database.
GAME_URL_PREFIX = "https://www.chess.com/game/"


class Game:
    def __init__(self, raw=None, pgn=None, lan=None, color=None,
                 kills=None, deaths=None, kdr=None,
                 weighted_kills=None, weighted_deaths=None, weighted_kdr=None,
                 game_id=None, date=None, opponent=None,
                 opponent_elo=None, user_elo=None, victory=None):
        self.raw = raw
        self.pgn = pgn
        self.lan = lan
        self.color = color
        self.kills = kills
        self.deaths = deaths
        self.kdr = kdr or 1.0
        self.weighted_kills = weighted_kills
        self.weighted_deaths = weighted_deaths
        self.weighted_kdr = weighted_kdr or 1.0
        # metadata used for DB storage
        self.game_id = game_id
        self.date = date
        self.opponent = opponent
        self.opponent_elo = opponent_elo
        self.user_elo = user_elo
        self.victory = victory

    def get_format(self, fmt):
        return getattr(self, fmt, None)

    def set_format(self, fmt, value):
        setattr(self, fmt, value)


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------

def error_check(response_code):
    if response_code == 200:
        print("Successfully fetched data from the server.")
        return True
    print(f"Error: Unable to fetch data from the server. Status Code: {response_code}")
    if response_code == 429:
        print("Rate limit exceeded")
    elif response_code == 404:
        print("URL malformed or data not available")
    elif response_code == 410:
        print("Data permanently unavailable")
    elif response_code == 304:
        print("Data not modified since the last request")
    return False


def fetch_archives(username):
    url = f"https://api.chess.com/pub/player/{username}/games/archives"
    print("Fetching archives for user:", username)
    response = session.get(url, headers=headers)
    if error_check(response.status_code):
        return response.json().get("archives", [])
    return []


def fetch_player_profile(username):
    """Return the Chess.com player profile JSON, or {}."""
    url = f"https://api.chess.com/pub/player/{username}"
    response = session.get(url, headers=headers)
    if error_check(response.status_code):
        return response.json()
    return {}


def fetch_avatar_url(username):
    """Pull just the avatar URL from the player profile endpoint."""
    profile = fetch_player_profile(username)
    return profile.get("avatar", "")


def get_current_elo(username):
    """Best-effort: pull the rapid rating from the stats endpoint."""
    url = f"https://api.chess.com/pub/player/{username}/stats"
    response = session.get(url, headers=headers)
    if error_check(response.status_code):
        data = response.json()
        # Try rapid first, then bullet, blitz
        for tc in ("chess_rapid", "chess_bullet", "chess_blitz"):
            if tc in data:
                return data[tc].get("last", {}).get("rating", 0)
    return 0


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def find_all_game_data(username, progress_callback=None):
    """
    Parse all games for a Chess.com user.

    progress_callback: optional callable invoked as
        progress_callback(stage, current, total, **extra)
    where stage is one of: "init", "fetching_archives", "fetching_games",
    "parsing", "saving", "done".
    """
    username = username.lower().strip()

    def emit(stage, current=0, total=0, **extra):
        if progress_callback:
            progress_callback(stage, current, total, **extra)

    emit("init", 0, 0, message=f"Initializing parser for {username}")

    # Ensure the DB is ready and the player row exists
    db.init_db()
    elo = get_current_elo(username)
    db.upsert_player(username, elo)

    # Profile pictures can change — refresh every run
    avatar = fetch_avatar_url(username)
    if avatar:
        db.update_player_profile_pic(username, avatar)

    emit("fetching_archives", 0, 0, message="Fetching archive list")
    archives = fetch_archives(username)
    if not archives:
        print("No archives found for user:", username)
        emit("done", 0, 0, message="No archives found")
        return []

    # Only fetch archives we haven't processed yet
    new_archives = db.filter_new_archives(username, archives)
    print(f"Total archives: {len(archives)}  |  New (unprocessed): {len(new_archives)}")

    # ------------------------------------------------------------------
    # Load already-cached games from DB so the graph stays complete
    # ------------------------------------------------------------------
    cached_rows = db.get_all_games(username)
    cached_games = []
    for row in cached_rows:
        wk = row["total-weighted-captures"] or 0
        wd = row["total-weighted-deaths"] or 0
        g = Game(
            game_id=row["chess-uuid"],
            date=row["date"],
            opponent=row["opponent"],
            opponent_elo=row["opponent-elo"],
            user_elo=row["user-elo"],
            color=row["user-color"],
            victory=row["victory"],
            kills=row["total-captures"],
            deaths=row["total-deaths"],
            weighted_kills=wk,
            weighted_deaths=wd,
        )
        g.kdr = row["total-captures"] / row["total-deaths"] if row["total-deaths"] > 0 else float(row["total-captures"] or 1)
        g.weighted_kdr = (wk / wd) if wd > 0 else float(wk or 1)
        # Synthesize a minimal raw dict so api.py can still read end_time/url
        # for cached games without re-fetching from the network. Note: the
        # url column stores only the suffix (e.g. "live/44139316037"); the
        # prefix is re-added by the click handler JS.
        g.raw = {
            "end_time": row["date"],
            "url": row["url"] or "",  # suffix-only, prefix added by JS
        }
        cached_games.append(g)

    if not new_archives:
        print("All archives already cached — returning DB data.")
        emit("done", len(cached_games), len(cached_games),
             message="All games loaded from cache")
        return cached_games

    # ------------------------------------------------------------------
    # Fetch raw games from new archives — in parallel.
    #
    # Each archive is one HTTP request, and a player with a few years of
    # history can have dozens of archives. Fetching them serially is
    # network-bound dead time; the chess.com API is fine with concurrent
    # requests at this rate. Order is preserved for the "last_fetched"
    # marker so resume-from-checkpoint still works.
    # ------------------------------------------------------------------
    all_games_list_raw = []
    last_fetched_archive = None
    completed_count = 0
    archive_results = {}  # url → games list (preserves order independently)

    def fetch_one(url):
        try:
            r = session.get(url, headers=headers, timeout=30)
            if r.status_code == 200:
                return url, r.json().get("games", [])
        except Exception as e:
            print(f"Error fetching {url}: {e}")
        return url, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_one, url): url for url in new_archives}
        for future in as_completed(futures):
            url, games = future.result()
            completed_count += 1
            emit("fetching_games", completed_count, len(new_archives),
                 message=f"Fetched archive {completed_count} of {len(new_archives)}")
            if games is None:
                print("Failed to fetch games from archive:", url)
            else:
                archive_results[url] = games

    # Reassemble in the original archive order so chronological ordering of
    # games is preserved and last_fetched_archive points to the most recent
    # successfully fetched archive.
    for url in new_archives:
        if url in archive_results:
            all_games_list_raw.extend(archive_results[url])
            last_fetched_archive = url

    # ------------------------------------------------------------------
    # Parse + persist each new game one-at-a-time so we can emit per-game
    # progress updates. This used to be three sequential passes (build,
    # parse, save) — we fuse them so the progress bar reflects real work.
    # ------------------------------------------------------------------
    total_new = len(all_games_list_raw)
    new_game_objects = []
    kills_total = 0
    deaths_total = 0

    # Accumulators flushed in batches at the end of parsing.
    # Avoiding per-game DB writes saves an enormous number of fsyncs.
    games_to_insert = []           # list of dicts for db.insert_games_batch
    piece_stat_buffer = []         # list of (chess_uuid, piece_stat_tuple_partial)
                                   # we resolve chess_uuid → game_id_int after batch insert

    # Pre-fetch the list of already-stored UUIDs so we don't re-scan one at
    # a time. One round trip beats len(games) round trips.
    already_stored_uuids = _get_existing_game_uuids(username)

    for i, raw_game in enumerate(all_games_list_raw, start=1):
        # Build Game object from raw data
        g = isolate_pgn(raw_game, i - 1, username)

        # Compute kills/deaths/weighted/per-piece for this single game
        k, d, wk, wd, piece_stats = utils.play_game(g.get_format("lan"), g.get_format("color"))
        g.set_format("kills", k)
        g.set_format("deaths", d)
        g.set_format("kdr", k / d if d > 0 else float(k or 1))
        g.set_format("weighted_kills", wk)
        g.set_format("weighted_deaths", wd)
        g.set_format("weighted_kdr", wk / wd if wd > 0 else float(wk or 1))
        kills_total += k
        deaths_total += d

        # Extract metadata
        raw = g.raw or {}
        game_id      = raw.get("uuid", "")
        date         = raw.get("end_time", 0)
        opponent     = _get_opponent(raw, username)
        opponent_elo = _get_opponent_elo(raw, username)
        user_elo     = _get_user_elo(raw, username)
        color        = utils.find_game_info(raw, username)
        victory      = _get_victory(raw, username)
        total_moves  = len(g.lan) if g.lan else 0

        # Write metadata back onto the Game object so api.py can read it
        g.set_format("game_id",      game_id)
        g.set_format("date",         date)
        g.set_format("opponent",     opponent)
        g.set_format("opponent_elo", opponent_elo)
        g.set_format("user_elo",     user_elo)
        g.set_format("color",        color)
        g.set_format("victory",      victory)

        # Queue for batch insert if not already there
        if game_id and game_id not in already_stored_uuids:
            full_url = raw.get("url", "")
            if full_url.startswith(GAME_URL_PREFIX):
                game_url = full_url[len(GAME_URL_PREFIX):]
            else:
                game_url = full_url

            games_to_insert.append({
                "chess_uuid":        game_id,
                "date":              date,
                "opponent":          opponent,
                "opponent_elo":      opponent_elo,
                "user_elo":          user_elo,
                "user_color":        color,
                "victory":           victory,
                "captures":          k,
                "deaths":            d,
                "weighted_captures": wk,
                "weighted_deaths":   wd,
                "total_moves":       total_moves,
                "url":               game_url,
            })

            # Buffer piece-stat rows keyed by chess_uuid; we'll resolve to
            # integer game-ids after the batch insert. Sparse storage:
            # only pieces with activity get rows.
            for pid, ps in piece_stats.items():
                if (ps["captures"] == 0 and ps["was_captured"] == 0
                        and ps["first_blood"] == 0):
                    continue
                piece_stat_buffer.append((
                    game_id,         # chess UUID — resolved later
                    pid,
                    ps["was_captured"],
                    ps["turn_captured_on"],
                    ps["captures"],
                    ps["weighted_captures"],
                    ps["first_blood"],
                ))

        new_game_objects.append(g)

        # Per-game progress update — this is what drives the front-end bar
        emit("parsing", i, total_new,
             message=f"Parsed game {i} of {total_new}")

    # Now flush everything in two batched DB transactions
    uuid_to_int_id = db.insert_games_batch(username, games_to_insert)

    # Resolve chess UUIDs to integer game-ids for the piece-stat rows
    piece_stat_rows = []
    for chess_uuid, *rest in piece_stat_buffer:
        gid_int = uuid_to_int_id.get(chess_uuid)
        if gid_int is not None:
            piece_stat_rows.append((gid_int, *rest))

    # Flush per-piece stats for all newly-parsed games in a single transaction
    db.insert_piece_stats_batch(piece_stat_rows)

    # ------------------------------------------------------------------
    # Update player aggregate stats
    # ------------------------------------------------------------------
    all_kills = sum(g.kills or 0 for g in cached_games + new_game_objects)
    all_deaths = sum(g.deaths or 0 for g in cached_games + new_game_objects)
    all_wkills = sum(g.weighted_kills or 0 for g in cached_games + new_game_objects)
    all_wdeaths = sum(g.weighted_deaths or 0 for g in cached_games + new_game_objects)
    total_games = len(cached_games) + len(new_game_objects)
    current_kdr = (all_kills / all_deaths) if all_deaths > 0 else float(all_kills or 0)
    weighted_kdr = (all_wkills / all_wdeaths) if all_wdeaths > 0 else float(all_wkills or 0)

    if last_fetched_archive:
        db.update_player_stats(
            username=username,
            total_captures=all_kills,
            total_deaths=all_deaths,
            total_games=total_games,
            recent_month=last_fetched_archive,
            current_kdr=round(current_kdr, 2),
            total_weighted_captures=all_wkills,
            total_weighted_deaths=all_wdeaths,
            weighted_kdr=round(weighted_kdr, 2),
        )

    # Reclaim space if we actually wrote new rows. SQLite's WAL mode + INSERT
    # OR IGNORE leaves behind unused pages; VACUUM rebuilds the file compactly.
    # Only worth running when meaningful new data was added (>0 games written).
    if new_game_objects:
        try:
            db.vacuum_db()
        except Exception as exc:
            print(f"VACUUM failed (non-fatal): {exc}")

    print(f"Total games for {username}: {total_games} "
          f"({len(cached_games)} cached + {len(new_game_objects)} new)")

    emit("done", total_games, total_games,
         message=f"Finished — {total_games} games parsed")

    # Return everything in date order (cached first, then new)
    return cached_games + new_game_objects


# ---------------------------------------------------------------------------
# PGN / LAN helpers  (unchanged from original)
# ---------------------------------------------------------------------------

def isolate_pgn(game_data_raw, iteration, username):
    if utils.DEBUG:
        print(f"\nGame #{iteration + 1}")
    color = utils.find_game_info(game_data_raw, username)
    if utils.DEBUG:
        print(f"Player color: {color}")

    pgn_data = game_data_raw.get("pgn", "")
    pgn_data = re.sub(r'\{.*?\}', '', pgn_data)
    pgn_data = re.sub(r'\[.*?\]', '', pgn_data)
    pgn_data = pgn_data.replace('\n', '')
    pgn_data = pgn_data.replace('0-1', '')
    pgn_data = pgn_data.replace('1-0', '')
    pgn_data = pgn_data.replace('0-0', '')

    dot_pattern = r'\d+\.{3}'
    pgn_data = re.sub(dot_pattern, '', pgn_data)
    pgn_data = pgn_data.replace('  ', ' ').replace('  ', ' ')

    if utils.DEBUG:
        print("Pgn Format:", pgn_data)

    lan_data = pgn_to_lan(pgn_data)
    if utils.DEBUG:
        print("Lan Format:", lan_data)

    return Game(raw=game_data_raw, pgn=pgn_data, lan=lan_data, color=color)


def pgn_to_lan(pgn_data):
    # Note: we don't actually need a chess.Board — just iterate the moves
    # and emit their UCI strings. Skipping the Board() instantiation and
    # board.push() per move shaves real time at scale.
    game = chess.pgn.read_game(io.StringIO(pgn_data))
    if game is None:
        return []
    return [move.uci() for move in game.mainline_moves()]


def parse_games(games_list):
    """Legacy helper retained for compatibility; find_all_game_data no longer
    uses this since parsing was inlined to support per-game progress events."""
    kills_total = 0
    deaths_total = 0
    for game in games_list:
        k, d, wk, wd, _piece_stats = utils.play_game(game.get_format("lan"), game.get_format("color"))
        kills_total += k
        deaths_total += d
        game.set_format("kdr", k / d if d > 0 else float(k or 1))
        game.set_format("kills", k)
        game.set_format("deaths", d)
        game.set_format("weighted_kills", wk)
        game.set_format("weighted_deaths", wd)
        game.set_format("weighted_kdr", wk / wd if wd > 0 else float(wk or 1))
        print(f"Game KDR: {game.get_format('kdr'):.2f}  Weighted: {game.get_format('weighted_kdr'):.2f}")
    print(f"Total Kills: {kills_total}  Total Deaths: {deaths_total}")
    kdr = kills_total / deaths_total if deaths_total > 0 else float('inf')
    print(f"Kill/Death Ratio: {kdr:.2f}")
    return games_list


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _get_existing_game_uuids(username: str) -> set:
    """Return the set of chess-uuid strings already stored for this player.

    Used as a fast in-memory lookup during parsing so we can avoid one DB
    round trip per game. Single SELECT, returns a set for O(1) membership.
    """
    cached = db.get_all_games(username)
    return {row["chess-uuid"] for row in cached if row.get("chess-uuid")}


def _get_opponent(game_data_raw: dict, username: str) -> str:
    white = game_data_raw.get("white", {}).get("username", "").lower()
    black = game_data_raw.get("black", {}).get("username", "").lower()
    return black if white == username else white


def _get_opponent_elo(game_data_raw: dict, username: str) -> int:
    color = utils.find_game_info(game_data_raw, username)
    opp_color = "black" if color == "white" else "white"
    return game_data_raw.get(opp_color, {}).get("rating", 0)


def _get_user_elo(game_data_raw: dict, username: str) -> int:
    color = utils.find_game_info(game_data_raw, username)
    return game_data_raw.get(color, {}).get("rating", 0)


def _get_victory(game_data_raw: dict, username: str) -> int:
    """Return 1 if the player won, 0 for a loss, -1 for a draw/other."""
    color = utils.find_game_info(game_data_raw, username)
    if color == "white":
        result = game_data_raw.get("white", {}).get("result", "")
    elif color == "black":
        result = game_data_raw.get("black", {}).get("result", "")
    else:
        return -1
    if result == "win":
        return 1
    if result in ("checkmated", "timeout", "resigned", "lose"):
        return 0
    return -1  # draw or other


# ---------------------------------------------------------------------------

def main():
    username = input("Please enter a player username: ").lower().strip()
    find_all_game_data(username)


if __name__ == "__main__":
    main()