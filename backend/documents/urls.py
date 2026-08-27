from django.urls import path

from .views import (
    DocumentDetailView,
    DocumentListCreateView,
    DocumentReviewView,
    DocumentRetryView,
    HealthView,
    StatsView,
)

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("stats/", StatsView.as_view(), name="stats"),
    path("documents/", DocumentListCreateView.as_view(), name="document-list"),
    path("documents/<uuid:pk>/", DocumentDetailView.as_view(), name="document-detail"),
    path("documents/<uuid:pk>/retry/", DocumentRetryView.as_view(), name="document-retry"),
    path("documents/<uuid:pk>/review/", DocumentReviewView.as_view(), name="document-review"),
]
