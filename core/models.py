from django.db import models


class Report(models.Model):
    """리포트 메타정보. MinIO 적재 URL만 저장."""

    report_name = models.CharField("리포트명", max_length=255)
    report_url = models.URLField(
        "MinIO 적재 URL",
        max_length=500,
        blank=True,
        help_text="MinIO에 적재된 파일의 URL",
    )
    created_at = models.DateTimeField("생성일시", auto_now_add=True)

    class Meta:
        db_table = "report"
        verbose_name = "리포트"
        verbose_name_plural = "리포트"

    def __str__(self):
        return self.report_name
