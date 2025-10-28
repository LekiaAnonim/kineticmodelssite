# 🔍 Understanding the Species Discrepancy

## The Problem

You're seeing **two different views** of the same data:

### Cluster Interface (localhost:8126):
```
✅ 25 Identified species
❌ 347 Unconfirmed species
📊 Total: 372 species in the mechanism
```

### Django Dashboard (localhost:8000):
```
✅ 25 Total species (all confirmed)
❌ 0 Unidentified
📊 Only showing: 25 species (missing 347!)
```

---

## 🎯 Root Cause

The **incremental sync is only syncing species that have votes** (from `species_votes` table) and **species that are already identified** (from `identified_species` table).

It's **NOT syncing the 347 unconfirmed species** that:
- Are in the CHEMKIN mechanism
- Don't have votes yet
- Haven't been identified
- Are waiting for user input

---

## 🗄️ Database Tables on Cluster

The cluster vote database likely has these tables:

1. **`species_votes`** - Species with voting evidence from reactions
   - Your 25 identified species came from here
   
2. **`identified_species`** - Confirmed species matches
   - Your 25 identified species also recorded here
   
3. **`unconfirmed_species`** or **`chemkin_species`** - All species from CHEMKIN
   - The missing 347 species are here
   - These need identification but have no votes yet

4. **`voting_reactions`** - Reactions that vote for species matches

5. **`blocked_matches`** - User-blocked incorrect matches

---

## 📊 Current Sync Logic

```python
# incremental_sync.py currently does:

1. Sync species_votes → CandidateSpecies
   ✅ Gets species that have voting evidence
   ❌ Misses species with no votes

2. Sync identified_species → Species (confirmed)
   ✅ Gets species that are already identified
   ❌ Misses unidentified species

3. Sync blocked_matches → BlockedMatch
   ✅ Gets blocked candidates

Result: Only syncs 25 species (the identified ones)
Missing: 347 unconfirmed species
```

---

## 🔧 What Needs to Be Fixed

We need to add **another sync query** to pull all unconfirmed species:

```python
def get_all_unconfirmed_species(self) -> Dict:
    """Get all unconfirmed CHEMKIN species"""
    query = """
    SELECT 
        chemkin_label,
        chemkin_formula,
        status,
        created_at
    FROM unconfirmed_species
    -- or possibly: chemkin_species, all_species, etc.
    WHERE status != 'confirmed'
    ORDER BY chemkin_label
    """
    # Execute and return
```

---

## 🎯 The Solution

### Option 1: Extend Sync to Include Unconfirmed Species

Add a new method to `IncrementalVoteSync` class:

```python
def sync_all_chemkin_species(self):
    """Sync ALL species from CHEMKIN, not just those with votes"""
    
    # Query for all CHEMKIN species
    query = """
    SELECT 
        chemkin_label,
        chemkin_formula,
        -- other fields
    FROM chemkin_species  -- or whatever table has ALL species
    """
    
    # Get data via SSH
    cmd = f"sqlite3 {self.db_path} -json '{query}'"
    stdout, stderr = self.ssh_manager.exec_command(cmd)
    
    # Parse and create Species objects
    all_species = json.loads(stdout)
    
    for sp_data in all_species:
        Species.objects.get_or_create(
            job=self.job,
            chemkin_label=sp_data['chemkin_label'],
            defaults={
                'formula': sp_data['chemkin_formula'],
                'identification_status': 'unidentified',
                # ...
            }
        )
```

### Option 2: Use the Cluster Web Interface

The cluster interface at `localhost:8126` **already has all 372 species** because it queries the database directly.

For now, you can:
1. Use `dashboard_new.py` to tunnel to cluster
2. Click "open" to access `localhost:8126`
3. Click "Unconfirmed species (347)"
4. Identify species directly in cluster interface

---

## 🔍 How to Investigate

### Step 1: Check what tables exist

```bash
ssh login.explorer.northeastern.edu

cd /projects/westgroup/lekia.p/Importer/RMG-models/CombFlame2013/2343-Hansen/

# Find the vote database
ls -la votes_*.db

# Check tables
sqlite3 votes_db8cff6d0de0c718b461f76ab76fa00e.db ".tables"
```

Expected output:
```
species_votes          
identified_species     
voting_reactions       
blocked_matches        
unconfirmed_species    ← This is what we need!
chemkin_species        ← Or maybe this?
```

### Step 2: Check table schema

```bash
sqlite3 votes_db8cff6d0de0c718b461f76ab76fa00e.db ".schema unconfirmed_species"
```

### Step 3: Count unconfirmed species

```bash
sqlite3 votes_db8cff6d0de0c718b461f76ab76fa00e.db "SELECT COUNT(*) FROM unconfirmed_species"
```

Expected: **347**

---

## 💡 Quick Fix: Manual Sync of All Species

While we fix the automatic sync, you can manually sync all species:

