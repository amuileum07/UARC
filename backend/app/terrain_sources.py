"""Public raster DEMs and explicit local imports normalized for display and contact."""

import hashlib
from contextlib import ExitStack
from datetime import UTC, datetime
from math import asinh, ceil, cos, floor, log2, pi, radians, tan
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.io import MemoryFile
from rasterio.merge import merge
from rasterio.transform import array_bounds, from_bounds
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform

from app.http import https_context
from app.schemas import TerrainGrid, TerrainImportOptions, TerrainRequest
from app.terrain import EARTH_RADIUS_M, coordinates

PORTALS = {
    "aws": "https://registry.opendata.aws/terrain-tiles/",
    "local": "https://map.ngii.go.kr/ms/map/NlipMap.do",
    "opentopography": "https://portal.opentopography.org/myopentopo",
    "vworld": "https://www.vworld.kr/dev/v4api.do",
}
RASTER_ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "GDAL_CACHEMAX": 32 * 1024**2,
    "PROJ_NETWORK": "OFF",
}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("지형 서비스의 리디렉션은 허용하지 않습니다.")


def _download(url, *, limit=16 * 1024**2):
    """Provider-built HTTPS URLs only; credentials never enter diagnostic messages."""
    try:
        with build_opener(_NoRedirect, HTTPSHandler(context=https_context())).open(
            Request(url, headers={"User-Agent": "UARC/0.1 DEM"}), timeout=30
        ) as response:
            raw = response.read(limit + 1)
    except HTTPError as error:
        raise ValueError(
            f"지형 요청 실패 (HTTP {error.code}). 키·권한·조회 범위를 확인하세요."
        ) from None
    except (URLError, TimeoutError, OSError):
        raise ValueError(
            "지형 서비스에 연결할 수 없습니다. 네트워크를 확인하세요."
        ) from None
    if len(raw) > limit:
        raise ValueError("지형 응답 크기 제한을 초과했습니다. 조회 반경을 줄이세요.")
    return raw


def grid_layout(request):
    south, _ = coordinates(request.latitude, request.longitude, 0, -request.radius_m)
    north, _ = coordinates(request.latitude, request.longitude, 0, request.radius_m)
    _, west = coordinates(request.latitude, request.longitude, -request.radius_m, 0)
    _, east = coordinates(request.latitude, request.longitude, request.radius_m, 0)
    if (
        not (-85 <= south < north <= 85 and -180 <= west < east <= 180)
        or east - west > 0.4
    ):
        raise ValueError(
            "날짜 변경선·극지방을 걸치는 범위는 지원하지 않습니다. 반경을 줄이세요."
        )
    # JSON snapshots remain bounded; the actual spacing is reported rather than hidden.
    count = min(257, max(3, 2 * ceil(request.radius_m / request.spacing_m) + 1))
    dx, dy = (east - west) / (count - 1), (north - south) / (count - 1)
    affine = from_bounds(
        west - dx / 2, south - dy / 2, east + dx / 2, north + dy / 2, count, count
    )
    return (south, west, north, east), count, affine


def _source_spacing(dataset, crs):
    x, y = dataset.transform * (dataset.width / 2, dataset.height / 2)
    a, b = dataset.transform * (dataset.width / 2 + 1, dataset.height / 2)
    c, d = dataset.transform * (dataset.width / 2, dataset.height / 2 + 1)
    lon, lat = transform(crs, "EPSG:4326", [x, a, c], [y, b, d])
    scale = EARTH_RADIUS_M * pi / 180
    return max(
        np.hypot((lon[i] - lon[0]) * cos(radians(lat[0])), lat[i] - lat[0]) * scale
        for i in (1, 2)
    )


