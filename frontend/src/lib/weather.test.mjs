import assert from "node:assert/strict";
import { test } from "node:test";
import {
  applyWeather,
  localDateInput,
  weatherMatches,
  weatherRequest,
  suggestWeatherColumns,
} from "./weather.ts";
import { placeLaunchSite } from "./edit.ts";

const env = {
  latitude: 35,
  longitude: 129,
  elevation: 100,
  datum: "WGS84",
  date: "2026-10-26T12:30",
  timezone: "Asia/Seoul",
  elevation_reference: "EGM96",
  geoid_undulation_m: null,
};
const profile = {
  levels: [{ altitude_m: 0 }, { altitude_m: 20000 }],
  request: {
    ...weatherRequest(env, "gfs_seamless"),
    date: "2026-10-26T12:30:00",
  },
};

test("file columns use recognizable names while units remain explicit", () => {
  const columns = suggestWeatherColumns([
    "altitude_m",
    "pressure_hPa",
    "temperature_C",
    "DRCT",
    "SPED",
  ]);
  assert.equal(columns.altitude, "altitude_m");
  assert.equal(columns.pressure, "pressure_hPa");
  assert.equal(columns.temperature, "temperature_C");
  assert.equal(columns.wind_direction, "DRCT");
  assert.equal(columns.wind_speed, "SPED");
  assert.equal(columns.wind_u, "");
  assert.throws(() =>
    applyWeather(
      { environment: env },
      { ...profile, levels: [{ altitude_m: 200 }, { altitude_m: 2000 }] },
    ),
  );
});

test("Wyoming station and UTC observation are independent of launch site/time", () => {
  const request = weatherRequest(env, "wyoming_sounding", {
    station_id: "47122",
    observation_time: "2026-10-26T00:00:00Z",
  });
  assert.equal(request.station_id, "47122");
  assert.equal(request.latitude, 35);
  assert.equal(request.date, env.date);
  assert.equal(weatherMatches(env, { ...profile, request }), true);
});

test("launch time preserves offsets/seconds and renders in the selected IANA zone", () => {
  assert.equal(localDateInput([2026, 10, 26, 12]), "2026-10-26T12:00");
  assert.equal(
    localDateInput("2026-10-26T03:30:00Z", "Asia/Seoul"),
    "2026-10-26T12:30",
  );
  assert.equal(localDateInput("2026-10-26T03:30:00Z", "invalid"), "");
  assert.equal(
    weatherRequest(
      { ...env, date: "2026-10-26T12:30:45+09:00" },
      "ecmwf_ifs025",
    ).date,
    "2026-10-26T12:30:45+09:00",
  );
  assert.throws(() => weatherRequest({ ...env, date: null }, "gfs_seamless"));
  assert.throws(() =>
    weatherRequest({ ...env, datum: "NAD83" }, "gfs_seamless"),
  );
});
test("weather application is atomic, clears external/manual inputs, and keeps the original", () => {
  const original = {
    environment: { ...env, pressure: 90000, wind_u: 5, atmosphere_file: "GFS" },
  };
  const applied = applyWeather(original, profile);
  assert.equal(applied.pressure, null);
  assert.equal(applied.wind_u, 0);
  assert.equal(applied.atmosphere_file, null);
  assert.equal(applied.weather_profile, profile);
  assert.equal(original.environment.wind_u, 5);
  assert.equal(applied.atmosphere_type, "custom_atmosphere");
});
test("late forecasts cannot apply to a changed site, height, time or vertical reference", () => {
  assert.equal(weatherMatches(env, profile), true);
  for (const changes of [
    { latitude: 36 },
    { longitude: 130 },
    { elevation: 101 },
    { pad_height_m: 2 },
    { date: "2026-10-26T12:31" },
    { date: "2026-10-26T12:30:01" },
    { timezone: "UTC" },
    { elevation_reference: "ellipsoid" },
    { geoid_undulation_m: 10 },
  ]) {
    assert.equal(weatherMatches({ ...env, ...changes }, profile), false);
    assert.throws(() =>
      applyWeather({ environment: { ...env, ...changes } }, profile),
    );
  }
});
test("map/search selection updates WGS84 coordinates together and invalidates only local site data", () => {
  const original = {
    environment: {
      ...env,
      elevation: 123,
      weather_profile: profile,
      terrain_mode: "terrain",
      terrain: { heights: [[1]] },
      geoid_undulation_m: 25,
    },
  };
  const moved = placeLaunchSite(original, 36, 130);
  assert.equal(moved.environment.latitude, 36);
  assert.equal(moved.environment.longitude, 130);
  assert.equal(moved.environment.datum, "WGS84");
  assert.equal(moved.environment.elevation, 123);
  assert.equal(moved.environment.terrain, null);
  assert.equal(moved.environment.terrain_mode, "flat");
  assert.equal(moved.environment.geoid_undulation_m, null);
  assert.equal(moved.environment.weather_profile, profile);
  assert.equal(weatherMatches(moved.environment, profile), false);
  assert.notEqual(original.environment.terrain, null);
  assert.throws(() => placeLaunchSite(original, Infinity, 130));
  assert.throws(() => placeLaunchSite(original, 91, 130));
  assert.equal(placeLaunchSite(original, 35, 129), original);
});
