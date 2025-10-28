# 🔄 Automatic Sync Behavior for Import Jobs

## Quick Answer

**There are TWO different syncs:**

### 1. **Vote Sync (AUTOMATIC)** ✅
- **What:** Syncs species identifications, candidates, votes from cluster
- **When:** Runs automatically when you view species queue
- **For:** ALL running jobs (not just Hansen job)
- **Data:** Species, CandidateSpecies, Vote, ThermoMatch records

### 2. **Full CHEMKIN Sync (MANUAL)** ❌
- **What:** Syncs complete reactions + thermo data
- **When:** Must run manually via command
- **For:** Only the job you specify
- **Data:** ChemkinReaction (8,314), ChemkinThermo (372)

---

## Detailed Explanation

### Vote Sync (Automatic) ✅

**When it runs:**

The vote sync runs **automatically** when you visit the species queue page for ANY job:

```python
# Location: importer_dashboard/species_views.py, line 36-78

should_sync = (
    job.status == 'running' and 
    job.host and 
    job.host != 'Pending...' and
    (species_count == 0 or request.GET.get('sync') == 'true')
)

if should_sync:
    sync_result = sync_job_votes_incremental(job)  # ← AUTOMATIC!
```

**Triggers:**
1. ✅ Automatically when viewing species queue for running job
2. ✅ If no species exist for the job (first time)
3. ✅ When you click "Refresh from Cluster" button
4. ✅ When URL has `?sync=true` parameter

**What data it syncs:**

```python
# From vote_db SQLite on cluster:
- species_votes table → Species + CandidateSpecies records
- voting_reactions table → Vote records  
- identified_species table → Species with confirmed identifications
- blocked_matches table → BlockedMatch records
```

**How it works:**
```
1. Connect to cluster via SSH
2. Query vote_db SQLite database
3. Get only NEW/UPDATED records since last sync (incremental)
4. Transfer JSON data over SSH
5. Update Django database (Species, CandidateSpecies, Vote)
6. Record sync timestamp in SyncLog
```

**Which jobs?**
- ✅ **ALL running jobs** - Any job with `status='running'` and valid host
- ✅ Works for Hansen job, and any other job you start
- ✅ Each job has its own vote database on cluster

**Performance:**
- Fast (seconds) - only transfers changes
- Incremental - tracks last sync timestamp
- Efficient - minimal data transfer

---

### Full CHEMKIN Sync (Manual) ❌

**When it runs:**

**NEVER automatically** - You must run it manually:

```bash
cd /Users/lekiaprosper/Documents/CoMoChEng/Prometheus/kineticmodelssite
conda activate kms

# For Hansen job (default):
python manage.py sync_all_chemkin --clear

# For other jobs:
python manage.py sync_all_chemkin --job "path/to/other/job" --clear
```

**What data it syncs:**

```python
# Downloads from cluster, parses with RMG-Py:
- mechanism.txt → ChemkinReaction records (8,314)
- thermo.txt → ChemkinThermo records (372)
- SMILES.txt → Species structures
```

**Why manual?**
1. Large data transfer (3.7 MB mechanism file)
2. Intensive parsing (several minutes with RMG-Py)
3. Creates thousands of database records
4. Should run when needed, not on every page load

**How to run for OTHER jobs:**

```bash
# Example: For a different mechanism
python manage.py sync_all_chemkin \
    --job "CombFlame2014/1234-NewMechanism" \
    --clear
```

The command will:
1. Find the job by name in Django database
2. Connect to cluster via SSH
3. Download mechanism files from that job's directory
4. Parse with RMG-Py
5. Create ChemkinReaction and ChemkinThermo records for THAT job

**Which jobs?**
- ❌ **Must specify manually** - Default is Hansen job
- ✅ Can run for ANY job by passing `--job` parameter
- ⚠️ Must have job record in Django database first

---

## Comparison Table

| Feature | Vote Sync | Full CHEMKIN Sync |
|---------|-----------|-------------------|
| **Automatic?** | ✅ Yes | ❌ No (manual command) |
| **Trigger** | View species queue | `python manage.py sync_all_chemkin` |
| **Applies to** | ALL running jobs | Specified job only |
| **Data synced** | Votes, candidates, identifications | Reactions, thermo, all species |
| **Data source** | vote_db (SQLite) | mechanism.txt, thermo.txt |
| **Speed** | Fast (seconds) | Slow (minutes) |
| **Frequency** | Every page visit (if running) | Once per job setup |
| **Incremental** | ✅ Yes (tracks changes) | ❌ No (full parse) |
| **Size** | Small (KB of JSON) | Large (MB of CHEMKIN files) |

---

## Which Data Is Available for Different Jobs?

### If you START a new job through the dashboard:

**Automatically available:**
- ✅ Species from vote_db (as job progresses)
- ✅ Candidates from cluster's matching
- ✅ Votes from cluster reactions
- ✅ Identified species
- ✅ Blocked matches

