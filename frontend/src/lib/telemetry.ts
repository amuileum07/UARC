export const telemetryLabels: Record<string, string> = {
  time_s: "시간 (s)",
  x_m: "동쪽 위치 (m)",
  y_m: "북쪽 위치 (m)",
  z_asl_m: "고도 (m ASL)",
  vx_m_s: "동쪽 속도 (m/s)",
  vy_m_s: "북쪽 속도 (m/s)",
  vz_m_s: "수직 속도 (m/s)",
  e0: "쿼터니언 e0",
  e1: "쿼터니언 e1",
  e2: "쿼터니언 e2",
  e3: "쿼터니언 e3",
  w1_rad_s: "각속도 ω1 (rad/s)",
  w2_rad_s: "각속도 ω2 (rad/s)",
  w3_rad_s: "각속도 ω3 (rad/s)",
};
export const telemetryColumns = Object.keys(telemetryLabels);
