# claude 스킬: 헤드리스 작업자 예약 (`schedule`, GitHub Actions)

> **구현 세션 첫 동작:** 하네스가 만든 심링크 `.claude/plans/claude-skills-claude-inherited-platypus.md`(이 파일을 가리킴)를 지운다. 이 파일(`261117_claude-skill-schedule.md`)만 보고 구현한다.

> 이어서 `ToolSearch("select:TaskCreate,TaskUpdate,TaskList")`로 트래커를 열고 아래 "단계"를 태스크로 만든다(description = 그 단계의 완료 판정). `coding`·`skill-maker`는 `Skill`로 연다. 리뷰는 아래 "리뷰 프로토콜"대로 한다.

> **이 계획의 승인이 겸하는 허락(성진, 2026-11-17):** 구현 세션은 실제 검증을 위해 private 임시 저장소(`tjdwls101010/claude-schedule-probe`)를 만들고, 임시 self-hosted 러너를 설치해 LaunchAgent 서비스로 돌리고(plist에서 `SessionCreate` 제거), 임시 디스패처 LaunchAgent를 설치할 수 있다. 검증이 끝나면 서비스 제거 → 러너 등록 해제 → 저장소 삭제 → `~/Library/LaunchAgents`·`~/Library/Logs`의 임시 항목 삭제까지 마친다. 성진의 기존 러너 셋(`~/actions-runner-{k-politics,news,invest}`)과 기존 dispatch plist는 건드리지 않는다.

## 승인 전에 볼 것: 성진이 고르지 않았지만 쓰면서 체감할 판단

아래는 질문으로 합의한 것이 아니라 클로드가 근거를 들어 정한 것이다. 승인은 이것들도 받아들이는 것이므로, 바꾸고 싶으면 승인 전에 말한다.

- **프롬프트는 git 이력에 남는다**(K2): 예약 정의가 기본 브랜치의 워크플로 파일이라 `unschedule` 뒤에도 이력에 있다.
- **`schedule`을 다시 부르면 꺼 둔 예약이 켜지고, `unschedule`은 워크플로 파일을 지운다**(K16). 잠시 멈추는 것은 GitHub 웹의 워크플로 비활성화로 한다(전용 명령 없음).
- **public 저장소는 거부한다**(K14, `--public-ok`로만) — 이 레포(`claude-in-claude`)에서는 예약을 걸 수 없다.
- **`schedule`은 stdin을 `--prompt-file -`일 때만 읽는다**(K24) — `start`와 다르다.
- **기존 `stop`의 동작을 고친다**(K25, PR ⓪): 시작 중인 런에 온 정지가 작업자를 못 막는 결함을 코덱스가 찾았다. 예약과 별개의 수정이다.
- **시간대는 맥의 시스템 시간대 하나**(K6), **cron은 숫자 형태만**, **macOS 전용**(K15).
- **스킬 경로가 바뀌면(플러그인 업데이트) 예약이 빨갛게 실패하고 다시 `schedule`해야 고쳐진다**(K3).
- **러너 서비스의 로그인 설정은 스킬이 바꾸지 않는다**(`schedule`·`doctor` 응답이 문제와 두 길을 설명 — K29) — 성진의 기존 러너 셋은 지금 설정으로는 클로드를 못 돌린다(probe 9).

## Context

성진은 `claude` 스킬(헤드리스 Claude Code 작업자를 관리되는 서브에이전트로, v0.1.0)을 잘 쓰고 있다. 지금 스킬은 "오케스트레이터가 지금 작업자를 띄워 관리한다"까지만 한다. 이 계획은 **사람도 오케스트레이터도 없는 시각에 작업자가 돌게 하는 예약 기능**을 더한다(v0.2.0).

구도는 성진이 다른 저장소들에서 이미 운영 중인 것과 같다: **GitHub Actions는 예약의 정의·기록·조작판(실행 기록, summary, 재실행, 취소, 수동 실행, 실패 메일)만 맡고, 클로드는 성진의 맥에서 그 저장소의 self-hosted 러너를 통해 돈다.** 작업자는 평소처럼 사용자 환경 전부·구독 로그인·macOS 샌드박스·프로젝트의 `.claude-runs/`를 쓰므로, 예약된 런도 로컬 레지스트리에 남아 `status`·`log`·`result`·`resume`으로 이어받을 수 있다. GitHub cron은 시각을 보장하지 않으므로(실측 46분간 0회) 정시 발화는 로컬 LaunchAgent가 맡고 cron은 백업이다.

품질의 중심은 두 가지다: ① 사람이 없어도 매번 같은 순서로 끝까지 가는 실행기(시작 → 끝까지 대기 → 살아 있으면 정지 → summary → 초록/빨강), ② GitHub 런 페이지에서 한눈에 읽히는 summary. 성공 기준은 퀄리티 하나다. 기존 코드는 재작성하지 않는다: 실측에서 기존 스킬이 러너 잡 안에서 그대로 동작했고, 필요한 구조 변경은 활동 해석과 결과 조회를 재사용 가능하게 여는 두 군데뿐이다.

스킬은 다른 사람도 쓰는 공개 플러그인이므로, 성진의 취향이 아니라 확인된 사실(러너·GitHub·launchd의 동작)과 성진이 정한 형식(summary 구성, 무인 규칙)을 싣는다.

## 합의 장부

