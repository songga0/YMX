import json
import logging
import os
import re
from datetime import date

from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .models import Report

logger = logging.getLogger(__name__)


def home(request):
    return render(request, "core/home.html")


@require_http_methods(["GET"])
def latest_reports(request):
    """현재 로그인 사용자의 최근 생성 3개 리포트를 JSON으로 반환 (번호, 리포트명, 생성일시)."""
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        qs = Report.objects.filter(person=user).order_by("-created_at")[:3]
    else:
        qs = Report.objects.filter(person__isnull=True).order_by("-created_at")[:3]
    reports = []
    for i, r in enumerate(qs, start=1):
        created = getattr(r, "created_at", None)
        created_display = timezone.localtime(created) if created else None
        reports.append({
            "id": r.pk,
            "no": i,
            "report_name": r.report_name,
            "report_url": r.report_url or "",
            "created_at": created_display.strftime("%Y-%m-%d %H:%M") if created_display else "",
        })
    response = JsonResponse({"reports": reports})
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    return response


@require_http_methods(["POST"])
def analyze_text(request):
    """POST body: {"info": "조건 안내문 텍스트", "personal": "내정보 텍스트"} → OpenAI 분석 후 JSON 반환."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    info = body.get("info") or ""
    personal = body.get("personal") or ""

    if not info.strip() or not personal.strip():
        return JsonResponse({"error": "info와 personal은 필수입니다."}, status=400)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return JsonResponse({"error": "OPENAI_API_KEY가 설정되지 않았습니다. .env 또는 Docker 환경변수를 확인하세요."}, status=500)

    try:
        from openai import OpenAI
    except ImportError:
        return JsonResponse({"error": "openai 패키지가 설치되지 않았습니다. requirements.txt 확인 후 설치하세요."}, status=500)

    result_dict, err_response = _run_analyze(api_key, info, personal)
    if err_response is not None:
        return err_response

    # 생성 시마다 PDF 만들어서 MinIO 적재 + Report 저장
    report_url = ""
    try:
        _, report_url = _generate_and_save_report_pdf(request, result_dict)
    except Exception as e:
        logger.exception("리포트 PDF 생성/저장 실패: %s", e)
    result_dict["report_url"] = report_url or ""
    return JsonResponse(result_dict)


def _run_analyze(api_key, info, personal):
    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    today = date.today()
    weekday_ko = ("월", "화", "수", "목", "금", "토", "일")[today.weekday()]
    today_str = f"{today.strftime('%Y-%m-%d')} ({weekday_ko})"

    system_prompt = f"""당신은 공고 조건과 지원자 정보를 분석하는 전문가입니다.
참고: 오늘 날짜는 {today_str} 입니다. 사용자가 "어제", "오늘", "내일" 등 상대적 날짜만 썼거나 날짜를 기입하지 않은 경우, 이 오늘 날짜를 기준으로 해석하세요.

주어진 조건 안내문(info)과 지원자 정보(personal)를 보고, 반드시 아래 JSON 형식만 출력하세요. 다른 설명은 붙이지 마세요.

{{
  "announcement_title": "공지 제목",
  "deadline": "신청 마감일",
  "submission_place": "신청 제출처",
  "basic_conditions": ["기본조건1", "기본조건2"],
  "preferred_conditions": ["우대조건1", "우대조건2"],
  "satisfied_conditions": [{{"condition": "조건 내용", "reason": "충족 이유"}}],
  "unsatisfied_conditions": [{{"condition": "조건 내용", "reason": "미충족 이유"}}],
  "action_recommendations": ["추천 행위1", "추천 행위2"],
  "human_review_items": ["사람이 확인할 사항1", "사람이 확인할 사항2"],
  "summary": "판단을 총 요약한 내용 (줄글)",
  "criteria_and_sources": "판단 기준 및 출처 (줄글)"
}}

