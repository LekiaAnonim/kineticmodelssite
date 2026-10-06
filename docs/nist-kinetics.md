# NIST Chemical Kinetics Database

The NIST Chemical Kinetics Database (SRD 17, <https://kinetics.nist.gov/>) has no API or bulk download, and its `robots.txt` allows no automated agents other than search engines. The site does not copy NIST's data and never fetches from it. Instead, each reaction page links to NIST's own search, so a reader can compare NIST's records with the models' rates there.

## Reaction links

NIST identifies species by CAS registry number. For each species in a reaction (explicit colliders aside), the site uses one CAS number it can trust:

1. ATcT's CAS number, when the species has an ATcT record (these are matched to the structure, and cover most small radicals);
2. otherwise the structure's PubChem synonyms, when they give exactly one CAS number, or exactly one that ATcT confirms;
3. otherwise the first CAS number among the synonyms of the PubChem compounds with the structure's standard InChIKey. PubChem lists the most relevant synonyms first. The species-search names only accept an exact SMILES match, which misses many radicals and small molecules such as H2; the InChIKey does not.

InChI ignores spin, so step 3 is skipped for a structure whose standard InChI another structure on the site shares in a different spin state (O(3P) and O(1D), singlet and triplet CH2): PubChem cannot say which one a CAS number means. To fill step 3 for new structures:

```sh
python manage.py enrich_structure_cas            # --refresh rechecks everything
```

The reaction page then offers:

| When | Links |
|---|---|
| every species has a CAS number | the reaction as written, written in reverse (NIST stores each reaction one way), and all reactions of the reactants (other product channels) |
| only the reactants (or only the products) do | all reactions of those species |
| neither side does | NIST's search form, to search by formula |

Species without a CAS number are named, each with a link to its NIST Chemistry WebBook page by InChI, where its CAS number can usually be found. A "CAS numbers used" list shows each number and where it came from. PubChem's CAS numbers are a search aid, not proof of identity; check the structures on NIST's record.

## Species links

Each structure on a species page links to its NIST Chemistry WebBook page by standard InChI (RMG's unpaired-electron and lone-pair layers removed).

Cite NIST as it asks: <https://kinetics.nist.gov/kinetics/citation.jsp>.
