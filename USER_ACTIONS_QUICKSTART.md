# ⚡ Quick Start: User Actions for Species Identification

## 🎯 The Three User Actions

```
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│  User sees species with candidates                          │
│                    ↓                                         │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Action 1: ✅ CONFIRM                                 │  │
│  │  "This candidate is correct"                          │  │
│  │  → Species becomes confirmed                          │  │
│  │  → SMILES assigned                                    │  │
│  └──────────────────────────────────────────────────────┘  │
│                    ↓                                         │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Action 2: ❌ BLOCK                                   │  │
│  │  "This candidate is wrong"                            │  │
│  │  → Candidate removed                                  │  │
│  │  → Votes deleted                                      │  │
│  └──────────────────────────────────────────────────────┘  │
│                    ↓                                         │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Action 3: ✏️ SUBMIT SMILES                           │  │
│  │  "None of these are right, here's the correct one"   │  │
│  │  → New candidate created                              │  │
│  │  → Can then be confirmed                              │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## 🚀 Getting Started (30 seconds)

### 1. Open the Dashboard
```bash
cd /Users/lekiaprosper/Documents/CoMoChEng/Prometheus/kineticmodelssite
conda activate kms
python manage.py runserver
```

### 2. Navigate to Job
```
Browser → http://localhost:8000/importer/
         → Click job name (e.g., "CombFlame2013/2343-Hansen")
         → Species queue appears
```

### 3. Start Identifying
```
Click "Unidentified" tab → Click a species → Make decision
```

---

## 📱 The User Interface

### Species Queue (List View)
```
╔════════════════════════════════════════════════════════════╗
║                    Species Queue                           ║
║  [All] [Unidentified] [Tentative] [Confirmed]            ║
║  [🔄 Sync Votes]    Search: [________]  Sort: [Confidence]║
╠════════════════════════════════════════════════════════════╣
║                                                            ║
║  ┌────────────────────────────────────────────────┐       ║
║  │ CH4 (Methane)                           [85%] │       ║
║  │ Status: Tentative  •  3 candidates            │       ║
║  │ Top: CH4 [C] (10 votes)                       │       ║
║  │ [View Details →]                              │       ║
║  └────────────────────────────────────────────────┘       ║
║                                                            ║
║  ┌────────────────────────────────────────────────┐       ║
║  │ OH (Hydroxyl)                           [92%] │       ║
║  │ Status: Tentative  •  2 candidates            │       ║
║  │ Top: OH [OH] (15 votes)                       │       ║
║  │ [View Details →]                              │       ║
║  └────────────────────────────────────────────────┘       ║
║                                                            ║
║  ┌────────────────────────────────────────────────┐       ║
║  │ CF4 (Tetrafluoromethane)                [12%] │       ║
║  │ Status: Unidentified  •  0 candidates         │       ║
║  │ No candidates found                           │       ║
║  │ [View Details →]                              │       ║
║  └────────────────────────────────────────────────┘       ║
║                                                            ║
╚════════════════════════════════════════════════════════════╝
```

---

### Species Detail (When You Click a Species)
```
╔════════════════════════════════════════════════════════════╗
║                    Species: CH4                            ║
║  Formula: CH4  |  Status: Tentative                       ║
║  ← Back to Queue                                           ║
╠════════════════════════════════════════════════════════════╣
║                                                            ║
║  ═══════════════════════════════════════════════════════  ║
║  🥇 CANDIDATE #1                      Confidence: 85%     ║
║  ═══════════════════════════════════════════════════════  ║
║                                                            ║
║  RMG Label: CH4                                            ║
║  SMILES: [C]                                               ║
║  Enthalpy Discrepancy: 2.3 kJ/mol                          ║
║  Votes: 10 unique reactions, 25 total votes                ║
║  Thermo Matches: GRI-Mech 3.0, USC-Mech II                 ║
║                                                            ║
║  Voting Evidence:                                          ║
║    • CH4 + OH → CH3 + H2O     (5 votes)                   ║
║    • CH4 + O → CH3 + OH       (3 votes)                   ║
║    • CH4 + H → CH3 + H2       (2 votes)                   ║
║                                                            ║
║  ┌────────────────────────────────────────────────────┐   ║
║  │ [✅ Confirm This Match]                            │   ║
║  │ [❌ Block This Match]                              │   ║
║  │ [👁 View All Reactions]                            │   ║
║  └────────────────────────────────────────────────────┘   ║
║                                                            ║
║  ═══════════════════════════════════════════════════════  ║
║  🥈 CANDIDATE #2                      Confidence: 10%     ║
║  ═══════════════════════════════════════════════════════  ║
║                                                            ║
║  RMG Label: methane                                        ║
║  SMILES: [C]                                               ║
║  Enthalpy Discrepancy: 15.7 kJ/mol                         ║
║  Votes: 2 unique reactions, 3 total votes                  ║
║                                                            ║
║  ┌────────────────────────────────────────────────────┐   ║
║  │ [✅ Confirm This Match]                            │   ║
║  │ [❌ Block This Match]                              │   ║
║  └────────────────────────────────────────────────────┘   ║
║                                                            ║
║  ─────────────────────────────────────────────────────    ║
║                                                            ║
║  No good match? Submit your own SMILES:                    ║
║                                                            ║
║  SMILES: [________________________]                        ║
║          [Submit Custom SMILES]                            ║
║                                                            ║
╚════════════════════════════════════════════════════════════╝
```

---

## ✅ Action 1: Confirm a Match

### When to Use:
- ✅ SMILES looks correct
- ✅ Enthalpy discrepancy is small (< 5 kJ/mol ideal)
- ✅ High vote count
- ✅ High confidence score
- ✅ Voting reactions make chemical sense

### How to Do It:
```
1. Click species card → Detail page opens
2. Review top candidate
3. Check SMILES structure
4. Verify enthalpy is close
5. Click green "Confirm" button
6. Modal appears: "Are you sure you want to confirm CH4 → [C]?"
7. Click "Confirm" in modal
8. ✅ Done! Species is now confirmed
```

### What Happens:
```
Before:
  Species: CH4
  Status: Tentative
  SMILES: None

