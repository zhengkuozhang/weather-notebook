#!/usr/bin/env python3
"""Build the bundled province/city/county selector data from the source datasets."""

import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = "https://raw.githubusercontent.com/modood/Administrative-divisions-of-China/master/dist/"


def read_json(name):
    request = urllib.request.Request(BASE + name, headers={"User-Agent": "LocalWeatherNotebook/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    mainland = read_json("pcas-code.json")
    special = read_json("HK-MO-TW.json")
    regions = []
    for province in mainland:
        cities = []
        for city in province.get("children", []):
            counties = [{"code": area["code"], "name": area["name"]}
                        for area in city.get("children", [])]
            cities.append({"code": city["code"], "name": city["name"], "children": counties})
        regions.append({"code": province["code"], "name": province["name"], "children": cities})

    for province_name, city_groups in special.items():
        cities = []
        for city_name, counties in city_groups.items():
            cities.append({"code": "", "name": city_name,
                           "children": [{"code": "", "name": county} for county in counties]})
        regions.append({"code": "", "name": province_name, "children": cities})

    output = ROOT / "regions.json"
    output.write_text(json.dumps(regions, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    city_count = sum(len(province["children"]) for province in regions)
    county_count = sum(len(city["children"]) for province in regions for city in province["children"])
    print("Wrote %s: %s province-level regions, %s cities/groups, %s counties/districts" %
          (output, len(regions), city_count, county_count))


if __name__ == "__main__":
    main()