```python
from importer_dashboard.models import ClusterJob, Species
from importer_dashboard.incremental_sync import IncrementalVoteSync

job = ClusterJob.objects.filter(name="CombFlame2013/2343-Hansen").first()
sync = IncrementalVoteSync(job)

# Query ALL species from cluster (need to know table name)
query = """
SELECT 
    chemkin_label,
    chemkin_formula
FROM chemkin_species  -- or unconfirmed_species
"""

cmd = f"sqlite3 {sync.db_path} -json '{query}'"
stdout, stderr = sync.ssh_manager.exec_command(cmd)

import json
all_species = json.loads(stdout)

print(f"Found {len(all_species)} species on cluster")

# Create Species objects for each
for sp_data in all_species:
    Species.objects.get_or_create(
        job=job,
        chemkin_label=sp_data['chemkin_label'],
        defaults={
            'formula': sp_data.get('chemkin_formula', ''),
            'identification_status': 'unidentified',
        }
    )

print("Sync complete!")
```

---

## 📋 Comparison

### What You Currently See (Django):

| Status | Count | What |
|--------|-------|------|
| Confirmed | 25 | Species with votes AND identified |
| Tentative | 0 | Species with votes but NOT confirmed |
| Unidentified | 0 | Species without votes |
| **TOTAL** | **25** | **Only synced species** |

### What You Should See (Complete):

| Status | Count | What |
|--------|-------|------|
| Confirmed | 25 | Already identified |
| Tentative | 0 | Have candidates, need review |
| Unidentified | 347 | **MISSING - Need to sync these!** |
| **TOTAL** | **372** | **All CHEMKIN species** |

---

## 🎯 Action Items

### Immediate (Use Cluster Interface):

1. Use `dashboard_new.py` for the 347 unconfirmed species
2. Access via `localhost:8126` (cluster interface)
3. Identify species there

### Short-term (Fix Sync):

1. SSH to cluster and check database tables
2. Find table with all CHEMKIN species
3. Add sync method for unconfirmed species
4. Re-run sync to get all 372 species

### Long-term (Complete Django Dashboard):

1. Implement full sync of all CHEMKIN species
2. Add auto-sync on page load
3. Add manual "Sync All Species" button
4. Display progress: "25/372 identified (7%)"

---

## 🔧 Code Fix Needed

Add this to `incremental_sync.py`:

```python
def get_all_chemkin_species(self) -> Dict:
    """
    Get ALL species from CHEMKIN mechanism, including unconfirmed
    
    Returns:
        Dictionary with species data
    """
    # TODO: Determine correct table name on cluster
    # Could be: unconfirmed_species, chemkin_species, all_species, etc.
    
    query = """
    SELECT 
        chemkin_label,
        chemkin_formula,
        status,
        created_at
    FROM chemkin_species  -- CHANGE THIS to actual table name
    ORDER BY chemkin_label
    """
    
    cmd = f"""sqlite3 {self.db_path} -json '{query}'"""
    stdout, stderr = self.ssh_manager.exec_command(cmd)
    
    try:
        species = json.loads(stdout) if stdout.strip() else []
        return {'species': species, 'count': len(species)}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse CHEMKIN species JSON: {e}")
        return {'species': [], 'count': 0}

def sync_all_species_to_django(self):
    """Sync ALL CHEMKIN species to Django, not just identified ones"""
    result = self.get_all_chemkin_species()
    
    for sp_data in result['species']:
        Species.objects.update_or_create(
            job=self.job,
            chemkin_label=sp_data['chemkin_label'],
            defaults={
                'formula': sp_data.get('chemkin_formula', ''),
                'identification_status': sp_data.get('status', 'unidentified'),
                # ... other fields
            }
        )
    
    return result['count']
```

Then call it in the main sync function:

```python
def sync_job_votes_incremental(job):
    """Main sync function"""
    sync = IncrementalVoteSync(job)
    
    # Sync ALL species first (including unconfirmed)
    all_species_count = sync.sync_all_species_to_django()
    
    # Then sync votes for identified species
    votes_result = sync.get_updated_votes()
    # ... rest of sync
    
    return {
        'success': True,
        'all_species': all_species_count,  # Should be 372
        'identified': 25,
        'unconfirmed': 347,
        # ...
    }
```

---

## 📝 Summary

**Why you see 25 instead of 372:**

The sync is **only pulling species that have votes** or are **already identified**. The 347 unconfirmed species (that exist in the CHEMKIN file but have no votes yet) are not being synced.

**How to fix:**

1. **Short-term:** Use the cluster interface (`localhost:8126`) to work with all 372 species
2. **Long-term:** Fix the sync to pull ALL CHEMKIN species, not just those with votes

**Where the 347 species are:**

They're in the cluster vote database, probably in a table called `unconfirmed_species`, `chemkin_species`, or similar. We just need to add a query for that table in the sync logic.

---

Want me to help you:
1. Check what tables exist in the cluster database?
2. Add the sync logic for all species?
3. Or just use the cluster interface for now?
