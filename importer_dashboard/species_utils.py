"""
Utility functions for species identification
"""

import re
import json
import logging
from typing import Dict, List, Tuple, Optional
from django.utils import timezone
from .models import (
    Species, CandidateSpecies, Vote, ThermoMatch, 
    BlockedMatch, ClusterJob
)

logger = logging.getLogger(__name__)


def parse_progress_json(progress_data: Dict) -> Dict:
    """
    Parse progress.json from importChemkin.py
    
    Expected format:
    {
        'processed': 40,
        'unprocessed': 0,
        'confirmed': 40,
        'tentative': 5,
        'unidentified': 5,
        'unconfirmed': 10,
        'total': 50,
        'unmatchedreactions': 120,
        'totalreactions': 500,
        'thermomatches': 3
    }
    """
    return {
        'total_species': progress_data.get('total', 0),
        'identified_species': progress_data.get('confirmed', 0),
        'processed_species': progress_data.get('processed', 0),
        'tentative_species': progress_data.get('tentative', 0),
        'unidentified_species': progress_data.get('unidentified', 0),
        'total_reactions': progress_data.get('totalreactions', 0),
        'unmatched_reactions': progress_data.get('unmatchedreactions', 0),
        'thermo_matches': progress_data.get('thermomatches', 0),
    }


def parse_species_from_smiles_file(smiles_file_content: str) -> List[Dict]:
    """
    Parse SMILES.txt file containing identified species
    
    Format:
    LABEL    SMILES    ! Confirmed by Username
    CH4      C         ! Confirmed by auto
    CH3      [CH3]     ! Confirmed by user1
    """
    species_list = []
    
    for line in smiles_file_content.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        
        # Split on whitespace and comments
        if '!' in line:
            parts, comment = line.split('!', 1)
            # Extract username
            user_match = re.search(r'Confirmed by ([^\.]+)', comment)
            identified_by = user_match.group(1).strip() if user_match else None
        else:
            parts = line
            identified_by = None
        
        tokens = parts.split()
        if len(tokens) >= 2:
            species_list.append({
                'chemkin_label': tokens[0],
                'smiles': tokens[1],
                'identified_by': identified_by,
                'identification_method': 'auto' if identified_by == 'auto' else 'manual'
            })
    
    return species_list


def parse_blocked_matches_file(blocked_file_content: str) -> List[Dict]:
    """
    Parse BLOCKED.txt file containing blocked matches
    
    Format:
    LABEL    SMILES    ! Blocked by Username
    """
    blocked_list = []
    
    for line in blocked_file_content.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        
        if '!' in line:
            parts, comment = line.split('!', 1)
            user_match = re.search(r'Blocked by ([^\.]+)', comment)
            blocked_by = user_match.group(1).strip() if user_match else None
        else:
            parts = line
            blocked_by = None
        
        tokens = parts.split()
        if len(tokens) >= 2:
            blocked_list.append({
                'chemkin_label': tokens[0],
                'smiles': tokens[1],
                'blocked_by': blocked_by,
            })
    
    return blocked_list


def parse_formula_from_thermo(thermo_content: str) -> Dict[str, str]:
    """
    Parse chemical formulas from Chemkin thermo file
    
    Returns dict mapping label -> formula (e.g., {'CH4': 'CH4', 'CH3': 'CH3'})
    """
    formulas = {}
    
    # Parse thermo entries (simplified - real parser would use RMG)
    # This is a placeholder that should be replaced with actual parsing
    lines = thermo_content.split('\n')
    
    for line in lines:
        # Skip comments and blank lines
        if line.strip().startswith('!') or not line.strip():
            continue
        
        # Thermo entry format: LABEL followed by formula info
        # This is simplified - actual implementation needs proper parsing
        if len(line) >= 24:
            label = line[:18].strip()
            if label:
                # Extract formula from positions 24-44 (simplified)
                formula_part = line[24:44] if len(line) > 44 else ''
                formulas[label] = label  # Placeholder
    
    return formulas


def calculate_confidence_score(
    vote_count: int,
    unique_votes: int,
    enthalpy_diff: float,
    thermo_matches: int
) -> float:
    """
    Calculate confidence score for a species match
    
    Args:
        vote_count: Total number of voting reactions
        unique_votes: Number of unique (non-common) votes
        enthalpy_diff: Enthalpy discrepancy in kJ/mol
        thermo_matches: Number of thermo library matches
    
    Returns:
        Confidence score from 0-100
    """
    score = 0.0
    
    # Vote contribution (max 50 points)
    score += min(unique_votes * 5, 50)
    
    # Enthalpy contribution (max 30 points)
    abs_diff = abs(enthalpy_diff)
    if abs_diff < 10:
        score += 30
    elif abs_diff < 50:
        score += 20
    elif abs_diff < 100:
        score += 10
    elif abs_diff < 150:
        score += 5
    
    # Thermo library match contribution (max 20 points)
    score += min(thermo_matches * 10, 20)
    
    return min(score, 100.0)


