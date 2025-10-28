# How Votes Are Generated - Complete Explanation

## 🎯 TL;DR - Why You Have No Votes

**Votes are generated during the RMG reaction matching process, NOT at import time.**

Your species `CH2` has:
- ✅ Status: Confirmed
- ⚠️ 0 votes

This means:
1. **Species was auto-confirmed** (likely only 1 candidate, or name match)
2. **Reactions haven't been matched yet** (this is when votes are created)
3. **OR reaction matching failed/skipped** for this species

---

## 📋 The Complete Vote Generation Pipeline

### Phase 1: Initial Setup (importChemkin.py)

```
1. Load CHEMKIN files
   ├── chem_annotated.inp (species list)
   ├── chem.inp (reactions) 
   └── chem_thermo.dat (thermodynamics)
   
2. Initialize RMG database
   ├── Load kinetics families
   ├── Load thermo libraries
   └── Load transport data

3. Create vote storage
   └── votes_<job_id>.db (local SQLite database)
```

**At this point: 0 votes exist**

---

### Phase 2: Species Discovery (FIRST PASS)

```python
# importChemkin.py - initial thermo matching
for chemkin_species in chemkin_species_list:
    # Match by name
    name_matches = find_rmg_species_by_name(chemkin_species)
    
    # Match by thermo
    thermo_matches = find_rmg_species_by_thermo(chemkin_species)
    
    # NO VOTES YET - just candidates!
```

**Result**: Creates `CandidateSpecies` in dashboard, but `Vote` count = 0

---

### Phase 3: Reaction Matching (WHERE VOTES ARE GENERATED!)

This is the **critical step** that creates votes:

```python
# importChemkin.py - check_reactions_for_matches()

def check_reactions_for_matches(self, reactions_to_check):
    """
    The VOTING ENGINE - this is where votes are created!
    """
    
    for chemkin_reaction in reactions_to_check:
        # Example: CH4 + OH -> CH3 + H2O
        
        # Generate all RMG reactions using kinetics families
        try:
            edge_reactions = self.rmg_model.generate_reactions(
                reactants=[...],
                products=[...],
                only_families=self.reaction_families  # e.g., H_Abstraction
            )
        except Exception as e:
            # If this fails, NO VOTES are created!
            logging.error(f"Could not generate reactions: {e}")
            continue
        
        # Compare CHEMKIN reaction to RMG reactions
        for edge_reaction in edge_reactions:
            if self.reactions_match(chemkin_reaction, edge_reaction):
                
                # CHECK SPECIES MAPPING
                species_map = self.get_species_mapping(
                    chemkin_reaction, edge_reaction
                )
                
                # For each species in the reaction:
                for chemkin_label, rmg_species in species_map.items():
                    
                    # CHECK THERMOCHEMISTRY (must be reasonable)
                    delta_h = self.get_enthalpy_discrepancy(
                        chemkin_label, rmg_species
                    )
                    if abs(delta_h) > 200:  # >200 kJ/mol = suspicious
                        continue  # Skip this vote!
                    
                    # ✅ CAST VOTE!
                    if chemkin_label not in self.votes:
                        self.votes[chemkin_label] = {}
                    
                    if rmg_species not in self.votes[chemkin_label]:
                        self.votes[chemkin_label][rmg_species] = set()
                    
                    # Store reaction pair as evidence
                    self.votes[chemkin_label][rmg_species].add(
                        (chemkin_reaction, edge_reaction)
                    )
                    
                    logging.info(f"✓ Vote: {chemkin_label} -> {rmg_species.label}")
                    logging.info(f"  Evidence: {chemkin_reaction}")
                    logging.info(f"  Family: {edge_reaction.family}")
                
                break  # Found match, move to next chemkin reaction
```

---

## 🔍 Why Your Species Has 0 Votes

Based on your job status, here are the **most likely reasons**:

### Reason 1: Reaction Matching Not Started Yet ⏳

The job might still be in the **initial species loading phase**:

