"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path

from core import views as core_views

urlpatterns = [
    path('', core_views.home, name='home'),
    path('api/analyze/', core_views.analyze_text, name='api_analyze'),
    path('api/reports/latest/', core_views.latest_reports, name='api_reports_latest'),
    path('api/auth/login/', core_views.auth_login_api, name='api_auth_login'),
    path('api/auth/register/', core_views.auth_register_api, name='api_auth_register'),
    path('api/auth/logout/', core_views.auth_logout_api, name='api_auth_logout'),
    path('api/auth/me/', core_views.auth_me_api, name='api_auth_me'),
    path('api/auth/profile/', core_views.auth_profile_api, name='api_auth_profile'),
    path('api/auth/withdraw/', core_views.auth_withdraw_api, name='api_auth_withdraw'),
    path('report/', core_views.report_page, name='report_page'),
    path('report/pdf/', core_views.report_pdf, name='report_pdf'),
    path('report/file/<int:report_id>/', core_views.report_file, name='report_file'),
    path('admin/', admin.site.urls),
]
