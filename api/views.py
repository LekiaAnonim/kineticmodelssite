from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.permissions import IsAdminUser, BasePermission, SAFE_METHODS

from database import models
from api import serializers


class ReadOnly(BasePermission):
    def has_permission(self, request, view):
        return request.method in SAFE_METHODS


class PermissionsViewSet(viewsets.ModelViewSet):
    """Read access is public; create, update, and delete require an admin user."""

    permission_classes = [IsAdminUser | ReadOnly]


@extend_schema(tags=["species"])
class FormulaViewSet(PermissionsViewSet):
    queryset = models.Formula.objects.all()
    serializer_class = serializers.FormulaSerializer


@extend_schema(tags=["species"])
class IsomerViewSet(PermissionsViewSet):
    queryset = models.Isomer.objects.all()
    serializer_class = serializers.IsomerSerializer


@extend_schema(tags=["species"])
@extend_schema_view(
    list=extend_schema(summary="List canonical species"),
    retrieve=extend_schema(summary="Retrieve a canonical species by ID"),
)
class SpeciesViewSet(PermissionsViewSet):
    queryset = models.Species.objects.all()
    serializer_class = serializers.SpeciesSerializer


@extend_schema(tags=["reactions"])
@extend_schema_view(
    list=extend_schema(summary="List reactions"),
    retrieve=extend_schema(summary="Retrieve a reaction (with stoichiometry) by ID"),
)
class ReactionViewSet(PermissionsViewSet):
    queryset = models.Reaction.objects.all()
    serializer_class = serializers.ReactionSerializer


@extend_schema(tags=["thermo-transport"])
class ThermoViewSet(PermissionsViewSet):
    queryset = models.Thermo.objects.all()
    serializer_class = serializers.ThermoSerializer


@extend_schema(tags=["thermo-transport"])
class TransportViewSet(PermissionsViewSet):
    queryset = models.Transport.objects.all()
    serializer_class = serializers.TransportSerializer


@extend_schema(tags=["reactions"])
class KineticsViewSet(PermissionsViewSet):
    queryset = models.Kinetics.objects.all()
    serializer_class = serializers.KineticsSerializer


@extend_schema(tags=["models"])
@extend_schema_view(
    list=extend_schema(summary="List kinetic models"),
    retrieve=extend_schema(summary="Retrieve a kinetic model (with components) by ID"),
)
class KineticModelViewSet(PermissionsViewSet):
    queryset = models.KineticModel.objects.all()
    serializer_class = serializers.KineticModelSerializer


@extend_schema(tags=["bibliography"])
class SourceViewSet(PermissionsViewSet):
    queryset = models.Source.objects.all()
    serializer_class = serializers.SourceSerializer


@extend_schema(tags=["bibliography"])
class AuthorViewSet(PermissionsViewSet):
    queryset = models.Author.objects.all()
    serializer_class = serializers.AuthorSerializer


@extend_schema(tags=["species"])
class StructureViewSet(PermissionsViewSet):
    queryset = models.Structure.objects.all()
    serializer_class = serializers.StructureSerializer