| 구분 | 내용 | 출처 |
|---|---|---|
| 결정 | 계획 파일명은 `261117_claude-skill-schedule.md`(이전 계획 `261031_claude-skill.md`의 관례), 하네스 경로는 이 파일을 가리키는 심링크 | 성진(파일명을 먼저 바꾸라는 요청), 이전 계획 3행 |
| 결정 | 이 계획의 검증은 `claude` 스킬 작업자로 한다(코덱스 한도 소진). 다른 모델 계열의 시각이 없다는 점을 계획 리뷰 기록과 PR 본문에 적는다 | 성진(2026-11-17) |
| 사실 | 로컬: claude 2.1.326, gh 2.103.3(계정 tjdwls101010, 스코프 `repo`·`workflow`·`delete_repo`·`gist`·`read:org`), uv 0.8.0, origin `https://github.com/tjdwls101010/claude-in-claude.git`(public), `.github/` 없음 | 실측 |
| 사실 | `claude setup-token`: "Set up a long-lived authentication token (requires Claude subscription)" | `claude setup-token --help` |
| 사실 | 기존 스킬: 명령 10개(`start` `resume` `send` `batch` `status` `log` `result` `stop` `clean` `doctor`) + 숨긴 `__supervise`, 종료 코드 0/1/2/3, 레지스트리는 본 체크아웃의 `.claude-runs/`(gitignore), `result`는 런 상태와 무관하게 exit 0, `--wait`는 attention이 생기면 일찍 돌아옴, read-only·write 프로필은 샌드박스 `failIfUnavailable: true` | `scripts/cli.py`, `261031_claude-skill.md` |
| 사실 | 이전 계획에서 Linux 샌드박스(bwrap)는 검증되지 않았고 범위 밖이었다 | `261031_claude-skill.md` "검증되지 않는 것"·"범위 밖" |
| 결정 | **GitHub Actions는 cron과 기록(로그·summary·재실행·취소)만 맡고, 클로드는 GitHub 서버가 아니라 성진의 로컬 머신에서 돈다.** 헤드리스 클로드가 로컬 파일시스템에서 일해야 하기 때문 | 성진(2026-11-17) |
| 결정 | 실행 방식 = **self-hosted runner**. Desktop local scheduled task(이미 있는 로컬 예약)와 GitHub-hosted 러너는 택하지 않는다. Desktop 대비 얻는 것: 웹·폰에서 조회·재실행·취소·수동 실행, 실패 메일, 스킬의 프로필·스키마 결과·압축 로그로 만든 summary, 권한 프롬프트에서 멈추지 않음 | 성진(클로드 추천, 2026-11-17) |
| 결정 | 예약(워크플로 파일)과 러너는 **예약할 프로젝트의 저장소마다** 둔다(전용 private 저장소 하나에 모으는 안은 택하지 않음 — 클로드 추천은 전용 저장소였다). 따르는 것: 프로젝트마다 러너 설치, public 저장소는 안전하게 쓸 수 없음(이 레포 포함), 예약을 바꿀 때마다 그 프로젝트 기본 브랜치에 커밋 | 성진(2026-11-17) |
| 결정 | 계획 세션에서 실측한다: private 임시 저장소(`claude-schedule-probe`)를 만들고 러너를 scratchpad 아래에 설치해 서비스 없이 전경으로 띄워 haiku 작업자로 확인, 끝나면 러너 등록 해제·저장소 삭제. LaunchAgent(서비스) 설치가 필요한 실측은 따로 묻는다 | 성진(클로드 추천, 2026-11-17) |
| 결정 | 예약할 일의 종류 = **읽기 전용 점검·보고**(코드 리뷰, 커밋 점검, 테스트 돌려 상태 보고)와 **파일을 바꾸는 유지보수**(문서 갱신, 정리, 생성물 재생성 — 변경을 로컬에 남김). 바깥 정보 수집(auto·네트워크)과 작업자가 커밋·푸시·PR까지 하는 일은 고르지 않았다 → 설계의 중심은 read-only·write 프로필, git은 여전히 사람 몫 | 성진(2026-11-17) |
| 결정 | **일회성 예약도 지원한다**(클로드 추천은 반복만). GitHub cron에 일회성 문법이 없으므로 날짜를 박은 cron + 실행 뒤 워크플로 스스로 비활성화. GitHub가 시각을 보장하지 않는다는 점은 help가 말한다 | 성진(2026-11-17) |
| 결정 | **활성화 = `schedule`이 GitHub API로 기본 브랜치에 워크플로 파일을 바로 커밋**(클로드 추천은 로컬 파일 + 평소 git 흐름). 로컬 작업 트리·현재 브랜치를 건드리지 않고 즉시 활성화. 따르는 것: PR 없이 기본 브랜치에 커밋이 생김, 브랜치 보호가 있으면 실패, 로컬 main은 다음 pull 때 받음, "git은 호출자 몫" 원칙의 명시적 예외(예약 정의 파일에 한함) | 성진(2026-11-17) |
| 결정 | 러너를 LaunchAgent(서비스)로 임시 설치해 실측한다(`svc.sh install` → 확인 → `svc.sh uninstall`) | 성진(클로드 추천, 2026-11-17) |
| 결정 | **시각 트리거 = 로컬 디스패처 + GitHub cron 백업.** `schedule`이 워크플로를 커밋하면서 맥에 LaunchAgent를 설치하고, 그것이 정시에 `gh workflow run`으로 잡을 시작한다. 워크플로의 `on.schedule` cron은 백업이며 늦게 온 중복은 "이미 실행됨"으로 건너뛴다(성진의 invest 저장소 운영과 같은 구도). 따르는 것: 예약마다 `~/Library/LaunchAgents`에 plist, 예약 삭제 명령 필요, Actions 목록에 건너뛴 백업 실행이 보임 | 성진(클로드 추천, 2026-11-17) |
| 결정 | **쓰기 트리 = 기본은 프로젝트 체크아웃 제자리, `schedule --worktree`를 주면 런마다 로컬 HEAD에서 만든 별도 worktree**(변경이 없던 런의 worktree는 끝날 때 스스로 지움). 커밋·푸시는 어느 쪽이든 사람 몫 | 성진(클로드 추천, 2026-11-17) |
| 결정 | **summary에 작업자에게 준 프롬프트도 싣는다** | 성진(2026-11-17, summary 질문의 메모) |
| 판단 | 위 결정을 만족하는 GitHub의 표준 수단은 **self-hosted runner**(성진 맥에 설치한 러너가 잡을 받아 로컬에서 실행)다. 이 경우 작업자는 지금처럼 사용자 환경 전부·구독 로그인·macOS 샌드박스·로컬 `.claude-runs/`를 그대로 쓴다 → GitHub-hosted 러너였다면 생겼을 문제(환경 없음, `CLAUDE_CODE_OAUTH_TOKEN` 시크릿, Linux bwrap, 레지스트리 소실)가 사라진다 | 클로드 |
| 사실 | self-hosted 러너: macOS 11+, x64·ARM64. macOS 서비스는 `./svc.sh install`(sudo 없음)로 `~/Library/LaunchAgents/actions.runner.<org>-<repo>.<runnerName>.plist`에 설치되는 **LaunchAgent**(사용자 로그인 세션). 러너 로그는 러너 디렉터리 `_diag/`. 러너 앱은 스스로 업데이트하며 버전이 너무 낮아지면 잡을 못 받는다 | docs.github.com configure-the-application, monitor-and-troubleshoot |
| 사실 | 저장소 단위 러너는 저장소 하나 전용이고, 여러 저장소가 함께 쓰는 러너는 조직 단위부터다 → 개인 계정에서는 저장소마다 러너를 따로 등록 | docs.github.com concepts/runners/self-hosted-runners |
| 사실 | 맞는 러너가 온라인·유휴가 아니면 잡은 큐에서 기다리고 **24시간** 넘으면 실패. self-hosted 잡 실행 한도 **5일**, 워크플로 런 35일 | docs.github.com reference/runners/self-hosted-runners, reference/limits |
| 사실 | `on.schedule`: POSIX cron 5필드, 기본 UTC이고 **`timezone:`에 IANA 문자열을 줄 수 있다**(`cron: '30 5 * * 1-5'` + `timezone: "America/New_York"`), 최소 간격 5분, **기본 브랜치의 최신 커밋에서만** 돈다. 일회성 예약 문법은 없다. 알림은 워크플로를 만든(또는 cron을 마지막으로 고친·다시 켠) 사용자에게 간다 | docs.github.com events-that-trigger-workflows#schedule, notifications-for-workflow-runs |
| 사실 | 취소: 러너가 스텝의 진입 프로세스에 SIGINT → 7500ms 안에 안 끝나면 SIGTERM → 2500ms 뒤 프로세스 트리 kill. `if: always()`·`cancelled()` 조건이 참인 스텝은 취소 뒤에도 돈다. 5분 뒤에는 서버가 강제 종료 → 스킬의 정지 사다리(SIGINT → 10초 → SIGTERM → 3초 → SIGKILL)는 취소 창(10초)에 들어가지 않는다 | docs.github.com workflow-cancellation, `cli.py` STOP_DESC |
| 사실 | job summary: 스텝마다 `$GITHUB_STEP_SUMMARY` 파일, GitHub Flavored Markdown, **스텝당 1MiB**(넘으면 업로드 실패 + 오류 주석, 잡 상태에는 영향 없음), 잡당 20개 표시, 시크릿 자동 마스킹, 스텝이 끝나면 업로드되어 뒤 스텝이 못 고친다 | docs.github.com workflow-commands#adding-a-job-summary |
| 사실 | 과금: self-hosted 러너 사용은 무료(포함 사용량을 깎지 않음) | docs.github.com billing/concepts/product-billing/github-actions |
| 사실 | 보안: "self-hosted runners should almost never be used for public repositories"(누구나 PR로 러너 머신에서 코드를 돌릴 수 있음). private도 포크·PR 권한자가 같은 위험. public 저장소의 Actions 로그·summary는 공개 | docs.github.com reference/security/secure-use |
| 사실 | 재실행은 원래 이벤트의 `GITHUB_SHA`·`GITHUB_REF`와 원래 actor 권한을 쓴다 | docs.github.com re-run-workflows-and-jobs |
| 사실 | Claude Code 자체의 예약 수단 셋: **cloud scheduled tasks**(구 routines; Anthropic 클라우드, 새 클론, 로컬 파일 없음, 최소 1시간, 일회성 가능), **Desktop local scheduled tasks**(내 머신·로컬 파일, Desktop 앱이 열려 있고 깨어 있을 때만, 놓친 실행은 7일 내 1회 따라잡기, 실행 기록·Run now·일시정지, worktree 옵션, 권한 프롬프트에서 멈출 수 있음, 태스크는 `~/.claude/scheduled-tasks/<name>/SKILL.md`), **`/loop`**(세션 범위). 문서는 "CI에서 예약 실행"으로 Claude Code GitHub Actions를 가리킨다 | code.claude.com desktop-scheduled-tasks.md, routines.md |
| 사실 | 인증: macOS 로그인 자격은 Keychain에 저장되고 Keychain이 쓰기를 거부하면(SSH 세션 등) `~/.claude/.credentials.json`으로 대체. `claude setup-token`은 CI·스크립트용 1년짜리 OAuth 토큰(`CLAUDE_CODE_OAUTH_TOKEN`)을 낸다. 약관: 본인 구독으로 수정하지 않은 Claude Code에 로그인해 쓰는 것은 허용, 구독 한도는 "ordinary, individual usage" 전제 | code.claude.com authentication.md, legal-and-compliance.md |
| 사실 | (probe 1, 러너 2.338.2 osx-arm64를 전경 `run.sh`로) 잡 스텝은 `/bin/bash -e <임시 스크립트>`(bash 3.2)로 돌고 cwd는 러너의 `_work/<repo>/<repo>`(checkout 안 하면 빈 디렉터리). PATH는 `config.sh` 때 캡처된 러너 디렉터리의 `.path` 파일(서비스는 `runsvc.sh`가 그 파일로 PATH를 설정), 그 밖의 env는 `.env` 파일(LANG 등 몇 개만 자동 캡처). 잡 env에 `CI=true`, `GITHUB_*`, `RUNNER_*`, `RUNNER_TRACKING_ID`, `GITHUB_STEP_SUMMARY`(러너 `_work/_temp` 아래 파일). 이 env에서 `claude auth status`는 `loggedIn: true`·`subscriptionType: max`(전경 실행이라 내 로그인 세션의 Keychain) | 실측(scratchpad `probe-out/env-*.txt`) |
| 사실 | (probe 2) 취소: 러너는 SIGINT를 **스텝의 진입 bash에만** 보낸다. bash는 전경 자식을 기다리느라 반응하지 않고 자식(파이썬)에게는 신호가 가지 않았다(핸들러 로그 없음) → 7.5초 뒤 SIGTERM, 2.5초 뒤 "kill entire process tree", 스텝은 exit 143·`cancelled`. 그 뒤 `if: always()` 스텝이 취소 약 12초 뒤 시작해 20초 sleep까지 끝냈고 잡 결론은 `cancelled` | 실측(`probe-out/cancel-*.log`, 러너 `_diag/Worker_*.log`) |
| 사실 | (probe 2) 잡이 끝날 때 러너는 잡 시작 뒤 생긴 프로세스의 env를 `ps e -p <pid> -o command`로 읽어 그 잡의 `RUNNER_TRACKING_ID`를 가진 것을 정리한다. 새 세션(setsid)으로 분리한 프로세스도 대상이다(세션 분리로는 못 피함). 긴 `-c` 인자를 가진 자식 셋은 살아남았다(이유는 확인하지 않음 — 정리가 완전하지 않다는 것만 사실) | 실측(같은 로그) |
| 사실 | (probe 3) 러너 잡에서 실제 스킬이 그대로 돈다: `uv run "<skill>/scripts/cli.py" start --project "<공백 있는 경로>" --profile read-only --model haiku …` → 1초 안에 `running`, `result --wait` 5초 뒤 `completed`, 런은 프로젝트의 `.claude-runs/`에 남고 잡 밖에서 `status`로 보인다. `result`의 헤더 JSON + 최종 메시지 + `log` 텍스트를 `$GITHUB_STEP_SUMMARY`에 썼을 때 약 2KB | 실측(`probe-out/flow-*.log`, `result-*.txt`) |
| 사실 | (probe 4) 실행 중 취소 → 본 스텝은 `cancelled`, `if: always()` 마무리 스텝이 `status`로 `running`을 보고 `stop --run`(SIGINT 한 번) → `interrupted`(세션은 resume 가능), summary 기록까지 성공. 취소부터 마무리 스텝 시작까지 15초 | 실측 |
| 사실 | (probe 5) **작업자가 살아 있는 채 잡이 끝나면 러너가 감독을 죽인다**: 기다리지 않고 스텝을 끝낸 잡이 `success`로 끝난 직후 런은 `orphaned`("the supervisor died before recording an outcome") → 잡이 런의 수명을 끝까지 쥐어야 하고(본 스텝이 끝까지 기다림), 잡이 끝나기 전에 마무리 스텝이 살아 있는 런을 `stop`으로 정리해야 한다 | 실측 |
| 사실 | (probe 6) `schedule`에 `timezone: "Asia/Seoul"`을 쓴 워크플로는 유효하게 받아들여졌다. `*/5 * * * *` 예약은 push 뒤 9분이 지나도록 첫 실행이 뜨지 않았다(계속 관찰 중) | 실측 |
| 사실 | 표현식 `cancelled()` 같은 상태 함수는 `if:`에서만 쓸 수 있다(`run:` 안에 쓰면 워크플로 파일이 거부됨) | 실측(push 직후 "workflow file issue") |
| 사실 | (probe 7) 잡 `timeout-minutes`에 걸리면 취소와 같은 경로다: 실행 중 스텝 `cancelled`, `if: always()` 스텝은 실행됨(`job.status=cancelled`), 잡 결론 `cancelled`. 1분 제한에서 시작 72초 뒤 마무리 스텝 시작 | 실측(`probe-out/timeout-*.log`) |
| 사실 | (probe 8) job summary 렌더링: 표, GFM 알림(`> [!WARNING]` → `markdown-alert`), `<details>`, 코드블록, mermaid가 모두 렌더링된다 | 실측(로그인 브라우저로 받은 런 페이지 HTML) |
| 사실 | (대조 1, sonnet·safe-mode·`cli.py --help`만 제공) 스킬 없는 클로드가 쓴 예약 워크플로: checkout 없이 `--project`, attention을 넘겨 끝까지 도는 대기 루프, `state`로 잡 실패 처리(`result`가 exit 0임을 help에서 읽음), `if: always()` stop 스텝, `concurrency`, `permissions: {}`를 스스로 넣었다. 틀리거나 빠진 것: ① `timezone:`을 몰라 UTC로 환산(`0 18 * * *`) ② `uv run` 대신 `python3 "$CLI"`(러너 PATH의 python이 3.11 미만이면 실패) ③ summary를 대기 스텝에서만 써서 취소·시간 초과 때 summary가 없음 ④ summary가 상태 한 줄 + 최종 메시지뿐(거부·변경 파일·로그·이어받는 법 없음) ⑤ "분리된 작업자는 잡 취소로 안 멈춘다"고 믿음(실제로는 잡 종료 때 러너가 죽여 `orphaned`) ⑥ GitHub가 보여 주는 커밋과 작업자가 본 로컬 트리가 다르다는 점은 "체크아웃이 낡았을 수 있다"로만 언급 | 실측(scratchpad `contrast1/`) |
| 사실 | (대조 2, 같은 조건) 스킬 없는 클로드가 쓴 러너 설치 스크립트: 최신 릴리스 내려받기·SHA-256 검증·`gh api`로 등록 토큰·라벨·sudo 없는 `svc.sh install`(LaunchAgent인 이유로 Keychain을 듦)·제거 절차까지 맞게 썼다. 틀리거나 확인 안 된 것: ① PATH를 `.env`에 씀(러너는 `.path` 파일을 씀 — `.env`의 PATH가 먹는지 미확인) ② "잠든 맥이 놓친 예약은 큐에 쌓이지 않는다"(문서: 잡은 러너를 24시간 기다림) ③ LaunchAgent에서 Keychain이 읽힌다고 단정(plist에 `SessionCreate: true`가 있어 미확인) | 실측(scratchpad `contrast2/`) |
| 판단 | **명령이 되는 것과 안 되는 것(Model over machinery, 대조 근거).** ① 러너에서 도는 **예약 실행기**(시작 → 끝까지 대기 → 살아 있으면 정지 → summary → 잡 성공/실패)는 코드로 둔다: 사람 없이 매번 같은 순서로 돌아야 하고, 대조 1에서 summary 누락·빈약이 실제로 나왔으며, 워크플로마다 bash로 굳히면 고칠 수 없다. ② **워크플로 파일 쓰기(`schedule`)**도 명령으로 둔다: 두 스텝·시간 제한 중첩·경로·`uv run`이 서로 맞아야 하고, 틀리면 새벽에 아무도 모르게 실패한다. ③ **러너 설치는 명령으로 만들지 않는다**: 대조 2에서 기본 모델이 거의 맞게 했고, 모자란 것은 사실 몇 개(PATH 캡처, Keychain, 24시간 큐, public 금지)라 reference 문서가 맡는다. ④ 예약 목록·일시정지·삭제·런 조회·재실행·취소는 `gh`와 파일 삭제로 모델이 직접 한다 | 클로드 |
| 사실 | (probe 9, **서비스**) `./svc.sh install`이 만든 기본 LaunchAgent(plist에 `SessionCreate: true`)에서 `claude auth status`는 `loggedIn: false`·`authMethod: none`이고, 작업자는 `failed`(`error: claude exited 1`, 마지막 메시지 `Not logged in · Please run /login`)로 끝난다 — 새 보안 세션에서는 Keychain의 구독 로그인이 읽히지 않는다 | 실측(`probe-out/env-43997138053-1.txt`, run `20261117-103902-sched-probe-c284`) |
| 사실 | (probe 10, 서비스) 설치된 plist에서 `SessionCreate` 키를 지우고(`PlistBuddy -c "Delete :SessionCreate"`) 서비스를 다시 띄우면 `loggedIn: true`·`subscriptionType: max`이고, read-only 작업자가 샌드박스 안에서 정상 실행된다(`python3` 실행 성공, cwd `touch`는 `Operation not permitted`, 5초·$0.004). 다른 해법은 `claude setup-token`의 1년 토큰을 러너 `.env`의 `CLAUDE_CODE_OAUTH_TOKEN`으로 두는 것(문서상 CI용 경로, 이번에 실측하지 않음) | 실측(`probe-out/env-43997328394-1.txt`, run `20261117-104104-sched-probe-ae7f`), authentication.md |
| 사실 | (probe 6 계속) `*/5 * * * *` + `timezone` 예약은 push 뒤 **23분이 지나도록 한 번도 실행되지 않았다**(같은 동안 수동 실행은 즉시 됨) | 실측 |
| 사실 | **성진의 기존 운영(선례).** 이 맥에 저장소별 self-hosted 러너 셋이 이미 서비스로 돈다: `~/actions-runner-k-politics`(Skills-for-K-Politics), `~/actions-runner-news`(K-News-DB), `~/actions-runner-invest`(Skills-for-Invest) — 모두 private, plist는 기본값(`SessionCreate: true`), PATH는 `.path`, 비밀·경로는 러너 `.env`. 그 워크플로들의 관례: `runs-on: self-hosted` 또는 `[self-hosted, macOS, rs-mac]`, `concurrency`(cancel-in-progress false), 이유를 주석으로 단 `timeout-minutes`, `permissions: contents: read`, 로컬 절대 경로를 YAML `env:`에(`NEWS_DB: /Users/seongjin/Coding/...`), `if: always()` Summary 스텝이 `$GITHUB_STEP_SUMMARY`에 표를 씀, "GitHub은 크론·로그·알림만 맡고 실행은 맥이 한다" | `~/actions-runner-*`, `gh api …/contents/.github/workflows`(scratchpad `prior/`) |
| 사실 | **성진은 GitHub cron의 지연을 이미 겪었고 로컬 디스패처로 풀었다**: `~/Library/LaunchAgents/com.seongjin.invest-*-dispatch.plist`가 `StartCalendarInterval`에 `/opt/homebrew/bin/gh workflow run <file> --repo <o/r> --ref main`을 부르고, 워크플로의 cron은 백업으로 남긴다("GitHub starts scheduled runs hours late … the cron below is the backup", 중복은 잡 로직이 6시간 창으로 건너뜀, "A time missed in sleep fires on wake"). 이 LaunchAgent(SessionCreate 없음)에서는 `gh`의 keyring 로그인이 읽힌다. 맥은 `pmset repeat wakeorpoweron`으로 깨운다 | `~/Library/LaunchAgents/com.seongjin.invest-serenity-dispatch.plist`, `prior/Skills-for-Invest--serenity-daily.yml`, `prior/K-News-DB--scheduled-collect.yml` |
| 사실 | (probe 11) GitHub Contents API로 기본 브랜치에 워크플로를 바로 커밋할 수 있다: `gh api -X PUT repos/<o>/<r>/contents/.github/workflows/<file> -f message=… -f content=<base64> -f branch=main` → 몇 초 안에 `gh workflow list`에 `active`. 이미 있는 파일을 `sha` 없이 PUT하면 HTTP 422 `"sha" wasn't supplied`, 없는 저장소는 HTTP 404. 토큰에 `workflow` 스코프 필요(성진 토큰에 있음) | 실측(scratchpad `fixtures/contents-put-create.json`, `contents-put-nosha-refusal.*`, `repo-404.stderr`) |
| 사실 | (probe 11) 최종 형태 워크플로를 GitHub가 받아들였다: `run-name: <name> · ${{ inputs.source \|\| github.event_name }}`(목록에 "probe-final · dispatcher"로 보임), `schedule`의 `timezone`, `workflow_dispatch` 입력 `source`, `concurrency`의 `queue: max`, 스텝 `env`의 블록 스칼라 프롬프트. 프롬프트 안의 `${{`는 `${{ '${{' }}`로 써야 글자 그대로 도착한다(들여쓰기·따옴표·`$HOME`·백틱·한글·빈 줄 보존 확인) | 실측(scratchpad `final/claude-probe-final.yml`, `probe-out/final-*.log`) |
| 사실 | `concurrency` 기본값(`queue: single`)에서는 새로 대기에 들어온 런이 **먼저 대기 중이던 런을 취소하고 자리를 차지한다**. `queue: max`면 100개까지 순서대로 기다린다(`cancel-in-progress: true`와는 함께 못 씀) → 늦게 온 백업이 대기 중인 수동 실행을 지우지 않게 하려면 `queue: max` | docs.github.com workflow-syntax#concurrency |
| 사실 | (probe 12, 디스패처) `~/Library/LaunchAgents`의 plist(`StartCalendarInterval`, `ProgramArguments`: `/opt/homebrew/bin/gh workflow run <file> --repo <o/r> --ref main -f source=dispatcher`)를 `launchctl bootstrap gui/<uid> <plist>`로 올리면 정한 분에 발화한다: 10:54:00 예약 → 10:54:07 런 생성 → 10:54:14 잡 스텝 시작. launchd는 자는 동안 놓친 발화를 깨어날 때 **하나로 합쳐** 실행하고, `Day`와 `Weekday`를 둘 다 주면 **어느 한쪽만 맞아도** 발화한다(cron과 같은 OR) | 실측(`probe-out/dispatcher.log`), `man launchd.plist` |
| 사실 | (probe 13) 잡 안에서: ① 러너가 기본 plist(`SessionCreate: true`)면 `gh`의 keyring 로그인도 읽히지 않는다("The token in default is invalid"), `SessionCreate`를 뺀 서비스에서는 읽힌다 ② 그래도 워크플로에 `permissions: actions: write`를 주고 스텝 env에 `GH_TOKEN: ${{ github.token }}`을 주면 `gh workflow disable <file>`이 **두 설정 모두에서** 성공한다(`disabled_manually`) ③ `launchctl bootout gui/<uid>/<label>`과 plist 삭제도 두 설정 모두에서 성공 → 잡 안의 GitHub 호출은 keyring이 아니라 잡 토큰으로 한다 | 실측(`probe-out/final-43999024579-1.log`, `final-43999178836-1.log`) |
| 판단 | **러너 서비스의 인증은 사람이 고르는 두 길**(`schedule`·`doctor`의 `runner.problems`가 상태를 판정하고 둘 다 설명 — K29): ① plist에서 `SessionCreate`를 빼 구독 로그인을 그대로 씀(디스크에 비밀 없음, `svc.sh install`을 다시 하면 되돌아감) ② `claude setup-token` 토큰을 러너 `.env`에(기본 plist 그대로, 평문 토큰·1년 만료). 스킬은 어느 쪽도 강제하지 않는다 | 클로드 |
| 사실 | (probe 6 끝) `*/5 * * * *` + `timezone` 예약은 저장소를 지울 때까지 **46분 동안 한 번도 실행되지 않았다** | 실측 |
| 사실 | (probe 14) 실제 write 작업자 런(haiku, 도구 7회, 거부 1건)의 이벤트: `assistant`·`user`(tool_result) 이벤트에는 `timestamp`(ISO, UTC)가 있고 `system`·`result`·`rate_limit_event`에는 없다. `result`에 `duration_ms`. meta에 `created_at`·`started_at`·`ended_at`(epoch) → 활동 표의 경과 시간은 이벤트 `timestamp` − `started_at`으로 낸다 | 실측(run `20261117-110035-nightly-docs-f079`) |
| 사실 | (probe 15) Contents API 형태: GET → `{name, path, sha, encoding: "base64", content, …}`; PUT(생성·`sha`로 갱신) → `{content: {sha, path, html_url, …}, commit: {sha, message, …}}`; DELETE(`sha` 필요) → `{content: null, commit}`; 지운 뒤 GET은 HTTP 404. `actions/workflows/<file>` → `{id, name, path, state}`(`active`·`disabled_manually`). `actions/runners` → `{total_count, runners: [{id, name, os, status, busy, labels: [{name}]}]}`. `repos/<o>/<r>` → `{full_name, private, visibility, default_branch, permissions: {admin, push, …}}` | 실측(scratchpad `fixtures/` — 구현 0단계에서 다시 캡처) |
| 결정 | **summary 구성 = 샘플 B.** 맨 위 제목(상태 아이콘 · 예약 이름 · 상태)과 표(Run·Trigger·Local tree), 주의 알림, 접힌 **Prompt**, 작업자의 답 본문(별도 제목 없이 그대로), 구분선, 열린 **Changes**(쓰기 런), 접힌 **Activity**(호출마다 한 행인 **표**: `#`·`Time`·`Step`·`Detail`·`Result`), 접힌 **Continue on your Mac**. 실행 중에는 스텝 로그에 활동이 한 줄씩 흐른다. 레이블은 영어, 답은 작업자가 쓴 언어 그대로. 성진이 실제 렌더링(probe 런 43999951274의 A·B)을 보고 B를 골랐다 | 성진(2026-11-17) |
| 결정 | **무인 규칙.** 프로필은 `schedule`에서 필수(기본값 없음). 런 시간 제한 기본 60분(`--timeout`), 잡 제한은 그보다 10분 길게. attention(멈춘 듯함·재시도·한도 거부)은 런을 멈추지 않고 summary 경고로만 — 시간 제한이 경계. 빨강 = `failed`·`timed_out`·`orphaned`·`--schema`인데 구조화 결과 없음. 웹 취소 = 작업자를 `stop`으로 멈추고 세션은 resume 가능하게. 초록 + 경고 = 완료했지만 권한 거부가 있었음, 프로필이 요청과 다르게 시작됨. 초록(건너뜀) = 늦게 온 중복. 작업자에게는 "예약 실행이고 보는 사람이 없으며 최종 메시지가 GitHub summary로 게시된다"를 알린다 | 성진(클로드 추천, 2026-11-17) |
| 결정 | **실패한 회차의 재시도 = read-only만 한 번 더.** 그 slot의 런이 완료되지 못했고 프로필이 read-only면 늦게 온 자동 트리거(백업)가 slot당 한 번 더 돌린다. write·auto 예약, 사람이 취소한 회차는 자동으로 다시 하지 않는다. 웹의 Re-run은 언제나 다시 돈다. 일시적 실패는 사람 없이 복구되고, 로그인 같은 지속 실패는 빨간 런이 둘 생긴다(K4에 반영) | 성진(클로드 추천, 2026-11-17) |
| 결정 | **`references/runner.md`를 따로 두지 않는다.** 러너에 관한 지식은 인터페이스와 SKILL.md로 나눠 싣는다(K29) | 성진(2026-11-17) |
| 판단 | **K29 러너 지식의 자리.** 모델이 몰라서 틀리는 러너 사실은 대부분 **도구가 그 맥에서 직접 판정할 수 있다**: 이 저장소의 러너가 있는가·온라인인가(API), 서비스 plist의 `SessionCreate`, 러너 `.env`의 토큰 유무, 러너 `.path`에 `uv`·`claude`·`gh`가 있는가(`github/runner.py`). 그래서 이것들은 `schedule`·`doctor` 응답의 `runner.problems[]`가 각각 `{problem, why, fixes}`로 말한다 — 예: `session_create` → why "a service in its own security session cannot read the Claude login in the Keychain; scheduled runs fail with Not logged in", fixes ① 설치된 plist에서 `SessionCreate`를 지우고 서비스 재시작(디스크에 비밀 없음; `svc.sh install`을 다시 하면 되돌아가고, 그 러너의 모든 잡이 로그인 세션 권한으로 돈다) ② `claude setup-token`의 토큰을 러너 `.env`의 `CLAUDE_CODE_OAUTH_TOKEN`으로(평문·1년 만료). `path_missing` → 러너는 `config.sh` 때의 PATH를 `.path`에 굳혀 쓰므로 `.path`를 고치고 서비스 재시작(`.env`의 PATH가 이기는지는 0단계 (b) 결과대로 적는다). `none` → 이 저장소에 러너를 서비스로 설치(`./svc.sh install`은 sudo 없이 LaunchAgent; 개인 계정의 러너는 저장소 하나 전용). 도구가 판정할 수 없는 것만 남는다: 대기 한도 24시간과 러너 하나가 잡을 하나씩 돈다는 것은 `schedule --help`의 epilog(시각·`--timeout`을 정하는 그 호출에서 읽힌다), 맥이 깨어 있어야 한다는 것과 check 실행만이 증명이라는 것은 SKILL.md(호출 전에 계획을 바꾼다). 설치 순서·제거 방법은 싣지 않는다(대조 2에서 기본 모델이 맞게 함) | 클로드 |
| 결정 | 실측에 쓴 임시 자원은 계획 세션에서 모두 지웠다(서비스 제거, 러너 등록 해제, 저장소·로그 삭제 확인). 구현 세션이 같은 방식으로 다시 만든다(맨 위 허락) | 성진(클로드 추천, 2026-11-17) |
| 판단 | **K1 두 스텝.** 워크플로의 잡은 `Run`(작업자를 시작하고 끝까지 기다림)과 `if: always()`인 `Finish`(살아 있으면 `stop`, worktree 정리, 일회성이면 스스로 끄기, summary) 두 스텝이다. 취소·시간 초과는 `Run`만 죽이고 `Finish`는 돈다(probe 4·7). summary는 `Finish`에서만 쓴다 — 어떤 끝이든 summary가 남는다(대조 1의 빈틈) | 클로드(probe 2·4·5·7) |
| 판단 | **K2 예약 정의의 진실은 워크플로 파일 하나.** `.github/workflows/claude-<name>.yml`이 프롬프트·시각·프로필 등 전부를 담고, 맨 위 주석 한 줄 `# spec: {json}`이 같은 내용을 기계가 읽는 형태로 싣는다(stdlib에 YAML 파서가 없으므로 되읽기는 이 줄로). 같은 `--name`으로 `schedule`을 다시 부르면 **플래그 > 기록된 spec > 기본값**으로 합쳐 다시 쓴다(`resume`의 설정 상속과 같은 규칙) — 시각만, 프롬프트만 바꾸거나 플래그 없이 불러 경로를 새로 고칠 수 있다. 로컬 레지스트리는 실행 상태만 갖는다 | 클로드 |
| 판단 | **K3 경로는 워크플로에 박는다**(성진의 기존 워크플로와 같은 관례): 프로젝트 체크아웃 절대 경로와 스킬 `cli.py` 절대 경로. 잡은 checkout하지 않는다. 스킬 경로가 바뀌면(플러그인 업데이트) 스텝이 "파일 없음"으로 빨갛게 실패하고, `schedule --list`가 `stale_entry`로 알리며(`doctor`는 예약 목록을 읽지 않는다 — feature 간 간선을 늘리지 않게), 플래그 없는 `schedule --name X`가 고친다. 다시 볼 조건: 플러그인 설치 사용자가 업데이트마다 깨진다고 보고하면 실행 시점 해석(런처)을 설계 | 클로드 |
| 판단 | **K4 slot 규칙(중복 건너뛰기).** slot = 예약이 가리키는 발화 시각. 자동 트리거(이벤트 `schedule`, 또는 입력 `source=dispatcher`)로 온 잡은 `현재 slot = 지금 이전의 가장 최근 발화 시각`을 계산해, 이 예약의 `last_slot`이 그 값 이상이면 작업자를 띄우지 않고 "이미 실행됨"으로 끝낸다(초록, 앞선 런 링크). 아니면 `last_slot`을 그 값으로 올리고 실행한다(예약 상태 파일의 잠금 아래). 수동 실행(입력 없는 `workflow_dispatch`)과 그 재실행은 건너뛰지 않고 `last_slot`도 건드리지 않는다. 걸어 보기: ① 03:00 디스패처 실행 → 05:47 백업 도착: 현재 slot 03:00 = last → 건너뜀 ② 매시 예약에서 백업이 70분 늦음: 현재 slot은 다음 시각이고 디스패처가 이미 그 slot을 실행 → 건너뜀 ③ 맥이 세 slot 동안 잠: 깨어날 때 디스패처 1회(launchd가 합침)가 최신 slot으로 실행, 큐에 쌓인 백업들은 건너뜀 → 놓친 여러 번에 대해 따라잡기 1회 ④ 디스패처의 `gh` 호출이 실패: 백업이 와서 실행. 일회성: slot = `--at` 시각, 지금이 그 전이면 slot 없음(수동 실행만 가능). **재실행(`GITHUB_RUN_ATTEMPT` > 1)은 사람이 누른 것이므로 수동과 같이 항상 실행하고 `last_slot`도 건드리지 않는다**(재실행은 원래 이벤트·입력을 그대로 쓰므로 attempt로만 구분된다; 실패한 03:00 런을 아침에 Re-run하면 돈다; 새 세션으로 시작하고, 끊긴 세션을 잇는 것은 summary의 resume 호출이 한다). 일회성의 자동 트리거는 상태와 무관하게 `지금 − at`가 26시간(큐 한도 24시간 + 여유)을 넘으면 건너뛴다 — 상태 파일을 잃어도 연도 없는 cron이 이듬해 다시 돌리지 못한다. slot은 **작업자를 띄우기 직전에** 차지한다(순서는 K28). **실패한 slot의 재시도(성진 결정):** 자동 트리거가 와서 보니 그 slot을 차지한 런이 완료되지 못했고(`failed`·`timed_out`·`orphaned`, 또는 런을 만들기도 전에 거부됨) 프로필이 `read-only`이며 그 slot의 재시도가 아직 없었으면, 건너뛰지 않고 한 번 더 돌린다(slot당 최대 1회; summary의 Trigger에 "retry of <앞선 런 링크>"). 재시도 여부는 상태 파일의 `retried`와 재시도 런의 meta `origin.retry_of`(앞선 잡 키) 양쪽에 남겨, 상태 파일을 잃어도 런들에서 "이 slot은 이미 재시도했다"를 다시 세운다(작업자를 만들지 못한 거부는 런이 없어 복구되지 않는다 — 그 경우 한 번 더 시도될 수 있다). "완료되지 못함"에는 slot을 차지한 뒤 작업자를 만들지 못한 거부도 든다(K28 ④): 프로필이 read-only면 재시도, 아니면 사람의 Re-run. `write`·`auto` 예약은 반쯤 한 일 위에서 다시 일하지 않도록 자동으로는 다시 하지 않고, 사람이 취소한 slot(`interrupted`)과 아직 살아 있는 런도 다시 하지 않는다 — 그 경우들은 사람의 Re-run. 상태 파일이 없으면 레지스트리의 이 예약 런들(meta `origin.slot`)에서 `last_slot`을 다시 세운다 | 클로드(어드바이저) |
| 판단 | **K19 `Run` → `Finish` 인계.** 잡의 키는 `<GITHUB_RUN_ID>-<GITHUB_RUN_ATTEMPT>`(런 id는 재실행에도 같으므로 attempt까지). ① `Run`은 **작업자를 띄우는 모든 잡에서**(자동·수동·재실행 모두) 띄우기 전에 예약 상태 파일 `jobs[<job>]`에 `{trigger, slot(자동만), mode, group(worktree면), tree_before(브랜치·SHA·`git status` 항목과 지문), outcome: null}`을 적는다. 자동 트리거면 K4의 slot 판정·차지와 같은 잠금 안에서 한 번에, 수동·재실행이면 slot은 건드리지 않고 잡 기록만. ② 작업자를 만들 때 meta `origin`에 `{kind: "schedule", name, trigger, slot, job, url}`을 넣는다 — `start(…, origin)` → `create_run(extra_meta=…)`, `batch(…, origin)` → `start_members` → `start_member` → `create_run`으로 넘기며, 런이 게시되는 순간 meta에 있다(`start`는 init을 15초까지 기다린 뒤에야 돌아오므로 반환값에 기대지 않는다). ③ `Finish`는 레지스트리에서 `origin.job`이 자기 잡인 런을 찾는다 — `Run`이 init 대기 중에 죽어도 런을 놓치지 않는다. ④ 작업자를 띄우지 않은 끝(건너뜀, check, 시작 전 거부)은 `jobs[<job>].outcome`에 적는다(최근 50개만 보관). ⑤ 인계가 하나도 없으면 `Finish`는 "`Run` 스텝이 작업자를 시작하지 못했다, 스텝 로그를 보라"는 summary를 쓴다. `Finish`는 `Run`과 **같은 플래그와 env**를 받으므로 인계가 없어도 일회성·worktree·mode를 안다 | 클로드(claude 리뷰 F1·F2) |
| 판단 | **K20 `Finish`의 단계는 서로 독립이다.** 정지 → 끝 스냅숏(Changes, K27) → worktree 정리 → 일회성 끄기 → 로컬 `summary.md` → `$GITHUB_STEP_SUMMARY` 각각을 따로 시도하고, 실패는 모아 summary의 알림에 싣는다(로컬 쓰기가 실패해도 GitHub 쓰기는 시도). exit 1은 두 경우뿐: **작업자가 멈췄음을 확인하지 못함**(정지 뒤에도 살아 있음, 또는 `meta.json`을 읽지 못해 살아 있는지 알 수 없음), `$GITHUB_STEP_SUMMARY`를 쓰지 못함 — 둘 다 `::error::`. 그 밖에는 exit 0("끝과 종료 코드" 표와 같다) | 클로드(claude 리뷰 F7, codex 2라운드 R9) |
| 판단 | **K21 스텝 로그로 새는 워크플로 명령을 막는다.** 러너는 스텝 stdout의 `::명령::`을 해석하므로, 작업자의 글·명령을 흘리기 전에 `::stop-commands::<무작위 토큰>`을 내고 실행기 자신의 `::warning::`을 낼 때만 `::<토큰>::`으로 풀었다가 다시 막는다(작업자 글이 `::error::`·`::add-mask::`가 되지 않게). 0단계에서 실제 러너로 확인한다 | 클로드(claude 리뷰 F16) |
| 판단 | **K22 스키마는 글로 싣는다.** `schedule --schema FILE`은 파일을 읽어 그 JSON 글을 spec과 워크플로의 `CLAUDE_SCHEDULE_SCHEMA` 블록에 넣는다(호출자의 임시 경로를 박지 않는다). 실행기는 그 글을 예약 상태 디렉터리의 파일로 써서 `start`·`batch`에 경로로 넘긴다(runs는 바꾸지 않는다) | 클로드(claude 리뷰 F15) |
| 판단 | **K23 프로젝트 경로를 먼저 본다.** `__scheduled`의 `run`·`finish`·check는 레지스트리에 무엇이든 쓰기 전에 `--project`가 존재하는 디렉터리인지 확인한다(레지스트리 코드는 없는 경로를 만들어 버린다). 아니면 `Run`은 `::error::`와 exit 1(잡이 빨강), `Finish`는 "프로젝트가 옮겨졌으면 `schedule --name X --project <새 경로>`"를 `$GITHUB_STEP_SUMMARY`에만 쓰고(로컬 기록 없음) exit 0. `--worktree`인데 저장소에 커밋이 없어 worktree를 줄 수 없으면 작업자를 띄우지 않고 빨강(`batch`는 그 경우 조용히 제자리에서 돌린다) | 클로드(claude 리뷰 F4·F6) |
| 판단 | **K24 `schedule`의 프롬프트 읽기.** stdin은 `--prompt-file -`일 때만 읽는다(`start`와 다르다): 기존 예약을 플래그만으로 다시 부를 때, 비어 있는 non-TTY stdin이 "빈 프롬프트" 거부가 되거나 흘러든 글이 기록된 프롬프트를 바꾸지 않게. 새 예약에서만 프롬프트가 필수 | 클로드(claude 리뷰 F13) |
| 판단 | **K25 시작 중인 런의 정지(기존 버그, 먼저 고친다).** 지금 `stop`은 meta에 `claude_pid`가 있어야 신호를 보내는데, 감독은 런 게시 → 감독 생성 → `claude` 실행 → pid 기록 순서라, 그 사이에 온 정지는 `stop_requested`만 남기고 작업자는 뒤늦게 뜬다(`runs/commands.py` `stop_one`, `runs/supervisor.py`의 `Popen` 뒤 `update_meta`). 감독이 ① `claude`를 띄우기 직전에 `stop_requested`를 보고 띄우지 않으며 ② pid를 기록한 직후 다시 보고 있으면 스스로 정지 사다리를 돌리도록 고친다. 예약과 무관한 기존 결함이라 **별도 PR ⓪**(재현 테스트 먼저). 예약 쪽에서는 그래도 남는 경우를 러너의 잡 종료 정리(`RUNNER_TRACKING_ID`, K9)가 받는다 | 클로드(codex 리뷰 F1) |
| 판단 | **K26 slot의 불변식.** slot은 트리거가 의도한 시각이 아니라 **잡이 실제로 작업자를 띄우려는 시각**으로 계산한다(launchd는 발화 시각을 넘겨주지 않고, 늦은 cron은 자기 원래 시각을 모른다). 그래서 보장하는 것은 "자동 실행은 slot마다 최대 한 번(read-only가 실패했을 때만 재시도 한 번을 더해 두 번), 어느 트리거가 했는지는 따지지 않는다"이다 — 03:00 백업이 큐에서 밀려 04:00 뒤에 돌면 04:00 slot을 채우고 진짜 04:00 디스패처가 건너뛴다(횟수는 같다). slot을 차지한 직후 런이 게시되기 전에 `Run`이 죽고 **상태 파일까지** 사라지는 이중 사고는 막지 않는다(차지 기록은 상태 파일에만 있다) | 클로드(codex 리뷰 F2·F6 — 설계는 바꾸지 않고 한계로 명시) |
| 판단 | **K28 `Run`의 순서.** ① `--project`가 있는 디렉터리인가(K23; 아니면 아무것도 쓰지 않고 빨강) ② `mode=check`면 확인만 하고 끝(slot·잡 기록 없음, 결과는 `jobs[<job>].outcome`) ③ 자동 트리거면 slot 판정(건너뜀 / 재시도 / 처음)과 차지 + 잡 기록, 수동·재실행이면 잡 기록만 ④ 시작 전 거부(`--worktree`인데 커밋 없음, 버전 하한 등)와 작업자 시작(`start` 또는 `batch`) — 여기서 거부되면 `jobs[<job>].outcome`에 적고 빨강; slot은 차지된 채이며 **K4의 재시도 규칙 하나가** 다음 자동 트리거를 정한다(read-only면 한 번 더, 아니면 건너뜀) ⑤ 끝까지 대기 ⑥ 종료 코드. slot을 차지하지 않는 실패는 ①뿐이다(레지스트리에 쓸 수 없으므로): 그때는 자동 트리거마다 빨갛고, 한 slot의 자동 트리거는 디스패처와 백업 둘뿐이다 | 클로드(어드바이저, codex 2라운드 R2) |
| 판단 | **K27 Changes는 "런 동안 바뀐 것"이다.** `Run`이 작업자 전에 남긴 `tree_before`(브랜치·SHA·`git status` 항목마다 내용 지문)와 `Finish` 시점의 같은 스냅숏을 비교해, 상태나 지문이 달라진 경로를 싣는다. 줄 수는 시작할 때 깨끗했던 추적 파일에만 붙이고(`git diff HEAD --numstat` — 작업자가 stage한 변경도 든다 — 이 곧 런의 변경), 시작 전에 이미 고쳐져 있던 파일은 "already modified before the run"으로만 표시한다. **worktree 런은 기준이 다르다:** worktree는 기준 커밋에서 깨끗하게 시작하므로 `tree_before`를 쓰지 않고 끝난 뒤 그 worktree의 `git status`와 `git diff HEAD --numstat` 전부가 런의 변경이다. `Finish`는 정리(`clean`)로 worktree가 지워지기 **전에** 이 스냅숏을 잡는다. 같은 시간에 다른 프로세스가 고친 것도 여기 들어가므로 섹션 이름은 "changed during the run"이고 summary가 그 한계를 한 줄로 말한다. 지문은 기존 `git.fingerprint`를 쓴다 | 클로드(codex 리뷰 F11) |
| 판단 | **K5 `concurrency`는 `queue: max`.** 그룹 `claude-<name>`, `cancel-in-progress: false`, `queue: max` — 기본값은 늦게 온 백업이 대기 중인 수동 실행을 취소한다 | 클로드(문서, probe 11) |
| 판단 | **K6 cron과 launchd는 한 시각의 두 표기**라, 둘에서 똑같이 발화함을 보일 수 있는 형태만 받는다: 5필드, 각 필드는 숫자·`*`·`,`·`-`·`/`(이름 `MON`·`JAN` 없음). 필드를 값 집합으로 펴서 launchd `StartCalendarInterval` 사전 목록(집합의 곱; 일·요일을 둘 다 제한하면 일 사전들 + 요일 사전들 — 둘 다 OR, `man launchd.plist`)을 만든다. 사전이 500개를 넘으면 거부하고 더 성긴 시각을 요구한다. 시간대는 **맥의 시스템 시간대 하나**(launchd가 그것을 쓴다): `schedule`이 IANA 이름을 읽어 워크플로 `timezone:`에 쓰고, 플래그는 없다. 일회성 `--at YYYY-MM-DDTHH:MM`(로컬 시각)은 cron `M H D Mo *`와 사전 하나가 되고, 연도가 없어 1년 뒤 다시 발화할 수 있으므로 실행 뒤 스스로 끈다(K8) | 클로드(어드바이저, `man launchd.plist`) |
| 판단 | **K7 잡 안의 GitHub 호출은 잡 토큰으로.** `Finish` 스텝에만 `GH_TOKEN: ${{ github.token }}`을 준다(작업자를 띄우는 `Run` 스텝에는 주지 않는다). 일회성 예약의 워크플로만 `permissions: actions: write`, 나머지는 `permissions: {}`. 러너 서비스가 기본 plist면 `gh`의 keyring이 안 읽히기 때문이다(probe 13) | 클로드 |
| 판단 | **K8 일회성 예약의 끝.** 자동 트리거로 온 잡의 `Finish`가 **그 slot이 더 시도될 일이 없을 때** 워크플로를 `disable`하고 디스패처 plist를 `bootout`·삭제한다(probe 12·13): 런이 완료됐거나, K4의 재시도가 해당되지 않거나(write·auto, 취소) 이미 재시도였거나, slot이 26시간을 넘겨 건너뛴 경우. read-only 런이 실패했고 재시도가 남아 있으면 **끄지 않고 둔다** — 늦게 올 백업이 재시도하고 그 잡이 끈다; 백업이 끝내 오지 않으면 다음 발화(이듬해)가 26시간 규칙으로 건너뛰면서 끈다. 다시 쓰려면 같은 이름으로 `schedule --at …`(워크플로를 다시 켠다). **자기가 시작한 정의일 때만 끈다:** `schedule`은 커밋할 때마다 **새로 만든 짧은 무작위 식별자**(`definition`; spec의 해시가 아니다 — 지웠다가 같은 내용으로 다시 만들어도 값이 달라야 옛 잡이 새 예약을 끄지 않는다)를 워크플로의 두 스텝 플래그와 로컬 예약 상태에 적고, `Finish`는 자기 `--definition`이 로컬 상태의 현재 값과 같을 때만 끄기·제거를 한다 — 런이 도는 동안 같은 이름을 다시 예약했거나 `unschedule`했으면 손대지 않고 summary에 그렇게 적는다. `unschedule`은 살아 있는 런 때문에 상태를 보존할 때도 `definition`은 비운다(인계 기록만 남긴다). 확인부터 끄기·제거까지와 `schedule`·`unschedule`의 커밋·설치는 **같은 예약 상태 잠금 아래**라, 비교 직후에 정의가 바뀌는 경합이 없다. 끄기와 제거는 따로 성공·실패하며, 실패한 쪽은 summary 경고에 사람이 칠 복구 명령(`gh workflow disable claude-<name>.yml --repo <o/r>`, `unschedule --name <name>`)과 함께 남는다. 다음 해 발화는 K4의 26시간 규칙이 상태 없이도 막는다 | 클로드(codex 리뷰 F3·F4) |
| 판단 | **K9 작업자에게서 잡의 손잡이를 뗀다.** 실행기는 작업자를 띄우기 전에 자기 env에서 `GITHUB_ENV`·`GITHUB_OUTPUT`·`GITHUB_PATH`·`GITHUB_STATE`·`GITHUB_STEP_SUMMARY`·`GH_TOKEN`·`GITHUB_TOKEN`을 지운다(작업자가 뒤 스텝의 환경이나 summary를 바꾸지 못하게). `RUNNER_TRACKING_ID`는 남긴다(잡이 비정상 종료해도 러너가 남은 프로세스를 정리) | 클로드 |
| 판단 | **K10 `--worktree`는 한 명짜리 그룹으로.** 쓰기 예약에 `--worktree`가 있으면 실행기는 `batch`로 그룹 `<name>-<GITHUB_RUN_ID>-<attempt>`(멤버 1, worktree; 잡마다 유일해 재실행과도 겹치지 않는다)을 만든다 — 격리·기준 커밋·`.worktreeinclude`·`clean` 판정을 그대로 재사용하고, 남은 worktree는 `status --group`·`clean --group`·`doctor`에 보인다. `batch`는 받은 `origin`을 그룹 매니페스트에도 적고, `Finish`는 **매니페스트의 `origin.job`이 자기 잡일 때만** 그 그룹을 정리한다 — 이름이 이미 있어 `batch`가 거부한 경우(남의 그룹)에는 손대지 않고 그 거부를 빨강으로 보고한다. 자기 그룹이면 `clean`(강제 아님)을 불러 잃을 것이 없는 worktree는 지우고 이름을 놓는다; 변경이 있으면 남기고 summary가 경로·브랜치·`clean` 호출을 말한다. 그룹 이름 한도(40자)와 런 id 자릿수(지금 11자리, 여유 1) 때문에 예약 이름은 24자까지. 한 명짜리 그룹에는 "다른 멤버가 병렬로 일한다"는 문장을 붙이지 않는다(`turn_preamble`). `schedule`은 `--worktree`와 `read-only`를 함께 주면 거부한다(read-only는 worktree를 받지 않는다) | 클로드(claude 리뷰 F6) |
| 판단 | **K11 예약 사실은 턴 앞머리에.** `start`·`batch`가 `origin`(예약 이름, 트리거, 시각, 저장소)을 받아 meta `origin`에 남기고, `turn_preamble`이 한 줄을 붙인다: 예약 실행이고 보는 사람이 없으며 최종 메시지가 그 저장소의 GitHub 런 summary로 게시되니, 이 대화를 못 본 독자에게 쓰라는 것 | 클로드 |
| 판단 | **K12 `schedule`은 두 시스템에 쓰므로 반쪽을 숨기지 않는다.** 순서: 비용 0 거부 → 기존 spec 읽기·합치기 → 워크플로 커밋(실패하면 아무것도 설치하지 않고 거부) → 꺼져 있으면 켜기 → 디스패처 설치. 응답의 `workflow`(`committed`·`unchanged`)와 `dispatcher`(`installed`·`failed`+이유)가 각각 말하고, 디스패처만 실패하면 "GitHub cron 백업만 남아 늦게 돈다, 같은 명령을 다시"를 적는다. `unschedule`도 같은 식(`dispatcher`: `removed`·`absent`·`failed`, `workflow`: `deleted`·`absent`·`failed`); 이 예약의 런이 살아 있으면 로컬 상태를 지우지 않고 `note`로 그 런과 `gh run cancel`을 알린다(그 잡의 `Finish`가 인계를 잃지 않게), 아니면 상태도 지운다. 같은 이름의 첫 커밋 둘이 겹치면 진 쪽은 409가 아니라 422 `"sha" wasn't supplied`를 받으므로(probe 11), 409와 그 422는 충돌로 보고 다시 읽어 합친 뒤 한 번 재시도한다; 그 밖의 422(브랜치 보호 등)는 거부 | 클로드(어드바이저, claude 리뷰 F5·F14) |
| 판단 | **K13 준비 상태는 잡으로만 증명된다.** 대화에서 부른 `doctor`는 로그인 세션 안이라 로그인됨으로 나오지만 서비스는 새벽에 실패할 수 있다(probe 9; 성진의 기존 러너 셋이 그 설정). 그래서 워크플로에 입력 `mode: check`를 두고, 그 잡은 작업자 없이 `claude auth status`·버전·샌드박스 전제·`uv`를 러너 안에서 확인해 summary와 초록/빨강으로 답한다(모델 호출 없음). `schedule`의 응답 `next`가 그 실행(`gh workflow run … -f mode=check`)을 가리킨다. `doctor`·`schedule`은 추가로 서비스 plist의 `SessionCreate`와 러너 `.env`의 토큰 유무를 읽어 미리 경고한다 | 클로드(어드바이저, probe 9·10) |
| 판단 | **K14 public 저장소는 거부, `--public-ok`로만.** 예약하면 프롬프트·답·활동 표가 공개 summary로 올라가고, 그 저장소의 러너는 누구의 PR로도 이 맥에서 코드를 돌릴 수 있다. 사람이 없을 때 벌어지고 되돌릴 수 없어서 기본은 거부하고, 이유를 help와 거부 메시지가 말한다 | 클로드(secure-use 문서) |
| 판단 | **K15 macOS 전용.** 디스패처가 launchd다. 다른 플랫폼에서 `schedule`·`unschedule`은 이유와 함께 거부한다(0.1.0도 Linux·Windows는 범위 밖) | 클로드 |
| 판단 | **K16 `unschedule`은 워크플로 파일을 지운다**(실행 기록은 Actions에 남는다). 잠시 멈추는 것은 GitHub의 워크플로 비활성화로 충분하다: cron이 멈추고 디스패처의 `gh workflow run`은 거부되어 로컬 로그에만 남는다. `schedule`을 다시 부르면 켜진 상태가 된다 | 클로드 |
| 판단 | **K17 summary는 런 디렉터리에도 남긴다**(`.claude-runs/<run>/summary.md`, 건너뜀·check처럼 런이 없으면 `.claude-runs/.schedules/<name>/`): GitHub에 올린 것과 같은 글이 로컬 기록이 되고, job summary를 돌려주는 API가 없어도 실제 검증이 읽을 수 있다 | 클로드 |
| 판단 | **K18 커밋 메시지.** 기본은 영어 한 줄(`Schedule Claude worker <name>: <when>` / `Unschedule Claude worker <name>`), `--message`로 바꾼다 — 저장소마다 커밋 관례가 사람 몫이기 때문(성진의 저장소는 `<타입>: <한국어>`) | 클로드 |
| 사실 | 코덱스 한도는 계획 세션 도중(2026-11-17) 복구됐다 → 위 "검증은 claude 작업자로" 결정의 전제가 풀려, 계획 리뷰는 claude 작업자와 코덱스 둘 다 했고 구현 세션의 리뷰 기본값은 다시 코덱스다 | 성진(2026-11-17) |
| 판단 | 이 계획은 승인 전에 `claude` 작업자(opus)와 코덱스(gpt-6.1-terra)가 각각 read-only로 리뷰했다 — 아래 "계획 리뷰 기록" | 클로드, 성진 |
| 사실 | (0단계 a, 구현 세션) 기본 plist(`SessionCreate: true`) 서비스 + 러너 `.env`의 `CLAUDE_CODE_OAUTH_TOKEN`(성진이 `claude setup-token`으로 발급해 직접 넣음): 잡 안 `claude auth status`가 `loggedIn: true`·`authMethod: oauth_token`, read-only 작업자가 샌드박스 안에서 `completed` → `session_create`의 두 번째 해결책은 **확인됨**. 검증 뒤 토큰 줄은 지웠다 | 실측(run 44006053369, `.tmp/schedule-impl/probe-out/a-default-plist-token.log`) |
| 사실 | (0단계 b) 러너 `.env`에 `PATH=…`을 넣고 서비스를 다시 띄워도 잡의 PATH는 `.path` 그대로다 → `path_missing`의 해결은 `.path`를 고치는 것뿐(`.env`의 PATH는 먹지 않는다) | 실측(run 44006154708, 리스너 시작 02:52:32Z < 잡 02:52:48Z) |
| 사실 | (0단계 c) 비활성화된 워크플로의 런은 재실행할 수 없다: `gh run rerun` → "Unable to retry disabled workflow"; 디스패치는 HTTP 422 "Cannot trigger a 'workflow_dispatch' on a disabled workflow" → 스스로 끈 일회성 예약은 웹의 Re-run이 안 되고, 다시 돌리려면 `gh workflow enable` 뒤 수동 실행이거나 `schedule --at` | 실측(run 44006242270) |
| 사실 | (0단계 d) 러너 잡 안에서 `batch --worktree`(write, haiku)가 worktree `.claude/worktrees/<group>-1`을 만들고 그 안에서 쓰며, `clean`(강제 아님)은 변경이 있어 남긴다. 사용자의 SessionStart 훅이 만드는 `.claude/histories`가 추적 파일이면 worktree에서 ` M`으로 보인다(그 저장소의 설정 문제) | 실측(run 44006368956) |
| 사실 | (0단계 e) `::stop-commands::<토큰>` 뒤의 `::error::`·`::add-mask::` 줄은 주석·마스크가 되지 않고 글자 그대로 로그에 남으며, `::<토큰>::` 뒤의 `::warning title=…::`만 주석이 된다. 러너는 토큰 자체를 로그에서 `***`로 가린다 (K21 그대로) | 실측(run 44006368956 annotations) |
| 사실 | (0단계 f) 같은 경로의 첫 생성 PUT 둘을 동시에 → 이긴 쪽 200, 진 쪽 **HTTP 409** `is at <sha> but expected <sha>`(422가 아니다). 이미 있는 파일에 `sha` 없이 PUT → 422 `"sha" wasn't supplied`, 낡은 `sha` → 409 `<path> does not match <sha>` → K12는 409·그 422를 모두 충돌로 보고 다시 읽어 합친 뒤 한 번 재시도(설계 그대로) | 실측(`.tmp/schedule-impl/raw/race-*.json`) |
| 사실 | (0단계) fixture 재캡처: Contents GET·GET 404·PUT 생성·PUT 갱신·PUT sha 없음(422)·PUT 낡은 sha(409)·DELETE·삭제 뒤 GET 404, `repos/<o>/<r>`·저장소 404, `actions/workflows/<file>` active·disabled·404·목록, enable·disable(빈 본문), `actions/runners`, 없는 워크플로 디스패치 404, 동시 생성 409. 공개 레포에 넣기 전 `download_url`의 `?token=`, `temp_clone_token`, 커밋 이메일을 가렸다. probe 14 같은 write 런(haiku, 도구 7회, 거부 1건)을 run `20261117-115443-nightly-docs-756b`로 다시 캡처해 경로·사용자 환경(init의 skills·plugins·slash_commands, thinking 서명)을 가렸다 | 실측(`.tmp/schedule-impl/fx/`) |