def should_auto_confirm(
    vote_count: int,
    unique_votes: int,
    enthalpy_diff: float,
    thermo_matches: int,
    is_only_candidate: bool = False,
    name_matches: bool = False
) -> bool:
    """
    Determine if a match should be automatically confirmed
    
    Criteria:
    - Only candidate with >3 unique votes
    - Confidence score > 70
    - Enthalpy difference < 100 kJ/mol
    - At least 2 thermo library matches with matching names
    """
    # Must have some evidence
    if vote_count == 0:
        return False
    
    # Must have reasonable enthalpy
    if abs(enthalpy_diff) > 100:
        return False
    
    # High confidence with unique candidate
    if is_only_candidate and unique_votes >= 3:
        confidence = calculate_confidence_score(
            vote_count, unique_votes, enthalpy_diff, thermo_matches
        )
        if confidence >= 70:
            return True
    
    # Strong thermo evidence
    if thermo_matches >= 2 and name_matches:
        return True
    
    return False


def prune_common_votes(species: Species) -> None:
    """
    Remove non-discriminating votes that are common to all candidates
    
    This implements the pruning logic from importChemkin.py
    """
    candidates = species.candidates.all()
    
    if len(candidates) <= 1:
        # Nothing to prune
        return
    
    # Get all votes for each candidate
    candidate_votes = {}
    for candidate in candidates:
        votes = Vote.objects.filter(
            species=species,
            candidate=candidate
        )
        candidate_votes[candidate.id] = set(
            v.chemkin_reaction for v in votes
        )
    
    # Find common reactions
    if candidate_votes:
        common_reactions = set.intersection(*candidate_votes.values())
        
        if common_reactions:
            # Mark common votes as not unique
            Vote.objects.filter(
                species=species,
                chemkin_reaction__in=common_reactions
            ).update(is_unique=False)
            
            # Update unique vote counts
            for candidate in candidates:
                unique_count = Vote.objects.filter(
                    species=species,
                    candidate=candidate,
                    is_unique=True
                ).count()
                candidate.unique_vote_count = unique_count
                candidate.save()


def get_species_image_url(smiles: str, size: int = 200) -> str:
    """
    Generate URL for species structure image
    
    Could use:
    - Local RMG-generated images
    - ChemDoodle API
    - PubChem image service
    - Custom rendering service
    """
    # For now, use PubChem's chemical structure service
    # This requires the SMILES to be URL-encoded
    import urllib.parse
    encoded_smiles = urllib.parse.quote(smiles)
    return f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/smiles/{encoded_smiles}/PNG?image_size={size}x{size}"


def format_reaction_string(reaction_str: str, identified_labels: List[str]) -> str:
    """
    Format reaction string with HTML highlighting for identified/unidentified species
    
    Args:
        reaction_str: Reaction string like "CH3+H<=>CH4"
        identified_labels: List of already identified species labels
    
    Returns:
        HTML formatted string
    """
    # Split on reaction arrows and operators
    parts = re.split(r'(\s*[+<=>\s]+\s*)', reaction_str)
    
    formatted = []
    for part in parts:
        part = part.strip()
        if not part or part in ['+', '<=>', '=>', '<=>']:
            formatted.append(f' {part} ')
        elif part in identified_labels:
            formatted.append(f'<span class="species-identified">{part}</span>')
        else:
            formatted.append(f'<span class="species-unidentified">{part}</span>')
    
    return ''.join(formatted)


def sync_species_from_job(job: ClusterJob, ssh_manager) -> Dict[str, int]:
    """
    Sync species data from cluster job files
    
    Returns:
        Dict with counts of created/updated species
    """
    stats = {
        'species_created': 0,
        'species_updated': 0,
        'votes_created': 0,
        'candidates_created': 0,
        'errors': []
    }
    
    try:
        # This would fetch files from cluster and parse them
        # Implementation depends on SSH manager interface
        pass
    except Exception as e:
        logger.error(f"Error syncing species for job {job.id}: {e}")
        stats['errors'].append(str(e))
    
    return stats


