"""
File-based species synchronization for importer_dashboard

This module provides functions to sync species data by parsing the original
Chemkin files (Thermo.dat, SpRxn.dat, SMILES.txt) directly from the cluster,
the same way importChemkin.py processes them.

This approach is more reliable than the API-based sync because:
- Works even when importChemkin.py job is not running
- Works for completed/crashed jobs  
- Source files persist after job completes
- Uses the same data source as CherryPy dashboard
"""

import logging
import re
from django.db import transaction

from .models import ClusterJob, Species, CandidateSpecies, Vote

logger = logging.getLogger(__name__)


def parse_smiles_file(ssh_manager, job_path):
    """
    Parse SMILES.txt to get identified species
    
    Format:
        CHEMKIN_LABEL    SMILES_STRING
        C2H2    C#C
        CH4     C
        ! Deleted by User: OH [OH]
    
    Returns:
        dict: {chemkin_label: smiles}
    """
    identified = {}
    
    cmd = f'cat {job_path}/SMILES.txt 2>/dev/null'
    stdout, stderr = ssh_manager.exec_command(cmd)
    
    if not stdout:
        logger.warning(f"SMILES.txt not found or empty at {job_path}")
        return identified
    
    for line in stdout.splitlines():
        line = line.strip()
        
        # Skip comments and deleted entries
        if not line or line.startswith('!'):
            continue
        
        # Parse "LABEL    SMILES"
        parts = line.split(None, 1)  # Split on whitespace, max 2 parts
        if len(parts) == 2:
            label, smiles = parts
            identified[label] = smiles
    
    logger.info(f"Parsed {len(identified)} identified species from SMILES.txt")
    return identified


def parse_thermo_file(ssh_manager, job_path):
    """
    Parse Thermo.dat to get all species
    
    Returns:
        dict: {chemkin_label: {'formula': str}}
    """
    all_species = {}
    
    cmd = f'cat {job_path}/Thermo.dat 2>/dev/null'
    stdout, stderr = ssh_manager.exec_command(cmd)
    
    if not stdout:
        logger.warning(f"Thermo.dat not found at {job_path}")
        return all_species
    
    # Chemkin thermo format:
    # LABEL     DATE  FORMULA  0 G  300.000  5000.000 1000.000    1
    # Lines with thermodynamic data follow
    
    in_data_section = False
    for line in stdout.splitlines():
        line_stripped = line.strip()
        
        # Start of data section (after THERMO header)
        if line_stripped.startswith('THERMO'):
            in_data_section = True
            continue
        
        # End of data section
        if line_stripped.startswith('END'):
            break
        
        if not in_data_section:
            continue
        
        # Skip empty lines and comments
        if not line_stripped or line_stripped.startswith('!'):
            continue
        
        # Species entry (first line of each species block)
        # Format: LABEL (spaces) DATE FORMULA G TLOW THIGH TCOMMON 1
        # The thermodynamic data follows on subsequent lines (4 lines total per species)
        if len(line) >= 18 and not line[0].isspace():
            label = line[:18].strip()
            
            # Skip entries that are obviously not species names
            # (numbers, empty, or thermodynamic coefficients)
            if not label:
                continue
            if label[0].isdigit() or label.startswith('-') or label.startswith('+'):
                continue
            if 'E+' in label or 'E-' in label:  # Scientific notation
                continue
            
            # Extract formula (appears after the date field)
            # Typical format: C2H2    121286C  2H  2    0    0G  300.000  5000.000 1000.000    1
            formula_match = re.search(r'([A-Z][a-z]?\s*\d*)+', line[24:44])
            if formula_match:
                formula = formula_match.group().replace(' ', '')
            else:
                formula = ''
            
            all_species[label] = {
                'formula': formula
            }
    
    logger.info(f"Parsed {len(all_species)} species from Thermo.dat")
    return all_species


