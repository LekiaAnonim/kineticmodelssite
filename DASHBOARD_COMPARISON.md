# 📊 Dashboard Comparison: Old vs. New Architecture

## Overview

There are **two separate dashboards** with different purposes:

1. **dashboard_new.py** (Old System) - Job monitoring and control
2. **importer_dashboard** (New System) - Species identification and voting

---

## 🏗️ Architecture Comparison

### Old System: dashboard_new.py

**Location:** `/Users/lekiaprosper/Documents/CoMoChEng/Prometheus/RMG-importer/dashboard_new.py`

**Purpose:** Monitor and control RMG import jobs running on cluster

**Technology Stack:**
- Python standalone script
- CherryPy web server (port 8000)
- SSH tunneling via Paramiko
- Direct port forwarding to cluster jobs
- No database persistence

**Key Features:**
```python
# Job monitoring dashboard
- Start/stop/kill jobs
- View RMG log files
- Monitor job progress (processed/confirmed/total counts)
- SSH tunnel management
- Error log viewing
- Git pull operations
```

**User Interface:**
```
http://localhost:8000/
├── / (index)           - Job list with controls
├── /start/{port}       - Start a job
├── /kill/{port}        - Kill a job
├── /log/{port}         - View RMG.log tail
├── /error/{port}       - View error.log
├── /progress           - Refresh progress counts
├── /tunnels            - Reconnect SSH tunnels
└── /settings           - Configure SLURM settings
```

**Progress Display:**
```
| Mechanism | Port | Job # | Status | Processed | Identified | Total |
|-----------|------|-------|--------|-----------|------------|-------|
| Hansen    | 8001 | 12345 | Run    | 218       | 218        | 230   |
```

**Limitations:**
- ❌ No species identification interface
- ❌ No voting visualization
- ❌ No candidate selection
- ❌ No user confirmation workflow
- ❌ Only shows aggregate counts
- ❌ Cannot drill down to individual species
- ❌ Read-only access to cluster jobs

---

### New System: importer_dashboard (Django)

**Location:** `/Users/lekiaprosper/Documents/CoMoChEng/Prometheus/kineticmodelssite/importer_dashboard/`

**Purpose:** Interactive species identification with voting system

**Technology Stack:**
- Django web framework
- PostgreSQL/SQLite database
- SSH-based incremental sync
- Bootstrap UI with AJAX
- Model-View-Template architecture

**Key Features:**
```python
# Species identification dashboard
- Browse all species in a job
- View candidate matches for each species
- See voting evidence from reactions
- Confirm correct matches
- Block incorrect matches
- Submit custom SMILES
- Track identification history
```

**User Interface:**
```
http://localhost:8000/importer/
├── /jobs/                              - Job list
├── /job/{job_id}/species/              - Species queue (filterable)
│   ├── ?status=unidentified            - Filter unidentified
│   ├── ?status=tentative               - Filter tentative
│   ├── ?status=confirmed               - Filter confirmed
│   └── ?sort=controversial             - Sort by controversy
├── /job/{job_id}/species/{species_id}/ - Species detail page
│   ├── Candidate cards with votes
│   ├── Confirm/Block buttons
│   └── Custom SMILES form
├── /job/{job_id}/species/{species_id}/confirm/     - Confirm endpoint
├── /job/{job_id}/species/{species_id}/block/       - Block endpoint
└── /job/{job_id}/species/{species_id}/submit-smiles/ - Custom SMILES
```

**Species Queue Display:**
```
┌─────────────────────────────────────────┐
│ CH4 (Methane)                    [30%] │
│ Status: Tentative  |  3 candidates     │
│ Top: CH4 [C] (10 votes)                │
│ [View Details →]                        │
└─────────────────────────────────────────┘
```

