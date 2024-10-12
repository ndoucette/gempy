#!/usr/bin/env python3

import curses
import logging
import os
import platform
import re
import subprocess
import sys
import time
from typing import List, Dict

import yaml  # Import PyYAML to parse the config file

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Constants for Lich and Profanity binaries will be set from the config file
LICH_BIN = ""
PROFANITY_BIN = ""
DEBUG = True  # Set to False to disable debug output

# Configuration file path
CONFIG_FILE = 'config.yaml'


def load_config():
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"Configuration file {CONFIG_FILE} not found.")
        sys.exit(1)

    with open(CONFIG_FILE, 'r') as f:
        try:
            config = yaml.safe_load(f)
            return config
        except yaml.YAMLError as e:
            logger.error(f"Error parsing configuration file: {e}")
            sys.exit(1)


def init_paths(config):
    global LICH_BIN, PROFANITY_BIN

    paths = config.get('paths', {})
    LICH_BIN = paths.get('lich_bin', '')
    PROFANITY_BIN = paths.get('profanity_bin', '')

    if not LICH_BIN or not PROFANITY_BIN:
        logger.error("LICH_BIN and PROFANITY_BIN paths must be specified in the configuration file.")
        sys.exit(1)

    # Verify that the paths exist
    if not os.path.exists(LICH_BIN):
        logger.error(f"Error: LICH_BIN path does not exist: {LICH_BIN}")
        sys.exit(1)
    if not os.path.exists(PROFANITY_BIN):
        logger.error(f"Error: PROFANITY_BIN path does not exist: {PROFANITY_BIN}")
        sys.exit(1)

    if DEBUG:
        logger.debug(f"LICH_BIN set to: {LICH_BIN}")
        logger.debug(f"PROFANITY_BIN set to: {PROFANITY_BIN}")


class CharacterStatus:
    def __init__(self, name: str, online: bool, port: int):
        self.name = name
        self.online = online
        self.port = port


def main(stdscr, config):
    curses.curs_set(0)  # Hide the cursor
    stdscr.nodelay(0)   # Wait for user input
    stdscr.keypad(True)

    # Initialize color pairs for text styling
    curses.start_color()
    curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLACK)   # Default
    curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)   # Online
    curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # Selected

    # Define accounts and characters from the config
    accounts = config.get('accounts', {})
    columns = [{'header': account, 'items': chars} for account, chars in accounts.items()]

    current_column = 0
    current_item = 0
    message = ""

    # Get initial online status for all characters
    character_statuses = get_character_statuses(columns)

    draw_screen(stdscr, columns, current_column, current_item, message, character_statuses)

    while True:
        key = stdscr.getch()
        if key == curses.KEY_UP:
            if current_item > 0:
                current_item -= 1
        elif key == curses.KEY_DOWN:
            if current_item < len(columns[current_column]['items']) - 1:
                current_item += 1
        elif key == curses.KEY_LEFT:
            if current_column > 0:
                current_column -= 1
                current_item = 0
        elif key == curses.KEY_RIGHT:
            if current_column < len(columns) - 1:
                current_column += 1
                current_item = 0
        elif key == curses.KEY_ENTER or key == 10 or key == 13:
            selected_char = columns[current_column]['items'][current_item]
            message = f"Launching {selected_char}"
            draw_screen(stdscr, columns, current_column, current_item, message, character_statuses)
            curses.endwin()
            launch_gemstone(selected_char)
            return
        elif key == ord('r'):
            # Refresh character statuses
            character_statuses = get_character_statuses(columns)
            message = "Refreshed character statuses"
        elif key == curses.KEY_RESIZE:
            stdscr.clear()
            stdscr.refresh()
        elif key == 27:  # Escape key
            curses.endwin()
            sys.exit(0)

        draw_screen(stdscr, columns, current_column, current_item, message, character_statuses)


