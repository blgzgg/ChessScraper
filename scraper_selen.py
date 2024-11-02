from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import time

# Set up Chrome options
chrome_options = Options()
chrome_options.add_argument("--headless")  # Run in headless mode (no GUI)

# Path to your ChromeDriver
chrome_driver_path = 'C:/ChromeDriver/chromedriver-win64/chromedriver.exe'

def extract_moves_with_selenium(game_url):
    """Extract moves from a game analysis page using Selenium."""
    service = Service(chrome_driver_path)
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    driver.get(game_url)
    time.sleep(3)  # Allow the page to load (adjust this based on load times)

    try:
        # Find the move list using Selenium
        move_list_element = driver.find_element(By.CSS_SELECTOR, 'wc-move-list.analysis-view-movelist')
        
        # Extract the move elements
        move_rows = move_list_element.find_elements(By.CLASS_NAME, 'main-line-row')
        moves = []

        for row in move_rows:
            # Extract white move if present
            white_move_div = row.find_elements(By.CLASS_NAME, 'white-move')  # Using find_elements to avoid exceptions
            if white_move_div:
                white_move = extract_move_selenium(white_move_div[0])  # Access the first element
                if white_move:
                    moves.append(white_move)

            # Extract black move if present
            black_move_div = row.find_elements(By.CLASS_NAME, 'black-move')  # Using find_elements to avoid exceptions
            if black_move_div:
                black_move = extract_move_selenium(black_move_div[0])  # Access the first element
                if black_move:
                    moves.append(black_move)
        
        driver.quit()
        return moves

    except Exception as e:
        print(f"Error occurred: {e}")
        driver.quit()
        return []

def extract_move_selenium(move_div):
    """Extract a move from a specific div element."""
    # Try to extract the piece being moved from the data-figurine attribute (if present)
    try:
        figurine_span = move_div.find_element(By.CSS_SELECTOR, 'span.icon-font-chess')
        piece = piece_notation.get(figurine_span.get_attribute('data-figurine'), '')  # Get piece notation or empty for pawns
    except Exception:
        piece = ''  # If no chess piece icon is found, default to pawn (which has no notation)

    # Try to extract the destination square from the move text
    try:
        move_text_span = move_div.find_element(By.CSS_SELECTOR, 'span.node-highlight-content')
        move_text = move_text_span.text.strip()  # Get the move's destination square
    except Exception:
        move_text = ''  # If no move text is found, return empty

    # Return the move in chess notation format
    return piece + move_text

# Example test run
game_url = "https://www.chess.com/analysis/game/live/115351119473?tab=analysis"
moves = extract_moves_with_selenium(game_url)
print("Moves:", moves)
