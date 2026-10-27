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

export const runStateLabels: Record<string, string> = {
  queued: "대기",
  running: "실행 중",
  cancelling: "취소 중",
  succeeded: "완료",
  failed: "실패",
  cancelled: "취소",
  timed_out: "시간 초과",
  interrupted: "중단",
};