- criteria_and_sources 작성 시: 조건 안내문(기입된 자료)에서 인용한 구체적 조건/항목(예: ㅇㅇ조건, ㅇㅇ요건)과 개인정보에서 드러난 구체적 상황(예: ㅇㅇ 상황)을 짚은 뒤, 그 조건과 상황이 어떻게 적합한지 또는 부적합한지 방향을 명시하고, 그에 따른 판단/결론으로 이어지게 줄글로 작성하세요. 예시 느낌: "조건 안내문의 〇〇 요건과 개인정보의 △△ 상황이 ~하여 적합/부적합하므로 …"
- 정보가 없거나 해당 항목이 없으면 빈 문자열 또는 빈 배열로 두세요."""

    user_prompt = f"""info (조건 안내문):
{info}

personal (내 정보):
{personal}"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
    except Exception as e:
        return None, JsonResponse({"error": f"OpenAI 호출 실패: {str(e)}"}, status=502)

    try:
        content = response.choices[0].message.content
        result = json.loads(content)
    except (AttributeError, json.JSONDecodeError, TypeError) as e:
        logger.exception("OpenAI 응답 처리 중 오류")
        raw = getattr(response.choices[0].message, "content", None) if response.choices else None
        return None, JsonResponse({"error": "OpenAI 응답 파싱 실패", "detail": str(e), "raw": raw}, status=502)

    return result, None


def _report_data_from_request(request):
    """POST에서 분석 결과 dict 추출 (report_page, report_pdf 공용)."""
    raw = None
    if request.content_type and "application/json" in request.content_type:
        try:
            raw = json.loads(request.body)
        except (json.JSONDecodeError, TypeError):
            pass
    if raw is None:
        data_str = request.POST.get("data") or "{}"
        try:
            raw = json.loads(data_str)
        except (json.JSONDecodeError, TypeError):
            raw = {}
    return raw


@require_http_methods(["POST"])
def report_page(request):
    """POST body에 analysis 결과 JSON(data 필드)을 받아 report.html로 렌더링한 HTML 반환."""
    raw = _report_data_from_request(request)
    html = render(request, "core/report.html", raw)
    return HttpResponse(html.content, content_type="text/html; charset=utf-8")


def _report_user_id(request):
    """MinIO 폴더용 사용자 고유값: 로그인 시 user.pk, 비로그인 시 anon_<session_key>."""
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False) and getattr(user, "pk", None):
        return str(user.pk)
    session_key = getattr(request.session, "session_key", None) or "unknown"
    return f"anon_{session_key}"


def _sanitize_filename(title, max_len=80):
    """파일명에 쓸 수 있도록 공지 제목 정리."""
    if not title or not isinstance(title, str):
        return "report"
    s = re.sub(r"[^\w\s\-가-힣a-zA-Z0-9]", "", title)
    s = re.sub(r"\s+", "_", s.strip())[:max_len].strip("_") or "report"
    return s


def _generate_and_save_report_pdf(request, raw):
    """분석 결과 dict로 PDF 생성 → MinIO 적재 → Report 저장. (pdf_bytes, report_url) 반환. report_url은 실패 시 ''."""
    raw = dict(raw)
    try:
        from django.contrib.staticfiles.finders import find
        import base64
        logo_path = find("icons/JDG.png")
        if logo_path and os.path.isfile(logo_path):
            with open(logo_path, "rb") as f:
                raw["logo_data_url"] = "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")
    except Exception as e:
        logger.debug("로고 base64 임베드 스킵: %s", e)
    html_response = render(request, "core/report.html", raw)
    html_string = html_response.content.decode("utf-8")
    base_url = request.build_absolute_uri("/")

    try:
        from weasyprint import HTML
        try:
            from weasyprint.fonts import FontConfiguration
        except ImportError:
            from weasyprint.text.fonts import FontConfiguration
        font_config = FontConfiguration()
        doc = HTML(string=html_string, base_url=base_url)
        pdf_bytes = doc.write_pdf(font_config=font_config)
    except Exception as e:
        logger.exception("PDF 변환 실패: %s", e)
        raise

    announcement_title = raw.get("announcement_title") or ""
    report_name = announcement_title or "리포트"
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    safe_title = _sanitize_filename(announcement_title)
    filename = f"{safe_title}_{timestamp}.pdf"
    user_id = _report_user_id(request)
    object_key = f"{user_id}/{filename}"

    report_url = ""
    try:
        saved_name = default_storage.save(object_key, ContentFile(pdf_bytes))
        report_url = default_storage.url(saved_name)
        person = getattr(request, "user", None) if getattr(getattr(request, "user", None), "is_authenticated", False) else None
        Report.objects.create(
            report_name=report_name,
            report_url=report_url,
            storage_key=object_key,
            person=person,
        )
        _trim_reports_for_user(person)
    except Exception as e:
        logger.exception("MinIO 적재 또는 Report 저장 실패: %s", e)
    return pdf_bytes, report_url