def sync_species_from_files(job):
    """
    Sync species data by parsing Chemkin files directly
    
    This reads:
    - Thermo.dat: All species (identified + unidentified)  
    - SMILES.txt: Identified species
    - Calculates unidentified = all - identified
    
    Args:
        job: ClusterJob instance
        
    Returns:
        dict: Sync result with counts
    """
    from .ssh_manager import SSHJobManager
    from .models import ImportJobConfig
    
    result = {
        'success': False,
        'message': '',
        'species_synced': 0,
        'identified_synced': 0,
        'unidentified_found': 0
    }
    
    try:
        # Get SSH connection
        config = job.config or ImportJobConfig.objects.filter(is_default=True).first()
        if not config:
            result['message'] = 'No configuration found'
            return result
        
        ssh_manager = SSHJobManager(config=config)
        ssh_manager.connect()
        
        job_path = f'{config.root_path}/{job.name}'
        logger.info(f"Syncing species from files in {job_path}")
        
        # Parse files
        identified_species = parse_smiles_file(ssh_manager, job_path)
        all_species = parse_thermo_file(ssh_manager, job_path)
        
        ssh_manager.disconnect()
        
        if not all_species:
            result['message'] = 'No species found in Thermo.dat'
            return result
        
        # Calculate unidentified species
        unidentified_labels = set(all_species.keys()) - set(identified_species.keys())
        
        logger.info(f"Found {len(all_species)} total species")
        logger.info(f"Found {len(identified_species)} identified species")
        logger.info(f"Found {len(unidentified_labels)} unidentified species")
        
        # Sync to database
        with transaction.atomic():
            # Create Species records for unidentified species
            for label in unidentified_labels:
                species_info = all_species[label]
                
                species, created = Species.objects.get_or_create(
                    job=job,
                    chemkin_label=label,
                    defaults={
                        'formula': species_info.get('formula', ''),
                        'identification_status': 'unidentified'
                    }
                )
                
                if created:
                    result['species_synced'] += 1
            
            # Mark identified species (these won't have candidate/vote data from files)
            for label, smiles in identified_species.items():
                species, created = Species.objects.get_or_create(
                    job=job,
                    chemkin_label=label,
                    defaults={
                        'formula': all_species.get(label, {}).get('formula', ''),
                        'identification_status': 'identified'
                    }
                )
                
                if not created:
                    species.identification_status = 'identified'
                    species.save()
                
                result['identified_synced'] += 1
        
        result['success'] = True
        result['unidentified_found'] = len(unidentified_labels)
        result['message'] = (
            f"Synced {result['species_synced']} unidentified species "
            f"and {result['identified_synced']} identified species from files"
        )
        
        logger.info(result['message'])
        return result
        
    except Exception as e:
        logger.error(f"Error syncing from files: {e}", exc_info=True)
        result['message'] = f"Error: {str(e)}"
        return result


def get_species_list_from_files(job):
    """
    Get a simple list of unidentified species by parsing files
    
    This is a lightweight version that just returns species names
    without creating database records.
    
    Returns:
        list: [{'label': str, 'formula': str}, ...]
    """
    from .ssh_manager import SSHJobManager
    from .models import ImportJobConfig
    
    try:
        config = job.config or ImportJobConfig.objects.filter(is_default=True).first()
        if not config:
            return []
        
        ssh_manager = SSHJobManager(config=config)
        ssh_manager.connect()
        
        job_path = f'{config.root_path}/{job.name}'
        
        identified_species = parse_smiles_file(ssh_manager, job_path)
        all_species = parse_thermo_file(ssh_manager, job_path)
        
        ssh_manager.disconnect()
        
        unidentified_labels = set(all_species.keys()) - set(identified_species.keys())
        
        return [
            {
                'label': label,
                'formula': all_species[label].get('formula', '')
            }
            for label in sorted(unidentified_labels)
        ]
        
    except Exception as e:
        logger.error(f"Error getting species list: {e}")
        return []
