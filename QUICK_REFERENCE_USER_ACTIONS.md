# Quick Reference: User Actions

## 📋 Species Identification Workflow

```
┌─────────────────────────────────────────────────────┐
│            Species Queue (Main Page)                │
│  http://localhost:8000/job/{job_id}/species/       │
└────────────┬────────────────────────────────────────┘
             │
             │ Click on species
             ▼
┌─────────────────────────────────────────────────────┐
│         Species Detail Page                         │
│  http://localhost:8000/job/{job_id}/species/{id}/  │
│                                                     │
│  Shows:                                             │
│  • Species info (label, formula, status)            │
│  • All candidate matches (ranked)                   │
│  • For each candidate:                              │
│    - SMILES                                         │
│    - Enthalpy discrepancy                           │
│    - Vote counts                                    │
│    - Voting reactions                               │
│    - Confidence score                               │
└────────────┬────────────────────────────────────────┘
             │
             │ User has 3 choices:
             │
    ┌────────┴────────┬─────────────┐
    │                 │             │
    ▼                 ▼             ▼
┌───────┐      ┌──────────┐   ┌────────────┐
│Confirm│      │  Block   │   │Submit      │
│Match  │      │  Match   │   │SMILES      │
└───┬───┘      └────┬─────┘   └─────┬──────┘
    │               │               │
    ▼               ▼               ▼
  ✅ OK          ❌ Wrong        ✏️ Custom
```

## 🎯 Three User Actions

### 1. ✅ Confirm Match
**Purpose:** Accept a candidate as correct

**Button:** Green "Confirm" button on candidate card

**Process:**
```
User clicks "Confirm"
    ↓
Modal dialog asks for confirmation
    ↓
User confirms
    ↓
POST /job/{job_id}/species/{id}/confirm/
    ↓
Species status → "confirmed"
Species SMILES → assigned
User recorded
    ↓
Redirect to species queue
```

**Code:** `species_views.py:confirm_match()`

---

### 2. ❌ Block Match
**Purpose:** Reject an incorrect candidate

**Button:** Red "Block" button on candidate card

**Process:**
```
User clicks "Block"
    ↓
Modal dialog asks for reason (optional)
    ↓
User provides reason and confirms
    ↓
POST /job/{job_id}/species/{id}/block/
    ↓
Candidate.is_blocked → True
Votes deleted for this candidate
User recorded as blocker
    ↓
Candidate removed from consideration
```

**Code:** `species_views.py:block_match()`

---

### 3. ✏️ Submit Custom SMILES
**Purpose:** Provide your own SMILES when no good candidates

**Location:** Form at bottom of species detail page

**Process:**
```
User enters SMILES string
    ↓
User clicks "Submit SMILES"
    ↓
POST /job/{job_id}/species/{id}/submit-smiles/
    ↓
New CandidateSpecies created
SMILES assigned
Marked as "manual"
    ↓
Page reloads showing new candidate
    ↓
User can then confirm it
```

**Code:** `species_views.py:submit_smiles()`

---

## 🔄 Voting vs User Actions

### Voting (Automatic)
```
Cluster Running RMG
    ↓
Generate Reactions
    ↓
Each Reaction "Votes" for Species Matches
    ↓
Votes Stored in SQLite Database
    ↓
Dashboard Syncs via SSH
    ↓
Votes Displayed in UI
```

**Users DON'T cast votes!**
Votes are automatic from reaction analysis.

### User Actions (Manual)
```
User Reviews Candidates
    ↓
Looks at Votes & Evidence
    ↓
Makes Decision:
    • Confirm if correct
    • Block if wrong
    • Submit SMILES if no match
    ↓
Species Identified
```

**Users make final identification decision!**

---

## 📊 Data Flow Diagram

