#!/usr/bin/env python3

import curses
import logging
import os
import platform
import re
import subprocess
import sys
import time
import threading
import socket
from typing import List, Dict

import yaml  # Import PyYAML to parse the config file

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
# Persist launcher diagnostics; frontend output may contain browser credentials.
file_handler = logging.FileHandler(os.path.join(os.path.dirname(__file__), 'gempy.log'))
file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
logger.addHandler(file_handler)

# Constants for Lich and Profanity binaries will be set from the config file
LICH_BIN = ""
VELLUM_BIN = ""
FRONTEND = "profanity"
PROFANITY_BIN = ""
PROFANITY_TEMPLATE = ""  # optional bundled template (used when no ~/.profanity/<char>.xml exists)
DEBUG = True  # Set to False to disable debug output
TERMINAL_SERVICE = None

# Configuration file path
CONFIG_FILE = 'config.yaml'

# Realms we can log into. The Lich flags are what select the game instance:
# `--gemstone --test` resolves to game code GST, which Lich falls back to the
# saved GS3 (prime) entry for — so no separate saved login is needed for test.
# `--test` on its own is NOT enough: without --gemstone Lich fails instance
# resolution and refuses the login.
PRIME = 'prime'
TEST = 'test'
REALM_ORDER = [PRIME, TEST]
DEFAULT_REALM_FLAGS = {
    PRIME: ['--gemstone'],           # GS3: modern Lich requires an explicit game
    TEST: ['--gemstone', '--test'],   # GST
}
REALM_FLAGS = dict(DEFAULT_REALM_FLAGS)


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


def init_realms(config):
    """Realm flags are overridable in config.yaml, e.g.

    realms:
      test: ["--gemstone", "--test"]
    """
    global REALM_FLAGS

    REALM_FLAGS = dict(DEFAULT_REALM_FLAGS)
    for realm, flags in (config.get('realms') or {}).items():
        if realm not in REALM_FLAGS:
            logger.warning(f"Ignoring unknown realm in config: {realm}")
            continue
        if isinstance(flags, str):
            flags = flags.split()
        REALM_FLAGS[realm] = list(flags or [])

    if DEBUG:
        logger.debug(f"Realm flags: {REALM_FLAGS}")


def init_paths(config):
    global LICH_BIN, PROFANITY_BIN, PROFANITY_TEMPLATE, VELLUM_BIN, FRONTEND

    FRONTEND = config.get('frontend', 'profanity')
    if FRONTEND not in ('profanity', 'vellum_despana', 'vellum_web', 'vellum_gui', 'vellum_tui', 'saga'):
        raise ValueError('Unknown frontend')
    paths = config.get('paths', {})
    VELLUM_BIN = paths.get('vellum_bin', '')
    LICH_BIN = paths.get('lich_bin', '')
    PROFANITY_BIN = paths.get('profanity_bin', '')
    PROFANITY_TEMPLATE = config.get('profanity_template', '')

    frontend_bin = VELLUM_BIN if FRONTEND.startswith('vellum_') else PROFANITY_BIN
    if FRONTEND == 'saga':
        from client_options import saga_binary
        frontend_bin = saga_binary(config)
    for path in (LICH_BIN, frontend_bin):
        if not path or not os.path.isfile(path):
            raise ValueError(f"Missing configured binary: {path}")


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
    curses.init_pair(4, curses.COLOR_MAGENTA, curses.COLOR_BLACK)  # Test realm

    # Define accounts and characters from the config
    accounts = config.get('accounts', {})
    columns = [{'header': account, 'items': chars} for account, chars in accounts.items()]

    current_column = 0
    current_item = 0
    realm = config.get('default_realm', PRIME)
    if realm not in REALM_ORDER:
        logger.warning(f"Unknown default_realm {realm!r}; falling back to {PRIME}")
        realm = PRIME
    message = "Enter=login  t=toggle server  r=refresh  Esc=quit"

    # Get initial online status for all characters
    character_statuses = get_character_statuses(columns, realm)

    draw_screen(stdscr, columns, current_column, current_item, message, character_statuses, realm)

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
            message = f"Launching {selected_char} on {realm.upper()}"
            draw_screen(stdscr, columns, current_column, current_item, message, character_statuses, realm)
            curses.endwin()
            launched = launch_gemstone(selected_char, realm)
            if FRONTEND in ('profanity', 'vellum_tui'):
                return
            stdscr.refresh()
            character_statuses = get_character_statuses(columns, realm)
            message = "Enter=login  t=toggle server  r=refresh  Esc=quit" if launched else "Startup failed; see gempy.log. Enter=retry  Esc=quit"
        elif key in (ord('t'), ord('T')):
            # The status-bar tag already reports the realm, so leave the
            # message as the key hint rather than echoing it twice.
            realm = REALM_ORDER[(REALM_ORDER.index(realm) + 1) % len(REALM_ORDER)]
            character_statuses = get_character_statuses(columns, realm)
        elif key in (ord('r'), ord('R')):
            # Refresh character statuses
            character_statuses = get_character_statuses(columns, realm)
            message = "Refreshed character statuses"
        elif key == curses.KEY_RESIZE:
            stdscr.clear()
            stdscr.refresh()
        elif key == 27:  # Escape key
            curses.endwin()
            sys.exit(0)

        draw_screen(stdscr, columns, current_column, current_item, message, character_statuses, realm)