def _get_storage_key_for_delete(report):
    """MinIO 삭제용 객체 키 반환. storage_key 우선, 없으면 report_url에서 추출 시도."""
    if report.storage_key:
        return report.storage_key
    if not report.report_url:
        return None
    try:
        from urllib.parse import urlparse
        path = urlparse(report.report_url).path
        parts = path.strip("/").split("/")
        if len(parts) >= 2:
            return "/".join(parts[1:])
        return None
    except Exception:
        return None


def _delete_report_and_storage(report):
    """MinIO 객체 삭제 후 Report 레코드 삭제."""
    key = _get_storage_key_for_delete(report)
    if key:
        try:
            default_storage.delete(key)
        except Exception as e:
            logger.warning("MinIO 객체 삭제 실패(key=%s): %s", key, e)
    report.delete()


def _trim_reports_for_user(user):
    """해당 사용자(person)의 리포트가 3개 초과면 가장 오래된 것부터 MinIO·DB에서 삭제."""
    if user is None:
        return
    qs = Report.objects.filter(person=user).order_by("created_at")
    total = qs.count()
    if total <= 3:
        return
    for report in qs[: total - 3]:
        _delete_report_and_storage(report)


@require_http_methods(["POST"])
def report_pdf(request):
    """POST body에 analysis 결과 JSON을 받아 PDF 변환 → MinIO 적재 → Report 저장 → 다운로드 응답."""
    raw = _report_data_from_request(request)
    try:
        pdf_bytes, _ = _generate_and_save_report_pdf(request, raw)
    except Exception as e:
        logger.exception("PDF 변환 실패")
        return JsonResponse({"error": f"PDF 변환 실패: {str(e)}"}, status=500)
    announcement_title = raw.get("announcement_title") or ""
    safe_title = _sanitize_filename(announcement_title)
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{safe_title}_{timestamp}.pdf"
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@require_http_methods(["GET"])
def report_file(request, report_id):
    """리포트 PDF를 MinIO에서 읽어 스트리밍 반환. 브라우저/모달에서 직접 열 때 사용."""
    report = get_object_or_404(Report, pk=report_id)
    user = getattr(request, "user", None)
    if report.person is not None and report.person != user:
        return HttpResponse("Forbidden", status=403)
    key = report.storage_key or _get_storage_key_for_delete(report)
    if not key:
        return HttpResponse("Report file not found", status=404)
    try:
        with default_storage.open(key, "rb") as f:
            pdf_bytes = f.read()
    except Exception as e:
        logger.exception("MinIO에서 PDF 읽기 실패: %s", e)
        return HttpResponse("File unavailable", status=502)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = "inline; filename=\"report.pdf\""
    response["X-Frame-Options"] = "SAMEORIGIN"
    return response


# ----- 인증 API (모달 로그인/회원가입용) -----