## 아키텍처

```
schedule (대화 중, 오케스트레이터가 부름)
  ├─ GitHub API ─▶ <repo> 기본 브랜치: .github/workflows/claude-<name>.yml   (정의의 진실 + cron 백업)
  └─ launchctl ──▶ ~/Library/LaunchAgents/claude-schedule.<owner>-<repo>.<name>.plist   (정시 디스패처)

정시:   launchd ── gh workflow run claude-<name>.yml -f source=dispatcher ──▶ GitHub ──▶ 이 저장소의 self-hosted 러너(이 맥)
늦게:   GitHub cron(백업) ───────────────────────────────────────────────▶ 같은 러너 → K4로 건너뜀
수동:   웹의 Run workflow / gh workflow run (mode=run|check) ─────────────▶ 같은 러너 → 항상 실행

러너 잡 (checkout 없음, concurrency 그룹으로 직렬)
  Run     uv run "<skill>/scripts/cli.py" __scheduled run …      env: CLAUDE_SCHEDULE_PROMPT
            slot 판정(K4) → start 또는 batch --worktree(K10) → 끝날 때까지: 활동을 스텝 로그로, attention은 ::warning:: → 상태로 exit 0/1
  Finish  if: always()   uv run "<skill>/scripts/cli.py" __scheduled finish …      env: GH_TOKEN(잡 토큰)
            살아 있으면 stop → worktree clean → 일회성이면 disable+디스패처 제거 → summary.md → $GITHUB_STEP_SUMMARY

작업자: 평소와 같은 감독·프로필·샌드박스, 프로젝트 체크아웃(또는 worktree)에서. 런은 <project>/.claude-runs/<run_id>/ 에 남는다.
```

