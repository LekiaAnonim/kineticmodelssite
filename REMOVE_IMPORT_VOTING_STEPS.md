# Steps to Remove import_voting App (If Needed)

## ⚠️ WARNING
Only follow these steps if you're **absolutely sure** you won't need the REST API system.

## Prerequisites
- Backup your database first
- Make sure no external systems are using the API endpoints

## Step-by-Step Removal

### 1. Remove from INSTALLED_APPS
Edit `kms/settings.py`:
```python
# Remove this line:
"import_voting.apps.ImportVotingConfig",
```

### 2. Remove URL Routes
Edit `kms/urls.py`:
```python
# Remove this line:
path("api/import-voting/", include("import_voting.urls")),
```

### 3. Remove Database Tables (if migrations were run)
```bash
# List current migrations
python manage.py showmigrations import_voting

# If migrations exist, unapply them
python manage.py migrate import_voting zero

# Or manually drop tables in Django shell:
python manage.py shell
```

```python
from django.db import connection
cursor = connection.cursor()

# Drop tables
cursor.execute("DROP TABLE IF EXISTS species_votes")
cursor.execute("DROP TABLE IF EXISTS voting_reactions")
cursor.execute("DROP TABLE IF EXISTS import_voting_identifiedspecies")
cursor.execute("DROP TABLE IF EXISTS import_voting_blockedmatch")
cursor.execute("DROP TABLE IF EXISTS import_voting_importjob")
```

### 4. Delete the Directory
```bash
rm -rf import_voting/
```

### 5. Verify Removal
```bash
# Check no references remain
grep -r "import_voting" . --exclude-dir=".git" --exclude="*.md"

# Run migrations
python manage.py migrate

# Start server to verify no errors
python manage.py runserver
```

## Rollback Plan

If you need to restore it:
1. Git revert the changes
2. Re-add to INSTALLED_APPS and urls.py
3. Run migrations: `python manage.py migrate import_voting`

## Alternative: Archive Instead of Delete

Instead of deleting, you could:
1. Move to an `archive/` directory
2. Comment out in INSTALLED_APPS
3. Keep for reference but don't use

```bash
mkdir -p archive/
mv import_voting archive/
```

Then update settings.py and urls.py to comment out the references.
