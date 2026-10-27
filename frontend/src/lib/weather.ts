import type {
  EnvironmentConfig,
  RocketDesign,
  WeatherColumns,
  WeatherProfile,
  WeatherRequest,
} from "./types";

export const weatherModels = {
  gfs_seamless: "NOAA GFS",
  ecmwf_ifs025: "ECMWF IFS 0.25°",
  wyoming_sounding: "University of Wyoming · 고층 관측",
  file: "CSV · Excel 파일",
} as const;

export function suggestWeatherColumns(names: string[]): WeatherColumns {
  const find = (aliases: string[]) =>
    names.find((name) =>
      aliases.includes(name.toLowerCase().replace(/[\s_()°/.-]/g, "")),
    ) || "";
  return {
    altitude: find([
      "altitude",
      "altitudem",
      "height",
      "heightm",
      "hght",
      "고도",
      "고도m",
    ]),
    pressure: find(["pressure", "pressurepa", "pressurehpa", "pres", "기압"]),
    temperature: find([
      "temperature",
      "temperaturek",
      "temperaturec",
      "temp",
      "기온",
    ]),
    wind_u: find(["u", "windu", "windums", "동쪽바람"]),
    wind_v: find(["v", "windv", "windvms", "북쪽바람"]),
    wind_speed: find(["speed", "windspeed", "sped", "sknt", "풍속"]),
    wind_direction: find(["direction", "winddirection", "drct", "풍향"]),
  };
}

export function localDateInput(
  value: EnvironmentConfig["date"],
  timezone = "UTC",
): string {
  if (!value) return "";
  if (Array.isArray(value)) {
    const [year, month, day, hour] = value;
    return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}T${String(hour).padStart(2, "0")}:00`;
  }
  if (!/(Z|[+-]\d{2}:\d{2})$/.test(value)) return value.slice(0, 16);
  try {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: timezone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).formatToParts(new Date(value));
    const part = (name: string) => parts.find((p) => p.type === name)?.value;
    return `${part("year")}-${part("month")}-${part("day")}T${part("hour")}:${part("minute")}`;
  } catch {
    return "";
  }
}

export function weatherRequest(
  env: EnvironmentConfig,
  model: WeatherRequest["model"],
  sounding?: Pick<WeatherRequest, "station_id" | "observation_time">,
): WeatherRequest {
  if (env.datum !== "WGS84")
    throw new Error("기상 조회에는 WGS84 좌표가 필요합니다.");
  if (!env.date) throw new Error("발사 날짜와 시각을 먼저 지정하세요.");
  const date = Array.isArray(env.date)
    ? `${localDateInput(env.date, env.timezone)}:00`
    : env.date;
  return {
    latitude: env.latitude,
    longitude: env.longitude,
    elevation: env.elevation,
    pad_height_m: env.pad_height_m || 0,
    elevation_reference: env.elevation_reference || "unknown",
    geoid_undulation_m: env.geoid_undulation_m ?? null,
    date,
    timezone: env.timezone || "UTC",
    model,
    ...sounding,
  };
}

export function automaticWeatherRequest(
  env: EnvironmentConfig,
): WeatherRequest | null {
  const profile = env.weather_profile;
  if (
    !profile ||
    profile.request.model === "file" ||
    weatherMatches(env, profile)
  )
    return null;
  try {
    return weatherRequest(
      env,
      profile.request.model,
      profile.request.model === "wyoming_sounding"
        ? {
            station_id: profile.request.station_id,
            observation_time: profile.request.observation_time,
          }
        : undefined,
    );
  } catch {
    return null;
  }
}

export function applyAutomaticWeather(
  design: RocketDesign,
  request: WeatherRequest,
  profile: WeatherProfile,
): RocketDesign {
  if (
    JSON.stringify(automaticWeatherRequest(design.environment)) !==
    JSON.stringify(request)
  )
    return design;
  return { ...design, environment: applyWeather(design, profile) };
}

export function preserveFileWeather(
  previous: EnvironmentConfig,
  current: EnvironmentConfig,
): EnvironmentConfig {
  const profile = previous.weather_profile;
  if (
    profile?.request.model !== "file" ||
    current.weather_profile !== profile ||
    previous.elevation_reference !== current.elevation_reference ||
    previous.geoid_undulation_m !== current.geoid_undulation_m ||
    weatherMatches(current, profile)
  )
    return current;
  try {
    // Keep imported absolute heights/values and provenance; only rebind the site/time.
    // A changed vertical reference needs a new import, not relabelled heights.
    return {
      ...current,
      weather_profile: { ...profile, request: weatherRequest(current, "file") },
    };
  } catch {
    return current;
  }
}

export function weatherMatches(
  env: EnvironmentConfig,
  profile: WeatherProfile,
) {
  try {
    const a = weatherRequest(env, profile.request.model);
    const b = profile.request;
    return (
      a.latitude === b.latitude &&
      a.longitude === b.longitude &&
      a.elevation === b.elevation &&
      a.pad_height_m === b.pad_height_m &&
      a.elevation_reference === b.elevation_reference &&
      a.geoid_undulation_m === b.geoid_undulation_m &&
      a.timezone === b.timezone &&
      dateSignature(a.date) === dateSignature(b.date)
    );
  } catch {
    return false;
  }
}

function dateSignature(value: string) {
  const aware = /(Z|[+-]\d{2}:\d{2})$/.test(value);
  return new Date(aware ? value : `${value}Z`).toISOString();
}

export function applyWeather(
  design: RocketDesign,
  profile: WeatherProfile,
): EnvironmentConfig {
  if (!weatherMatches(design.environment, profile))
    throw new Error(
      "요청 뒤 발사장·고도·시각이 바뀌었습니다. 기상을 다시 가져오세요.",
    );
  if (
    design.environment.elevation < profile.levels[0].altitude_m ||
    design.environment.elevation >
      profile.levels[profile.levels.length - 1].altitude_m
  )
    throw new Error(
      "자료 고도 범위에 발사 고도가 포함되지 않습니다. 다른 자료를 사용하세요.",
    );
  return {
    ...design.environment,
    weather_profile: profile,
    atmosphere_type: "custom_atmosphere",
    pressure: null,
    temperature: null,
    wind_u: 0,
    wind_v: 0,
    atmosphere_file: null,
    atmosphere_dictionary: null,
    pressure_conversion_factor: null,
    ensemble_member: 0,
  };
}