def draw_screen(stdscr, columns, current_column, current_item, message, character_statuses):
    stdscr.clear()
    height, width = stdscr.getmaxyx()
    num_columns = len(columns)
    column_width = max(width // num_columns, 20)  # Ensure a minimum column width

    # Check if the terminal is tall enough
    max_items = max(len(col['items']) for col in columns)
    if height < max_items + 3:  # Additional space for header and message
        stdscr.addstr(0, 0, "Terminal window is too small. Please resize.", curses.A_BOLD)
        stdscr.refresh()
        return

    for col_index, column in enumerate(columns):
        x = col_index * column_width

        # Draw header
        header = column['header']
        try:
            stdscr.addstr(0, x, header.center(column_width - 1), curses.A_REVERSE)
        except curses.error:
            pass  # Ignore errors caused by writing outside the screen

        # Draw items
        for item_index, item in enumerate(column['items']):
            y = item_index + 1
            if y >= height - 1:
                continue  # Skip if beyond screen height

            status = character_statuses.get(item)
            prefix = "  "
            style = curses.color_pair(1)

            if col_index == current_column and item_index == current_item:
                style |= curses.A_BOLD
                prefix = "> "

            # Add [Online] status if character is online
            if status and status.online:
                item_display = f"{item} [Online]"
                style |= curses.color_pair(2)  # Green text
            else:
                item_display = item

            try:
                stdscr.addstr(y, x, (prefix + item_display).ljust(column_width - 1), style)
            except curses.error:
                pass  # Ignore errors caused by writing outside the screen

    # Draw message at the bottom
    try:
        stdscr.addstr(height - 1, 0, message.ljust(width - 1), curses.A_REVERSE)
    except curses.error:
        pass  # Ignore errors caused by writing outside the screen

    stdscr.refresh()


def get_character_statuses(columns) -> Dict[str, CharacterStatus]:
    statuses = {}
    process_output = get_process_list()

    for column in columns:
        for char in column['items']:
            port = lookup_char_port(char, process_output)
            online = port != 0
            statuses[char] = CharacterStatus(name=char, online=online, port=port)
            if DEBUG:
                logger.debug(f"Character {char} - Online: {online}, Port: {port}")

    return statuses


def get_process_list() -> str:
    try:
        output = subprocess.check_output(['ps', 'ax'], universal_newlines=True)
        return output
    except subprocess.CalledProcessError as e:
        logger.error(f"Error getting process list: {e}")
        return ""


def lookup_char_port(char: str, process_output: str) -> int:
    # Make the regex case-insensitive and more flexible
    pattern = re.compile(rf'--login\s+{re.escape(char)}\s+.*?--detachable-client=(\d+)', re.IGNORECASE)
    matches = pattern.findall(process_output)
    if matches:
        port = int(matches[0])
        return port

    if DEBUG:
        logger.debug(f"No match found for character {char} in process list")
        # Uncomment the following line to print the entire process list for debugging
        # logger.debug(f"Process list: {process_output}")

    return 0


def launch_gemstone(char: str):
    os.environ['TERM'] = 'screen-256color'

    if os.getenv('DISPLAY', '') == '':
        os.environ['DISPLAY'] = ':0'
        logger.info("Detected empty DISPLAY setting, defaulting to :0")

    logger.info(f"Attempting to login as {char}...")

    port = 8000
    process_output = get_process_list()
    if is_character_running(char, process_output):
        port = lookup_char_port(char, process_output)
        logger.info(f"Detecting existing connection on port {port}")
    else:
        existing_clients = get_existing_clients()
        if existing_clients:
            max_port = max(existing_clients)
            port = max_port + 1
        logger.info(f"Detecting existing clients but no connection for this character. Using Port[{port}]")
        start_lich_backend(char, port)
        time.sleep(4)  # Wait for the backend to initialize

    connect_to_lich(char, port)


def is_character_running(char: str, process_output: str) -> bool:
    return lookup_char_port(char, process_output) != 0


def get_existing_clients() -> List[int]:
    try:
        output = subprocess.check_output(['ps', 'a'], universal_newlines=True)
        pattern = re.compile(r'--detachable-client=(\d+)')
        matches = pattern.findall(output)
        ports = [int(port) for port in matches]
        return ports
    except subprocess.CalledProcessError as e:
        logger.error(f"Error getting existing clients: {e}")
        return []


def start_lich_backend(char: str, port: int):
    lich_path = os.path.abspath(LICH_BIN)
    cmd = [
        'ruby',
        lich_path,
        '--login',
        char,
        f'--detachable-client={port}',
        '--without-frontend'
    ]
    try:
        subprocess.Popen(cmd, stderr=subprocess.PIPE)
    except Exception as e:
        logger.error(f"Error starting Lich backend: {e}")


def connect_to_lich(char: str, port: int):
    profanity_path = os.path.abspath(PROFANITY_BIN)
    for attempt in range(10):
        logger.info(f"Attempting to connect to lich process... (Attempt {attempt + 1}/10)")
        cmd = [
            'ruby',
            profanity_path,
            f'--port={port}',
            f'--char={char}'
        ]
        try:
            subprocess.run(cmd, check=True)
            logger.info("Connection established. Exiting.")
            return
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to establish connection: {e}")
            logger.info("Trying again in 3 seconds...")
            time.sleep(3)
    logger.error("Failed to connect after 10 attempts")


if __name__ == '__main__':
    config = load_config()
    init_paths(config)
    try:
        curses.wrapper(main, config)
    except KeyboardInterrupt:
        curses.endwin()
        logger.info("Application exited by user")
    except Exception as e:
        curses.endwin()
        logger.error(f"An unexpected error occurred: {e}")
        sys.exit(1)
