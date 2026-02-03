import functools
from itertools import zip_longest
from collections import defaultdict

from dal import autocomplete
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.urls import reverse, reverse_lazy
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.views import View
from django.views.generic import TemplateView, DetailView, ListView
from django.views.generic.edit import FormView, CreateView, UpdateView, DeleteView
from django_filters.views import FilterView
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.utils.html import format_html
from rmgpy.molecule.draw import MoleculeDrawer

from database import models
from .models import (
    Species,
    Structure,
    KineticModel,
    Thermo,
    Transport,
    Source,
    Reaction,
    Kinetics,
    Author,
    Authorship,
)
from .filters import SpeciesFilter, ReactionFilter, SourceFilter
from .forms import RegistrationForm, SourceForm, AuthorshipFormSet, KineticModelForm, AuthorForm
from database.templatetags import renders
from database.services import exports


class SidebarLookup:
    def __init__(self, cls, *args, **kwargs):
        cls.get = self.lookup_get(cls.get)
        cls.get_context_data = self.lookup_get_context_data(cls.get_context_data)
        self.cls = cls

    def as_view(self, *args, **kwargs):
        return self.cls.as_view(*args, **kwargs)

    def lookup_get(self, func):
        @functools.wraps(func)
        def inner(self, request, *args, **kwargs):
            species_pk = request.GET.get("species_pk")
            reaction_pk = request.GET.get("reaction_pk")
            source_pk = request.GET.get("source_pk")
            if species_pk:
                try:
                    Species.objects.get(pk=species_pk)
                    return HttpResponseRedirect(reverse("species-detail", args=[species_pk]))
                except Species.DoesNotExist:
                    response = func(self, request, *args, **kwargs)
                    return response
            elif reaction_pk:
                try:
                    Reaction.objects.get(pk=reaction_pk)
                    return HttpResponseRedirect(reverse("reaction-detail", args=[reaction_pk]))
                except Reaction.DoesNotExist:
                    return func(self, request, *args, **kwargs)
            elif source_pk:
                try:
                    Source.objects.get(pk=source_pk)
                    return HttpResponseRedirect(reverse("source-detail", args=[source_pk]))
                except Source.DoesNotExist:
                    return func(self, request, *args, **kwargs)
            else:
                return func(self, request, *args, **kwargs)

        return inner

    def lookup_get_context_data(self, func):
        @functools.wraps(func)
        def inner(self, *args, **kwargs):
            context = func(self, *args, **kwargs)
            species_pk = self.request.GET.get("species_pk")
            reaction_pk = self.request.GET.get("reaction_pk")
            source_pk = self.request.GET.get("source_pk")
            species_invalid = "Species with that ID wasn't found"
            reaction_invalid = "Reaction with that ID wasn't found"
            source_invalid = "Source with that ID wasn't found"
            if species_pk:
                try:
                    Species.objects.get(pk=species_pk)
                except Species.DoesNotExist:
                    context["species_invalid"] = species_invalid
                    return context
            if reaction_pk:
                try:
                    Reaction.objects.get(pk=reaction_pk)
                    return context
                except Reaction.DoesNotExist:
                    context["reaction_invalid"] = reaction_invalid
                    return context
            if source_pk:
                try:
                    Source.objects.get(pk=source_pk)
                    return context
                except Source.DoesNotExist:
                    context["source_invalid"] = source_invalid
                    return context
            else:
                return context

        return inner


@SidebarLookup
class BaseView(TemplateView):
    template_name = "database/home.html"
    # Get counts for display on home page
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["species_count"] = Species.objects.count()
        context["model_count"] = KineticModel.objects.count()
        context["reaction_count"] = Reaction.objects.count()
        context["source_count"] = Source.objects.count()
        return context

class KineticModelFilterView(ListView):
    model = KineticModel
    paginate_by = 25
    queryset = KineticModel.objects.order_by("id")
    template_name = "database/kineticmodel_filter.html"

@SidebarLookup
class SpeciesFilterView(FilterView):
    filterset_class = SpeciesFilter
    paginate_by = 25
    queryset = Species.objects.order_by("id")


