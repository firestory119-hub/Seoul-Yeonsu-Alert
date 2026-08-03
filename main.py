from __future__ import annotations

import csv
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://yeonsu.eseoul.go.kr"
MAIN_URL = urljoin(BASE_URL, "/main")
LOGIN_POST_URL = urljoin(BASE_URL, "/loginProcAjax")
LIST_URL = urljoin(BASE_URL, "/onlineRsv/list")

CONFIG_FILE = Path("config.json")
STATE_FILE = Path("state.json")
RESULT_FILE = Path("results.csv")
TELEGRAM_FILE = Path("telegram.json")

DEFAULT_STATE = {
    "updated_at": None,
    "available_keys": [],
    "last_login_ok": None,
    "last_error": None,
}


@dataclass(frozen=True)
class Room:
    name: str
    count: int


def load_json(path: Path, default=None):
    if not path.exists():
        if default is not None:
            return default.copy() if isinstance(default, dict) else default
        raise SystemExit(f"{path.name}이 없습니다.")
    return json.loads(path.read_text(encoding="utf-8"))


def load_config() -> dict:
    config = load_json(CONFIG_FILE)
    facilities = config.get("facilities")
    if not isinstance(facilities, dict) or not facilities:
        raise SystemExit("config.json의 facilities 설정이 비어 있습니다.")
    return config


def load_state() -> dict:
    state = load_json(STATE_FILE, DEFAULT_STATE)
    for key, value in DEFAULT_STATE.items():
        state.setdefault(key, value)
    return state


def save_state(state: dict) -> None:
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_credentials() -> tuple[str, str]:
    user_id = os.getenv("YEONSU_ID", "").strip()
    password = os.getenv("YEONSU_PASSWORD", "").strip()

    if user_id and password:
        return user_id, password

    local = Path("login.json")
    if local.exists():
        data = load_json(local)
        user_id = str(data.get("user_id", "")).strip()
        password = str(data.get("password", "")).strip()
        if user_id and password:
            return user_id, password

    raise SystemExit(
        "로그인 정보가 없습니다. GitHub Secrets에 YEONSU_ID와 "
        "YEONSU_PASSWORD를 등록하거나 로컬에서 save_login.py를 실행하세요."
    )


def load_telegram() -> dict | None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if token and chat_id:
        return {"bot_token": token, "chat_id": chat_id}

    if TELEGRAM_FILE.exists():
        data = load_json(TELEGRAM_FILE)
        if data.get("bot_token") and data.get("chat_id"):
            return data

    return None


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/150.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    })
    return session


def find_csrf_token(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")

    token_input = soup.find("input", attrs={"name": "csrf_token"})
    if token_input and token_input.get("value"):
        return str(token_input["value"]).strip()

    patterns = (
        r'name=["\']csrf_token["\'][^>]*value=["\']([^"\']+)["\']',
        r'csrf_token["\']?\s*[:=]\s*["\']([^"\']+)["\']',
    )
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.I)
        if match:
            return match.group(1).strip()

    return None


def get_login_page(session: requests.Session) -> tuple[str, str]:
    errors = []

    for path in ("/main", "/", "/login"):
        url = urljoin(BASE_URL, path)
        try:
            response = session.get(url, timeout=30, allow_redirects=True)

            if response.status_code >= 400:
                errors.append(f"{url} → HTTP {response.status_code}")
                continue

            response.encoding = response.apparent_encoding or "utf-8"
            token = find_csrf_token(response.text)
            if token:
                return response.url, token

            errors.append(f"{response.url} → csrf_token 없음")
        except requests.RequestException as exc:
            errors.append(f"{url} → {exc}")

    raise RuntimeError(
        "로그인 페이지에서 csrf_token을 찾지 못했습니다.\n"
        + "\n".join(errors)
    )


def is_logged_in(html: str) -> bool:
    if "로그아웃" in html:
        return True

    soup = BeautifulSoup(html, "html.parser")
    if soup.find(attrs={"name": "mbmr_id"}) or soup.find(attrs={"name": "mbmr_pwd"}):
        return False

    return "마이페이지" in html and "연수원 온라인예약" in html