def draw_screen(stdscr, columns, current_column, current_item, message, character_statuses, realm=PRIME):
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
            attrs = 0

            if col_index == current_column and item_index == current_item:
                attrs |= curses.A_BOLD
                prefix = "> "

            # Add [Online] status if character is online in the selected realm.
            # Colour pairs are assigned, never OR'd: pair(1) | pair(2) is pair(3).
            if status and status.online:
                item_display = f"{item} [Online]"
                style = curses.color_pair(2) | attrs  # Green text
            else:
                item_display = item
                style = curses.color_pair(1) | attrs

            try:
                stdscr.addstr(y, x, (prefix + item_display).ljust(column_width - 1), style)
            except curses.error:
                pass  # Ignore errors caused by writing outside the screen

    # Status bar: message on the left, target server pinned to the right.
    # Test is coloured so an accidental test login is obvious before Enter.
    try:
        stdscr.addstr(height - 1, 0, message.ljust(width - 1)[:width - 1], curses.A_REVERSE)
    except curses.error:
        pass  # Ignore errors caused by writing outside the screen

    tag = f" SERVER: {realm.upper()} "
    tag_style = curses.A_REVERSE | curses.A_BOLD | (curses.color_pair(4) if realm == TEST else curses.color_pair(2))
    tag_x = width - 1 - len(tag)
    # Drop the tag rather than overwrite the message on a narrow terminal.
    if tag_x > len(message):
        try:
            stdscr.addstr(height - 1, tag_x, tag, tag_style)
        except curses.error:
            pass  # Ignore errors caused by writing outside the screen

    stdscr.refresh()


def get_character_statuses(columns, realm: str = PRIME) -> Dict[str, CharacterStatus]:
    statuses = {}
    if TERMINAL_SERVICE is not None:
        sessions = TERMINAL_SERVICE.sessions()
        for column in columns:
            for char in column['items']:
                match = next((session for session in sessions
                              if session['character'].lower() == char.lower()
                              and session['realm'] == realm), None)
                statuses[char] = CharacterStatus(char, bool(match), match['port'] if match else 0)
        return statuses
    process_output = get_process_list()

    for column in columns:
        for char in column['items']:
            port = lookup_char_port(char, process_output, realm)
            online = port != 0
            statuses[char] = CharacterStatus(name=char, online=online, port=port)
            if DEBUG:
                logger.debug(f"Character {char} ({realm}) - Online: {online}, Port: {port}")

    return statuses


def get_process_list() -> str:
    try:
        output = subprocess.check_output(['ps', 'ax'], universal_newlines=True)
        return output
    except subprocess.CalledProcessError as e:
        logger.error(f"Error getting process list: {e}")
        return ""


