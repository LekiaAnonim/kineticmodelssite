# 🚀 How to Use importer_dashboard for Species Identification

## Step-by-Step Guide

### 1️⃣ Start the Django Server

```bash
cd /Users/lekiaprosper/Documents/CoMoChEng/Prometheus/kineticmodelssite
conda activate kms
python manage.py runserver
```

You should see:
```
Starting development server at http://127.0.0.1:8000/
Quit the server with CONTROL-C.
```

---

### 2️⃣ Open the Dashboard

Open your browser and go to:
```
http://localhost:8000/importer/
```

You'll see the main dashboard with a list of jobs.

---

### 3️⃣ Navigate to Your Job

Find your job "CombFlame2013/2343-Hansen" in the job list and click on it, OR go directly to:

```
http://localhost:8000/importer/job/{job_id}/species-queue/
```

To find your job_id, you can run:
```bash
conda activate kms
python manage.py shell
```

Then:
```python
from importer_dashboard.models import ClusterJob
job = ClusterJob.objects.filter(name__contains="Hansen").first()
print(f"Job ID: {job.id}")
print(f"Job Name: {job.name}")
```

**Or**, if the job is already in the system, just click it from the dashboard.

---

### 4️⃣ Species Queue Page

You should now see the **Species Queue** page with tabs:

```
╔════════════════════════════════════════════════════════╗
║  Species Queue - CombFlame2013/2343-Hansen             ║
╠════════════════════════════════════════════════════════╣
║                                                        ║
║  [All] [Unidentified] [Tentative] [Confirmed]        ║
║  [🔄 Sync Votes]                                       ║
║                                                        ║
║  ┌──────────────────────────────────────────────┐     ║
║  │ CH4 (Methane)                         [85%]  │     ║
║  │ Status: Tentative  •  3 candidates          │     ║
║  │ Top: CH4 [C] (10 votes)                     │     ║
║  │ [View Details →]                            │     ║
║  └──────────────────────────────────────────────┘     ║
║                                                        ║
║  ┌──────────────────────────────────────────────┐     ║
║  │ C3H6 (Propene)                        [65%]  │     ║
║  │ Status: Unidentified  •  2 candidates        │     ║
║  │ Top: C3H6 [CC=C] (5 votes)                  │     ║
║  │ [View Details →]                            │     ║
║  └──────────────────────────────────────────────┘     ║
║                                                        ║
╚════════════════════════════════════════════════════════╝
```

**URL:** `http://localhost:8000/importer/job/{job_id}/species-queue/`

---

### 5️⃣ Click on a Species

Click **"View Details →"** on any species card (or click the species name).

This takes you to the **Species Detail Page**.

**URL:** `http://localhost:8000/importer/job/{job_id}/species/{species_id}/`

---

### 6️⃣ Species Detail Page - WHERE THE BUTTONS ARE! 🎯

This is where you'll see the three user actions:

```
╔════════════════════════════════════════════════════════════╗
║  Species: C3H6                                             ║
║  Formula: C3H6  |  Status: Tentative                      ║
║  ← Back to Queue                                           ║
╠════════════════════════════════════════════════════════════╣
║                                                            ║
║  ═══════════════════════════════════════════════════════  ║
║  🥇 CANDIDATE #1                      Confidence: 85%     ║
║  ═══════════════════════════════════════════════════════  ║
║                                                            ║
║  RMG Label: C3H6 (propene)                                 ║
║  SMILES: CC=C                                              ║
║  Enthalpy Discrepancy: 2.3 kJ/mol                          ║
║  Votes: 10 unique reactions, 25 total votes                ║
║  Thermo Matches: GRI-Mech 3.0                              ║
║                                                            ║
║  Voting Evidence:                                          ║
║    • C3H6 + OH → C3H5 + H2O     (5 votes)                 ║
║    • C3H6 + H → C3H7            (3 votes)                 ║
║    • C3H6 + O → Products        (2 votes)                 ║
║                                                            ║
║  ┌─────────────────────────────────────────────────────┐  ║
║  │ [✅ Confirm This Match] ← BUTTON 1                  │  ║
║  │ [❌ Block This Match]   ← BUTTON 2                  │  ║
║  │ [👁 View All Reactions]                             │  ║
║  └─────────────────────────────────────────────────────┘  ║
║                                                            ║
║  ═══════════════════════════════════════════════════════  ║
║  🥈 CANDIDATE #2                      Confidence: 10%     ║
║  ═══════════════════════════════════════════════════════  ║
║                                                            ║
║  RMG Label: C3H6 (cyclopropane)                            ║
║  SMILES: C1CC1                                             ║
║  Enthalpy Discrepancy: 45.2 kJ/mol                         ║
║  Votes: 2 unique reactions, 3 total votes                  ║
║                                                            ║
║  ┌─────────────────────────────────────────────────────┐  ║
║  │ [✅ Confirm This Match]                             │  ║
║  │ [❌ Block This Match]                               │  ║
║  └─────────────────────────────────────────────────────┘  ║
║                                                            ║
║  ─────────────────────────────────────────────────────    ║
║                                                            ║
║  No good match? Submit your own SMILES:                    ║
║                                                            ║
║  SMILES: [________________________] ← INPUT BOX           ║
║          [Submit Custom SMILES]    ← BUTTON 3             ║
║                                                            ║
╚════════════════════════════════════════════════════════════╝
```