**Species Detail Page:**
```
┌─────────────────────────────────────────────────────────────┐
│ Species: CH4                                                 │
│ Formula: CH4  |  Status: Tentative                          │
│                                                              │
│ Candidates (3):                                             │
│                                                              │
│ 🥇 #1 - CH4 [C]                              Confidence: 85% │
│    Votes: 10 unique, 25 total                               │
│    ΔH(298K): 2.3 kJ/mol discrepancy                         │
│    [✓ Confirm]  [✗ Block]  [👁 View Reactions]              │
│                                                              │
│ 🥈 #2 - methane [C]                          Confidence: 10% │
│    Votes: 2 unique, 3 total                                 │
│    ΔH(298K): 15.7 kJ/mol discrepancy                        │
│    [✓ Confirm]  [✗ Block]  [👁 View Reactions]              │
│                                                              │
│ 🥉 #3 - CH3 radical [CH3]                    Confidence: 5%  │
│    Votes: 1 unique, 1 total                                 │
│    ΔH(298K): 138.2 kJ/mol discrepancy                       │
│    [✓ Confirm]  [✗ Block]  [👁 View Reactions]              │
│                                                              │
│ ── Submit Custom SMILES ──────────────────────────────────  │
│ If none of the above are correct, enter SMILES:            │
│ [_________________]  [Submit]                               │
└─────────────────────────────────────────────────────────────┘
```

**Advantages:**
- ✅ Interactive species identification
- ✅ Visual voting evidence
- ✅ User confirmation workflow
- ✅ Candidate ranking and confidence scores
- ✅ Database persistence
- ✅ User tracking and audit trail
- ✅ Incremental sync from cluster
- ✅ Detailed drill-down to individual species

---

## 🔄 How They Work Together

```
┌─────────────────────────────────────────────────────────────┐
│                    CLUSTER (Explorer)                        │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  RMG-Py Import Jobs (Running)                          │ │
│  │  - Job: CombFlame2013/2343-Hansen                      │ │
│  │  - Port: 8001                                          │ │
│  │  - Generates reactions → votes                         │ │
│  │  - Writes to votes_db8cff...db (SQLite)                │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ SSH Tunnel (Paramiko)
                              │ SSH Query (Incremental Sync)
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    LOCAL MACHINE                             │
│                                                              │
│  ┌────────────────────────────────────────┐                 │
│  │  dashboard_new.py (Port 8000)          │                 │
│  │  - Monitor job status                  │                 │
│  │  - Start/stop jobs                     │                 │
│  │  - View logs                           │                 │
│  │  - Shows aggregate counts              │                 │
│  │    (processed: 218, confirmed: 218)    │                 │
│  └────────────────────────────────────────┘                 │
│                                                              │
│  ┌────────────────────────────────────────┐                 │
│  │  Django (importer_dashboard)           │                 │
│  │  - Species identification UI           │                 │
│  │  - Voting visualization                │                 │
│  │  - User confirmations                  │                 │
│  │  - Database storage                    │                 │
│  │  - Incremental sync via SSH            │                 │
│  └────────────────────────────────────────┘                 │
│                                                              │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ Browser
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    USER                                      │
│                                                              │
│  dashboard_new.py            importer_dashboard             │
│  ├─ Start Hansen job         ├─ View Hansen species         │
│  ├─ Monitor progress          ├─ Confirm CH4 → [C]          │
│  ├─ View logs                 ├─ Block wrong matches        │
│  └─ Kill job when done        └─ Submit custom SMILES       │
└─────────────────────────────────────────────────────────────┘
```

---

## 📋 Typical User Workflow

### Phase 1: Start Job (dashboard_new.py)

1. **SSH to dashboard:**
   ```bash
   cd /Users/lekiaprosper/Documents/CoMoChEng/Prometheus/RMG-importer
   python dashboard_new.py
   ```

2. **Open browser:**
   ```
   http://localhost:8000/
   ```

3. **Start a job:**
   - Click "start" next to mechanism
   - Job submits to SLURM
   - RMG begins processing on cluster