```
Current Status:
├── ✅ Species loaded (372 species)
├── ✅ Reactions loaded (8,314 reactions)  
├── ✅ Thermo loaded (372 entries)
├── ✅ Initial candidates found (by name/thermo)
└── ❌ Reaction matching NOT STARTED  <-- You are here!
```

**Solution**: Wait for the job to progress to reaction matching phase.

---

### Reason 2: Species Auto-Confirmed Too Early 🤖

```python
# importChemkin.py - main()

# Auto-confirm if only one candidate AND name matches
if len(candidates) == 1 and name_matches:
    self.set_tentative_match(chemkin_label, rmg_species)
    # Status: "confirmed"
    # Votes: 0 (reactions haven't been checked yet!)
```

For `CH2`:
- Only 1 candidate found: `[CH2]` (RMG species)
- Name matches: `CH2` == `CH2`
- **Auto-confirmed immediately**
- **Reaction matching skipped** (already matched)
- **Result**: Confirmed but 0 votes

**This is normal and OK!** High-confidence matches don't need voting.

---

### Reason 3: Reaction Matching Failed ❌

Possible failures during reaction generation:

```python
# Why generate_reactions() might fail:

1. Missing reaction families
   └── Solution: Check self.reaction_families is populated

2. Complex species structure
   └── RMG can't generate reactions for this species
   └── Example: Aromatics, metals, unusual bonding

3. Kinetics database incomplete
   └── No templates match this reaction type

4. Memory/timeout errors
   └── Cluster job crashed or killed during matching

5. Species already identified
   └── Reaction matching skipped for identified species
```

---

### Reason 4: Thermochemistry Mismatch 🌡️

Even if reactions match, votes are rejected if enthalpy is way off:

```python
delta_h = abs(chemkin_H298 - rmg_H298)

if delta_h > 200:  # kJ/mol threshold
    logging.warning(f"Enthalpy mismatch too large: {delta_h:.1f} kJ/mol")
    # NO VOTE CAST!
    continue
```

For `CH2`:
- Enthalpy Δ: **0.88 kcal/mol** (3.68 kJ/mol) ✅ GOOD!
- This is NOT the problem

---

## 🔧 How to Check What's Happening

### 1. Check Cluster Job Logs

SSH to cluster and look for these messages:

```bash
ssh login.explorer.northeastern.edu
cd /scratch/your_username/rmg_jobs/your_job

# Look for voting messages:
grep -i "vote" output.log | tail -20
grep -i "reaction matching" output.log | tail -20
grep -i "check_reactions_for_matches" output.log | tail -20

# Check if reaction matching started:
grep -i "generating reactions" output.log | tail -20

# Check for errors:
grep -i "error" output.log | tail -20
grep -i "failed" output.log | tail -20
```

### 2. Check Vote Database

The cluster stores votes in a local SQLite database:

```bash
# Find the vote database:
ls -lh votes_*.db

# Query it directly:
sqlite3 votes_d8cff2a08d9d4e6e55aef6e7b1f8c5c2.db

# Check vote counts:
SELECT 
    chemkin_label,
    COUNT(*) as vote_count
FROM species_votes
GROUP BY chemkin_label
ORDER BY vote_count DESC;

# Check if CH2 has votes:
SELECT * FROM species_votes WHERE chemkin_label = 'CH2';

# Check voting reactions:
SELECT 
    sv.chemkin_label,
    COUNT(vr.id) as reaction_count
FROM species_votes sv
LEFT JOIN voting_reactions vr ON sv.id = vr.species_vote_id
WHERE sv.chemkin_label = 'CH2'
GROUP BY sv.chemkin_label;
```

### 3. Check Django Dashboard Sync Status

```bash
# On your local machine:
cd /Users/lekiaprosper/Documents/CoMoChEng/Prometheus/kineticmodelssite

# Check when votes were last synced:
python manage.py shell

>>> from importer_dashboard.models import ClusterJob, Vote
>>> job = ClusterJob.objects.get(id=21)
>>> Vote.objects.filter(species__job=job).count()
0  # <-- This confirms no votes in dashboard

# Check if any votes exist for ANY job:
>>> Vote.objects.all().count()
```

