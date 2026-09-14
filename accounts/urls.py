from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import AdminLoginView, AdminLogoutView, AdminSessionView

urlpatterns = [
    path('login/', AdminLoginView.as_view(), name='admin-login'),
    path('refresh/', TokenRefreshView.as_view(), name='admin-refresh'),
    path('session/', AdminSessionView.as_view(), name='admin-session'),
    path('logout/', AdminLogoutView.as_view(), name='admin-logout'),
]