4. **Monitor progress:**
   - Refresh to see job running
   - Click "log" to view RMG.log
   - Watch processed/confirmed counts increase
   - Wait for job to complete

---

### Phase 2: Identify Species (importer_dashboard)

1. **Start Django server:**
   ```bash
   cd /Users/lekiaprosper/Documents/CoMoChEng/Prometheus/kineticmodelssite
   conda activate kms
   python manage.py runserver
   ```

2. **Open browser:**
   ```
   http://localhost:8000/importer/
   ```

3. **Select job:**
   - Choose "CombFlame2013/2343-Hansen"
   - Click to view species

4. **Sync votes (if needed):**
   - Click "Sync Votes" button at top
   - Wait for incremental sync to complete
   - Vote counts update

5. **Filter species:**
   - Click "Unidentified" tab
   - Or "Tentative" for candidates needing review

6. **For each species:**
   
   a. **Click species card** → Detail page
   
   b. **Review candidates:**
      - Check SMILES structures
      - Compare enthalpy discrepancies
      - Review vote counts
      - Check confidence scores
   
   c. **Make decision:**
      - **Option 1: Confirm** (if correct)
        - Click "Confirm" button
        - Confirm in modal
        - Species → confirmed
      
      - **Option 2: Block** (if wrong)
        - Click "Block" button
        - Provide reason
        - Candidate removed
      
      - **Option 3: Submit SMILES** (if no match)
        - Scroll to bottom
        - Enter correct SMILES
        - Click "Submit SMILES"
        - New candidate created
        - Then confirm it

7. **Repeat until all species identified**

---

### Phase 3: Export Results (future)

**Currently manual, but could add:**
- Export identified species to CSV
- Generate ChemKin with RMG SMILES
- Upload to database
- Generate report

---

## 🎯 Key Differences Summary

| Feature                    | dashboard_new.py      | importer_dashboard    |
|----------------------------|-----------------------|-----------------------|
| **Purpose**                | Job monitoring        | Species identification|
| **Technology**             | CherryPy standalone   | Django framework      |
| **Database**               | None (transient)      | PostgreSQL/SQLite     |
| **User Actions**           | Start/stop jobs       | Confirm/block species |
| **Granularity**            | Job-level             | Species-level         |
| **Voting**                 | Shows counts only     | Full visualization    |
| **Persistence**            | None                  | Full history          |
| **Concurrency**            | Single user           | Multi-user capable    |
| **Authentication**         | None                  | Django auth           |
| **API**                    | None                  | REST endpoints        |

---

## 🚀 User Decision-Making Process

### In dashboard_new.py (Old):
```
User sees:
  "Processed: 218, Confirmed: 218, Total: 230"

User can:
  - Start/stop jobs
  - View logs
  - Monitor progress

User CANNOT:
  - See individual species
  - Make identification decisions
  - View voting evidence
  - Confirm/block matches
```

### In importer_dashboard (New):
```
User sees:
  CH4 (Methane)
  Status: Tentative
  Top candidate: CH4 [C] (10 votes, 85% confidence)
  ΔH: 2.3 kJ/mol

User can:
  1. Review candidate details
  2. Check voting reactions
  3. Compare enthalpy
  4. Make decision:
     a) Confirm ✓
     b) Block ✗
     c) Submit custom SMILES ✏️

User actions are:
  - Recorded in database
  - Tracked by username
  - Reversible (can block after confirm)
  - Auditable (full history)
```

---

## 💡 Design Philosophy

### dashboard_new.py:
- **Admin tool** - For managing cluster jobs
- **Read-mostly** - Few write operations
- **Cluster-focused** - Direct tunnel to RMG jobs
- **Lightweight** - Standalone script, no dependencies
- **Operations view** - System health and job status

### importer_dashboard:
- **User tool** - For domain experts
- **Write-heavy** - Many confirmation/blocking actions
- **Data-focused** - Species and voting data
- **Full-featured** - Django ORM, migrations, auth
- **Science view** - Chemical species and thermodynamics

