# Docent Data Registry

A utility for quickly getting data into Docent via two routes:

* **Ingest** via Docent SDK: relatively robust, but limited to restoring agent runs
* **Restore** from database dump: brittle, but can also restore rubrics, judge results, and other tables

## Prerequisites

### Database Tools (macOS)
```bash
# Install PostgreSQL tools
brew install postgresql
```

### Environment Setup
Set up your environment variables. Create a `.env` file in the docent root directory or set these environment variables:

```bash
# Database connection (for dump/restore operations)
DOCENT_PG_HOST=localhost
DOCENT_PG_PORT=5432
DOCENT_PG_DATABASE=docent
DOCENT_PG_USER=ubuntu
DOCENT_PG_PASSWORD=your_password_here

# AWS S3 credentials
AWS_ACCESS_KEY_ID=your_access_key # or sign in with the AWS CLI
AWS_SECRET_ACCESS_KEY=your_secret_key # or sign in with the AWS CLI

# Docent API (for ingestion)
DOCENT_API_KEY=your_api_key
NEXT_PUBLIC_API_HOST=http://localhost:8889/
```

## Usage

All commands should be run from the docent root directory:

### Ingest Data Files

Import data files using the Docent SDK:

```bash
# Show menu to select file from S3
python -m data ingest

# Ingest specific file
python -m data ingest my_collection.inspect.eval
```

**File Naming Convention**: Files must follow the pattern `[collection_name].[importer_name].[extension]`

### Create Database Dumps
Create dump files for collections:

```bash
# Show menu to select collection
python -m data dump

# Dump specific collection
python -m data dump collection-uuid-here
```

### Restore Database Dumps

Restore data from database dumps:

```bash
# Show menu to select dump file from S3
python -m data restore

# Restore specific file
python -m data restore my_collection.abc123.pg.tgz
```

When restoring, the file menu will only show Alembic revision-compatible dumps. But you can still (attempt to) restore from a different revision by passing the filename as a CLI argument.

Restored collections will be assigned to the user test@transluce.org. Restore will fail if this user does not exist.

## File Storage

### Local Cache
Files are cached locally in `data/cache/` to avoid repeated downloads.

### S3 Integration
- **Bucket**: `docent-test-data` (us-west-1)
- Dump files can be automatically uploaded to S3 after creation
- Files are organized and filtered based on type (`pg.tgz` files for restore, others for ingest)