def export_smiles_file(job: ClusterJob) -> str:
    """
    Export confirmed species identifications to SMILES.txt format
    
    Returns:
        String content of SMILES.txt file
    """
    lines = ["# Species identifications for " + job.name]
    lines.append("# Generated by KMS Importer Dashboard")
    lines.append("# Format: LABEL    SMILES    ! Confirmed by User")
    lines.append("")
    
    species = Species.objects.filter(
        job=job,
        identification_status__in=['confirmed', 'processed']
    ).order_by('chemkin_label')
    
    for sp in species:
        username = sp.identified_by.username if sp.identified_by else 'auto'
        line = f"{sp.chemkin_label}\t{sp.smiles}\t! Confirmed by {username}"
        lines.append(line)
    
    return '\n'.join(lines)


def export_blocked_file(job: ClusterJob) -> str:
    """
    Export blocked matches to BLOCKED.txt format
    
    Returns:
        String content of blocked matches file
    """
    lines = ["# Blocked species matches for " + job.name]
    lines.append("# Generated by KMS Importer Dashboard")
    lines.append("# Format: LABEL    SMILES    ! Blocked by User")
    lines.append("")
    
    blocked = BlockedMatch.objects.filter(job=job).order_by('chemkin_label')
    
    for match in blocked:
        username = match.blocked_by.username if match.blocked_by else 'system'
        line = f"{match.chemkin_label}\t{match.smiles}\t! Blocked by {username}"
        if match.reason:
            line += f" - {match.reason}"
        lines.append(line)
    
    return '\n'.join(lines)