After:
  Species: CH4
  Status: Confirmed ✅
  SMILES: [C]
  Confirmed by: lekia.p
  Confirmed at: 2025-10-27 14:30:22
```

### Backend Code:
```python
# File: species_views.py, function: confirm_match()
# Line: ~314-375

@require_http_methods(["POST"])
def confirm_match(request, job_id, species_id):
    species = get_object_or_404(Species, id=species_id, job_id=job_id)
    candidate_id = request.POST.get('candidate_id')
    candidate = get_object_or_404(CandidateSpecies, id=candidate_id)
    
    with transaction.atomic():
        # Update species
        species.smiles = candidate.smiles
        species.identification_status = 'confirmed'
        species.confirmed_by = request.user
        species.confirmed_at = timezone.now()
        species.save()
        
        # Mark candidate as confirmed
        candidate.is_confirmed = True
        candidate.save()
    
    return JsonResponse({'success': True})
```

---

## ❌ Action 2: Block a Match

### When to Use:
- ❌ SMILES is clearly wrong
- ❌ Enthalpy discrepancy is huge (> 50 kJ/mol)
- ❌ Wrong functional groups
- ❌ Wrong number of atoms
- ❌ Radical vs. molecule mismatch

### Example: Wrong Match
```
Species: CH4 (methane - saturated)
Candidate: [CH3] (methyl radical)
Problem: CH4 has 4 H atoms, CH3 has 3 H atoms
Action: Block this candidate ❌
```

### How to Do It:
```
1. Click species card → Detail page opens
2. Find the wrong candidate
3. Click red "Block" button
4. Modal appears: "Why are you blocking this match?"
5. Enter reason: "CH3 is radical, CH4 is saturated"
6. Click "Block" in modal
7. ❌ Done! Candidate is blocked
```

### What Happens:
```
Before:
  Candidate #3: CH3 [CH3]
  Votes: 1 unique, 1 total
  Status: Active

After:
  Candidate #3: CH3 [CH3]
  Status: Blocked ❌
  Blocked by: lekia.p
  Reason: "CH3 is radical, CH4 is saturated"
  Votes: Deleted
  Hidden from view
```

### Backend Code:
```python
# File: species_views.py, function: block_match()
# Line: ~378-456

@require_http_methods(["POST"])
def block_match(request, job_id, species_id):
    species = get_object_or_404(Species, id=species_id, job_id=job_id)
    candidate_id = request.POST.get('candidate_id')
    candidate = get_object_or_404(CandidateSpecies, id=candidate_id)
    reason = request.POST.get('reason', '')
    
    with transaction.atomic():
        # Create blocked match record
        BlockedMatch.objects.create(
            species=species,
            candidate=candidate,
            blocked_by=request.user,
            reason=reason
        )
        
        # Mark candidate as blocked
        candidate.is_blocked = True
        candidate.save()
        
        # Delete votes for this candidate
        Vote.objects.filter(candidate=candidate).delete()
    
    return JsonResponse({'success': True})
