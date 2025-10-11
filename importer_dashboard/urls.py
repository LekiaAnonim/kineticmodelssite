"""
URL configuration for the importer dashboard
"""

from django.urls import path
from . import views

app_name = 'importer_dashboard'

urlpatterns = [
    # Main dashboard
    path('', views.dashboard_index, name='index'),
    
    # Job management
    path('job/<int:job_id>/', views.job_detail, name='job_detail'),
    path('job/<int:job_id>/start/', views.job_start, name='job_start'),
    path('job/<int:job_id>/kill/', views.job_kill, name='job_kill'),
    path('job/<int:job_id>/pause/', views.job_pause, name='job_pause'),
    path('job/<int:job_id>/resume/', views.job_resume, name='job_resume'),
    path('job/<int:job_id>/log/', views.job_log_view, name='job_log'),
    path('job/<int:job_id>/console/', views.job_console_output_view, name='job_console_output'),
    path('job/<int:job_id>/error-log/', views.job_error_log_view, name='job_error_log'),
    path('job/<int:job_id>/interactive/', views.interactive_session, name='interactive_session'),
    
    # Dashboard actions
    path('refresh-jobs/', views.refresh_jobs, name='refresh_jobs'),
    path('refresh-progress/', views.refresh_progress, name='refresh_progress'),
    path('reconnect/', views.reconnect, name='reconnect'),
    path('git-pull/', views.git_pull, name='git_pull'),
    path('settings/', views.settings_view, name='settings'),
    
    # API endpoints
    path('api/job/<int:job_id>/progress/', views.api_job_progress, name='api_job_progress'),
    path('api/job/<int:job_id>/identify/', views.api_species_identify, name='api_species_identify'),
    path('api/job/<int:job_id>/test-progress/', views.test_progress_fetch, name='test_progress_fetch'),
    
    # Real-time logging
    path('logs/stream/', views.log_stream, name='log_stream'),
    path('logs/get/', views.get_logs, name='get_logs'),
    path('logs/clear/', views.clear_logs, name='clear_logs'),
    path('logs/test/', views.log_stream_test, name='log_stream_test'),
]
