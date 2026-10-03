## Persistent web service

The web workspace shows sessions at the top, with a searchable character roster below.
Use **Add a character** to enter a character name already saved in Lich and choose
an existing account label or create a new one. Account labels organize the roster;
Lich uses its saved login for authentication. Additions are saved to `config.yaml`
and are available immediately, including after restarting Gempy.

The terminal launcher remains available with `./run.sh`. For a Linux web daemon,
configure your existing Lich saved logins and set `paths.vellum_bin` to the
installed Vellum executable. The web interface has its own client selector. No desktop environment is required.

Set the single Gempy administrator password interactively, then start the server:

```bash
./run.sh --set-password
./run.sh --web
```

Open `http://127.0.0.1:8080` and sign in. Gempy stores a salted password hash
in private application state under `${XDG_STATE_HOME:-$HOME/.local/state}/gempy`;
it does not store the password itself. Login sessions expire, login attempts are
throttled, and state-changing requests require a CSRF token. Use **Log out** on
shared browsers. This login is separate from your Lich saved game logins. After
changing the password with `--set-password`, restart the daemon to apply it and
revoke existing Gempy login sessions.

The **Characters** tab lists configured accounts and lets you choose Prime or
Test before launching. A launch reuses a matching running Lich session. The
**Sessions** tab also discovers local sessions started outside Gempy and shows
**Attached**, **Headless**, or **Unknown** client status. **Open/Attach client**
opens Despana in a new tab; allow pop-ups for Gempy if your browser blocks it.
Status refreshes every three seconds. Attachment is checked passively and is not
a measure of open browser tabs.

**Disconnect** asks for confirmation and requests an orderly Lich exit. Allow
up to 70 seconds for cleanup. If orderly exit fails, a separately confirmed
**Force Disconnect** can terminate the revalidated process. Successful disconnect
also removes managed frontend processes. Closing a browser tab, logging out of
Gempy, or stopping/restarting the daemon leaves game and Vellum sessions running;
the next daemon start rediscovers them.

For LAN or Tailscale access, bind Gempy to all interfaces:

```bash
./run.sh --web --host 0.0.0.0 --port 8080
```

Visit `http://<server-LAN-or-Tailscale-hostname>:8080`. Despana links use the
hostname you used to access Gempy and Vellum's actual web port. Gempy and Vellum
use separate ports: both must be reachable from your browser, including through
any host firewall. Vellum keeps its pairing authentication; treat pairing URLs
as secrets. Gempy returns them only after login and excludes them from logs.

This mode is intended for a trusted LAN or Tailscale network with one
administrator, not deployment directly on the public internet. Plain HTTP does
not encrypt LAN traffic. Use Tailscale for access over untrusted networks.
Run one daemon worker so operation locks and port allocation remain coordinated.

An optional systemd user-service example is in
[`examples/gempy.service`](examples/gempy.service). Edit its paths for your
checkout, run password setup as the same user first, and install it yourself:

```bash
mkdir -p ~/.config/systemd/user
cp examples/gempy.service ~/.config/systemd/user/gempy.service
# Edit ~/.config/systemd/user/gempy.service before starting it.
systemctl --user daemon-reload
systemctl --user enable --now gempy.service
journalctl --user -u gempy.service
```

To keep a user service running after logout, configure user lingering separately
if needed (`loginctl enable-linger "$USER"`). No service is installed or enabled
by Gempy. The example uses `KillMode=process` so stopping it leaves launched game
and frontend processes alive. Keep that setting when adapting the unit.

## Other clients

Choose **Client** above the roster; the choice applies to launches and existing
session attachments. **Vellum Despana** remains the default. **Vellum Web / mobile**
opens the `/play` layout using the same authenticated Vellum engine, so switching
browser layouts does not create another game login.

**Vellum desktop** and **Vellum terminal** open on the computer running Gempy.
The desktop needs a graphical display. The terminal choice opens a terminal
emulator; configure `clients.terminal_command` as an argument list if needed
(for example `['xterm', '-e']`). A browser on another device does not cause
these windows to open on that device. **Connection details** provides desktop,
terminal, and SSH tunnel commands for connecting from another computer without
exposing Lich's unauthenticated listener to the network. Replace `USER@SERVER`
in the tunnel command with your SSH login. Vellum mobile apps can also pair
with the existing web session; use Vellum's pairing workflow.