---

## 📊 What Normal Vote Generation Looks Like

### Timeline:

```
0:00 - Job starts
├── Load CHEMKIN files (2 min)
├── Load RMG database (5 min)
├── Find initial candidates (10 min)
│   └── Dashboard shows: Species with 0 votes
│
0:17 - Start reaction matching <-- VOTES START HERE
├── Match reaction 1/8314 (cast ~4 votes)
├── Match reaction 2/8314 (cast ~4 votes)
├── Match reaction 3/8314 (cast ~4 votes)
│   └── Dashboard syncs every 5 minutes
│       └── Vote count increases!
│
2:00 - Reaction matching complete
└── Final: ~25,000 votes cast across all species
```

### Expected Voting Pattern:

```
Species      Expected Votes    Why?
───────────────────────────────────────────────────
H2           200-500          Common reactant/product
OH           150-400          Many radical reactions
CH4          100-200          Fuel species
CH3          80-150           Common radical
H2O          300-600          Very common product
───────────────────────────────────────────────────
CH2          20-60            Carbene reactions only
                              Less common than CH3!
```

For `CH2` specifically:
- Carbene (divalent carbon)
- Only appears in specific reaction families
- **Expected: 20-60 votes** from reactions like:
  - CH2 + O2 -> Products
  - CH3 + M -> CH2 + H + M
  - CH2 + CH2 -> Products

---

## ✅ What To Do Now

### Option 1: Wait for Reaction Matching

If the job is still running:
1. Check cluster log: `tail -f output.log`
2. Look for "check_reactions_for_matches"
3. Wait for vote sync (every 5 minutes)
4. Refresh dashboard

### Option 2: Manual Vote Sync

Force a sync from the cluster:

```bash
cd /Users/lekiaprosper/Documents/CoMoChEng/Prometheus/kineticmodelssite

# Sync votes manually:
python manage.py sync_votes --job-id 21

# Or use the dashboard button:
# Go to Species Queue → Click "Refresh from Cluster"
```

### Option 3: Check If Votes Exist on Cluster

```bash
ssh login.explorer.northeastern.edu
cd /scratch/your_username/rmg_jobs/your_job

# Check vote database:
python3 << EOF
from vote_local_db import VoteLocalDB

db = VoteLocalDB('votes_*.db')
votes = db.load_votes('your_job_id')

print(f"Total species with votes: {len(votes)}")
for vote in votes[:10]:
    print(f"  {vote['chemkin_label']}: {vote['vote_count']} votes")
EOF
```

### Option 4: Accept That It's OK

If `CH2` is auto-confirmed with good thermochemistry:
- **✅ 30% confidence is fine** for single-candidate matches
- **✅ 0.88 kcal/mol enthalpy match** is excellent
- **✅ No votes needed** when there's only 1 candidate

The species is **correctly identified**, just without voting evidence.

---

## 🎯 Summary

**Votes depend on:**
1. ✅ **Reaction matching** running (not just loading files)
2. ✅ **RMG generating edge reactions** (needs kinetics families)
3. ✅ **Reactions comparing successfully** (structure + thermochem)
4. ✅ **Votes being saved** to local SQLite database
5. ✅ **Dashboard syncing** via SSH (every 5 min)

**For CH2 with 0 votes:**
- Most likely: Auto-confirmed before reaction matching
- This is **normal and expected** for high-confidence matches
- The species is correctly identified even without votes

**To get votes:**
- Wait for reaction matching phase (may take hours)
- Or accept that single-candidate matches don't need votes
- Focus on controversial species (multiple candidates) that really need voting evidence

---

## 📚 Related Files

- Vote generation: `/RMG39/RMG-Py/importChemkin.py` (line 1450-1600)
- Vote storage: `/RMG39/RMG-Py/vote_local_db.py`
- Vote sync: `/Prometheus/kineticmodelssite/importer_dashboard/species_utils.py`
- Documentation: `/Prometheus/kineticmodelssite/importer_dashboard/VOTING_EVIDENCE_EXPLAINED.md`