@SidebarLookup
class SourceFilterView(FilterView):
    filterset_class = SourceFilter
    paginate_by = 25


@SidebarLookup
class ReactionFilterView(FilterView):
    filterset_class = ReactionFilter
    paginate_by = 25


@SidebarLookup
class SpeciesDetail(DetailView):
    model = Species
    paginate_per_page = 10

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        species = self.get_object()
        structures = Structure.objects.filter(isomer__species=species)
        reactions = Reaction.objects.filter(species=species).order_by("id")

        names_models = defaultdict(list)
        for values in species.speciesname_set.values(
            "name", "kinetic_model__model_name", "kinetic_model"
        ):
            name, model_name, model_id = values.values()
            if name:
                names_models[name].append((model_name, model_id))

        context["names_models"] = sorted(list(names_models.items()), key=lambda x: -len(x[1]))
        context["adjlists"] = structures.values_list("adjacency_list", flat=True)
        context["smiles"] = structures.values_list("smiles", flat=True)
        context["isomer_inchis"] = species.isomers.values_list("inchi", flat=True)
        context["thermo_list"] = Thermo.objects.filter(species=species)
        context["transport_list"] = Transport.objects.filter(species=species)
        context["structures"] = structures

        paginator = Paginator(reactions, self.paginate_per_page)
        page = self.request.GET.get("page", 1)
        try:
            paginated_reactions = paginator.page(page)
        except PageNotAnInteger:
            paginated_reactions = paginator.page(1)
        except EmptyPage:
            paginated_reactions = paginator.page(paginator.num_pages)

        context["reactions"] = paginated_reactions
        context["page"] = page

        return context


@SidebarLookup
class ThermoDetail(DetailView):
    model = Thermo
    context_object_name = "thermo"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        thermo = self.get_object()
        thermo_comments = thermo.thermocomment_set.all()
        context["thermo_comments"] = thermo_comments
        return context


@SidebarLookup
class TransportDetail(DetailView):
    model = Transport

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        transport = self.get_object()
        kinetic_model = KineticModel.objects.get(transport=transport)
        context["species_name"] = kinetic_model.speciesname_set.get(species=transport.species).name

        return context


@SidebarLookup
class SourceDetail(DetailView):
    model = Source

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        source = self.get_object()
        kinetic_models = source.kineticmodel_set.all()
        context["source"] = source
        context["kinetic_models"] = kinetic_models
        return context


@SidebarLookup
class ReactionDetail(DetailView):
    model = Reaction
    context_object_name = "reaction"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        reaction = self.get_object()

        context["reactants"] = reaction.reactants()
        context["products"] = reaction.products()
        context["kinetics_modelnames"] = [
            (k, k.kineticmodel_set.values_list("model_name", flat=True))
            for k in reaction.kinetics_set.all()
        ]

        return context


@SidebarLookup
class KineticModelDetail(DetailView):
    model = KineticModel
    context_object_name = "kinetic_model"
    paginate_per_page = 25

    def get_context_data(self, **kwargs):
        kinetic_model = self.get_object()
        context = super().get_context_data(**kwargs)
        
        # Get thermo and transport comments
        thermo_comments = kinetic_model.thermocomment_set.select_related('thermo__species')
        transport_comments = kinetic_model.transportcomment_set.select_related('transport__species')
        
        # Build dictionaries keyed by species ID for proper matching
        thermo_by_species = {tc.thermo.species_id: tc for tc in thermo_comments}
        transport_by_species = {tc.transport.species_id: tc for tc in transport_comments}
        
        # Get all unique species IDs from both thermo and transport
        all_species_ids = set(thermo_by_species.keys()) | set(transport_by_species.keys())
        
        # Create paired list: (thermo_comment, transport_comment) matched by species
        thermo_transport = []
        for species_id in sorted(all_species_ids):
            thermo_comment = thermo_by_species.get(species_id)
            transport_comment = transport_by_species.get(species_id)
            thermo_transport.append((thermo_comment, transport_comment))
        
        kinetics_data = kinetic_model.kineticscomment_set.order_by("kinetics__reaction__id")

        paginator1 = Paginator(thermo_transport, self.paginate_per_page)
        page1 = self.request.GET.get("page1", 1)
        try:
            paginated_thermo_transport = paginator1.page(page1)
        except PageNotAnInteger:
            paginated_thermo_transport = paginator1.page(1)
        except EmptyPage:
            paginated_thermo_transport = paginator1.page(paginator1.num_pages)

        paginator2 = Paginator(kinetics_data, self.paginate_per_page)
        page2 = self.request.GET.get("page2", 1)
        try:
            paginated_kinetics_data = paginator2.page(page2)
        except PageNotAnInteger:
            paginated_kinetics_data = paginator2.page(1)
        except EmptyPage:
            paginated_kinetics_data = paginator2.page(paginator2.num_pages)

        context["thermo_transport"] = paginated_thermo_transport
        context["kinetics_data"] = paginated_kinetics_data
        context["page1"] = page1
        context["page2"] = page2
        context["source"] = kinetic_model.source

        return context


