# 기능 확장과 CI·릴리스 검증 가이드

기능을 추가하거나 수정할 때 어떤 검증을 확장하고, 어떤 결과가 있어야 배포할 수 있는지 정한다.
2026-10-30의 저장소 구성을 기준으로 작성했다. **현재 구현된 검사와 앞으로 추가할 검사를 구분한다.**
이 문서를 추가한 것만으로 워크플로가 바뀌지는 않는다.

공식 지원 대상은 **Windows x64, Linux x64, macOS Apple Silicon(arm64)**이다.
Intel Mac은 지원 대상에서 제외되어 있다. 지원 범위와 검증 한계는 [PACKAGING.md](PACKAGING.md),
과거 실패와 실행 증거는 [VALIDATION.md](VALIDATION.md), 코드 규칙은 [CODING_STYLE.md](../CODING_STYLE.md)를 따른다.
도구 버전은 아래 설명에 복사해 고정하지 않고 manifests, lockfiles, workflow의 실제 값을 확인한다.

## 1. 현재 구성과 아직 없는 검증

| 항목                                             | Desktop acceptance                                                    | Release UARC                                            |
| ------------------------------------------------ | --------------------------------------------------------------------- | ------------------------------------------------------- |
| 정의                                             | [desktop-acceptance.yml](../.github/workflows/desktop-acceptance.yml) | [release.yml](../.github/workflows/release.yml)         |
| 실행 계기                                        | 수동 `workflow_dispatch`                                              | 수동 `workflow_dispatch`                                |
| Ruff lint·format                                 | Linux prepare에서 실행                                                | Linux prepare에서 실행                                  |
| Biome·TypeScript·프런트엔드 테스트·빌드          | 실행                                                                  | 실행                                                    |
| 프런트엔드 `format:check`                        | 현재 workflow에 없음                                                  | 현재 workflow에 없음                                    |
| 백엔드 전체 단위 테스트                          | Linux prepare에서 실행                                                | Linux prepare에서 실행                                  |
| OS별 추가 검사                                   | acceptance·launcher·URL 회귀 검사                                     | acceptance·launcher·URL 검사, Windows setup 검사 등     |
| Python wheel·sdist 빌드와 검사                   | 없음                                                                  | 실행, 세 OS에서 `--fresh --gui` 포함                    |
| 네이티브 실행 파일의 worker·파일 검사            | 최종 archive를 추출한 뒤 실행                                         | 빌드 폴더에서 실행, acceptance 선택 시 추출 후에도 실행 |
| 최종 archive의 실제 UI·WebGL·3D·정상 종료·재실행 | 세 OS에서 필수                                                        | `desktop_acceptance=true`(기본값)일 때 세 OS에서 필수   |
| 버전 변경·태그·GitHub Release·선택적 PyPI 게시   | 없음                                                                  | 모든 해당 release job 통과 후 실행                      |

현재 `push`/`pull_request`용 자동 CI workflow는 없다. 소스를 푸시했다는 이유만으로 위 검사가 실행되지는 않는다.
**Release UARC의 `desktop_acceptance` 옵션은 기본값이 켜짐이다.** 이번 릴리스에서 만든 최종 archive를
직접 검사하며, 세 플랫폼 중 하나라도 실패하면 `build`가 실패해 게시가 차단된다. 검증한 파일을 그대로 게시한다.
옵션을 끄면 기존 worker·wheel·native-webview 검사는 유지하고, 전체 archive 검사 생략을 실행 요약과 릴리스 노트에 명시한다.
별도 Desktop acceptance는 버전 변경·게시 없는 사전 점검용이며, 릴리스 전에 반드시 별도로 실행할 필요는 없다.
`smoke_gui.py`의 검사 페이지·bridge 검증과 `smoke_desktop.py`의 배포 UI 전체 흐름은 서로 다른 검사다.

## 2. 통과 결과를 해석하는 기준