## 구현 후 디렉터리 구조 (바뀌는 것만)

```
.claude/skills/claude/
├── SKILL.md                         # 섹션 하나 추가(아래); references/는 두지 않는다(K29)
└── scripts/
    ├── cli.py                       # schedule · unschedule · 숨긴 __scheduled 추가, start --help는 그대로
    └── claude/
        ├── schedule/                # feature (새로)
        │   ├── __init__.py          # 입구
        │   ├── spec.py              # 예약 spec: 검증, 플래그 > 기록 > 기본 합치기, 이름·경로
        │   ├── times.py             # cron 5필드·--at → 값 집합, 이전/다음 발화 시각, slot(K4·K6)
        │   ├── define.py            # schedule · unschedule · 목록(K12)
        │   ├── execute.py           # __scheduled run / finish / check(K1·K4·K8·K9·K13)
        │   └── summary.py           # 런 → summary 마크다운(아래 명세)
        ├── github/                  # system (새로): gh CLI와 Actions가 소유한 형식 전부
        │   ├── __init__.py
        │   ├── api.py               # 저장소 사실, Contents GET/PUT/DELETE, workflow enable/disable, runners, 오류 해석
        │   ├── workflow.py          # 워크플로 YAML 쓰기(`${{` 이스케이프, 블록 스칼라), `# spec:` 줄 읽기
        │   ├── job.py               # 잡 env 읽기·지우기(K9), step summary·output·주석 쓰기, 런 URL
        │   └── runner.py            # 이 저장소 러너의 로컬 설치 찾기: 서비스 plist(SessionCreate), `.env` 토큰 유무, `.path`
        ├── launchd/                 # system (새로): launchd가 소유한 형식
        │   ├── __init__.py
        │   └── agents.py            # 디스패처 plist 쓰기(plistlib)·bootstrap·bootout·목록, StartCalendarInterval 사전
        ├── registry/
        │   └── schedules.py         # store (새로): <registry>/.schedules/<name>/state.json — last_slot, 잡별 인계(run_id), 잠금
        ├── claude_cli/stream.py     # activity_rows 추가, log_lines는 그 행의 글 렌더링(PR ①)
        ├── claude_cli/argv.py       # turn_preamble(origin=…), 한 명짜리 그룹 문장 생략
        ├── observe/                 # snapshot 추가(PR ①): 헤더·답·활동 행을 구조로
        ├── runs/ · batch/           # origin 인자 통과; runs/supervisor.py는 시작 중 정지(K25, PR ⓪)
        ├── git/repo.py              # current_branch · status_snapshot · numstat 추가(K27)
        └── doctor.py                # schedule 섹션
tests/
├── support/fake_gh/gh               # 새로: argv·stdin 기록, 실제 캡처 fixture로 응답
├── support/fake_launchctl/launchctl # 새로: bootstrap/bootout/print 기록
├── support/fixtures/github/*.json   # 0단계에서 실제 gh로 캡처
├── support/fixtures/summary/*.md    # 손으로 쓴 기대 summary
├── test_times.py test_workflow.py test_schedule_define.py test_scheduled_run.py test_summary.py test_schedule_races.py
├── smoke_real_schedule.py           # CLAUDE_SKILL_REAL=1 CLAUDE_SKILL_REAL_GITHUB=1
└── e2e/scenarios.md                 # 예약 시나리오 추가
```

`__init__.py` 독스트링(패키지 지도)에 Features `schedule/`, Systems `github/`·`launchd/`, Store 한 줄(`.schedules`)을 더하고 간선 문장을 "feature 간 간선은 batch → runs, schedule → runs·batch·observe"로 고친다. `tests/test_structure.py`: `KINDS`에 `schedule: feature`·`github: system`·`launchd: system`, `FEATURE_EDGES`에 `(schedule, runs)`·`(schedule, batch)`·`(schedule, observe)`.

## 명령 표면 (0.2.0에서 더해지는 것)

최상위 12개 + 숨긴 `__supervise`·`__scheduled`. 종료 코드 규칙은 그대로(0 / 1 거부·실패 / 2 명령줄 / 3 doctor blocker). 세 번째 단계의 help는 만들지 않는다: 예약 관련은 `schedule`·`unschedule` 두 형제 명령이고, 런 조회·재실행·취소·일시정지는 `gh`와 GitHub 웹이 한다.

| 명령 | 인자 | 출력 요지 |
|---|---|---|
| `schedule` | `--name NAME`(소문자·숫자·하이픈, 24자), `[PROMPT]` 또는 `--prompt-file FILE`(`-`면 stdin; K24), `--cron EXPR` 또는 `--at YYYY-MM-DDTHH:MM`(둘 다 **이 맥의 시스템 시간대** 기준이고 그 이름이 워크플로 `timezone:`에 쓰인다고 help가 말한다 — UTC로 환산하지 않게), `--profile`(새 예약이면 필수; `--worktree`와 `read-only`는 함께 못 씀), `--model`·`--effort`(스킬 기본값), `--schema FILE`, `--timeout SEC`(기본 3600), `--worktree`·`--no-worktree`, `--runs-on LABEL`(반복; 기본 `self-hosted`), `--message TEXT`, `--public-ok`, `--dry-run`, `--project`. 같은 이름이 있으면 준 플래그만 바꾼다(K2) | `name`, `repo`, `workflow`(`status` committed/unchanged, `path`, `url`, `commit`, `was_disabled`), `dispatcher`(`status`, `label`, `plist`, 실패면 `error`), `fires`(`timezone`, `cron` 또는 `at`, 다음 발화 3개), `settings`(profile·model·effort·timeout·worktree), `runner`(맞는 러너의 `name`·`status`·`labels`, 로컬 서비스의 `session_create`·`env_token`·`path_has`, 그리고 `problems[]` — 각 `{problem: none|offline|session_create|path_missing, why, fixes}`; K29), `warnings`, `next`(`gh workflow run … -f mode=check`와 이유 — K13). `--dry-run`이면 아무것도 쓰지 않고 `workflow_text`·`dispatcher_text`·`fires` |
| `schedule --list` | `--project` | 이 저장소의 예약마다 `name`, `cron`/`at`, `profile`, `state`(active·disabled), `dispatcher`(loaded·missing), `stale_entry`, `last`(로컬 상태: slot·run_id·state·GitHub 런 URL); 워크플로 없는 디스패처는 `orphans` |
| `unschedule` | `--name NAME`, `--message TEXT`, `--project` | `dispatcher`·`workflow` 각각의 결과(K12), 남은 것이 있으면 `note` |
| `doctor` | (그대로) | `schedule` 섹션 추가: `gh`(경로·로그인·`workflow` 스코프), `repo`(이름·`private`·기본 브랜치, 없으면 이유), `runners`(API의 이름·상태·라벨 + 로컬 서비스의 `session_create`·`env_token`·`path_has` + `problems[]`, `schedule` 응답과 같은 모양), `platform_ok`. 예약 준비가 안 된 것은 blocker가 아니라 `warnings`(평소 런에는 영향이 없으므로) |
| `__scheduled` (숨김) | `run`·`finish`, 둘 다 같은 플래그(`--name`, `--project`, 설정, `--cron`/`--at`, `--timezone`, `--worktree`, `--workflow FILE`, `--definition ID`)와 env(`CLAUDE_SCHEDULE_MODE`·`_SOURCE`·`_PROMPT`·`_SCHEMA`) | 위 "끝과 종료 코드" 표 그대로 |

거부(비용 0, 아무것도 쓰기 전): 작업자 안(J6), macOS 아님(K15), `gh` 없음·로그인 안 됨·`workflow` 스코프 없음, 프로젝트가 GitHub 원격을 가진 git 저장소가 아님, public인데 `--public-ok` 없음(K14), 이름 규칙 위반, 새 예약인데 프롬프트·프로필·시각 중 빠진 것, `--cron`과 `--at` 동시, 받지 않는 cron 형태·5분 미만 간격·사전 500개 초과(K6), 과거의 `--at`. GitHub가 커밋을 거부하면(브랜치 보호 422 등) 그 메시지와 `instead`(`--dry-run`으로 파일을 받아 PR로).

## 워크플로 파일

GitHub가 실제로 받아들이고 돌린 부분(probe 11): `run-name`의 `inputs.source || github.event_name`, `schedule`의 `timezone`, 문자열 입력 `source`, `concurrency`의 `queue: max`, 스텝 env의 블록 스칼라 프롬프트와 `${{ '${{' }}` 이스케이프, `permissions: actions: write`, `if: always()` 스텝, `GH_TOKEN: ${{ github.token }}`. **아직 GitHub에 올려 보지 않은 부분**: `mode` choice 입력, `run-name`의 삼항식, `--definition` 플래그, 스키마 블록, `permissions: {}`와의 조합. GitHub가 유일한 검증기이므로(probe 6에서 `cancelled()` 한 줄로 파일 전체가 거부됐다), 기대 파일(golden)은 0단계·PR ③에서 **생성된 파일을 임시 저장소에 올려 통과한 뒤에** 그 본문으로 쓴다.

```yaml
# Written by the claude skill's `schedule` command. Run it again with the same --name to change it; `unschedule` removes it.
# spec: {"name": "nightly-review", "cron": "0 3 * * *", "timezone": "Asia/Seoul", "profile": "read-only", …}
name: claude · nightly-review
run-name: nightly-review · ${{ inputs.mode == 'check' && 'check' || inputs.source || github.event_name }}
on:
  schedule:
    - cron: '0 3 * * *'
      timezone: Asia/Seoul
  workflow_dispatch:
    inputs:
      mode:
        description: run starts the worker; check only verifies that this runner can log in and start one
        type: choice
        options: [run, check]
        default: run
      source:
        description: Leave empty for a manual run. The local dispatcher sets it so that a late duplicate is skipped.
        type: string
        required: false
permissions: {}                      # 일회성 예약만 actions: write (K7)
concurrency:
  group: claude-nightly-review
  cancel-in-progress: false
  queue: max
jobs:
  run:
    runs-on: [self-hosted]
    timeout-minutes: 70              # 런 시간 제한 + 10분
    steps:
      - name: Run
        env:
          CLAUDE_SCHEDULE_MODE: ${{ inputs.mode }}
          CLAUDE_SCHEDULE_SOURCE: ${{ inputs.source }}
          CLAUDE_SCHEDULE_PROMPT: |
            <프롬프트, `${{`는 `${{ '${{' }}`로>
          # --schema가 있으면 CLAUDE_SCHEDULE_SCHEMA 블록도 여기(K22)
        run: uv run "/abs/skill/scripts/cli.py" __scheduled run --name nightly-review --project "/abs/project" --profile read-only --model sonnet --effort high --timeout 3600 --cron '0 3 * * *' --timezone Asia/Seoul --workflow claude-nightly-review.yml --definition 3f9a1c2e
      - name: Finish
        if: always()
        env:
          CLAUDE_SCHEDULE_MODE: ${{ inputs.mode }}
          CLAUDE_SCHEDULE_SOURCE: ${{ inputs.source }}
          GH_TOKEN: ${{ github.token }}
        run: uv run "/abs/skill/scripts/cli.py" __scheduled finish --name nightly-review --project "/abs/project" --profile read-only --model sonnet --effort high --timeout 3600 --cron '0 3 * * *' --timezone Asia/Seoul --workflow claude-nightly-review.yml --definition 3f9a1c2e
```

두 스텝은 같은 플래그를 받는다(K19): `Finish`가 인계 없이도 일회성·worktree·mode를 알도록.

### 끝과 종료 코드 (K1·K20)

| 일어난 일 | `Run` | `Finish` | 잡 결론 |
|---|---|---|---|
| 작업자가 `completed`(스키마면 구조화 결과 있음) | 0 | 0 | 초록 |
| 완료했지만 권한 거부·`mode_mismatch`·attention이 있었음 | 0 | 0, WARNING | 초록 |
| 늦게 온 중복(K4) · check 통과 | 0 | 0, NOTE | 초록 |
| `failed`·`timed_out`·`orphaned`·스키마 결과 없음·누가 로컬에서 `stop`함 | 1 | 0, CAUTION + `::error::` | 빨강 |
| 시작 전 거부(버전 하한, worktree 불가 — slot은 차지됨, K28 ④) · check 실패 | 1 | 0, CAUTION + `::error::` | 빨강 |
| 프로젝트 경로 없음(K23 — 아무것도 기록하지 못함) | 1 + `::error::` | 0, `$GITHUB_STEP_SUMMARY`에만 CAUTION | 빨강 |
| 웹에서 취소 · 잡 시간 초과 | 죽음(143) | 0, 살아 있던 작업자를 정지 | 회색(cancelled) |
| `Finish`의 정리 단계 일부 실패(worktree 정리, 일회성 끄기, 로컬 summary) | — | 0, WARNING에 실패와 복구 명령 | `Run`대로 |
| 작업자가 멈췄음을 확인하지 못함(정지 뒤에도 살아 있음, `meta.json`을 못 읽음) · `$GITHUB_STEP_SUMMARY`를 못 씀 | — | 1 + `::error::` | 빨강 |
| `Finish`가 아예 돌지 못함(`uv`·스킬 경로 없음, 러너 죽음) | — | — | 빨강, summary 없음; 남은 작업자는 러너의 잡 종료 정리가 죽여 `orphaned`(보장 밖) |

디스패처 plist: `Label` `claude-schedule.<owner>-<repo>.<name>`, `ProgramArguments` [`gh`의 절대 경로, `workflow`, `run`, `claude-<name>.yml`, `--repo`, `<owner>/<repo>`, `--ref`, `<기본 브랜치>`, `-f`, `source=dispatcher`], `StartCalendarInterval`(K6), 로그 `~/Library/Logs/claude-schedule/<owner>-<repo>.<name>.log`.

## summary 명세 (성진이 고른 샘플 B)

`summary.md`의 순서. 없는 부분은 통째로 빠진다. 전체는 900KB 아래로 자른다(스텝 한도 1MiB): 답 400KB, 프롬프트 50KB, 활동 300행을 넘으면 넘은 양과 로컬 `log` 호출을 적는다.

1. **제목** `# <아이콘> <name> · <상태>` — ✅ completed, ❌ failed·timed_out·orphaned, ⏹ interrupted(취소), ⏭ skipped, 🔎 check.
2. **표** — `Run`: 프로필 · 모델/effort · 소요 · 도구 호출 수 · 비용. `Trigger`: dispatcher·schedule (backup)·manual·re-run (attempt n) · slot · 시작 시각. `Local tree`: 브랜치 @ 짧은 SHA, 시작할 때 미커밋 수, "not the commit GitHub shows for this run"(worktree면 그 경로·브랜치·기준 커밋; git이 아니면 그 말).
3. **알림** — `[!CAUTION]` 실패: `error`, 마지막 메시지(예: `Not logged in · Please run /login`), 시간 초과면 제한 값. `[!WARNING]` 권한 거부(도구와 대상 목록), `mode_mismatch`, 런 중에 본 attention(종류와 지속), 프로필 예외 수, 끄기·정리 실패(K8). `[!NOTE]` 건너뜀(앞선 런 링크)·취소(세션은 resume 가능).
4. **`<details>` Prompt** — 네 개짜리 백틱 울타리 안에 전문.
5. **답** — 작업자의 최종 메시지를 제목 없이 그대로. `--schema` 런은 `json` 코드블록.
6. `---`
7. **`<details open>` Changes**(write·auto 런) — "changed during the run": K27의 전후 비교로 본 경로, 시작할 때 깨끗했던 파일에는 줄 수, 이미 고쳐져 있던 파일에는 그 표시, 어느 트리인지, "다른 프로세스가 같은 시간에 고친 것도 여기 보인다" 한 줄. worktree가 남았으면 경로·브랜치·`clean --group` 호출. git이 아니면 편집 도구가 쓴 파일 목록과 "셸이 쓴 파일은 여기 없다".
8. **`<details>` Activity** — 표 `# | Time | Step | Detail | Result`: 호출마다 한 행(read·bash·edit·write·grep·glob·fetch·search·skill·agent·mcp·🚫 denied·retry·compact·result), `Time`은 시작 후 m:ss, `Detail`은 한 줄로 자른 명령·경로(코드 서식, `|` 이스케이프), `Result`는 exit·출력 크기. 표 아래에: 실패한 명령의 출력 발췌(코드블록), 중간 메시지 전문(번호로 표의 행과 이어짐), 시작 모델·모드·한도 한 줄.
9. **`<details>` Continue on your Mac** — `resume` 호출(전체 한 줄), `claude --resume <session>`(작업 디렉터리 포함), 런 id와 `.claude-runs/<run>/`.

스텝 로그(`Run`의 stdout): 시작 한 줄(런 id·프로필·slot), 이어서 `log`와 같은 줄을 생기는 대로, attention은 `::warning title=<name>::…`, 끝에 상태 한 줄. `Finish`는 실패면 `::error title=<name> failed::<error>`(런 페이지 맨 위 주석), `$GITHUB_OUTPUT`에 `run_id`·`state`.

## 단위 입구 (새것과 바뀌는 것)

| 단위 | 입구 | 숨기는 것 |
|---|---|---|
| `schedule` (feature) | `schedule(...)`, `unschedule(...)`, `schedules(...)`, `scheduled_run(...)`, `scheduled_finish(...)`, `fire_times(spec, now, count)`, `current_slot(spec, now)`, `render_summary(snapshot, context)`(context = 트리거·slot·트리 전후·URL·정리 결과), `SCHEDULE_DEFAULTS`, `NAME_RULE` — 시각과 summary는 `now`·입력을 인자로 받는 순수 입구라 테스트가 직접 부른다. 서브프로세스 테스트의 시계는 env `CLAUDE_SKILL_TEST_NOW`(epoch; `CLAUDE_SKILL_TEST_TIMINGS`와 같은 관례)로 고정 | spec 합치기, K4 slot 판정, K12 순서, summary 구성·자르기, cron 해석 |
| `github` (system) | `repo_facts(cwd)`, `read_workflow(repo, file)`, `write_workflow(repo, file, text, message, sha)`, `delete_workflow(...)`, `set_workflow_enabled(...)`, `list_workflows(repo, prefix)`, `runners(repo)`, `local_runner(repo)`, `render_workflow(spec)`, `parse_spec(text)`, `job_context(env)`, `scrub_job_env(env)`, `write_summary(text)`, `write_output(...)`, `annotate(...)`, `gh_status()` | `gh` argv, API 경로·필드 이름·HTTP 오류 문구, YAML 문법·`${{` 이스케이프, `GITHUB_*` 변수 이름, 러너 디렉터리 파일(`.runner`·`.env`·`.path`)과 서비스 plist 이름 규칙 |
| `launchd` (system) | `install_agent(label, argv, calendar, log)`, `remove_agent(label)`, `agent_state(label)`, `list_agents(prefix)`, `calendar_entries(fields)`, `supported()` | plist 키, `launchctl` 도메인·하위 명령·종료 코드 |
| `registry` (store) | `schedule_state(registry, name)`, `claim_slot(registry, name, slot, job, entry)`(잠금 아래 K4의 판정과 K19 ①의 잡 기록을 한 번에; 건너뛰면 앞선 잡을 돌려줌), `record_job_outcome(...)`, `read_job(...)`, `set_definition(registry, name, id)`·현재 값 읽기(K8), `remove_schedule_state(...)`, 런 찾기 `find_by_origin_job(registry, job)` | 상태 파일 모양·잠금·보관 개수 |
| `claude_cli` | `activity_rows(events, rel_to, messages)` 추가; `log_lines`는 그대로(행의 글 렌더링); `turn_preamble(profile, group, worktree, origin)` | 이벤트 → 행 해석, `timestamp` 필드 |
| `observe` | `snapshot(cwd, ref, runs_dir)` 추가 → `{header, text, json, rows}`(스키마 결과가 없어도 예외 없이 `json: None`; 거부는 `result` 렌더링만 던진다), `wait_ended(cwd, ref, runs_dir, on_attention)` 추가(끝날 때까지; 새 attention마다 콜백). `result`·`log`의 지금 출력은 글자 그대로 보존: `log`의 `unparsed lines`와 끝줄 `run=… state=…`, `result`의 live·finishing `note`와 `next`, 스키마 문서, 그룹·`--wait` 출력 | — |
| `runs` · `batch` | `start(..., origin=None)` → `create_run(..., origin=None)`(meta `origin`에 넣고 `turn_preamble`에 넘김), `batch(..., origin=None)` → `start_members` → `start_member` → `create_run`. 감독의 시작 중 정지(K25) | — |
| `git` | `current_branch(path)`, `status_snapshot(path)`(항목마다 상태와 `fingerprint`), `numstat(path, paths)` 추가 | porcelain 해석 |

`cli.py`는 위 입구만 부르고 결정 로직을 갖지 않는다: 인자만으로 하는 검사(`--cron`과 `--at` 동시 등), 분기, 출력, 종료 코드.

## SKILL.md 섹션 구조 (영어, 한 파일; 기존 네 섹션은 그대로)

- **frontmatter `description`**: 기존 문장에 예약을 더한다 — "…and scheduling a worker to run later or on a recurring schedule on this Mac, with GitHub Actions as the record and the controls". 트리거 추가: `schedule a claude worker`, `scheduled claude`, `예약`, `매일 ~시에 돌려`, `정기 실행`, `예약 작업자`. "Not for"에 Claude Code 자체의 cloud·Desktop scheduled tasks와 `/loop`에 대한 질문을 더한다(다른 스킬 이름은 쓰지 않는다). `claude -p "/skill-doctor"`로 내장 `schedule` 스킬과의 트리거 겹침을 확인하고, 겹치면 이 description만 고친 뒤 결과를 성진에게.
- **대응표**(`## Handing work over`)에 한 행: `a scheduled or recurring agent` → `schedule` (runs here, through this repository's runner) → —.
- **새 섹션 `## Scheduling a worker`** (사실로 쓴다; 각 문장은 e2e 대조에서 행동을 바꾸는지 확인하고, 안 바꾸면 뺀다):
  1. **Nobody is there when it runs.** 프로필과 시간 제한이 사람 대신 경계를 정한다; attention은 아무도 못 보므로 런을 멈추지 않는다; 그래서 프롬프트는 이 대화 없이 혼자 서야 하고(무엇을 보고 무엇을 답으로 낼지), 답은 GitHub의 summary가 된다.
  2. **`schedule` changes things outside this conversation.** 저장소 기본 브랜치에 워크플로 파일을 PR 없이 커밋하고 이 맥에 LaunchAgent를 설치하며, 둘 다 `unschedule`까지 남는다. **프롬프트는 그 커밋된 파일에 들어가므로 `unschedule` 뒤에도 git 이력에 남고**, 프롬프트·답·활동은 런마다 그 저장소를 볼 수 있는 모두에게 보이는 summary로 올라간다(public이면 누구에게나 — 그래서 거부된다) → 비밀이나 남의 정보를 프롬프트에 넣지 않는다.
  3. **This Mac keeps the time and does the work; GitHub keeps the record and the controls.** 정시 발화는 이 맥의 LaunchAgent가 하고 GitHub의 cron은 늦게 오는 백업이다(늦은 중복은 건너뛴다). 필요한 것: private 저장소, 그 저장소의 self-hosted 러너, 그 러너 서비스가 Claude 로그인을 읽을 수 있음, 맥이 깨어 있음(자고 있었으면 깨어날 때 한 번 따라잡는다). 대화 안의 `doctor`는 서비스 안을 보지 못하므로 `schedule` 응답의 `next`(check 실행)만이 증명이다. 러너가 없거나 설정이 모자라면 응답의 `runner.problems`가 무엇이 왜 실패하는지와 고치는 길을 말한다; 로그인을 어떻게 읽게 할지처럼 길이 둘 이상인 것은 그 맥 주인의 선택이다.
  4. **The worker sees the checkout as it is when the job actually starts it.** 예약 시각이 아니라 잡이 큐를 지나 작업자를 띄우는 그때의 브랜치와 미커밋 상태이고, GitHub가 그 런에 보여 주는 커밋이 아니다; 쓰기 예약은 그 트리를 고치며 `--worktree`가 격리한다(변경을 가져오는 것은 사람 몫).
  5. **Afterwards it is a run like any other.** `status`·`log`·`result`·`resume`이 그대로 되고 summary의 "Continue on your Mac"이 호출을 준다. GitHub 쪽(보기·재실행·취소·일시정지)은 `gh`와 웹의 일이다; 일시정지는 워크플로 비활성화.
- `## When something goes wrong`에 한 줄: 예약이 빨갛게 끝나면 summary의 맨 위 알림이 이유이고, `Not logged in`은 작업자가 아니라 러너 서비스 쪽 문제다 — `doctor`의 `schedule.runners[].problems`가 무엇을 고칠지 말한다.

## 러너 지식이 사는 곳 (references/ 없음 — K29)

이전 안의 `references/runner.md` 일곱 섹션이 어디로 갔는가. 구현 세션은 이 표대로 싣고, 어디에도 싣지 않는 것은 싣지 않는다.

| 내용 | 자리 |
|---|---|
| 이 저장소에 러너가 있는가·온라인인가·라벨 | `schedule`·`doctor` 응답 `runner`(API) |
| 저장소 하나에 러너 하나(개인 계정), 서비스로 설치(`svc.sh install`, sudo 없음) | `runner.problems`의 `none` 항목 `fixes` |
| public 저장소에 러너를 달지 않는 이유 | K14 거부 메시지와 `schedule --help`의 `--public-ok` 설명 |
| `.path`에 PATH가 굳는다, `uv`·`claude`·`gh`가 그 안에 있어야 한다 | `runner.problems`의 `path_missing`(로컬 러너 디렉터리를 읽어 판정) |
| 기본 서비스는 Keychain 로그인을 못 읽는다, 두 길과 대가 | `runner.problems`의 `session_create`(plist를 읽어 판정; `.env`에 토큰이 있으면 문제 아님) |
| 증명은 check 실행뿐, 그 summary를 읽는다 | `schedule` 응답 `next`, SKILL.md 3번 |
| 맥이 깨어 있어야 함, 깨어나면 한 번 따라잡음 | SKILL.md 3번 |
| 오프라인이면 잡은 24시간 기다리다 실패, 러너 하나는 잡을 하나씩 돈다(긴 작업자가 그 저장소의 다른 잡을 막는다) | `schedule --help` epilog |
| 설치 순서, 체크섬, 제거 방법, `pmset` | 싣지 않는다(대조 2에서 기본 모델이 맞게 함) |

## 그 밖의 문서 (섹션 구조)

- **README.md**: 기능 목록에 한 항목, 새 절 `## Scheduling`(구도 그림 한 장, 필요한 것 네 가지, 첫 예약 → check → 첫 실행의 흐름, summary 스크린샷 대신 구성 요약, 일회성·`--worktree`·일시정지·삭제), "Scope"에 macOS 전용·private 전용.
- **CHANGELOG.md** `[0.2.0]`: Added(`schedule`·`unschedule`·`doctor`의 schedule 섹션·summary), Changed(한 명짜리 그룹의 앞머리 문장).
- **SECURITY.md**: 예약이 맥과 GitHub에 남기는 것(워크플로 파일, LaunchAgent, summary에 올라가는 내용), public 거부의 이유, 잡 토큰의 범위(K7), 작업자에게서 떼는 변수(K9).
- **CONTRIBUTING.md**: 새 단위 셋과 간선, 가짜 `gh`·`launchctl`, 실제 예약 스모크 실행법과 그것이 만드는·지우는 것.
- **`.claude-plugin/plugin.json`**: `version` 0.2.0, description에 예약 한 구절, keywords에 `github-actions`·`launchd`·`schedule`·`self-hosted-runner`.
- **`CLAUDE.md`(레포)**: Tests 줄에 실제 예약 스모크 한 구절.

## 테스트 seam (coding 스킬)

기대값은 구현 밖에서 온다: 이 장부의 실측, 실제 `gh` 캡처, `man launchd.plist`, 손으로 계산한 시각, 성진이 고른 샘플 B. 러너의 종료 코드와 실패 출력은 파이프로 가리지 않는다. red는 의도한 동작이 없어서여야 한다(새 단위는 빈 입구부터).

- **S1 CLI 서브프로세스 + PATH의 가짜 `claude`·`gh`·`launchctl`, 임시 HOME**(주 seam).
  - 가짜 `gh`: argv와 stdin을 기록하고, 0단계에서 실제 `gh`로 캡처한 fixture로 답한다(Contents GET·PUT 생성·PUT 갱신·DELETE·404·422, `repos/<o>/<r>`, `actions/runners`, `actions/workflows`, enable·disable). 가짜 `launchctl`: `bootstrap`·`bootout`·`print`를 상태 파일로.
  - `schedule` 계약: 커밋된 워크플로 본문(가짜 `gh`가 받은 base64를 풀어 **손으로 쓴 기대 파일**과 비교 — 기대 파일의 모양은 probe 11이 통과시킨 것), 임시 HOME에 생긴 plist(plistlib로 읽어 기대 사전과 비교), 응답 필드, K12의 반쪽 실패(가짜 `launchctl`이 실패 → `workflow: committed`·`dispatcher: failed`; 가짜 `gh`가 422 → 아무 plist도 없음), 같은 이름 재호출의 합치기(K2), 모든 거부, `--dry-run`이 가짜들에 쓰기 호출을 하나도 남기지 않음.
  - `__scheduled` 계약(잡 env를 흉내: `GITHUB_EVENT_NAME`·`GITHUB_RUN_ID`·`GITHUB_STEP_SUMMARY`·`GITHUB_OUTPUT`·`RUNNER_TRACKING_ID` 등): 완료 → exit 0과 summary; 시작 실패(`Not logged in` 가짜 시나리오) → exit 1과 CAUTION; 권한 거부 → exit 0과 WARNING; `--schema` 결과 없음 → exit 1; 시간 초과; `Run`을 죽인 뒤 `Finish` → 런이 `interrupted`이고 summary가 있음(취소 경로); 자동 트리거 두 번째 → 건너뜀(작업자 argv 기록이 하나뿐); 수동은 항상 실행; 일회성 → 가짜 `gh`에 disable, 가짜 `launchctl`에 bootout; K9(가짜 `claude`가 기록한 env에 `GITHUB_ENV`·`GITHUB_STEP_SUMMARY`·`GH_TOKEN`이 없고 `RUNNER_TRACKING_ID`는 있음); `origin` 앞머리 문장이 작업자 stdin에; `--worktree` → 그룹 하나·`Finish` 뒤 변경 없으면 worktree 없음·있으면 남고 summary가 말함; `mode=check` → 작업자 argv 없음.
  - `__scheduled`의 빈틈 경로(두 리뷰가 짚은 것): 가짜 `claude`의 init을 늦춘 채 `Run`을 죽이고 `Finish` → 런을 `origin.job`으로 찾아 정지; 실패한 자동 런의 attempt 2 → 작업자가 다시 뜸; 건너뛴 런의 attempt 2 → 실행; 실패한 slot의 재시도(K4): read-only 런이 `failed`로 끝난 slot에 자동 트리거가 다시 옴 → 한 번 더 돎·세 번째는 건너뜀, write 런이면 건너뜀, 취소된(`interrupted`) slot이면 건너뜀; 재시도 뒤 상태 파일을 지우고 세 번째 자동 트리거 → 런 meta의 `origin.retry_of`로 복구해 건너뜀; `Run`의 순서(K28): 시작 전 거부(커밋 없는 `--worktree`)도 slot을 차지한 채 `outcome`에 남고 재시도 규칙을 따름(write라 다음 자동 트리거는 건너뜀), 수동·재실행도 잡 기록(`tree_before`)을 남겨 Changes가 나옴; 일회성 read-only 실패 → `Finish`가 끄지 않음 → 두 번째 자동 트리거가 재시도하고 그 `Finish`가 끔, 일회성 write 실패 → 바로 끔(K8); 살아 있는 일회성 런 중에 `unschedule` → 상태는 남고 `definition`은 비며 `Finish`가 끄기를 시도하지 않음, 이어서 **같은 내용으로** 다시 `schedule` → `definition`이 새 값이라 옛 잡의 `Finish`가 새 예약을 끄지 않음; `batch`가 이름 충돌로 거부 → 빨강이고 기존 그룹은 그대로(K10); worktree 런의 Changes는 정리 전의 worktree에서 잡히고 변경 없는 worktree는 지워짐, 작업자가 stage한 변경의 줄 수가 나옴(K27); 상태 파일을 지운 뒤 자동 트리거 → 런 meta에서 `last_slot` 복구; 일회성에 `지금 − at` > 26시간 → 건너뜀; 프로젝트 디렉터리를 지운 뒤 `run`·`finish` → 빨강·레지스트리가 새로 생기지 않음; `--worktree`인데 커밋 없는 저장소 → 작업자 argv 없음·빨강; `meta.json`을 깨뜨린 뒤 `Finish` → summary는 있고 exit 1; `Finish`의 정리 한 단계만 실패(가짜 `gh` disable 실패, 가짜 `launchctl` bootout 실패 각각) → 나머지는 진행·WARNING에 복구 명령; 런이 도는 동안 같은 이름을 다시 `schedule`한 일회성 → `Finish`가 끄지 않음(K8); check 실패 → exit 1과 🔎 summary; 가짜 `claude`가 `::error::x`를 담은 메시지를 냄 → 스텝 출력에서 그 줄이 `::stop-commands::` 구간 안(K21); 시작 전에 고쳐져 있던 파일을 작업자가 더 고침·미추적 파일을 고침·지움 → Changes가 K27대로; 스키마 원본 파일을 지운 뒤 `run` → 성공(K22). 위 "끝과 종료 코드" 표의 각 행이 테스트 하나다.
  - `unschedule`·`--list`: `unschedule`의 세 갈래(가짜 `launchctl` 실패, 가짜 `gh` 404, 둘 다 성공)와 살아 있는 런이 있을 때 상태 보존; `--list`의 `orphans`(워크플로 없는 plist), `stale_entry`(spec의 스킬 경로가 없음), `state: disabled`. 빈 non-TTY stdin으로 플래그 없는 재호출 → 프롬프트 유지·exit 0(K24). 같은 이름 동시 생성에서 진 쪽의 422 `"sha" wasn't supplied` → 다시 읽어 합치고 성공(K12).
  - summary: 서브프로세스에서는 섹션의 존재·순서·알림 종류·종료 코드만 단정한다(가짜 `claude`가 `timestamp`를 현재 시각으로 바꾸고 런 id·경로가 매번 달라서). **전문 비교는 프로세스 안에서** `render_summary`에 손으로 쓴 meta(시작 시각·런 id·세션 id·경로 고정)와 fixture 이벤트(기존 `tests/support/fixtures/*.jsonl` + probe 14 런을 0단계에서 다시 캡처)를 주고, **손으로 쓴 기대 마크다운**(샘플 B의 구조)과 비교한다. 정규화 코드를 테스트 대상에 두지 않는다. 자르기 한도는 큰 입력으로.
- **S2 단위 입구(프로세스 안)**: `schedule`의 시각 계산 — 손으로 계산한 표(매일, 평일, `*/15`, 일·요일 OR, 월말, 일회성, DST가 있는 시간대의 건너뛴·겹친 시각)로 이전/다음 발화와 slot; `launchd.calendar_entries` — 손으로 쓴 사전 목록; `github.render_workflow` — `${{`·따옴표·빈 줄·끝 공백·한글 프롬프트(probe 11의 입력과 도착 문자열); `github.parse_spec` — 왕복만으로는 렌더러와 파서가 같은 오해를 나눠 가지므로, **손으로 쓴 워크플로 글**을 입력으로 주고 손으로 쓴 spec과 비교한다(왕복은 그다음); `registry.claim_slot`의 K4 표(걸어 보기 ①~④와 재실행·일회성 26시간이 그대로 테스트 케이스); `claude_cli.activity_rows` — 실측 fixture와 손으로 쓴 행.
- **S3 레이스(실제 프로세스)**: 같은 slot의 `__scheduled run` 둘을 동시에 → 작업자는 하나만; `schedule` 둘을 같은 이름·다른 프롬프트로 동시에 → 워크플로 하나·plist 하나이고 **마지막에 커밋된 본문이 둘 중 한 쪽의 것 전체**(섞이지 않음)이며 plist와 로컬 `definition`이 그 본문과 맞는다; `stop`이 런 게시 직후·감독 생성 직후·`claude` pid 기록 직전에 온 세 경우 모두 가짜 `claude`가 뜨지 않거나 곧 정지된다(K25, PR ⓪).
- **S4 구조·계약**: `test_structure`(위 KINDS·간선), `test_cli_contract`(루트 지도 12개, `__scheduled` 숨김, 새 명령의 `Prints:`·`Exits:`·모든 인자 help), `test_install`(SKILL.md가 가리키는 명령·플래그·필드가 존재, 스킬 폴더에 `references/`가 없음). `runner.problems`: 임시 HOME에 `SessionCreate`가 있는/없는 plist, 토큰이 있는 `.env`, `uv`가 빠진 `.path`를 가진 가짜 러너 디렉터리를 두고 `doctor`·`schedule --dry-run`이 각 문제를 내거나 내지 않는지(S1).
- **PR ①의 보존**: `activity_rows`·`snapshot`으로 옮기기 전에 기존 `test_stream`·`test_observe`가 `log`·`result` 출력을 붙들고 있는지 확인하고, 옮긴 뒤 한 번 일부러 깨서(행 하나를 빼서) 빨개지는지 본다.
- **S5 실제 예약 스모크**(`CLAUDE_SKILL_REAL=1 CLAUDE_SKILL_REAL_GITHUB=1`, haiku; 맨 위 허락의 임시 자원): `schedule` → 웹이 받아들임(`gh workflow list`에 active) → `mode=check` 초록 → 수동 실행 초록·`summary.md`가 기대 구조·런이 레지스트리에 → 2분 뒤 발화하는 디스패처로 정시 실행 → 같은 slot에 `source=dispatcher`를 한 번 더 → 건너뜀 → 긴 작업 중 `gh run cancel` → 런 `interrupted`·summary 있음 → `--worktree` 쓰기 런 → 일회성(`--at` 2분 뒤) → 실행 뒤 `disabled_manually`·plist 없음 → `unschedule` → 워크플로 404·plist 없음 → 자원 정리.
- **S6 헤드리스 e2e**(draft vs control, 가짜 `gh`·`launchctl`을 PATH 앞에 둬 실제 GitHub에 쓰지 않음): ① "매일 새벽 3시에 이 저장소 어제 커밋을 리뷰해 줘" ② "문서 색인을 매주 월요일 9시에 다시 만들어 줘(파일을 바꿈)" ③ "내일 오후 3시에 한 번 테스트 돌려서 알려 줘" ④ 러너가 없는 저장소에서 같은 요청. 측정: 무엇이 커밋·설치되는지 말하고 동의를 구하는가, 프로필을 일에 맞게 고르는가(①·③ read-only, ② write), 프롬프트가 대화 없이 서는가, 응답의 `next` check를 돌리는가, ④에서 `runner.problems`를 사람에게 옮기고 로그인 방식을 대신 고르지 않는가.
- 하지 않는 것: 문장 해시, JSON 키 순서, 내부 함수 모킹, 기본 스위트에서 실제 `gh`·GitHub 호출.

## 단계 (PR별, 완료 판정)

모든 PR: `main`에서 브랜치 → 결정 하나에 커밋 하나(경로 명시 스테이징) → 푸시 → PR(본문 `## 무엇을 바꿨나`/`## 왜`/`## 영향`/`## 검증`, 제목 `<타입>: <한국어>`) → 리뷰(아래) → `gh pr merge --squash` → `git pull`. 동작은 red 먼저, 구조와 동작은 다른 커밋.

**0. 준비와 재캡처**(커밋 없음, 결과는 PR ② 본문에)
- 심링크 삭제(맨 위). 임시 저장소·러너를 만들고(허락), `tests/support/fixtures/github/`에 넣을 실제 `gh` 응답을 캡처한다(probe 15 목록 + 409·422). probe 14와 같은 런을 한 번 돌려 이벤트 fixture로 캡처한다.
- 남은 실측: (a) 러너 `.env`의 `CLAUDE_CODE_OAUTH_TOKEN`으로 기본 plist에서 작업자가 도는지(성진이 `claude setup-token`을 직접 실행해 줘야 한다 — `AskUserQuestion`으로 요청; 거절하면 `session_create`의 두 번째 `fixes` 문구에 "documented, not verified by this skill"을 붙인다) (b) 러너 `.env`의 PATH가 `.path`를 이기는지(대조 2의 가정) (c) 비활성화된 워크플로의 런을 재실행할 수 있는지(일회성의 재실행이 가능한지 — K4의 재실행 규칙이 닿는 범위) (d) 잡 안에서 `batch --worktree`가 되는지 (e) `::stop-commands::<토큰>` 구간 안의 `::error::x` 줄이 주석이 되지 않고, `::<토큰>::` 뒤의 `::warning::`은 되는지(K21) (f) 같은 이름을 동시에 처음 커밋할 때 진 쪽이 받는 응답(422 `"sha" wasn't supplied`)을 fixture로.
- 완료 판정: fixture가 실제 캡처이고, (a)~(f) 결과가 장부에 추가됨. 결과가 K7·K10·K13·K21을 뒤집으면 성진에게 `AskUserQuestion`.

**PR ⓪ `fix: 시작 중인 런을 멈추면 작업자가 뜨지 않는다`**(K25; 예약과 다른 이유라 먼저, 따로)
- 재현 테스트 먼저(S3의 세 시점: 런 게시 직후, 감독 생성 직후, `claude` pid 기록 직전에 `stop`) → 감독이 `claude`를 띄우기 직전과 pid 기록 직후에 `stop_requested`를 본다.
- 완료 판정: 재현이 고치기 전 빨강(가짜 `claude`가 떠서 일함)·고친 뒤 초록, 스위트 초록, 리뷰 멈춤 조건.

**PR ① `refactor: 활동 해석과 결과 조회를 구조로 연다`**
- `claude_cli.activity_rows`(행: 종류·대상·결과·시각·발췌), `log_lines`는 그 행의 글 렌더링. `observe.snapshot`·`observe.wait_ended`, `result`·`log`는 그것을 렌더링. 동작은 바꾸지 않는다(단위 입구 표의 보존 목록).
- 완료 판정: 스위트가 테스트 수정 없이 초록(수·시간 기록), 일부러 깬 변이(행 하나 빼기, 끝줄 빼기)에서 빨강, 실제 claude로 `start`→`result`→`log` 한 바퀴와 스키마 런·그룹 `result`의 출력이 머지 전과 글자 그대로 같음.

**PR ② `feat: 예약된 런을 러너에서 끝까지 실행하고 summary를 쓴다`**
- 새 단위 `schedule/{times,execute,summary}.py`와 `github/job.py`, `registry/schedules.py`, `git/repo.py` 추가분, `__scheduled`, `origin`(runs·batch·`turn_preamble`), 한 명짜리 그룹 문장. 이 PR이 만드는 단위의 등록도 여기서: `KINDS`에 `schedule`·`github`, `FEATURE_EDGES` 셋, `__init__.py` 독스트링. **일회성의 스스로 끄기(K8)는 여기 넣지 않는다** — `github`의 API 입구와 `launchd`가 PR ③에서 생긴다.
- 완료 판정: S1의 `__scheduled`·summary 항목(일회성 끄기 제외)과 S2 시각·slot·`render_summary`가 red→green, S3 slot 레이스, S4 중 이 시점에 있는 것(구조 테스트, 기존 10개 명령의 계약, `__scheduled`가 지도에 숨겨짐 — 12개 지도와 새 명령의 help는 PR ③), 0단계의 임시 러너에서 **손으로 쓴 워크플로**로 수동 실행·취소·시간 초과·건너뜀·재실행·check가 "끝과 종료 코드" 표대로(각 런의 `summary.md`를 PR에 붙임), 리뷰 멈춤 조건.

**PR ③ `feat: schedule과 unschedule로 예약을 걸고 지운다`**
- `github/{api,workflow,runner}.py`, `launchd/`(`KINDS`에 등록), `schedule/{spec,define}.py`, `cli.py`의 두 명령, 가짜 `gh`·`launchctl`, 일회성의 끝(K8: `definition` 비교, 끄기, 디스패처 제거).
- 완료 판정: S1의 `schedule`·`unschedule`·`--list`·일회성 항목과 S2 렌더링·`parse_spec`, S3이 red→green, S4 초록, S5 전 항목 통과, `schedule --help`·`unschedule --help`가 동작과 일치, 리뷰 멈춤 조건.

**PR ④ `feat: doctor가 예약 준비 상태를 보인다`**
- `doctor`의 `schedule` 섹션(K13), help.
- 완료 판정: S1 red→green; 실제로 러너 없는 저장소·기본 plist 러너·고친 러너 세 경우의 `doctor` 출력을 PR에 붙임.

**PR ⑤ `docs: SKILL.md에 예약을 쓴다`**
- `skill-maker`를 `Skill`로 연다. 위 섹션 구조대로 쓰고 S6(4 × 2 세션), `skill-doctor`, 여섯 프로퍼티 리뷰. 성진에게 **전문** 승인(글을 채팅에 보이고 다음 턴에 `AskUserQuestion`).
- 완료 판정: `claude plugin validate --strict "<repo>/.claude/skills"` exit 0, S4 초록, S6의 draft vs control 차이를 문장별 근거로 PR 본문에, 성진 명시 승인.

**PR ⑥ `chore(release): v0.2.0`**
- README·CHANGELOG·SECURITY·CONTRIBUTING·plugin.json·레포 CLAUDE.md. 머지 뒤 태그 `v0.2.0`, `gh release create v0.2.0 --verify-tag --notes-file <파일>`.
- 완료 판정: S5 다시 통과, README의 명령을 실제 실행, `gh release view v0.2.0`, 임시 자원이 남지 않음(`gh repo view` 404, `launchctl print` 없음, `~/Library/LaunchAgents`에 `claude-schedule.*` 없음).

**레포 밖(성진 결정 필요, 구현 세션이 초안을 보이고 승인받은 뒤에만):** 전역 `~/.claude/CLAUDE.md`의 "스킬을 여는 순간"에 예약 라우팅 한 문장(내장 `schedule` 스킬 = 클라우드 루틴, 이 스킬의 `schedule` = 이 맥에서 러너로) — 스킬 자체에는 라우팅을 담지 않는다. 성진의 기존 러너에서 예약을 쓰려면 그 러너의 로그인 설정을 바꿔야 한다는 점을 핸드오프에 적는다(구현 세션은 바꾸지 않는다).

**핸드오프(성진에게):** S5·S6 요약, 아래 "검증되지 않는 것", 넣지 않은 것과 다시 볼 조건, 승인이 여러 실제 세션에서의 성능 증거는 아니라는 점.

## 리뷰 프로토콜 (PR마다)

기본은 `codex` 스킬: `start --sandbox read-only --model gpt-6.1-terra --effort high --schema <repo>/.tmp/review-schema.json --label review-pr<n> --prompt-file <repo>/.tmp/review-pr<n>.md`. 코덱스를 쓸 수 없으면(한도 소진, CLI 장애) 이 스킬 자체로 `start --profile read-only --model opus --effort high …`를 쓰고, **그 경우 다른 모델 계열의 시각이 없다는 점을 PR `## 검증`에 적는다.** 계획 리뷰에서 두 리뷰어가 서로 다른 것을 찾았으므로(리뷰 기록), 공유 계약을 바꾸는 PR ②·③은 가능하면 둘 다 건다.

1. 프롬프트: PR의 목적, `git diff main...HEAD`, 이 PR의 계약과 완료 판정, 이 계획 경로, 소비자가 실제로 받는 것(`--help`, 거부 응답, 실제 `summary.md`, 실제 워크플로 파일), "테스트를 실행해 재현하라". 지적 schema: `{id, file, line, claim, evidence, reachable_in_ordinary_use, violates_contract, severity}`.
2. 지적마다 재현해 판단한다. 계약을 깨면 고친다(동작이면 red 먼저). 기각은 이유와 함께 PR `## 검증`에.
3. 다음 라운드는 같은 세션을 `resume`해 "수정이 버티는가, 수정이 만든 회귀가 있는가"만 묻는다.
4. 멈춤: `reachable_in_ordinary_use`이거나 `violates_contract`인 지적 0. 계획의 결정과 충돌하는 지적은 성진에게 `AskUserQuestion`.

## skill-maker 프레임 대조 (완료 판정에 그대로)

- **Principle over rail**: SKILL.md의 예약 섹션은 사실로 쓴다(무엇이 대화 밖에 남는가, 서비스 안은 대화에서 안 보인다, 작업자가 보는 트리). 무인 규칙은 "known scheduled run이 미리 정하는 것"이라 코드와 help가 고정한다. public 거부(K14)는 사람이 못 보고 못 되돌리는 경우의 금지이고 이유를 함께 말한다.
- **Interface over document**: 플래그·출력·거부·종료 코드는 `schedule --help`·`unschedule --help`, 반쪽 실패는 응답, 준비 상태는 `doctor`와 check 실행. SKILL.md에는 help가 호출 시점에야 읽히는 것 — 호출 전에 계획을 바꾸는 사실 — 만.
- **Model over machinery**: 대조 1·2가 근거(장부). 실행기·summary·워크플로 쓰기는 코드, 러너 설치·런 조작은 모델과 `gh`.
- **For the model**: 실측 경위·probe 번호·성진의 기존 운영은 커밋·PR·CHANGELOG에만.
- **Dense**: 러너 사실은 도구가 판정할 수 있으면 응답이 말하고(K29), SKILL.md에는 호출 전에 계획을 바꾸는 것만; 설치 순서를 베끼지 않는다.
- **Colleague over autopilot**: 무엇을 커밋·설치·게시하는지 이름 붙여 말하게 하고, 로그인 방식·시각·프로필·worktree·변경 가져오기는 사람의 선택으로 남긴다. 결과가 보여 주지 않는 것(셸이 쓴 파일, GitHub의 커밋 ≠ 작업자가 본 트리)은 summary가 말한다.
- **번들 코드 규칙**: 두 최상위 이름, `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py"`, `cli.py`에 결정 로직 없음, 명령별 help가 스스로 출력·실패를 말함, stdout은 결과만, system 단위가 남의 형식을 다 가짐, import 한 방향, 테스트는 스킬 밖, 구조 테스트. 상태 위치는 0.1.0의 합의대로 프로젝트 `.claude-runs/`.
- **완료 조건**: SKILL.md 전문 승인, `claude plugin validate --strict` exit 0, 코드가 제 계약대로·help와 일치·구조 테스트, 다른 모델 계열 리뷰(가능하면)·불가능하면 그 위험을 명시, 개발 기록은 스킬 밖.

## 검증 (전체)

- `python3 -m unittest discover -s tests` exit 0(수·시간을 PR ⑥ 본문에), 구조 테스트 초록, `claude plugin validate --strict` exit 0.
- S5 전 항목(실제 GitHub·실제 러너·실제 launchd), S6 8세션.
- 살아 있는 스킬로: `doctor`의 schedule 섹션, `schedule --dry-run`, `schedule` → check 초록 → 디스패처 정시 실행 → summary를 웹에서 확인 → `resume`으로 이어받기 → `unschedule`.

## 검증되지 않는 것 (핸드오프에)

- 가짜 `gh`·`launchctl` 뒤의 실제 계약은 S5가 한 번 지나갈 뿐이다. GitHub·러너·launchd가 바뀌면 fixture가 낡는다.
- 맥이 잡 도중에 잠들거나 꺼지는 경우(런이 `orphaned`로 남는지, 러너가 다시 붙는지).
- `Finish`가 아예 돌지 못하는 끝(`uv`·스킬 경로 없음, 러너 프로세스 죽음): summary가 없고, 남은 작업자는 러너의 잡 종료 정리에 맡겨진다 — 그 정리는 실측에서 완전하지 않았다(probe 2).
- slot을 차지한 직후 `Run`이 죽고 같은 slot 안에서 상태 파일까지 사라지는 이중 사고(K26).
- 러너가 여러 대(다른 맥)인 저장소: 워크플로의 절대 경로가 한 대에만 맞는다.
- 플러그인 업데이트 뒤의 경로(K3) — `stale_entry` 탐지만 테스트한다.
- DST 전환일의 slot, 사전 수가 많은 cron의 launchd 동작.
- `auto` 프로필의 무인 실행(막지 않지만 설계의 중심이 아니다).
- 수십 번의 실제 예약 실행에서의 품질.

## 범위 밖 (다시 볼 조건과 함께)

- 전용 저장소 하나에 예약을 모으기, GitHub-hosted 러너에서 실행 — 성진이 택하지 않음.
- 러너 설치 명령 — 대조 2에서 기본 모델이 해냄. 다시 볼 조건: `runner.problems`를 보고도 반복해서 틀리는 단계가 보이면. 별도 reference 문서도 같은 조건에서 다시 본다(성진은 두지 않기로 함).
- 작업자가 커밋·푸시·PR까지 하는 예약, 바깥 정보 수집 예약 — 성진이 고르지 않음(프롬프트로 시킬 수는 있다).
- 예약 일시정지·재개 명령(K16), 런 조회·재실행·취소 명령(`gh`).
- Linux·Windows, 여러 시간대, 이름으로 쓰는 cron(`MON`), 5분 미만 간격.
- 성진의 기존 러너·dispatch plist를 이 스킬로 옮기기.

## 부록: 성진이 고른 summary 샘플 B (실제 렌더링에 쓴 원문)

실제 런 `20261117-110035-nightly-docs-f079`(haiku, write)의 값에 Trigger·경로만 예시로 바꾼 것. `summary.py`의 기대 모양이고, 테스트의 기대 마크다운은 이 구조를 따라 fixture별로 손으로 쓴다. 답 본문(`## Probe report` …)은 작업자의 글 그대로다.

`````markdown
# ✅ nightly-docs · completed

| | |
|:--|:--|
| **Run** | `write` · claude-haiku-5-5 / low · 18s · 7 tool calls · $0.01 |
| **Trigger** | dispatcher · slot 2026-11-17 03:00 KST · started 03:00:14 |
| **Local tree** | `main` @ `3bc9e11`, clean when the run began (not the commit GitHub shows for this run) |

> [!WARNING]
> **1 permission denial.** The worker tried something its profile does not allow.
> - `Write` `/etc/claude-probe-denied.txt`

<details><summary><b>Prompt</b></summary>

````text
Do these steps in order, each as its own tool call, then write a short final report …
````

</details>

## Probe report

- **Step 1 (README.md):** Read successfully. …
- **Step 5 (write `/etc/claude-probe-denied.txt`):** **Blocked.** …

Files changed: `docs/notes.md` (new) and `README.md` (one line appended). Nothing was committed, since the task did not ask for it.

---

<details open><summary><b>Changes</b> · 2 files in the project checkout, uncommitted</summary>

```text
 M README.md      +1 −0
?? docs/notes.md  (new, 3 lines)
```

</details>

<details><summary><b>Activity</b> · 7 tool calls</summary>

| # | Time | Step | Detail | Result |
|--:|--:|:--|:--|:--|
| 1 | 0:03 | read | `README.md` | |
| 2 | 0:05 | bash | `ls -la .github/workflows` | exit 0 · 442 B |
| 3 | 0:06 | bash | `python3 -c 'import sys; print("checking"); sys.exit(3)'; echo "exit code: $?"` | exit 0 · 21 B |
| 4 | 0:08 | bash | `grep -ril "timezone" .github; echo "grep exit: $?"` | exit 0 · 85 B |
| 5 | 0:09 | 🚫 denied | `Write` `/etc/claude-probe-denied.txt` | not allowed |
| 6 | 0:11 | write | `docs/notes.md` | |
| 7 | 0:13 | edit | `README.md` | |
| 8 | 0:18 | result | success · 8 turns | $0.0100 |

Started as claude-haiku-5-5 in `acceptEdits` mode · usage limits at start: 5h 5%, 7d 76%

</details>

<details><summary><b>Continue on your Mac</b></summary>

```bash
# ask the same session a follow-up (it remembers this run)
uv run "/Users/seongjin/.claude/skills/claude/scripts/cli.py" resume 20261117-110035-nightly-docs-f079 "…" --project "/Users/seongjin/Coding/project"
# or open the session yourself
cd "/Users/seongjin/Coding/project" && claude --resume d6d0c910-d2e6-460f-8089-a543e0b84073
```

Run `20261117-110035-nightly-docs-f079` · full record in `.claude-runs/20261117-110035-nightly-docs-f079/`

</details>
`````

## 계획 리뷰 기록

두 리뷰어에게 같은 프롬프트와 schema를 줬다(코드와의 대조, 무인 실행의 빈틈, 테스트가 증거인가, 내적 일관성, skill-maker 프레임). 지적마다 코드를 다시 읽어 판단했다.

**claude 작업자**(opus, high, read-only; 런 `20261117-111206-plan-review-8b24`, 세션 `37a9492d-20a6-45b4-988c-f8f3c7056f26`, 레지스트리는 이 레포의 `.claude-runs/`) — 18건, 모두 반영:

| 지적 | 처리 |
|---|---|
| F1 `start()`는 init을 15초 기다린 뒤에야 돌아와 `Run`이 죽으면 런을 놓친다 / F2 `Finish`가 무엇을 근거로 판단하는지 없다, 런 id는 재실행에도 같다 | K19(잡 키에 attempt, 작업자 전 잡 기록, `origin`을 게시 시점 meta에, 두 스텝 같은 플래그) |
| F3 자동 런을 재실행하면 초록 "건너뜀"이 된다 | K4(attempt > 1은 항상 실행, `last_slot` 불변) |
| F4 없는 프로젝트 경로를 레지스트리가 만들어 빈 트리에서 초록 | K23 |
| F5 상태 파일을 잃으면 일회성이 이듬해 다시 돈다, `unschedule`과 살아 있는 런 | K4(26시간), K12(살아 있으면 상태 보존) |
| F6 worktree 그룹 이름 충돌, read-only·커밋 없는 저장소에서 조용히 제자리 | K10(잡 키로 이름, read-only 거부), K23 |
| F7 `Finish` 단계가 앞에서 실패하면 summary가 없다 | K20, "끝과 종료 코드" 표 |
| F8 PR ②가 PR ③의 가짜·입구·KINDS에 기댄다 | 단계 재배치(일회성 끝은 PR ③, 등록은 단위를 만드는 PR에서) |
| F9 시각·summary를 테스트가 부를 입구가 없다 / F10 가짜 `claude`의 timestamp 때문에 서브프로세스 전문 비교가 불가 | 단위 입구(`fire_times`·`current_slot`·`render_summary`, 테스트 시계), S1 summary 항목 |
| F11 git·observe에 필요한 추가가 목록에 없다, snapshot이 스키마 거부를 물려받는다 | 단위 입구(`git` 세 함수, `wait_ended`, snapshot은 예외 없음) |
| F12 `doctor`의 `stale_entry`가 간선을 만든다 | K3(`schedule --list`만) |
| F13 플래그 없는 재호출이 빈 stdin에서 깨진다 | K24 |
| F14 동시 생성에서 진 쪽은 409가 아니라 422 | K12 |
| F15 스키마를 어떻게 싣는지 없다 | K22 |
| F16 작업자 글이 스텝 로그에서 워크플로 명령이 된다 | K21, 0단계 (e) |
| F17 `unschedule`·`--list`를 잡는 테스트가 없다 | S1 |
| F18 프롬프트가 git 이력에 남는다는 사실, `--cron`의 시간대 | SKILL.md 2번, 명령 표면 |

**코덱스**(gpt-6.1-terra, high, read-only; 런 `20261117-112252-plan-review-6e40`, 스레드 `01a1e750-75c3-7201-bf41-5a3a9157310e`, 레지스트리는 이 레포의 `.codex-runs/`) — 14건, 12건 반영·2건은 설계를 바꾸지 않고 한계로 명시:

| 지적 | 처리 |
|---|---|
| F1 pid가 기록되기 전의 정지는 작업자를 못 멈춘다(`stop_one`은 pid가 있어야 신호) | **반영, 기존 결함으로 확인** → K25, PR ⓪ |
| F2 slot 차지 직후 죽고 상태 파일도 사라지면 다시 돈다 | 한계로 명시(K26): 차지 기록은 상태 파일에 남고, 두 사고가 같은 slot 안에서 겹쳐야 한다 |
| F3 런 중에 다시 정의된 일회성을 옛 잡이 끈다 | K8(`definition` 비교) |
| F4 일회성 끄기의 부분 실패와 복구 | K8(따로 기록, 복구 명령) |
| F5 프로젝트 경로가 없을 때 인계·summary 위치, `Finish`가 못 돌 때 | K23, "끝과 종료 코드" 표의 마지막 행(보장 밖을 명시) |
| F6 slot을 실행 시각으로 세면 원래 발화를 가리지 못한다 | 한계로 명시(K26): 불변식은 "slot마다 최대 한 번"이고 횟수는 같다 |
| F7 worktree 그룹의 충돌·부분 생성 | K10(잡 키 이름), K20(정리 실패는 경고) |
| F8 `origin` 전달 경로와 snapshot의 보존 범위 | 단위 입구(runs·batch·observe 행) |
| F9 PR ②가 PR ③에 기댄다 | 단계 재배치 |
| F10 스키마의 수명 | K22 |
| F11 `git status` 차이만으로는 이미 고쳐진 파일의 추가 변경을 못 본다 | K27 |
| F12 `parse_spec` 왕복은 같은 오해를 나눠 가진다, 빠진 실패 경로 테스트 | S2(손으로 쓴 입력), S1·S3 추가 |
| F13 "GitHub가 시계"는 틀린 말, "발화 시점의 체크아웃"도 | SKILL.md 3·4번, description |
| F14 `Finish` 종료 코드가 두 곳에서 다르다 | "끝과 종료 코드" 표 하나로 |

**코덱스 2라운드**(같은 스레드 resume, 런 `20261117-113141-plan-review-2641`; "수정이 버티는가, 두 곳이 어긋나는가"만) — 10건, 모두 반영:

| 지적 | 처리 |
|---|---|
| R1 일회성 read-only 실패는 재시도하기로 했는데 `Finish`가 바로 끈다 | K8(더 시도될 일이 없을 때만 끈다) |
| R2 slot 차지 전 거부는 프로필·횟수와 무관하게 다시 시도된다 | K28(프로젝트 확인 뒤 곧바로 차지, 재시도 규칙 하나로) |
| R3 상태 파일을 잃으면 재시도 기록이 사라진다 | K4(`origin.retry_of`), K26 문구 |
| R4 `unschedule`이 상태를 보존하면 옛 `definition`이 남는다, 비교 직후 경합 | K8(`definition`은 비움, 같은 잠금) |
| R5 충돌한 그룹을 `Finish`가 자기 것으로 알고 정리한다 | K10(매니페스트의 `origin.job`으로 소유 확인) |
| R6 worktree 런의 전후 비교가 다른 트리를 보거나 지운 뒤 비교한다 / R7 stage한 변경의 줄 수 | K27(worktree 기준, 정리 전 스냅숏, `git diff HEAD --numstat`), K20 순서 |
| R8 없는 프로젝트에서 `Finish` 종료 코드 / R9 summary 쓰기 실패의 종료 코드 | K23, K20, 종료 코드 표 |
| R10 PR ②의 S4가 PR ③의 명령에 기댄다 | PR ② 완료 판정 |

**코덱스 3라운드**(런 `20261117-113341-plan-review-6206`) — 2건, 모두 반영: R4-1 지웠다가 같은 spec으로 다시 만들면 해시가 같아 옛 잡이 새 예약을 끈다 → K8(`definition`은 커밋마다 새로 만드는 무작위 식별자). R9-1 `meta.json`이 깨진 경우의 `Finish` 종료 코드가 K20과 S1에서 다르다 → K20·종료 코드 표("멈췄음을 확인하지 못함"에 포함, exit 1).

**코덱스 4라운드**(런 `20261117-113434-plan-review-fa96`) — 지적 0건: "R4-1과 R9-1은 수정됐으며, 확인한 범위에서 같은 결과에 대한 추가 충돌은 발견하지 못했습니다." 멈춤 조건(수정이 버티고 두 곳이 어긋나지 않음)에 닿아 여기서 멈췄다. 2~4라운드는 좁은 질문이었으므로 "빠진 영역이 없다"의 증거는 아니다. claude 작업자는 1라운드만 했고 그 뒤의 수정(K19~K28)은 보지 않았다.

두 리뷰가 독립적으로 같은 곳을 짚은 것: `Run` → `Finish` 인계, PR ②·③의 의존, 스키마, 상태 파일 손실. 코덱스만 찾은 것: 기존 `stop`의 시작 중 결함, 일회성의 정의 식별, Changes 계산의 한계, "시계" 표현.
