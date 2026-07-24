from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

BASE_URL = "https://yeonsu.eseoul.go.kr"
LIST_URL = f"{BASE_URL}/onlineRsv/list"
CONFIG_FILE = Path("config.json")
COOKIE_FILE = Path("cookie.txt")
TELEGRAM_FILE = Path("telegram.json")
STATE_FILE = Path("state.json")
RESULT_FILE = Path("results.csv")


@dataclass(frozen=True)
class Room:
    name: str
    count: int


def load_json(path: Path, default=None):
    if not path.exists():
        if default is not None:
            return default
        raise SystemExit(f"{path.name}이 없습니다.")
    return json.loads(path.read_text(encoding="utf-8"))


def load_config() -> dict:
    config = load_json(CONFIG_FILE)
    if not isinstance(config.get("facilities"), dict) or not config["facilities"]:
        raise SystemExit("config.json의 facilities 설정이 비어 있습니다.")
    return config


def load_cookie() -> str:
    env_cookie = os.getenv("YEONSU_COOKIE", "").strip()
    if env_cookie:
        return env_cookie

    if not COOKIE_FILE.exists():
        raise SystemExit("cookie.txt가 없습니다. python save_cookie.py를 먼저 실행하세요.")
    cookie = COOKIE_FILE.read_text(encoding="utf-8").strip()
    if not cookie or "=" not in cookie:
        raise SystemExit("cookie.txt 내용이 올바르지 않습니다.")
    return cookie


def load_telegram() -> dict | None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if token and chat_id:
        return {"bot_token": token, "chat_id": chat_id}

    if not TELEGRAM_FILE.exists():
        return None
    data = load_json(TELEGRAM_FILE)
    if not data.get("bot_token") or not data.get("chat_id"):
        return None
    return data


def load_state() -> set[str]:
    data = load_json(STATE_FILE, {"available_keys": []})
    return set(data.get("available_keys", []))


def save_state(keys: set[str]) -> None:
    STATE_FILE.write_text(
        json.dumps(
            {
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "available_keys": sorted(keys),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


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
            checkout = current + timedelta(days=nights)
            stays.append((current, checkout))
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


def make_session(cookie: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/150.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": BASE_URL,
        "Referer": LIST_URL,
        "Cookie": cookie,
    })
    return session


def fetch_html(session, facility_code, check_in, check_out) -> str:
    response = session.post(
        LIST_URL,
        data=build_payload(facility_code, check_in, check_out),
        timeout=30,
        allow_redirects=True,
    )
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text


def verify_login(html: str) -> None:
    if "로그아웃" not in html or "/mypage/" not in html:
        raise RuntimeError("로그인 세션이 만료되었습니다. Cookie를 다시 저장하세요.")


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
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    response.raise_for_status()


def write_results(rows: list[dict[str, str]]) -> None:
    with RESULT_FILE.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["연수원", "체크인", "체크아웃", "객실", "수량", "상태"],
        )
        writer.writeheader()
        writer.writerows(rows)


def run_once(config: dict) -> tuple[int, int]:
    cookie = load_cookie()
    session = make_session(cookie)
    telegram = load_telegram()
    telegram_enabled = bool(config.get("telegram_enabled", True) and telegram)

    facilities = config["facilities"]
    stays = generate_stays(config)
    delay = float(config.get("request_delay_seconds", 0.3))
    show_only_available = bool(config.get("show_only_available", True))
    save_only_available = bool(config.get("save_only_available", True))

    previous = load_state()
    current = set()
    rows = []
    available_schedules = 0
    errors = 0
    total = len(facilities) * len(stays)
    number = 0

    print("\n" + "=" * 72)
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Seoul Yeonsu Alert v3.0 검사 시작")
    print(f"조회 범위: {stays[0][0]:%Y-%m-%d} ~ {stays[-1][1]:%Y-%m-%d}" if stays else "조회 범위: 없음")
    print(f"총 조회 수: {total}")
    print("=" * 72)

    for facility_name, facility_code in facilities.items():
        if not show_only_available:
            print(f"\n[{facility_name}]")

        for check_in, check_out in stays:
            number += 1
            try:
                html = fetch_html(session, facility_code, check_in, check_out)
                verify_login(html)
                rooms = parse_rooms(html, facility_code)

                if rooms:
                    available_schedules += 1
                    room_text = ", ".join(f"{r.name} {r.count}개" for r in rooms)
                    print(
                        f"✅ ({number}/{total}) {facility_name} | "
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

                    if new_rooms and telegram_enabled:
                        message = (
                            "🔔 서울시 연수원 빈자리\n\n"
                            f"🏨 {facility_name}\n"
                            f"📅 {check_in:%Y-%m-%d} → {check_out:%Y-%m-%d}\n"
                            + "\n".join(f"• {r.name}: {r.count}개" for r in new_rooms)
                            + f"\n\n예약: {BASE_URL}"
                        )
                        try:
                            send_telegram(telegram, message)
                            print("   📲 텔레그램 알림 전송")
                        except Exception as exc:
                            print(f"   ⚠️ 텔레그램 전송 실패(조회 계속): {exc}")
                else:
                    if not show_only_available:
                        print(
                            f"❌ ({number}/{total}) {facility_name} | "
                            f"{check_in:%Y-%m-%d} → {check_out:%Y-%m-%d} | 없음"
                        )
                    if not save_only_available:
                        rows.append({
                            "연수원": facility_name,
                            "체크인": check_in.isoformat(),
                            "체크아웃": check_out.isoformat(),
                            "객실": "",
                            "수량": "0",
                            "상태": "없음",
                        })

            except Exception as exc:
                errors += 1
                print(
                    f"⚠️ ({number}/{total}) {facility_name} | "
                    f"{check_in:%Y-%m-%d} → {check_out:%Y-%m-%d} | {exc}"
                )
                if "로그인 세션" in str(exc):
                    raise

            if delay > 0:
                time.sleep(delay)

    write_results(rows)
    save_state(current)

    print("=" * 72)
    print(f"예약 가능 일정: {available_schedules}건")
    print(f"오류: {errors}건")
    print(f"결과: {RESULT_FILE.resolve()}")
    print("=" * 72)

    return available_schedules, errors


def main() -> int:
    config = load_config()
    repeat_minutes = int(config.get("repeat_minutes", 0))

    if os.getenv("GITHUB_ACTIONS", "").lower() == "true":
        repeat_minutes = 0

    while True:
        try:
            run_once(config)
        except KeyboardInterrupt:
            print("\n사용자가 종료했습니다.")
            return 0
        except Exception as exc:
            print(f"\n[중단 오류] {exc}")
            return 1

        if repeat_minutes <= 0:
            return 0

        print(f"\n다음 검사까지 {repeat_minutes}분 대기합니다. 종료: Ctrl+C")
        try:
            time.sleep(repeat_minutes * 60)
        except KeyboardInterrupt:
            print("\n사용자가 종료했습니다.")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
