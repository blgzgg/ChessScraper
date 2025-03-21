import chess
from datetime import datetime

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
                
            except ValueError as e:
                print(f"Invalid move at {move_number}: {move}. Error: {e}")
        
        return game_info
    
    def get_move_event(self, move_number, move):
        """
        Gathers information about the move, such as piece moved, capture, and check.
        """
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