---

## 📚 User Guide for Making Decisions

### Step-by-Step: Confirming a Species

**Scenario:** You need to confirm that "CH4" in the CHEMKIN file matches RMG species [C].

1. **Navigate to species:**
   ```
   importer_dashboard → Jobs → Hansen → Species Queue → Click CH4
   ```

2. **Review evidence:**
   - **SMILES:** [C] (single carbon with 4 hydrogens)
   - **Votes:** 10 unique reactions voted for this
   - **Enthalpy:** 2.3 kJ/mol difference (very close)
   - **Confidence:** 85% (high)

3. **Check reactions (optional):**
   - Click "View Reactions"
   - See which reactions use this species
   - Verify they make chemical sense
   - Example: CH4 + OH → CH3 + H2O

4. **Make decision:**
   - Click green "Confirm" button
   - Modal appears: "Are you sure?"
   - Review SMILES one more time
   - Click "Confirm" in modal

5. **Result:**
   - Species status → "Confirmed"
   - SMILES assigned: [C]
   - Your username recorded
   - Species moves to "Confirmed" list
   - Can still be unblocked/reconfirmed if needed

---

### Step-by-Step: Blocking a Wrong Match

**Scenario:** Candidate suggests CH3 radical [CH3] for methane CH4 (clearly wrong).

1. **Navigate to species:**
   ```
   importer_dashboard → Jobs → Hansen → Species → CH4
   ```

2. **Find wrong candidate:**
   - Scroll to candidate #3
   - SMILES: [CH3] (methyl radical)
   - ΔH: 138 kJ/mol (way too high)
   - This is clearly wrong (radical vs. molecule)

3. **Block it:**
   - Click red "Block" button
   - Modal appears: "Why block this?"
   - Enter reason: "CH3 is radical, CH4 is saturated"
   - Click "Block" in modal

4. **Result:**
   - Candidate marked as blocked
   - Votes deleted for this match
   - Candidate removed from consideration
   - Other candidates still available

---

### Step-by-Step: Submitting Custom SMILES

**Scenario:** No good candidates for CF4 (carbon tetrafluoride).

1. **Navigate to species:**
   ```
   importer_dashboard → Jobs → Hansen → Species → CF4
   ```

2. **Review candidates:**
   - Candidate #1: CF3 [CF3] - Wrong (radical)
   - Candidate #2: CCl4 [CCl4] - Wrong (chlorine not fluorine)
   - No correct match available

3. **Look up correct SMILES:**
   - Google: "CF4 SMILES"
   - Or use RDKit: `Chem.MolToSmiles(Chem.MolFromSmiles('C(F)(F)(F)F'))`
   - Result: `FC(F)(F)F` or `C(F)(F)(F)F`

4. **Submit custom SMILES:**
   - Scroll to bottom of page
   - Enter: `C(F)(F)(F)F`
   - Click "Submit SMILES"

5. **New candidate created:**
   - Candidate #3: CF4 [C(F)(F)(F)F]
   - Marked as "Manual entry"
   - Now you can confirm it

6. **Confirm custom match:**
   - Click "Confirm" on new candidate
   - Species → Confirmed with your SMILES

---

## 🎨 UI Elements Guide

### Species Card (Queue View)
```
┌──────────────────────────────────────┐
│ CH4                           [85%]  │  ← Chemkin label + confidence
│ ─────────────────────────────────    │
│ Formula: CH4                         │  ← Molecular formula
│ Status: Tentative                    │  ← Current status badge
│ Candidates: 3                        │  ← Number of possible matches
│ Top: CH4 [C] (10 votes)              │  ← Best candidate preview
│ [View Details →]                     │  ← Click to detail page
└──────────────────────────────────────┘
```

