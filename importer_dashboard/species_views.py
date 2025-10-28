"""
Views for interactive species identification
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db.models import Count, Q, F, Sum, Case, When, IntegerField
from django.db import transaction
import json
import logging
import urllib.parse

from .models import (
    ClusterJob, Species, CandidateSpecies, Vote, ThermoMatch,
    BlockedMatch, ImportJobStatus, ChemkinReaction
)
from .species_utils import (
    prune_common_votes, calculate_confidence_score,
    should_auto_confirm, get_species_image_url,
    format_reaction_string, export_smiles_file, export_blocked_file
)
from .logger import dashboard_logger

logger = logging.getLogger(__name__)


@login_required
def species_queue(request, job_id):
    """
    Display species queue for identification
    
    Shows all unidentified species ranked by controversy (vote count)
    """
    job = get_object_or_404(ClusterJob, id=job_id)
    
    # Auto-sync species data if job is running and species data is stale/empty
    species_count = Species.objects.filter(job=job).count()
    should_sync = (
        job.status == 'running' and 
        job.host and 
        job.host != 'Pending...' and
        (species_count == 0 or request.GET.get('sync') == 'true')
    )
    
    sync_message = None
    if should_sync:
        try:
            # Use new incremental sync instead of old CherryPy API
            from .incremental_sync import sync_job_votes_incremental
            sync_result = sync_job_votes_incremental(job)
            
            if sync_result['success']:
                sync_message = {
                    'type': 'success',
                    'text': (
                        f"✓ Synced from cluster: {sync_result['votes_synced']} votes, "
                        f"{sync_result['identified_synced']} identified, "
                        f"{sync_result['blocked_synced']} blocked "
                        f"({'incremental' if sync_result.get('incremental') else 'full sync'})"
                    )
                }
            else:
                sync_message = {
                    'type': 'warning',
                    'text': f"⚠ Sync issue: {sync_result['message']}"
                }
        except Exception as e:
            logger.warning(f"Auto-sync failed for job {job_id}: {e}")
            sync_message = {
                'type': 'info',
                'text': "Using cached data. Click 'Refresh' to sync from cluster."
            }
    
    # Get filter parameters
    status_filter = request.GET.get('status', 'unidentified')
    sort_by = request.GET.get('sort', 'controversy')
    
    # Smart default: if no filter specified and no unidentified species, 
    # but there are confirmed species, show confirmed instead
    if 'status' not in request.GET:
        unidentified_count = Species.objects.filter(
            job=job, 
            identification_status='unidentified'
        ).count()
        
        if unidentified_count == 0:
            confirmed_count = Species.objects.filter(
                job=job,
                identification_status__in=['confirmed', 'processed']
            ).count()
            
            if confirmed_count > 0:
                status_filter = 'confirmed'
    
    # Base query
    species_qs = Species.objects.filter(job=job)
    
    # Apply status filter
    if status_filter == 'unidentified':
        species_qs = species_qs.filter(identification_status='unidentified')
    elif status_filter == 'tentative':
        species_qs = species_qs.filter(identification_status='tentative')
    elif status_filter == 'confirmed':
        species_qs = species_qs.filter(identification_status__in=['confirmed', 'processed'])
    elif status_filter == 'all':
        pass  # No filter
    
    # Annotate with vote counts and candidate counts
    species_qs = species_qs.annotate(
        total_votes=Count('votes', distinct=True),
        candidate_count=Count('candidates', distinct=True),
        unique_votes=Count(
            Case(
                When(votes__is_unique=True, then=1),
                output_field=IntegerField()
            )
        )
    )
    
    # Apply sorting
    if sort_by == 'controversy':
        # Most votes first (most controversial)
        species_qs = species_qs.order_by('-total_votes', '-candidate_count')
    elif sort_by == 'name':
        species_qs = species_qs.order_by('chemkin_label')
    elif sort_by == 'formula':
        species_qs = species_qs.order_by('formula', 'chemkin_label')
    elif sort_by == 'confidence':
        # This requires getting top candidate confidence - done in template
        species_qs = species_qs.order_by('-unique_votes', '-total_votes')
    elif sort_by == 'importance':
        # Sort by reaction participation (NEW FEATURE!)
        # Count reactions for each species using exact word boundary matching
        import re
        species_with_counts = []
        for species in species_qs:
            # Use regex for exact word boundary matching
            species_pattern = r'(^|,|\s)' + re.escape(species.chemkin_label) + r'(,|\s|$)'
            reaction_count = ChemkinReaction.objects.filter(
                Q(reactants__iregex=species_pattern) |
                Q(products__iregex=species_pattern),
                job=job
            ).count()
            species_with_counts.append((species, reaction_count))
        
        # Sort by reaction count descending
        species_with_counts.sort(key=lambda x: x[1], reverse=True)
        species_qs = [s[0] for s in species_with_counts]
    
    # Get species with their candidates
    species_list = []
    for species in species_qs:
        candidates = species.candidates.filter(is_blocked=False).order_by(
            '-unique_vote_count', '-vote_count', 'enthalpy_discrepancy'
        )[:5]  # Top 5 candidates
        
        top_candidate = candidates.first() if candidates.exists() else None
        
        # Add absolute enthalpy and thermo match info for template display
        confidence_score = None
        if top_candidate:
            top_candidate.enthalpy_discrepancy_abs = abs(top_candidate.enthalpy_discrepancy) if top_candidate.enthalpy_discrepancy else 0
            
            # Get thermo match information
            thermo_matches = ThermoMatch.objects.filter(
                species=species,
                candidate=top_candidate
            )
            top_candidate.thermo_matches_count = thermo_matches.count()
            top_candidate.thermo_name_matches = thermo_matches.filter(name_matches=True).exists()
            
            # Calculate confidence score for the top candidate
            confidence_score = calculate_confidence_score(
                vote_count=top_candidate.vote_count,
                unique_votes=top_candidate.unique_vote_count,
                enthalpy_diff=top_candidate.enthalpy_discrepancy,
                thermo_matches=thermo_matches.count()
            )
        
        species_data = {
            'species': species,
            'candidates': candidates,
            'top_candidate': top_candidate,
            'confidence_score': confidence_score,
            'total_votes': species.total_votes,
            'unique_votes': species.unique_votes,
            'candidate_count': species.candidate_count,
        }
        species_list.append(species_data)
    
    # Statistics - use job statistics from cluster, fall back to database counts
    species_db_count = Species.objects.filter(job=job).count()
    
    if species_db_count == 0 and job.total_species > 0:
        # Use statistics from cluster job (no local Species records yet)
        stats = {
            'total': job.total_species or 0,
            'confirmed': job.identified_species or 0,
            'tentative': 0,  # Not tracked separately in job model
            'unidentified': (job.total_species or 0) - (job.identified_species or 0),
        }
    else:
        # Use local database counts (Species records exist)
        stats = {
            'total': species_db_count,
            'unidentified': Species.objects.filter(job=job, identification_status='unidentified').count(),
            'tentative': Species.objects.filter(job=job, identification_status='tentative').count(),
            'confirmed': Species.objects.filter(job=job, identification_status__in=['confirmed', 'processed']).count(),
        }
    
    context = {
        'job': job,
        'species_list': species_list,
        'stats': stats,
        'status_filter': status_filter,
        'sort_by': sort_by,
        'sync_message': sync_message,
    }
    
    return render(request, 'importer_dashboard/species_queue.html', context)


@login_required
def species_detail(request, job_id, species_id):
    """
    Detailed view of a single species showing all candidates and voting reactions
    """
    job = get_object_or_404(ClusterJob, id=job_id)
    species = get_object_or_404(Species, id=species_id, job=job)
    
    # Get all candidates with their votes
    candidates = species.candidates.filter(is_blocked=False).annotate(
        vote_count_db=Count('votes'),
        unique_vote_count_db=Count(
            Case(
                When(votes__is_unique=True, then=1),
                output_field=IntegerField()
            )
        ),
        thermo_match_count=Count('thermo_matches')
    ).order_by('-unique_vote_count_db', '-vote_count_db', 'enthalpy_discrepancy')
    
    # Build voting matrix
    # Get all reactions this species participates in
    all_chemkin_reactions = set()
    for candidate in candidates:
        votes = Vote.objects.filter(species=species, candidate=candidate)
        for vote in votes:
            all_chemkin_reactions.add(vote.chemkin_reaction)
    
    # Build matrix: reaction -> candidate -> vote details
    voting_matrix = {}
    identified_labels = list(Species.objects.filter(
        job=job,
        identification_status__in=['confirmed', 'processed']
    ).values_list('chemkin_label', flat=True))
    
    for reaction in sorted(all_chemkin_reactions):
        voting_matrix[reaction] = {
            'formatted': format_reaction_string(reaction, identified_labels),
            'votes': {}
        }
        
        for candidate in candidates:
            vote = Vote.objects.filter(
                species=species,
                candidate=candidate,
                chemkin_reaction=reaction
            ).first()
            
            if vote:
                voting_matrix[reaction]['votes'][candidate.id] = {
                    'family': vote.rmg_reaction_family,
                    'rmg_reaction': vote.rmg_reaction,
                    'is_unique': vote.is_unique
                }
    
    # Get thermo matches for each candidate
    candidate_data = []
    for candidate in candidates:
        thermo_matches = ThermoMatch.objects.filter(
            species=species,
            candidate=candidate
        ).order_by('-name_matches', 'library_name')
        
        # Add absolute enthalpy for template
        candidate.enthalpy_discrepancy_abs = abs(candidate.enthalpy_discrepancy)
        
        # Calculate confidence score
        confidence = calculate_confidence_score(
            vote_count=candidate.vote_count_db,
            unique_votes=candidate.unique_vote_count_db,
            enthalpy_diff=candidate.enthalpy_discrepancy,
            thermo_matches=thermo_matches.count()
        )
        
        candidate_data.append({
            'candidate': candidate,
            'confidence': confidence,
            'thermo_matches': thermo_matches,
            'vote_count': candidate.vote_count_db,
            'unique_vote_count': candidate.unique_vote_count_db,
            'image_url': get_species_image_url(candidate.smiles),
        })
    
    # Get reactions this species appears in (NEW FEATURE!)
    # Use regex for exact word boundary matching to avoid false positives
    # (e.g., "CH2" should NOT match "CH2O" or "C2CH2")
    import re
    species_pattern = r'(^|,|\s)' + re.escape(species.chemkin_label) + r'(,|\s|$)'
    
    species_reactions = ChemkinReaction.objects.filter(
        Q(reactants__iregex=species_pattern) |
        Q(products__iregex=species_pattern),
        job=job
    ).order_by('equation')[:50]  # Show first 50 reactions
    
    context = {
        'job': job,
        'species': species,
        'candidates': candidate_data,
        'voting_matrix': voting_matrix,
        'species_reactions': species_reactions,
        'reaction_count': species_reactions.count(),
        'auto_confirm_suggested': False,  # Calculate this
    }
    
    # Check if auto-confirm is suggested
    if len(candidate_data) == 1:
        top = candidate_data[0]
        context['auto_confirm_suggested'] = should_auto_confirm(
            vote_count=top['vote_count'],
            unique_votes=top['unique_vote_count'],
            enthalpy_diff=top['candidate'].enthalpy_discrepancy,
            thermo_matches=len(top['thermo_matches']),
            is_only_candidate=True
        )
    
    return render(request, 'importer_dashboard/species_detail.html', context)


@login_required
@require_POST
def confirm_match(request, job_id, species_id):
    """
    User confirms a species match
    """
    job = get_object_or_404(ClusterJob, id=job_id)
    species = get_object_or_404(Species, id=species_id, job=job)
    
    candidate_id = request.POST.get('candidate_id')
    if not candidate_id:
        return JsonResponse({'success': False, 'error': 'No candidate specified'}, status=400)
    
    try:
        with transaction.atomic():
            candidate = get_object_or_404(CandidateSpecies, id=candidate_id, species=species)
            
            # Update species
            species.identification_status = 'confirmed'
            species.rmg_label = candidate.rmg_label
            species.rmg_index = candidate.rmg_index
            species.smiles = candidate.smiles
            species.enthalpy_discrepancy = candidate.enthalpy_discrepancy
            species.identified_by = request.user
            species.identification_method = 'manual'
            species.confirmed_at = timezone.now()
            species.save()
            
            # Log the confirmation
            dashboard_logger.info(
                f"Species confirmed: {species.chemkin_label} → {candidate.smiles}",
                "species_identification",
                job_id=job.id,
                job_name=job.name,
                details={
                    'chemkin_label': species.chemkin_label,
                    'smiles': candidate.smiles,
                    'rmg_label': candidate.rmg_label,
                    'enthalpy_diff': candidate.enthalpy_discrepancy,
                    'vote_count': candidate.vote_count,
                    'identified_by': request.user.username
                }
            )
            
            # Update job statistics
            job.confirmed_species = Species.objects.filter(
                job=job,
                identification_status__in=['confirmed', 'processed']
            ).count()
            job.save()
            
            messages.success(
                request,
                f"Confirmed: {species.chemkin_label} = {candidate.smiles} "
                f"(ΔH = {candidate.enthalpy_discrepancy:.1f} kJ/mol)"
            )
            
            return JsonResponse({
                'success': True,
                'species_label': species.chemkin_label,
                'smiles': candidate.smiles,
                'redirect_url': f"/dashboard/job/{job_id}/species-queue/"
            })
            
    except Exception as e:
        logger.error(f"Error confirming match: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def block_match(request, job_id, species_id):
    """
    User blocks an incorrect match
    """
    job = get_object_or_404(ClusterJob, id=job_id)
    species = get_object_or_404(Species, id=species_id, job=job)
    
    candidate_id = request.POST.get('candidate_id')
    reason = request.POST.get('reason', '')
    
    if not candidate_id:
        return JsonResponse({'success': False, 'error': 'No candidate specified'}, status=400)
    
    try:
        with transaction.atomic():
            candidate = get_object_or_404(CandidateSpecies, id=candidate_id, species=species)
            
            # Mark candidate as blocked
            candidate.is_blocked = True
            candidate.blocked_by = request.user
            candidate.block_reason = reason
            candidate.save()
            
            # Create blocked match record
            BlockedMatch.objects.get_or_create(
                job=job,
                chemkin_label=species.chemkin_label,
                smiles=candidate.smiles,
                defaults={
                    'rmg_label': candidate.rmg_label,
                    'blocked_by': request.user,
                    'reason': reason
                }
            )
            
            # Clear votes for this candidate
            Vote.objects.filter(species=species, candidate=candidate).delete()
            
            # Recalculate vote counts
            candidate.vote_count = 0
            candidate.unique_vote_count = 0
            candidate.save()
            
            # Re-prune votes for remaining candidates
            prune_common_votes(species)
            
            dashboard_logger.info(
                f"Match blocked: {species.chemkin_label} ≠ {candidate.smiles}",
                "species_identification",
                job_id=job.id,
                job_name=job.name,
                details={
                    'chemkin_label': species.chemkin_label,
                    'blocked_smiles': candidate.smiles,
                    'reason': reason,
                    'blocked_by': request.user.username
                }
            )
            
            messages.warning(
                request,
                f"Blocked match: {species.chemkin_label} ≠ {candidate.smiles}"
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Match blocked successfully'
            })
            
    except Exception as e:
        logger.error(f"Error blocking match: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def submit_smiles(request, job_id, species_id):
    """
    User manually submits SMILES for a species
    """
    job = get_object_or_404(ClusterJob, id=job_id)
    species = get_object_or_404(Species, id=species_id, job=job)
    
    smiles = request.POST.get('smiles', '').strip()
    
    if not smiles:
        return JsonResponse({'success': False, 'error': 'SMILES is required'}, status=400)
    
    try:
        # Validate SMILES (requires RMG or RDKit)
        # For now, basic validation
        if not smiles or len(smiles) > 500:
            return JsonResponse({
                'success': False,
                'error': 'Invalid SMILES string'
            }, status=400)
        
        with transaction.atomic():
            # Create or get candidate
            # Note: This is simplified - real implementation needs RMG to:
            # 1. Parse SMILES and create Molecule
            # 2. Check formula matches
            # 3. Calculate thermodynamics
            # 4. Get enthalpy discrepancy
            
            # For now, create a manual candidate
            candidate, created = CandidateSpecies.objects.get_or_create(
                species=species,
                smiles=smiles,
                defaults={
                    'rmg_label': f'Manual_{species.chemkin_label}',
                    'rmg_index': 0,  # Placeholder
                    'enthalpy_discrepancy': 0.0,  # Would calculate
                    'vote_count': 0,
                    'unique_vote_count': 0,
                }
            )
            
            # Set as tentative match
            species.identification_status = 'tentative'
            species.rmg_label = candidate.rmg_label
            species.smiles = smiles
            species.identified_by = request.user
            species.identification_method = 'manual_smiles'
            species.save()
            
            dashboard_logger.info(
                f"Manual SMILES submitted: {species.chemkin_label} → {smiles}",
                "species_identification",
                job_id=job.id,
                job_name=job.name,
                details={
                    'chemkin_label': species.chemkin_label,
                    'smiles': smiles,
                    'submitted_by': request.user.username
                }
            )
            
            messages.info(
                request,
                f"Tentative match set: {species.chemkin_label} = {smiles}. "
                "Review and confirm when ready."
            )
            
            return JsonResponse({
                'success': True,
                'species_label': species.chemkin_label,
                'smiles': smiles,
                'image_url': get_species_image_url(smiles),
                'message': 'SMILES submitted as tentative match'
            })
            
    except Exception as e:
        logger.error(f"Error submitting SMILES: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def export_identifications(request, job_id):
    """
    Export confirmed species identifications as SMILES.txt
    """
    job = get_object_or_404(ClusterJob, id=job_id)
    
    try:
        content = export_smiles_file(job)
        
        response = HttpResponse(content, content_type='text/plain')
        response['Content-Disposition'] = f'attachment; filename="SMILES_{job.name.replace("/", "_")}.txt"'
        
        return response
        
    except Exception as e:
        logger.error(f"Error exporting identifications: {e}")
        messages.error(request, f"Failed to export: {str(e)}")
        return redirect('importer_dashboard:species_queue', job_id=job_id)


@login_required
def export_blocked(request, job_id):
    """
    Export blocked matches as BLOCKED.txt
    """
    job = get_object_or_404(ClusterJob, id=job_id)
    
    try:
        content = export_blocked_file(job)
        
        response = HttpResponse(content, content_type='text/plain')
        response['Content-Disposition'] = f'attachment; filename="BLOCKED_{job.name.replace("/", "_")}.txt"'
        
        return response
        
    except Exception as e:
        logger.error(f"Error exporting blocked matches: {e}")
        messages.error(request, f"Failed to export: {str(e)}")
        return redirect('importer_dashboard:species_queue', job_id=job_id)


@login_required
def species_statistics(request, job_id):
    """
    Show detailed statistics about species identification progress
    """
    job = get_object_or_404(ClusterJob, id=job_id)
    
    # Aggregate statistics
    stats = {
        'total': Species.objects.filter(job=job).count(),
        'by_status': {},
        'by_formula': {},
        'vote_distribution': [],
        'confidence_distribution': [],
    }
    
    # Count by status
    for status, label in Species.IDENTIFICATION_STATUS:
        count = Species.objects.filter(job=job, identification_status=status).count()
        stats['by_status'][label] = count
    
    # Count by formula (top 10)
    formula_counts = Species.objects.filter(job=job).values('formula').annotate(
        count=Count('id')
    ).order_by('-count')[:10]
    stats['by_formula'] = list(formula_counts)
    
    # Vote distribution
    vote_ranges = [
        (0, 0, 'No votes'),
        (1, 3, '1-3 votes'),
        (4, 10, '4-10 votes'),
        (11, 20, '11-20 votes'),
        (21, float('inf'), '20+ votes'),
    ]
    
    for min_v, max_v, label in vote_ranges:
        if max_v == float('inf'):
            count = Species.objects.filter(
                job=job,
                votes__isnull=False
            ).annotate(
                vote_count=Count('votes')
            ).filter(vote_count__gte=min_v).distinct().count()
        else:
            count = Species.objects.filter(
                job=job,
                votes__isnull=False
            ).annotate(
                vote_count=Count('votes')
            ).filter(vote_count__gte=min_v, vote_count__lte=max_v).distinct().count()
        
        stats['vote_distribution'].append({'range': label, 'count': count})
    
    context = {
        'job': job,
        'stats': stats,
    }
    
    return render(request, 'importer_dashboard/species_statistics.html', context)


@login_required
@require_POST
def auto_confirm_all(request, job_id):
    """
    Auto-confirm all high-confidence matches
    """
    job = get_object_or_404(ClusterJob, id=job_id)
    
    confirmed_count = 0
    errors = []
    
    try:
        # Get all unidentified species with exactly one candidate
        species_list = Species.objects.filter(
            job=job,
            identification_status='unidentified'
        ).annotate(
            candidate_count=Count('candidates', filter=Q(candidates__is_blocked=False))
        ).filter(candidate_count=1)
        
        for species in species_list:
            candidate = species.candidates.filter(is_blocked=False).first()
            
            if not candidate:
                continue
            
            # Check if should auto-confirm
            if should_auto_confirm(
                vote_count=candidate.vote_count,
                unique_votes=candidate.unique_vote_count,
                enthalpy_diff=candidate.enthalpy_discrepancy,
                thermo_matches=candidate.thermo_matches.count(),
                is_only_candidate=True
            ):
                try:
                    with transaction.atomic():
                        species.identification_status = 'confirmed'
                        species.rmg_label = candidate.rmg_label
                        species.rmg_index = candidate.rmg_index
                        species.smiles = candidate.smiles
                        species.enthalpy_discrepancy = candidate.enthalpy_discrepancy
                        species.identified_by = request.user
                        species.identification_method = 'auto'
                        species.confirmed_at = timezone.now()
                        species.save()
                        
                        confirmed_count += 1
                except Exception as e:
                    errors.append(f"{species.chemkin_label}: {str(e)}")
        
        # Update job stats
        job.confirmed_species = Species.objects.filter(
            job=job,
            identification_status__in=['confirmed', 'processed']
        ).count()
        job.save()
        
        dashboard_logger.info(
            f"Auto-confirmed {confirmed_count} species",
            "species_identification",
            job_id=job.id,
            job_name=job.name,
            details={
                'confirmed_count': confirmed_count,
                'errors': len(errors),
                'triggered_by': request.user.username
            }
        )
        
        if confirmed_count > 0:
            messages.success(request, f"Auto-confirmed {confirmed_count} high-confidence matches")
        else:
            messages.info(request, "No matches met auto-confirmation criteria")
        
        if errors:
            messages.warning(request, f"{len(errors)} errors occurred during auto-confirmation")
        
        return JsonResponse({
            'success': True,
            'confirmed_count': confirmed_count,
            'errors': errors
        })
        
    except Exception as e:
        logger.error(f"Error in auto-confirm: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def sync_votes_manual(request, job_id):
    """
    Manually trigger incremental vote sync from cluster
    
    This syncs vote data, identified species, and blocked matches
    using the new SSH-based incremental sync system.
    """
    job = get_object_or_404(ClusterJob, id=job_id)
    
    try:
        from .incremental_sync import sync_job_votes_incremental
        
        dashboard_logger.info(f"Manual sync triggered for job {job.name}")
        result = sync_job_votes_incremental(job)
        
        if result['success']:
            messages.success(
                request,
                f"✓ Sync complete: {result['votes_synced']} votes, "
                f"{result['identified_synced']} identified species, "
                f"{result['blocked_synced']} blocked matches "
                f"({'incremental' if result.get('incremental') else 'full sync'})"
            )
            dashboard_logger.info(f"Manual sync succeeded: {result['message']}")
        else:
            messages.error(request, f"✗ Sync failed: {result['message']}")
            dashboard_logger.error(f"Manual sync failed: {result['message']}")
            
    except Exception as e:
        messages.error(request, f"✗ Sync error: {str(e)}")
        dashboard_logger.error(f"Manual sync exception: {e}", exc_info=True)
    
    # Redirect back to species queue
    return redirect('importer_dashboard:species_queue', job_id=job_id)