```
┌─────────────────────────────────────────────────────┐
│              CLUSTER (SSH)                          │
│  /projects/.../CombFlame2013/2343-Hansen/          │
│                                                     │
│  votes_db8cff...db (SQLite)                        │
│  ├─ species_votes (automatic votes)                │
│  ├─ voting_reactions (evidence)                    │
│  ├─ identified_species (confirmed)                 │
│  └─ blocked_matches (user blocks)                  │
└─────────────┬───────────────────────────────────────┘
              │
              │ SSH + SQLite Queries
              │ (Incremental Sync)
              ▼
┌─────────────────────────────────────────────────────┐
│           DJANGO DASHBOARD (Local)                  │
│                                                     │
│  Models:                                            │
│  • Species (chemkin species)                        │
│  • CandidateSpecies (potential matches)             │
│  • Vote (individual reaction votes)                 │
│  • BlockedMatch (user rejections)                   │
│  • SyncLog (sync history)                           │
└─────────────┬───────────────────────────────────────┘
              │
              │ HTTP/Templates
              │
              ▼
┌─────────────────────────────────────────────────────┐
│               WEB UI (Browser)                      │
│                                                     │
│  Pages:                                             │
│  • Species Queue - List all species                 │
│  • Species Detail - Show candidates & votes         │
│                                                     │
│  User Actions:                                      │
│  [Confirm] [Block] [Submit SMILES]                  │
└─────────────────────────────────────────────────────┘
```

---

## 🎨 UI Elements

### Species Queue Card
```
┌────────────────────────────────────┐
│ CH2                    [Confirmed] │
│ Formula: CH2                       │
│ ────────────────────────────────── │
│ 👥 0 votes  |  📊 30% confidence   │
│ 🎯 1 candidate                     │
│                                    │
│ Top: [CH2]                         │
│ ΔH: 0.88 kcal/mol                  │
│                                    │
│        [View Details →]            │
└────────────────────────────────────┘
```

### Candidate Card (Detail Page)
```
┌────────────────────────────────────────────┐
│ #1  CH2               [30% Confidence]     │
│ ──────────────────────────────────────────│
│ SMILES                                     │
│ [CH2]                                      │
│                                            │
│ ENTHALPY Δ                                 │
│ 0.88 kcal/mol (0.88 absolute)             │
│                                            │
│ VOTING STATS                               │
│ 0 unique • 0 total                         │
│                                            │
│ VOTING EVIDENCE                            │
│ No voting evidence available               │
│                                            │
│ ──────────────────────────────────────────│
│ [✅ Confirm]          [❌ Block]          │
└────────────────────────────────────────────┘
```

---

## ⚙️ Configuration

### URL Routes (`urls.py`)
```python
path('job/<int:job_id>/species/', species_queue, name='species_queue'),
path('job/<int:job_id>/species/<int:species_id>/', species_detail, name='species_detail'),
path('job/<int:job_id>/species/<int:species_id>/confirm/', confirm_match, name='confirm_match'),
path('job/<int:job_id>/species/<int:species_id>/block/', block_match, name='block_match'),
path('job/<int:job_id>/species/<int:species_id>/submit-smiles/', submit_smiles, name='submit_smiles'),
```

### View Functions (`species_views.py`)
```python
def species_queue(request, job_id)           # List page
def species_detail(request, job_id, species_id)  # Detail page
def confirm_match(request, job_id, species_id)   # POST: confirm
def block_match(request, job_id, species_id)     # POST: block
def submit_smiles(request, job_id, species_id)   # POST: custom SMILES
```

---

## 💡 Tips

**For efficient identification:**
1. Sort by confidence (high → low)
2. Confirm obvious matches first
3. Review voting evidence for uncertain cases
4. Block clearly wrong matches
5. Submit custom SMILES for missing species

**Understanding your CH2 case:**
- ✅ Already confirmed (nothing to do)
- 0 votes = Pre-identified (formula/thermo match)
- 30% confidence = Only 1 candidate, no votes
- This is normal and OK!

---

**Quick Answer to Your Question:**

**Voting:** Automatic (cluster generates during import)
**User Actions:** Confirm ✅, Block ❌, or Submit SMILES ✏️

Your CH2 is already confirmed, so no action needed! The 0 votes just mean it was identified through formula matching, not reaction voting.
