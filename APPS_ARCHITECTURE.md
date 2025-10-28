# Django Apps Architecture

This project contains **two separate voting/import systems**. They serve different purposes and should not be confused.

## 1. `importer_dashboard` (Primary - Currently Active)

**Purpose:** Web dashboard for managing cluster-based RMG import jobs with SSH integration

**Features:**
- SSH connection to cluster
- Real-time job monitoring
- Species identification queue
- Vote data sync via incremental SSH queries
- User interface for species confirmation

**Models:**
- `ClusterJob` - Running import jobs on cluster
- `Species` - Chemkin species being identified
- `CandidateSpecies` - Potential RMG matches
- `Vote` - Reaction-based votes for matches
- `ThermoMatch` - Thermo library matches
- `BlockedMatch` - User-blocked matches

**Key Field Names:**
- `identification_status` (not `status`)
- `smiles` (not `identified_smiles`)
- `formula` (not `chemkin_formula`)

**Location:** `/importer_dashboard/`
**URLs:** `/job/`, `/species/`, etc.
**Database sync:** SSH-based from cluster SQLite files

---

## 2. `import_voting` (REST API - Standalone)

**Purpose:** Standalone REST API for species voting system (cluster-independent)

**Features:**
- REST API endpoints
- JSON-based data exchange
- Bulk create/update operations
- Statistics endpoints
- API-first design

**Models:**
- `ImportJob` - Abstract import job records
- `SpeciesVote` - Species matching votes
- `VotingReaction` - Reactions contributing to votes
- `IdentifiedSpecies` - Confirmed species
- `BlockedMatch` - Blocked matches

**Key Field Names:**
- No `status` field on species
- `rmg_species_smiles` (different naming)
- `chemkin_formula` (different naming)

**Location:** `/import_voting/`
**URLs:** `/api/import-voting/`
**Database sync:** API-based (originally designed for cluster API, but cluster blocks outbound connections)

---

## Which One to Use?

### Use `importer_dashboard` if:
- ✅ Working with the Django web UI
- ✅ Managing cluster jobs
- ✅ SSH-based sync from cluster
- ✅ Interactive species identification
- **👉 THIS IS THE ACTIVE SYSTEM**

### Use `import_voting` if:
- ⚠️ Building external integrations
- ⚠️ Need a pure REST API
- ⚠️ Cluster API becomes available (currently blocked)
- **👉 NOT CURRENTLY USED**

---

## History & Context

1. **Original Design:** `import_voting` was created as an API-first system
2. **Network Issue:** Cluster firewall blocks outbound API connections
3. **Current Solution:** `importer_dashboard` uses SSH-based incremental sync instead
4. **Result:** Two systems exist, but only `importer_dashboard` is actively used

---

## For Developers

### When syncing vote data:
Always use `importer_dashboard` models and field names:

```python
# ✅ CORRECT - Use importer_dashboard models
from importer_dashboard.models import Species, CandidateSpecies

species = Species.objects.create(
    job=job,
    chemkin_label="CH3",
    formula="CH3",  # Not chemkin_formula
    identification_status="confirmed",  # Not status
    smiles="[CH3]"  # Not identified_smiles
)

# ❌ WRONG - Don't use import_voting models
from import_voting.models import SpeciesVote  # Don't use this
```

### When adding new features:
- Add to `importer_dashboard` (the active system)
- Don't modify `import_voting` unless reviving the API approach
- Test with the web UI, not just the API

---

## Future Considerations

### If Cluster API Becomes Available:
- Could revive `import_voting` for API-based sync
- Would need to migrate data between systems
- Consider consolidating into one system

### If REST API Not Needed:
- Could deprecate `import_voting` entirely
- Remove from `INSTALLED_APPS`
- Delete migrations and tables
- Keep as reference/documentation only

---

## Decision: Keep or Delete?

**Current Status: KEEP (Documented)**

**Reasons:**
- Recent migrations (Oct 2025) suggest intentional creation
- Complete REST API implementation
- No conflicts (isolated)
- Potential future use if cluster API becomes available

**Action Items:**
- ✅ Document both systems (this file)
- ✅ Use only `importer_dashboard` for active development
- ⚠️ Consider removal if unused for 6+ months
- ⚠️ Consider consolidation if both systems needed

---

**Last Updated:** October 27, 2025  
**Primary System:** `importer_dashboard` (SSH-based)  
**Secondary System:** `import_voting` (API-based, dormant)