---

## 🎮 The Three Actions

### ✅ Action 1: Confirm a Match

**When:** The candidate is correct

**How:**
1. Review the candidate details
2. Check SMILES, enthalpy, votes
3. Click the green **"Confirm This Match"** button
4. Modal appears asking "Are you sure?"
5. Click "Confirm" in the modal
6. ✅ Done! Species is now confirmed

**What happens:**
- Species status → "confirmed"
- SMILES assigned to species
- Your username recorded
- Species appears in "Confirmed" tab

---

### ❌ Action 2: Block a Match

**When:** The candidate is incorrect

**How:**
1. Find the wrong candidate
2. Click the red **"Block This Match"** button
3. Modal appears asking "Why block?"
4. Enter reason (optional but recommended)
5. Click "Block" in modal
6. ❌ Done! Candidate is blocked

**What happens:**
- Candidate marked as blocked
- Votes deleted
- Candidate hidden from view
- BlockedMatch record created

---

### ✏️ Action 3: Submit Custom SMILES

**When:** No good candidates, but you know the correct SMILES

**How:**
1. Scroll to bottom of species detail page
2. Find "No good match? Submit your own SMILES:"
3. Enter SMILES in text box (e.g., `CC=C`)
4. Click **"Submit Custom SMILES"** button
5. New candidate appears
6. Then confirm it using Action 1

**What happens:**
- New CandidateSpecies created
- Marked as manual entry
- Your username recorded
- Candidate appears in list (can then be confirmed)

---

## 📍 Quick URLs Reference

Assuming your job_id is `1` and species_id is `42`:

```
Main Dashboard:
http://localhost:8000/importer/

Job List:
http://localhost:8000/importer/

Species Queue (List):
http://localhost:8000/importer/job/1/species-queue/

Species Detail (Buttons HERE):
http://localhost:8000/importer/job/1/species/42/

Confirm Endpoint (POST):
http://localhost:8000/importer/job/1/species/42/confirm/

Block Endpoint (POST):
http://localhost:8000/importer/job/1/species/42/block/

Submit SMILES Endpoint (POST):
http://localhost:8000/importer/job/1/species/42/submit-smiles/
```

---

## 🔍 How to Find Your Job and Species IDs

### Option 1: From the Browser URL

When you click on your job, the URL will show:
```
http://localhost:8000/importer/job/1/species-queue/
                                      ↑
                                   job_id
```

When you click on a species, the URL will show:
```
http://localhost:8000/importer/job/1/species/42/
                                      ↑        ↑
                                   job_id  species_id
```

### Option 2: From Django Shell

```bash
conda activate kms
python manage.py shell
```

```python
from importer_dashboard.models import ClusterJob, Species

# Find your job
job = ClusterJob.objects.filter(name__contains="Hansen").first()
print(f"Job ID: {job.id}")

# Find species in that job
species_list = Species.objects.filter(job=job)
for sp in species_list[:5]:
    print(f"Species {sp.id}: {sp.chemkin_label} - {sp.identification_status}")
```

---

## 🚦 Complete Workflow Example

