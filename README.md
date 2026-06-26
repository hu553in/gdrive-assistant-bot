# Google Drive assistant bot

[![CI](https://github.com/hu553in/gdrive-assistant-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/hu553in/gdrive-assistant-bot/actions/workflows/ci.yml)

Telegram bot for semantic search and Q&A over Google Drive documents, backed by Qdrant and an
optional OpenAI-compatible LLM.

## What it does

- Indexes Google Drive folders or all files accessible to the service account
- Extracts text from Google Docs, Sheets, Slides, text files, PDFs, and Microsoft Office files
- Stores embeddings in Qdrant
- Answers `/ask` questions from retrieved chunks
- Optionally calls an OpenAI-compatible LLM for final answer generation
- Accepts manual notes via `/ingest`

## Requirements

- Python 3.13+
- `uv`
- Docker and Docker Compose
- Telegram bot token
- Google service account JSON key
- Enabled Drive, Docs, Sheets, and Slides APIs

## Setup

```bash
cp .env.example .env
mkdir -p secrets
```

Place the Google service account key at `secrets/google_sa.json`, then share the target Drive
folders with the service account email. Edit `.env` before starting the services.

Docker Compose reads `.env` by default. Set `ENV_FILE` for another env file or `GOOGLE_SA_FILE` for
another service account key path.

## Configuration

All settings are read from `.env`.

| Name                                        | Required    | Default                                                       | Description                |
| ------------------------------------------- | ----------- | ------------------------------------------------------------- | -------------------------- |
| `TELEGRAM_BOT_TOKEN`                        | Yes         | -                                                             | Telegram bot token         |
| `STORAGE_GOOGLE_DRIVE_FOLDER_IDS`           | Conditional | `[]`                                                          | Folder IDs as JSON array   |
| `STORAGE_GOOGLE_DRIVE_ALL_ACCESSIBLE`       | Conditional | `false`                                                       | Index all accessible files |
| `STORAGE_GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON` | Yes         | `/run/secrets/google_sa`                                      | Service account key path   |
| `QDRANT_URL`                                | No          | `http://qdrant:6333`                                          | Qdrant endpoint            |
| `EMBED_MODEL`                               | No          | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | fastembed model            |
| `LLM_API_KEY`                               | No          | -                                                             | Enables LLM answers        |
| `LLM_BASE_URL`                              | No          | `https://api.openai.com/v1`                                   | OpenAI-compatible API URL  |
| `LLM_MODEL`                                 | No          | `gpt-4o-mini`                                                 | LLM model name             |

Set either `STORAGE_GOOGLE_DRIVE_FOLDER_IDS` or `STORAGE_GOOGLE_DRIVE_ALL_ACCESSIBLE=true`.

Access control is optional:

- `TELEGRAM_ALLOWED_USER_IDS` restricts private chats
- `TELEGRAM_ALLOWED_GROUP_IDS` restricts groups and supergroups
- empty lists mean public access

See `.env.example` for file type toggles, rate limits, ingest intervals, and health ports.

## Usage

Telegram commands:

- `/start` - show help
- `/ask <question>` - search the indexed knowledge base
- `/ingest <text>` - add a manual note

Service commands:

```bash
make start
make stop
make restart
```

## Runtime behavior

- `ingest` syncs Google Drive content into Qdrant
- `bot` serves Telegram commands and manual notes
- LLM calls are disabled unless `LLM_API_KEY` is set
- Docker Compose health checks use the configured bot and ingest health ports
- The Google service account needs read access to every folder being indexed

## Development

```bash
make install-deps
make check
```

Focused checks:

```bash
make lint
make test
make check-types
```
