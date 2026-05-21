# D-Drive 💾🤖 (Discord Drive)

D-Drive is a web-based and CLI application that allows you to use a private Discord server as a cloud storage drive. It bypasses Discord's file size limits by splitting large files into smaller parts, uploading them to dedicated text channels, and later downloading and reconstructing the original files seamlessly.

Features a clean, modern **Flask-based web dashboard** with real-time transfer logs and a **live-updating speed tracking graph**!

---

## 🌟 Features

- **Split & Upload**: Splitted chunk uploads (default `10 MB` per chunk) to accommodate Discord's standard and boosted upload limits.
- **Dynamic Channels**: Every uploaded file is given its own sanitized channel in a designated Discord server (Guild) so that files stay organized.
- **Download & Merge**: Scan existing channels, select a destination folder, and download all chunks to rebuild your original file using memory-efficient streams.
- **Real-Time Web Interface**:
  - Live progress logs.
  - Interactive speed tracking chart showing upload/download throughput.
  - Native file and directory picker integrations.
- **CLI Mode**: Use `file_splitter.py` directly from the terminal to split or merge files offline without starting the web application.

---

## 🛠️ Tech Stack

- **Backend**: Python 3.8+, Flask, `discord.py`, `python-dotenv`
- **Frontend**: HTML5, Vanilla CSS (with modern dark-mode styling and glassmorphism elements), Vanilla JavaScript, Chart.js for data visualization
- **Threading**: Asyncio-based Discord runner executing inside a daemon thread alongside Flask.

---

## 🚀 Setup & Installation

### 1. Prerequisites
- Python 3.8 or higher installed.
- A Discord Bot Token and a dedicated Discord Server (Guild) where the bot has administrator permissions (needed to create channels, write messages, and upload attachments).

### 2. Clone and Initialize Repository
If you haven't already, initialize a Git repository in the project folder:
```bash
git init
```

### 3. Create a Virtual Environment & Install Dependencies
Create a Python virtual environment to keep packages isolated and install dependencies:

**On macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**On Windows:**
```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy the `.env.example` file to `.env`:
```bash
cp .env.example .env
```

Open `.env` in your editor and configure the variables:
```env
DISCORD_TOKEN=your_bot_token_here
DISCORD_SERVER_ID=your_server_id_here
```

> [!IMPORTANT]
> - **DISCORD_TOKEN**: Obtained from the [Discord Developer Portal](https://discord.com/developers/applications) by creating an application, adding a Bot, and copying the token. Ensure the Bot has **Server Members Intent** and **Message Content Intent** enabled under the Bot tab.
> - **DISCORD_SERVER_ID**: Right-click your server icon in Discord and select **Copy Server ID** (enable Developer Mode in Discord settings if you don't see this option).

---

## 🖥️ Running the Application

To start the Flask web application, run:
```bash
python app.py
```
By default, the server will start at `http://127.0.0.1:5000/`. Open this address in your web browser.

### Using the Web GUI
1. **Upload Tab**:
   - Click **Select File** to open a native file dialog and select any file.
   - Click **Start Upload**. The bot will split the file, create a new channel in your Discord server, and upload the parts.
2. **Download Tab**:
   - Click **Scan Channels** to list files stored in your server.
   - Click **Select Save Folder** to choose where the restored file should be saved.
   - Choose a channel/file from the scanned list and click **Download & Merge**.

---

## 💻 CLI Usage (Offline File Splitter)

You can also use the file splitter/merger directly from the command line without launching the web server.

### Splitting a File
Split a large file into `10 MB` chunks:
```bash
python file_splitter.py split /path/to/large_file.zip
```

Customize chunk size (e.g., `25 MB` for boosted servers) and specify output directory:
```bash
python file_splitter.py split /path/to/large_file.zip --size 25 --output-dir ./parts
```

### Merging Chunks
Merge parts back into the original file:
```bash
python file_splitter.py merge ./parts/large_file.zip.part* --output-dir ./restored
```

---

## 🔒 Security Notice

Never commit your `.env` file containing your Discord Token to public repositories. The `.gitignore` file included in this repository is pre-configured to ignore `.env`, Python cache, and virtual environments.

---

## 📄 License

This project is open-source and available under the [MIT License](LICENSE).
