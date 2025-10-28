# Phase 1 Features Testing Checklist

## Overview
We've implemented 3 major features that leverage the synced CHEMKIN data (372 species, 8,314 reactions, 372 thermo entries).

---

## ✅ Feature #5: Show Reactions for Each Species

**What was implemented:**
- Added reactions display to species detail page
- Shows up to 50 reactions where the species appears (as reactant or product)
- Displays: equation, kinetics parameters (A, n, Ea), temperature range, reversible/duplicate flags

**How to test:**
1. Navigate to: http://localhost:8000/importer_dashboard/
2. Click on your job (e.g., "Hansen")
3. Click "Species Queue" or go to: http://localhost:8000/importer_dashboard/job/1/species-queue/
4. Click on any species to view details
5. **Scroll down** - you should see a new section: "Reactions Containing This Species"
6. Verify:
   - [ ] Section header shows reaction count
   - [ ] Reactions are displayed with equations
   - [ ] Kinetics parameters shown as badges (A, n, Ea)
   - [ ] Temperature range displayed if available
   - [ ] Alert shown if more than 50 reactions exist

**Expected result:**
```
Reactions Containing This Species (123 reactions)
├── H2 + OH <=> H2O + H
│   A: 2.16e+08  n: 1.51  Ea: 3430.0
│   Temp: 300-2500 K  Reversible: ✓
├── CH4 + OH <=> CH3 + H2O
│   A: 1.00e+08  n: 1.6  Ea: 3120.0
...
```

---

## ✅ Feature #6: Sort by Importance (Reaction Participation)

**What was implemented:**
- Added new sort option: "Most Important (by reactions)"
- Counts how many reactions each species appears in
- Sorts species by reaction count (descending)
- Prioritizes "hub" species that appear in many reactions

**How to test:**
1. Go to species queue: http://localhost:8000/importer_dashboard/job/1/species-queue/
2. Find the **Sort by** dropdown in the filters section
3. Select **"Most Important (by reactions)"**
4. Page should reload with reordered species

5. Verify:
   - [ ] Dropdown shows new option
   - [ ] Species are reordered after selection
   - [ ] Species at top should be ones that appear in many reactions (e.g., H2, O2, OH, H2O)
   - [ ] Can switch between sort options (confidence, name, importance)

**Expected behavior:**
- Species like H₂, O₂, OH, H₂O should appear at the top (they're in many reactions)
- Large molecules that appear in few reactions should be at the bottom
- This helps prioritize identification of the most impactful species

---

## ✅ Feature #7: Mechanism Coverage Page

**What was implemented:**
- New dedicated page for coverage analysis
- Calculates what % of mechanism is usable with current identifications
- Categories:
  - **Fully Usable**: All species identified (can use in simulations now)
  - **Partially Identified**: Some species identified (close to usable)
  - **Not Yet Usable**: No species identified (need more work)
- Shows sample reactions from each category
- Provides interpretation guide

**How to test:**
1. From species queue, click the **"Mechanism Coverage"** button in the header
   - Or go directly to: http://localhost:8000/importer_dashboard/job/1/mechanism-coverage/

2. Verify the page displays:
   - [ ] Overall progress bars (species and reactions)
   - [ ] Three colored cards with counts:
     - Green: Fully Usable Reactions
     - Yellow: Partially Identified
     - Red: Not Yet Usable
   - [ ] Sample reactions from each category (up to 10 each)
   - [ ] Interpretation guide at bottom

3. Check calculations:
   - [ ] Total reactions = 8,314 (for Hansen job)
   - [ ] Coverage % should match: (usable / total) × 100
   - [ ] Species count: X / 372
   - [ ] Numbers should add up: usable + partial + unidentified = 8,314

**Expected insights:**
- Early in identification: Most reactions are "Not Yet Usable" or "Partially Identified"
- As you identify species: Coverage % increases, more reactions become "Fully Usable"
- Goal: Reach 80%+ coverage for comprehensive mechanism representation

---

## Quick Visual Test (All Features at Once)

**5-Minute Walkthrough:**

1. **Start at job list** → Click your job → Click "Species Queue"

2. **Test Coverage Button**
   - Click "Mechanism Coverage" button (new, blue)
   - Should see coverage analysis page with progress bars
   - Note the coverage percentage
   - Click back to Species Queue

3. **Test Importance Sort**
   - Find "Sort by" dropdown
   - Select "Most Important (by reactions)"
   - Top species should be common ones (H2, O2, OH, etc.)

4. **Test Reactions Display**
   - Click on first species in the list
   - Scroll to bottom of species detail page
   - Should see "Reactions Containing This Species" section
   - Verify reactions are displayed with kinetics

---

## Common Issues & Troubleshooting

### Issue: "Mechanism Coverage" button not visible
- **Fix**: Refresh browser (Ctrl+F5 or Cmd+Shift+R)
- **Cause**: Template cached

### Issue: Sort dropdown doesn't have "Most Important" option
- **Fix**: Clear browser cache, refresh page
- **Check**: Look at line 230 in species_queue.html

### Issue: No reactions showing on species detail page
- **Possible causes**:
  1. Species doesn't appear in any reactions (rare)
  2. ChemkinReaction data not synced (check: should be 8,314 reactions)
  3. ChemkinLabel mismatch (check species.chemkin_label)
- **Debug**: Check Django logs for SQL queries

### Issue: Coverage page shows 0% or wrong numbers
- **Check**: 
  1. ChemkinReaction count: Should be 8,314
  2. Species identification_status: Should have some 'confirmed'
  3. ChemkinLabel formatting: Should match between Species and ChemkinReaction

### Issue: Page loads slowly with importance sort
- **Expected**: First load may take 5-10 seconds (counting reactions for each species)
- **Future optimization**: Use Django annotations for database-level counting
- **Workaround**: Use other sort options for quick browsing

---

## Performance Notes

**Current implementation (Phase 1 - MVP):**
- Importance sort: In-memory counting (acceptable for 372 species)
- Reactions display: Limited to 50 per species (prevents overload)
- Coverage page: Single query + Python processing

**If needed (Phase 2 optimization):**
- Add database index on ChemkinReaction.reactants and .products
- Use Django annotations for importance sort (database-level aggregation)
- Cache coverage calculations (update on species confirmation)

---

## Next Steps After Testing

**If all tests pass:**
- [ ] Mark testing todo as complete
- [ ] Consider Phase 2 features (export mechanism, reaction search)
- [ ] Update documentation with screenshots

**If issues found:**
- [ ] Document specific errors
- [ ] Check Django logs: `tail -f kineticmodelssite/debug.log`
- [ ] Report issues to fix

---

## Success Criteria

✅ **Phase 1 is successful if:**
1. Coverage page loads and shows correct calculations
2. Importance sort reorders species logically
3. Reactions display on species detail page
4. No Python errors or 500 errors
5. Page load times are reasonable (<10 seconds)

🎉 **Congratulations!** You now have a mechanism curation dashboard that:
- Shows the full reaction network
- Helps prioritize important species
- Tracks your progress toward a usable mechanism
- All powered by the 8,314 reactions and 372 thermo entries we synced!
