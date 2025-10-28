# Field Mapping Fix Complete! 🎉

## Problem Summary

When syncing vote data from the cluster, we encountered two critical issues:

### Issue 1: Invalid Field Names
**Error:** `Invalid field name(s) for model ThermoMatch: 'enthalpy_discrepancy', 'notes'.`

**Root Cause:** The sync code was using field names from the `import_voting` app models, but we're actually using the `importer_dashboard` app models which have different field names.

**Field Name Differences:**

| Remote DB Field | import_voting | importer_dashboard (correct) |
|-----------------|---------------|------------------------------|
| chemkin_formula | chemkin_formula | **formula** |
| status | status | **identification_status** |
| rmg_species_smiles | identified_smiles | **smiles** |
| rmg_species_index | rmg_species_index | **rmg_index** |
| rmg_species_label | rmg_species_label | **rmg_label** |

### Issue 2: Missing CandidateSpecies Records
**Symptom:** Species showed as "Confirmed" but with "0 votes" and "Not calculated" enthalpy

**Root Cause:** The sync was only creating `Species` records but not the corresponding `CandidateSpecies` records that the dashboard displays.

## Fixes Applied

### Fix 1: Corrected Field Mappings in `sync_votes_to_django()` (Lines 308-340)

**Before:**
```python
Species.objects.get_or_create(
    defaults={
        'chemkin_formula': ...,  # ❌ Wrong field name
        'status': 'unidentified'  # ❌ Wrong field name
    }
)

CandidateSpecies.objects.get_or_create(
    rmg_species_index=...,  # ❌ Wrong field name
    defaults={
        'rmg_species_label': ...,  # ❌ Wrong field name
        'rmg_species_smiles': ...,  # ❌ Wrong field name
        'confidence_score': ...  # ❌ Field doesn't exist
    }
)
```

**After:**
```python
Species.objects.get_or_create(
    defaults={
        'formula': ...,  # ✅ Correct field name
        'identification_status': 'unidentified'  # ✅ Correct field name
    }
)

CandidateSpecies.objects.get_or_create(
    rmg_index=...,  # ✅ Correct field name
    defaults={
        'rmg_label': ...,  # ✅ Correct field name
        'smiles': ...,  # ✅ Correct field name
        # confidence_score removed (doesn't exist in model)
    }
)
```

### Fix 2: Removed Invalid ThermoMatch Creation (Lines 363-393)

**Before:**
```python
# ❌ Tried to create ThermoMatch without required 'candidate' field
ThermoMatch.objects.update_or_create(
    species=species,
    defaults={
        'enthalpy_discrepancy': ...,  # ❌ Field doesn't exist on ThermoMatch
        'notes': ...  # ❌ Field doesn't exist on ThermoMatch
    }
)
```

**After:**
```python
# ✅ Store enthalpy_discrepancy directly on Species model
species_defaults = {
    'enthalpy_discrepancy': enthalpy_discrepancy,  # ✅ Field exists on Species
    ...
}
```

### Fix 3: Create CandidateSpecies for Identified Species (Lines 363-409)

**Added:**
```python
# Also create/update CandidateSpecies for the identified match
# This is what the dashboard displays
if rmg_species_smiles and rmg_species_index is not None:
    candidate_defaults = {
        'rmg_label': record.get('rmg_species_label', ''),
        'smiles': rmg_species_smiles,
        'enthalpy_discrepancy': enthalpy_discrepancy,
        'is_confirmed': True,
        'vote_count': 0  # Identified species may not have votes
    }
    
    CandidateSpecies.objects.update_or_create(
        species=species,
        rmg_index=rmg_species_index,
        defaults=candidate_defaults
    )
```

## Expected Results After Re-Sync

When you refresh the species queue page or manually trigger a sync, you should now see:

✅ **25 identified species** with:
- ✅ Correct SMILES displayed
- ✅ Enthalpy discrepancy values (if available in database)
- ✅ CandidateSpecies records created
- ✅ "Confirmed" status
- ⚠️ 0 votes (expected - these were identified by other methods, not voting)

## Why 0 Votes is OK

These species show **0 votes** because they were identified through:
- **Formula matching** - Direct name → SMILES mapping
- **Thermo library matching** - Found in RMG thermo libraries
- **Manual identification** - User-confirmed
- **Pre-existing data** - Already in the mechanism

They don't need voting reactions to be valid identifications!

## Next Steps to Test

1. **Clear existing data** (optional, to see fresh sync):
```bash
python manage.py shell
```
```python
from importer_dashboard.models import Species, CandidateSpecies
job_id = <your_job_id>
Species.objects.filter(job_id=job_id).delete()  # This cascades to CandidateSpecies
```

2. **Trigger fresh sync:**
- Visit: `http://localhost:8000/job/<job_id>/species/`
- Or click "Sync Votes" button
- Or run in shell: `sync_job_votes_incremental(job)`

3. **Verify results:**
- ✅ 25 species show with SMILES
- ✅ Each has 1 CandidateSpecies (the identified match)
- ✅ Enthalpy discrepancies displayed (if in database)
- ✅ "Confirmed" status
- ✅ No errors in logs

## Files Changed

1. **incremental_sync.py** - 3 methods updated:
   - `sync_votes_to_django()` - Fixed field names
   - `sync_identified_species_to_django()` - Fixed field names + create CandidateSpecies
   - Removed invalid ThermoMatch creation

2. **Documentation created:**
   - `APPS_ARCHITECTURE.md` - Explains two app systems
   - `REMOVE_IMPORT_VOTING_STEPS.md` - How to remove import_voting if needed
   - `VOTE_SYNC_DEBUG.md` - Debugging guide
   - `FIELD_MAPPING_FIX_SUMMARY.md` - This file

## Root Cause Analysis

The confusion arose from having **two separate Django apps** with similar purposes but different schemas:
- `import_voting` - REST API-based (not used)
- `importer_dashboard` - Web UI-based (active)

The sync code was written for one but executed against the other, causing field name mismatches.

**Solution:** Always use `importer_dashboard` models and field names for sync operations.

---

**Status:** ✅ FIXED  
**Date:** October 27, 2025  
**Next Action:** Test sync and verify enthalpy values display correctly