class KineticModelDownloadView(View):
    def get(self, request, pk, format):
        kinetic_model = get_object_or_404(KineticModel, pk=pk)
        strict_value = request.GET.get("strict", "").strip().lower()
        strict = strict_value in {"1", "true", "yes", "on"}

        try:
            if format == "chemkin":
                result = exports.build_chemkin_bundle(kinetic_model, strict=strict)
            elif format in {"cantera", "cantera-yaml", "yaml"}:
                result = exports.build_cantera_yaml(kinetic_model, strict=strict)
            else:
                return HttpResponseBadRequest("Unknown download format.")
        except exports.ExportError as exc:
            return HttpResponseBadRequest(str(exc))

        response = HttpResponse(result.content, content_type=result.content_type)
        response["Content-Disposition"] = f'attachment; filename="{result.filename}"'
        return response


@SidebarLookup
class KineticsDetail(DetailView):
    model = Kinetics
    context_object_name = "kinetics"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        kinetics = self.get_object()
        context["table_data"] = kinetics.data.table_data()
        # context["efficiencies"] = kinetics.data.efficiency_set.all()
        context["kinetics_comments"] = kinetics.kineticscomment_set.order_by("kinetic_model__id")

        return context


class DrawStructure(View):
    def get(self, request, pk):
        structure = Structure.objects.get(pk=pk)
        molecule = structure.to_rmg()
        (
            surface,
            _,
            _,
        ) = MoleculeDrawer().draw(molecule, file_format="png")
        response = HttpResponse(surface.write_to_png(), content_type="image/png")

        return response


class RegistrationView(FormView):
    template_name = "database/register.html"
    form_class = RegistrationForm
    success_url = "/"

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)

        return super().form_valid(form)