def lookup_char_port(char: str, process_output: str, realm: str = PRIME) -> int:
    """Port of a running Lich backend for this character *in this realm*.

    A character can legitimately be logged into prime and test at the same
    time, so the realm's flags have to be part of the match — otherwise the
    launcher would happily attach a prime request to a live test session.
    """
    pattern = re.compile(rf'--login\s+{re.escape(char)}\s+.*?--detachable-client=(\d+)', re.IGNORECASE)
    other_flags = {flag for other, flags in REALM_FLAGS.items() if other != realm for flag in flags}
    wanted_flags = [flag for flag in REALM_FLAGS.get(realm, []) if flag not in ('--gemstone', '--gs')]
    other_flags.difference_update(('--gemstone', '--gs'))
    # Flags unique to some *other* realm disqualify a line; a realm with no
    # flags of its own (prime) is identified by the absence of those.
    disqualifying = [flag for flag in other_flags if flag not in wanted_flags]

    for line in process_output.splitlines():
        match = pattern.search(line)
        if not match:
            continue
        if any(flag in line.split() for flag in disqualifying):
            continue
        if not all(flag in line.split() for flag in wanted_flags):
            continue
        return int(match.group(1))

    if DEBUG:
        logger.debug(f"No match found for character {char} ({realm}) in process list")

    return 0


def launch_gemstone(char: str, realm: str = PRIME):
    os.environ['TERM'] = 'screen-256color'

    if os.getenv('DISPLAY', '') == '':
        os.environ['DISPLAY'] = ':0'
        logger.info("Detected empty DISPLAY setting, defaulting to :0")

    logger.info(f"Attempting to login as {char} on the {realm} server...")
    if TERMINAL_SERVICE is not None:
        try:
            if FRONTEND in ('vellum_gui', 'vellum_web', 'saga'):
                result = TERMINAL_SERVICE.launch(char, realm, FRONTEND)
                if FRONTEND == 'vellum_web':
                    import webbrowser
                    webbrowser.open(f"http://127.0.0.1:{result['web_port']}{result['pairing_path']}")
                return True
            session = TERMINAL_SERVICE.ensure_backend(char, realm)
            return connect_to_lich(char, session['port'], realm)
        except Exception:
            logger.error('Unable to prepare the game session; check Lich logs.')
            return False

    port = 8000
    process_output = get_process_list()
    if is_character_running(char, process_output, realm):
        port = lookup_char_port(char, process_output, realm)
        logger.info(f"Detecting existing {realm} connection on port {port}")
    else:
        existing_clients = get_existing_clients()
        if existing_clients:
            max_port = max(existing_clients)
            port = max_port + 1
        logger.info(f"Detecting existing clients but no connection for this character. Using Port[{port}]")
        backend = start_lich_backend(char, port, realm)
        if not backend:
            return False
        # Wait for Lich's FE listener PASSIVELY (/proc/net/tcp) — never by
        # connecting: Lich's detachable listener is single-client, and a
        # connect probe landing mid-login wedges its accept loop.
        if not wait_for_port_listen(port, process=backend):
            logger.error(f"Lich never opened port {port} — check login/flags (is the character name in Lich's saved entries?)")
            return
        time.sleep(2)  # let login settle before the FE attaches

    return connect_to_lich(char, port, realm)


def wait_for_port_listen(port: int, timeout: float = 120.0, process=None) -> bool:
    """True once 127.0.0.1:<port> is in LISTEN state, checked passively
    via /proc/net/tcp{,6} (state 0A), polling until timeout."""
    hex_port = format(port, '04X')
    pattern = re.compile(rf':{hex_port} [0-9A-F]+:0+ 0A ', re.IGNORECASE)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process is not None and process.poll() is not None:
            logger.error("Lich exited before opening port %s (status %s); check Ruby requirements and Lich logs", port, process.returncode)
            return False
        for path in ('/proc/net/tcp', '/proc/net/tcp6'):
            try:
                with open(path, 'r') as f:
                    if pattern.search(f.read()):
                        return True
            except OSError:
                pass
        time.sleep(0.5)
    return False


def is_character_running(char: str, process_output: str, realm: str = PRIME) -> bool:
    return lookup_char_port(char, process_output, realm) != 0


def get_existing_clients() -> List[int]:
    try:
        output = subprocess.check_output(['ps', 'ax'], universal_newlines=True)
        pattern = re.compile(r'--detachable-client=(\d+)')
        matches = pattern.findall(output)
        ports = [int(port) for port in matches]
        return ports
    except subprocess.CalledProcessError as e:
        logger.error(f"Error getting existing clients: {e}")
        return []


