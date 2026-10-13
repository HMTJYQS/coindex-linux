"""China workday calendar and automatic detection windows; no model calls."""
import datetime as dt
import json
import time
import urllib.request
import urllib.parse
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Asia/Shanghai")
SOURCES = ["https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json",
           "https://cdn.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json"]


def normalize_calendar(data, year):
    if data.get("year") != year or not data.get("papers") or not data.get("days"):
        raise ValueError("%d 年的法定节假日安排尚未发布或数据不完整" % year)
    for paper in data["papers"]:
        url = urllib.parse.urlparse(paper)
        if url.scheme != "https" or not (url.hostname or "").endswith(".gov.cn"):
            raise ValueError("节假日数据缺少可信的政府公告来源")
    days = {}
    for item in data["days"]:
        date = dt.date.fromisoformat(item["date"])
        if date.year not in (year-1, year) or type(item.get("isOffDay")) is not bool:
            raise ValueError("工作日数据格式错误")
        if date.isoformat() in days:
            raise ValueError("工作日数据日期重复")
        days[date.isoformat()] = {"off": item["isOffDay"], "name": str(item["name"])[:40]}
    return {"year": year, "days": days, "papers": data["papers"]}


def fetch_calendar(year):
    last_error = None
    for source in SOURCES:
        try:
            req = urllib.request.Request(source.format(year=year), headers={"User-Agent": "CodexTodo/1.2"})
            with urllib.request.urlopen(req, timeout=8) as response:
                raw = response.read(1024*1024+1)
            if len(raw) > 1024*1024:
                raise ValueError("工作日数据过大")
            return normalize_calendar(json.loads(raw), year)
        except Exception as error:
            last_error = error
    raise RuntimeError(str(last_error))


def calendar_years(now=None):
    date = dt.datetime.fromtimestamp(now if now is not None else time.time(), ZONE)
    return [date.year] + ([date.year+1] if date.month >= 11 else [])


def off_duty_state(store, now=None):
    now = time.time() if now is None else now
    until = store.meta("off_duty_until", 0)
    return {"off_duty": until > now, "off_duty_until": until if until > now else None}


def finish_workday(store, now=None):
    now = time.time() if now is None else now
    state = off_duty_state(store, now)
    if state["off_duty"]:
        return state["off_duty_until"]
    settings = store.settings()
    tomorrow = dt.datetime.fromtimestamp(now, ZONE).date() + dt.timedelta(days=1)
    start = settings["work_start_minutes"] if settings["work_hours_enabled"] else 0
    until = (dt.datetime.combine(tomorrow, dt.time(), ZONE) + dt.timedelta(minutes=start)).timestamp()
    store.put_meta("off_duty_until", until)
    return until


def refresh_needed(store, now=None):
    now = time.time() if now is None else now
    if off_duty_state(store, now)["off_duty"]:
        return False
    if not store.settings()["workdays_only"]:
        return False
    for year in calendar_years(now):
        cached = store.meta("calendar_%d" % year, {})
        if now-cached.get("updated_at", 0) >= 86400 and now-store.meta("calendar_attempt_%d" % year, 0) >= 3600:
            return True
    return False


def refresh_calendars(store, force=False, now=None):
    now = time.time() if now is None else now
    for year in calendar_years(now):
        cached = store.meta("calendar_%d" % year, {})
        if not force and (now-cached.get("updated_at", 0) < 86400 or now-store.meta("calendar_attempt_%d" % year, 0) < 3600):
            continue
        store.put_meta("calendar_attempt_%d" % year, now)
        try:
            calendar = fetch_calendar(year)
            calendar["updated_at"] = now
            store.put_meta("calendar_%d" % year, calendar)
            store.put_meta("calendar_error_%d" % year, "")
        except Exception as error:
            # Keep a previously verified calendar usable while offline.
            store.put_meta("calendar_error_%d" % year, str(error)[:500])


def day_state(date, settings, calendars):
    if not settings["workdays_only"]:
        return True, "每天检测"
    year = calendars.get(date.year)
    if not year:
        return None, "%d 年工作日数据尚未就绪" % date.year
    override = year["days"].get(date.isoformat())
    upcoming = calendars.get(date.year+1, {}).get("days", {}).get(date.isoformat())
    override = upcoming or override
    if override:
        return not override["off"], override["name"] + ("休息日" if override["off"] else "调休补班")
    return date.weekday() < 5, "工作日" if date.weekday() < 5 else "周末休息日"


def automatic_state(store, now=None):
    now = time.time() if now is None else now
    settings = store.settings()
    local = dt.datetime.fromtimestamp(now, ZONE)
    calendars = {y: store.meta("calendar_%d" % y) for y in range(local.year-1, local.year+2)}
    calendars = {y: data for y, data in calendars.items() if data}
    working, day_label = day_state(local.date(), settings, calendars)
    current = calendars.get(local.year, {})
    result = {"due": False, "next_at": None, "summary": "自动更新已暂停", "day_label": day_label,
              "calendar_updated_at": current.get("updated_at", 0), "calendar_papers": current.get("papers", []),
              "calendar_error": store.meta("calendar_error_%d" % local.year, ""), "timezone": "Asia/Shanghai"}
    rest = off_duty_state(store, now)
    result.update(rest)
    if rest["off_duty"]:
        # The holiday/window gate below still determines the actual next check.
        result["summary"] = "已下班，等待恢复检测"
    if not settings["automatic"]:
        return result
    if working is None:
        if not rest["off_duty"]:
            result["summary"] = "等待工作日数据"
        return result
    earliest = max(now, rest["off_duty_until"] or 0,
                   store.meta("last_check", store.meta("last_sync", 0)) + settings["interval_seconds"])
    start = settings["work_start_minutes"] if settings["work_hours_enabled"] else 0
    end = settings["work_end_minutes"] if settings["work_hours_enabled"] else 1440
    # Include yesterday's window for shifts that run across midnight.
    for offset in range(-1, 370):
        date = local.date() + dt.timedelta(days=offset)
        is_working, _ = day_state(date, settings, calendars)
        if is_working is None:
            if offset < 0:
                continue
            break
        if not is_working:
            continue
        midnight = dt.datetime.combine(date, dt.time(), ZONE)
        opens = (midnight + dt.timedelta(minutes=start)).timestamp()
        closes = (midnight + dt.timedelta(minutes=end + (1440 if end <= start else 0))).timestamp()
        candidate = max(opens, earliest)
        if candidate < closes:
            result["next_at"] = candidate
            result["due"] = candidate <= now
            break
    if rest["off_duty"]:
        return result
    if result["due"]:
        result["summary"] = "现在可自动检测"
    elif not working:
        result["summary"] = "休息日，等待下次检测"
    elif result["next_at"] and result["next_at"] > earliest:
        result["summary"] = "等待检测时段"
    else:
        result["summary"] = "等待下次检测"
    return result
