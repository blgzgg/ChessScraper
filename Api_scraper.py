from move_parser import ChessGameProcessor

def process_game_data(game_data):
    """
    Parses game metadata and saves both game and move data to the database.
    """
    # Parse PGN and metadata
    pgn = io.StringIO(game_data['pgn'])
    game = chess.pgn.read_game(pgn)
    metadata = game.headers

    # Check if the game already exists in the database
    existing_game = session.query(Game).filter_by(url=game_data['url']).first()
    if existing_game:
        print(f"Game already exists. Overwriting: {game_data['url']}")
        session.delete(existing_game)
        session.commit()

    # Create a new game record
    game_record = Game(
        url=game_data['url'],
        white_player=metadata["White"],
        black_player=metadata["Black"],
        white_rating=metadata.get("WhiteElo"),
        black_rating=metadata.get("BlackElo"),
        result=metadata["Result"],
        date_played=datetime.strptime(metadata["UTCDate"], "%Y.%m.%d"),
        pgn=game_data['pgn']
    )
    session.add(game_record)
    session.commit()

    # Pass the PGN to ChessGameProcessor for move parsing
    processor = ChessGameProcessor(game_data['pgn'])
    processor.process_and_save_game(game_record)

def collect_games(username):
    """
    Fetches game data and processes each game.
    """
    archives = fetch_archives(username)
    for archive_url in archives:
        print(f"Fetching games from {archive_url}...")
        try:
            archive_data = fetch_game_data(archive_url)
            for game_data in archive_data:
                process_game_data(game_data)
        except requests.exceptions.RequestException as e:
            print(f"Error fetching data from {archive_url}: {e}")
            continue