@require_http_methods(["POST"])
def auth_login_api(request):
    """POST JSON: {username, password} → 로그인 후 200 또는 401."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        return JsonResponse({"error": "아이디와 비밀번호를 입력해 주세요."}, status=400)
    user = authenticate(request, username=username, password=password)
    if user is None:
        return JsonResponse({"error": "아이디 또는 비밀번호가 올바르지 않습니다."}, status=401)
    login(request, user)
    return JsonResponse({"success": True, "username": user.username})


@require_http_methods(["POST"])
def auth_register_api(request):
    """POST JSON: {username, password, password_confirm} → 회원가입 후 200 또는 400."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    password_confirm = body.get("password_confirm") or ""

    if not username:
        return JsonResponse({"error": "아이디를 입력해 주세요."}, status=400)
    if not password:
        return JsonResponse({"error": "비밀번호를 입력해 주세요."}, status=400)
    if password != password_confirm:
        return JsonResponse({"error": "비밀번호가 일치하지 않습니다."}, status=400)
    if User.objects.filter(username=username).exists():
        return JsonResponse({"error": "이미 사용 중인 아이디입니다."}, status=400)

    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError
    try:
        validate_password(password)
    except ValidationError as e:
        msg = (list(e.messages)[0]) if getattr(e, "messages", None) else str(e)
        return JsonResponse({"error": msg}, status=400)

    user = User.objects.create_user(username=username, password=password)
    login(request, user)
    return JsonResponse({"success": True, "username": username})


@require_http_methods(["POST"])
def auth_logout_api(request):
    """로그아웃 후 200."""
    from django.contrib.auth import logout
    logout(request)
    return JsonResponse({"success": True})


@require_http_methods(["GET"])
def auth_me_api(request):
    """로그인 사용자 정보 반환. 비로그인 시 401."""
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return JsonResponse({"error": "로그인이 필요합니다."}, status=401)
    return JsonResponse({"username": user.username})


@require_http_methods(["POST"])
def auth_profile_api(request):
    """사용자 정보 수정: username 변경 또는 비밀번호 변경."""
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return JsonResponse({"error": "로그인이 필요합니다."}, status=401)
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    new_username = (body.get("username") or "").strip()
    if new_username and new_username != user.username:
        if User.objects.filter(username=new_username).exclude(pk=user.pk).exists():
            return JsonResponse({"error": "이미 사용 중인 아이디입니다."}, status=400)
        user.username = new_username
        user.save()

    current_password = body.get("current_password") or ""
    new_password = body.get("new_password") or ""
    new_password_confirm = body.get("new_password_confirm") or ""
    if new_password or new_password_confirm:
        if not current_password:
            return JsonResponse({"error": "현재 비밀번호를 입력해 주세요."}, status=400)
        if not user.check_password(current_password):
            return JsonResponse({"error": "현재 비밀번호가 올바르지 않습니다."}, status=400)
        if new_password != new_password_confirm:
            return JsonResponse({"error": "새 비밀번호가 일치하지 않습니다."}, status=400)
        if not new_password:
            return JsonResponse({"error": "새 비밀번호를 입력해 주세요."}, status=400)
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError
        try:
            validate_password(new_password)
        except ValidationError as e:
            msg = (list(e.messages)[0]) if getattr(e, "messages", None) else str(e)
            return JsonResponse({"error": msg}, status=400)
        user.set_password(new_password)
        user.save()

    return JsonResponse({"success": True, "username": user.username})


@require_http_methods(["POST"])
def auth_withdraw_api(request):
    """회원 탈퇴: 비밀번호 확인 후 계정 삭제 및 로그아웃."""
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return JsonResponse({"error": "로그인이 필요합니다."}, status=401)
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    password = body.get("password") or ""
    if not password:
        return JsonResponse({"error": "비밀번호를 입력해 주세요."}, status=400)
    if not user.check_password(password):
        return JsonResponse({"error": "비밀번호가 올바르지 않습니다."}, status=400)
    from django.contrib.auth import logout
    logout(request)
    user.delete()
    return JsonResponse({"success": True})
