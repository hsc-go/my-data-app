# main.py
# ------------------------------------------------------------
# 어제의 박스오피스(KOBIS 일별 박스오피스)를 보여주는 스트림릿 앱
# 초보자를 위해 각 단계마다 한국어 주석을 달아두었습니다.
# ------------------------------------------------------------

import streamlit as st
import requests
from datetime import datetime, timedelta, timezone
import pandas as pd

# ------------------------------------------------------------
# 1) 기본 설정
# ------------------------------------------------------------

# 스트림릿 페이지 기본 설정 (탭 제목, 레이아웃 등)
st.set_page_config(page_title="어제의 박스오피스", page_icon="🎬", layout="wide")

# KOBIS 일별 박스오피스 조회 API 주소 (공식 문서 그대로)
API_URL = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"


def get_yesterday_kst() -> str:
    """
    '어제' 날짜를 한국 시간(KST, UTC+9) 기준으로 계산해서
    KOBIS가 요구하는 yyyymmdd(8자리 문자열) 형태로 돌려줍니다.

    - 배포 서버(스트림릿 클라우드)의 시계는 한국 시간이 아닐 수 있으므로,
      timezone(timedelta(hours=9))를 직접 지정해서 한국 시간을 계산합니다.
    - 오늘 날짜에서 하루(1일)를 빼서 '어제'를 구합니다.
    """
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    yesterday_kst = now_kst - timedelta(days=1)
    return yesterday_kst.strftime("%Y%m%d")


# ------------------------------------------------------------
# 2) API 호출 함수 (캐시 적용)
# ------------------------------------------------------------

# st.cache_data를 사용하면, 같은 target_dt로 다시 요청했을 때
# 실제 API를 다시 호출하지 않고 저장해둔 결과를 그대로 돌려줍니다.
# ttl=3600 은 "1시간(3600초) 동안 결과를 기억한다"는 뜻입니다.
@st.cache_data(ttl=3600)
def fetch_box_office(target_dt: str):
    """
    KOBIS API를 호출해서 특정 날짜(target_dt, yyyymmdd)의
    일별 박스오피스 목록을 가져옵니다.

    돌려주는 값은 항상 (성공여부, 데이터 또는 에러메시지) 형태의 튜플입니다.
    - 성공하면: (True, 영화 목록 리스트)
    - 실패하면: (False, "사용자에게 보여줄 한국어 안내 메시지")
    """

    # 2-1) 인증키는 절대 코드에 직접 쓰지 않고, 스트림릿 비밀 금고(secrets)에서 불러옵니다.
    #      스트림릿 클라우드의 [Settings > Secrets]에 아래처럼 등록해두어야 합니다.
    #      KOBIS_KEY = "발급받은_인증키"
    try:
        api_key = st.secrets["KOBIS_KEY"]
    except Exception:
        return False, (
            "❌ 인증키를 찾을 수 없습니다.\n\n"
            "스트림릿 클라우드의 [Settings > Secrets]에 다음과 같이 등록되어 있는지 확인해주세요.\n\n"
            'KOBIS_KEY = "발급받은_인증키"'
        )

    params = {
        "key": api_key,
        "targetDt": target_dt,
    }

    # 2-2) 실제 API 요청 보내기 (네트워크 오류, 타임아웃 등에 대비해 try/except 사용)
    try:
        response = requests.get(API_URL, params=params, timeout=10)
    except requests.exceptions.RequestException:
        return False, (
            "❌ KOBIS 서버에 접속하지 못했습니다.\n\n"
            "인터넷 연결 상태나 잠시 후 재시도가 필요한지 확인해주세요."
        )

    # 2-3) 상태 코드 확인 (문서상 인증키가 틀려도 200이 올 수 있으니, 이후 faultInfo도 반드시 확인해야 함)
    if response.status_code != 200:
        return False, (
            f"❌ KOBIS 서버가 오류 상태코드({response.status_code})를 반환했습니다.\n\n"
            "잠시 후 다시 시도하거나, API 주소가 맞는지 확인해주세요."
        )

    # 2-4) 응답이 JSON 형태가 아닐 수도 있으니 안전하게 파싱
    try:
        data = response.json()
    except ValueError:
        return False, (
            "❌ 서버 응답을 이해할 수 없는 형식(JSON 아님)입니다.\n\n"
            "KOBIS 서버 상태나 요청 주소가 올바른지 확인해주세요."
        )

    # 2-5) faultInfo 상자 확인
    #      문서에 따르면 인증키가 틀려도 상태코드는 200이고, 대신 faultInfo가 옵니다.
    if "faultInfo" in data:
        message = data["faultInfo"].get("message", "알 수 없는 오류")
        return False, (
            f"❌ KOBIS API에서 오류를 반환했습니다: {message}\n\n"
            "인증키(KOBIS_KEY)가 올바른지, 사용량 제한을 넘지 않았는지 확인해주세요."
        )

    # 2-6) 정상 구조인지 확인 (boxOfficeResult > dailyBoxOfficeList)
    box_office_result = data.get("boxOfficeResult")
    if not box_office_result:
        return False, (
            "❌ 예상한 응답 구조(boxOfficeResult)를 찾을 수 없습니다.\n\n"
            "KOBIS API 명세가 변경되었는지 확인해주세요."
        )

    movie_list = box_office_result.get("dailyBoxOfficeList")

    # 2-7) 영화 목록이 비어있는 경우 (예: 너무 이른 날짜, 아직 집계 전 등)
    if not movie_list:
        return False, (
            "❌ 해당 날짜의 박스오피스 데이터가 비어 있습니다.\n\n"
            "조회 날짜가 너무 이르거나(예: 오늘 새벽), 아직 KOBIS 집계가 끝나지 않았을 수 있습니다."
        )

    return True, movie_list