def _resample(dataset, request, *, crs_epsg=None, height_scale=1):
    if dataset.count != 1 or dataset.width > 200_000 or dataset.height > 200_000:
        raise ValueError(
            "단일 고도 밴드 DEM을 선택하세요. 지원 크기는 각 축 200,000 픽셀까지입니다."
        )
    if dataset.dtypes[0].startswith("complex"):
        raise ValueError("복소수 래스터는 고도 자료로 사용할 수 없습니다.")
    if (
        dataset.block_shapes[0][0]
        * dataset.block_shapes[0][1]
        * np.dtype(dataset.dtypes[0]).itemsize
        > 64 * 1024**2
    ):
        raise ValueError(
            "DEM 압축 블록이 너무 큽니다. 타일 GeoTIFF로 변환한 뒤 가져오세요."
        )
    crs = f"EPSG:{crs_epsg}" if crs_epsg else dataset.crs
    if not crs:
        raise ValueError(
            "원본의 좌표계가 없습니다. 자료 설명서의 EPSG 코드를 지정하세요."
        )
    if dataset.transform == rasterio.Affine.identity():
        raise ValueError("지리 참조가 없는 원시 배열은 GeoTIFF로 변환한 뒤 가져오세요.")
    _, count, affine = grid_layout(request)
    with WarpedVRT(
        dataset,
        src_crs=crs,
        crs="EPSG:4326",
        transform=affine,
        width=count,
        height=count,
        dtype="float64",
        nodata=float("nan"),
        resampling=Resampling.bilinear,
        warp_mem_limit=32,
    ) as vrt:
        values = vrt.read(1)
    values = (values * dataset.scales[0] + dataset.offsets[0]) * height_scale
    return values, float(_source_spacing(dataset, crs))


def _grid(request, values, *, reference, source, resolution):
    if not np.isfinite(values).all():
        raise ValueError(
            "조회 범위에 결측 고도 또는 원본 밖 영역이 있습니다. 다른 도엽을 선택하거나 반경을 줄이세요."
        )
    if np.any(values < -12_000) or np.any(values > 10_000):
        raise ValueError(
            "고도 값이 지구 DEM 범위를 벗어났습니다. 단위·NoData·스케일을 확인하세요."
        )
    (south, west, north, east), count, _ = grid_layout(request)
    digest = hashlib.sha256(np.asarray(values, dtype="<f8").tobytes()).hexdigest()
    return TerrainGrid(
        south=south,
        west=west,
        north=north,
        east=east,
        heights=np.flipud(values).tolist(),
        reference=reference,
        provider=request.provider,
        source=f"{source}; grid SHA256 {digest}",
        retrieved_at=datetime.now(UTC).isoformat(),
        source_resolution_m=resolution,
        sampling_distance_m=2 * request.radius_m / (count - 1),
    )


def _tile(latitude, longitude, zoom):
    n = 2**zoom
    return floor((longitude + 180) / 360 * n), floor(
        (1 - asinh(tan(radians(latitude))) / pi) / 2 * n
    )


def _aws(request):
    _, count, target_transform = grid_layout(request)
    west, south, east, north = array_bounds(count, count, target_transform)
    spacing = 2 * request.radius_m / (count - 1)
    zoom = min(
        14,
        max(
            0,
            ceil(
                log2(
                    2
                    * pi
                    * EARTH_RADIUS_M
                    * cos(radians(request.latitude))
                    / (512 * spacing)
                )
            ),
        ),
    )
    x0, y0 = _tile(north, west, zoom)
    x1, y1 = _tile(south, east, zoom)
    if (x1 - x0 + 1) * (y1 - y0 + 1) > 16:
        raise ValueError("AWS 조회 타일 수 제한을 초과했습니다.")
    with ExitStack() as stack:
        datasets = []
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                raw = _download(
                    f"https://elevation-tiles-prod.s3.amazonaws.com/geotiff/{zoom}/{x}/{y}.tif",
                    limit=4 * 1024**2,
                )
                memory = stack.enter_context(MemoryFile(raw))
                dataset = stack.enter_context(memory.open(driver="GTiff"))
                if (
                    dataset.count != 1
                    or dataset.width != 512
                    or dataset.height != 512
                    or dataset.crs != rasterio.CRS.from_epsg(3857)
                ):
                    raise ValueError("예상한 AWS GeoTIFF 타일 규격이 아닙니다.")
                datasets.append(dataset)
        mosaic, affine = merge(
            datasets, indexes=[1], dtype="float64", nodata=float("nan")
        )
        memory = stack.enter_context(MemoryFile())
        with memory.open(
            driver="GTiff",
            width=mosaic.shape[2],
            height=mosaic.shape[1],
            count=1,
            crs="EPSG:3857",
            transform=affine,
            dtype="float64",
            nodata=float("nan"),
        ) as writer:
            writer.write(mosaic)
        dataset = stack.enter_context(memory.open())
        values, resolution = _resample(dataset, request)
    return _grid(
        request,
        values,
        reference="EGM96",
        source="AWS Open Data / Terrain Tiles (USGS and contributors)",
        resolution=resolution,
    )