| 통과한 검사                    | 확인한 범위                                 | 아직 확인하지 못한 범위                                           |
| ------------------------------ | ------------------------------------------- | ----------------------------------------------------------------- |
| Ruff·Biome·TypeScript·Prettier | 코드 규칙·타입·포맷                         | 실행, 네이티브 라이브러리 로딩, GUI                               |
| 단위·회귀 테스트               | 실행한 입력과 경계 조건의 동작              | 건너뛴 OS 전용 동작, 배포 파일                                    |
| 의존성 해결·wheel 설치         | 해당 Python·OS·CPU에 설치 가능              | 앱 실행, GUI, frozen 실행 파일                                    |
| frozen CLI smoke               | 실제 worker·시뮬레이션·파일 작업            | webview·실제 화면·3D                                              |
| native GUI smoke               | 실제 webview의 browser API·bridge·설계 저장 | 배포 편집기의 전체 사용자 동작                                    |
| 최종 archive acceptance        | 추출된 앱의 UI·3D·정상 종료·저장 후 재실행  | 모든 사용자 GPU, 깨끗한 OS의 설치 경험, 외부 서비스의 항상 가용성 |

결과를 기록할 때 다음 원칙을 적용한다.

- `총 N / 통과 P / 실패 F / 건너뜀 S`를 구분한다. Windows 전용 검사를 Linux에서 건너뛴 결과는 Windows 실행 증거가 아니다.
- 대상 OS·CPU·Python·커밋 SHA·workflow URL을 함께 적는다. archive 검사는 파일명과 SHA-256도 연결한다.
- mock으로 Darwin/Windows 분기를 검사한 결과, Rosetta 실행, 실제 대상 OS 실행을 각각 명시한다.
- GUI 성공은 올바른 보고서, 정상 프로세스 종료, 저장 결과 재확인을 함께 만족해야 한다. 강제 종료는 실패다.
- 실제 3D 검사는 살아 있는 WebGL 컨텍스트와 렌더링 완료가 필요하다. 2D 대체 화면은 3D 통과로 세지 않는다.
- CI의 llvmpipe·SwiftShader 등 소프트웨어 렌더러 결과에는 실제 renderer를 적는다. 이를 모든 하드웨어 GPU의 검증으로 확대하지 않는다.
- 수치 회귀 통과와 실제 로켓의 물리 정확도는 별도다. 검증된 모델·조건·허용 오차를 [AERODYNAMICS.md](AERODYNAMICS.md) 등의 근거와 함께 기록한다.

## 3. 변경 종류별로 추가할 검사

아래는 변경에 따라 선택할 검증 기준이다. 모든 항목이 이미 자동화되었다는 뜻은 아니다.
먼저 변경한 입력이 DTO → 설계 계산 → worker → 저장 → bridge → 화면으로 이동하는 경로를 추적한다.
문제가 발생하는 가장 작은 경계에 회귀 검사를 추가하고, 실제로 바뀐 배포 경로까지 검증을 넓힌다.

