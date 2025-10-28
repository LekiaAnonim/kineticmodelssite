# Vote Database Schema Investigation

## What We Know

From the dashboard output, we can see:
- ✅ 25 identified species synced successfully
- ❌ 0 votes synced
- ❌ All species show "0 total votes • 0 unique votes"
- ❌ All show "30% confidence" (default for 1 candidate with no votes)
- ❌ "ΔH(298K) Discrepancy: Not calculated"

## The Issue

The sync message says: "✓ Synced from cluster: **0 votes**, 25 identified, 0 blocked (full sync)"

This indicates:
1. ✅ `identified_species` table has 25 records → synced successfully
2. ❌ `species_votes` table has 0 records → no votes to sync
3. ❌ Enthalpy discrepancies not populated

## Possible Causes

### 1. Vote Data in Different Format
The cluster database might store votes differently than expected:
- Vote data might be in the `identified_species` table itself
- Enthalpy discrepancy might be a field in `identified_species`
- The `species_votes` table might not be used for pre-identified species

### 2. Schema Mismatch
The cluster SQLite schema might be different from what we expect:
```sql
-- We're querying:
SELECT * FROM species_votes WHERE ...

-- But cluster might have:
SELECT * FROM identified_species WHERE ...
-- With enthalpy_discrepancy as a column
```

### 3. Pre-Identified Species Don't Have Votes
These species were identified by:
- Formula matching
- Thermo library matching  
- Manual identification
- Not by voting reactions

So they legitimately have 0 votes, and that's okay!

## Solution: Check What's Actually in the Database

We need to:

1. **SSH to cluster and check schema:**
```bash
ssh lekia.p@login.explorer.northeastern.edu
cd /projects/westgroup/lekia.p/Importer/RMG-models/CombFlame2013/2343-Hansen
sqlite3 votes_db8cff6d0de0c718b461f76ab76fa00e.db

-- Check tables
.tables

-- Check identified_species schema
.schema identified_species

-- Check if enthalpy_discrepancy is in identified_species
PRAGMA table_info(identified_species);

-- Count records
SELECT COUNT(*) FROM identified_species;
SELECT COUNT(*) FROM species_votes;

-- Sample data
SELECT * FROM identified_species LIMIT 5;
```

2. **Check the JSON export you created:**
The JSON file should show the actual data structure:
```bash
cat votes_db8cff6d0de0c718b461f76ab76fa00e.json | head -50
```

## Expected Fix

If enthalpy_discrepancy is in `identified_species`, we need to update the sync query:

```python
# In get_updated_identified_species():
query = f"""
SELECT 
    chemkin_label,
    chemkin_formula,
    rmg_species_label,
    rmg_species_smiles,
    rmg_species_index,
    identification_method,
    identified_by,
    enthalpy_discrepancy,  # <-- Add this
    notes,
    created_at,
    updated_at
FROM identified_species
{where_clause}
"""
```

Then the sync_identified_species_to_django() method will correctly populate the enthalpy values.

## Next Steps

1. Check the actual database schema on cluster
2. Verify which table has enthalpy_discrepancy
3. Update the SQL query if needed
4. Re-run sync to populate enthalpy values