```

---

## ✏️ Action 3: Submit Custom SMILES

### When to Use:
- 🤔 No candidates shown
- 🤔 All candidates are wrong
- 🤔 You know the correct SMILES
- 🤔 Species is unusual/rare

### Example: No Good Match
```
Species: CF4 (carbon tetrafluoride)
Candidates shown:
  #1: CF3 [CF3] - Wrong (only 3 F, not 4)
  #2: CCl4 [C(Cl)(Cl)(Cl)Cl] - Wrong (Cl not F)

Solution: Submit correct SMILES → C(F)(F)(F)F
```

### How to Do It:
```
1. Click species card → Detail page opens
2. Scroll to bottom
3. Find "No good match? Submit your own SMILES:"
4. Enter SMILES: C(F)(F)(F)F
5. Click "Submit Custom SMILES"
6. ✏️ New candidate created!
7. Now confirm it (Action 1)
```

### What Happens:
```
Before:
  Candidates: 2 (both wrong)
  Status: Unidentified

After:
  Candidates: 3
  Candidate #3: CF4 [C(F)(F)(F)F]
  Source: Manual entry by lekia.p
  Status: Unconfirmed
  
Then you confirm it:
  Species: CF4
  Status: Confirmed ✅
  SMILES: C(F)(F)(F)F
```

### Backend Code:
```python
# File: species_views.py, function: submit_smiles()
# Line: ~459-530

@require_http_methods(["POST"])
def submit_smiles(request, job_id, species_id):
    species = get_object_or_404(Species, id=species_id, job_id=job_id)
    smiles = request.POST.get('smiles', '').strip()
    
    # Validate SMILES (basic)
    if not smiles:
        return JsonResponse({'success': False, 'error': 'SMILES required'})
    
    with transaction.atomic():
        # Create new candidate
        candidate = CandidateSpecies.objects.create(
            species=species,
            smiles=smiles,
            rmg_label=species.chemkin_label,
            rmg_index=None,
            vote_count=0,
            confidence_score=0.0,
            is_manual=True,
            submitted_by=request.user
        )
    
    return JsonResponse({
        'success': True,
        'candidate_id': candidate.id
    })
```

---

## 🎮 Decision Tree: Which Action?

```
Start: Looking at species with candidates
         ↓
    Question: Is there a good candidate?
         ↓
    ┌────┴────┐
    YES       NO
    ↓          ↓
Question:     Question: Do you know the correct SMILES?
Is it         ↓
correct?      ┌────┴────┐
    ↓         YES       NO
┌───┴───┐     ↓          ↓
YES    NO     Action 3:  Mark as
↓      ↓      Submit     tentative,
Action Action  SMILES     investigate
1:     2:      ↓          further
Confirm Block  Then Action 1
              (Confirm it)
```

---

## 💡 Tips for Making Good Decisions

### ✅ Good Signs (Confirm):
- 🟢 High confidence (> 70%)
- 🟢 Many votes (> 5 unique)
- 🟢 Low enthalpy discrepancy (< 5 kJ/mol)
- 🟢 Multiple thermo library matches
- 🟢 SMILES structure makes chemical sense
- 🟢 Voting reactions are logical

### ⚠️ Warning Signs (Investigate):
- 🟡 Medium confidence (40-70%)
- 🟡 Few votes (1-5 unique)
- 🟡 Medium enthalpy discrepancy (5-20 kJ/mol)
- 🟡 Competing candidates with similar votes
- 🟡 Unusual species or functional groups

### 🚫 Bad Signs (Block):
- 🔴 Very low confidence (< 20%)
- 🔴 Huge enthalpy discrepancy (> 50 kJ/mol)
- 🔴 Wrong molecular formula
- 🔴 Wrong number of atoms
- 🔴 Radical vs. molecule mismatch
- 🔴 Obviously wrong structure

---

## 📊 Reading the Evidence

### Vote Count Interpretation:
```
0 votes:
  → Pre-identified (formula match, thermo library)
  → Or no reactions use this species
  → Check if already confirmed

