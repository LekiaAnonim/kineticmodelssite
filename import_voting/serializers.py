"""
Serializers for the import voting API
"""
from rest_framework import serializers
from .models import ImportJob, SpeciesVote, VotingReaction, IdentifiedSpecies, BlockedMatch


class VotingReactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = VotingReaction
        fields = [
            'id',
            'chemkin_reaction_str',
            'edge_reaction_str',
            'reaction_family',
            'created_at'
        ]


class SpeciesVoteSerializer(serializers.ModelSerializer):
    voting_reactions = VotingReactionSerializer(many=True, read_only=True)
    voting_reaction_count = serializers.IntegerField(
        source='voting_reactions.count',
        read_only=True
    )
    
    class Meta:
        model = SpeciesVote
        fields = [
            'id',
            'chemkin_label',
            'chemkin_formula',
            'rmg_species_label',
            'rmg_species_smiles',
            'rmg_species_index',
            'rmg_species_formula',
            'vote_count',
            'enthalpy_discrepancy',
            'confidence_score',
            'voting_reactions',
            'voting_reaction_count',
            'created_at',
            'updated_at'
        ]


class IdentifiedSpeciesSerializer(serializers.ModelSerializer):
    class Meta:
        model = IdentifiedSpecies
        fields = [
            'id',
            'chemkin_label',
            'chemkin_formula',
            'rmg_species_label',
            'rmg_species_smiles',
            'rmg_species_index',
            'identification_method',
            'identified_by',
            'enthalpy_discrepancy',
            'notes',
            'identified_at'
        ]


class BlockedMatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlockedMatch
        fields = [
            'id',
            'chemkin_label',
            'rmg_species_label',
            'rmg_species_smiles',
            'rmg_species_index',
            'blocked_by',
            'reason',
            'blocked_at'
        ]


class ImportJobSerializer(serializers.ModelSerializer):
    species_votes_count = serializers.IntegerField(
        source='species_votes.count',
        read_only=True
    )
    identified_count = serializers.IntegerField(
        source='identified_species_set.count',
        read_only=True
    )
    blocked_count = serializers.IntegerField(
        source='blocked_matches.count',
        read_only=True
    )
    
    class Meta:
        model = ImportJob
        fields = [
            'id',
            'job_id',
            'model_name',
            'user',
            'status',
            'species_file',
            'reactions_file',
            'thermo_file',
            'total_species',
            'identified_species',
            'total_reactions',
            'matched_reactions',
            'species_votes_count',
            'identified_count',
            'blocked_count',
            'created_at',
            'updated_at',
            'last_activity'
        ]
        read_only_fields = ['created_at', 'updated_at', 'last_activity']


class ImportJobDetailSerializer(ImportJobSerializer):
    """Extended serializer with related objects"""
    species_votes = SpeciesVoteSerializer(many=True, read_only=True)
    identified_species_set = IdentifiedSpeciesSerializer(many=True, read_only=True)
    blocked_matches = BlockedMatchSerializer(many=True, read_only=True)
    
    class Meta(ImportJobSerializer.Meta):
        fields = ImportJobSerializer.Meta.fields + [
            'species_votes',
            'identified_species_set',
            'blocked_matches'
        ]


# Simplified serializers for bulk operations
class BulkVoteCreateSerializer(serializers.Serializer):
    """Serializer for bulk creating votes"""
    chemkin_label = serializers.CharField(max_length=255)
    chemkin_formula = serializers.CharField(max_length=100, required=False, allow_blank=True)
    rmg_species_label = serializers.CharField(max_length=255)
    rmg_species_smiles = serializers.CharField()
    rmg_species_index = serializers.IntegerField()
    rmg_species_formula = serializers.CharField(max_length=100, required=False, allow_blank=True)
    enthalpy_discrepancy = serializers.FloatField(required=False, allow_null=True)
    voting_reactions = serializers.ListField(
        child=serializers.DictField(),
        required=False
    )


class BulkIdentifiedSpeciesSerializer(serializers.Serializer):
    """Serializer for bulk creating identified species"""
    chemkin_label = serializers.CharField(max_length=255)
    chemkin_formula = serializers.CharField(max_length=100, required=False, allow_blank=True)
    rmg_species_label = serializers.CharField(max_length=255)
    rmg_species_smiles = serializers.CharField()
    rmg_species_index = serializers.IntegerField(required=False, allow_null=True)
    identification_method = serializers.CharField(max_length=50, required=False)
    identified_by = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    enthalpy_discrepancy = serializers.FloatField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True)