def auto_login(session: requests.Session, user_id: str, password: str) -> None:
    login_page_url, csrf_token = get_login_page(session)

    response = session.post(
        LOGIN_POST_URL,
        data={
            "csrf_token": csrf_token,
            "mbmr_id": user_id,
            "mbmr_pwd": password,
        },
        headers={
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": BASE_URL,
            "Referer": login_page_url,
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=30,
        allow_redirects=True,
    )
    response.raise_for_status()

    main_response = session.get(MAIN_URL, timeout=30, allow_redirects=True)
    main_response.raise_for_status()
    main_response.encoding = main_response.apparent_encoding or "utf-8"

    if not is_logged_in(main_response.text):
        detail = response.text[:200].strip()
        raise RuntimeError(f"자동 로그인 실패: {detail or '응답 내용 없음'}")


def last_day_of_next_month(today: date) -> date:
    if today.month == 12:
        first_after_next = date(today.year + 1, 2, 1)
    elif today.month == 11:
        first_after_next = date(today.year + 1, 1, 1)
    else:
        first_after_next = date(today.year, today.month + 2, 1)
    return first_after_next - timedelta(days=1)


def generate_stays(config: dict) -> list[tuple[date, date]]:
    today = date.today()
    end = last_day_of_next_month(today)
    weekdays = {int(x) for x in config.get("checkin_weekdays", [4, 5])}
    nights = int(config.get("stay_nights", 1))

    stays = []
    current = today
    while current <= end:
        if current.weekday() in weekdays:
            stays.append((current, current + timedelta(days=nights)))
        current += timedelta(days=1)

    return stays


def build_payload(facility_code: str, check_in: date, check_out: date) -> dict[str, str]:
    ci = check_in.strftime("%Y%m%d")
    co = check_out.strftime("%Y%m%d")

    return {
        "year_month": ci[:6],
        "check_in_day_hidden": "",
        "check_out_day_hidden": "",
        "mbmr_id": "",
        "rming_dt": "",
        "leve_dt": "",
        "rsv_user_id": "",
        "rsv_user_contact": "",
        "rsv_stat": "",
        "yeonsu_gbn": "",
        "vster_contact": "",
        "room_tye": "",
        "ori_room_tye": "",
        "date_change_yn": "",
        "finish_point": "",
        "finish_room": "",
        "rsv_no": "",
        "hist_seq": "",
        "rsv_pre_no": "",
        "org_bse_gbn": "",
        "move_mypage": "",
        "chkinDt": "",
        "chkoutDt": "",
        "yeonsuGbn": "",
        "ins_upt_gbn": "",
        "ser_yeonsu_gbn": facility_code,
        "check_in_day": ci,
        "check_out_day": co,
        "cellChoice": "010",
        "cellChoice1": "",
        "cellChoice2": "",
    }


def fetch_html(
    session: requests.Session,
    facility_code: str,
    check_in: date,
    check_out: date,
) -> str:
    response = session.post(
        LIST_URL,
        data=build_payload(facility_code, check_in, check_out),
        headers={
            "Origin": BASE_URL,
            "Referer": LIST_URL,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=30,
        allow_redirects=True,
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def verify_reservation_page(html: str) -> None:
    if not is_logged_in(html):
        raise RuntimeError("조회 중 로그인 세션이 끊겼습니다.")


def extract_facility_branch(html: str, facility_code: str) -> str:
    pos = html.find("// 연수원별로 객실 보여주기.")
    if pos < 0:
        pos = html.find("var roomHtml")
    if pos < 0:
        raise ValueError("객실 생성 구간을 찾지 못했습니다.")

    room_section = html[pos:]
    marker = re.compile(
        rf'(?:else\s+)?if\(\s*\$\("#ser_yeonsu_gbn"\)\.val\(\)'
        rf'\s*==\s*"{re.escape(facility_code)}"\s*\)\s*\{{'
    )
    match = marker.search(room_section)
    if not match:
        raise ValueError(f"연수원 코드 분기문을 찾지 못했습니다: {facility_code}")

    next_facility = re.compile(
        r'\}\s*else\s+if\(\s*\$\("#ser_yeonsu_gbn"\)\.val\(\)'
        r'\s*==\s*"00003\d{3}"\s*\)\s*\{'
    )
    next_match = next_facility.search(room_section, match.end())
    end = next_match.start() if next_match else len(room_section)

    return room_section[match.end():end]


def parse_rooms(html: str, facility_code: str) -> list[Room]:
    branch = extract_facility_branch(html, facility_code)

    pattern = re.compile(
        r'if\("(\d+)"\s*>\s*0\)\s*\{'
        r'(?:(?!if\("\d+"\s*>\s*0\)).)*?'
        r'class="room-type">([^<]+)</p>',
        flags=re.I | re.S,
    )

    rooms = []
    for count_text, room_name in pattern.findall(branch):
        count = int(count_text)
        room_name = room_name.strip()
        if count > 0 and not any(room.name == room_name for room in rooms):
            rooms.append(Room(room_name, count))

    return rooms


def send_telegram(settings: dict, text: str) -> None:
    url = f"https://api.telegram.org/bot{settings['bot_token']}/sendMessage"
    response = requests.post(
        url,
        json={
            "chat_id": settings["chat_id"],
            "text": text,
            "disable_web_page_preview": False,
        },
        timeout=20,
    )
    response.raise_for_status()


def write_results(rows: list[dict[str, str]]) -> None:
    with RESULT_FILE.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["연수원", "체크인", "체크아웃", "객실", "수량", "상태"],
        )
        writer.writeheader()
        writer.writerows(rows)


def run_once(config: dict) -> int:
    started = time.monotonic()
    user_id, password = load_credentials()
    telegram = load_telegram()
    state = load_state()
    previous = set(state.get("available_keys", []))

    session = make_session()

    print("=" * 72)
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Seoul Yeonsu Alert v4.0")
    print("자동 로그인 시작")

    try:
        auto_login(session, user_id, password)
        state["last_login_ok"] = True
        state["last_error"] = None
        print("✅ 자동 로그인 성공")
    except Exception as exc:
        state["last_login_ok"] = False
        state["last_error"] = str(exc)
        save_state(state)
        print(f"❌ 자동 로그인 실패: {exc}")

        if telegram:
            try:
                send_telegram(
                    telegram,
                    "⚠️ 서울시 연수원 자동 로그인 실패\n\n"
                    "GitHub Secrets의 YEONSU_ID와 YEONSU_PASSWORD를 확인해 주세요.",
                )
            except Exception as notify_exc:
                print(f"⚠️ 텔레그램 오류: {notify_exc}")

        return 1

    facilities = config["facilities"]
    selected = config.get("selected_facilities") or list(facilities)
    facilities = {
        name: code for name, code in facilities.items()
        if name in selected
    }

    stays = generate_stays(config)
    total = len(facilities) * len(stays)
    delay = float(config.get("request_delay_seconds", 0.3))
    show_progress = bool(config.get("show_progress", True))

    if stays:
        print(f"조회 범위: {stays[0][0]:%Y-%m-%d} ~ {stays[-1][1]:%Y-%m-%d}")
    print(f"총 조회 수: {total}")
    print("=" * 72)

    current = set()
    rows = []
    number = 0
    available_schedules = 0
    new_alerts = 0
    errors = 0

    for facility_name, facility_code in facilities.items():
        for check_in, check_out in stays:
            number += 1

            if show_progress:
                print(
                    f"⏳ ({number}/{total}) {facility_name} | "
                    f"{check_in:%Y-%m-%d} → {check_out:%Y-%m-%d}",
                    flush=True,
                )

            try:
                html = fetch_html(session, facility_code, check_in, check_out)
                verify_reservation_page(html)
                rooms = parse_rooms(html, facility_code)

                if not rooms:
                    if delay > 0:
                        time.sleep(delay)
                    continue

                available_schedules += 1
                room_text = ", ".join(f"{room.name} {room.count}개" for room in rooms)
                print(
                    f"✅ {facility_name} | "
                    f"{check_in:%Y-%m-%d} → {check_out:%Y-%m-%d} | {room_text}"
                )

                new_rooms = []
                for room in rooms:
                    key = (
                        f"{facility_code}|{check_in.isoformat()}|"
                        f"{check_out.isoformat()}|{room.name}|{room.count}"
                    )
                    current.add(key)

                    if key not in previous:
                        new_rooms.append(room)

                    rows.append({
                        "연수원": facility_name,
                        "체크인": check_in.isoformat(),
                        "체크아웃": check_out.isoformat(),
                        "객실": room.name,
                        "수량": str(room.count),
                        "상태": "예약 가능",
                    })

                if new_rooms and telegram:
                    message = (
                        "🔔 서울시 연수원 빈자리\n\n"
                        f"🏨 {facility_name}\n"
                        f"📅 {check_in:%Y-%m-%d} → {check_out:%Y-%m-%d}\n"
                        + "\n".join(
                            f"• {room.name}: {room.count}개" for room in new_rooms
                        )
                        + f"\n\n👉 예약 페이지: {LIST_URL}"
                    )
                    try:
                        send_telegram(telegram, message)
                        new_alerts += 1
                        print("📲 텔레그램 전송 완료")
                    except Exception as exc:
                        print(f"⚠️ 텔레그램 전송 실패: {exc}")

            except Exception as exc:
                errors += 1
                print(
                    f"⚠️ ({number}/{total}) {facility_name} | "
                    f"{check_in:%Y-%m-%d} → {check_out:%Y-%m-%d} | {exc}"
                )

            if delay > 0:
                time.sleep(delay)

    write_results(rows)
    state["available_keys"] = sorted(current)
    state["last_login_ok"] = True
    state["last_error"] = None
    save_state(state)

    elapsed = time.monotonic() - started
    print("=" * 72)
    print(f"예약 가능 일정: {available_schedules}건")
    print(f"신규 텔레그램 알림: {new_alerts}건")
    print(f"오류: {errors}건")
    print(f"소요시간: {elapsed:.1f}초")
    print("=" * 72)

    return 0


def main() -> int:
    config = load_config()
    repeat_minutes = int(config.get("repeat_minutes", 0))

    if os.getenv("GITHUB_ACTIONS", "").lower() == "true":
        repeat_minutes = 0

    while True:
        result = run_once(config)

        if result != 0 or repeat_minutes <= 0:
            return result

        print(f"다음 검사까지 {repeat_minutes}분 대기합니다. 종료: Ctrl+C")
        try:
            time.sleep(repeat_minutes * 60)
        except KeyboardInterrupt:
            print("사용자가 종료했습니다.")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
