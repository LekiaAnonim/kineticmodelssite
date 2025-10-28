"""
CHEMKIN Mechanism Parser

Parses CHEMKIN format mechanism files to extract:
- Species from SPECIES section
- Reactions from REACTIONS section with kinetics parameters
- Thermodynamics data from NASA polynomial format
"""

import re
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass


@dataclass
class ChemkinSpecies:
    """Represents a species from CHEMKIN mechanism"""
    name: str
    index: int  # Position in species list


@dataclass
class ChemkinReaction:
    """Represents a reaction from CHEMKIN mechanism"""
    index: int
    equation: str
    reactants: List[str]
    products: List[str]
    
    # Arrhenius parameters
    A: float  # Pre-exponential factor
    n: float  # Temperature exponent
    Ea: float  # Activation energy (cal/mol or J/mol)
    
    # Optional parameters
    is_reversible: bool = True
    is_duplicate: bool = False
    pressure_dependent: bool = False
    third_body: bool = False
    
    # Temperature range (if specified)
    temp_low: Optional[float] = None
    temp_high: Optional[float] = None
    
    # Additional attributes
    comments: str = ""


@dataclass
class NASAPolynomial:
    """NASA polynomial coefficients for thermodynamics"""
    temp_low: float
    temp_high: float
    coeffs: List[float]  # 7 coefficients: a1-a7


@dataclass
class ThermoEntry:
    """Thermodynamics data for a species"""
    name: str
    formula: str  # Chemical formula
    phase: str  # G=gas, L=liquid, S=solid
    temp_low: float
    temp_mid: float  # Mid temperature for polynomial switch
    temp_high: float
    low_temp_poly: NASAPolynomial  # Polynomial for T_low to T_mid
    high_temp_poly: NASAPolynomial  # Polynomial for T_mid to T_high
    comments: str = ""


