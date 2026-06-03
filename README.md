# D-Drive

A **Discord bot + web UI** for splitting large files into chunks, uploading them to Discord, and merging them back into the original file. Supports **encryption, checksums, parallel uploads, and resume functionality**.

---

## ✨ Features

- **File Splitting & Merging**: Split large files into smaller chunks and merge them back.
- **SHA-256 Checksums**: Verify file integrity during upload and download.
- **AES-256 Encryption**: Optional encryption for sensitive files (enabled via `.env`).
- **Parallel Uploads**: Upload multiple chunks simultaneously to Discord for faster transfers.
- **Resume Support**: Track upload progress in SQLite and resume interrupted transfers.
- **Web UI**: User-friendly interface built with Flask.
- **Discord Bot Integration**: Automatically upload chunks to a Discord channel.
- **Docker Support**: Easy deployment with `Dockerfile` and `docker-compose.yml`.
- **Unit Tests**: Test suite for `file_splitter.py`.

---

## 🚀 Quick Start

### Option 1: Run Natively (Python)

1. **Clone the repository**:
   ```bash
   git clone https://github.com/filosquared/D-Drive.git
   cd D-Drive
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up `.env`**:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and add your **Discord bot token**, **server ID**, and optional **encryption key**:
   ```ini
   DISCORD_TOKEN=your_bot_token_here
   DISCORD_SERVER_ID=your_server_id_here
   ENCRYPTION_KEY=your_optional_encryption_key
   ```

4. **Run the app**:
   ```bash
   python app.py
   ```
   Open the web UI at: [http://127.0.0.1:5000](http://127.0.0.1:5000)

---

### Option 2: Run with Docker

1. **Build and start the containers**:
   ```bash
   docker-compose up --build
   ```
   The app will be available at: [http://127.0.0.1:5000](http://127.0.0.1:5000)

---

## 📂 Project Structure

```
D-Drive/
├── app.py                 # Flask web UI and Discord bot
├── backend_logic.py       # File splitting, merging, upload logic
├── file_splitter.py       # Core file splitting/merging with checksums and encryption
├── requirements.txt       # Python dependencies
├── Dockerfile             # Docker image for the app
├── docker-compose.yml     # Docker setup (app + Redis for rate limiting)
├── .env.example           # Example environment variables
├── tests/                 # Unit tests
│   └── test_file_splitter.py
└── README.md
```

---

## 🔧 Configuration

Edit `.env` to configure the bot:

| Variable              | Description                                                                 | Required | Default       |
|-----------------------|-----------------------------------------------------------------------------|----------|---------------|
| `DISCORD_TOKEN`       | Your Discord bot token (from [Discord Developer Portal](https://discord.com/developers/applications)) | ✅ Yes  | -             |
| `DISCORD_SERVER_ID`   | The ID of your Discord server/guild.                                       | ✅ Yes  | -             |
| `ENCRYPTION_KEY`      | Optional key for AES-256 encryption. If not set, files are not encrypted.   | ❌ No   | -             |
| `CHUNK_SIZE_MB`       | Size of each chunk in MB.                                                   | ❌ No   | `10`          |
| `ENCRYPT_FILES`       | Enable/disable encryption (`true` or `false`).                              | ❌ No   | `false`       |

---

## 🛠️ Usage

### Web UI
1. Open the web UI at [http://127.0.0.1:5000](http://127.0.0.1:5000).
2. Upload a file.
3. Select a Discord channel.
4. Click **Upload** to split, encrypt (if enabled), and upload the file.

### Discord Bot Commands
| Command               | Description                                      |
|-----------------------|--------------------------------------------------|
| `/upload <file>`      | Upload and split a file to Discord.              |
| `/status`             | Check the status of ongoing uploads.             |
| `/resume`             | Resume interrupted uploads.                     |

---

## 🧪 Running Tests

Run the unit tests for `file_splitter.py`:

```bash
python -m pytest tests/test_file_splitter.py -v
```

---

## 📦 Dependencies

- Python 3.8+
- Flask
- discord.py
- cryptography (for encryption)
- redis (for rate limiting in Docker)

---

## 🤝 Contributing

1. Fork the repository.
2. Create a branch: `git checkout -b feature/your-feature`.
3. Commit your changes: `git commit -m "feat: add your feature"`.
4. Push to the branch: `git push origin feature/your-feature`.
5. Open a pull request.

---

## 📜 License

This project is licensed under the **MIT License**. See [LICENSE](LICENSE) for details.
