"""PubChem PUG-REST enrichment, run outside the search request path.

https://iupac.github.io/WFChemCookbook/datasources/pubchem_pugrest3.html
"""

import time

import requests

from .chemical_identity import canonical_smiles


class PubChemError(Exception):
    """A temporary or malformed response; do not mark this structure as checked."""


class PubChemClient:
    base_url = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
    retryable_statuses = {429, 500, 502, 503, 504}

    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "kineticmodelssite/1.0 (species naming)"
        self.last_request = 0

    def _get(self, path, params=None):
        for attempt in range(3):
            # PubChem permits at most five requests per second; stay below that.
            time.sleep(max(0, 0.25 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            try:
                response = self.session.get(
                    f"{self.base_url}/{path}", params=params, timeout=(5, 20)
                )
                if response.status_code == 404:
                    return None
                if response.status_code in self.retryable_statuses and attempt < 2:
                    time.sleep(2 ** (attempt + 1))
                    continue
                if response.status_code >= 400:
                    detail = ""
                    try:
                        payload = response.json()
                        fault = payload.get("Fault", {}) if isinstance(payload, dict) else {}
                        if isinstance(fault, dict):
                            detail = " ".join(str(fault.get("Message", "")).split())[:240]
                    except ValueError:
                        pass
                    raise PubChemError(
                        f"PubChem HTTP {response.status_code} on {path}"
                        f" after {attempt + 1} attempt(s)" + (f": {detail}" if detail else ".")
                    )
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                if attempt == 2:
                    reason = type(exc).__name__
                    raise PubChemError(
                        f"PubChem {reason} on {path} after {attempt + 1} attempts."
                    ) from exc
                time.sleep(2 ** (attempt + 1))

    def resolve(self, smiles):
        identity = canonical_smiles(smiles)
        if not identity:
            return None
        payload = self._get(
            "compound/smiles/property/IUPACName,IsomericSMILES/JSON",
            params={"smiles": identity},
        )
        if payload is None:
            return None
        try:
            candidates = payload["PropertyTable"]["Properties"]
            # PubChem may standardize tautomers, charge, or stereo. Only accept
            # the exact local molecular identity, never just a shared formula.
            matches = [item for item in candidates if canonical_smiles(
                item.get("SMILES") or item.get("IsomericSMILES", "")
            ) == identity]
            if len(matches) != 1:
                return None
            match = matches[0]
            cid = int(match["CID"])
            # Some valid compounds (e.g. CID 22750579) have structure data but
            # no computed IUPAC name. This is missing coverage, not an API failure.
            iupac_name = match.get("IUPACName")
            if iupac_name is None:
                iupac_name = ""
            if not isinstance(iupac_name, str) or cid <= 0:
                raise ValueError("Missing compound identity")
            synonyms = self._get(f"compound/cid/{cid}/synonyms/JSON")
            names = []
            if synonyms is not None:
                for item in synonyms["InformationList"]["Information"]:
                    if int(item["CID"]) == cid:
                        names.extend(item.get("Synonym", []))
            names = sorted({name.strip() for name in names
                            if isinstance(name, str) and 0 < len(name.strip()) <= 500})
            # Retain the verified compound link even when naming data is absent.
            return {"cid": cid, "iupac_name": iupac_name.strip(), "synonyms": names}
        except (KeyError, TypeError, ValueError) as exc:
            raise PubChemError("PubChem returned an incomplete compound record.") from exc

    def cas_numbers(self, inchikey):
        """CAS numbers among the synonyms of the compounds with this standard InChIKey, in
        PubChem's order (most relevant synonyms first)."""
        from .nist import CAS, valid_cas
        payload = self._get(f"compound/inchikey/{inchikey}/synonyms/JSON")
        if payload is None:
            return []
        try:
            synonyms = [name for item in payload["InformationList"]["Information"] for name in item.get("Synonym", [])]
        except (KeyError, TypeError) as exc:
            raise PubChemError("PubChem returned an incomplete synonym record.") from exc
        found = {}
        for name in synonyms:
            match = CAS.match(name.strip()) if isinstance(name, str) else None
            if match and valid_cas(match.group(1)):
                found.setdefault(match.group(1))
        return list(found)
