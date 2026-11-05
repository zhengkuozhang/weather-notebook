#!/usr/bin/env python3
"""Local weather dashboard backed by the Open-Meteo public APIs."""

import csv
import io
import json
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "weather_history.db"
PORT = 8765
USER_AGENT = "LocalWeatherNotebook/1.0 (personal project)"
_nominatim_lock = threading.Lock()
_last_nominatim_request = 0.0


def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city TEXT NOT NULL, country TEXT NOT NULL DEFAULT '',
            observed_at TEXT NOT NULL, captured_at TEXT, temperature REAL, feels_like REAL,
            humidity INTEGER, precipitation REAL,
            wind_speed REAL, weather_code INTEGER, is_day INTEGER,
            latitude REAL, longitude REAL
        )""")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(observations)")}
        if "captured_at" not in columns:
            conn.execute("ALTER TABLE observations ADD COLUMN captured_at TEXT")
        conn.execute("UPDATE observations SET captured_at = observed_at WHERE captured_at IS NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_observations_city_time ON observations(city, captured_at DESC)")
        conn.execute("""CREATE TABLE IF NOT EXISTS geocode_cache (
            path TEXT PRIMARY KEY, name TEXT NOT NULL, country TEXT NOT NULL,
            latitude REAL NOT NULL, longitude REAL NOT NULL
        )""")


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def geocode_path(path):
    global _last_nominatim_request
    path = [" ".join(str(part).strip().split()) for part in path if str(part).strip()]
    if len(path) < 3:
        raise ValueError("请选择到县、区或同级地区后再查询天气。")
    cache_key = "|".join(path)
    with db_connect() as conn:
        cached = conn.execute("SELECT * FROM geocode_cache WHERE path = ?", (cache_key,)).fetchone()
    if cached:
        place = dict(cached)
        place["name"] = path[-1]
        return place

    administrative_labels = {"市辖区", "省直辖县级行政区划", "自治区直辖县级行政区划"}
    search_path = [part for part in reversed(path) if part not in administrative_labels]
    language = "zh-CN"
    if path[0] == "台湾省":
        search_path = [path[-1]] + ([path[-2]] if len(path) > 2 else []) + ["台湾"]
        language = "zh-TW"
    elif path[0] == "澳门特别行政区":
        search_path = [path[-1], "澳门"]
        language = "zh-TW"
    elif path[0] == "香港特别行政区":
        language = "zh-TW"
    query = urllib.parse.urlencode({"q": ", ".join(search_path + ["中国"]), "format": "jsonv2", "limit": 10, "accept-language": language})
    with _nominatim_lock:
        elapsed = time.monotonic() - _last_nominatim_request
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        results = fetch_json("https://nominatim.openstreetmap.org/search?" + query)
        _last_nominatim_request = time.monotonic()
    traditional = str.maketrans({"區":"区", "島":"岛", "灣":"湾", "臺":"台", "門":"门", "莊":"庄", "鶯":"莺", "蘆":"芦", "樹":"树", "龍":"龙", "橋":"桥", "萬":"万", "雙":"双", "烏":"乌", "豐":"丰", "勢":"势", "霧":"雾", "棲":"栖", "後":"后", "關":"关", "歸":"归", "鹽":"盐", "營":"营", "將":"将"})
    normalize = lambda value: str(value).translate(traditional)
    matches = [result for result in results if normalize(result.get("name", "")) == normalize(path[-1]) and result.get("type") == "administrative"]
    if not matches:
        raise ValueError("这个地区暂时没有可用的地图坐标，请尝试选择相邻的市级地区。")
    result = matches[0]
    place = {"path": cache_key, "name": path[-1], "country": "中国",
             "latitude": float(result["lat"]), "longitude": float(result["lon"])}
    with db_connect() as conn:
        conn.execute("INSERT OR REPLACE INTO geocode_cache(path,name,country,latitude,longitude) VALUES(:path,:name,:country,:latitude,:longitude)", place)
    return place


def get_weather(city, place_path=None, selected_place=None):
    city = " ".join(city.strip().split())
    if not city or len(city) > 80:
        raise ValueError("请输入有效的城市名称（最多 80 个字符）。")
    if selected_place:
        place = selected_place
    elif place_path:
        place = geocode_path(place_path)
    else:
        query = urllib.parse.urlencode({"name": city, "count": 1, "language": "zh", "format": "json"})
        geo = fetch_json("https://geocoding-api.open-meteo.com/v1/search?" + query)
        results = geo.get("results") or []
        if not results:
            raise ValueError("没有找到这个城市，请检查拼写或尝试英文名称。")
        result = results[0]
        place = {"name": result["name"], "country": result.get("country", ""),
                 "latitude": result["latitude"], "longitude": result["longitude"]}
    params = urllib.parse.urlencode({
        "latitude": place["latitude"], "longitude": place["longitude"],
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "auto", "forecast_days": 5,
    })
    weather = fetch_json("https://api.open-meteo.com/v1/forecast?" + params)
    current = weather["current"]
    units = weather.get("current_units", {})
    daily = weather.get("daily", {})
    country = place.get("country", "")
    record = {
        "city": place["name"], "country": country,
        "observed_at": current["time"], "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "temperature": current.get("temperature_2m"),
        "feels_like": current.get("apparent_temperature"),
        "humidity": current.get("relative_humidity_2m"),
        "precipitation": current.get("precipitation"),
        "wind_speed": current.get("wind_speed_10m"),
        "weather_code": current.get("weather_code"), "is_day": current.get("is_day"),
        "latitude": place.get("latitude"), "longitude": place.get("longitude"),
    }
    with db_connect() as conn:
        conn.execute("""INSERT INTO observations
            (city,country,observed_at,captured_at,temperature,feels_like,humidity,precipitation,wind_speed,weather_code,is_day,latitude,longitude)
            VALUES (:city,:country,:observed_at,:captured_at,:temperature,:feels_like,:humidity,:precipitation,:wind_speed,:weather_code,:is_day,:latitude,:longitude)""", record)
    return {"place": {"name": record["city"], "country": country, "latitude": record["latitude"], "longitude": record["longitude"]},
            "current": dict(current), "current_units": units, "daily": daily,
            "timezone": weather.get("timezone"), "fetched_at": datetime.now(timezone.utc).isoformat(), "source": "Open-Meteo"}


def history_csv(rows):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["城市", "国家/地区", "观测时间（当地）", "采集时间 UTC", "温度 °C", "体感温度 °C", "湿度 %", "降水 mm", "风速 km/h", "天气代码", "纬度", "经度"])
    for row in rows:
        values = list(row)
        for index in (0, 1):
            if isinstance(values[index], str) and values[index].lstrip().startswith(("=", "+", "-", "@")):
                values[index] = "'" + values[index]
        writer.writerow(values)
    return ("\ufeff" + output.getvalue()).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

    def send_bytes(self, status, content_type, body, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status, payload):
        self.send_bytes(status, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            self.send_bytes(200, "text/html; charset=utf-8", (ROOT / "index.html").read_bytes(), {"Cache-Control": "no-store"})
        elif parsed.path == "/api/weather":
            query = urllib.parse.parse_qs(parsed.query)
            city = query.get("city", [""])[0]
            region_path = query.get("path", [""])[0].split("|") if query.get("path", [""])[0] else None
            selected_place = None
            if query.get("latitude") and query.get("longitude"):
                try:
                    selected_place = {
                        "name": city,
                        "country": query.get("country", [""])[0],
                        "latitude": float(query["latitude"][0]),
                        "longitude": float(query["longitude"][0]),
                    }
                except (ValueError, TypeError):
                    self.send_json(400, {"error": "城市坐标无效，请重新选择。"})
                    return
            try:
                self.send_json(200, get_weather(city, region_path, selected_place))
            except ValueError as error:
                self.send_json(400, {"error": str(error)})
            except Exception as error:
                print("Weather request failed:", repr(error))
                self.send_json(502, {"error": "天气服务暂时不可用，请稍后重试并检查网络连接。"})
        elif parsed.path == "/api/locations":
            query = urllib.parse.parse_qs(parsed.query)
            term = " ".join(query.get("q", [""])[0].strip().split())
            if len(term) < 2:
                self.send_json(200, {"items": []})
                return
            try:
                params = urllib.parse.urlencode({"name": term, "count": 8, "language": "zh", "format": "json"})
                data = fetch_json("https://geocoding-api.open-meteo.com/v1/search?" + params)
                items = [{
                    "name": item.get("name", ""), "country": item.get("country", ""),
                    "admin1": item.get("admin1", ""), "admin2": item.get("admin2", ""),
                    "latitude": item.get("latitude"), "longitude": item.get("longitude"),
                    "timezone": item.get("timezone", ""),
                } for item in (data.get("results") or []) if item.get("name") and item.get("latitude") is not None]
                self.send_json(200, {"items": items})
            except Exception as error:
                print("Location search failed:", repr(error))
                self.send_json(502, {"error": "全球城市搜索暂时不可用。"})
        elif parsed.path == "/api/history":
            query = urllib.parse.parse_qs(parsed.query)
            city = query.get("city", [""])[0].strip()
            try:
                limit = min(max(int(query.get("limit", ["8"])[0]), 1), 100)
            except ValueError:
                limit = 8
            try:
                offset = min(max(int(query.get("offset", ["0"])[0]), 0), 1000000)
            except ValueError:
                offset = 0
            with db_connect() as conn:
                all_total = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
                if city:
                    total = conn.execute("SELECT COUNT(*) FROM observations WHERE city = ? COLLATE NOCASE", (city,)).fetchone()[0]
                    rows = conn.execute("SELECT * FROM observations WHERE city = ? COLLATE NOCASE ORDER BY captured_at DESC, id DESC LIMIT ? OFFSET ?", (city, limit, offset)).fetchall()
                else:
                    total = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
                    rows = conn.execute("SELECT * FROM observations ORDER BY captured_at DESC, id DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
            self.send_json(200, {"items": [dict(row) for row in rows], "total": total, "all_total": all_total, "has_more": offset + len(rows) < total})
        elif parsed.path == "/api/regions":
            self.send_bytes(200, "application/json; charset=utf-8", (ROOT / "regions.json").read_bytes(), {"Cache-Control": "public, max-age=86400"})
        elif parsed.path == "/api/export":
            with db_connect() as conn:
                rows = conn.execute("SELECT city,country,observed_at,captured_at,temperature,feels_like,humidity,precipitation,wind_speed,weather_code,latitude,longitude FROM observations ORDER BY captured_at DESC, id DESC").fetchall()
            body = history_csv(rows)
            self.send_bytes(200, "text/csv; charset=utf-8", body, {"Content-Disposition": "attachment; filename=weather-history.csv"})
        else:
            self.send_json(404, {"error": "未找到请求的路径。"})

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/history":
            self.send_json(404, {"error": "未找到请求的路径。"})
            return
        with db_connect() as conn:
            deleted = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            conn.execute("DELETE FROM observations")
        self.send_json(200, {"deleted": deleted})


if __name__ == "__main__":
    init_db()
    print("天气记录本已启动: http://127.0.0.1:%d" % PORT)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
