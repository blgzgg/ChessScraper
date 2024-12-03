import chess
import chess.pgn
from datetime import datetime

# Assume db_session is an SQLAlchemy session and models have been defined.
# We'll be simulating a game and then updating the database.

class ChessGameProcessor:
    def __init__(self, pgn_moves):
        self.board = chess.Board()  # Create an empty chessboard
        self.pgn_moves = pgn_moves  # List of moves in PGN (Portable Game Notation)
        self.move_history = []      # Store history of moves
    
    def process_game(self, white_player, black_player, date_played):
        """
        Processes the PGN moves, updates the board after each move, and logs the events.
        """
        game_info = {
            "white_player": white_player,
            "black_player": black_player,
            "date_played": date_played,
            "moves": []
        }
        
        # Simulate the moves
        for move_number, move in enumerate(self.pgn_moves, start=1):
            # Parse the move in SAN
            try:
                san_move = self.board.parse_san(move)
                self.board.push(san_move)  # Update the board
                event = self.get_move_event(move_number, san_move)
                game_info['moves'].append(event)  # Collect event info
                
                # Optional: Commit event to DB here using SQLAlchemy
                self.save_move_to_db(move_number, white_player, black_player, san_move)
                
            except ValueError as e:
                print(f"Invalid move at {move_number}: {move}. Error: {e}")
        
        return game_info
    
    def get_move_event(self, move_number, move):
        """
        Gathers information about the move, such as piece moved, capture, and check.
        """
        # Get the piece moved and the source and destination squares
        piece_moved = self.board.piece_at(move.to_square)
        is_capture = self.board.is_capture(move)
        is_check = self.board.is_check()
        is_checkmate = self.board.is_checkmate()

        move_event = {
            "move_number": move_number,
            "piece": piece_moved.symbol(),  # e.g., 'R', 'Q', 'N', etc.
            "from_square": chess.square_name(move.from_square),
            "to_square": chess.square_name(move.to_square),
            "is_capture": is_capture,
            "is_check": is_check,
            "is_checkmate": is_checkmate
        }
        return move_event
    
    def save_move_to_db(self, move_number, white_player, black_player, move):
        """
        Saves the move event to the database (SQLAlchemy ORM example).
        """
        # Assume Game and Move models exist, and we store the game data there
        move_record = Move(
            move_number=move_number,
            white_player_id=white_player,
            black_player_id=black_player,
            piece_moved=self.board.piece_at(move.to_square).symbol(),
            from_square=chess.square_name(move.from_square),
            to_square=chess.square_name(move.to_square),
            is_capture=self.board.is_capture(move),
            is_check=self.board.is_check(),
            is_checkmate=self.board.is_checkmate()
        )
        db_session.add(move_record)
        db_session.commit()

# Example use case
pgn_moves = ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"]  # Replace with actual moves
white_player = 1  # Assume user ID from database
black_player = 2  # Assume opponent user ID from database
date_played = datetime.now()

processor = ChessGameProcessor(pgn_moves)
game_data = processor.process_game(white_player, black_player, date_played)

# Now you can access the game data or use it for statistics
print(game_data)
