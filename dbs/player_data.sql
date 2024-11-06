CREATE TABLE users (
    user_id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE games (
    game_id SERIAL PRIMARY KEY,
    white_player_id INT REFERENCES users(user_id),
    black_player_id INT REFERENCES users(user_id),
    result VARCHAR(10),  -- e.g., '1-0' for white win, '0-1' for black win, '1/2-1/2' for draw
    played_on TIMESTAMP NOT NULL,
    winner_id INT REFERENCES users(user_id),  -- winner of the match
    loser_id INT REFERENCES users(user_id)    -- loser of the match
);

CREATE TABLE game_pieces (
    piece_id SERIAL PRIMARY KEY,
    game_id INT REFERENCES games(game_id),
    player_id INT REFERENCES users(user_id),  -- Owner of the piece (user)
    piece_type VARCHAR(10),  -- 'Pawn', 'Rook', etc
    piece_side VARCHAR(5),  -- 'White' or 'Black'
    starting_position VARCHAR(2),  -- 'a1', 'h1', etc
    captured BOOLEAN DEFAULT FALSE,  -- Whether this piece was captured
    captured_on_move INT,  -- Move number piece was captured on (if applicable)
    total_captures INT DEFAULT 0,  -- total pieces captured by this piece
    total_value_captured INT DEFAULT 0,  -- total value of captured pieces
    piece_identifier VARCHAR(20)  -- Unique identifier for tracking the specific piece ('left_rook', 'right_bishop', etc)
);

CREATE TABLE moves (
    move_id SERIAL PRIMARY KEY,
    game_id INT REFERENCES games(game_id),
    player_id INT REFERENCES users(user_id),  -- The player who made the move
    piece_id INT REFERENCES game_pieces(piece_id),  -- The piece being moved
    move_number INT, 
    from_position VARCHAR(2),  -- Position at start of move 
    to_position VARCHAR(2),  -- New position after move
    captured_piece_id INT REFERENCES game_pieces(piece_id),  -- only if a piece was captured on this move
    move_time TIMESTAMP DEFAULT NOW()  -- timestamp of the move
);