| 변경 영역                         | 추가·확장할 검증                                                                                                 | 기존 확장 위치                                                                                                                                                                                                                   |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 설정·설계·결과 DTO                | 허용·거부 입력, JSON 왕복, 단위와 범위, 이전 저장 입력과의 호환성, 생성 TS와 bridge 계약                         | [schemas](../backend/app/schemas/), [test_engine.py](../backend/tests/test_engine.py), [test_design.py](../backend/tests/test_design.py), [bridge.test.mjs](../frontend/src/lib/bridge.test.mjs)                                 |
| 질량·관성·공력·시뮬레이션         | 독립적으로 계산 가능한 기준 사례, 경계값, 유한한 결과, 단위·좌표·ASL/AGL, 근거 있는 허용 오차                    | [test_physics.py](../backend/tests/test_physics.py), [test_aerodynamics.py](../backend/tests/test_aerodynamics.py), [test_compressible_drag.py](../backend/tests/test_compressible_drag.py)                                      |
| 폼·편집·미리보기·결과 UI          | 입력 → React 상태 반영 → 검증 → bridge → 화면 갱신, 잘못된 입력, 오래된 비동기 응답, 키보드·레이블·오류 표시     | [edit.test.mjs](../frontend/src/lib/edit.test.mjs), [forms.test.mjs](../frontend/src/lib/forms.test.mjs), [desktop_check.js](../backend/scripts/desktop_check.js)                                                                |
| Three.js·Cesium·canvas            | 독립 WebGL probe, 컨텍스트 생성·손실·해제, 실제 3D 프레임, 뷰 전환 후 복구, 정상 종료                            | [webgl.test.mjs](../frontend/src/lib/webgl.test.mjs), [probe_webgl.js](../backend/scripts/probe_webgl.js), [desktop_check.js](../backend/scripts/desktop_check.js)                                                               |
| worker·작업 큐·취소·종료          | 실제 `spawn`, 중복·대기 한도, 취소·시간 초과·비정상 종료, 자식 회수, 재시작 후 상태                              | [test_jobs.py](../backend/tests/test_jobs.py), [smoke_bundle.py](../backend/scripts/smoke_bundle.py), [test_gui_portability.py](../backend/tests/test_gui_portability.py)                                                        |
| 저장소·가져오기·내보내기          | 기존 설계·실행 기록 보존, 실패 시 부분 저장 방지, 덮어쓰기 거부, 손상·큰 입력·경로 이탈·파일 잠금                | [test_files.py](../backend/tests/test_files.py), [test_design_files.py](../backend/tests/test_design_files.py), [test_importers.py](../backend/tests/test_importers.py)                                                          |
| 날씨·지형·위치·HTTPS              | 작은 로컬 fixture, 단위·시간대·좌표 변환, 타임아웃·잘못된 응답, TLS 검증 유지, 새 입력을 사용한 실제 worker 실행 | [test_weather.py](../backend/tests/test_weather.py), [test_terrain_sources.py](../backend/tests/test_terrain_sources.py), [test_locations.py](../backend/tests/test_locations.py), [test_http.py](../backend/tests/test_http.py) |
| native 의존성·Python·webview 버전 | 지원 OS·CPU·최소 OS의 wheel 존재, fresh 설치, 같은 프로세스의 실제 I/O, GUI, frozen startup·worker·archive       | [test_python_distribution.py](../backend/tests/test_python_distribution.py), [test_macos_bundle.py](../backend/tests/test_macos_bundle.py), [smoke_python.py](../backend/scripts/smoke_python.py)                                |
| launcher·리소스·패키징            | 소스 디렉터리 밖 실행, 한글·공백 경로, bundled asset·인증서·시간대, symlink·실행 권한, native child 종료         | [test_frozen_startup.py](../backend/tests/test_frozen_startup.py), [test_desktop_runtime.py](../backend/tests/test_desktop_runtime.py), [test_desktop_acceptance.py](../backend/tests/test_desktop_acceptance.py)                |
| 지원 플랫폼·릴리스 workflow       | 두 OS matrix와 공통 target 목록 일치, 필수 파일 누락·빈 파일·불필요한 파일 거부, 버전 불일치·중복 태그·실패 보존 | [release_desktop.py](../backend/scripts/release_desktop.py), [test_release_desktop.py](../backend/tests/test_release_desktop.py)                                                                                                 |
| 설명·레이블·스타일만 변경         | 링크·명령·화면 배치·접근성 등 실제 영향만 확인, 기존 관련 검사 실행                                              | 해당 문서 또는 UI와 [DEVELOPMENT.md](DEVELOPMENT.md)                                                                                                                                                                             |

단순 문구 변경을 위해 구현을 그대로 따라 쓰는 테스트를 만들지는 않는다.
동작·계산·데이터 경계가 바뀌면 변경 전 실패를 재현하고 변경 후 통과하는 최소 검사를 남긴다.
새 기능마다 전체 GUI 시나리오를 복제하지 말고, 기존 기본 흐름을 유지하면서 해당 동작의 관찰·조작을 확장한다.

### 예: 새 설계 입력 필드를 추가할 때

1. Pydantic DTO에 형식·단위·범위를 정의한다. 기존 저장 파일에 필드가 없을 때의 기본값이나 명시적 변환 정책도 정한다.
2. 정상·경계·잘못된 입력과 기존 설계 로딩을 검사한다. DTO에는 RocketPy 런타임 객체를 넣지 않는다.
3. [export_frontend_types.py](../backend/scripts/export_frontend_types.py)로 TS 타입을 재생성하고 frontend formatter를 실행한다. 이 생성기는 현재 `--check` 옵션이 없으며 파일을 쓴다.
4. 폼 수정이 실제 React 상태와 Python 입력에 반영되는지 검사한다. 저장 → 닫기 → 다시 열기 후 값을 확인한다.
5. 시뮬레이션에 쓰이는 필드라면 결과 또는 입력 스냅샷에서 그 반영을 확인한다. 새 필드가 기존 기본 acceptance를 깨뜨리지 않는지도 확인한다.

