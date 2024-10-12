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

- **Python 3.6 or higher**
- **Ruby interpreter**
- **Lich 5** (Lich5) installed and configured
- **Profanity Frontend** installed
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
   cp config_sample.yaml config.yaml
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
