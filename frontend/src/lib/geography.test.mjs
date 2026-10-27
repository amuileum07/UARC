import assert from "node:assert/strict";
import { test } from "node:test";
import { flightCoordinates, flightPath } from "./geography.ts";

const site = {
  latitude: 35.55,
  longitude: 129.3,
  elevation_reference: "EGM96",
  geoid_undulation_m: 25,
};
const telemetry = {
  columns: ["z_asl_m", "y_m", "time_s", "x_m"],
  data: [
    [100, 0, 0, 0],
    [600, 50, 2, 100],
    [80, 100, 5, 200],
  ],
};

test("maps named telemetry columns to absolute 3D heights at the run's frozen site", () => {
  const path = flightPath(telemetry, site);
  assert.ok(Math.abs(path[0].latitude - site.latitude) < 1e-10);
  assert.ok(Math.abs(path[0].longitude - site.longitude) < 1e-10);
  assert.equal(path[0].time, 0);
  assert.equal(path[0].height, 125);
  const [latitude, longitude] = flightCoordinates(35.55, 129.3, 100, 50);
  assert.deepEqual(path[1], { latitude, longitude, time: 2, height: 625 });
  assert.equal(path[2].height, 105); // Descent below launch height stays below it.
  assert.equal(telemetry.data[1][0], 600);
  assert.equal(
    flightPath(telemetry, { ...site, elevation_reference: "ellipsoid" })[1]
      .height,
    600,
  );
  assert.equal(
    flightPath(telemetry, { ...site, geoid_undulation_m: null })[1].height,
    600,
  );
});

test("rejects incomplete, nonfinite, reversed, or out-of-range flight positions", () => {
  assert.throws(
    () => flightPath({ columns: ["time_s"], data: [] }, site),
    /x_m/,
  );
  for (const row of [
    [NaN, 0, 1, 0],
    [100, 0, 1],
    [100, 0, -1, 0],
    [100, 0, 1, 10_001],
  ])
    assert.throws(() =>
      flightPath({ ...telemetry, data: [telemetry.data[0], row] }, site),
    );
  assert.deepEqual(flightPath({ ...telemetry, data: [] }, site), []);
});
