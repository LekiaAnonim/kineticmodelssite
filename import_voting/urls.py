"""
URL configuration for import voting API
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ImportJobViewSet,
    SpeciesVoteViewSet,
    IdentifiedSpeciesViewSet,
    BlockedMatchViewSet
)

router = DefaultRouter()
router.register(r'jobs', ImportJobViewSet, basename='importjob')
router.register(r'votes', SpeciesVoteViewSet, basename='speciesvote')
router.register(r'identified', IdentifiedSpeciesViewSet, basename='identifiedspecies')
router.register(r'blocked', BlockedMatchViewSet, basename='blockedmatch')

urlpatterns = [
    path('', include(router.urls)),
]