class ChemkinParser:
    """
    Parser for CHEMKIN format mechanism files
    """
    
    def __init__(self, mechanism_file_path: str):
        self.mechanism_file_path = mechanism_file_path
        self._content = None
        self._species_section = None
        self._reactions_section = None
    
    def _load_file(self):
        """Load mechanism file content"""
        if self._content is None:
            with open(self.mechanism_file_path, 'r') as f:
                self._content = f.read()
    
    def parse_species(self) -> List[ChemkinSpecies]:
        """
        Parse SPECIES section to extract all species names
        
        Returns:
            List of ChemkinSpecies objects
        """
        self._load_file()
        
        # Find SPECIES section
        species_pattern = r'SPECIES\s+(.*?)\s+END'
        match = re.search(species_pattern, self._content, re.DOTALL | re.IGNORECASE)
        
        if not match:
            raise ValueError("No SPECIES section found in mechanism file")
        
        species_text = match.group(1)
        
        # Extract species names (whitespace or newline separated)
        # Remove comments (lines starting with !)
        lines = species_text.split('\n')
        species_names = []
        
        for line in lines:
            # Remove comments
            if '!' in line:
                line = line[:line.index('!')]
            
            # Split by whitespace and add to list
            names = line.split()
            species_names.extend(names)
        
        # Create ChemkinSpecies objects
        species_list = [
            ChemkinSpecies(name=name.strip(), index=idx)
            for idx, name in enumerate(species_names, start=1)
        ]
        
        return species_list
    
    def parse_reactions(self) -> List[ChemkinReaction]:
        """
        Parse REACTIONS section to extract all reactions with kinetics
        
        Returns:
            List of ChemkinReaction objects
        """
        self._load_file()
        
        # Find REACTIONS section
        reactions_pattern = r'REACTIONS\s+(.*?)\s+END'
        match = re.search(reactions_pattern, self._content, re.DOTALL | re.IGNORECASE)
        
        if not match:
            raise ValueError("No REACTIONS section found in mechanism file")
        
        reactions_text = match.group(1)
        reactions = []
        
        lines = reactions_text.split('\n')
        idx = 0
        reaction_idx = 1
        
        while idx < len(lines):
            line = lines[idx].strip()
            
            # Skip empty lines and comments
            if not line or line.startswith('!'):
                idx += 1
                continue
            
            # Check if line contains a reaction equation (contains = or =>)
            if '=' in line or '=>' in line:
                try:
                    reaction = self._parse_reaction_line(line, reaction_idx, lines, idx)
                    if reaction:
                        reactions.append(reaction)
                        reaction_idx += 1
                except Exception as e:
                    # Log but continue parsing
                    print(f"Warning: Failed to parse reaction at line {idx}: {e}")
            
            idx += 1
        
        return reactions
    
    def _parse_reaction_line(self, line: str, reaction_idx: int, 
                            all_lines: List[str], current_idx: int) -> Optional[ChemkinReaction]:
        """
        Parse a single reaction line and its kinetics parameters
        """
        # Split equation from kinetics
        # Format: REACTANTS = PRODUCTS   A   n   Ea
        parts = line.split()
        
        if len(parts) < 5:
            return None
        
        # Find the equation part (everything before kinetics parameters)
        equation_parts = []
        kinetics_start = -1
        
        for i, part in enumerate(parts):
            # Look for the first numeric value (start of kinetics)
            try:
                float(part.replace('D', 'E').replace('d', 'e'))
                kinetics_start = i
                break
            except ValueError:
                equation_parts.append(part)
        
        if kinetics_start == -1 or len(parts) < kinetics_start + 3:
            return None
        
        equation = ' '.join(equation_parts)
        
        # Determine if reversible
        is_reversible = '<=>' in equation or '=' in equation
        if not is_reversible:
            is_reversible = '=>' not in equation
        
        # Split reactants and products
        if '<=>' in equation:
            reactants_str, products_str = equation.split('<=>')
        elif '=>' in equation:
            reactants_str, products_str = equation.split('=>')
        elif '=' in equation:
            reactants_str, products_str = equation.split('=')
        else:
            return None
        
        # Parse reactants and products
        reactants = self._parse_species_list(reactants_str)
        products = self._parse_species_list(products_str)
        
        # Parse kinetics parameters (A, n, Ea)
        try:
            A_str = parts[kinetics_start].replace('D', 'E').replace('d', 'e')
            n_str = parts[kinetics_start + 1].replace('D', 'E').replace('d', 'e')
            Ea_str = parts[kinetics_start + 2].replace('D', 'E').replace('d', 'e')
            
            A = float(A_str)
            n = float(n_str)
            Ea = float(Ea_str)
        except (ValueError, IndexError):
            return None
        
        # Check for modifiers (DUPLICATE, etc.) in following lines
        is_duplicate = False
        comments = []
        
        # Look ahead a few lines for modifiers
        for i in range(current_idx + 1, min(current_idx + 5, len(all_lines))):
            next_line = all_lines[i].strip().upper()
            if 'DUPLICATE' in next_line or 'DUP' in next_line:
                is_duplicate = True
            if next_line.startswith('!'):
                comments.append(all_lines[i].strip())
            if next_line and not next_line.startswith('!') and 'DUPLICATE' not in next_line:
                break
        
        return ChemkinReaction(
            index=reaction_idx,
            equation=equation.strip(),
            reactants=reactants,
            products=products,
            A=A,
            n=n,
            Ea=Ea,
            is_reversible=is_reversible,
            is_duplicate=is_duplicate,
            comments='\n'.join(comments)
        )
    
    def _parse_species_list(self, species_str: str) -> List[str]:
        """
        Parse species from reaction equation string
        
        Handles:
        - CH4 + O2
        - 2CH4 + O2
        - CH4(+M)
        """
        species_str = species_str.replace('(+M)', '').replace('(+m)', '')
        
        species = []
        # Split by + sign
        parts = species_str.split('+')
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            # Remove stoichiometric coefficient if present
            # Match pattern: optional number followed by species name
            match = re.match(r'^(\d*\.?\d*)\s*(.+)$', part)
            if match:
                species_name = match.group(2).strip()
                if species_name:
                    species.append(species_name)
        
        return species