def sync_species_from_cluster(job: ClusterJob, ssh_manager=None) -> Dict:
    """
    Sync species data from cluster job to Django database
    
    Fetches detailed species/candidate/vote data from importChemkin.py's web interface
    and populates the Species, CandidateSpecies, and Vote models.
    
    This should be called:
    - When job starts running
    - When interactive session connects
    - Periodically (every 60 seconds) for running jobs
    
    Returns:
        Dict with sync statistics: {
            'species_synced': int,
            'candidates_synced': int,
            'votes_synced': int,
            'success': bool,
            'message': str
        }
    """
    from .ssh_manager import SSHJobManager
    from .models import ImportJobConfig, Species, CandidateSpecies, Vote, ThermoMatch
    from django.db import transaction
    import urllib.request
    import urllib.error
    import re
    
    result = {
        'species_synced': 0,
        'candidates_synced': 0,
        'votes_synced': 0,
        'success': False,
        'message': ''
    }
    
    try:
        # Get SSH manager if not provided
        if not ssh_manager:
            config = job.config or ImportJobConfig.objects.filter(is_default=True).first()
            if not config:
                result['message'] = 'No configuration found'
                return result
            ssh_manager = SSHJobManager(config=config)
        
        # For completed/failed jobs, skip progress.json and go straight to file sync
        if job.status in ['completed', 'failed', 'cancelled']:
            logger.info(f"Job {job.id} is {job.status}, using file-based sync only")
            from .file_sync import sync_species_from_files
            return sync_species_from_files(job)
        
        # First, update job-level statistics from progress.json (for running jobs)
        progress = ssh_manager.get_progress_json(job)
        
        if not progress:
            # If we can't get progress but job appears to be running,
            # try file-based sync as fallback
            logger.warning(f"Could not fetch progress.json for job {job.id}, trying file sync")
            from .file_sync import sync_species_from_files
            return sync_species_from_files(job)
        
        # Update job stats
        job.total_species = progress.get('total', 0)
        job.identified_species = progress.get('confirmed', 0)
        job.processed_species = progress.get('processed', 0)
        job.confirmed_species = progress.get('confirmed', 0)
        job.total_reactions = progress.get('totalreactions', 0)
        job.unmatched_reactions = progress.get('unmatchedreactions', 0)
        job.save()
        
        # Calculate unidentified species count
        unidentified_count = job.total_species - job.identified_species
        
        # Try API-based sync first (if job is running)
        # If that fails, fall back to file-based sync
        votes_data = None
        sync_method = None
        
        # Fetch detailed voting data from votes_api.json endpoint
        try:
            url = f'http://localhost:{job.port}/votes_api.json'
            logger.info(f"Attempting API sync from {url}")
            
            with urllib.request.urlopen(url, timeout=10) as response:
                votes_data = json.loads(response.read().decode('utf-8'))
            
            sync_method = 'api'
            logger.info(f"✅ API sync successful: {len(votes_data.get('species', []))} species")
            
            # Process the voting data
            with transaction.atomic():
                # Process unidentified and tentative species
                for species_info in votes_data.get('species', []):
                    ck_label = species_info['chemkin_label']
                    formula = species_info.get('formula', ck_label)
                    status = species_info.get('status', 'unidentified')
                    
                    # Create or update Species
                    species, created = Species.objects.get_or_create(
                        job=job,
                        chemkin_label=ck_label,
                        defaults={
                            'formula': formula,
                            'identification_status': status
                        }
                    )
                    
                    if created:
                        result['species_synced'] += 1
                    else:
                        # Update status if changed
                        if species.identification_status != status:
                            species.identification_status = status
                            species.save()
                    
                    # Process candidates
                    for candidate_info in species_info.get('candidates', []):
                        smiles = candidate_info.get('smiles', '')
                        if not smiles:
                            continue
                        
                        # Determine label source (if label matches chemkin label, it's from chemkin)
                        rmg_label = candidate_info.get('label', smiles)
                        label_source = 'chemkin' if rmg_label.upper() == ck_label.upper() else 'rmg'
                        
                        # Get enthalpy discrepancy - could be in different keys
                        enthalpy_disc = candidate_info.get('enthalpy_discrepancy')
                        if enthalpy_disc is None:
                            enthalpy_disc = candidate_info.get('delta_H')
                        if enthalpy_disc is None:
                            enthalpy_disc = candidate_info.get('H_discrepancy')
                        
                        # Create or update CandidateSpecies
                        candidate, created = CandidateSpecies.objects.get_or_create(
                            species=species,
                            smiles=smiles,
                            defaults={
                                'rmg_label': rmg_label,
                                'label_source': label_source,
                                'enthalpy_discrepancy': enthalpy_disc,
                                'vote_count': candidate_info.get('vote_count', 0),
                                'unique_vote_count': candidate_info.get('unique_vote_count', 0)
                            }
                        )
                        
                        if created:
                            result['candidates_synced'] += 1
                        else:
                            # Update vote counts and enthalpy
                            candidate.vote_count = candidate_info.get('vote_count', 0)
                            candidate.unique_vote_count = candidate_info.get('unique_vote_count', 0)
                            candidate.label_source = label_source
                            if enthalpy_disc is not None:
                                candidate.enthalpy_discrepancy = enthalpy_disc
                            candidate.save()
                        
                        # Process thermo matches
                        for thermo_info in candidate_info.get('thermo_matches', []):
                            library_name = thermo_info.get('library', '')
                            library_species_name = thermo_info.get('species_name', '')
                            name_matches = thermo_info.get('name_matches', False)
                            
                            if library_name and library_species_name:
                                ThermoMatch.objects.get_or_create(
                                    species=species,
                                    candidate=candidate,
                                    library_name=library_name,
                                    defaults={
                                        'library_species_name': library_species_name,
                                        'name_matches': name_matches
                                    }
                                )
                        
                        # Process votes
                        # Clear old votes for this candidate to avoid duplicates
                        Vote.objects.filter(species=species, candidate=candidate).delete()
                        
                        for vote_info in candidate_info.get('votes', []):
                            vote, created = Vote.objects.get_or_create(
                                species=species,
                                candidate=candidate,
                                chemkin_reaction=vote_info.get('chemkin_reaction', ''),
                                defaults={
                                    'rmg_reaction': vote_info.get('rmg_reaction', ''),
                                    'rmg_reaction_family': vote_info.get('family', ''),
                                    'is_unique': vote_info.get('is_unique', False)
                                }
                            )
                            
                            if created:
                                result['votes_synced'] += 1
                
                # Process identified species
                for identified_info in votes_data.get('identified', []):
                    ck_label = identified_info['chemkin_label']
                    formula = identified_info.get('formula', ck_label)
                    smiles = identified_info.get('smiles', '')
                    
                    # Create or update Species as confirmed
                    species, created = Species.objects.get_or_create(
                        job=job,
                        chemkin_label=ck_label,
                        defaults={
                            'formula': formula,
                            'identification_status': 'confirmed'
                        }
                    )
                    
                    if created:
                        result['species_synced'] += 1
                    else:
                        species.identification_status = 'confirmed'
                        species.save()
                    
                    # Create confirmed candidate
                    if smiles:
                        rmg_index = identified_info.get('rmg_index')
                        
                        # Build the lookup and defaults
                        lookup = {'species': species, 'smiles': smiles}
                        defaults = {
                            'rmg_label': identified_info.get('rmg_label', smiles),
                            'is_confirmed': True,
                            'vote_count': 0,
                            'unique_vote_count': 0,
                            'enthalpy_discrepancy': identified_info.get('enthalpy_discrepancy', 0.0)
                        }
                        
                        # Add rmg_index if available
                        if rmg_index is not None:
                            lookup['rmg_index'] = rmg_index
                            defaults['rmg_index'] = rmg_index
                        
                        CandidateSpecies.objects.get_or_create(**lookup, defaults=defaults)
                        result['candidates_synced'] += 1
                
                # Process blocked matches
                for blocked_info in votes_data.get('blocked', []):
                    ck_label = blocked_info['chemkin_label']
                    smiles = blocked_info.get('smiles', '')
                    
                    # Find the species
                    try:
                        species = Species.objects.get(job=job, chemkin_label=ck_label)
                        
                        # Find or create the candidate and mark as blocked
                        if smiles:
                            candidate = CandidateSpecies.objects.filter(
                                species=species,
                                smiles=smiles
                            ).first()
                            
                            if candidate:
                                candidate.is_blocked = True
                                candidate.save()
                    except Species.DoesNotExist:
                        pass
            
            result['success'] = True
            result['message'] = (
                f'Synced {result["species_synced"]} species, '
                f'{result["candidates_synced"]} candidates, '
                f'{result["votes_synced"]} votes from importChemkin.py'
            )
            logger.info(f"Successfully synced detailed data for job {job.id}: {result['message']}")
            
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            # API not available - try multiple fallback strategies
            logger.warning(f"API sync failed ({e}), trying fallback strategies")
            
            # Strategy 1: Try to sync from votes database first (has vote details!)
            try:
                from .vote_reader import sync_votes_to_django
                
                vote_result = sync_votes_to_django(job, ssh_manager)
                
                if vote_result['success']:
                    sync_method = 'votes_db'
                    result['success'] = True
                    stats = vote_result.get('statistics', {})
                    result['species_synced'] = stats.get('total_species_with_votes', 0)
                    result['candidates_synced'] = stats.get('total_candidates', 0)
                    result['votes_synced'] = stats.get('total_votes', 0)
                    result['message'] = (
                        f"✅ Votes DB sync: {stats.get('total_species_with_votes', 0)} species, "
                        f"{stats.get('total_candidates', 0)} candidates, "
                        f"{stats.get('total_votes', 0)} votes. "
                        f"[{stats.get('identified_count', 0)} identified, "
                        f"{stats.get('blocked_count', 0)} blocked]"
                    )
                    logger.info(f"Successfully synced from votes database: {result['message']}")
                    return result  # Success! Return early
                    
            except Exception as vote_error:
                logger.warning(f"Votes DB sync failed: {vote_error}")
            
            # Strategy 2: Fall back to file-based sync (species labels only)
            try:
                from .file_sync import sync_species_from_files
                
                file_result = sync_species_from_files(job)
                
                if file_result['success']:
                    sync_method = 'files'
                    result['success'] = True
                    result['species_synced'] = file_result['species_synced']
                    result['message'] = (
                        f"✅ File-based sync: {file_result['species_synced']} unidentified species, "
                        f"{file_result['identified_synced']} identified species. "
                        f"⚠ Voting details not available (use votes DB for full data)."
                    )
                    logger.info(f"Successfully synced from files: {result['message']}")
                else:
                    result['success'] = True
                    result['message'] = (
                        f'Updated job statistics: {job.total_species} species '
                        f'({job.identified_species} identified, {unidentified_count} remaining). '
                        f'Could not sync detailed data: {file_result.get("message", "unknown error")}'
                    )
                    logger.warning(f"File sync also failed: {file_result.get('message')}")
                    
            except Exception as file_error:
                result['success'] = True
                result['message'] = (
                    f'Updated job statistics only: {job.total_species} species '
                    f'({job.identified_species} identified, {unidentified_count} remaining). '
                    f'All sync strategies failed (API, votes DB, files).'
                )
                logger.error(f"All sync strategies failed: {file_error}", exc_info=True)
        
        except Exception as e:
            result['success'] = False
            result['message'] = f'Error syncing species data: {str(e)}'
            logger.error(f"Failed to sync species for job {job.id}: {e}", exc_info=True)
        
    except Exception as e:
        result['message'] = f'Error syncing species data: {str(e)}'
        logger.error(f"Failed to sync species for job {job.id}: {e}", exc_info=True)
    
    return result
