# 🔥 Why Thermo Matches Are Missing

## Problem Summary

**Zero `ThermoMatch` records in database** despite 3,243 species and 2,681 candidates.

## Root Cause

The thermo match data exists on the cluster but is **never saved to the vote database**, so it never gets synced to Django.

---

## Data Flow (What's Broken)

```
┌─────────────────────────────────────────────────────────────────┐
│ CLUSTER (importChemkin.py)                                       │
├─────────────────────────────────────────────────────────────────┤
│ 1. check_thermo_libraries()                                      │
│    ├─ Compares chemkin thermo to RMG thermo libraries           │
│    ├─ Finds matches using is_identical_to()                     │
│    └─ Stores in self.thermo_matches dictionary                  │
│                                                                   │
│ Format: {                                                        │
│   'CH4': {                                                       │
│     RMGSpecies#148: [                                           │
│       ('primaryThermoLibrary', 'CH4'),                          │
│       ('GRI-Mech3.0', 'methane')                                │
│     ]                                                            │
│   }                                                              │
│ }                                                                │
│                                                                   │
│ 2. save_votes() in vote_local_db.py                             │
│    ├─ Saves species_votes to SQLite                             │
│    ├─ Saves voting_reactions                                     │
│    ├─ Saves identified_species                                   │
│    └─ ❌ DOES NOT save thermo_matches (no table exists!)        │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                     ❌ Data lost here!
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ VOTE DATABASE (votes_db8cff...db)                               │
├─────────────────────────────────────────────────────────────────┤
│ Tables:                                                          │
│  ✅ species_votes                                                │
│  ✅ voting_reactions                                             │
│  ✅ identified_species                                           │
│  ✅ blocked_matches                                              │
│  ❌ thermo_matches (MISSING!)                                    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                  SSH sync via incremental_sync.py
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ DJANGO DASHBOARD                                                 │
├─────────────────────────────────────────────────────────────────┤
│ sync_species_from_cluster()                                      │
│   ├─ Reads votes_data from cluster                              │
│   └─ Processes candidate_info.get('thermo_matches', [])         │
│       └─ Always empty [] because not in database! ❌            │
│                                                                   │
│ Result:                                                          │
│   ThermoMatch.objects.count() = 0                                │
└─────────────────────────────────────────────────────────────────┘
```

---

## Code Evidence

### 1. Cluster Stores Thermo Matches (In Memory Only)

**File:** `/RMG39/RMG-Py/importChemkin.py` line 1543
```python
def set_thermo_match(self, chemkin_label, rmg_species, library_name,
                   library_species_name):
    """
    Store a match made by recognizing identical thermo from a library.
    """
    if chemkin_label not in self.thermo_matches:
        self.thermo_matches[chemkin_label] = dict()
    d = self.thermo_matches[chemkin_label]
    if rmg_species not in d: d[rmg_species] = list()
    d[rmg_species].append((library_name, library_species_name))
```

### 2. Vote Database Has No Thermo Table

**File:** `/RMG39/RMG-Py/vote_local_db.py` line 36
```python
def _create_tables(self):
    """Create database tables if they don't exist"""
    # ... creates these tables:
    # ✅ import_jobs
    # ✅ species_votes
    # ✅ voting_reactions
    # ✅ identified_species
    # ✅ blocked_matches
    # ❌ NO thermo_matches table!
```

### 3. Dashboard Tries to Read Non-Existent Data

**File:** `/kineticmodelssite/importer_dashboard/species_utils.py` line 549
```python
# Process thermo matches
for thermo_info in candidate_info.get('thermo_matches', []):
    library_name = thermo_info.get('library', '')
    library_species_name = thermo_info.get('species_name', '')
    name_matches = thermo_info.get('name_matches', False)
    
    if library_name and library_species_name:
        ThermoMatch.objects.get_or_create(...)
```

This loop **never executes** because `candidate_info['thermo_matches']` is always empty!

---

## Solution

### Option 1: Add Thermo Matches to Vote Database (Recommended)

**Add to `vote_local_db.py`:**

```python
def _create_tables(self):
    # ... existing tables ...
    
    # Thermo matches table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS thermo_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            species_vote_id INTEGER NOT NULL,
            library_name TEXT NOT NULL,
            library_species_name TEXT NOT NULL,
            name_matches BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (species_vote_id) REFERENCES species_votes(id) ON DELETE CASCADE,
            UNIQUE(species_vote_id, library_name)
        )
    """)

def save_thermo_matches(self, species_vote_id: int, thermo_matches: List[Tuple]):
    """Save thermo matches for a species vote"""
    cursor = self.conn.cursor()
    for (library_name, library_species_name) in thermo_matches:
        # Check if library name matches chemkin label
        name_matches = (library_species_name == chemkin_label)
        
        cursor.execute("""
            INSERT OR REPLACE INTO thermo_matches 
            (species_vote_id, library_name, library_species_name, name_matches)
            VALUES (?, ?, ?, ?)
        """, (species_vote_id, library_name, library_species_name, name_matches))
    
    self.conn.commit()
```

**Modify `importChemkin.py` to save thermo matches:**

```python
def save_all_to_database(self):
    """Save votes, thermo matches, and identified species"""
    self.vote_db.save_votes(self.job_id, self.votes)
    
    # NEW: Save thermo matches
    for chemkin_label, rmg_matches in self.thermo_matches.items():
        for rmg_species, library_matches in rmg_matches.items():
            species_vote_id = self.vote_db.get_species_vote_id(
                self.job_id, chemkin_label, rmg_species.index
            )
            if species_vote_id:
                self.vote_db.save_thermo_matches(species_vote_id, library_matches)
```

### Option 2: Accept Empty Thermo Matches (Temporary)

The UI already handles missing thermo matches gracefully with the `{% if %}` check. This is not ideal but won't break anything.

---

## Impact

**Current State:**
- ✅ Voting works (reactions vote for species)
- ✅ Identification works (users can confirm/block)
- ❌ **Thermo library hints missing** (less confidence in matches)
- ❌ **Name match badges don't work** (can't show if library name matches chemkin)

**After Fix:**
- Users see which thermo libraries support a match
- "Name Match" badges show when library species name matches chemkin label
- Confidence scoring includes thermo match count
- Better match validation

---

## Workaround

Users can check thermo libraries manually:
1. SSH to cluster: `ssh comocheng@discovery7.neu.edu`
2. Check cluster job directory: `cd /scratch/comocheng/...`
3. Open web interface: `http://discovery7.neu.edu:PORT/thermolibraries_html`
4. Compare species manually

---

## Database Query to Confirm

```bash
# On cluster
sqlite3 /scratch/comocheng/.../votes_db8cff...db
.tables
# You'll see: species_votes, voting_reactions, identified_species, blocked_matches
# NO thermo_matches table!

# On Django
python manage.py shell
from importer_dashboard.models import ThermoMatch
ThermoMatch.objects.count()  # Returns 0
```

---

## Status

🔴 **NOT IMPLEMENTED** - Thermo match tracking not yet added to vote database system.

Priority: **Medium** - Nice to have for better confidence, but not blocking species identification.