## 4. 개발 중 실행 순서

### 작은 수정과 회귀 검사

관련 테스트부터 실행해 원인을 좁힌다. 예를 들어 저장 형식 변경이라면 `test_design_files.py`,
작업 종료 문제라면 `test_jobs.py`와 해당 OS의 native 검사를 선택한다.
범위를 좁혀 통과한 뒤 관련 코드 변경의 기본 검사를 실행한다.

저장소 루트에서:

```bash
corepack pnpm --dir frontend install --frozen-lockfile
corepack pnpm check
corepack pnpm --dir frontend test
corepack pnpm --dir frontend format:check
corepack pnpm build
```

`backend/`에서:

```bash
uv sync --locked
uv run --locked ruff check app scripts tests
uv run --locked ruff format --check app scripts tests
uv run --locked python -m unittest discover -s tests -v
```

문서만 변경했다면 앱 전체 빌드보다 변경 문서의 포맷·링크·실제 명령과 경로를 확인한다.
포맷 자동 수정은 변경 범위에 한정한다. 검사가 이미 통과했고 새 변경이나 우려가 없다면 같은 검사를 반복하지 않는다.

### native 검증까지 넓혀야 할 때

GUI·bridge·worker lifecycle·파일 경로·의존성·Python·빌드 도구·배포 리소스를 바꾸거나,
릴리스 후보를 정했다면 지원 세 OS의 전체 archive 검사를 실행한다. 배포 없이 검사할 때는 Desktop acceptance,
배포할 때는 Release UARC의 `desktop_acceptance` 옵션을 사용한다.
특정 기능의 OS 전용 검사는 그 OS에서 실행해야 완료로 판단한다.
GPU·installer 변경은 아래의 별도 검증 한계도 확인한다.

의존성 변경은 manifests와 lockfiles를 함께 갱신한다.
로컬 `uv.lock` 설치와 PyPI 소비자의 fresh 설치를 모두 확인한다. pip/pipx/uvx는 패키지 metadata로
의존성을 해결하므로 lockfile 통과만으로 배포 설치를 확인할 수 없다.
네이티브 라이브러리는 새 Python minor·CPU·최소 OS에서 사용할 wheel을 확인한다.
현재 `smoke_python.py --fresh`는 rasterio/netCDF4에만 binary 설치를 요구한다.
새 native 의존성에도 필요하면 이 검사를 확장하되, 모든 pure-Python sdist까지 일괄 금지하지 않는다.
fresh 통과는 실행 시점의 의존성 해결 결과다. 이후 upstream 변경으로 재현되는 호환성 문제가 있으면
실패 조합을 기록하고 필요한 호환 범위·상한·고정 버전을 package metadata에 반영한다.

## 5. 기존 검증 도구를 확장하는 위치

아래 도구를 우선 재사용한다. 실행 경로·출력 디렉터리·Linux GUI 설정의 상세 명령은
[PACKAGING.md](PACKAGING.md)에 유지한다. 빌드·진단 출력은 새 디렉터리를 사용한다.

| 도구                                                                 | 책임과 확장할 내용                                                                                                            |
| -------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| [build_python.py](../backend/scripts/build_python.py)                | frontend·예제·문서·라이선스를 포함한 wheel·sdist 생성                                                                         |
| [smoke_python.py](../backend/scripts/smoke_python.py)                | 설치된 패키지의 import·asset 출처, 실제 flight/history, offline sdist 재빌드; `--fresh --gui`는 새 환경의 native I/O·GUI 검사 |
| [build_desktop.py](../backend/scripts/build_desktop.py)              | 대상 OS의 PyInstaller 빌드와 native/bundled resource 수집                                                                     |
| [smoke_bundle.py](../backend/scripts/smoke_bundle.py)                | 실제 frozen worker·시뮬레이션·압축 NetCDF·설계·내보내기·지원되는 취소 동작                                                    |
| [smoke_gui.py](../backend/scripts/smoke_gui.py)                      | 작은 검사 페이지를 통한 native webview·browser API·bridge·저장 및 process cleanup                                             |
| [release_desktop.py](../backend/scripts/release_desktop.py)          | 공통 `TARGETS`, 버전 검증·준비, archive 생성, 전체 배포 파일 집합·체크섬 검증                                                 |
| [smoke_desktop.py](../backend/scripts/smoke_desktop.py)              | 최종 archive를 한글·공백 경로에 추출하고 CLI → graphics → first → reopen 검증                                                 |
| [desktop_check.js](../backend/scripts/desktop_check.js)              | 실제 배포 화면의 편집·저장·불러오기·버튼 실행·3D·결과·재실행 시나리오                                                         |
| [desktop_check.test.mjs](../frontend/scripts/desktop_check.test.mjs) | UI driver의 대기·이벤트·오류·실행 순서 회귀 검사                                                                              |