### Candidate Card (Detail View)
```
┌──────────────────────────────────────────────────────┐
│ 🥇 Rank #1                       Confidence: 85%     │  ← Rank badge
│ ─────────────────────────────────────────────────    │
│ RMG Label: CH4                                       │
│ SMILES: [C]                                          │  ← Structure
│ ΔH(298K): 2.3 kJ/mol discrepancy                     │  ← Thermo check
│ Votes: 10 unique, 25 total                           │  ← Evidence
│ Thermo matches: 2 libraries                          │  ← Library support
│                                                      │
│ [✓ Confirm]  [✗ Block]  [👁 View Reactions]         │  ← Actions
└──────────────────────────────────────────────────────┘
```

### Status Badges
```
Unidentified  - ⚪ Gray badge - No candidates or votes
Tentative     - 🟡 Yellow badge - Has candidates, needs review
Confirmed     - 🟢 Green badge - User confirmed
```

### Confidence Colors
```
🟢 Green (>70%)  - High confidence, likely correct
🟡 Yellow (40-70%) - Medium confidence, review
🔴 Red (<40%)    - Low confidence, careful review
```

---

## 🔒 Access Control

### dashboard_new.py
- **No authentication** - Anyone with SSH access
- **SSH password required** - Explorer cluster
- **Single user** - One session at a time
- **No user tracking** - Anonymous actions

### importer_dashboard
- **Django authentication** - Username/password
- **Multi-user** - Multiple concurrent sessions
- **User tracking** - All actions recorded
- **Permissions** - Can add role-based access control

---

## 📊 Data Flow

### Vote Data Flow:
```
1. Cluster: RMG generates reactions
              ↓
2. Cluster: Reactions create votes → SQLite DB
              ↓
3. Cluster: votes_db8cff...db file grows
              ↓
4. dashboard_new.py: Shows aggregate counts (read-only)
              ↓
5. importer_dashboard: SSH query + incremental sync
              ↓
6. importer_dashboard: Django ORM → PostgreSQL
              ↓
7. importer_dashboard: UI displays individual species
              ↓
8. User: Makes confirmation decisions
              ↓
9. importer_dashboard: Records confirmation in DB
              ↓
10. Future: Export confirmed species to file
```

---

## 🎯 When to Use Which Dashboard

### Use dashboard_new.py when:
- ✅ Starting new import jobs
- ✅ Monitoring job progress
- ✅ Checking if jobs are running
- ✅ Viewing RMG logs
- ✅ Killing stuck jobs
- ✅ Debugging cluster issues
- ✅ Managing SLURM settings

### Use importer_dashboard when:
- ✅ Identifying individual species
- ✅ Reviewing voting evidence
- ✅ Confirming species matches
- ✅ Blocking incorrect candidates
- ✅ Submitting custom SMILES
- ✅ Tracking identification progress
- ✅ Generating reports

---

## 🚀 Future Enhancements

### dashboard_new.py could add:
- Integration with importer_dashboard
- Direct links to species pages
- Real-time progress updates
- Job scheduling

### importer_dashboard could add:
- Batch confirmation workflow
- Machine learning confidence scores
- Automated blocking rules
- Export to various formats
- Statistics dashboard
- User leaderboard
- Species search
- Reaction browser

---

## 📝 Summary

**dashboard_new.py = Job Control Panel**
- Manage cluster jobs
- Monitor progress
- View logs
- System operations

**importer_dashboard = Species Identification Interface**
- Review species candidates
- Make confirmation decisions
- Track voting evidence
- User-driven curation

**They complement each other:**
1. Use dashboard_new.py to **start jobs and monitor**
2. Use importer_dashboard to **identify species and confirm**
3. Together they form a complete workflow

**Your question about user decisions:**
- Users make decisions in **importer_dashboard**, not dashboard_new.py
- Three actions: Confirm ✓, Block ✗, Submit SMILES ✏️
- All actions tracked and auditable
- Full voting evidence visible
- Interactive, database-backed workflow

---

**Need help? Check USER_GUIDE_VOTING.md for detailed instructions!**
