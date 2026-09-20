# Athar (أثر)

Athar is a social space built with Django, featuring real user authentication, timeline feeds, replies, interactions (likes, reposts, bookmarks), search, profile management, and native PostgreSQL / Supabase integration.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

The application runs at `http://127.0.0.1:8000/`.

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

- **Database-Backed Models**: `Profile`, `Post`, `Follow`, `PostLike`, `PostRepost`, `Bookmark`, and `Topic`.
- **Supabase PostgreSQL Ready**: Connection pooling support, PgBouncer compatibility, SSL mode, and pre-generated DDL in `supabase_schema.sql`.
- **RESTful JSON API**: Endpoints for posts, replies, likes, reposts, bookmarks, following, server-side search, profile editing, and post deletion.
- **Optimized Queries**: Annotated ORM queries to prevent N+1 overhead and reduce round trips.
- **Atomic Transactions**: Database transactions (`transaction.atomic`) guarantee data consistency across likes, follows, reposts, and bookmark toggles.
- **Session-Based Authentication**: Seamless registration, login, and logout with cookie protection designed for cross-origin iframe previews.
- **Responsive LTR UI**: Modern English layout with clean typography, smooth animations, and zero fake content.
