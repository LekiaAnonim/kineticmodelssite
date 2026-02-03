"""
ReSpecTh v2.x to Database Converter

This module provides conversion functionality for ReSpecTh v2.x XML files,
which have a different structure than the v1.x files that PyKED expects.

ReSpecTh v2.x file types:
- kdetermination: Rate coefficient determination data (k files)
- tdetermination: Thermochemical data (t files)
- experiment: Experimental data (x files) - similar to ChemKED

Author: Generated for kineticmodelssite
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from decimal import Decimal
import re
import logging

logger = logging.getLogger(__name__)


@dataclass
class Author:
    """Represents an author from bibliographic data."""
    name: str
    orcid: Optional[str] = None


@dataclass
class Reference:
    """Represents bibliography/reference information."""
    description: str
    doi: Optional[str] = None
    journal: Optional[str] = None
    volume: Optional[str] = None
    pages: Optional[str] = None
    year: Optional[int] = None
    title: Optional[str] = None
    authors: List[Author] = field(default_factory=list)
    location: Optional[str] = None
    table: Optional[str] = None
    figure: Optional[str] = None


@dataclass 
class Species:
    """Represents a species in the reaction or composition."""
    preferred_key: str
    cas: Optional[str] = None
    inchi: Optional[str] = None
    smiles: Optional[str] = None
    chem_name: Optional[str] = None


@dataclass
class Reaction:
    """Represents a reaction."""
    preferred_key: str
    order: Optional[int] = None
    bulk_gas: Optional[str] = None
    reactants: List[str] = field(default_factory=list)
    products: List[str] = field(default_factory=list)


@dataclass
class DataProperty:
    """Represents a data property definition."""
    name: str
    id: str
    label: Optional[str] = None
    source_type: Optional[str] = None
    units: Optional[str] = None
    species_link: Optional[Species] = None


@dataclass
class DataPoint:
    """Represents a single data point with property values."""
    values: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CommonProperty:
    """Represents a common property that applies to all datapoints."""
    name: str
    value: Any
    units: Optional[str] = None
    source_type: Optional[str] = None
    label: Optional[str] = None
    reference: Optional[str] = None
    kind: Optional[str] = None
    components: List[Dict[str, Any]] = field(default_factory=list)  # For composition


@dataclass
class CompositionComponent:
    """Represents a species in the initial composition."""
    species_name: str
    amount: float
    amount_units: str = 'mole fraction'
    cas: Optional[str] = None
    inchi: Optional[str] = None
    smiles: Optional[str] = None


@dataclass
class UncertaintyData:
    """Represents uncertainty/standard deviation data for a species."""
    species_name: str
    value: float
    units: str = 'mole fraction'
    kind: str = 'absolute'
    method: str = ''
    source_type: str = ''


@dataclass
class ReSpecThV2Data:
    """
    Container for parsed ReSpecTh v2.x data.
    """
    # File metadata
    file_type: str  # 'kdetermination', 'tdetermination', 'experiment'
    file_author: str
    file_doi: Optional[str] = None
    file_version: str = "1.0"
    respecth_version: str = "2.0"
    first_publication_date: Optional[str] = None
    last_modification_date: Optional[str] = None
    
    # Reference information
    reference: Optional[Reference] = None
    
    # Reaction (for k and t files)
    reaction: Optional[Reaction] = None
    
    # Method (experimental method description)
    method: Optional[str] = None
    
    # Properties and data
    common_properties: List[CommonProperty] = field(default_factory=list)
    data_properties: List[DataProperty] = field(default_factory=list)
    datapoints: List[DataPoint] = field(default_factory=list)
    
    # Composition data
    initial_composition: List[CompositionComponent] = field(default_factory=list)
    
    # Uncertainty data for species
    uncertainties: List[UncertaintyData] = field(default_factory=list)
    
    # Additional fields for experiment files
    experiment_type: Optional[str] = None
    apparatus_kind: Optional[str] = None


class ReSpecThV2Parser:
    """
    Parser for ReSpecTh v2.x XML files.
    
    Supports:
    - kdetermination files (rate coefficient data)
    - tdetermination files (thermochemical data)  
    - experiment files (experimental measurements like ignition delay)
    """
    
    def __init__(self, xml_file: str):
        """
        Initialize parser with an XML file path.
        
        Args:
            xml_file: Path to the ReSpecTh v2.x XML file
        """
        self.xml_file = xml_file
        self.tree = ET.parse(xml_file)
        self.root = self.tree.getroot()
        self.file_type = self.root.tag
        
    def parse(self):
        """
        Parse the XML file and return structured data.
        
        Returns:
            ReSpecThV2Data object containing all parsed information
        """
        data = ReSpecThV2Data(
            file_type=self.file_type,
            file_author=self._get_text('fileAuthor', ''),
            file_doi=self._get_text('fileDOI'),
            file_version=self._parse_version('fileVersion'),
            respecth_version=self._parse_version('ReSpecThVersion'),
            first_publication_date=self._get_text('firstPublicationDate'),
            last_modification_date=self._get_text('lastModificationDate'),
        )
        
        # Parse reference/bibliography
        data.reference = self._parse_bibliography()
        
        # Parse reaction (for k and t files)
        data.reaction = self._parse_reaction()
        
        # Parse method
        data.method = self._get_text('method')
        
        # Parse common properties
        data.common_properties = self._parse_common_properties()
        
        # Parse initial composition from common properties
        data.initial_composition = self._parse_initial_composition()
        
        # Parse uncertainty/standard deviation data
        data.uncertainties = self._parse_uncertainties()
        
        # Parse data group
        data.data_properties, data.datapoints = self._parse_data_group()
        
        # Parse experiment-specific fields
        data.experiment_type = self._get_text('experimentType')
        apparatus = self.root.find('apparatus')
        if apparatus is not None:
            data.apparatus_kind = self._get_text_from_element(apparatus, 'kind')
        
        return data
    
    def _get_text(self, tag: str, default: Optional[str] = None):
        """Get text content of a direct child element."""
        elem = self.root.find(tag)
        return elem.text.strip() if elem is not None and elem.text else default
    
    def _get_text_from_element(self, parent: ET.Element, tag: str, 
                                default: Optional[str] = None):
        """Get text content of a child element from a parent."""
        elem = parent.find(tag)
        return elem.text.strip() if elem is not None and elem.text else default
    
    def _parse_version(self, tag: str):
        """Parse version element with major/minor children."""
        elem = self.root.find(tag)
        if elem is None:
            return "1.0"
        major = self._get_text_from_element(elem, 'major') or '1'
        minor = self._get_text_from_element(elem, 'minor') or '0'
        return f"{major}.{minor}"
    
    def _parse_bibliography(self):
        """Parse bibliographyLink element."""
        bib = self.root.find('bibliographyLink')
        if bib is None:
            return None
        
        ref = Reference(
            description=self._get_text_from_element(bib, 'description') or '',
            doi=self._get_text_from_element(bib, 'referenceDOI'),
            location=self._get_text_from_element(bib, 'location'),
            table=self._get_text_from_element(bib, 'table'),
            figure=self._get_text_from_element(bib, 'figure'),
        )
        
        # Parse details if present
        details = bib.find('details')
        if details is not None:
            ref.journal = self._get_text_from_element(details, 'journal')
            ref.volume = self._get_text_from_element(details, 'volume')
            ref.pages = self._get_text_from_element(details, 'pages')
            ref.title = self._get_text_from_element(details, 'title')
            
            year_text = self._get_text_from_element(details, 'year')
            if year_text:
                try:
                    ref.year = int(year_text)
                except ValueError:
                    pass
            
            # Parse authors
            author_text = self._get_text_from_element(details, 'author')
            if author_text:
                # Authors are often in format "Last, First and Last, First"
                ref.authors = self._parse_author_string(author_text)
        
        return ref
    
    def _parse_author_string(self, author_text: str):
        """Parse author string into list of Author objects."""
        authors = []
        # Split by " and " to separate authors
        author_parts = re.split(r'\s+and\s+', author_text)
        for part in author_parts:
            name = part.strip()
            if name:
                authors.append(Author(name=name))
        return authors
    
    def _parse_reaction(self):
        """Parse reaction element."""
        rxn = self.root.find('reaction')
        if rxn is None:
            return None
        
        reaction = Reaction(
            preferred_key=rxn.get('preferredKey', ''),
            bulk_gas=rxn.get('bulkgas'),
        )
        
        # Parse order
        order_str = rxn.get('order')
        if order_str:
            try:
                reaction.order = int(order_str)
            except ValueError:
                pass
        
        # Parse reactants (reactant1, reactant2, etc.)
        for i in range(1, 10):
            reactant = self._get_text_from_element(rxn, f'reactant{i}')
            if reactant:
                reaction.reactants.append(reactant)
            else:
                break
        
        # Parse products (product1, product2, etc.)
        for i in range(1, 10):
            product = self._get_text_from_element(rxn, f'product{i}')
            if product:
                reaction.products.append(product)
            else:
                break
        
        return reaction
    
    def _parse_common_properties(self):
        """Parse commonProperties element."""
        common_props = []
        common = self.root.find('commonProperties')
        if common is None:
            return common_props
        
        for prop in common.findall('property'):
            cp = CommonProperty(
                name=prop.get('name', ''),
                value=None,
                units=prop.get('units'),
                source_type=prop.get('sourcetype'),
                label=prop.get('label'),
                reference=prop.get('reference'),
                kind=prop.get('kind'),
            )
            
            # Get value from child element
            value_elem = prop.find('value')
            if value_elem is not None and value_elem.text:
                cp.value = self._parse_value(value_elem.text.strip())
            
            common_props.append(cp)
        
        return common_props
    
    def _parse_initial_composition(self):
        """Parse initial composition from commonProperties."""
        composition = []
        common = self.root.find('commonProperties')
        if common is None:
            return composition
        
        for prop in common.findall('property'):
            prop_name = prop.get('name', '').lower()
            if 'composition' in prop_name or 'initial composition' in prop_name:
                # Parse each component
                for component in prop.findall('component'):
                    species_link = component.find('speciesLink')
                    amount_elem = component.find('amount')
                    
                    if species_link is not None and amount_elem is not None:
                        try:
                            amount_val = float(amount_elem.text.strip())
                        except (ValueError, TypeError):
                            continue
                        
                        comp = CompositionComponent(
                            species_name=species_link.get('preferredKey', ''),
                            amount=amount_val,
                            amount_units=amount_elem.get('units', 'mole fraction'),
                            cas=species_link.get('CAS'),
                            inchi=species_link.get('InChI'),
                            smiles=species_link.get('SMILES'),
                        )
                        composition.append(comp)
        
        return composition
    
    def _parse_uncertainties(self):
        """Parse evaluated standard deviation entries from commonProperties."""
        uncertainties = []
        common = self.root.find('commonProperties')
        if common is None:
            return uncertainties
        
        for prop in common.findall('property'):
            prop_name = prop.get('name', '').lower()
            if 'standard deviation' in prop_name or 'uncertainty' in prop_name:
                species_link = prop.find('speciesLink')
                value_elem = prop.find('value')
                
                if species_link is not None and value_elem is not None:
                    try:
                        unc_val = float(value_elem.text.strip())
                    except (ValueError, TypeError):
                        continue
                    
                    unc = UncertaintyData(
                        species_name=species_link.get('preferredKey', ''),
                        value=unc_val,
                        units=prop.get('units', 'mole fraction'),
                        kind=prop.get('kind', 'absolute'),
                        method=prop.get('method', ''),
                        source_type=prop.get('sourcetype', ''),
                    )
                    uncertainties.append(unc)
        
        return uncertainties
    
    def _parse_data_group(self):
        """Parse dataGroup element."""
        properties = []
        datapoints = []
        
        dg = self.root.find('dataGroup')
        if dg is None:
            return properties, datapoints
        
        # Parse property definitions
        prop_map = {}  # id -> DataProperty
        for prop in dg.findall('property'):
            dp = DataProperty(
                name=prop.get('name', ''),
                id=prop.get('id', ''),
                label=prop.get('label'),
                source_type=prop.get('sourcetype'),
                units=prop.get('units'),
            )
            
            # Check for speciesLink
            species_link = prop.find('speciesLink')
            if species_link is not None:
                dp.species_link = Species(
                    preferred_key=species_link.get('preferredKey', ''),
                    cas=species_link.get('CAS'),
                    inchi=species_link.get('InChI'),
                    smiles=species_link.get('SMILES'),
                    chem_name=species_link.get('chemName'),
                )
            
            properties.append(dp)
            prop_map[dp.id] = dp
        
        # Parse datapoints
        for dp_elem in dg.findall('dataPoint'):
            dp = DataPoint()
            
            # Parse each value element (x1, x2, etc.)
            for child in dp_elem:
                prop_id = child.tag
                if child.text:
                    value = self._parse_value(child.text.strip())
                    dp.values[prop_id] = value
            
            datapoints.append(dp)
        
        return properties, datapoints
    
    def _parse_value(self, text: str):
        """Parse a value string to appropriate type."""
        if not text:
            return None
        
        # Try to parse as number
        try:
            # Handle scientific notation
            if 'e' in text.lower() or 'E' in text:
                return float(text)
            elif '.' in text:
                return float(text)
            else:
                return int(text)
        except ValueError:
            return text


def parse_respecth_v2(xml_file: str):
    """
    Convenience function to parse a ReSpecTh v2.x XML file.
    
    Args:
        xml_file: Path to the XML file
        
    Returns:
        ReSpecThV2Data object with parsed content
    """
    parser = ReSpecThV2Parser(xml_file)
    return parser.parse()


def respecth_v2_to_dict(xml_file: str):
    """
    Parse ReSpecTh v2.x file and return as dictionary.
    
    This is useful for JSON serialization or database storage.
    
    Args:
        xml_file: Path to the XML file
        
    Returns:
        Dictionary representation of the parsed data
    """
    data = parse_respecth_v2(xml_file)
    
    result = {
        'file_type': data.file_type,
        'file_author': data.file_author,
        'file_doi': data.file_doi,
        'file_version': data.file_version,
        'respecth_version': data.respecth_version,
        'first_publication_date': data.first_publication_date,
        'last_modification_date': data.last_modification_date,
        'method': data.method,
        'experiment_type': data.experiment_type,
        'apparatus_kind': data.apparatus_kind,
    }
    
    # Reference
    if data.reference:
        result['reference'] = {
            'description': data.reference.description,
            'doi': data.reference.doi,
            'journal': data.reference.journal,
            'volume': data.reference.volume,
            'pages': data.reference.pages,
            'year': data.reference.year,
            'title': data.reference.title,
            'location': data.reference.location,
            'table': data.reference.table,
            'figure': data.reference.figure,
            'authors': [{'name': a.name, 'orcid': a.orcid} for a in data.reference.authors],
        }
    
    # Reaction
    if data.reaction:
        result['reaction'] = {
            'preferred_key': data.reaction.preferred_key,
            'order': data.reaction.order,
            'bulk_gas': data.reaction.bulk_gas,
            'reactants': data.reaction.reactants,
            'products': data.reaction.products,
        }
    
    # Common properties
    result['common_properties'] = [
        {
            'name': cp.name,
            'value': cp.value,
            'units': cp.units,
            'source_type': cp.source_type,
            'label': cp.label,
            'reference': cp.reference,
            'kind': cp.kind,
        }
        for cp in data.common_properties
    ]
    
    # Data properties (column definitions)
    result['data_properties'] = []
    for dp in data.data_properties:
        prop_dict = {
            'name': dp.name,
            'id': dp.id,
            'label': dp.label,
            'source_type': dp.source_type,
            'units': dp.units,
        }
        if dp.species_link:
            prop_dict['species_link'] = {
                'preferred_key': dp.species_link.preferred_key,
                'cas': dp.species_link.cas,
                'inchi': dp.species_link.inchi,
                'smiles': dp.species_link.smiles,
                'chem_name': dp.species_link.chem_name,
            }
        result['data_properties'].append(prop_dict)
    
    # Datapoints
    result['datapoints'] = [dp.values for dp in data.datapoints]
    
    return result
