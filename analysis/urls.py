"""
Analysis URL Configuration
"""

from django.urls import path
from . import views

app_name = "analysis"

urlpatterns = [
    # Dashboard
    path("", views.AnalysisDashboardView.as_view(), name="dashboard"),

    # Simulation runs
    path("run/create/", views.SimulationCreateView.as_view(), name="run-create"),
    path("run/<int:pk>/", views.SimulationDetailView.as_view(), name="run-detail"),
    path("run/<int:pk>/execute/", views.SimulationRunView.as_view(), name="run-execute"),
    path("run/<int:pk>/rerun/", views.SimulationRerunView.as_view(), name="run-rerun"),
    path("runs/", views.SimulationListView.as_view(), name="run-list"),

    # Coverage & comparison
    path("coverage/", views.CoverageMatrixView.as_view(), name="coverage-matrix"),
    path("compare/", views.CompareModelsView.as_view(), name="compare-models"),

    # API endpoints
    path("api/datasets-by-fuel/", views.DatasetsByFuelView.as_view(), name="api-datasets-by-fuel"),
    path("api/models/", views.ModelsByKeywordView.as_view(), name="api-models-by-keyword"),
    path("api/model-counts/", views.ModelCountsView.as_view(), name="api-model-counts"),
    path("api/run/<int:pk>/status/", views.SimulationStatusView.as_view(), name="api-run-status"),
    path("api/run/<int:pk>/log/", views.SimulationLogView.as_view(), name="api-run-log"),
]
