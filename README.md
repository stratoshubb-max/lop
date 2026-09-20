# Athar (أثر)

Athar is a social space built with Django, featuring real user authentication, timeline feeds, replies, interactions (likes, reposts, bookmarks), search, profile management, and native PostgreSQL / Supabase integration.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_athar      # optional: demo voices, thoughts and topics
python manage.py runserver
```

The application runs at `http://127.0.0.1:8000/`.

`python manage.py seed_athar --reset` rebuilds the demo content. Every demo
account (`layan`, `sohaib`, `nour`, `yacine`) uses the password
`athar-demo-2026`.

Run the test suite with:

```bash
python manage.py test core
```

## Supabase (PostgreSQL) Database Setup

The project supports direct connection to managed Supabase PostgreSQL databases via environment variables in `.env` (see `.env.example`):

1. Create a `.env` file from the template:
   ```bash
   cp .env.example .env
   ```
2. Enter your Supabase connection string (from Supabase Dashboard > Project Settings > Database):
   ```env
   # Recommended connection via Transaction Pooler (port 6543):
   DATABASE_URL=postgresql://postgres.[PROJECT-REF]:[YOUR-PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres?sslmode=require
   ```
3. Run migrations on your database:
   ```bash
   python manage.py migrate
   ```
4. Verify connection status via the health check endpoint:
   ```
   GET /api/health/
   ```
   When connected to Supabase/PostgreSQL, it returns: `{"status": "healthy", "database": "postgresql", "supabase_ready": true}`.
   If Supabase variables are absent or unreachable, the application smoothly defaults to local SQLite storage.

## Features

- **Profile pictures (PFP)**: upload, drag-and-drop, live preview, remove and a
  colour fallback per account. Images are cropped to a square, resized, stripped
  of EXIF data and stored as processed bytes in the database, then served from a
  versioned, immutable URL (`/api/avatar/<handle>/<version>/`).
- **Post attachments**: one photo per thought, processed the same way and served
  from `/api/media/posts/<id>/<version>/`.
- **Athar Assistant (AI)**: tone, readability, hashtags, rewrites, shortening,
  expansion, reply ideas, writing prompts, moderation, thread summaries, feed
  digests, related thoughts and live in-composer help (score, tone, tags and a
  Tab-completion line). It runs fully offline on a deterministic NLP engine, and
  upgrades to any OpenAI-compatible model when `AI_API_KEY` is set.
- **Drafts that wait for you**: an unfinished thought is kept locally and
  restored (with a fresh analysis) if the page reloads before you publish.
- **Keyboard-first**: `/` searches, `n` starts a new thought, `d` opens the
  digest, `⌘/Ctrl + Enter` publishes, `Tab` accepts an assistant suggestion and
  `Esc` closes any layer.
- **Database-Backed Models**: `Profile`, `Post`, `Follow`, `PostLike`, `PostRepost`, `Bookmark`, and `Topic`.
- **Supabase PostgreSQL Ready**: Connection pooling support, PgBouncer compatibility, SSL mode, and pre-generated DDL in `supabase_schema.sql`.
- **RESTful JSON API**: Endpoints for posts, replies, likes, reposts, bookmarks, following, server-side search, profile editing, and post deletion.
- **Optimized Queries**: Annotated ORM queries to prevent N+1 overhead and reduce round trips.
- **Atomic Transactions**: Database transactions (`transaction.atomic`) guarantee data consistency across likes, follows, reposts, and bookmark toggles.
- **Session-Based Authentication**: Seamless registration, login, and logout with cookie protection designed for cross-origin iframe previews.
- **Responsive LTR UI**: Modern English layout with clean typography, smooth animations, and zero fake content.

## Athar Assistant (AI)

The assistant is built to work with **no API key at all**: `core/ai.py` is a
deterministic engine (tokenising, stemming, TF-IDF-style keyword ranking,
Flesch readability, lexicon tone analysis, extractive summarisation, BM25
ranking, hashtag canonicalisation and template-based rewriting). Every endpoint
is therefore fast, private and free.

Set any OpenAI-compatible provider to upgrade the rewriting path:

```env
AI_API_KEY=sk-...
AI_BASE_URL=https://api.openai.com/v1     # optional
AI_MODEL=gpt-4o-mini                      # optional
```

If the hosted call fails or times out, the local engine answers instead — a bad
key can never break the assistant. `GET /api/health/` reports the active
provider (`athar-local` or `hosted:<model>`).

| Endpoint | What it does |
| --- | --- |
| `POST /api/ai/compose/` | Live draft read: score, tone, readability, tags, nudge, Tab-completion |
| `POST /api/ai/coach/` | Full pre-publish read-out with checks |
| `POST /api/ai/improve/` | Three rewrite variants (polish, tighten, clarify) |
| `POST /api/ai/hashtags/` | Canonical tags (`designing` → `#design`) plus key ideas |
| `POST /api/ai/tone/` | Mood, sentiment and one piece of advice |
| `POST /api/ai/shorten/` `expand/` `title/` | Shape a draft without losing its voice |
| `POST /api/ai/reply/` | Three reply ideas matched to the parent thought |
| `POST /api/ai/prompts/` | Writing prompts (works with an empty composer) |
| `POST /api/ai/moderate/` | Kindness/safety pre-flight (`safe` flag + checks) |
| `POST /api/ai/summary/` | Summary of a thread |
| `GET /api/ai/digest/` | Feed digest: mood, themes, notable lines, open questions |
| `GET /api/ai/search/` | Search insights and closest angles |

## Development notes

- Template loaders are uncached while `DEBUG=True`, so edits to templates show
  up immediately in `runserver` (production keeps `cached.Loader`).
- SQLite runs in WAL mode with a 15s busy timeout, so the front end can fire
  several API calls in parallel without "database is locked" errors.
- Images are validated by magic bytes and size before decoding; BLOBs live in the
  database, which keeps the feature working identically on SQLite, Supabase and
  ephemeral hosts.
- Assistant requests are budgeted per caller (anonymous callers get 60 per
  10 minutes, members 300) so a configured hosted model cannot be abused; the
  feed widgets (`/api/ai/digest/`, `/api/ai/topics/`) are exempt.
- The assistant, uploads and every interactive control are covered by
  `python manage.py test core` (69 tests).
