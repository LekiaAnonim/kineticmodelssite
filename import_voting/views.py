"""
REST API views for import voting system
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticatedOrReadOnly, AllowAny
from django.db import models
from django.db.models import Count, Q, Prefetch, Avg
from django.shortcuts import get_object_or_404

from .models import (
    ImportJob, SpeciesVote, VotingReaction, 
    IdentifiedSpecies, BlockedMatch
)
from .serializers import (
    ImportJobSerializer, ImportJobDetailSerializer,
    SpeciesVoteSerializer, VotingReactionSerializer,
    IdentifiedSpeciesSerializer, BlockedMatchSerializer,
    BulkVoteCreateSerializer, BulkIdentifiedSpeciesSerializer
)


class ImportJobViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing import jobs
    
    list: Get all import jobs
    retrieve: Get a specific import job with all related data
    create: Create a new import job
    update: Update an import job
    destroy: Delete an import job
    """
    queryset = ImportJob.objects.all()
    permission_classes = [AllowAny]  # TODO: Change to IsAuthenticatedOrReadOnly in production
    lookup_field = 'job_id'
    
    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ImportJobDetailSerializer
        return ImportJobSerializer
    
    def get_queryset(self):
        queryset = ImportJob.objects.all()
        
        # Filter by status
        status_param = self.request.query_params.get('status', None)
        if status_param:
            queryset = queryset.filter(status=status_param)
        
        # Annotate with counts
        queryset = queryset.annotate(
            votes_count=Count('species_votes'),
            identified_count=Count('identified_species_set'),
            blocked_count=Count('blocked_matches')
        )
        
        return queryset
    
    @action(detail=True, methods=['post'])
    def update_status(self, request, job_id=None):
        """Update the status of an import job"""
        import_job = self.get_object()
        new_status = request.data.get('status')
        
        if new_status not in dict(ImportJob.STATUS_CHOICES):
            return Response(
                {'error': 'Invalid status'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        import_job.status = new_status
        import_job.save()
        
        serializer = self.get_serializer(import_job)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def statistics(self, request, job_id=None):
        """Get detailed statistics for an import job"""
        import_job = self.get_object()
        
        stats = {
            'job_id': import_job.job_id,
            'model_name': import_job.model_name,
            'status': import_job.status,
            'total_species': import_job.total_species,
            'identified_species': import_job.identified_species_set.count(),
            'total_reactions': import_job.total_reactions,
            'matched_reactions': import_job.matched_reactions,
            'species_with_votes': import_job.species_votes.values('chemkin_label').distinct().count(),
            'total_votes': import_job.species_votes.count(),
            'blocked_matches': import_job.blocked_matches.count(),
            'avg_votes_per_species': import_job.species_votes.aggregate(
                avg=Avg('vote_count')
            )['avg'] or 0,
            'top_voted_species': list(
                import_job.species_votes.order_by('-vote_count')[:10].values(
                    'chemkin_label', 'rmg_species_label', 'vote_count'
                )
            ),
            'identification_methods': dict(
                import_job.identified_species_set.values('identification_method').annotate(
                    count=Count('id')
                ).values_list('identification_method', 'count')
            )
        }
        
        return Response(stats)


class SpeciesVoteViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing species votes
    
    list: Get all species votes (filterable by job_id, chemkin_label)
    retrieve: Get a specific species vote
    create: Create a new species vote
    update: Update a species vote
    destroy: Delete a species vote
    """
    queryset = SpeciesVote.objects.all()
    serializer_class = SpeciesVoteSerializer
    permission_classes = [AllowAny]  # TODO: Change to IsAuthenticatedOrReadOnly in production
    
    def get_queryset(self):
        queryset = SpeciesVote.objects.select_related('import_job').prefetch_related(
            'voting_reactions'
        )
        
        # Filter by job_id
        job_id = self.request.query_params.get('job_id', None)
        if job_id:
            queryset = queryset.filter(import_job__job_id=job_id)
        
        # Filter by chemkin_label
        chemkin_label = self.request.query_params.get('chemkin_label', None)
        if chemkin_label:
            queryset = queryset.filter(chemkin_label=chemkin_label)
        
        # Filter by minimum votes
        min_votes = self.request.query_params.get('min_votes', None)
        if min_votes:
            queryset = queryset.filter(vote_count__gte=int(min_votes))
        
        return queryset.order_by('-vote_count', 'chemkin_label')
    
    @action(detail=False, methods=['post'])
    def bulk_create(self, request):
        """
        Bulk create or update species votes
        
        Expected payload:
        {
            "job_id": "abc123",
            "votes": [
                {
                    "chemkin_label": "CH3",
                    "rmg_species_label": "CH3(1)",
                    "rmg_species_smiles": "[CH3]",
                    "rmg_species_index": 1,
                    ...
                },
                ...
            ]
        }
        """
        job_id = request.data.get('job_id')
        votes_data = request.data.get('votes', [])
        
        if not job_id:
            return Response(
                {'error': 'job_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        import_job = get_object_or_404(ImportJob, job_id=job_id)
        
        created_count = 0
        updated_count = 0
        errors = []
        
        for vote_data in votes_data:
            serializer = BulkVoteCreateSerializer(data=vote_data)
            if not serializer.is_valid():
                errors.append({
                    'data': vote_data,
                    'errors': serializer.errors
                })
                continue
            
            validated_data = serializer.validated_data
            voting_reactions_data = validated_data.pop('voting_reactions', [])
            
            # Create or update species vote
            species_vote, created = SpeciesVote.objects.update_or_create(
                import_job=import_job,
                chemkin_label=validated_data['chemkin_label'],
                rmg_species_index=validated_data['rmg_species_index'],
                defaults={
                    'rmg_species_label': validated_data['rmg_species_label'],
                    'rmg_species_smiles': validated_data['rmg_species_smiles'],
                    'chemkin_formula': validated_data.get('chemkin_formula', ''),
                    'rmg_species_formula': validated_data.get('rmg_species_formula', ''),
                    'enthalpy_discrepancy': validated_data.get('enthalpy_discrepancy'),
                    'vote_count': len(voting_reactions_data)
                }
            )
            
            if created:
                created_count += 1
            else:
                updated_count += 1
            
            # Clear old voting reactions and add new ones
            species_vote.voting_reactions.all().delete()
            for rxn_data in voting_reactions_data:
                VotingReaction.objects.create(
                    species_vote=species_vote,
                    chemkin_reaction_str=rxn_data.get('chemkin_reaction_str', ''),
                    edge_reaction_str=rxn_data.get('edge_reaction_str', ''),
                    reaction_family=rxn_data.get('reaction_family', '')
                )
        
        return Response({
            'created': created_count,
            'updated': updated_count,
            'errors': errors
        })
    
    @action(detail=False, methods=['delete'])
    def bulk_delete(self, request):
        """
        Bulk delete species votes
        
        Expected payload:
        {
            "job_id": "abc123",
            "chemkin_labels": ["CH3", "CH4", ...],
            "rmg_species_indices": [1, 2, ...]
        }
        """
        job_id = request.data.get('job_id')
        chemkin_labels = request.data.get('chemkin_labels', [])
        rmg_indices = request.data.get('rmg_species_indices', [])
        
        if not job_id:
            return Response(
                {'error': 'job_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        queryset = SpeciesVote.objects.filter(import_job__job_id=job_id)
        
        if chemkin_labels:
            queryset = queryset.filter(chemkin_label__in=chemkin_labels)
        
        if rmg_indices:
            queryset = queryset.filter(rmg_species_index__in=rmg_indices)
        
        deleted_count, _ = queryset.delete()
        
        return Response({'deleted': deleted_count})


class IdentifiedSpeciesViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing identified species
    """
    queryset = IdentifiedSpecies.objects.all()
    serializer_class = IdentifiedSpeciesSerializer
    permission_classes = [AllowAny]  # TODO: Change to IsAuthenticatedOrReadOnly in production
    
    def get_queryset(self):
        queryset = IdentifiedSpecies.objects.select_related('import_job')
        
        # Filter by job_id
        job_id = self.request.query_params.get('job_id', None)
        if job_id:
            queryset = queryset.filter(import_job__job_id=job_id)
        
        # Filter by identification method
        method = self.request.query_params.get('method', None)
        if method:
            queryset = queryset.filter(identification_method=method)
        
        return queryset.order_by('-identified_at')
    
    @action(detail=False, methods=['post'])
    def bulk_create(self, request):
        """
        Bulk create identified species
        
        Expected payload:
        {
            "job_id": "abc123",
            "species": [
                {
                    "chemkin_label": "CH3",
                    "rmg_species_label": "CH3(1)",
                    ...
                },
                ...
            ]
        }
        """
        job_id = request.data.get('job_id')
        species_data = request.data.get('species', [])
        
        if not job_id:
            return Response(
                {'error': 'job_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        import_job = get_object_or_404(ImportJob, job_id=job_id)
        
        created_count = 0
        updated_count = 0
        errors = []
        
        for sp_data in species_data:
            serializer = BulkIdentifiedSpeciesSerializer(data=sp_data)
            if not serializer.is_valid():
                errors.append({
                    'data': sp_data,
                    'errors': serializer.errors
                })
                continue
            
            validated_data = serializer.validated_data
            
            # Create or update identified species
            _, created = IdentifiedSpecies.objects.update_or_create(
                import_job=import_job,
                chemkin_label=validated_data['chemkin_label'],
                defaults={
                    'chemkin_formula': validated_data.get('chemkin_formula', ''),
                    'rmg_species_label': validated_data['rmg_species_label'],
                    'rmg_species_smiles': validated_data['rmg_species_smiles'],
                    'rmg_species_index': validated_data.get('rmg_species_index'),
                    'identification_method': validated_data.get('identification_method', 'auto'),
                    'identified_by': validated_data.get('identified_by'),
                    'enthalpy_discrepancy': validated_data.get('enthalpy_discrepancy'),
                    'notes': validated_data.get('notes', '')
                }
            )
            
            if created:
                created_count += 1
            else:
                updated_count += 1
        
        # Update job statistics
        import_job.update_statistics()
        
        return Response({
            'created': created_count,
            'updated': updated_count,
            'errors': errors
        })


class BlockedMatchViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing blocked matches
    """
    queryset = BlockedMatch.objects.all()
    serializer_class = BlockedMatchSerializer
    permission_classes = [AllowAny]  # TODO: Change to IsAuthenticatedOrReadOnly in production
    
    def get_queryset(self):
        queryset = BlockedMatch.objects.select_related('import_job')
        
        # Filter by job_id
        job_id = self.request.query_params.get('job_id', None)
        if job_id:
            queryset = queryset.filter(import_job__job_id=job_id)
        
        return queryset.order_by('-blocked_at')
