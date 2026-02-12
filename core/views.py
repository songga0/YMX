import json
import os

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from .models import Report


def home(request):
    return render(request, "core/home.html")


@require_http_methods(["GET"])
def latest_reports(request):
    """최근 생성된 3개 리포트 목록을 JSON으로 반환 (번호, 리포트명, 생성일시)."""
    qs = Report.objects.order_by("-created_at")[:3]
    reports = []
    for i, r in enumerate(qs, start=1):
        created = getattr(r, "created_at", None)
        reports.append({
            "no": i,
            "report_name": r.report_name,
            "report_url": r.report_url or "",
            "created_at": created.strftime("%Y-%m-%d %H:%M") if created else "",
        })
    return JsonResponse({"reports": reports})


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
        return JsonResponse({"error": "OPENAI_API_KEY가 설정되지 않았습니다."}, status=500)

    from openai import OpenAI

    client = OpenAI(api_key=api_key)

    system_prompt = """당신은 공고 조건과 지원자 정보를 분석하는 전문가입니다.
주어진 조건 안내문(info)과 지원자 정보(personal)를 보고, 반드시 아래 JSON 형식만 출력하세요. 다른 설명은 붙이지 마세요.

{
  "announcement_title": "공지 제목",
  "deadline": "신청 마감일",
  "submission_place": "신청 제출처",
  "basic_conditions": ["기본조건1", "기본조건2"],
  "preferred_conditions": ["우대조건1", "우대조건2"],
  "satisfied_conditions": [{"condition": "조건 내용", "reason": "충족 이유"}],
  "unsatisfied_conditions": [{"condition": "조건 내용", "reason": "미충족 이유"}],
  "action_recommendations": ["추천 행위1", "추천 행위2"],
  "human_review_items": ["사람이 확인할 사항1", "사람이 확인할 사항2"],
  "summary": "판단을 총 요약한 내용 (줄글)",
  "criteria_and_sources": "판단 기준 및 출처 (줄글)"
}

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
        return JsonResponse({"error": f"OpenAI 호출 실패: {str(e)}"}, status=502)

    content = response.choices[0].message.content
    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        return JsonResponse({"error": "OpenAI 응답 파싱 실패", "raw": content}, status=502)

    return JsonResponse(result)