class ThermoParser:
    """
    Parser for NASA polynomial format thermodynamics data
    """
    
    def __init__(self, thermo_file_path: str):
        self.thermo_file_path = thermo_file_path
        self._content = None
    
    def _load_file(self):
        """Load thermo file content"""
        if self._content is None:
            with open(self.thermo_file_path, 'r') as f:
                self._content = f.readlines()
    
    def parse_thermo(self) -> List[ThermoEntry]:
        """
        Parse NASA polynomial format thermodynamics data
        
        NASA 7-coefficient polynomial format:
        Line 1: Species name, comments, formula, phase, temp range
        Lines 2-4: Polynomial coefficients
        
        Returns:
            List of ThermoEntry objects
        """
        self._load_file()
        
        thermo_entries = []
        idx = 0
        
        # Skip header lines (THERMO ALL or THERMO)
        while idx < len(self._content):
            line = self._content[idx].strip().upper()
            if line.startswith('THERMO'):
                idx += 1
                break
            idx += 1
        
        # Parse entries (4 lines per species)
        while idx < len(self._content) - 3:
            line1 = self._content[idx]
            
            # Check for END
            if line1.strip().upper().startswith('END'):
                break
            
            # Skip comment lines
            if line1.strip().startswith('!'):
                idx += 1
                continue
            
            try:
                entry = self._parse_thermo_entry(
                    self._content[idx:idx+4]
                )
                if entry:
                    thermo_entries.append(entry)
                idx += 4
            except Exception as e:
                print(f"Warning: Failed to parse thermo entry at line {idx}: {e}")
                idx += 1
        
        return thermo_entries
    
    def _parse_thermo_entry(self, lines: List[str]) -> Optional[ThermoEntry]:
        """
        Parse a single 4-line NASA polynomial entry
        
        Format:
        Line 1: NAME          DATE  FORMULA      PHASE  TLOW   THIGH  TMID      1
        Line 2: a1 a2 a3 a4 a5                                                   2
        Line 3: a6 a7 a1' a2' a3' a4' a5'                                        3
        Line 4: a6' a7' (more coefficients or blank)                             4
        """
        if len(lines) < 4:
            return None
        
        line1 = lines[0]
        line2 = lines[1]
        line3 = lines[2]
        line4 = lines[3]
        
        # Parse line 1: species name and temperature range
        # Format is column-based in original CHEMKIN
        name = line1[0:18].strip()
        formula = line1[24:44].strip()
        phase = line1[44:45].strip() if len(line1) > 44 else 'G'
        
        # Temperature range (columns vary by format)
        try:
            temp_low = float(line1[45:55].strip())
            temp_high = float(line1[55:65].strip())
            temp_mid = float(line1[65:75].strip())
        except (ValueError, IndexError):
            return None
        
        # Parse coefficients from lines 2-4
        # Each line has 5 coefficients in scientific notation (15 chars each)
        try:
            coeffs = []
            
            # Line 2: first 5 coefficients of high-temp polynomial
            for i in range(5):
                start = i * 15
                end = start + 15
                coeff_str = line2[start:end].strip().replace('D', 'E').replace('d', 'e')
                if coeff_str:
                    coeffs.append(float(coeff_str))
            
            # Line 3: last 2 of high-temp + first 3 of low-temp
            for i in range(5):
                start = i * 15
                end = start + 15
                coeff_str = line3[start:end].strip().replace('D', 'E').replace('d', 'e')
                if coeff_str:
                    coeffs.append(float(coeff_str))
            
            # Line 4: last 4 of low-temp
            for i in range(4):
                start = i * 15
                end = start + 15
                coeff_str = line4[start:end].strip().replace('D', 'E').replace('d', 'e')
                if coeff_str:
                    coeffs.append(float(coeff_str))
            
            # Should have 14 coefficients total
            # First 7: high temperature polynomial (a1-a7)
            # Last 7: low temperature polynomial (a1'-a7')
            if len(coeffs) < 14:
                return None
            
            high_temp_poly = NASAPolynomial(
                temp_low=temp_mid,
                temp_high=temp_high,
                coeffs=coeffs[0:7]
            )
            
            low_temp_poly = NASAPolynomial(
                temp_low=temp_low,
                temp_high=temp_mid,
                coeffs=coeffs[7:14]
            )
            
            return ThermoEntry(
                name=name,
                formula=formula,
                phase=phase,
                temp_low=temp_low,
                temp_mid=temp_mid,
                temp_high=temp_high,
                low_temp_poly=low_temp_poly,
                high_temp_poly=high_temp_poly
            )
            
        except (ValueError, IndexError) as e:
            print(f"Error parsing coefficients for {name}: {e}")
            return None
