"""Offline Korean POI/address search, service boundaries and cached results."""

import unittest
from copy import deepcopy
from unicodedata import normalize
from unittest.mock import call, patch

from pydantic import ValidationError

from app.bridge import DesktopBridge
from app.schemas import LocationResult, LocationSearch
from app.weather import PLACE_URL, SEARCH_URL, _search_places, search_locations


def feature(**changes):
    value = {
        "type": "Feature",
        "properties": {
            "osm_type": "W",
            "osm_id": 166906657,
            "name": "울산과학기술원",
            "osm_value": "university",
            "countrycode": "KR",
            "country": "대한민국",
            "city": "울산광역시",
            "district": "울주군",
            "street": "유니스트길",
            "housenumber": "50",
        },
        "geometry": {"type": "Point", "coordinates": [129.1898563, 35.573527]},
    }
    value["properties"].update(changes)
    return value


def collection(*features):
    return {"type": "FeatureCollection", "features": list(features)}


class LocationTests(unittest.TestCase):
    def setUp(self):
        _search_places.cache_clear()
        self.addCleanup(_search_places.cache_clear)
        timer = patch("app.weather.sleep")
        self.sleep = timer.start()
        self.addCleanup(timer.stop)

    def test_korean_unist_aliases_share_cached_coordinates_without_shared_mutation(
        self,
    ):
        with patch(
            "app.weather._read_json", return_value=(collection(feature()), "hash")
        ) as read:
            for query in (
                "UNIST",
                " unist ",
                "유니스트",
                "울산과학기술원",
                normalize("NFD", "유니스트"),
            ):
                with self.subTest(query=query):
                    places = search_locations(LocationSearch(query=query))
                    self.assertEqual(places[0].name, "울산과학기술원")
                    self.assertEqual(places[0].latitude, 35.573527)
                    self.assertEqual(places[0].id, "osm:W:166906657")
                    self.assertEqual(places[0].timezone, "Asia/Seoul")
                    self.assertEqual(places[0].category, "대학교")
                    self.assertIn("유니스트길, 50", places[0].region)
                    self.assertEqual(
                        LocationResult.model_validate_json(places[0].model_dump_json()),
                        places[0],
                    )
                    places[0].name = "Changed by caller"
            read.assert_called_once_with(
                PLACE_URL, {"q": "울산과학기술원", "limit": 8, "countrycode": "KR"}
            )

    def test_road_suffix_and_road_number_remain_searchable(self):
        with patch(
            "app.weather._read_json", return_value=(collection(feature()), "hash")
        ) as read:
            for query in ("UNIST-gill", "unist-gil", "UNIST gil", "유니스트길"):
                search_locations(LocationSearch(query=query))
            read.assert_called_once_with(
                PLACE_URL, {"q": "유니스트길", "limit": 8, "countrycode": "KR"}
            )
            search_locations(LocationSearch(query="UNIST-gill 50"))
            self.assertEqual(read.call_args.args[1]["q"], "유니스트길 50")

    def test_scope_changes_cache_and_foreign_timezone_is_not_guessed(self):
        response = collection(
            feature(), feature(osm_id=2, countrycode="FR", name="Paris")
        )
        with patch("app.weather._read_json", return_value=(response, "hash")) as read:
            self.assertEqual(len(search_locations(LocationSearch(query="Paris"))), 1)
            places = search_locations(LocationSearch(query="Paris", country="all"))
            self.assertEqual(len(places), 2)
            self.assertEqual(places[1].timezone, "")
            self.assertNotIn("countrycode", read.call_args.args[1])
            self.assertEqual(read.call_count, 2)

    def test_duplicate_osm_objects_collapse_but_node_and_way_ids_do_not_collide(self):
        response = collection(feature(), feature(), feature(osm_type="N"))
        with patch("app.weather._read_json", return_value=(response, "hash")):
            places = search_locations(LocationSearch(query="울산"))
        self.assertEqual(
            [place.id for place in places], ["osm:W:166906657", "osm:N:166906657"]
        )

    def test_empty_photon_results_fall_back_to_filtered_geonames(self):
        fallback = {
            "results": [
                dict(
                    id=1,
                    name="울산",
                    latitude=35.0,
                    longitude=129.0,
                    country_code="KR",
                    timezone="Asia/Seoul",
                )
            ]
        }
        with patch(
            "app.weather._read_json",
            side_effect=[(collection(), "hash"), (fallback, "hash")],
        ) as read:
            places = search_locations(LocationSearch(query="울산"))
        self.assertEqual(places[0].source, "GeoNames")
        self.assertEqual(
            read.call_args,
            call(
                SEARCH_URL,
                {
                    "name": "울산",
                    "count": 8,
                    "language": "ko",
                    "format": "json",
                    "countryCode": "KR",
                },
            ),
        )

    def test_unavailable_search_is_not_cached_as_no_results(self):
        with (
            patch("app.weather._read_json", side_effect=ValueError("offline")),
            self.assertRaises(ValueError),
        ):
            search_locations(LocationSearch(query="UNIST"))
        with patch(
            "app.weather._read_json", return_value=(collection(feature()), "hash")
        ) as read:
            self.assertTrue(search_locations(LocationSearch(query="UNIST")))
            self.assertEqual(read.call_count, 1)
        _search_places.cache_clear()
        with (
            patch(
                "app.weather._read_json",
                side_effect=[ValueError("offline"), ({"results": []}, "hash")],
            ),
            self.assertRaisesRegex(ValueError, "다시 검색"),
        ):
            search_locations(LocationSearch(query="UNIST"))

    def test_malformed_and_out_of_range_service_data_are_rejected(self):
        for modify in (
            lambda item: item.update(
                geometry={"type": "Point", "coordinates": [129, 91]}
            ),
            lambda item: item.update(
                geometry={"type": "Point", "coordinates": [True, 35]}
            ),
            lambda item: item.update(
                geometry={"type": "Point", "coordinates": [float("nan"), 35]}
            ),
            lambda item: item.update(geometry={"type": "Point", "coordinates": [129]}),
            lambda item: item.update(properties=None),
            lambda item: item["properties"].update(osm_type="malformed"),
        ):
            with self.subTest(modify=modify):
                item = deepcopy(feature())
                modify(item)
                with (
                    patch(
                        "app.weather._read_json",
                        return_value=(collection(item), "hash"),
                    ),
                    self.assertRaises(ValueError),
                ):
                    search_locations(LocationSearch(query="UNIST"))
        with (
            patch(
                "app.weather._read_json",
                return_value=(collection(*[feature()] * 9), "hash"),
            ),
            self.assertRaises(ValueError),
        ):
            search_locations(LocationSearch(query="UNIST"))

    def test_bridge_validation_and_throttle_apply_before_uncached_requests(self):
        for payload in (
            '{"query":"a"}',
            '{"query":"UNIST","country":"bad"}',
            '{"query":true}',
        ):
            with self.assertRaises(ValidationError):
                DesktopBridge().search_locations(payload)
        with (
            patch("app.weather._LAST_SEARCH", 100.0),
            patch("app.weather.monotonic", return_value=100.4),
            patch(
                "app.weather._read_json", return_value=(collection(feature()), "hash")
            ),
        ):
            result = DesktopBridge().search_locations('{"query":"UNIST"}')
        self.assertAlmostEqual(self.sleep.call_args.args[0], 0.7)
        self.assertEqual(result[0]["source"], "OpenStreetMap")


if __name__ == "__main__":
    unittest.main()
