# 🔧 Architecture Correction: The Real System

## ❌ What I Misunderstood

I incorrectly stated that `dashboard_new.py` only monitors jobs and has no identification interface.

## ✅ The Truth

**`dashboard_new.py` creates SSH tunnels to the RMG importer web server running ON THE CLUSTER**, which has the full species identification interface at `http://localhost:8126/`

---

## 🏗️ Actual Architecture

### System Components

```
┌──────────────────────────────────────────────────────────┐
│              CLUSTER (Explorer)                          │
│  ┌────────────────────────────────────────────────────┐ │
│  │  RMG Import Job (Running on compute node)          │ │
│  │  - Port: 8126                                      │ │
│  │  - Runs full web server (CherryPy or Flask)       │ │
│  │  - Has complete identification UI                 │ │
│  │  - URL: http://c-001:8126/                        │ │
│  │                                                    │ │
│  │  Pages available:                                 │ │
│  │  - /identified.html - Identified species list     │ │
│  │  - /propose.html?ck_label=C3H6 - Propose match    │ │
│  │  - /tentative.html - Tentative matches            │ │
│  │  - /unconfirmed.html - Unconfirmed species        │ │
│  │  - /voting_reactions.html - Voting evidence       │ │
│  │  - /autoconfirm.html - Auto-confirmation table    │ │
│  │  - /blocked.html - Blocked matches                │ │
│  │  - /thermo_matches.html - Thermo matches          │ │
│  │                                                    │ │
│  │  Generates:                                       │ │
│  │  - Species matching via reactions                 │ │
│  │  - Voting database (SQLite)                       │ │
│  │  - Real-time identification interface             │ │
│  └────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
                         │
                         │ SSH Tunnel (Paramiko)
                         │ Port Forwarding: 8126 → 8126
                         │
                         ↓
┌──────────────────────────────────────────────────────────┐
│              LOCAL MACHINE                               │
│                                                          │
│  ┌────────────────────────────────────────────────────┐ │
│  │  dashboard_new.py (Port 8000)                      │ │
│  │  - SSH tunnel manager                              │ │
│  │  - Opens tunnels to cluster jobs                  │ │
│  │  - Forwards localhost:8126 → cluster:8126         │ │
│  │  - Displays job list with "open" links            │ │
│  └────────────────────────────────────────────────────┘ │
│                                                          │
└──────────────────────────────────────────────────────────┘
                         │
                         │ Browser Access
                         │
                         ↓
┌──────────────────────────────────────────────────────────┐
│              USER BROWSER                                │
│                                                          │
│  Dashboard (http://localhost:8000/)                      │
│  ├─ Shows job list                                       │
│  ├─ Click "open" → http://localhost:8126/               │
│  └─ Opens CLUSTER web interface (via tunnel)            │
│                                                          │
│  Cluster Interface (http://localhost:8126/)              │
│  ├─ Identified species                                   │
│  ├─ Propose matches                                      │
│  ├─ Confirm/block buttons HERE                          │
│  └─ Full species identification UI                       │
└──────────────────────────────────────────────────────────┘
```

---

## 🔍 Where the Buttons Actually Are

### In dashboard_new.py (http://localhost:8000/)

**This is just the job monitor:**
```
Mechanism: CombFlame2013/2343-Hansen
Port: 8126
Status: Running
Progress: 25 identified, 347 unconfirmed

[open] ← Click this link
```

### In Cluster Interface (http://localhost:8126/)

**This is where the buttons are!**

When you click "open" in dashboard_new.py, you access the cluster's web interface via SSH tunnel.

**Pages you see:**
- http://localhost:8126/ - Main menu
- http://localhost:8126/identified.html - List of 25 identified species
- http://localhost:8126/propose.html?ck_label=C3H6 - Propose matches for C3H6
- http://localhost:8126/tentative.html - Species with candidates
- http://localhost:8126/unconfirmed.html - 347 unconfirmed species

---

## 📱 The Real User Interface (On Cluster)

### Main Menu (http://localhost:8126/)
```
╔════════════════════════════════════════════════════════╗
║  Mechanism importer: CombFlame2013/2343-Hansen         ║
╠════════════════════════════════════════════════════════╣
║                                                        ║
║  [All species]              (Sorted by name/formula)   ║
║  [Identified species]       (25)                       ║
║  [Tentative Matches]        (0)                        ║
║  [Voting reactions list]                               ║
║  [Voting reactions table]                              ║
║  [Autoconfirm table]                                   ║
║  [Unmatched reactions]      (8213)                     ║
║  [Unconfirmed species]      (347)                      ║
║  [Blocked matches]                                     ║
║  [Unconfirmed thermo]       (124)                      ║
║                                                        ║
║  Your name: Anonymous                                  ║
╚════════════════════════════════════════════════════════╝
```