def start_lich_backend(char: str, port: int, realm: str = PRIME):
    lich_path = os.path.abspath(LICH_BIN)
    cmd = [
        'ruby',
        lich_path,
        '--login',
        char,
        f'--detachable-client={port}',
        '--without-frontend'
    ]
    cmd.extend(REALM_FLAGS.get(realm, []))
    logger.info(f"Starting Lich backend: {' '.join(cmd)}")
    try:
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception as e:
        logger.error(f"Error starting Lich backend: {e}")
        return False


def allocate_web_port():
    # Older Vellum binaries format the browser URL from the configured port,
    # so port zero opens an unusable URL. Allocate a real loopback port here.
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def vellum_command(char: str, port: int, realm: str = PRIME):
    return [os.path.abspath(VELLUM_BIN), '--launch-profile',
            f'gempy-{char}-{realm}', '--port', str(port), '--host', '127.0.0.1',
            '--web-port', str(allocate_web_port()), '--web-bind', '0.0.0.0']


def connect_to_lich(char: str, port: int, realm: str = PRIME):
    if FRONTEND == 'vellum_tui':
        from client_options import vellum_command as native_command
        subprocess.run(native_command(os.path.abspath(VELLUM_BIN), char, realm, port, 'tui'), check=True)
        return True
    if FRONTEND == 'vellum_despana':
        try:
            # Vellum owns browser opening. Discard output containing pairing URLs;
            # its exit status records startup failures without logging secrets.
            process = subprocess.Popen(vellum_command(char, port, realm),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True)
            def monitor():
                status = process.wait()
                if status:
                    logger.error("Vellum exited for %s (%s), status %s", char, realm, status)
            threading.Thread(target=monitor, daemon=True).start()
            time.sleep(1)
            if process.poll() is not None:
                return False
            return True
        except OSError:
            logger.error("Unable to start Vellum for %s (%s)", char, realm)
            return False

    profanity_path = os.path.abspath(PROFANITY_BIN)
    # A per-character layout in ~/.profanity/ always wins; the configured
    # template is only the fallback for characters without one (profanity's
    # --template flag would otherwise override per-char files).
    user_layout = os.path.expanduser(f'~/.profanity/{char.lower()}.xml')
    use_template = PROFANITY_TEMPLATE and not os.path.exists(user_layout)
    for attempt in range(10):
        logger.info(f"Attempting to connect to lich process... (Attempt {attempt + 1}/10)")
        cmd = [
            'ruby',
            profanity_path,
            f'--port={port}',
            f'--char={char}'
        ]
        if use_template:
            cmd.append(f'--template={PROFANITY_TEMPLATE}')
        try:
            subprocess.run(cmd, check=True)
            logger.info("Connection established. Exiting.")
            return
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to establish connection: {e}")
            logger.info("Trying again in 3 seconds...")
            time.sleep(3)
    logger.error("Failed to connect after 10 attempts")


def cli():
    global TERMINAL_SERVICE
    import argparse
    parser = argparse.ArgumentParser(description="Gempy terminal launcher and web daemon")
    parser.add_argument('--web', action='store_true', help='run the persistent web service')
    parser.add_argument('--host', default='127.0.0.1', help='web bind address (default: loopback)')
    parser.add_argument('--port', type=int, default=8080, help='web port (default: 8080)')
    parser.add_argument('--set-password', action='store_true', help='set the Gempy administrator password')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    if args.set_password:
        from web_app import setup_password
        try:
            setup_password()
        except ValueError as error:
            parser.error(str(error))
        return
    config = load_config()
    if args.web:
        from web_app import create_app
        import uvicorn
        # A single process owns coordinated launch and operation locks.
        try:
            app = create_app(config, config_path=CONFIG_FILE)
        except RuntimeError as error:
            parser.error(str(error))
        uvicorn.run(app, host=args.host, port=args.port, workers=1,
                    access_log=False)
        return
    init_paths(config)
    init_realms(config)
    from gempy_service import Service
    TERMINAL_SERVICE = Service(config)
    try:
        curses.wrapper(main, config)
    except KeyboardInterrupt:
        curses.endwin()
        logger.info("Application exited by user")
    except Exception as e:
        curses.endwin()
        logger.error(f"An unexpected error occurred: {e}")
        sys.exit(1)


if __name__ == '__main__':
    cli()