**Saga (experimental)** starts an installed Saga against the matching Lich
session. Set `paths.saga_bin` to its executable or Linux AppImage. On Windows/WSL,
Gempy also discovers `C:\Program Files\Saga\Saga.exe`. Saga must be closed first:
its single-instance relay does not preserve the connection's host and port.
Gempy passes the detachable connection through environment variables, including
WSL's Windows environment forwarding, and intentionally omits a proxy login key.
It reports success only after a new socket appears on Lich's listener.
Windows Saga must be able to reach WSL at `127.0.0.1`; the tested installation
uses the existing WSL localhost networking. On older Lich versions accepting a
single client, close the attached frontend before opening another one.

Native client windows remain under your control. Closing a native client leaves
Lich running; **Disconnect** ends the game session. Gempy does not force-close
Windows Saga or a terminal emulator. A missing display/client or startup timeout
returns an error; if a window opened despite a timeout, check it before retrying.

The terminal launcher can select `frontend: vellum_gui`, `vellum_tui`,
`vellum_web`, or `saga` in `config.yaml`. Vellum TUI uses the current terminal.
Restart Gempy after changing its configuration or installing these changes.

## Vellum Despana setup

Run `./run.sh` from this directory. The ignored `config.yaml` selects
`frontend: vellum_despana`, the shared `/home/nick/gs4/Lich5/lich.rbw`,
and `/home/nick/gs4/vellum-fe`. Python requirements are installed in `.venv`.
Prime is the default; press `t` to switch to Test, then Enter to launch.
The menu stays available for additional characters while Vellum runs in the
background. Startup failures are recorded in `gempy.log`; frontend output
containing authenticated browser URLs is never copied into that log.

Each character has `gempy-<Character>-prime` and `gempy-<Character>-test`
profiles in `~/.vellum-fe/launcher.toml`. They use Lich mode,
`web_client = "despana"`, `web_port = 0` for automatic allocation, and
all-interface web binding (`0.0.0.0`) for LAN access. Gempy allocates an available loopback web port and passes
it explicitly to Vellum, so installed builds that open port-zero browser
URLs still open the correct session. Existing per-character Vellum settings
are reused.
Vellum opens the authenticated browser URL itself. Gempy starts Lich,
waits passively for its detachable listener, and supplies the actual port
when launching the matching saved profile. Existing Lich sessions are reused
only when their character and realm match.

The shared configurations were backed up beside the originals as
`entry.yaml.gempy-20260930-backup` and
`launcher.toml.gempy-20260930-backup`. Saved passwords remain in Lich.

**Ruby runtime:** Ruby 4.0.3 is installed at `~/.local/ruby-4.0.3` with
Lich's runtime gems, GTK, and curses. User executables in `~/.local/bin`
select this version. `./run.sh` also selects this runtime when present;
the system Ruby remains available as `/usr/bin/ruby`.

For existing Profanity configurations, omit `frontend` or set it to
`profanity` and retain `paths.profanity_bin` and any `profanity_template`.

Install test dependencies with `.venv/bin/python -m pip install -r requirements-dev.txt`,
then run launcher, service, and web checks with `.venv/bin/python -m unittest -q`.

# Gemstone Launcher Script

