PRAGMA foreign_keys = ON;
BEGIN;

-- Players are stored once per username with a small INTEGER PK.
-- Child tables reference player_id rather than the text username,
-- which saves ~9 bytes per row across thousands of rows.
CREATE TABLE IF NOT EXISTS `Player` (
  `player-id`               INTEGER PRIMARY KEY AUTOINCREMENT,
  `name`                    TEXT UNIQUE NOT NULL COLLATE NOCASE,
  `total-captures`          INTEGER DEFAULT 0,
  `total-deaths`            INTEGER DEFAULT 0,
  `total-games`             INTEGER DEFAULT 0,
  `current-elo`             INTEGER DEFAULT 0,
  `current-kdr`             REAL    DEFAULT 0,
  `total-weighted-captures` INTEGER DEFAULT 0,
  `total-weighted-deaths`   INTEGER DEFAULT 0,
  `weighted-kdr`            REAL    DEFAULT 0,
  `recent-parsed-month`     TEXT    DEFAULT NULL,
  `profile-pic-url`         TEXT    DEFAULT NULL
);

-- Games use an INTEGER PK and store the chess.com UUID separately.
-- Same UUID can appear once per (uuid, player_id) since two scanned users
-- may have played each other.
CREATE TABLE IF NOT EXISTS `Games` (
  `game-id`                 INTEGER PRIMARY KEY AUTOINCREMENT,
  `chess-uuid`              TEXT NOT NULL,
  `player-id`               INTEGER NOT NULL,
  `date`                    INTEGER,
  `opponent`                TEXT,
  `opponent-elo`            INTEGER DEFAULT 0,
  `user-elo`                INTEGER DEFAULT 0,
  `user-color`              TEXT    DEFAULT '',
  `victory`                 INTEGER,
  `total-captures`          INTEGER DEFAULT 0,
  `total-deaths`            INTEGER DEFAULT 0,
  `total-weighted-deaths`   INTEGER DEFAULT 0,
  `total-weighted-captures` INTEGER DEFAULT 0,
  `total-moves`             INTEGER DEFAULT 0,
  `url`                     TEXT,
  UNIQUE (`chess-uuid`, `player-id`),
  FOREIGN KEY (`player-id`) REFERENCES `Player` (`player-id`) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_games_player ON Games(`player-id`);

-- Per-piece per-game stats. Uses WITHOUT ROWID because the natural PK
-- (game-id, piece-id) is a compact integer pair and we never need a separate
-- rowid. WITHOUT ROWID storage is cheaper for this access pattern — saves
-- ~12 bytes per row on the rowid + its index entry. Player is implied via
-- game-id → Games.player-id, so we don't store it again here.
CREATE TABLE IF NOT EXISTS `Player-Piece-Stats` (
  `game-id`           INTEGER NOT NULL,
  `piece-id`          INTEGER NOT NULL,
  `was-captured`      INTEGER DEFAULT 0,
  `turn-captured-on`  INTEGER DEFAULT NULL,
  `captures`          INTEGER DEFAULT 0,
  `weighted-captures` INTEGER DEFAULT 0,
  `first-blood`       INTEGER DEFAULT 0,
  PRIMARY KEY (`game-id`, `piece-id`),
  FOREIGN KEY (`game-id`) REFERENCES `Games` (`game-id`) ON DELETE CASCADE
) WITHOUT ROWID;

COMMIT;