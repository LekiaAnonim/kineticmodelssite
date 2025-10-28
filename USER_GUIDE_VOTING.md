# 📖 User Guide: Voting and Species Identification

## Overview

The RMG Import Dashboard allows you to **identify species** from CHEMKIN mechanisms by matching them to RMG species. The system provides:
- **Automatic voting** based on reaction matching (from cluster)
- **Manual confirmation** by users
- **Manual SMILES input** for unidentified species
- **Block incorrect matches**

---

## 🎯 Current System State

Based on your example:
```
Species: CH2
Status: Confirmed
Candidates: 1
Top Match: CH2 [CH2]
Confidence: 30%
Votes: 0 unique, 0 total
```

**This species is already "Confirmed"** but has:
- ✅ **Already identified** (status = confirmed)
- ⚠️ **Low confidence** (30% - only 1 candidate, no votes)
- ⚠️ **No voting evidence** (0 votes)

---

## 📊 How Voting Works

### Automatic Voting (From Cluster)

Votes are **automatically generated** during the RMG import process on the cluster, NOT manually by users. Here's how:

1. **RMG runs on cluster** and generates reactions
2. **Reactions are analyzed** to find species matches
3. **Each reaction "votes"** for species matches
4. **Votes are stored** in the cluster SQLite database (`votes_db8cff...db`)
5. **Dashboard syncs** vote data via SSH

### Vote Data Structure:
```
Reaction: CH4 + OH -> CH3 + H2O
         ↓
Votes for: CH4 ↔ RMG Species #148
           OH  ↔ RMG Species #159
           CH3 ↔ RMG Species #164
           H2O ↔ RMG Species #154
```

Each reaction that uses a species is a "vote" for that species-RMG match.

---

## 👤 How Users Interact (3 Actions)

### 1. ✅ Confirm a Match

**When to use:** The top candidate looks correct and you want to confirm it.

**Steps:**
1. Click on species in queue
2. Review the candidate(s)
3. Click **"Confirm"** button on the desired candidate
4. Confirm in modal dialog
5. Species marked as "Confirmed"

**What happens:**
- Species status → `confirmed`
- SMILES assigned to species
- User recorded as identifier
- Species moves to "Confirmed" list

**URL endpoint:** `POST /importer/job/{job_id}/species/{species_id}/confirm/`

**Code location:** `species_views.py:confirm_match()`

---

### 2. ❌ Block a Match

**When to use:** A candidate is incorrect and should not be considered.

**Steps:**
1. Click on species in queue
2. Find the incorrect candidate
3. Click **"Block"** button
4. Optionally provide reason
5. Candidate is blocked

**What happens:**
- Candidate marked as `is_blocked = True`
- Votes for this candidate are deleted
- Candidate removed from consideration
- User recorded as blocker

**URL endpoint:** `POST /importer/job/{job_id}/species/{species_id}/block/`

**Code location:** `species_views.py:block_match()`

---

### 3. ✏️ Submit Custom SMILES

**When to use:** No good candidates exist, you know the correct SMILES.

**Steps:**
1. Click on species in queue
2. Scroll to bottom
3. Enter SMILES string in text box
4. Click **"Submit SMILES"**
5. New candidate created

**What happens:**
- New `CandidateSpecies` created with your SMILES
- Marked as manual entry
- Can then be confirmed

**URL endpoint:** `POST /importer/job/{job_id}/species/{species_id}/submit-smiles/`

**Code location:** `species_views.py:submit_smiles()`

---

## 🔍 Why Your CH2 Has No Votes

Looking at your example:
```
CH2 - Confirmed
SMILES: [CH2]
ΔH: 0.88 kcal/mol
Votes: 0 unique, 0 total
```

**Possible reasons:**

### 1. Pre-Identified Species
This species was identified **before voting**, likely by:
- **Formula matching** - CH2 label → CH2 formula → [CH2] SMILES
- **Thermo library matching** - Found in RMG thermo libraries
- **Manual identification** - Someone already confirmed it
- **Name-based matching** - CHEMKIN label exactly matched RMG label

### 2. Votes Not Synced Yet
- Vote data exists on cluster but hasn't synced
- Check: Click "Sync Votes" button to pull latest data

### 3. No Reactions Use This Species
- If no reactions in the mechanism use CH2, there are no voting reactions
- This is normal for some species

---

## 📱 User Interface Walkthrough

### Species Queue Page
```
http://localhost:8000/job/{job_id}/species/
```

Shows all species with filters:
- **Unidentified** - Need identification
- **Tentative** - Have candidates but not confirmed
- **Confirmed** - Already identified
- **All** - Everything

