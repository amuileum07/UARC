"""Raster/provider boundaries with deterministic DEMs, no network or API keys."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import numpy as np
import rasterio
from pydantic import ValidationError
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.warp import transform_bounds

from app.schemas import EnvironmentConfig, TerrainImportOptions, TerrainRequest
from app.terrain import GroundSurface, fetch_terrain, sample_grid
from app.terrain_sources import _download, grid_layout, import_dem


def raster_bytes(
    *,
    crs="EPSG:4326",
    bounds=(129.28, 35.53, 129.32, 35.57),
    missing=False,
    driver="GTiff",
):
    heights = np.repeat(np.linspace(200, 100, 80)[:, None], 80, axis=1).astype(
        "float32"
    )
    if missing:
        heights[30:50, 30:50] = -9999
    with MemoryFile() as memory:
        with memory.open(
            driver=driver,
            width=80,
            height=80,
            count=1,
            dtype="float32",
            crs=crs,
            transform=from_bounds(*bounds, 80, 80),
            nodata=-9999,
        ) as dataset:
            dataset.write(heights, 1)
        return memory.read()


class DemSourceTests(unittest.TestCase):
    def setUp(self):
        self.area = TerrainRequest(latitude=35.55, longitude=129.3, radius_m=200)

    def test_height_scale_is_strict_and_keeps_the_schema_enum(self):
        for scale in (1.0, 0.3048):
            options = TerrainImportOptions(area=self.area, height_scale=scale)
            self.assertEqual(options.height_scale, scale)
            self.assertEqual(
                TerrainImportOptions.model_validate_json(options.model_dump_json()),
                options,
            )
        for scale in (True, "1.0", 0, -1, 2, 0.3049, float("nan")):
            with self.subTest(scale=scale), self.assertRaises(ValidationError):
                TerrainImportOptions(area=self.area, height_scale=scale)
        schema = TerrainImportOptions.model_json_schema()
        self.assertEqual(schema["properties"]["height_scale"]["enum"], [1.0, 0.3048])

    def test_local_orientation_projected_crs_units_and_same_contact_surface(self):
        bounds = transform_bounds(
            "EPSG:4326", "EPSG:5186", 129.28, 35.53, 129.32, 35.57
        )
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "national.tif"
            source.write_bytes(raster_bytes(crs="EPSG:5186", bounds=bounds))
            grid = import_dem(
                source, TerrainImportOptions(area=self.area, reference="national")
            )
            self.assertGreater(grid.heights[-1][0], grid.heights[0][0])
            self.assertEqual(grid.provider, "local")
            self.assertEqual(grid.reference, "national")
            self.assertIn("SHA256", grid.source)
            env = EnvironmentConfig(
                latitude=35.55,
                longitude=129.3,
                datum="WGS84",
                elevation=180,
                elevation_reference="national",
                terrain=grid,
                terrain_mode="terrain",
            )
            self.assertAlmostEqual(
                GroundSurface(env).at(0, 0), sample_grid(grid, 35.55, 129.3), places=6
            )
            feet = import_dem(
                source,
                TerrainImportOptions(
                    area=self.area, reference="national", height_scale=0.3048
                ),
            )
            self.assertAlmostEqual(feet.heights[0][0], grid.heights[0][0] * 0.3048)

    def test_nodata_outside_coverage_unknown_crs_and_external_format_fail(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "bad.tif"
            source.write_bytes(raster_bytes(missing=True))
            with self.assertRaisesRegex(ValueError, "결측"):
                import_dem(source, TerrainImportOptions(area=self.area))
            source.write_bytes(raster_bytes(crs=None))
            with self.assertRaisesRegex(ValueError, "EPSG"):
                import_dem(source, TerrainImportOptions(area=self.area))
            grid = import_dem(
                source, TerrainImportOptions(area=self.area, crs_epsg=4326)
            )
            self.assertEqual(grid.reference, "unknown")
            source.write_bytes(raster_bytes(bounds=(0, 0, 1, 1)))
            with self.assertRaisesRegex(ValueError, "결측"):
                import_dem(source, TerrainImportOptions(area=self.area))
            source = Path(root) / "malicious.vrt"
            source.write_text("<VRTDataset/>")
            with self.assertRaises(ValueError):
                import_dem(source, TerrainImportOptions(area=self.area))

    def test_opentopography_queries_geotiff_and_keeps_credentials_out_of_snapshot(self):
        request = self.area.model_copy(
            update={"provider": "opentopography", "dataset": "COP30"}
        )
        request = TerrainRequest.model_validate(
            {**request.model_dump(), "api_key": "example-private-key"}
        )
        with patch(
            "app.terrain_sources._download", return_value=raster_bytes()
        ) as download:
            grid = fetch_terrain(request)
        self.assertIn("API_Key=example-private-key", download.call_args.args[0])
        self.assertEqual(grid.reference, "EGM2008")
        self.assertNotIn("example-private-key", grid.model_dump_json())
        self.assertNotIn("example-private-key", request.model_dump_json())
        with self.assertRaisesRegex(ValueError, "키"):
            fetch_terrain(self.area.model_copy(update={"provider": "opentopography"}))

    def test_aws_tile_mosaic_crosses_xy_boundaries_without_seams(self):
        from math import pi
        from urllib.parse import urlsplit

        from app.terrain import EARTH_RADIUS_M

        def tile(url, **_kwargs):
            parts = urlsplit(url).path.split("/")
            z, x, y = int(parts[-3]), int(parts[-2]), int(parts[-1].split(".")[0])
            span = 2 * pi * EARTH_RADIUS_M / 2**z
            # AWS EPSG:3857 uses the standard WGS84 semimajor axis.
            span *= 6378137 / EARTH_RADIUS_M
            left, top = -pi * 6378137 + x * span, pi * 6378137 - y * span
            rows = top - (np.arange(512) + 0.5) * span / 512
            values = np.repeat((100 + rows * 0.001)[:, None], 512, axis=1).astype(
                "float32"
            )
            with MemoryFile() as memory:
                with memory.open(
                    driver="GTiff",
                    width=512,
                    height=512,
                    count=1,
                    crs="EPSG:3857",
                    transform=from_bounds(left, top - span, left + span, top, 512, 512),
                    dtype="float32",
                ) as dataset:
                    dataset.write(values, 1)
                return memory.read()

        request = TerrainRequest(latitude=0, longitude=0, radius_m=300)
        with patch("app.terrain_sources._download", side_effect=tile) as download:
            grid = fetch_terrain(request)
        self.assertEqual(download.call_count, 4)
        self.assertEqual(grid.provider, "aws")
        self.assertEqual(grid.reference, "EGM96")
        self.assertEqual(len(grid.heights), 21)
        self.assertAlmostEqual(sample_grid(grid, 0, 0), 100, places=4)
        self.assertGreater(grid.heights[-1][10], grid.heights[0][10])
        self.assertAlmostEqual(grid.heights[-1][9], grid.heights[-1][11], places=5)

    def test_ngii_img_driver_reads_a_single_local_file(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "ngii.img"
            with rasterio.open(
                source,
                "w",
                driver="HFA",
                width=80,
                height=80,
                count=1,
                dtype="float32",
                crs="EPSG:4326",
                transform=from_bounds(129.28, 35.53, 129.32, 35.57, 80, 80),
            ) as dataset:
                dataset.write(np.full((80, 80), 150, dtype="float32"), 1)
            grid = import_dem(
                source, TerrainImportOptions(area=self.area, reference="national")
            )
        self.assertEqual(grid.heights[0][0], 150)

    def test_key_portals_are_fixed_and_arbitrary_urls_are_rejected(self):
        from app.bridge import DesktopBridge

        bridge = DesktopBridge()
        with patch("webbrowser.open", return_value=True) as opened:
            self.assertTrue(bridge.open_terrain_portal("opentopography"))
            self.assertEqual(
                opened.call_args.args[0], "https://portal.opentopography.org/myopentopo"
            )
            self.assertTrue(bridge.open_terrain_portal("vworld"))
            self.assertEqual(
                opened.call_args.args[0], "https://www.vworld.kr/dev/v4api.do"
            )
            with self.assertRaises(ValueError):
                bridge.open_terrain_portal("https://untrusted.invalid/")
            self.assertEqual(opened.call_count, 2)

    def test_download_error_does_not_expose_keys(self):
        url = "https://portal.opentopography.org/API/globaldem?API_Key=secret"
        with patch("app.terrain_sources.build_opener") as build:
            build.return_value.open.side_effect = HTTPError(
                url, 403, "secret", None, None
            )
            with self.assertRaisesRegex(ValueError, "HTTP 403") as caught:
                _download(url)
        self.assertNotIn("secret", str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)

    def test_layout_reports_actual_spacing_and_keeps_launch_center(self):
        large = self.area.model_copy(update={"radius_m": 5000, "spacing_m": 5})
        bounds, count, affine = grid_layout(large)
        self.assertEqual(count, 257)
        self.assertAlmostEqual(
            (bounds[1] + bounds[3]) / 2, self.area.longitude, places=5
        )
        self.assertLess(affine.e, 0)

    def test_different_orthometric_datums_are_not_converted_with_a_single_geoid_offset(
        self,
    ):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "dem.tif"
            source.write_bytes(raster_bytes())
            grid = import_dem(
                source, TerrainImportOptions(area=self.area, reference="national")
            )
        env = EnvironmentConfig(
            latitude=35.55,
            longitude=129.3,
            datum="WGS84",
            elevation=180,
            elevation_reference="EGM96",
            terrain=grid,
            geoid_undulation_m=20,
        )
        with self.assertRaisesRegex(ValueError, "orthometric"):
            GroundSurface(env).at(0, 0)


if __name__ == "__main__":
    unittest.main()
