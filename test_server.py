import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

import server


class WeatherProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "weather.db"
        self.db_patch = patch.object(server, "DB_PATH", self.db_path)
        self.db_patch.start()
        server.init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_weather_query_normalizes_city_and_persists_snapshot(self):
        geocoding = {"results": [{"name": "Shanghai", "country": "China", "latitude": 31.23, "longitude": 121.47}]}
        forecast = {
            "current": {"time": "2026-11-03T10:00", "temperature_2m": 18.5,
                        "apparent_temperature": 17.2, "relative_humidity_2m": 65,
                        "is_day": 1, "precipitation": 0, "weather_code": 1,
                        "wind_speed_10m": 7.1},
            "current_units": {"temperature_2m": "°C"},
            "daily": {"time": ["2026-11-03"], "temperature_2m_max": [20], "temperature_2m_min": [13]},
            "timezone": "Asia/Shanghai",
        }
        with patch.object(server, "fetch_json", side_effect=[geocoding, forecast]) as fetch:
            result = server.get_weather("  Shanghai   ")

        self.assertEqual(result["place"]["name"], "Shanghai")
        self.assertEqual(fetch.call_count, 2)
        self.assertIn("name=Shanghai", fetch.call_args_list[0].args[0])
        with server.db_connect() as conn:
            row = conn.execute("SELECT * FROM observations").fetchone()
        self.assertEqual(row["temperature"], 18.5)
        self.assertEqual(row["city"], "Shanghai")
        self.assertTrue(row["captured_at"])

    def test_rejects_empty_city_without_network_request(self):
        with patch.object(server, "fetch_json") as fetch:
            with self.assertRaises(ValueError):
                server.get_weather("   ")
        fetch.assert_not_called()

    def test_unknown_city_is_reported(self):
        with patch.object(server, "fetch_json", return_value={"results": []}):
            with self.assertRaisesRegex(ValueError, "没有找到"):
                server.get_weather("Nowhere")

    def test_selected_global_city_uses_exact_coordinates(self):
        forecast = {
            "current": {"time": "2026-11-03T10:00", "temperature_2m": 13},
            "current_units": {}, "daily": {}, "timezone": "Europe/Paris",
        }
        place = {"name": "Paris", "country": "France", "latitude": 48.8534, "longitude": 2.3488}
        with patch.object(server, "fetch_json", return_value=forecast) as fetch:
            result = server.get_weather("Paris", selected_place=place)
        self.assertEqual(result["place"]["country"], "France")
        self.assertIn("latitude=48.8534", fetch.call_args.args[0])
        self.assertEqual(fetch.call_count, 1)

    def test_selected_county_uses_exact_admin_boundary_and_caches_coordinates(self):
        boundary = [{"name": "朝阳区", "type": "administrative", "lat": "39.92", "lon": "116.44"}]
        forecast = {
            "current": {"time": "2026-11-03T10:00", "temperature_2m": 12},
            "current_units": {}, "daily": {}, "timezone": "Asia/Shanghai",
        }
        path = ["北京市", "市辖区", "朝阳区"]
        with patch.object(server, "fetch_json", side_effect=[boundary, forecast, forecast]) as fetch:
            first = server.get_weather("朝阳区", path)
            second = server.get_weather("朝阳区", path)
        self.assertEqual(first["place"]["name"], "朝阳区")
        self.assertEqual(first["place"]["latitude"], 39.92)
        self.assertEqual(second["current"]["temperature_2m"], 12)
        self.assertEqual(fetch.call_count, 3)
        self.assertIn("q=%E6%9C%9D%E9%98%B3%E5%8C%BA%2C+%E5%8C%97%E4%BA%AC%E5%B8%82", fetch.call_args_list[0].args[0])

    def test_taiwan_county_matches_traditional_map_boundary(self):
        boundary = [{"name": "大安區", "type": "administrative", "lat": "25.0265", "lon": "121.5344"}]
        forecast = {"current": {"time": "2026-11-03T10:00", "temperature_2m": 24}, "daily": {}, "timezone": "Asia/Taipei"}
        with patch.object(server, "fetch_json", side_effect=[boundary, forecast]) as fetch:
            result = server.get_weather("大安区", ["台湾省", "台北市", "大安区"])
        self.assertEqual(result["place"]["name"], "大安区")
        self.assertIn("q=%E5%A4%A7%E5%AE%89%E5%8C%BA%2C+%E5%8F%B0%E5%8C%97%E5%B8%82%2C+%E5%8F%B0%E6%B9%BE", fetch.call_args_list[0].args[0])

    def test_region_dataset_has_34_regions_and_county_level_leaves(self):
        regions = json.loads((Path(server.ROOT) / "regions.json").read_text(encoding="utf-8"))
        self.assertEqual(len(regions), 34)
        self.assertTrue({"香港特别行政区", "澳门特别行政区", "台湾省"}.issubset({item["name"] for item in regions}))
        self.assertEqual(sum(len(city["children"]) for province in regions for city in province["children"]), 3361)
        self.assertTrue(all(county.get("name") for province in regions for city in province["children"] for county in city["children"]))

    def test_homepage_starts_without_default_city_or_weather_request(self):
        html = (Path(server.ROOT) / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('value="上海"', html)
        self.assertIn('id="emptyChoose">选择地区，查看天气</button>', html)
        self.assertNotIn('<h2>选择一个地区</h2>', html)
        script = html.split("<script>", 1)[1].split("</script>", 1)[0]
        self.assertIn("loadRegions(); loadHistory(true);", script)
        self.assertNotIn("loadWeather($('#cityInput').value);", script)
        self.assertNotIn("autoCollect", script)
        self.assertIn("limit=8&offset=", script)

    def test_history_http_endpoint_paginates_and_filters(self):
        with server.db_connect() as conn:
            for index in range(11):
                city = "Shanghai" if index < 9 else "Beijing"
                conn.execute("""INSERT INTO observations(city,country,observed_at,captured_at,temperature)
                    VALUES(?,?,?,?,?)""", (city, "China", "2026-11-03T10:00", "2026-11-03T10:%02d:00+00:00" % index, index))

        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            url = "http://127.0.0.1:%d/api/history?city=Shanghai&limit=4&offset=4" % httpd.server_address[1]
            with urlopen(url) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["total"], 9)
            self.assertEqual(len(payload["items"]), 4)
            self.assertTrue(payload["has_more"])
            self.assertTrue(all(item["city"] == "Shanghai" for item in payload["items"]))
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_delete_history_endpoint_removes_all_observations(self):
        with server.db_connect() as conn:
            conn.execute("INSERT INTO observations(city,country,observed_at,captured_at,temperature) VALUES(?,?,?,?,?)",
                         ("Shanghai", "China", "2026-11-03T10:00", "2026-11-03T02:00:00+00:00", 18))
            conn.execute("INSERT INTO observations(city,country,observed_at,captured_at,temperature) VALUES(?,?,?,?,?)",
                         ("Beijing", "China", "2026-11-03T11:00", "2026-11-03T03:00:00+00:00", 12))

        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            url = "http://127.0.0.1:%d/api/history" % httpd.server_address[1]
            with urlopen(Request(url, method="DELETE")) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["deleted"], 2)
            with server.db_connect() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 0)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_init_db_migrates_legacy_schema(self):
        legacy_path = Path(self.temp_dir.name) / "legacy.db"
        with patch.object(server, "DB_PATH", legacy_path):
            with server.db_connect() as conn:
                conn.execute("""CREATE TABLE observations (
                    id INTEGER PRIMARY KEY, city TEXT NOT NULL, country TEXT NOT NULL DEFAULT '',
                    observed_at TEXT NOT NULL, temperature REAL, feels_like REAL, humidity INTEGER,
                    apparent_humidity INTEGER, precipitation REAL, wind_speed REAL, weather_code INTEGER,
                    is_day INTEGER, latitude REAL, longitude REAL)""")
                conn.execute("INSERT INTO observations(city, observed_at, temperature) VALUES('Shanghai', '2026-11-03T10:00', 18)")
            server.init_db()
            with server.db_connect() as conn:
                row = conn.execute("SELECT captured_at FROM observations").fetchone()
            self.assertEqual(row["captured_at"], "2026-11-03T10:00")

    def test_csv_export_has_expected_columns_and_protects_formula_cells(self):
        row = ["=2+2", "@weather", "2026-11-03T10:00", "2026-11-03T02:00:00+00:00", 18.5,
               17.2, 65, 0, 7.1, 1, 31.23, 121.47]
        exported = server.history_csv([row]).decode("utf-8-sig").splitlines()
        self.assertEqual(exported[0].split(",")[:4], ["城市", "国家/地区", "观测时间（当地）", "采集时间 UTC"])
        self.assertTrue(exported[1].startswith("'=2+2,'@weather,"))


if __name__ == "__main__":
    unittest.main()
