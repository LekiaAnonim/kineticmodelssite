"""
Vote Reader for Django Application

This module reads vote data from the votes_{job_id}.db SQLite database
created by importChemkin.py and makes it available to Django views.
"""

import sqlite3
import json
import logging
from typing import Dict, List, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


class VoteReader:
    """
    Read voting data from the SQLite database created by importChemkin.py
    """
    
    def __init__(self, db_path: str):
        """
        Initialize reader with path to votes database
        
        Args:
            db_path: Path to votes_{job_id}.db file
        """
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"Votes database not found: {db_path}")
    
    def get_connection(self) -> sqlite3.Connection:
        """Get database connection"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Access columns by name
        return conn
    
    def get_all_votes(self, job_id: str) -> Dict:
        """
        Get all votes for a job
        
        Returns:
            {
                'chemkin_label': {
                    'candidates': [
                        {
                            'rmg_index': int,
                            'smiles': str,
                            'vote_count': int,
                            'reactions': [...]
                        }
                    ]
                }
            }
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # Get all species with votes
            cursor.execute("""
                SELECT chemkin_label, rmg_index, smiles, vote_count, adjlist
                FROM species_votes
                WHERE job_id = ?
                ORDER BY chemkin_label, vote_count DESC
            """, (job_id,))
            
            votes = {}
            for row in cursor.fetchall():
                chemkin_label = row['chemkin_label']
                
                if chemkin_label not in votes:
                    votes[chemkin_label] = {'candidates': []}
                
                # Get reactions for this candidate
                reactions = self.get_voting_reactions(
                    job_id, 
                    chemkin_label, 
                    row['rmg_index']
                )
                
                votes[chemkin_label]['candidates'].append({
                    'rmg_index': row['rmg_index'],
                    'smiles': row['smiles'],
                    'adjlist': row['adjlist'],
                    'vote_count': row['vote_count'],
                    'reactions': reactions
                })
            
            return votes
            
        finally:
            conn.close()
    
    def get_votes_for_species(self, job_id: str, chemkin_label: str) -> Dict:
        """
        Get voting data for a specific species
        
        Args:
            job_id: Job identifier
            chemkin_label: Chemkin species label
            
        Returns:
            {
                'chemkin_label': str,
                'candidates': [
                    {
                        'rmg_index': int,
                        'smiles': str,
                        'vote_count': int,
                        'reactions': [...]
                    }
                ]
            }
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT rmg_index, smiles, adjlist, vote_count
                FROM species_votes
                WHERE job_id = ? AND chemkin_label = ?
                ORDER BY vote_count DESC
            """, (job_id, chemkin_label))
            
            candidates = []
            for row in cursor.fetchall():
                reactions = self.get_voting_reactions(
                    job_id,
                    chemkin_label,
                    row['rmg_index']
                )
                
                candidates.append({
                    'rmg_index': row['rmg_index'],
                    'smiles': row['smiles'],
                    'adjlist': row['adjlist'],
                    'vote_count': row['vote_count'],
                    'reactions': reactions
                })
            
            return {
                'chemkin_label': chemkin_label,
                'candidates': candidates
            }
            
        finally:
            conn.close()
    
    def get_voting_reactions(
        self, 
        job_id: str, 
        chemkin_label: str, 
        rmg_index: int
    ) -> List[Dict]:
        """
        Get all reactions that voted for a specific candidate
        
        Returns:
            [
                {
                    'chemkin_reaction': str,
                    'rmg_reaction': str,
                    'family': str
                }
            ]
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT chemkin_reaction, rmg_reaction, family
                FROM voting_reactions
                WHERE job_id = ? 
                  AND chemkin_label = ? 
                  AND rmg_index = ?
            """, (job_id, chemkin_label, rmg_index))
            
            reactions = []
            for row in cursor.fetchall():
                reactions.append({
                    'chemkin_reaction': row['chemkin_reaction'],
                    'rmg_reaction': row['rmg_reaction'],
                    'family': row['family']
                })
            
            return reactions
            
        finally:
            conn.close()
    
    def get_identified_species(self, job_id: str) -> List[Dict]:
        """
        Get all identified species
        
        Returns:
            [
                {
                    'chemkin_label': str,
                    'smiles': str,
                    'adjlist': str,
                    'confirmed_by': str,
                    'confirmed_at': str
                }
            ]
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT chemkin_label, smiles, adjlist, confirmed_by, confirmed_at
                FROM identified_species
                WHERE job_id = ?
                ORDER BY confirmed_at DESC
            """, (job_id,))
            
            identified = []
            for row in cursor.fetchall():
                identified.append({
                    'chemkin_label': row['chemkin_label'],
                    'smiles': row['smiles'],
                    'adjlist': row['adjlist'],
                    'confirmed_by': row['confirmed_by'],
                    'confirmed_at': row['confirmed_at']
                })
            
            return identified
            
        finally:
            conn.close()
    
    def get_blocked_matches(self, job_id: str) -> List[Dict]:
        """
        Get all blocked matches
        
        Returns:
            [
                {
                    'chemkin_label': str,
                    'rmg_index': int,
                    'smiles': str,
                    'blocked_by': str,
                    'blocked_at': str,
                    'reason': str
                }
            ]
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT chemkin_label, rmg_index, smiles, adjlist, 
                       blocked_by, blocked_at, reason
                FROM blocked_matches
                WHERE job_id = ?
                ORDER BY blocked_at DESC
            """, (job_id,))
            
            blocked = []
            for row in cursor.fetchall():
                blocked.append({
                    'chemkin_label': row['chemkin_label'],
                    'rmg_index': row['rmg_index'],
                    'smiles': row['smiles'],
                    'adjlist': row['adjlist'],
                    'blocked_by': row['blocked_by'],
                    'blocked_at': row['blocked_at'],
                    'reason': row['reason'] if 'reason' in row.keys() else None
                })
            
            return blocked
            
        finally:
            conn.close()
    
    def get_statistics(self, job_id: str) -> Dict:
        """
        Get summary statistics
        
        Returns:
            {
                'total_species_with_votes': int,
                'total_votes': int,
                'total_candidates': int,
                'identified_count': int,
                'blocked_count': int,
                'top_voted': [...]
            }
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # Count species with votes
            cursor.execute("""
                SELECT COUNT(DISTINCT chemkin_label) as count
                FROM species_votes
                WHERE job_id = ?
            """, (job_id,))
            species_with_votes = cursor.fetchone()['count']
            
            # Total votes
            cursor.execute("""
                SELECT SUM(vote_count) as total
                FROM species_votes
                WHERE job_id = ?
            """, (job_id,))
            total_votes = cursor.fetchone()['total'] or 0
            
            # Total candidates
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM species_votes
                WHERE job_id = ?
            """, (job_id,))
            total_candidates = cursor.fetchone()['count']
            
            # Identified count
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM identified_species
                WHERE job_id = ?
            """, (job_id,))
            identified_count = cursor.fetchone()['count']
            
            # Blocked count
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM blocked_matches
                WHERE job_id = ?
            """, (job_id,))
            blocked_count = cursor.fetchone()['count']
            
            # Top voted species
            cursor.execute("""
                SELECT chemkin_label, rmg_index, smiles, vote_count
                FROM species_votes
                WHERE job_id = ?
                ORDER BY vote_count DESC
                LIMIT 10
            """, (job_id,))
            
            top_voted = []
            for row in cursor.fetchall():
                top_voted.append({
                    'chemkin_label': row['chemkin_label'],
                    'rmg_index': row['rmg_index'],
                    'smiles': row['smiles'],
                    'vote_count': row['vote_count']
                })
            
            return {
                'total_species_with_votes': species_with_votes,
                'total_votes': total_votes,
                'total_candidates': total_candidates,
                'identified_count': identified_count,
                'blocked_count': blocked_count,
                'top_voted': top_voted
            }
            
        finally:
            conn.close()


