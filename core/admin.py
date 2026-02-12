from django.contrib import admin
from django.utils.html import format_html
from .models import Report


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("id", "report_name", "created_at", "report_url_link")
    list_display_links = ("report_name",)
    list_filter = ("created_at",)
    search_fields = ("report_name",)
    ordering = ("-created_at",)

    def report_url_link(self, obj):
        if obj.report_url:
            return format_html('<a href="{}" target="_blank">MinIO 링크</a>', obj.report_url)
        return "-"

    report_url_link.short_description = "MinIO URL"