1-3 votes:
  → Low evidence
  → Might be correct but uncertain
  → Review carefully

5-10 votes:
  → Moderate evidence
  → Likely correct if enthalpy agrees
  → Good confidence

10+ votes:
  → Strong evidence
  → Very likely correct
  → High confidence, can confirm
```

### Enthalpy Discrepancy Guide:
```
0-5 kJ/mol:
  ✅ Excellent match
  → Almost certainly correct
  → Confirm with confidence

5-20 kJ/mol:
  ⚠️ Acceptable match
  → Probably correct
  → Check structure visually
  → Confirm if structure looks right

20-50 kJ/mol:
  ⚠️ Suspicious
  → May be correct but uncertain
  → Could be similar species
  → Investigate further

> 50 kJ/mol:
  ❌ Very suspicious
  → Likely wrong match
  → Different species entirely
  → Block or find alternative
```

### Confidence Score Guide:
```
🟢 Green (70-100%):
  → High confidence
  → Clear winner
  → Safe to confirm

🟡 Yellow (40-70%):
  → Medium confidence
  → Review evidence
  → Check enthalpy and structure

🔴 Red (0-40%):
  → Low confidence
  → Needs careful review
  → Consider custom SMILES
```

---

## 🔄 Common Workflows

### Workflow 1: Easy Confirmation
```
1. Filter: "Tentative" + Sort: "High Confidence"
2. Click first species (e.g., 95% confidence)
3. Quick review: SMILES looks good, ΔH = 1.2 kJ/mol
4. Click "Confirm"
5. Done in 10 seconds
6. Next species...
```

### Workflow 2: Competing Candidates
```
1. Species: C2H5 (ethyl radical)
2. Candidates:
   #1: [CH2]C (ethyl radical) - 10 votes, ΔH = 3 kJ/mol
   #2: CC (ethane) - 2 votes, ΔH = 150 kJ/mol
3. Decision:
   - #1 is correct (radical, low ΔH)
   - #2 is wrong (saturated, huge ΔH)
4. Actions:
   - Confirm #1 ✅
   - Block #2 ❌ (reason: "Ethane not ethyl")
5. Done
```

### Workflow 3: No Good Match
```
1. Species: CF3CHF2 (pentafluoroethane)
2. Candidates: None
3. Look up SMILES:
   - Google: "CF3CHF2 SMILES"
   - Result: FC(F)(F)C(F)F
4. Submit SMILES: FC(F)(F)C(F)F
5. New candidate appears
6. Confirm it ✅
7. Done
```

### Workflow 4: Controversial Species
```
1. Species flagged as "Controversial"
2. Multiple candidates with similar votes
3. Steps:
   a) Click "View Reactions" for each
   b) Compare reaction families
   c) Check enthalpy for all
   d) Look up species in literature
   e) Make informed decision
4. Confirm best match OR submit custom SMILES
5. Add note explaining choice
```

---

## ⚡ Keyboard Shortcuts (Future Feature)

```
Not yet implemented, but could add:

Queue View:
  ↑/↓     - Navigate species
  Enter   - Open detail
  u       - Filter unidentified
  t       - Filter tentative
  c       - Filter confirmed

Detail View:
  1       - Confirm candidate #1
  2       - Block candidate #1
  s       - Focus SMILES input
  Esc     - Back to queue
  n       - Next species
  p       - Previous species
```

---

## 📈 Tracking Your Progress

### Dashboard Stats:
```
Job: CombFlame2013/2343-Hansen

Total Species: 230
  ✅ Confirmed: 218 (95%)
  🟡 Tentative: 7 (3%)
  ⚪ Unidentified: 5 (2%)

Your Contributions:
  ✅ Confirmed: 42 species
  ❌ Blocked: 8 candidates
  ✏️ Custom SMILES: 3 species