# ------------------------------------------------------------
# 3) 데이터 가공 함수
# ------------------------------------------------------------

def to_dataframe(movie_list: list) -> pd.DataFrame:
    """
    API에서 받은 영화 목록(리스트, 안의 숫자는 전부 문자열)을
    화면에 표시하기 좋은 pandas DataFrame으로 바꿉니다.
    이 과정에서 숫자 컬럼들을 실제 숫자(int) 타입으로 변환합니다.
    """
    df = pd.DataFrame(movie_list)

    # 문서에 나온 숫자형 컬럼들: 전부 문자열로 오기 때문에 숫자로 변환해야
    # 정렬(sort)이나 그래프(chart)에 제대로 쓸 수 있습니다.
    numeric_columns = ["rank", "audiCnt", "audiAcc", "scrnCnt", "showCnt"]
    for col in numeric_columns:
        if col in df.columns:
            # errors="coerce": 혹시 숫자로 바꿀 수 없는 값이 있으면 에러 대신 NaN으로 처리
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 순위(rank) 기준으로 오름차순 정렬 (1위가 맨 위로 오도록)
    df = df.sort_values("rank").reset_index(drop=True)

    return df


# ------------------------------------------------------------
# 4) 화면 구성 (메인 로직)
# ------------------------------------------------------------

def main():
    st.title("🎬 어제의 박스오피스")

    # 4-1) 조회할 날짜(어제, 한국 시간 기준) 계산
    target_dt = get_yesterday_kst()

    # 화면에 보여줄 사람이 읽기 좋은 날짜 형식 (예: 2026-09-16)
    pretty_date = f"{target_dt[0:4]}-{target_dt[4:6]}-{target_dt[6:8]}"
    st.caption(f"조회 기준일: {pretty_date} (어제, 한국 시간 기준)")

    # 4-2) API 호출 (캐시가 적용되어 있어서 같은 날짜면 1시간 동안 재호출하지 않음)
    success, result = fetch_box_office(target_dt)

    # 4-3) 실패했을 경우: 빈 화면 대신 안내 메시지 표시하고 종료
    if not success:
        st.error(result)
        return

    movie_list = result

    # 4-4) 데이터프레임으로 가공 (숫자 변환 + 정렬 포함)
    df = to_dataframe(movie_list)

    # ------------------------------------------------------------
    # 4-5) 1위 영화: 지표 카드 3장으로 크게 보여주기
    # ------------------------------------------------------------
    st.subheader("🏆 오늘의 1위")

    top_movie = df.iloc[0]

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(
            label=f"🎞️ {top_movie['movieNm']}",
            value=f"{int(top_movie['audiCnt']):,}명",
            help="어제 하루 관객수",
        )
    with col2:
        st.metric(
            label="누적 관객수",
            value=f"{int(top_movie['audiAcc']):,}명",
        )
    with col3:
        st.metric(
            label="스크린수",
            value=f"{int(top_movie['scrnCnt']):,}개",
        )

    st.caption(f"개봉일: {top_movie['openDt']}")

    st.divider()

    # ------------------------------------------------------------
    # 4-6) 관객수 상위 5편: 막대그래프
    # ------------------------------------------------------------
    st.subheader("📊 관객수 상위 5편")

    top5 = df.sort_values("audiCnt", ascending=False).head(5)

    # 영화명을 인덱스로 지정해야 막대그래프의 x축(가로축)에 영화 이름이 표시됩니다.
    chart_data = top5.set_index("movieNm")[["audiCnt"]]
    st.bar_chart(chart_data)

    st.divider()

    # ------------------------------------------------------------
    # 4-7) 전체 순위표
    # ------------------------------------------------------------
    st.subheader("📋 전체 박스오피스 순위")

    # 표에 보여줄 컬럼만 골라서, 한국어 이름으로 바꿔줍니다.
    table_df = df[["rank", "movieNm", "openDt", "audiCnt", "audiAcc", "scrnCnt"]].copy()
    table_df.columns = ["순위", "영화명", "개봉일", "관객수", "누적관객", "스크린수"]

    st.dataframe(
        table_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "관객수": st.column_config.NumberColumn(format="%d"),
            "누적관객": st.column_config.NumberColumn(format="%d"),
            "스크린수": st.column_config.NumberColumn(format="%d"),
        },
    )


if __name__ == "__main__":
    main()