단위 테스트는 좁고 결정적인 입력으로, archive acceptance는 짧은 대표 사용자 흐름으로 유지한다.
새 기능의 모든 입력 조합을 무거운 native GUI 검사로 옮기지 않는다.
UI 기능을 검사할 때 저장·실행 bridge를 직접 호출해 실제 버튼·이벤트·상태 반영을 우회하지 않는다.
진단 훅과 fixture는 격리한 임시 데이터에만 사용한다. native 파일 대화상자의 실제 조작은 별도 대상 OS 검증으로 남긴다.
외부 서버 응답·실시간 날씨·지도 타일에 기본 acceptance의 성패를 맡기지 않는다.
외부 서비스 연결 확인은 해당 서비스 변경 시 별도 수동 검사로 기록하고, 실패 원인을 로컬 계산·GUI 실패와 구분한다.

## 6. 앞으로 CI에 추가할 항목

아래는 **아직 구현하지 않은 개선 작업**이다. 한 번에 모두 추가하기보다 각 단계가 실제로 실패를 잡는지 확인하며 확장한다.

| 우선순위 | 추가할 작업                                   | 완료 기준                                                                                                       |
| -------- | --------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| 1        | `pull_request`와 기본 브랜치 `push`용 빠른 CI | locked 설치, Ruff lint·format, Biome·TypeScript, 양쪽 테스트, frontend format·build가 자동 실행되고 실패가 보임 |
| 1        | 두 기존 workflow의 frontend format 검사       | `format:check`를 source 검사에 포함하고 workflow 및 외부 JS 검사 파일도 별도로 포맷 확인                        |
| 2        | 생성 DTO 일치 검사                            | 스키마에서 TS 생성 → formatter → diff 확인; 생성 파일 수동 수정이나 누락을 CI가 거부                            |
| 2        | 설치·빌드·기본 smoke의 실패 진단 보강         | 최종 archive의 진단 artifact는 구현됨; 그 이전 단계의 native loader·설치 실패 자료도 필요에 따라 보강           |
| 2        | 깨끗한 OS의 설치·첫 실행                      | 필요한 runtime이 없는 환경에서 안내·동의·취소·설치 실패와 복구·재실행을 확인하고 OS·archive·SHA-256 기록        |
| 필요 시  | 성능·대용량 회귀                              | 실제 요구가 생긴 기능에 고정 workload·시간/메모리 예산·허용 변동 폭을 정해 측정                                 |

빠른 CI를 required check로 쓰려면 workflow 추가와 별도로 저장소의 병합 규칙도 설정한다.
문서 전용 변경에 무거운 native 빌드를 무조건 요구하지 않고, 공통 런타임·의존성·패키징 변경에는
영향받는 native 경로가 빠지지 않도록 trigger/filter를 검토한다.