Time spent: 2h 15m
Average time per species: 3m 12s
```

---

## 🚨 Common Mistakes to Avoid

### ❌ Don't:
1. **Confirm without checking enthalpy**
   - Always verify ΔH is reasonable
   - Large discrepancies indicate wrong match

2. **Block candidates prematurely**
   - Only block if clearly wrong
   - Tentative is better than blocking

3. **Submit invalid SMILES**
   - Validate SMILES before submitting
   - Use RDKit or online checker

4. **Ignore voting evidence**
   - Click "View Reactions" for suspicious matches
   - Reactions tell you why votes exist

5. **Confirm radicals as molecules (or vice versa)**
   - [CH3] is radical (3 H)
   - [CH4] or C is methane (4 H)
   - Check carefully!

### ✅ Do:
1. **Start with high confidence species**
   - Build momentum
   - Get familiar with interface

2. **Review multiple candidates**
   - Don't just confirm #1
   - Compare all options

3. **Document unusual decisions**
   - Add notes for controversial matches
   - Help future users

4. **Ask for help when uncertain**
   - Better to ask than guess
   - Domain experts can review

5. **Take breaks**
   - Fatigue leads to errors
   - Fresh eyes catch mistakes

---

## 🆘 Troubleshooting

### Problem: "No candidates shown"
```
Possible causes:
1. Vote data not synced yet
   → Click "Sync Votes" button
   → Wait for sync to complete

2. No reactions use this species
   → This is normal
   → Submit custom SMILES

3. RMG couldn't find matches
   → Species is unusual/rare
   → Submit custom SMILES
```

### Problem: "All candidates have low confidence"
```
This means:
- No clear winner
- Few votes
- Conflicting evidence

Action:
1. Review all candidates carefully
2. Check enthalpy discrepancies
3. Look up species in literature
4. Submit custom SMILES if needed
5. Ask expert if very uncertain
```

### Problem: "Confirmed the wrong species"
```
Solution:
1. Go back to species detail
2. Block the wrong candidate (reason: "Incorrect confirmation")
3. Confirm correct candidate
4. Or submit custom SMILES

Note: Currently no "undo" button
       But you can block then re-confirm
```

### Problem: "Can't find SMILES for rare species"
```
Resources:
1. PubChem: pubchem.ncbi.nlm.nih.gov
2. ChemSpider: chemspider.com
3. RDKit: Generate from structure
4. Ask RMG team
5. Use SMILES converter tools
```

---

## 📚 Additional Resources

### Documentation:
- `USER_GUIDE_VOTING.md` - Detailed voting explanation
- `DASHBOARD_COMPARISON.md` - Old vs new system
- `QUICK_REFERENCE_USER_ACTIONS.md` - Visual diagrams
- `IMPLEMENTATION_SUMMARY.md` - Technical details

### Code Locations:
- UI: `importer_dashboard/templates/importer_dashboard/`
- Views: `importer_dashboard/species_views.py`
- Models: `importer_dashboard/models.py`
- Sync: `importer_dashboard/incremental_sync.py`

### Getting Help:
- Check documentation first
- Ask in team chat
- Email: lekia.p@northeastern.edu
- GitHub issues (if applicable)

---

## 🎯 Quick Reference Card

```
╔═══════════════════════════════════════════════════════════╗
║         SPECIES IDENTIFICATION QUICK REFERENCE            ║
╠═══════════════════════════════════════════════════════════╣
║                                                           ║
║  Action 1: ✅ CONFIRM                                     ║
║  When: High confidence, low ΔH, correct structure         ║
║  How: Click green "Confirm" button                        ║
║  Result: Species → confirmed, SMILES assigned             ║
║                                                           ║
║  ─────────────────────────────────────────────────────    ║
║                                                           ║
║  Action 2: ❌ BLOCK                                       ║
║  When: Wrong structure, huge ΔH, clearly incorrect        ║
║  How: Click red "Block" button, give reason               ║
║  Result: Candidate hidden, votes deleted                  ║
║                                                           ║
║  ─────────────────────────────────────────────────────────║
║                                                           ║
║  Action 3: ✏️ SUBMIT SMILES                               ║
║  When: No good candidates, you know correct SMILES        ║
║  How: Enter SMILES in bottom form, click "Submit"         ║
║  Result: New candidate created, then confirm it           ║
║                                                           ║
║  ═════════════════════════════════════════════════════════║
║                                                           ║
║  Confidence Colors:                                       ║
║    🟢 Green (>70%)  → Confirm with confidence            ║
║    🟡 Yellow (40-70%) → Review carefully                  ║
║    🔴 Red (<40%)    → Investigate thoroughly              ║
║                                                           ║
║  Enthalpy Guide:                                          ║
║    < 5 kJ/mol    → ✅ Excellent                           ║
║    5-20 kJ/mol   → ⚠️ Acceptable                          ║
║    > 50 kJ/mol   → ❌ Very suspicious                     ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
```

---

**Ready to start identifying species? Open the dashboard and dive in!** 🚀