### Step 1: Start Server
```bash
cd /Users/lekiaprosper/Documents/CoMoChEng/Prometheus/kineticmodelssite
conda activate kms
python manage.py runserver
```

### Step 2: Create/Get Job (if needed)
```bash
python manage.py shell
```

```python
from importer_dashboard.models import ClusterJob

# Create job if doesn't exist
job, created = ClusterJob.objects.get_or_create(
    name="CombFlame2013/2343-Hansen",
    defaults={
        'port': 8126,
        'status': 'completed',
        'cluster_path': '/projects/westgroup/lekia.p/Importer/RMG-models/CombFlame2013/2343-Hansen/'
    }
)
print(f"Job ID: {job.id}")
```

### Step 3: Sync Data
```python
from importer_dashboard.incremental_sync import sync_job_votes_incremental

result = sync_job_votes_incremental(job)
print(f"Sync successful: {result['success']}")
print(f"Species synced: {result.get('votes_synced', 0)}")
```

### Step 4: Open Browser
```
http://localhost:8000/importer/job/{job.id}/species-queue/
```

### Step 5: Click Species
Click any species card → Detail page opens

### Step 6: Make Decision
- Review candidates
- Click Confirm/Block/Submit SMILES
- Done!

---

## 🎯 What If I Don't See Any Species?

### Check 1: Is the job in the database?

```python
from importer_dashboard.models import ClusterJob
jobs = ClusterJob.objects.all()
for job in jobs:
    print(f"{job.id}: {job.name}")
```

### Check 2: Has vote data been synced?

```python
from importer_dashboard.models import Species
from importer_dashboard.incremental_sync import sync_job_votes_incremental

job = ClusterJob.objects.get(id=1)  # Use your job_id
result = sync_job_votes_incremental(job)
print(result)

# Check species count
species_count = Species.objects.filter(job=job).count()
print(f"Species in database: {species_count}")
```

### Check 3: Click "Sync Votes" Button

On the species queue page, click the **🔄 Sync Votes** button at the top to manually trigger a sync.

---

## 📊 Current System Status

Based on your sync results, you should have:

```
✅ 25 confirmed species
✅ 25 candidates
✅ 100% with enthalpy data
✅ All sync working correctly
```

So when you open:
```
http://localhost:8000/importer/job/1/species-queue/
```

You should see **25 species** in the "Confirmed" tab.

Click on any species (e.g., CH4, CO2, H2O) to see the detail page with buttons.

---

## 🔧 Troubleshooting

### "Page not found" Error

Make sure the URL format is correct:
```
✅ http://localhost:8000/importer/job/1/species-queue/
❌ http://localhost:8000/importer/species-queue/  (missing job_id)
```

### "No species found"

1. Click **"Sync Votes"** button
2. Or run sync manually in shell:
```python
from importer_dashboard.models import ClusterJob
from importer_dashboard.incremental_sync import sync_job_votes_incremental

job = ClusterJob.objects.first()
sync_job_votes_incremental(job)
```

### Buttons not working

Check browser console (F12) for JavaScript errors. The buttons use AJAX.

### Can't find job

Create the job manually:
```python
from importer_dashboard.models import ClusterJob

job = ClusterJob.objects.create(
    name="CombFlame2013/2343-Hansen",
    port=8126,
    status='completed',
    cluster_path='/projects/westgroup/lekia.p/Importer/RMG-models/CombFlame2013/2343-Hansen/'
)
```

---

## 📚 Summary

### Where are the buttons?

**Location:** Species Detail Page

**URL:** `http://localhost:8000/importer/job/{job_id}/species/{species_id}/`

**How to get there:**
1. Start Django server: `python manage.py runserver`
2. Open browser: `http://localhost:8000/importer/`
3. Click your job
4. Click "species-queue" or species link
5. Click any species card
6. **Buttons are on this page!**

### The three buttons:

1. ✅ **Green "Confirm" button** - Accept match
2. ❌ **Red "Block" button** - Reject match
3. ✏️ **"Submit SMILES" form** - Enter custom SMILES

All three are on the **species detail page**, one set of buttons per candidate, plus the SMILES form at the bottom.

---

**Need more help? Check the other documentation files or let me know what specific issue you're encountering!**