Each species card shows:
- Chemkin label
- Formula
- Status badge
- Vote counts
- Confidence score
- Top candidate preview

**Actions available:**
- Click species → Go to detail page
- Filter by status
- Sort by controversy/confidence
- Sync votes (button at top)

---

### Species Detail Page
```
http://localhost:8000/job/{job_id}/species/{species_id}/
```

**Shows:**
- Species information (label, formula, status)
- All candidate matches (ranked by votes/confidence)
- For each candidate:
  - SMILES string
  - Enthalpy discrepancy
  - Vote counts (unique vs total)
  - Confidence score
  - Voting reactions (evidence)
  - Thermo library matches

**Actions available per candidate:**
- **"Confirm"** button - Accept this match
- **"Block"** button - Reject this match
- **"View Reactions"** - See voting evidence

**Bottom of page:**
- **"Submit Custom SMILES"** form
- Manual SMILES entry
- For when no good candidates exist

---

## 🎨 Confidence Scores

Confidence is calculated based on:
- **Vote count** - More votes = higher confidence
- **Unique votes** - Non-overlapping reactions are better
- **Thermo matches** - Library matches increase confidence
- **Enthalpy discrepancy** - Lower difference = higher confidence
- **Number of candidates** - Fewer alternatives = higher confidence

**Color coding:**
- 🟢 **Green (>70%)** - High confidence, likely correct
- 🟡 **Yellow (40-70%)** - Medium confidence, review recommended
- 🔴 **Red (<40%)** - Low confidence, needs careful review

Your 30% confidence is low because:
- Only 1 candidate (good - no competition)
- 0 votes (bad - no evidence)
- Result: Low confidence, but might still be correct

---

## 💡 Best Practices

### For Users:

1. **Start with high-confidence species**
   - Sort by confidence
   - Confirm obvious matches first
   - Builds progress quickly

2. **Review voting evidence**
   - Click "View Reactions" to see why votes exist
   - Check if reactions make chemical sense
   - Look for consensus across reaction families

3. **Check enthalpy discrepancy**
   - < 5 kJ/mol - Very likely correct
   - 5-20 kJ/mol - Probably correct, review
   - > 20 kJ/mol - Suspicious, investigate

4. **When in doubt, don't confirm**
   - Mark as tentative
   - Ask domain expert
   - Better to leave unidentified than wrong

5. **Use block judiciously**
   - Only block clearly wrong matches
   - Provide reasons when blocking
   - Helps train the system

---

## 🔧 Technical Details

### Backend Models

**Species**
- Represents CHEMKIN species
- Fields: chemkin_label, formula, smiles, status
- Status: unidentified → tentative → confirmed

**CandidateSpecies**
- Potential RMG matches for a species
- Fields: smiles, rmg_label, vote_count, confidence
- Ranked by votes and confidence

**Vote**
- Individual reaction votes
- Links species → candidate via reaction
- Tracks which reactions support which matches

### Sync Process

1. Cluster generates reactions
2. Reactions create votes in SQLite
3. Dashboard queries SQLite via SSH
4. Votes synced to Django models
5. UI displays updated data

---

## 🎯 Your Specific Case: CH2

For your CH2 species with 0 votes:

**It's already confirmed, so you don't need to do anything!**

But if you wanted to review it:

1. **Check if correct:**
   - CH2 is a carbene radical
   - SMILES [CH2] represents this
   - Enthalpy 0.88 kcal/mol seems reasonable

2. **Why no votes:**
   - Likely pre-identified by formula matching
   - Or from thermo library
   - Or manually confirmed earlier

3. **What you can do:**
   - Leave it as is (it's correct)
   - Check reactions tab to see if it's used
   - If unsure, you could "unconfirm" and block the match, then submit correct SMILES

4. **To unconfirm (if needed):**
   - Currently no UI for this
   - Would need to use Django admin or shell
   - Generally not recommended

---

## 📝 Summary

### Voting System:
- ✅ **Automatic** - Generated by RMG on cluster
- ✅ **Synced** - Downloaded to dashboard via SSH
- ❌ **Not manual** - Users don't cast votes directly

### User Actions:
1. ✅ **Confirm** - Accept a candidate match
2. ❌ **Block** - Reject a candidate match
3. ✏️ **Submit SMILES** - Provide custom match

### Your CH2 Case:
- **Status:** Already confirmed ✅
- **Action needed:** None (unless you want to review)
- **Votes:** 0 is OK for pre-identified species

---

**Questions? Check the documentation or ask the system administrator!**
