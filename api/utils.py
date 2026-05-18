import copy

# Set to True to print board state and per-move debug info during play_game().
# Stays off by default — every print is a syscall, and play_game runs ~30
# moves × thousands of games, so prints visibly slow parsing.
DEBUG = False

def _dbg(*args, **kwargs):
    if DEBUG:
        _dbg(*args, **kwargs)

# The chess board matrix is a list of 64 integers that represent the pieces on the chess board
# Each individual piece is denoted by its own integer, and empty spaces are denoted by 0,

#Right now the matrix represents white on the top row and black on the bottom, however it should be noted it is currently mirrored
#Functionally this does not create any issues, but it can be confusing when trying to figure out the queen/king orientation a bit
chess_board_matrix = [[1, 2, 3, 4, 5, 6, 7, 8],
                      [9, 10, 11, 12, 13, 14, 15, 16],
                      [0, 0, 0, 0, 0, 0, 0, 0],
                      [0, 0, 0, 0, 0, 0, 0, 0],
                      [0, 0, 0, 0, 0, 0, 0, 0],
                      [0, 0, 0, 0, 0, 0, 0, 0],
                      [17, 18, 19, 20, 21, 22, 23, 24],
                      [25, 26, 27, 28, 29, 30, 31, 32]]


# ---------------------------------------------------------------------------
# Piece-value lookup for weighted KDR
# ---------------------------------------------------------------------------
# Standard chess values: Q=9, R=5, B=3, N=3, P=1, K=0 (king can't be captured)
#
# Back rank IDs are R N B Q K B N R for both colors:
#   White back rank: 1=R 2=N 3=B 4=Q 5=K 6=B 7=N 8=R
#   Black back rank: 25=R 26=N 27=B 28=Q 29=K 30=B 31=N 32=R
# Pawns: white 9-16, black 17-24
PIECE_VALUES = {
    # White back rank
    1: 5, 2: 3, 3: 3, 4: 9, 5: 0, 6: 3, 7: 3, 8: 5,
    # White pawns
    9: 1, 10: 1, 11: 1, 12: 1, 13: 1, 14: 1, 15: 1, 16: 1,
    # Black pawns
    17: 1, 18: 1, 19: 1, 20: 1, 21: 1, 22: 1, 23: 1, 24: 1,
    # Black back rank
    25: 5, 26: 3, 27: 3, 28: 9, 29: 0, 30: 3, 31: 3, 32: 5,
}


def piece_value(piece_id, promoted_pieces=None):
    """Return the standard point value of a piece.

    Pawns that have promoted are tracked in promoted_pieces (a set/list of
    pawn IDs); they're counted as queens.
    """
    if promoted_pieces and piece_id in promoted_pieces:
        return 9  # promoted pawn → queen
    return PIECE_VALUES.get(piece_id, 0)


# This function parses chess moves in lan notation and converts them into a list of 4 digits
# This list will be used to identify and move pieces to their appropirate spot the chess board matrix
# First 2 digits: Location of the piece to move, Last 2 digits: Location to move the piece to
def move_replacer(moves):
    moves = moves.replace('1', '0')
    moves = moves.replace('2', '1')
    moves = moves.replace('3', '2')
    moves = moves.replace('4', '3')
    moves = moves.replace('5', '4')
    moves = moves.replace('6', '5')
    moves = moves.replace('7', '6')
    moves = moves.replace('8', '7')

    moves = moves.replace('a', '0')
    moves = moves.replace('b', '1')
    moves = moves.replace('c', '2')
    moves = moves.replace('d', '3')
    moves = moves.replace('e', '4')
    moves = moves.replace('f', '5')
    moves = moves.replace('g', '6')
    moves = moves.replace('h', '7')

    # Handle edge cases
    # Indicates a pawn promotion to queen
    moves = moves.replace('q', '')
    moves = moves.replace('r', '')
    moves = moves.replace('k', '')
    moves = moves.replace('n', '')

    return moves

