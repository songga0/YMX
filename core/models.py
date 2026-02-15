from django.conf import settings
from django.db import models


class Report(models.Model):
    """리포트 메타정보. MinIO 적재 URL·키 저장. 로그인 사용자당 최대 3개 유지."""

    report_name = models.CharField("리포트명", max_length=255)
    report_url = models.URLField(
        "MinIO 적재 URL",
        max_length=500,
        blank=True,
        help_text="MinIO에 적재된 파일의 URL",
    )
    storage_key = models.CharField(
        "MinIO 객체 키",
        max_length=500,
        blank=True,
        help_text="MinIO 삭제 시 사용하는 객체 키",
    )
    created_at = models.DateTimeField("생성일시", auto_now_add=True)
    person = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reports",
        db_column="person_id",
        verbose_name="로그인 사용자",
    )

    class Meta:
        db_table = "report"
        verbose_name = "리포트"
        verbose_name_plural = "리포트"

    def __str__(self):
        return self.report_name