This script provides a terminal-based interface for launching characters in GemstonIV using Lich and the Profanity Front End. It allows you to select characters from your accounts and handles the login process then launches Profanity. It also displays the online status of characters currently logged in on the same computer.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
  - [Clone the Repository](#clone-the-repository)
  - [Set Up the Configuration File](#set-up-the-configuration-file)
  - [Install Dependencies](#install-dependencies)
- [Configuration](#configuration)
  - [Paths to Lich and Profanity Binaries](#paths-to-lich-and-profanity-binaries)
  - [Accounts and Characters](#accounts-and-characters)
- [Usage](#usage)
  - [Running the Script](#running-the-script)
  - [Navigating the Interface](#navigating-the-interface)
- [Important Notes](#important-notes)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Prerequisites

Before you begin, ensure you have the following installed on your system:

- **Python 3.10 or higher**
- **Ruby interpreter**
- **Lich 5** (Lich5) installed and configured
- **Profanity Frontend** for the terminal default, or **Vellum** for Despana/web clients
- **Git** (optional, for cloning the repository)

Ensure that the `ruby` command is available in your system's PATH.

## Installation

### Clone the Repository

Clone the repository or download the script files into a directory of your choice:

```bash
git clone https://github.com/ndoucette/gempy.git
cd gempy
```


### Set Up the Configuration File

The script uses a YAML configuration file named `config.yaml`. You'll need to create and customize this file based on your setup.

1. **Create the `config.yaml` File:**

   You can create the file manually or copy the sample provided:

   ```bash
   cp config-sample.yaml config.yaml
   ```

2. **Edit the `config.yaml` File:**

   Open `config.yaml` in your preferred text editor and configure the following sections:

   - **Paths to Lich and Profanity**
   - **Accounts and Characters**

   **Example `config.yaml`:**

   ```yaml
   # config.yaml

   # Paths to the Lich and Profanity binaries
   paths:
     lich_bin: '/path/to/your/lich.rbw'
     profanity_bin: '/path/to/your/profanity.rb'

   # Character accounts and their characters
   accounts:
     AccountName1:
       - CharacterName1
       - CharacterName2
     AccountName2:
       - CharacterName3
       - CharacterName4
   ```

### Install Dependencies

Install the required Python packages using `pip` and the provided `requirements.txt` file:

```bash
pip install -r requirements.txt
```

If you're using Python 3 and `pip` refers to Python 2, use:

```bash
pip3 install -r requirements.txt
```

**Dependencies:**

- **PyYAML**: For parsing the YAML configuration file.
- **FastAPI** and **Uvicorn**: For the web daemon and authenticated APIs.
- **websocket-client**: For authenticated local Vellum connections.

## Configuration

### Paths to Lich and Profanity Binaries

In the `config.yaml` file, specify the full paths to your `lich.rbw` and `profanity.rb` binaries:

```yaml
paths:
  lich_bin: '/full/path/to/your/lich.rbw'
  profanity_bin: '/full/path/to/your/profanity.rb'
```

**Notes:**

- Ensure that the paths are absolute (full paths), not relative.
- Verify that the files exist at the specified locations.
- The paths should point to the executable Ruby scripts (`.rbw` and `.rb` files).

### Accounts and Characters

Define your accounts and associated character names under the `accounts` section:

```yaml
accounts:
  AccountName1:
    - CharacterName1
    - CharacterName2
  AccountName2:
    - CharacterName3
    - CharacterName4
```

**Important:**

- **Character names are case-sensitive.** Ensure they match exactly as required for login.
- You can add as many accounts and characters as you need.
- Account names are used as headers in the terminal interface.

## Usage

### Running the Script

To launch the script, navigate to the directory containing `launcher.py` and run:

```bash
./launcher.py
```

If the script is not executable, you can make it executable:

```bash
chmod +x launcher.py
```

Alternatively, run the script using Python:

```bash
python launcher.py
```

### Navigating the Interface

Once the script is running, you'll see a terminal-based interface displaying your accounts and characters.

| Key | Action |
| --- | --- |
| Arrow keys | Move between accounts and characters |
| `Enter` | Log the selected character in |
| `t` | Toggle between the **prime** and **test** servers |
| `r` | Refresh online status |
| `Esc` | Quit |

### Prime vs. test server

The right-hand side of the bottom status bar always shows which server you're
about to log into — green for prime, magenta for test. Press `t` to toggle; the
`[Online]` markers refresh to show who is logged in *on that server*, since a character can
be on prime and test at the same time and each gets its own Profanity port.

Test logins pass `--gemstone --test` to Lich, which resolves to game code `GST`.
Lich falls back to your existing prime (`GS3`) saved entry for that character, so
you do **not** need to add separate saved logins for the test server.

To start the launcher on the test server by default, set `default_realm: test` in
`config.yaml`.

## Important Notes

- **Terminal Size:** Ensure your terminal window is large enough to display the interface. If it's too small, you'll be prompted to resize.
- **Case Sensitivity:** Character names in the configuration file are **case-sensitive**. Enter them exactly as required.
- **Dependencies:** All required dependencies must be installed. Use the provided `requirements.txt` file.
- **Environment Variables:**
  - The script sets `TERM` to `screen-256color`.
  - If `DISPLAY` is not set, it defaults to `:0`.

## Troubleshooting

- **"Unsupported Operating System" Error:**
  - Ensure you're running the script on a supported system (Linux, macOS, or WSL).
- **"Configuration File Not Found" Error:**
  - Verify that `config.yaml` exists in the same directory as `launcher.py`.
- **"LICH_BIN path does not exist" Error:**
  - Check that the path to `lich.rbw` is correct and the file exists.
- **"PROFANITY_BIN path does not exist" Error:**
  - Check that the path to `profanity.rb` is correct and the file exists.
- **Terminal Rendering Issues:**
  - If the interface doesn't display correctly, try running the script in a different terminal emulator.
- **Permission Denied Errors:**
  - Ensure that `launcher.py` is executable.
  - Verify permissions on the Lich and Profanity binaries.
- **Ruby Not Found:**
  - Ensure that Ruby is installed and the `ruby` command is available in your PATH.

## License

This script is provided under the [MIT License](LICENSE). You are free to use, modify, and distribute it as per the terms of the license.

---

**Enjoy your gaming experience! If you encounter any issues or have suggestions for improvements, feel free to contribute or open an issue.**

---
