"""Real CSV/XLSX parsing, explicit conversions, bridge authorization, frozen replay."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook
from pydantic import ValidationError

from app.bridge import DesktopBridge
from app.importers.weather import import_weather_file, preview_weather_file
from app.schemas import RocketDesign, WeatherImportOptions, WeatherProfile
from app.simulation.engine import build_environment
from app.simulation.jobs import JobManager
from tests.test_weather import environment, weather_request

HEADERS = ["height", "pressure", "temperature", "u", "v"]
ROWS = [
    [0, 101325, 288.15, 1, 2],
    [1000, 89875, 281.65, 3, 4],
    [20000, 5500, 216.65, 5, 6],
]


class WeatherFileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "weather.csv"
        self.csv(ROWS)

    def csv(self, rows, headers=HEADERS, delimiter=",", encoding="utf-8-sig"):
        text = "\n".join(delimiter.join(map(str, row)) for row in [headers, *rows])
        self.source.write_text(text, encoding=encoding)

    def options(self, **changes):
        values = dict(
            request=weather_request(model="file"),
            columns=dict(
                zip(
                    ["altitude", "pressure", "temperature", "wind_u", "wind_v"],
                    HEADERS,
                    strict=True,
                )
            ),
            source_name=self.source.name,
            expected_sha256=preview_weather_file(self.source).sha256,
        )
        return WeatherImportOptions(**(values | changes))

    def test_csv_preview_and_sorted_profile_drive_rocketpy_offline(self):
        self.csv(list(reversed(ROWS)))
        table = preview_weather_file(self.source)
        self.assertEqual(table.columns, HEADERS)
        self.assertEqual(table.row_count, 3)
        self.assertIsNone(table.sheet)
        saved = import_weather_file(self.source, self.options())
        self.assertEqual(saved.source, "File")
        self.assertEqual(saved.levels[0].altitude_m, 0)
        native = build_environment(environment(saved))
        self.assertAlmostEqual(native.wind_velocity_x(1000), 3)
        self.assertAlmostEqual(native.temperature(1000), 281.65)

    def test_csv_korean_encoding_and_delimiter(self):
        names = ["고도", "기압", "기온", "동풍", "북풍"]
        self.csv(ROWS, names, ";", "cp949")
        table = preview_weather_file(self.source)
        self.assertEqual(table.columns, names)
        options = self.options(
            columns=dict(
                zip(
                    ["altitude", "pressure", "temperature", "wind_u", "wind_v"],
                    names,
                    strict=True,
                )
            )
        )
        self.assertEqual(
            import_weather_file(self.source, options).levels[0].pressure_pa, 101325
        )

    def test_feet_agl_hpa_celsius_knots_and_meteorological_direction(self):
        self.csv([[0, 1000, 20, 90, 10], [1000, 900, 10, 360, 20]])
        options = self.options(
            request=weather_request(model="file", elevation=102, pad_height_m=2),
            columns=dict(
                altitude="height",
                pressure="pressure",
                temperature="temperature",
                wind_speed="v",
                wind_direction="u",
            ),
            height_unit="ft",
            height_reference="AGL",
            pressure_unit="hPa",
            temperature_unit="C",
            wind_format="speed_direction",
            wind_unit="knots",
        )
        saved = import_weather_file(self.source, options)
        a, b = saved.levels
        self.assertEqual(a.altitude_m, 100)
        self.assertAlmostEqual(b.altitude_m, 404.8)
        self.assertAlmostEqual(a.temperature_k, 293.15)
        self.assertEqual(a.pressure_pa, 100000)
        self.assertAlmostEqual(a.wind_u_m_s, -10 * 1852 / 3600)
        self.assertAlmostEqual(b.wind_v_m_s, -20 * 1852 / 3600)

    def test_geopotential_and_geoid_conversion(self):
        options = self.options(
            request=weather_request(
                model="file", elevation_reference="ellipsoid", geoid_undulation_m=30
            ),
            height_reference="geopotential",
            wind_unit="km/h",
        )
        saved = import_weather_file(self.source, options)
        self.assertEqual(saved.levels[0].altitude_m, 30)
        self.assertGreater(saved.levels[1].altitude_m, 1030)
        self.assertAlmostEqual(saved.levels[0].wind_u_m_s, 1 / 3.6)

    def test_invalid_values_order_and_column_mapping_are_rejected(self):
        for bad in ("", "NaN", "Infinity", "bad"):
            with self.subTest(value=bad):
                self.csv([[0, 101325, 288, bad, 2], ROWS[1]])
                with self.assertRaisesRegex(ValueError, "2행 u"):
                    import_weather_file(self.source, self.options())
        for rows in (
            [ROWS[0], [0, 90000, 280, 1, 2]],
            [ROWS[0], [1000, 110000, 280, 1, 2]],
            [ROWS[0], [1000, 90000, -1, 1, 2]],
        ):
            self.csv(rows)
            with self.assertRaises(ValidationError):
                import_weather_file(self.source, self.options())
        self.csv(ROWS)
        with self.assertRaisesRegex(ValueError, "열을 파일"):
            import_weather_file(
                self.source,
                self.options(
                    columns=dict(
                        altitude="missing",
                        pressure="pressure",
                        temperature="temperature",
                        wind_u="u",
                        wind_v="v",
                    )
                ),
            )
        with self.assertRaises(ValidationError):
            self.options(
                columns=dict(
                    altitude="height",
                    pressure="pressure",
                    temperature="temperature",
                    wind_u="u",
                    wind_v="u",
                )
            )

    def test_changed_file_and_height_outside_coverage_are_rejected(self):
        options = self.options()
        self.csv(ROWS[:2])
        with self.assertRaisesRegex(ValueError, "파일이 바뀌"):
            import_weather_file(self.source, options)
        saved = import_weather_file(
            self.source,
            self.options(request=weather_request(model="file", elevation=2000)),
        )
        with self.assertRaisesRegex(ValidationError, "cover the launch"):
            environment(saved)

    def test_file_size_row_count_and_headers_are_bounded(self):
        for text in (
            "",
            "a,a,c,d,e\n1,2,3,4,5\n2,3,4,5,6",
            "a,,c,d,e\n1,2,3,4,5\n2,3,4,5,6",
            "a,b,c,d,e\n1,2,3,4,5,6\n2,3,4,5,6",
        ):
            self.source.write_text(text)
            with self.subTest(text=text), self.assertRaises(ValueError):
                preview_weather_file(self.source)
        self.csv([ROWS[0]] * 4097)
        with self.assertRaisesRegex(ValueError, "4096"):
            preview_weather_file(self.source)
        self.source.write_bytes(b"x" * (8 * 1024 * 1024 + 1))
        with self.assertRaisesRegex(ValueError, "8 MiB"):
            preview_weather_file(self.source)
        self.source = self.root / "old.xls"
        self.source.write_bytes(b"not a workbook")
        with self.assertRaisesRegex(ValueError, "xlsx"):
            preview_weather_file(self.source)

    def workbook(self):
        self.source = self.root / "weather.xlsx"
        book = Workbook()
        book.active.title = "설명"
        book.active.append(HEADERS)
        for row in ROWS:
            book.active.append(row)
        data = book.create_sheet("관측")
        data.append(HEADERS)
        for row in ROWS:
            data.append(row)
        return book

    def test_real_excel_sheet_selection_and_numeric_import(self):
        book = self.workbook()
        book.save(self.source)
        table = preview_weather_file(self.source, "관측")
        self.assertEqual(table.sheets, ["설명", "관측"])
        self.assertEqual(table.sheet, "관측")
        saved = import_weather_file(self.source, self.options(sheet="관측"))
        self.assertEqual(saved.levels[1].wind_v_m_s, 4)
        with self.assertRaisesRegex(ValueError, "시트가 없"):
            preview_weather_file(self.source, "missing")

    def test_excel_formulas_errors_and_hidden_out_of_range_cells_rejected(self):
        for value, cell in (
            ("=1+1", "D2"),
            ("#DIV/0!", "D2"),
            (True, "D2"),
            (1, "A5000"),
            (1, "AG2"),
        ):
            with self.subTest(value=value, cell=cell):
                book = self.workbook()
                book["관측"][cell] = value
                book.save(self.source)
                with self.assertRaises(ValueError):
                    import_weather_file(self.source, self.options(sheet="관측"))

    def test_bridge_only_reads_selected_assets_and_saved_design_keeps_original(self):
        with JobManager(self.root / "data") as jobs:
            bridge = DesktopBridge(jobs)
            with self.assertRaises(ValueError):
                bridge.preview_weather_file(str(self.source))
            asset = jobs.import_file(self.source)
            table = bridge.preview_weather_file(asset["path"])
            options = self.options(expected_sha256=table["sha256"])
            saved = bridge.import_weather_file(asset["path"], options.model_dump_json())
            design = RocketDesign.model_validate_json(
                Path("../examples/design.json").read_text()
            )
            design.environment = environment(
                WeatherProfile.model_validate_json(json.dumps(saved))
            )
            record = jobs.save_design(design)
            self.source.unlink()
            restored = RocketDesign.model_validate_json(
                json.dumps(jobs.get_saved_design(record["design_id"]))
            )
            source = Path(restored.environment.weather_profile.source_asset)
            self.assertTrue(source.is_file())
            self.assertIn("designs", source.parts)
            with patch(
                "app.weather._read_bytes", side_effect=AssertionError("offline")
            ):
                native = build_environment(restored.environment)
            self.assertAlmostEqual(native.wind_velocity_x(1000), 3)