릴리스의 최종 archive acceptance와 해당 진단 artifact 보존은 구현되어 1절에 반영했다.
릴리스 workflow는 **배포할 버전으로 한 번 빌드한 파일을 검증하고 그대로 게시하는 구조**를 유지한다.
검증 뒤 다시 빌드하면 다른 파일이 생길 수 있다. job 사이에는 같은 artifact를 전달하고 그 출처를 확인한다.
관련 원리는 [GitHub의 workflow artifact 문서](https://docs.github.com/en/actions/tutorials/store-and-share-data)를 참고한다.

PR용 검증에는 게시 권한·비밀값을 넘기지 않는다. 기존의 Action commit SHA 고정과 최소 권한 원칙을 유지하고,
쓰기 권한은 게시 job으로 한정한다. 외부 PR의 코드를 실행하는 새 경로를 추가할 때는
[GitHub Actions secure use](https://docs.github.com/en/actions/reference/security/secure-use)를 확인한다.

## 7. 릴리스할 때의 절차

### 지금 적용할 운영 절차

1. 관련 회귀·기본 검사를 통과시키고 [RELEASE_NOTES.md](RELEASE_NOTES.md)에 변경 내용·호환성·지원 범위·검증 한계를 반영한 뒤 커밋·푸시한다.
2. 배포 없이 사전 점검하려면 **Desktop acceptance → 새 Run workflow**를 선택한다. 이 단계는 선택 사항이며 버전·태그를 만들지 않는다.
3. 릴리스할 때는 **Release UARC → Run workflow**에서 입력 SHA를 확인하고 `bump` 또는 명시적 버전,
   pre-release 여부를 정한다. **`desktop_acceptance`는 기본값인 켜짐으로 둔다.**
   `publish_pypi`는 Trusted Publisher 준비와 배포 의도가 있을 때 선택한다.
4. `prepare` → 세 native `build` → `publish` 결과를 확인한다. 각 native job은 릴리스 버전으로 빌드·압축한
   바로 그 archive를 검사한다. 세 OS 중 하나라도 실패하면 게시가 차단된다.
5. CLI·graphics·first·reopen 보고서, 정상 종료와 저장 결과를 확인한다. 누락·실패·미실행을 통과로 처리하지 않는다.
   옵션을 껐다면 full archive 검사는 생략이며, 실행 요약과 릴리스 노트에도 생략으로 표시되어야 한다.
6. 검사 후 버전 커밋·태그가 생성된다. 실제 release 입력 SHA와 만들어진 release commit SHA를 함께 기록한다.
7. 게시된 세 native archive·wheel·sdist와 `SHA256SUMS.txt`가 맞는지 확인한다. PyPI를 선택했다면 그 job의 결과도 별도로 확인한다.
8. 게시된 파일을 내려받은 깨끗한 대상 환경에서 설치·실행·저장·정상 종료·재실행 결과를 확인하고 기록한다.
   runner에 이미 설치된 WebView2·Qt 시스템 라이브러리 등이 사용자 환경에도 있다고 가정하지 않는다.

실패를 수정하거나 사전 점검 이후 소스가 바뀌면 새 커밋으로 시작한다. 예전 실행의 재시도는 원래 SHA를 사용한다.
이 동작은 [GitHub 재실행 문서](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs)에 명시되어 있다.
앞선 별도 acceptance의 통과 여부와 관계없이 릴리스는 선택된 옵션에 따라 이번 배포 파일을 직접 검증한다.

### 게시 실패와 재시도

- 빌드 실패, 버전 커밋/태그 생성 이후 실패, GitHub 게시 이후 PyPI 실패를 구분한다.
- 게시 단계에서 브랜치가 이동해 중단되면 원격 변경을 먼저 반영하고 새 소스를 검증한다. 검사를 우회하려고 브랜치·태그를 덮어쓰지 않는다.
- 이미 생성된 태그·draft·공개 자산·PyPI 버전을 확인한 후 재시도 방법을 정한다. 같은 버전의 파일을 바꿔 배포하지 않는다.
- 잘못 게시된 버전은 문제와 영향을 기록하고 수정 버전을 준비한다. 이전 정상 버전 안내와 사용자 데이터 호환성도 함께 확인한다.

## 8. 이전 시행착오를 재발 방지 규칙으로 바꾸기

| 관찰한 문제                                                             | 다음 변경에서 적용할 규칙                                                                         |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| PyPI 접속 timeout과 native wheel 부재가 서로 다른 문제였음              | 네트워크 요청 실패와 의존성 해결·source build 실패를 구분하고 Python·OS·CPU·최소 OS를 먼저 기록   |
| 소스 테스트는 통과했지만 Windows에서 rasterio/GDAL 빌드 실패            | 지원 Python 범위를 명시하고 소비자 방식의 fresh wheel 설치를 세 OS에서 실행                       |
| Linux xcb plugin은 존재하지만 native library 누락으로 GUI 종료          | 일반적인 cursor 경고만 보고 패키지를 추측하지 말고 plugin·WebEngine의 실제 loader 결과 확인       |
| Mac GUI timeout에 여러 원인이 섞였음                                    | 프로세스 생성·asset server·navigation·bridge·native loop·worker 종료 경계별 로그와 제한 시간 확보 |
| Windows socket HANDLE과 파일 descriptor 차이, launcher 자식의 파일 잠금 | OS 전용 저수준 동작은 실제 OS에서 검사하고 자식 프로세스 회수·임시 파일 해제까지 확인             |
| 한글·공백 경로와 Windows stdout 인코딩에서 실패                         | 설치·추출·frontend 경로와 진단 로그를 해당 조건으로 검증; 환경의 기본 인코딩에 기대지 않음        |
| DOM 값 설정 후 React 상태 반영 전에 클릭해 실패                         | 실제 이벤트와 상태 commit을 기다리고 의미 있는 조건으로 동기화; 고정 sleep 증가는 최후 수단       |
| 성공 JSON은 생겼지만 native 프로세스가 종료되지 않았음                  | 보고서·exit code·정상 close·worker cleanup을 모두 통과 조건으로 유지                              |
| 라이브러리 실행 전에 Intel runner의 독립 WebGL부터 실패                 | 먼저 환경 probe로 실패 계층을 분리; 검증할 장비가 없는 플랫폼은 지원 정책으로 명시적으로 결정     |
| 이전 SHA 재실행이나 로컬 mock 통과를 새 native 검증으로 오해            | 실행 URL·SHA·OS·CPU·artifact·skip 사유를 결과에 묶어 기록                                         |

원인과 관련된 fixture·최소 재현·phase 로그를 먼저 추가한다.
필수 검사를 `continue-on-error`로 바꾸거나, 실패를 광범위하게 무시하거나, timeout만 늘려서 통과시키지 않는다.
지원 플랫폼 제외는 CI·릴리스·공통 `TARGETS`·게시 파일 검증·문서·회귀 테스트를 함께 바꾸는 별도 결정이다.
과거 Intel/Rosetta 결과는 [VALIDATION.md](VALIDATION.md)에 남기고 현재 지원 증거와 구분한다.

## 9. 기능 변경마다 복사할 검증 기록

PR 설명이나 [VALIDATION.md](VALIDATION.md)에 아래 항목을 필요한 범위로 채운다.
숫자와 실행 결과는 실제 출력으로 기록한다. 해당하지 않는 항목에는 이유를 적는다.

```text
변경: 사용자에게 달라지는 동작 / 재현 조건
영향 경로: 입력 → DTO → 계산/worker → 저장 → bridge → 화면 중 변경한 경계
대상 환경: 지원 OS·CPU / Python / 의존성·lock 변경 여부

회귀 검사: 기존 실패 재현 / 정상·잘못된 입력·경계 조건
기본 검사: 실행 명령 / 통과·실패·skip 수 / skip 사유와 대상 OS의 별도 결과
배포 검사: workflow URL / 입력 SHA / OS·CPU / archive 이름·SHA-256
GUI 결과: graphics / first / reopen / 정상 종료 / 저장 값·run ID 일치

호환성: 이전 설계·실행 기록 / 기본값·변환 정책 / 실패 시 기존 데이터 보존
설치·외부 환경: 필요한 native runtime / 실 GPU·clean OS·외부 API의 확인 범위
문서·릴리스: 지원 범위·release notes·라이선스 변경 / 버전·게시 계획
미검증·실패: 남은 항목 / 영향 / 필요한 다음 검증
```

## 10. 가이드를 갱신하는 시점

workflow나 helper의 책임을 바꾸면 1절과 5절을 먼저 갱신한다.
6절의 개선을 구현하면 현재 구성 표에 반영하고 미구현 목록에서 제거하거나 완료 기록으로 옮긴다.
새 기능은 3절의 기존 분류에 연결하고, 실제로 새로운 검증 경계가 생긴 경우에만 분류를 늘린다.
새 플랫폼은 wheel·native GUI·3D·배포 파일 검증 환경이 확보된 뒤 공식 지원에 추가한다.
과거 실행 결과는 삭제하거나 새 코드의 결과처럼 고치지 않고 실행 당시 SHA와 함께 유지한다.
