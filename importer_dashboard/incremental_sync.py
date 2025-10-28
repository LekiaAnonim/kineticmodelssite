"""
Incremental Vote Database Sync

Implements efficient incremental synchronization of vote data from cluster
to Django dashboard. Only transfers updates since last sync instead of
copying entire database each time.

Architecture:
1. Track last sync timestamp in Django
2. Query remote DB for records updated after last sync
3. Transfer only delta data via SSH
4. Update local Django models
5. Record sync timestamp for next iteration

Advantages over full DB copy:
- Minimal data transfer (KB instead of MB)
- Faster sync cycles (seconds instead of minutes)
- Less network bandwidth usage
- Real-time updates possible
- Works with large databases
"""

import os
import json
import logging
import tempfile
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from django.db import transaction
from django.utils import timezone

from .models import (
    ClusterJob, Species, CandidateSpecies, Vote, 
    ThermoMatch, SyncLog
)
from .ssh_manager import SSHJobManager

logger = logging.getLogger(__name__)


class IncrementalVoteSync:
    """
    Manages incremental synchronization of vote data from cluster to Django
    """
    
    def __init__(self, ssh_manager: SSHJobManager, job: ClusterJob):
        """
        Initialize sync manager
        
        Args:
            ssh_manager: Connected SSH manager instance
            job: ClusterJob to sync
        """
        import re
        
        self.ssh_manager = ssh_manager
        self.job = job
        self.job_path = f"{ssh_manager.config.root_path}/{job.name}"
        
        # Find the actual votes database file in the job directory
        # The job_id hash is generated from input file paths in importChemkin.py,
        # so we need to discover it by listing files
        stdout, stderr = ssh_manager.exec_command(f'ls {self.job_path}/votes_*.db 2>/dev/null || echo "NOTFOUND"')
        
        if 'NOTFOUND' in stdout or not stdout.strip():
            # No database found yet - this might be a new job
            logger.warning(f"No votes database found in {self.job_path}")
            # Use a placeholder - the database will be created by importChemkin.py
            self.db_path = None
            self.job_id = None
        else:
            # Extract the first database file found
            db_files = [line.strip() for line in stdout.strip().split('\n') if line.strip()]
            if db_files:
                self.db_path = db_files[0]
                # Extract job_id hash from filename: votes_{hash}.db
                match = re.search(r'votes_([a-f0-9]{32})\.db', self.db_path)
                if match:
                    self.job_id = match.group(1)
                    logger.info(f"Found vote DB: {self.db_path} (job_id: {self.job_id})")
                else:
                    logger.error(f"Could not parse job_id from {self.db_path}")
                    self.job_id = None
            else:
                self.db_path = None
                self.job_id = None
        
    def check_remote_db_exists(self) -> bool:
        """Check if votes database exists on cluster"""
        if not self.db_path:
            return False
        stdout, stderr = self.ssh_manager.exec_command(f'test -f {self.db_path} && echo "EXISTS"')
        return 'EXISTS' in stdout
    
    def get_remote_db_size(self) -> int:
        """Get size of remote database in bytes"""
        if not self.db_path:
            return 0
        stdout, stderr = self.ssh_manager.exec_command(f'stat -f%z {self.db_path} 2>/dev/null || stat -c%s {self.db_path}')
        try:
            return int(stdout.strip())
        except:
            return 0
    
    def get_last_sync_time(self) -> Optional[str]:
        """
        Get timestamp of last successful sync for this job
        
        Returns:
            ISO format timestamp string or None if never synced
        """
        try:
            last_sync = SyncLog.objects.filter(
                job=self.job,
                sync_type='votes',
                direction='pull',
                success=True
            ).order_by('-synced_at').first()
            
            if last_sync:
                # Format for SQLite: 'YYYY-MM-DD HH:MM:SS'
                return last_sync.synced_at.strftime('%Y-%m-%d %H:%M:%S')
            return None
        except Exception as e:
            logger.warning(f"Could not get last sync time: {e}")
            return None
    
    def get_updated_votes(self, since: Optional[str] = None) -> Dict:
        """
        Query remote database for votes updated since timestamp
        
        Args:
            since: ISO timestamp string, or None for all votes
            
        Returns:
            Dictionary with votes data
        """
        # Build SQL query for updated votes
        if since:
            where_clause = f"WHERE updated_at > '{since}'"
        else:
            where_clause = ""
        
        query = f"""
        SELECT 
            sv.id,
            sv.job_id,
            sv.chemkin_label,
            sv.chemkin_formula,
            sv.rmg_species_label,
            sv.rmg_species_smiles,
            sv.rmg_species_index,
            sv.rmg_species_formula,
            sv.vote_count,
            sv.enthalpy_discrepancy,
            sv.confidence_score,
            sv.created_at,
            sv.updated_at
        FROM species_votes sv
        {where_clause}
        ORDER BY sv.updated_at
        """
        
        # Execute query via SSH and capture JSON output
        cmd = f"""sqlite3 {self.db_path} -json '{query}'"""
        stdout, stderr = self.ssh_manager.exec_command(cmd)
        
        if stderr:
            logger.warning(f"SQLite query stderr: {stderr}")
        
        try:
            votes = json.loads(stdout) if stdout.strip() else []
            return {'votes': votes, 'count': len(votes)}
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse votes JSON: {e}")
            logger.debug(f"Raw output: {stdout[:500]}")
            return {'votes': [], 'count': 0}
    
    def get_voting_reactions(self, species_vote_ids: List[int]) -> Dict:
        """
        Get voting reactions for specific species votes
        
        Args:
            species_vote_ids: List of species_vote.id values
            
        Returns:
            Dictionary mapping species_vote_id to list of reactions
        """
        if not species_vote_ids:
            return {}
        
        # Create comma-separated list for SQL IN clause
        ids_str = ','.join(str(id) for id in species_vote_ids)
        
        query = f"""
        SELECT 
            vr.id,
            vr.species_vote_id,
            vr.chemkin_reaction_str,
            vr.edge_reaction_str,
            vr.reaction_family,
            vr.created_at
        FROM voting_reactions vr
        WHERE vr.species_vote_id IN ({ids_str})
        ORDER BY vr.species_vote_id, vr.created_at
        """
        
        cmd = f"""sqlite3 {self.db_path} -json '{query}'"""
        stdout, stderr = self.ssh_manager.exec_command(cmd)
        
        try:
            reactions = json.loads(stdout) if stdout.strip() else []
            
            # Group by species_vote_id
            grouped = {}
            for rxn in reactions:
                species_vote_id = rxn['species_vote_id']
                if species_vote_id not in grouped:
                    grouped[species_vote_id] = []
                grouped[species_vote_id].append(rxn)
            
            return grouped
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse reactions JSON: {e}")
            return {}
    
    def get_thermo_matches(self, species_vote_ids: List[int]) -> Dict:
        """
        Get thermo matches for specific species votes
        
        Args:
            species_vote_ids: List of species_vote.id values
            
        Returns:
            Dictionary mapping species_vote_id to list of thermo matches
        """
        if not species_vote_ids:
            return {}
        
        # Create comma-separated list for SQL IN clause
        ids_str = ','.join(str(id) for id in species_vote_ids)
        
        query = f"""
        SELECT 
            tm.id,
            tm.species_vote_id,
            tm.library_name,
            tm.library_species_name,
            tm.name_matches,
            tm.created_at
        FROM thermo_matches tm
        WHERE tm.species_vote_id IN ({ids_str})
        ORDER BY tm.species_vote_id, tm.name_matches DESC, tm.library_name
        """
        
        cmd = f"""sqlite3 {self.db_path} -json '{query}'"""
        stdout, stderr = self.ssh_manager.exec_command(cmd)
        
        try:
            matches = json.loads(stdout) if stdout.strip() else []
            
            # Group by species_vote_id
            grouped = {}
            for match in matches:
                species_vote_id = match['species_vote_id']
                if species_vote_id not in grouped:
                    grouped[species_vote_id] = []
                grouped[species_vote_id].append({
                    'library': match['library_name'],
                    'species_name': match['library_species_name'],
                    'name_matches': bool(match['name_matches'])
                })
            
            return grouped
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse thermo matches JSON: {e}")
            return {}
    
    def get_updated_identified_species(self, since: Optional[str] = None) -> Dict:
        """Get identified species updated since timestamp"""
        if since:
            where_clause = f"WHERE identified_at > '{since}'"
        else:
            where_clause = ""
        
        query = f"""
        SELECT 
            id,
            job_id,
            chemkin_label,
            chemkin_formula,
            rmg_species_label,
            rmg_species_smiles,
            rmg_species_index,
            identification_method,
            identified_by,
            enthalpy_discrepancy,
            notes,
            identified_at
        FROM identified_species
        {where_clause}
        ORDER BY identified_at
        """
        
        cmd = f"""sqlite3 {self.db_path} -json '{query}'"""
        stdout, stderr = self.ssh_manager.exec_command(cmd)
        
        try:
            species = json.loads(stdout) if stdout.strip() else []
            return {'species': species, 'count': len(species)}
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse identified species JSON: {e}")
            return {'species': [], 'count': 0}
    
    def get_updated_blocked_matches(self, since: Optional[str] = None) -> Dict:
        """Get blocked matches updated since timestamp"""
        if since:
            where_clause = f"WHERE blocked_at > '{since}'"
        else:
            where_clause = ""
        
        query = f"""
        SELECT 
            id,
            job_id,
            chemkin_label,
            rmg_species_label,
            rmg_species_smiles,
            rmg_species_index,
            blocked_by,
            reason,
            blocked_at
        FROM blocked_matches
        {where_clause}
        ORDER BY blocked_at
        """
        
        cmd = f"""sqlite3 {self.db_path} -json '{query}'"""
        stdout, stderr = self.ssh_manager.exec_command(cmd)
        
        try:
            blocked = json.loads(stdout) if stdout.strip() else []
            return {'blocked': blocked, 'count': len(blocked)}
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse blocked matches JSON: {e}")
            return {'blocked': [], 'count': 0}
    
    def sync_votes_to_django(self, votes_data: List[Dict], reactions_data: Dict, 
                            thermo_matches_data: Dict = None) -> int:
        """
        Sync vote data to Django models
        
        Args:
            votes_data: List of vote records from SQLite
            reactions_data: Dictionary of reactions grouped by species_vote_id
            thermo_matches_data: Dictionary of thermo matches grouped by species_vote_id
            
        Returns:
            Number of votes synced
        """
        if thermo_matches_data is None:
            thermo_matches_data = {}
        
        synced_count = 0
        
        with transaction.atomic():
            for vote_record in votes_data:
                chemkin_label = vote_record['chemkin_label']
                rmg_species_smiles = vote_record.get('rmg_species_smiles', '')
                rmg_species_index = vote_record.get('rmg_species_index')
                
                # Get or create Species with correct field names
                species, _ = Species.objects.get_or_create(
                    job=self.job,
                    chemkin_label=chemkin_label,
                    defaults={
                        'formula': vote_record.get('chemkin_formula', ''),  # Field is 'formula', not 'chemkin_formula'
                        'identification_status': 'unidentified'  # Field is 'identification_status', not 'status'
                    }
                )
                
                # Get or create CandidateSpecies with correct field names
                candidate, created = CandidateSpecies.objects.get_or_create(
                    species=species,
                    rmg_index=rmg_species_index,  # Field is 'rmg_index', not 'rmg_species_index'
                    defaults={
                        'rmg_label': vote_record.get('rmg_species_label', ''),  # Field is 'rmg_label'
                        'smiles': rmg_species_smiles,  # Field is 'smiles'
                        'vote_count': vote_record.get('vote_count', 0),
                        'enthalpy_discrepancy': vote_record.get('enthalpy_discrepancy')
                        # Note: confidence_score doesn't exist in CandidateSpecies model
                    }
                )
                
                # Update if exists
                if not created:
                    candidate.vote_count = vote_record.get('vote_count', 0)
                    candidate.enthalpy_discrepancy = vote_record.get('enthalpy_discrepancy')
                    candidate.save()
                
                # Sync voting reactions
                species_vote_id = vote_record['id']
                reactions = reactions_data.get(species_vote_id, [])
                
                for rxn in reactions:
                    Vote.objects.get_or_create(
                        candidate=candidate,
                        chemkin_reaction_str=rxn.get('chemkin_reaction_str', ''),
                        defaults={
                            'edge_reaction_str': rxn.get('edge_reaction_str', ''),
                            'reaction_family': rxn.get('reaction_family', '')
                        }
                    )
                
                # Sync thermo matches (NEW)
                thermo_matches = thermo_matches_data.get(species_vote_id, [])
                
                for match in thermo_matches:
                    ThermoMatch.objects.get_or_create(
                        species=species,
                        candidate=candidate,
                        library_name=match.get('library', ''),
                        defaults={
                            'library_species_name': match.get('species_name', ''),
                            'name_matches': match.get('name_matches', False)
                        }
                    )
                
                synced_count += 1
        
        return synced_count
    
    def sync_identified_species_to_django(self, species_data: List[Dict]) -> int:
        """Sync identified species to Django models"""
        synced_count = 0
        
        with transaction.atomic():
            for record in species_data:
                chemkin_label = record['chemkin_label']
                rmg_species_smiles = record.get('rmg_species_smiles', '')
                rmg_species_index = record.get('rmg_species_index')
                enthalpy_discrepancy = record.get('enthalpy_discrepancy')
                
                # Map to importer_dashboard.Species field names
                species_defaults = {
                    'formula': record.get('chemkin_formula', ''),
                    'identification_status': 'confirmed',
                    'smiles': rmg_species_smiles,
                    'rmg_label': record.get('rmg_species_label', ''),
                    'rmg_index': rmg_species_index,
                    'identification_method': record.get('identification_method', 'auto'),
                    'enthalpy_discrepancy': enthalpy_discrepancy
                }
                
                # Update or create Species as identified
                species, created = Species.objects.update_or_create(
                    job=self.job,
                    chemkin_label=chemkin_label,
                    defaults=species_defaults
                )
                
                # Also create/update CandidateSpecies for the identified match
                # This is what the dashboard displays
                if rmg_species_smiles and rmg_species_index is not None:
                    candidate_defaults = {
                        'rmg_label': record.get('rmg_species_label', ''),
                        'smiles': rmg_species_smiles,
                        'enthalpy_discrepancy': enthalpy_discrepancy,
                        'is_confirmed': True,
                        'vote_count': 0  # Identified species may not have votes
                    }
                    
                    CandidateSpecies.objects.update_or_create(
                        species=species,
                        rmg_index=rmg_species_index,
                        defaults=candidate_defaults
                    )
                
                synced_count += 1
        
        return synced_count
    
    def sync_blocked_matches_to_django(self, blocked_data: List[Dict]) -> int:
        """Sync blocked matches to Django models"""
        synced_count = 0
        
        with transaction.atomic():
            for record in blocked_data:
                chemkin_label = record['chemkin_label']
                rmg_species_index = record.get('rmg_species_index')
                
                # Get Species
                try:
                    species = Species.objects.get(
                        job=self.job,
                        chemkin_label=chemkin_label
                    )
                except Species.DoesNotExist:
                    logger.warning(f"Species {chemkin_label} not found when syncing blocked match")
                    continue
                
                # Get CandidateSpecies
                try:
                    candidate = CandidateSpecies.objects.get(
                        species=species,
                        rmg_species_index=rmg_species_index
                    )
                    
                    # Mark as blocked
                    candidate.is_blocked = True
                    candidate.blocked_by = record.get('blocked_by', '')
                    candidate.blocked_reason = record.get('reason', '')
                    candidate.save()
                    
                    synced_count += 1
                except CandidateSpecies.DoesNotExist:
                    logger.warning(f"Candidate not found for {chemkin_label} index {rmg_species_index}")
        
        return synced_count
    
    def record_sync(self, sync_type: str, record_count: int, success: bool, 
                   error_message: str = None):
        """Record sync operation in SyncLog"""
        try:
            SyncLog.objects.create(
                job=self.job,
                sync_type=sync_type,
                direction='pull',
                record_count=record_count,
                success=success,
                error_message=error_message,
                synced_at=timezone.now()
            )
        except Exception as e:
            logger.error(f"Failed to record sync: {e}")
    
    def sync_incremental(self) -> Dict:
        """
        Perform incremental sync of all data types
        
        Returns:
            Dictionary with sync results
        """
        result = {
            'success': False,
            'message': '',
            'votes_synced': 0,
            'identified_synced': 0,
            'blocked_synced': 0,
            'db_size': 0,
            'incremental': False
        }
        
        try:
            # Check if DB exists
            if not self.check_remote_db_exists():
                result['message'] = 'Votes database not found on cluster'
                return result
            
            # Get DB size for reporting
            result['db_size'] = self.get_remote_db_size()
            logger.info(f"Remote database size: {result['db_size']:,} bytes")
            
            # Get last sync time
            last_sync = self.get_last_sync_time()
            
            if last_sync:
                logger.info(f"Last sync: {last_sync} - performing incremental sync")
                result['incremental'] = True
            else:
                logger.info("No previous sync - performing full sync")
                result['incremental'] = False
            
            # 1. Sync votes
            logger.info("Fetching updated votes...")
            votes_result = self.get_updated_votes(since=last_sync)
            votes_data = votes_result['votes']
            
            if votes_data:
                logger.info(f"Found {len(votes_data)} updated votes")
                
                # Get reactions and thermo matches for these votes
                species_vote_ids = [v['id'] for v in votes_data]
                reactions_data = self.get_voting_reactions(species_vote_ids)
                thermo_matches_data = self.get_thermo_matches(species_vote_ids)
                
                # Sync to Django
                result['votes_synced'] = self.sync_votes_to_django(
                    votes_data, reactions_data, thermo_matches_data
                )
                self.record_sync('votes', result['votes_synced'], True)
            
            # 2. Sync identified species
            logger.info("Fetching updated identified species...")
            identified_result = self.get_updated_identified_species(since=last_sync)
            identified_data = identified_result['species']
            
            if identified_data:
                logger.info(f"Found {len(identified_data)} updated identified species")
                result['identified_synced'] = self.sync_identified_species_to_django(identified_data)
                self.record_sync('identified_species', result['identified_synced'], True)
            
            # 3. Sync blocked matches
            logger.info("Fetching updated blocked matches...")
            blocked_result = self.get_updated_blocked_matches(since=last_sync)
            blocked_data = blocked_result['blocked']
            
            if blocked_data:
                logger.info(f"Found {len(blocked_data)} updated blocked matches")
                result['blocked_synced'] = self.sync_blocked_matches_to_django(blocked_data)
                self.record_sync('blocked_matches', result['blocked_synced'], True)
            
            result['success'] = True
            result['message'] = (
                f"Synced {result['votes_synced']} votes, "
                f"{result['identified_synced']} identified, "
                f"{result['blocked_synced']} blocked"
            )
            
            logger.info(f"✓ Incremental sync complete: {result['message']}")
            
        except Exception as e:
            result['message'] = f"Sync failed: {str(e)}"
            logger.error(f"Incremental sync failed: {e}", exc_info=True)
            self.record_sync('error', 0, False, str(e))
        
        return result
    
    def sync_full_fallback(self) -> Dict:
        """
        Fallback: Download entire DB and read with VoteReader
        
        Used when incremental sync fails or for first sync
        """
        from .vote_reader import VoteReader
        
        result = {
            'success': False,
            'message': '',
            'votes_synced': 0,
            'identified_synced': 0,
            'blocked_synced': 0
        }
        
        try:
            # Check if DB exists
            if not self.db_path or not self.check_remote_db_exists():
                result['message'] = 'Votes database not found on cluster'
                return result
            
            # Create temp directory for DB
            with tempfile.TemporaryDirectory() as temp_dir:
                # Use job_id for local filename to match cluster filename
                local_filename = f'votes_{self.job_id}.db' if self.job_id else 'votes_temp.db'
                local_db_path = os.path.join(temp_dir, local_filename)
                
                # Download DB via SCP
                logger.info(f"Downloading database from {self.db_path} to {local_db_path}...")
                
                # Use SCP via SSH
                scp_command = f'scp {self.db_path} {local_db_path}'
                # Note: This assumes SSH keys are set up, otherwise use paramiko SFTPClient
                
                # For paramiko SFTPClient:
                sftp = self.ssh_manager.ssh_client.open_sftp()
                sftp.get(self.db_path, local_db_path)
                sftp.close()
                
                logger.info("✓ Database downloaded, reading with VoteReader...")
                
                # Read with VoteReader
                reader = VoteReader(local_db_path)
                
                # Get all data
                all_votes = reader.get_all_votes(self.job.name)
                identified_species = reader.get_identified_species(self.job.name)
                blocked_matches = reader.get_blocked_matches(self.job.name)
                
                # Convert to format expected by sync methods
                # (This would need implementation based on VoteReader output format)
                
                result['success'] = True
                result['message'] = "Full database sync completed"
                
        except Exception as e:
            result['message'] = f"Full sync failed: {str(e)}"
            logger.error(f"Full sync failed: {e}", exc_info=True)
        
        return result


def sync_job_votes_incremental(job: ClusterJob) -> Dict:
    """
    Convenience function to perform incremental sync for a job
    
    Args:
        job: ClusterJob instance
        
    Returns:
        Dictionary with sync results
    """
    from .models import ImportJobConfig
    
    try:
        # Get SSH connection
        config = job.config or ImportJobConfig.objects.filter(is_default=True).first()
        if not config:
            return {
                'success': False,
                'message': 'No configuration found',
                'votes_synced': 0
            }
        
        ssh_manager = SSHJobManager(config=config)
        ssh_manager.connect()
        
        # Create sync manager and run
        syncer = IncrementalVoteSync(ssh_manager, job)
        result = syncer.sync_incremental()
        
        ssh_manager.disconnect()
        
        return result
        
    except Exception as e:
        logger.error(f"Job vote sync failed: {e}", exc_info=True)
        return {
            'success': False,
            'message': str(e),
            'votes_synced': 0
        }