### Identified Species Page (http://localhost:8126/identified.html)
```
╔════════════════════════════════════════════════════════╗
║  25 Identified Species                                 ║
╠════════════════════════════════════════════════════════╣
║                                                        ║
║  #  Label    Molecule      Identified by    Delete?   ║
║  1  CH2      CH2(143)       -                [X]      ║
║  2  CH2(S)   CH2(S)(144)    -                [X]      ║
║  3  H2       H2(145)        -                [X]      ║
║  4  CO2      CO2(146)       -                [X]      ║
║  ...                                                   ║
╚════════════════════════════════════════════════════════╝
```

### Propose Match Page (http://localhost:8126/propose.html?ck_label=C3H6)
```
╔════════════════════════════════════════════════════════╗
║  Propose C3H6                                          ║
╠════════════════════════════════════════════════════════╣
║                                                        ║
║  Chemkin Species: C3H6                                 ║
║                                                        ║
║  Candidates:                                           ║
║                                                        ║
║  🥇 RMG Species #1: C3H6 (propene)                    ║
║     SMILES: CC=C                                       ║
║     Votes: 25                                          ║
║     Enthalpy: ΔH = 2.3 kJ/mol                         ║
║     [✓ Confirm]  [✗ Block]                            ║
║                                                        ║
║  🥈 RMG Species #2: C3H6 (cyclopropane)               ║
║     SMILES: C1CC1                                      ║
║     Votes: 3                                           ║
║     Enthalpy: ΔH = 45.2 kJ/mol                        ║
║     [✓ Confirm]  [✗ Block]                            ║
║                                                        ║
║  ──────────────────────────────────────────────────   ║
║                                                        ║
║  Submit custom SMILES:                                 ║
║  [_____________________]  [Submit]                     ║
║                                                        ║
╚════════════════════════════════════════════════════════╝
```

---

## 🎯 So Where Are The Buttons?

### ❌ NOT in dashboard_new.py Interface

`http://localhost:8000/` only shows:
- Job list
- Start/stop/kill buttons
- "Open" link to tunnel to cluster

### ✅ YES in Cluster Web Interface

`http://localhost:8126/` (accessed via tunnel) has:
- **Confirm buttons** ✅
- **Block buttons** ❌
- **Submit SMILES form** ✏️
- Full voting evidence
- Candidate lists
- All species management

---

## 🔄 Complete User Workflow

### Step 1: Start dashboard_new.py
```bash
cd /Users/lekiaprosper/Documents/CoMoChEng/Prometheus/RMG-importer
python dashboard_new.py
# Opens SSH tunnels to cluster
```

### Step 2: Open Job Monitor
```
Browser → http://localhost:8000/
```

You see:
```
Mechanism: CombFlame2013/2343-Hansen
Port: 8126
Status: Running on c-001
Tunnel: [open] ← CLICK THIS
Progress: 25 identified, 347 unconfirmed
```

### Step 3: Click "Open" Link
```
Clicks → http://localhost:8126/
```

This opens the **cluster's web interface** via SSH tunnel.

### Step 4: Navigate to Species
```
http://localhost:8126/
  ↓
Click "Unconfirmed species (347)"
  ↓
http://localhost:8126/unconfirmed.html
```

### Step 5: Propose Match
```
Click on species "C3H6"
  ↓
http://localhost:8126/propose.html?ck_label=C3H6
```

**NOW you see the buttons:**
- Candidate list with votes
- [✓ Confirm] button (green)
- [✗ Block] button (red)
- Submit SMILES form (bottom)

### Step 6: Make Decision
```
Review candidates → Click [✓ Confirm]
  ↓
Species marked as identified
  ↓
Appears in "Identified species (26)" list
```

---

## 🔍 Why This Was Confusing

### What I Said:
```
❌ "dashboard_new.py only monitors jobs"
❌ "No species identification interface"
❌ "Use importer_dashboard instead"
```

### What's Actually True:
```
✅ dashboard_new.py creates SSH tunnels
✅ Tunnels connect to cluster web interface
✅ Cluster interface has FULL identification UI
✅ Buttons are at http://localhost:8126/ (via tunnel)
✅ importer_dashboard is a SEPARATE Django replacement
```