def play_game(game_data_lan, color):
    """Play through a game and return (kills, deaths, weighted_kills, weighted_deaths, piece_stats).

    piece_stats is a dict keyed by piece-id (only the user's 16 pieces) where each
    value is another dict:
        {
          "captures":          int,   # kills this piece made
          "weighted_captures": int,   # sum of point values it took
          "was_captured":      0|1,
          "turn_captured_on":  int|None,  # 1-indexed move number, or None if survived
          "first_blood":       0|1,   # 1 if this piece made the very first capture
        }

    Note: "first blood" is awarded only if the *user's* piece made the first capture
    of the game. If the opponent struck first, no user piece earns first blood.
    """
    kills = 0
    deaths = 0
    weighted_kills = 0
    weighted_deaths = 0

    # Initialize per-piece tracking for the user's 16 pieces
    if color == "white":
        user_piece_ids = list(range(1, 17))    # 1..16
    elif color == "black":
        user_piece_ids = list(range(17, 33))   # 17..32
    else:
        user_piece_ids = []

    piece_stats = {
        pid: {
            "captures":          0,
            "weighted_captures": 0,
            "was_captured":      0,
            "turn_captured_on":  None,
            "first_blood":       0,
        }
        for pid in user_piece_ids
    }

    # Track whether the very first capture of the game has happened yet
    first_capture_made = False

    # Join the list together as a single string temporarily to reaplace letters faster
    game_data_lan = ','.join(str(x) for x in game_data_lan)
    game_data_lan = move_replacer(game_data_lan)
    game_data_lan = game_data_lan.split(',')

    _dbg("This is what the game data looks like:")
    _dbg(game_data_lan)

    if(game_data_lan == ['']):
        _dbg("No moves found in game data, skipping...")
        return kills, deaths, weighted_kills, weighted_deaths, piece_stats

    if(color == "black"):
        chess_board = copy.deepcopy(chess_board_matrix)
        promotion_tracker = []

        for index, move in enumerate(game_data_lan):
            move_list = list(move)
            move_list = [int(x) for x in move_list]

            _dbg(f"Move#{index + 1}: {move_list}")

            # The piece doing the moving (and potentially capturing)
            mover = chess_board[move_list[1]][move_list[0]]
            captured_piece = chess_board[move_list[3]][move_list[2]]

            if(captured_piece != 0):
                value = piece_value(captured_piece, promotion_tracker)
                if index % 2 != 0:
                    # User (black) made a capture
                    kills += 1
                    weighted_kills += value
                    if mover in piece_stats:
                        piece_stats[mover]["captures"] += 1
                        piece_stats[mover]["weighted_captures"] += value
                        if not first_capture_made:
                            piece_stats[mover]["first_blood"] = 1
                else:
                    # Opponent captured one of the user's pieces
                    deaths += 1
                    weighted_deaths += value
                    if captured_piece in piece_stats and not piece_stats[captured_piece]["was_captured"]:
                        piece_stats[captured_piece]["was_captured"] = 1
                        piece_stats[captured_piece]["turn_captured_on"] = index + 1
                first_capture_made = True

            # Check for Castling
            piece = mover

            if piece in [29, 5]:  # assuming 29 = black king, 5 = white king
                if abs(move_list[2] - move_list[0]) == 2:
                    row = move_list[1]

                    # Kingside castling
                    if move_list[2] == 6:
                        chess_board[row][5] = chess_board[row][7]
                        chess_board[row][7] = 0
                    elif move_list[2] == 2:
                        chess_board[row][3] = chess_board[row][0]
                        chess_board[row][0] = 0

            # Check for En Passant & promotions
            if (piece <= 24 and piece >= 9):
                #En Passant
                if (move_list[0] != move_list[2]) and (chess_board[move_list[3]][move_list[2]] == 0) and (piece not in promotion_tracker):
                    if index % 2 != 0:
                        _dbg(chess_board)
                        kills += 1
                        weighted_kills += 1  # always a pawn
                        # Track for the user's pawn doing the en passant
                        if piece in piece_stats:
                            piece_stats[piece]["captures"] += 1
                            piece_stats[piece]["weighted_captures"] += 1
                            if not first_capture_made:
                                piece_stats[piece]["first_blood"] = 1
                        # Mark the captured pawn (sits one rank away)
                        ep_target = chess_board[move_list[2]][move_list[3]+1]
                        if ep_target in piece_stats and not piece_stats[ep_target]["was_captured"]:
                            piece_stats[ep_target]["was_captured"] = 1
                            piece_stats[ep_target]["turn_captured_on"] = index + 1
                        chess_board[move_list[2]][move_list[3]+1] = 0
                        _dbg(chess_board)
                        _dbg("Black performed an en passant capture!")
                        first_capture_made = True
                    else:
                        _dbg(chess_board)
                        deaths += 1
                        weighted_deaths += 1
                        ep_target = chess_board[move_list[2]][move_list[3]-1]
                        if ep_target in piece_stats and not piece_stats[ep_target]["was_captured"]:
                            piece_stats[ep_target]["was_captured"] = 1
                            piece_stats[ep_target]["turn_captured_on"] = index + 1
                        chess_board[move_list[2]][move_list[3]-1] = 0
                        _dbg(chess_board)
                        _dbg("White performed an en passant capture!")
                        first_capture_made = True

                #Promotions
                if (move_list[3] == 0 or move_list[3] == 7) and (piece not in promotion_tracker):
                    promotion_tracker.append(piece)


            # Move the piece to its new location

            chess_board[move_list[3]][move_list[2]] = chess_board[move_list[1]][move_list[0]]


            chess_board[move_list[1]][move_list[0]] = 0

    elif(color == "white"):
        chess_board = copy.deepcopy(chess_board_matrix)
        promotion_tracker = []

        for index, move in enumerate(game_data_lan):
            move_list = list(move)
            move_list = [int(x) for x in move_list]

            _dbg(f"Move#{index + 1}: {move_list}")

            mover = chess_board[move_list[1]][move_list[0]]
            captured_piece = chess_board[move_list[3]][move_list[2]]

            if(captured_piece != 0):
                value = piece_value(captured_piece, promotion_tracker)
                if index % 2 == 0:
                    # User (white) made a capture
                    kills += 1
                    weighted_kills += value
                    if mover in piece_stats:
                        piece_stats[mover]["captures"] += 1
                        piece_stats[mover]["weighted_captures"] += value
                        if not first_capture_made:
                            piece_stats[mover]["first_blood"] = 1
                else:
                    deaths += 1
                    weighted_deaths += value
                    if captured_piece in piece_stats and not piece_stats[captured_piece]["was_captured"]:
                        piece_stats[captured_piece]["was_captured"] = 1
                        piece_stats[captured_piece]["turn_captured_on"] = index + 1
                first_capture_made = True

            # Check for Castling
            piece = mover

            if piece in [29, 5]:  # assuming 29 = white king, 5 = black king
                if abs(move_list[2] - move_list[0]) == 2:
                    row = move_list[1]

                    # Kingside castling
                    if move_list[2] == 6:
                        chess_board[row][5] = chess_board[row][7]
                        chess_board[row][7] = 0
                    elif move_list[2] == 2:
                        chess_board[row][3] = chess_board[row][0]
                        chess_board[row][0] = 0

            # Check for En Passant & promotions
            if (piece <= 24 and piece >= 9):
                #En Passant
                if (move_list[0] != move_list[2]) and (chess_board[move_list[3]][move_list[2]] == 0) and (piece not in promotion_tracker):
                    if index % 2 == 0:
                        _dbg(chess_board)
                        kills += 1
                        weighted_kills += 1
                        if piece in piece_stats:
                            piece_stats[piece]["captures"] += 1
                            piece_stats[piece]["weighted_captures"] += 1
                            if not first_capture_made:
                                piece_stats[piece]["first_blood"] = 1
                        ep_target = chess_board[move_list[2]][move_list[3]-1]
                        if ep_target in piece_stats and not piece_stats[ep_target]["was_captured"]:
                            piece_stats[ep_target]["was_captured"] = 1
                            piece_stats[ep_target]["turn_captured_on"] = index + 1
                        chess_board[move_list[2]][move_list[3]-1] = 0
                        _dbg(chess_board)
                        _dbg("White performed an en passant capture!")
                        first_capture_made = True
                    else:
                        _dbg(chess_board)
                        deaths += 1
                        weighted_deaths += 1
                        ep_target = chess_board[move_list[2]][move_list[3]+1]
                        if ep_target in piece_stats and not piece_stats[ep_target]["was_captured"]:
                            piece_stats[ep_target]["was_captured"] = 1
                            piece_stats[ep_target]["turn_captured_on"] = index + 1
                        chess_board[move_list[2]][move_list[3]+1] = 0
                        _dbg(chess_board)
                        _dbg("Black performed an en passant capture!")
                        first_capture_made = True

                #Promotions
                if (move_list[3] == 0 or move_list[3] == 7) and (piece not in promotion_tracker):
                    promotion_tracker.append(piece)


            # Move the piece to its new location

            chess_board[move_list[3]][move_list[2]] = chess_board[move_list[1]][move_list[0]]


            chess_board[move_list[1]][move_list[0]] = 0




    # print("Does the color work?: ", color)
    _dbg(f"Kills: {kills}, Deaths: {deaths}, Weighted Kills: {weighted_kills}, Weighted Deaths: {weighted_deaths}")



    return kills, deaths, weighted_kills, weighted_deaths, piece_stats

def find_game_info(game_data, username):
    if (game_data["white"]["username"].lower() == username):
        return "white"
    elif (game_data["black"]["username"].lower() == username):
        return "black"
    else:
        return "unknown"

# Test move parser functionality

#integral = '1234'
#digits = move_parser(integral)
#print(digits[1] + digits[2])