class AutocompleteView(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        queryset = self.model.objects.all()

        if self.q:
            for query in self.queries:
                try:
                    filtered = queryset.filter(**{query: self.q})
                    if filtered:
                        return filtered
                except ValueError:
                    continue

        return queryset if not self.q else []


class SpeciesAutocompleteView(AutocompleteView):
    model = Species
    queries = [
        "speciesname__name__istartswith",
        "isomers__formula__formula",
        "prime_id",
        "cas_number",
        "id",
    ]

    def get_result_label(self, item):
        return renders.render_species_list_card(item)

    def get_selected_result_label(self, item):
        return str(item)


class IsomerAutocompleteView(AutocompleteView):
    model = models.Isomer
    queries = ["inchi__istartswith", "formula__formula__istartswith", "id"]


class StructureAutocompleteView(AutocompleteView):
    model = models.Structure
    queries = ["adjacency_list__istartswith", "smiles__istartswith", "multiplicity", "id"]

    def get_result_label(self, item):
        draw_url = reverse("draw-structure", args=[item.pk])
        return format_html(f'<img src="{draw_url}" />')


# =============================================================================
# Source CRUD Views
# =============================================================================

class SourceCreateView(LoginRequiredMixin, CreateView):
    """Create a new Source (publication)."""
    model = Source
    form_class = SourceForm
    template_name = 'database/source_form.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.POST:
            context['authorship_formset'] = AuthorshipFormSet(self.request.POST, instance=self.object)
        else:
            context['authorship_formset'] = AuthorshipFormSet(instance=self.object)
        context['form_title'] = 'Add New Source'
        context['submit_text'] = 'Create Source'
        return context
    
    def form_valid(self, form):
        context = self.get_context_data()
        authorship_formset = context['authorship_formset']
        
        if authorship_formset.is_valid():
            self.object = form.save()
            authorship_formset.instance = self.object
            
            # Process authorships, creating new authors if needed
            for authorship_form in authorship_formset:
                if authorship_form.cleaned_data and not authorship_form.cleaned_data.get('DELETE'):
                    firstname = authorship_form.cleaned_data.get('author_firstname', '').strip()
                    lastname = authorship_form.cleaned_data.get('author_lastname', '').strip()
                    author = authorship_form.cleaned_data.get('author')
                    
                    # Create new author if names provided but no author selected
                    if firstname and lastname and not author:
                        author, _ = Author.objects.get_or_create(
                            firstname=firstname,
                            lastname=lastname
                        )
                        authorship_form.instance.author = author
            
            authorship_formset.save()
            messages.success(self.request, f'Source "{self.object.source_title}" created successfully.')
            return HttpResponseRedirect(self.get_success_url())
        else:
            return self.render_to_response(self.get_context_data(form=form))
    
    def get_success_url(self):
        return reverse('source-detail', kwargs={'pk': self.object.pk})


class SourceUpdateView(LoginRequiredMixin, UpdateView):
    """Update an existing Source."""
    model = Source
    form_class = SourceForm
    template_name = 'database/source_form.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.POST:
            context['authorship_formset'] = AuthorshipFormSet(self.request.POST, instance=self.object)
        else:
            context['authorship_formset'] = AuthorshipFormSet(instance=self.object)
        context['form_title'] = 'Edit Source'
        context['submit_text'] = 'Save Changes'
        return context
    
    def form_valid(self, form):
        context = self.get_context_data()
        authorship_formset = context['authorship_formset']
        
        if authorship_formset.is_valid():
            self.object = form.save()
            
            # Process authorships, creating new authors if needed
            for authorship_form in authorship_formset:
                if authorship_form.cleaned_data and not authorship_form.cleaned_data.get('DELETE'):
                    firstname = authorship_form.cleaned_data.get('author_firstname', '').strip()
                    lastname = authorship_form.cleaned_data.get('author_lastname', '').strip()
                    author = authorship_form.cleaned_data.get('author')
                    
                    if firstname and lastname and not author:
                        author, _ = Author.objects.get_or_create(
                            firstname=firstname,
                            lastname=lastname
                        )
                        authorship_form.instance.author = author
            
            authorship_formset.save()
            messages.success(self.request, f'Source "{self.object.source_title}" updated successfully.')
            return HttpResponseRedirect(self.get_success_url())
        else:
            return self.render_to_response(self.get_context_data(form=form))
    
    def get_success_url(self):
        return reverse('source-detail', kwargs={'pk': self.object.pk})


class SourceDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a Source."""
    model = Source
    template_name = 'database/confirm_delete.html'
    success_url = reverse_lazy('source-search')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['object_type'] = 'Source'
        context['object_name'] = self.object.source_title or f'Source #{self.object.pk}'
        context['cancel_url'] = reverse('source-detail', kwargs={'pk': self.object.pk})
        return context
    
    def delete(self, request, *args, **kwargs):
        source = self.get_object()
        title = source.source_title or f'Source #{source.pk}'
        messages.success(request, f'Source "{title}" deleted successfully.')
        return super().delete(request, *args, **kwargs)


# =============================================================================
# KineticModel CRUD Views
# =============================================================================

class KineticModelCreateView(LoginRequiredMixin, CreateView):
    """Create a new KineticModel."""
    model = KineticModel
    form_class = KineticModelForm
    template_name = 'database/kineticmodel_form.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form_title'] = 'Add New Kinetic Model'
        context['submit_text'] = 'Create Model'
        return context
    
    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, f'Kinetic Model "{self.object.model_name}" created successfully.')
        return HttpResponseRedirect(self.get_success_url())
    
    def get_success_url(self):
        return reverse('kinetic-model-detail', kwargs={'pk': self.object.pk})


class KineticModelUpdateView(LoginRequiredMixin, UpdateView):
    """Update an existing KineticModel."""
    model = KineticModel
    form_class = KineticModelForm
    template_name = 'database/kineticmodel_form.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form_title'] = 'Edit Kinetic Model'
        context['submit_text'] = 'Save Changes'
        return context
    
    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, f'Kinetic Model "{self.object.model_name}" updated successfully.')
        return HttpResponseRedirect(self.get_success_url())
    
    def get_success_url(self):
        return reverse('kinetic-model-detail', kwargs={'pk': self.object.pk})


class KineticModelDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a KineticModel."""
    model = KineticModel
    template_name = 'database/confirm_delete.html'
    success_url = reverse_lazy('kinetic-model-list')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['object_type'] = 'Kinetic Model'
        context['object_name'] = self.object.model_name
        context['cancel_url'] = reverse('kinetic-model-detail', kwargs={'pk': self.object.pk})
        # Warning about related data
        context['warning'] = (
            f'This will also remove all {self.object.species.count()} species names, '
            f'{self.object.kinetics.count()} kinetics comments, '
            f'{self.object.thermo.count()} thermo comments, and '
            f'{self.object.transport.count()} transport comments associated with this model.'
        )
        return context
    
    def delete(self, request, *args, **kwargs):
        model = self.get_object()
        messages.success(request, f'Kinetic Model "{model.model_name}" deleted successfully.')
        return super().delete(request, *args, **kwargs)


# =============================================================================
# Author CRUD Views
# =============================================================================

class AuthorListView(ListView):
    """List all Authors with unique names and aggregated publication counts."""
    model = Author
    template_name = 'database/author_list.html'
    paginate_by = 50
    context_object_name = 'author_list'
    
    def get_queryset(self):
        from django.db.models import Count, Min
        # Get unique authors by firstname+lastname, with publication count and primary ID
        # Uses Min('id') to get a representative ID for each unique author name
        return (
            Author.objects
            .values('firstname', 'lastname')
            .annotate(
                author_id=Min('id'),
                publication_count=Count('authorship', distinct=True)
            )
            .order_by('lastname', 'firstname')
        )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Add total unique authors count
        context['total_authors'] = self.get_queryset().count()
        return context


class AuthorCreateView(LoginRequiredMixin, CreateView):
    """Create a new Author."""
    model = Author
    form_class = AuthorForm
    template_name = 'database/author_form.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form_title'] = 'Add New Author'
        context['submit_text'] = 'Create Author'
        return context
    
    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, f'Author "{self.object.name}" created successfully.')
        return HttpResponseRedirect(self.get_success_url())
    
    def get_success_url(self):
        return reverse('author-list')


class AuthorUpdateView(LoginRequiredMixin, UpdateView):
    """Update an existing Author."""
    model = Author
    form_class = AuthorForm
    template_name = 'database/author_form.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form_title'] = 'Edit Author'
        context['submit_text'] = 'Save Changes'
        return context
    
    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, f'Author "{self.object.name}" updated successfully.')
        return HttpResponseRedirect(self.get_success_url())
    
    def get_success_url(self):
        return reverse('author-list')


class AuthorDeleteView(LoginRequiredMixin, DeleteView):
    """Delete an Author."""
    model = Author
    template_name = 'database/confirm_delete.html'
    success_url = reverse_lazy('author-list')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['object_type'] = 'Author'
        context['object_name'] = self.object.name
        context['cancel_url'] = reverse('author-list')
        pub_count = self.object.authorship_set.count()
        if pub_count:
            context['warning'] = f'This author is associated with {pub_count} publication(s).'
        return context
    
    def delete(self, request, *args, **kwargs):
        author = self.get_object()
        messages.success(request, f'Author "{author.name}" deleted successfully.')
        return super().delete(request, *args, **kwargs)