def fetch_dem(request: TerrainRequest) -> TerrainGrid:
    with rasterio.Env(**RASTER_ENV):
        if request.provider == "aws":
            return _aws(request)
        if request.provider != "opentopography":
            raise ValueError("로컬 DEM은 파일 선택으로 가져오세요.")
        key = request.api_key.get_secret_value().strip()
        if not 8 <= len(key) <= 256 or any(c.isspace() for c in key):
            raise ValueError("OpenTopography API 키를 입력하세요.")
        (south, west, north, east), count, _ = grid_layout(request)
        # Cover edge-node pixel footprints, not just their centers, before warping.
        latitude_pad = max((north - south) / (count - 1), 90 / 111_195)
        longitude_pad = max(
            (east - west) / (count - 1), latitude_pad / cos(radians(request.latitude))
        )
        query = urlencode(
            dict(
                demtype=request.dataset,
                south=south - latitude_pad,
                north=north + latitude_pad,
                west=west - longitude_pad,
                east=east + longitude_pad,
                outputFormat="GTiff",
                API_Key=key,
            )
        )
        raw = _download("https://portal.opentopography.org/API/globaldem?" + query)
        try:
            with MemoryFile(raw) as memory, memory.open(driver="GTiff") as dataset:
                values, _ = _resample(dataset, request)
        except rasterio.errors.RasterioError:
            raise ValueError(
                "OpenTopography가 GeoTIFF를 반환하지 않았습니다. 키·할당량·데이터 범위를 확인하세요."
            ) from None
        reference, resolution = {
            "SRTMGL1": ("EGM96", 30),
            "SRTMGL3": ("EGM96", 90),
            "COP30": ("EGM2008", 30),
        }[request.dataset]
        return _grid(
            request,
            values,
            reference=reference,
            resolution=resolution,
            source=f"OpenTopography / {request.dataset}",
        )


def import_dem(source: Path, options: TerrainImportOptions) -> TerrainGrid:
    source = source.resolve(strict=True)
    if not source.is_file() or source.suffix.lower() not in {
        ".tif",
        ".tiff",
        ".img",
        ".asc",
        ".hgt",
    }:
        raise ValueError(
            "GeoTIFF(.tif), ERDAS IMG(.img), ASCII Grid(.asc), HGT(.hgt)를 선택하세요."
        )
    before = source.stat()
    if before.st_size > 2 * 1024**3:
        raise ValueError(
            "로컬 DEM은 2 GiB까지 지원합니다. 관심 영역을 GeoTIFF로 잘라 주세요."
        )
    try:
        driver = {
            ".tif": "GTiff",
            ".tiff": "GTiff",
            ".img": "HFA",
            ".asc": "AAIGrid",
            ".hgt": "SRTMHGT",
        }[source.suffix.lower()]
        with (
            rasterio.Env(**RASTER_ENV),
            rasterio.open(source, driver=driver) as dataset,
        ):
            if any(Path(name).resolve() != source for name in dataset.files):
                raise ValueError(
                    "외부 파일에 의존하는 DEM입니다. 단일 GeoTIFF로 변환한 뒤 가져오세요."
                )
            values, resolution = _resample(
                dataset,
                options.area,
                crs_epsg=options.crs_epsg,
                height_scale=options.height_scale,
            )
    except rasterio.errors.RasterioError:
        raise ValueError(
            "DEM을 읽을 수 없습니다. 지리 참조·좌표계·파일 형식을 확인하세요."
        ) from None
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("가져오는 동안 원본 DEM이 변경되었습니다. 다시 선택하세요.")
    request = options.area.model_copy(update={"provider": "local"})
    return _grid(
        request,
        values,
        reference=options.reference,
        source=f"Local DEM / {source.name[:160]}",
        resolution=resolution,
    )
