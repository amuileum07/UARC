import assert from "node:assert/strict";
import { test } from "node:test";
import {
  flightCoordinates,
  flightPath,
  nearestTimeIndex,
} from "./geography.ts";

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

test("nearest trajectory time preserves first duplicates and earlier ties", () => {
  for (const [times, time, expected] of [
    [[], 0, -1],
    [[2], -10, 0],
    [[0, 1, 1, 3], 1, 1],
    [[0, 1, 1, 3], 1.1, 1],
    [[0, 1, 1, 3], 2, 1],
    [[0, 1, 1, 3], 2.1, 3],
    [[0, 3, 3], 100, 1],
    [[0, 0], 10, 0],
    [[0, 1], NaN, -1],
  ])
    assert.equal(nearestTimeIndex(times, time), expected);
  const times = Array.from({ length: 1000 }, (_, i) => Math.floor(i / 3));
  for (let time = -1; time < 335; time += 0.37) {
    let expected = 0;
    for (let i = 1; i < times.length; i++)
      if (Math.abs(times[i] - time) < Math.abs(times[expected] - time))
        expected = i;
    assert.equal(nearestTimeIndex(times, time), expected);
  }
});

test("nearest trajectory time reads logarithmically many samples", () => {
  let reads = 0;
  const times = new Proxy(
    Array.from({ length: 65536 }, (_, i) => Math.floor(i / 2)),
    {
      get(target, key) {
        if (/^\d+$/.test(String(key))) reads++;
        return Reflect.get(target, key);
      },
    },
  );
  assert.equal(nearestTimeIndex(times, 12345.25), 24690);
  assert.ok(reads < 40, `Read ${reads} samples`);
});

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