---

## 🏗️ Two Parallel Systems

### System 1: Cluster Web Interface (Original)

**Access:**
```bash
python dashboard_new.py
→ http://localhost:8000/ (job monitor)
→ Click "open"
→ http://localhost:8126/ (cluster web UI via tunnel)
```

**Features:**
- Real-time connection to running RMG job
- Immediate species identification
- Voting reactions visible
- Confirm/block/submit buttons
- Direct database updates on cluster

**Limitations:**
- Only works while job is running
- Requires SSH tunnel
- Single user at a time
- No persistent history after job ends

---

### System 2: Django Dashboard (New)

**Access:**
```bash
cd kineticmodelssite
python manage.py runserver
→ http://localhost:8000/importer/
```

**Features:**
- Persistent database (PostgreSQL)
- Multi-user support
- Works after job completes
- Historical tracking
- Incremental sync from cluster
- Audit trail

**Limitations:**
- Requires manual sync
- Not real-time
- Additional setup needed

---

## 📊 Feature Comparison

| Feature | Cluster Web UI | Django Dashboard |
|---------|---------------|------------------|
| **Access** | Via SSH tunnel | Direct web server |
| **URL** | localhost:8126 | localhost:8000/importer |
| **Real-time** | ✅ Yes | ❌ No (sync needed) |
| **Persistent** | ❌ Job only | ✅ Database |
| **Multi-user** | ❌ One tunnel | ✅ Multiple users |
| **Confirm button** | ✅ Yes | ✅ Yes |
| **Block button** | ✅ Yes | ✅ Yes |
| **Submit SMILES** | ✅ Yes | ✅ Yes |
| **Voting evidence** | ✅ Full detail | ✅ Synced data |
| **History** | ❌ Lost after job | ✅ Permanent |
| **Setup** | dashboard_new.py | Django + migration |

---

## 🎯 Corrected Answer to Your Question

### Question: "Where are the confirm/block/submit buttons?"

**Answer:**

**In the cluster web interface at `http://localhost:8126/`**, accessed via SSH tunnel created by `dashboard_new.py`.

**Step-by-step:**

1. **Run dashboard_new.py:**
   ```bash
   python dashboard_new.py
   ```

2. **Open job monitor:**
   ```
   http://localhost:8000/
   ```

3. **Click "open" link** next to running job

4. **Cluster interface opens:**
   ```
   http://localhost:8126/
   ```

5. **Navigate to species:**
   - Click "Unconfirmed species (347)"
   - Or click "All species"
   - Click on a species name (e.g., "C3H6")

6. **Propose page loads:**
   ```
   http://localhost:8126/propose.html?ck_label=C3H6
   ```

7. **Buttons are HERE:**
   - [✓ Confirm] - Green button on each candidate
   - [✗ Block] - Red button on each candidate
   - Submit SMILES form - At bottom of page

---

## 💡 Key Insight

**`dashboard_new.py` is a TUNNEL MANAGER that connects you to the cluster's web interface.**

The actual identification interface runs **ON THE CLUSTER** (port 8126), and dashboard_new.py forwards that port to your local machine so you can access it via `http://localhost:8126/`.

**The buttons you're looking for are in the cluster web interface, NOT in dashboard_new.py itself.**

---

## 🔧 Why importer_dashboard Exists

Since the cluster web interface:
- Only works while job is running
- Requires SSH tunnel
- Data lost after job ends
- No multi-user support

The **importer_dashboard** was created to:
- Store data permanently
- Work after jobs complete
- Support multiple users
- Provide historical tracking
- Enable better collaboration

**But the original cluster interface still works and has all the buttons you need!**

---

## 📝 Summary

### Your Confusion:
```
"I can't find the buttons in the species_queue page"
```

### The Reality:
```
✅ Buttons ARE in dashboard_new.py's linked interface
✅ Located at http://localhost:8126/ (via tunnel)
✅ Click "open" link in job monitor to access them
✅ Full UI with confirm/block/submit available
✅ This is the ORIGINAL RMG importer interface
```

### The Correction:
```
❌ I was wrong: dashboard_new.py DOES have identification UI
✅ But it's accessed via SSH tunnel to cluster
✅ Cluster runs full web server on port 8126
✅ dashboard_new.py at port 8000 just links to it
✅ All buttons are at localhost:8126 (tunneled)
```

---

**Apologies for the confusion! The buttons are definitely there - just follow the "open" link in the dashboard_new.py interface to access them.**