def find_votes_database_on_cluster(ssh_job_manager, job_path: str, job_id: str) -> Optional[str]:
    """
    Find votes database file for a job on the cluster
    
    Args:
        ssh_job_manager: SSHJobManager instance
        job_path: Path to job directory on cluster
        job_id: Job ID (MD5 hash)
        
    Returns:
        Path to votes database or None if not found
    """
    # Try several possible locations
    possible_paths = [
        f'{job_path}/votes_{job_id}.db',
        f'{job_path}/RMG-Py/votes_{job_id}.db',
        f'{job_path}/../votes_{job_id}.db',
    ]
    
    for path in possible_paths:
        # Check if file exists on cluster
        result = ssh_job_manager.exec_command(f'[ -f {path} ] && echo EXISTS || echo MISSING')
        stdout, stderr = result
        
        if 'EXISTS' in stdout:
            logger.info(f"Found votes database: {path}")
            return path
    
    logger.warning(f"Votes database not found for job {job_id}")
    return None


def sync_votes_to_django(job, ssh_job_manager):
    """
    Sync vote data from SQLite database to Django models
    
    Args:
        job: ClusterJob instance
        ssh_job_manager: SSHJobManager instance
        
    Returns:
        dict: Result with success status and statistics
    """
    from .models import Species, VoteCandidate, VotingReaction
    
    try:
        # Get configuration
        from .models import ImportJobConfig
        config = job.config or ImportJobConfig.objects.filter(is_default=True).first()
        if not config:
            return {
                'success': False,
                'message': 'No configuration found'
            }
        
        # Construct job path
        job_path = f'{config.root_path}/{job.name}'
        
        # Calculate job_id (MD5 hash of input file paths)
        # The actual files are: chem_annotated-surface.inp, chem_annotated-gas.inp, Thermo.dat
        import hashlib
        species_file = f"{job_path}/chem_annotated-surface.inp"
        reactions_file = f"{job_path}/chem_annotated-gas.inp"
        thermo_file = f"{job_path}/Thermo.dat"
        job_identifier = f"{species_file}{reactions_file}{thermo_file}"
        job_id = hashlib.md5(job_identifier.encode()).hexdigest()
        
        logger.info(f"Looking for votes database with job_id: {job_id}")
        
        # Connect to cluster if not already connected
        if not ssh_job_manager.client:
            ssh_job_manager.connect()
        
        # Find votes database on cluster
        db_path = find_votes_database_on_cluster(ssh_job_manager, job_path, job_id)
        if not db_path:
            return {
                'success': False,
                'message': 'Votes database not found on cluster'
            }
        
        # Copy database to local temp file using SFTP
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            local_db_path = tmp.name
        
        # Download database from cluster using paramiko SFTP
        sftp = ssh_job_manager.client.open_sftp()
        try:
            sftp.get(db_path, local_db_path)
            logger.info(f"Downloaded votes database to {local_db_path}")
        finally:
            sftp.close()
        
        # Read votes from database
        reader = VoteReader(local_db_path)
        
        # Get all votes
        votes_data = reader.get_all_votes(job_id)
        
        # Get identified species
        identified_data = reader.get_identified_species(job_id)
        
        # Get statistics
        stats = reader.get_statistics(job_id)
        
        # Update Species records with voting data
        for chemkin_label, vote_info in votes_data.items():
            species = Species.objects.filter(
                job=job,
                chemkin_label=chemkin_label
            ).first()
            
            if not species:
                logger.warning(f"Species {chemkin_label} not found in database")
                continue
            
            # Delete existing candidates
            VoteCandidate.objects.filter(species=species).delete()
            
            # Create candidates
            for candidate_data in vote_info['candidates']:
                candidate = VoteCandidate.objects.create(
                    species=species,
                    rmg_index=candidate_data['rmg_index'],
                    smiles=candidate_data['smiles'],
                    adjlist=candidate_data.get('adjlist', ''),
                    vote_count=candidate_data['vote_count']
                )
                
                # Create voting reactions
                for reaction_data in candidate_data['reactions']:
                    VotingReaction.objects.create(
                        candidate=candidate,
                        chemkin_reaction=reaction_data['chemkin_reaction'],
                        rmg_reaction=reaction_data['rmg_reaction'],
                        family=reaction_data.get('family', '')
                    )
        
        # Update identified species
        for identified in identified_data:
            Species.objects.filter(
                job=job,
                chemkin_label=identified['chemkin_label']
            ).update(
                identification_status='identified',
                smiles=identified['smiles']
            )
        
        # Clean up temp file
        Path(local_db_path).unlink()
        
        return {
            'success': True,
            'message': 'Votes synced successfully from database',
            'statistics': stats
        }
        
    except Exception as e:
        logger.error(f"Error syncing votes from database: {e}", exc_info=True)
        return {
            'success': False,
            'message': f'Error syncing votes: {str(e)}'
        }