**NOT automatically available:**
- ❌ ChemkinReaction records
- ❌ ChemkinThermo records
- ❌ Complete species list (372 species)

**To get full data:**
```bash
# Must run manual sync
python manage.py sync_all_chemkin --job "YourJobName" --clear
```

---

## Example: Starting a New Job

### Step 1: Create and Start Job in Dashboard

1. Go to `http://localhost:8000/importer/`
2. Click "Start New Job"
3. Job starts on cluster, gets SLURM ID

### Step 2: Vote Data (Automatic)

**When:** As soon as you visit species queue
**What happens:**
```
Visit: http://localhost:8000/importer/job/2/species/

→ Auto-sync runs
→ Downloads vote_db from cluster
→ Creates Species + CandidateSpecies records
→ Shows species queue with candidates
```

**Result:** You can immediately start identifying species!

### Step 3: Full CHEMKIN Data (Manual - Optional)

**When:** If you want reaction context and full analysis
**What to do:**
```bash
# Get job name from dashboard (e.g., "CombFlame2014/NewMech")
python manage.py sync_all_chemkin --job "CombFlame2014/NewMech" --clear
```

**Result:** 
- All reactions available for analysis
- Can show reactions per species
- Can calculate mechanism coverage
- Can validate chemistry
- Can export complete mechanisms

---

## Why This Design?

### Vote Sync (Automatic)
**Goal:** Real-time collaboration on species identification
- Users need immediate access to candidates and votes
- Small data size allows frequent updates
- Critical for workflow (can't identify without votes)

### Full CHEMKIN Sync (Manual)
**Goal:** Deep mechanism analysis (optional)
- Large data transfer - can't do on every page load
- Not needed for basic identification workflow
- Advanced features (coverage, validation) are optional
- Run once per job, not continuously

---

## Summary for Users

### **For Basic Species Identification:**
✅ **Everything is automatic!**
- Start job → visit species queue → auto-sync happens
- See candidates, votes, make identifications
- Works for ALL jobs you create

### **For Advanced Analysis (reactions, coverage, validation):**
❌ **Must run manual sync:**
```bash
python manage.py sync_all_chemkin --job "YourJobName" --clear
```

Then you get:
- See exact reactions for each species
- Calculate mechanism coverage
- Validate chemistry
- Export complete mechanisms

---

## How to Check What Data You Have

### Django Shell:
```bash
cd /Users/lekiaprosper/Documents/CoMoChEng/Prometheus/kineticmodelssite
conda activate kms
python manage.py shell
```

```python
from importer_dashboard.models import *

# List all jobs
for job in ClusterJob.objects.all():
    print(f"\nJob: {job.name}")
    print(f"  Species: {Species.objects.filter(job=job).count()}")
    print(f"  Candidates: {CandidateSpecies.objects.filter(species__job=job).count()}")
    print(f"  Votes: {Vote.objects.filter(species__job=job).count()}")
    print(f"  Reactions: {ChemkinReaction.objects.filter(job=job).count()}")  # ← Will be 0 without manual sync!
    print(f"  Thermo: {ChemkinThermo.objects.filter(species__job=job).count()}")  # ← Will be 0 without manual sync!
```

**Expected output:**

```
Job: CombFlame2013/2343-Hansen
  Species: 372         ← From manual sync
  Candidates: 150      ← From automatic vote sync
  Votes: 450           ← From automatic vote sync
  Reactions: 8314      ← From manual sync
  Thermo: 372          ← From manual sync

Job: CombFlame2014/NewMech
  Species: 25          ← From automatic vote sync only
  Candidates: 80       ← From automatic vote sync
  Votes: 200           ← From automatic vote sync  
  Reactions: 0         ← NO MANUAL SYNC YET!
  Thermo: 0            ← NO MANUAL SYNC YET!
```

---

## Recommendations

### For Regular Use (Species Identification):
✅ **Just use the dashboard** - automatic sync handles everything

### For Advanced Analysis:
✅ **Run manual sync once per job:**
```bash
python manage.py sync_all_chemkin --job "YourJobName" --clear
```

### For Multiple Jobs:
✅ **Run manual sync for each job you want to analyze:**
```bash
# Job 1
python manage.py sync_all_chemkin --job "CombFlame2013/2343-Hansen" --clear

# Job 2  
python manage.py sync_all_chemkin --job "CombFlame2014/1234-NewMech" --clear

# Job 3
python manage.py sync_all_chemkin --job "OtherProject/5678-Test" --clear
```

---

## TL;DR

**Q: Is the sync automatic for other jobs?**

**A: DEPENDS which sync:**

- **Vote sync (candidates, votes):** ✅ YES - Automatic for ALL running jobs
- **CHEMKIN sync (reactions, thermo):** ❌ NO - Manual command for each job

**For basic identification:** Everything auto-syncs ✅

**For advanced features:** Must run `sync_all_chemkin` for each job ❌
