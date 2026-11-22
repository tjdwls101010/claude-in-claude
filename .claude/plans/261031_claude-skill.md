# claude 스킬 0.1.0: 클로드 작업자를 관리되는 서브에이전트로

> **구현 세션 첫 동작:** 하네스가 만든 심링크 `.claude/plans/users-seongjin-coding-claude-in-claude-wise-panda.md`(이 파일을 가리킴)를 지운다. 이 파일(`261031_claude-skill.md`)만 보고 구현한다. 이어서 `ToolSearch("select:TaskCreate,TaskUpdate,TaskList")`로 트래커를 열고 아래 "단계"를 태스크로 만든다(description = 그 단계의 완료 판정). `coding`·`codex`·`skill-maker` 스킬은 `Skill`로 연다.

## Context

성진은 대부분의 일을 클로드로 한다. 네이티브 서브에이전트·에이전트 팀·다이나믹 워크플로우는 진행을 오케스트레이터가 들여다볼 수 없고, 여러 개를 띄워 각각 추적할 수 없으며, 작업자가 권한 대기·질문·API 재시도 등으로 멈춰도 오케스트레이터가 알아차리지 못하고 무한정 기다린다. 성진이 전에 만든 `codex` 스킬은 Codex CLI에 대해 같은 문제를 풀었다(분리 감독 프로세스, 즉시 돌려주는 핸들, 압축 이벤트 로그, `result --wait` 한 호출 대기, resume·stop·batch·worktree).

이 계획은 같은 능력을 **클로드 작업자**에게 주는 새 스킬 `.claude/skills/claude`를 **처음부터** 만든다. 오케스트레이터 클로드가 설치된 `claude` CLI를 헤드리스(`-p`, stream-json 입출력)로 띄우고, 스킬의 감독 프로세스가 stdin·stdout을 붙들어 핸들·진행 추적·방향 전환(`send`)·정지·이어 시키기·그룹 실행을 제공한다. 작업자는 성진의 클로드 환경을 그대로 물려받되, 권한은 스킬이 정한 프로필로 매 턴 고정한다. 인증은 성진의 구독 로그인 그대로다. 성공 기준은 퀄리티 하나다. 코드는 `https://github.com/tjdwls101010/claude-in-claude`(public, 비어 있음)에 플러그인으로 둔다.

## 합의 장부

실측은 이 계획 세션의 scratchpad(`/private/tmp/claude-501/-Users-seongjin-Coding-claude-in-claude/80986063-4487-4f17-8110-da6ed935907f/scratchpad/`)에서 haiku로 했다(`exp1`~`exp17`, 프로브 스크립트 `scripts/`; scratchpad는 세션이 끝나면 사라질 수 있으므로 S1 fixture는 PR ①에서 다시 캡처해도 된다 — 같은 프로브로). 구현 세션은 이 값을 기대값의 출처로 쓴다(구현에서 끌어낸 값이 아님).

| 구분 | 내용 | 출처 |
|---|---|---|
| 결정 | 목표 = 위 Context(오케스트레이터가 클로드 세션을 관리되는 서브에이전트로: 백그라운드 시작→핸들→압축 로그→결과(텍스트/스키마)→이어 시키기→멈추기·방향 바꾸기→그룹; 멈춤을 알아차림; 구독 로그인; 퀄리티 기준; skill-maker 레이아웃) | 성진 |
| 결정 | 실행 방식 = 설치된 `claude -p --input-format stream-json --output-format stream-json --verbose`를 스킬의 분리 감독 프로세스가 붙든다. Agent SDK·`claude --bg`는 쓰지 않는다 | 성진(클로드 추천) |
| 결정 | 권한 프로필 세 개 `read-only`·`write`·`auto`, 기본 `write`. bypass 없음. 프로필은 매 턴 argv로 재주입 | 성진(클로드 추천) |
| 결정 | 환경 = **사용자 환경 전부**(전역 CLAUDE.md·사용자 스킬·훅·플러그인·claude.ai 커넥터·auto memory). `--setting-sources`로 끊지 않는다. 단 부모 세션의 정체성 환경변수는 지운다(판단 J7) | 성진(클로드 추천은 "프로젝트만"이었음) |
| 결정 | 작업자의 git은 호출자 몫: 작업자 상황 설명에 "프롬프트가 시키지 않는 한 커밋·브랜치·푸시·PR·머지는 하지 말고 바꾼 것을 최종 메시지에" | 성진(클로드 추천) |
| 결정 | 작업자는 작업자를 못 띄운다(재귀 금지). 다른 위임 도구 사용은 작업자 환경(전역 규칙)에 맡긴다 | 성진(클로드 추천) |
| 결정 | `--model`·`--effort`를 주면 그 값, 안 주면 스킬 고정 기본값 `sonnet`·`high`(성진 settings.json의 model·effort를 따르지 않음) | 성진 |
| 결정 | **처음부터 새로 쓴다.** codex 스킬(`/Users/seongjin/Coding/codex in claude`)은 구조·계약·알려진 함정의 참고일 뿐, 코드를 복사하지 않는다 | 성진(클로드 추천은 복사 후 재설계였음) |
| 결정 | **codex 스킬과 독립.** 코드·의존성·description·SKILL.md·README 어디에도 codex를 언급하지 않고, 다른 위임 도구와의 라우팅("언제 무엇을")도 담지 않는다. 네이티브 `Agent`·`Workflow`로 하던 일을 이 스킬 호출로 옮기는 대응표는 사용법이므로 둔다 | 성진 |
| 결정 | 새 기능은 `send`(살아 있는 런에 메시지 주입)와 한도·재시도 표시(rate_limit·api_retry·`/usage`)만. `--max-turns`·`--max-budget-usd`·fork·`--agent`·이미지 플래그·단일 런 worktree는 넣지 않는다. 거부된 호출(permission_denials)과 스키마 결과는 기본 | 성진 |
| 결정 | batch 격리 = Claude 내장 `--worktree`(`.claude/worktrees/<이름>`, 브랜치 `worktree-<이름>`). 남는 worktree·잠금·빈 브랜치 정리는 스킬의 `clean` | 성진(클로드 추천) |
| 결정 | 레지스트리 = 저장소 본 체크아웃의 `.claude-runs/`(스스로 `.gitignore` `*`), 비 git이면 그 디렉터리 | 성진(클로드 추천) |
| 결정 | 배포 = 플러그인(`.claude-plugin/plugin.json`·`marketplace.json`, README·CHANGELOG·CONTRIBUTING·LICENSE Apache-2.0, v0.1.0 태그·GitHub 릴리스). 개발 중 `~/.claude/skills/claude` 심링크 | 성진(클로드 추천) |
| 결정 | SKILL.md는 영어, description에 한국어 트리거 | 성진(클로드 추천) |
| 결정 | 작업자의 백그라운드 작업은 끈다: env `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`, `BASH_DEFAULT_TIMEOUT_MS=600000`(`timeout`을 안 준 명령도 10분까지 — 기본 2분이면 백그라운드가 없어 그냥 끊김), `BASH_MAX_TIMEOUT_MS=3600000`(`timeout`을 주면 전경에서 최대 1시간). "턴이 끝나면 런이 끝난다"가 성립해 `result --wait`가 작업자의 답과 함께 돌아온다 | 성진(클로드 추천) |
| 결정 | batch `--worktree` 멤버는 호출자의 로컬 HEAD에서 시작(`worktree.baseRef: "head"`). 미커밋 변경은 없고 그 수를 멤버에게 알린다 | 성진(클로드 추천) |
| 결정 | 실제 한도를 쓰는 검증: S5는 haiku 작업자, S6는 오케스트레이터 sonnet·시나리오 프롬프트로 작업자 haiku | 성진(클로드 추천) |
| 결정 | **`result --wait`는 주의가 필요하면 일찍 돌아온다**: 런이 끝났거나, 새 이벤트가 10분(600초) 없거나, API 재시도가 2분 넘게 이어지거나, 한도가 거부(`rejected`)되면. 응답에 `attention`(이유·진행 중 도구·경과·재시도 정보)과 같은 대기를 다시 거는 `next` | 성진(클로드 추천, 코덱스 F1) |
| 결정 | 작업자에서 Monitor를 금지한다(모든 프로필 argv에 `--disallowedTools Monitor`). 기다림·감시는 전경 명령(최대 1시간)이나 오케스트레이터의 `result --wait` attention으로 | 성진(클로드 추천, exp14) |
| 결정 | 작업자에서 턴 밖으로 영향을 남기는 도구도 금지: `SendMessage`(레지스트리를 거치지 않는 세션 간 메시지 — "작업자 간 대화 없음" 결정과 일관), `PushNotification`(성진 기기 알림), `CronCreate`·`RemoteTrigger`(런 뒤에도 남는 예약·클라우드 루틴). 나머지 사용자 환경은 그대로 | 성진(클로드 추천, exp17) |
| 결정 | 에이전트 팀류 기능(작업자끼리 직접 대화·공유 작업 목록)은 넣지 않는다 — 네이티브 팀은 `-p`에서 팀원을 만들지 않고, 작업자 간 조율은 오케스트레이터 밖에서 일어나 추적을 약하게 한다. 토론은 라운드(batch → 수집 → 서로의 발견을 넣어 resume)로. SKILL.md 대응표에 "teammates messaging each other → not available; run rounds" 한 줄. 다시 볼 조건: 라운드로 안 되는 실제 일이 생겼을 때, 그룹 안 레지스트리 경유 `send`부터 | 성진(클로드 추천) |
| 결정 | 레포 밖: 구현 세션이 `~/.claude/settings.json`에 이 스킬의 권한 규칙 두 줄을 넣는다. 전역 CLAUDE.md의 라우팅은 "위임·검증 기본값은 codex, 성진이 명시적으로 요청하거나 codex를 쓸 수 없을 때 claude" — 구현 세션이 그 문장을 초안으로 보여 승인받은 뒤 고친다 | 성진 |
| 결정 | **프로필 예외는 알리고 실행**: 적용되는 설정 파일(사용자·프로젝트·로컬·관리)에서 `sandbox.excludedCommands`, `sandbox.filesystem.allowWrite`, `sandbox.network.allowedDomains`, `WebFetch(domain:…)` 허용 규칙(샌드박스 명령의 허용 도메인에도 더해짐 — settings-reference.md "adds … `WebFetch(domain:...)` allow … rules to the network domain lists"), `permissions.additionalDirectories`(샌드박스 쓰기와 `acceptEdits` 자동 승인을 그 디렉터리로 넓힘 — sandboxing.md, permission-modes.md), 작업자 env를 덮는 settings `env`의 `BASH_DEFAULT_TIMEOUT_MS`·`BASH_MAX_TIMEOUT_MS`·`CLAUDE_CODE_DISABLE_BACKGROUND_TASKS`(settings `env`가 셸 값보다 우선 — settings-reference.md), `sandbox.enabled: false`(관리 설정), cwd 밖 `Edit`·`Write` 허용 규칙을 찾아 `start`·`resume`·`batch` 응답과 `doctor`에 `profile_exceptions`로 나열. help는 "프로필은 네 설정 위에 거는 제한"이라고 말한다 | 성진(클로드 추천, 코덱스 F5) |
| 사실 | 설치: claude 2.1.314, uv 0.8.0, python3 3.14.8, macOS(Darwin 25.5). `claude auth status`: `authMethod: claude.ai`, `subscriptionType: max` | 실측 |
| 사실 | 세션 안(Bash 도구, `CLAUDECODE=1`)에서 `claude -p` 중첩 실행이 된다. haiku 짧은 작업 약 5초·$0.004 | exp1 |
| 사실 | 플래그 없이 띄운 `-p` 작업자는 `~/.claude`를 그대로 받는다: `permissionMode: auto`(settings의 `defaultMode`), 스킬 25개, SessionStart 훅 2개(`hook_started`), Orca 플러그인(`CLAUDE_CODE_PLUGIN_DIRS`), claude.ai 커넥터 2개, auto memory 경로. → 스킬은 권한 관련 플래그를 **항상** 명시한다 | exp1 |
| 사실 | `--session-id <uuid>`로 핸들을 시작 전에 정할 수 있고 init·result의 `session_id`가 그 값이다 | exp1 |
| 사실 | stream-json 입력: 한 프로세스에서 여러 턴, 턴마다 `system/init`이 다시 나오고 턴마다 `result`가 하나. stdin을 닫으면 exit 0 | exp2 |
| 사실 | 턴 도중 `{"type":"user",…,"priority":"now"}` → 실행 중이던 도구가 끝난 뒤 그 턴이 `terminal_reason: aborted_tools`로 끝나고 새 지시를 수행 | exp2 |
| 사실 | 턴 도중 프로세스 그룹에 SIGINT → 도구 거부, `result` `subtype: error_during_execution`·`terminal_reason: aborted_tools`, exit 0. 그 세션을 `--resume`하면 이어지고 작업자가 중단 사실을 안다. stdin `control_request` `interrupt`도 같은 결과(닫으면 exit 1). SIGTERM → exit 143, result 없음 | exp3, exp4 |
| 사실 | Claude Code는 전경 `sleep N && …`을 막고(`Blocked: … use Monitor`) 모델이 명령을 백그라운드로 돌릴 수 있다. 백그라운드 완료는 `origin: {kind: "task-notification"}`인 후속 턴과 그 `result`를 만든다. stdin을 닫아도 프로세스는 백그라운드 작업과 후속 턴을 마친 뒤 종료한다. `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`이면 전경에서 돈다 | exp3(close), exp4 |
| 사실 | 오래 걸리는 전경 Bash는 `system/task_started`(`task_type: local_bash`, `is_backgrounded: false`)와 끝날 때 `task_notification`만 내고 그 사이에는 이벤트가 없다 | exp2, exp4 |
| 사실 | `rate_limit_event.rate_limit_info`에 `status`와 `unifiedWindows.five_hour/seven_day.{utilization, resetsAt, status}`가 있다(실측 0.02·0.42) | exp2 |
| 사실 | `-p "/usage"`는 모델을 부르지 않는다(`num_turns: 0`, 비용 0, 약 2초). stream-json에서 assistant 메시지의 `usage_report.rate_limits.limits[]`(`kind` session/weekly_all/weekly_scoped, `percent`, `resets_at`)로 구조화돼 온다 | exp11 |
| 사실 | `--json-schema`는 스트림 입력에서도 턴마다 동작한다(`StructuredOutput` 도구, 턴마다 `result.structured_output`) | exp5 |
| 사실 | `-p --resume`은 모델은 복원하지만 **권한 모드와 스키마는 복원하지 않는다**(user settings 제외 시 `default`, 포함 시 `auto`; tools 31→30). → 프로필·스키마·effort를 매 턴 재주입 | exp5, sessions.md "Permission mode on resume" |
| 사실 | read-only 묶음(`--permission-mode dontAsk --disallowedTools Edit Write NotebookEdit --settings '{"sandbox":{"enabled":true,"autoAllowBashIfSandboxed":true,"allowUnsandboxedCommands":false,"failIfUnavailable":true,"filesystem":{"denyWrite":["<cwd>"],"allowWrite":["~/.cache"]}}}'`): `python3 -m unittest`이 돌아 심은 버그를 FAIL로 보고(tempfile은 샌드박스 TMPDIR `/tmp/claude-501`), `~/.cache` 쓰기·`uv run` 성공, `touch ./x` 거부, curl은 프록시 403(`sandbox_violations`), Write 도구 없음. 트리에 남은 것은 Claude Code가 만든 빈 `.claude/.cc-writes/`뿐. macOS `mktemp`은 TMPDIR를 무시하고 `/var/folders`에 써서 실패 | exp6, exp7 |
| 사실 | write 묶음(`acceptEdits` + 위 샌드박스에서 `denyWrite` 없음): cwd 안 Write·Bash 쓰기 성공, cwd 밖 Write는 거부되어 `permission_denials`에 남음, 네트워크 차단(exit 56) | exp9 |
| 사실 | `auto`(haiku): cwd 밖 쓰기·네트워크가 분류기 승인으로 성공 | exp9 |
| 사실 | 작업자 3개 병렬 약 10초에 모두 완료. `-p` 작업자는 `claude agents --json`에 나오지 않는다 → 추적은 스킬 레지스트리뿐 | exp8 |
| 사실 | `-p --worktree w1`: cwd `<repo>/.claude/worktrees/w1`, 브랜치 `worktree-w1`, git worktree `locked`, `.worktreeinclude`의 `.env` 복사, 본 체크아웃 경로 Write는 차단·worktree로 돌려짐, 본 체크아웃에서 `--resume` → 같은 worktree로 복귀. 끝난 뒤 worktree·잠금·브랜치가 남고 본 레포 `git status`에 `?? .claude/` | exp10, worktrees.md |
| 사실 | `--worktree` 기본 base는 원격 기본 브랜치(`worktree.baseRef: "fresh"`), `"head"`면 로컬 HEAD. 같은 이름이 있으면 새로 만들지 않고 연다 | worktrees.md |
| 사실 | `--permission-prompts none`(v2.1.259+)은 AskUserQuestion을 없애고, 프롬프트로 갈 호출을 거부하며 "다시 시도하지 말라"고 알린다. 거부는 `result.permission_denials`에 | headless.md |
| 사실 | 시스템 프롬프트 플래그 텍스트는 첫 요청 때 세션에 기록되어 resume 후에도 압축 전까지 그대로 쓰인다 | cli-reference.md |
| 사실 | 같은 세션을 두 프로세스가 동시에 이어 쓰면 트랜스크립트가 섞인다 | sessions.md |
| 사실 | 부모 세션이 Bash 하위 프로세스에 내보내는 변수: `CLAUDECODE`, `CLAUDE_CODE_CHILD_SESSION`, `CLAUDE_CODE_SESSION_ID`, `CLAUDE_CODE_MESSAGING_SOCKET`·`_TOKEN`, `CLAUDE_CODE_BRIDGE_SESSION_ID`, `CLAUDE_PID`, `CLAUDE_EFFORT`, `CLAUDE_CODE_SESSION_ATTENDED`, `CLAUDE_CODE_ENTRYPOINT`, `CLAUDE_CODE_EXECPATH`, (Orca) `CLAUDE_CODE_PLUGIN_DIRS` | `env`, env-vars.md |
| 사실 | 성진 settings.json: `defaultMode: auto`, `model: opus[1m]`, effortLevel·modelSettings, Orca 훅이 거의 모든 이벤트에, SessionStart `link_project_history.py`가 `<cwd>/.claude/histories` 심링크를 만든다(worktree에도 생김), `permissions.allow`에 `Bash(curl:*)` 등 | `~/.claude/settings.json` |
| 사실 | 문서: SDK로 만든 제품에 claude.ai 로그인을 쓰지 말라는 경고, `--bare`는 OAuth를 읽지 않음. `-p`는 수정하지 않은 Claude Code를 본인 로그인으로 쓰는 경로 | agent-sdk/overview.md, legal-and-compliance.md, headless.md |
| 사실 | 턴 도중 `priority:"next"` 메시지는 실행 중 도구를 끊지 않고 그 도구가 끝난 뒤 **같은 턴**에서 읽힌다. 그 턴의 result `user_message_uuids`에 두 메시지 uuid가 함께 있다(`user_message_uuid`는 첫 것). 다음 턴의 result는 그 턴 메시지 uuid만 | exp12 |
| 사실 | `--disallowedTools "Skill(claude)" "Skill(claude:claude)"`는 그런 스킬이 없어도 오류 없이 시작한다 | exp12 |
| 사실 | `/usage`는 `--safe-mode --no-session-persistence`에서도 `usage_report`를 준다(훅·플러그인 없이, 턴 0) | 실측 |
| 사실 | write 묶음 + `--worktree w2` + `worktree.baseRef: "head"`: worktree 안에서 `git log`·`git status`·`git diff`·`git add`가 샌드박스 안에서 된다. (원격 없는 저장소라 "head"와 "fresh"의 차이는 이 실측으로 구분되지 않음 → S5에서 원격 있는 저장소로) | exp10 w2 |
| 사실 | 사용자 환경 전부 + read-only 묶음: `Bash(curl:*)` 허용 규칙이 있어도 curl은 샌드박스 안에서 네트워크 거부(`allowUnsandboxedCommands: false`), cwd 쓰기 거부, `~/.claude/settings.json` 읽기 가능, WebFetch(github.com)는 사용자 허용 규칙대로 성공, 사용자 SessionStart 훅이 cwd에 `.claude/histories` 심링크를 만듦(훅은 샌드박스 밖) | exp13 |
| 사실 | 문서: `sandbox.excludedCommands`는 `allowUnsandboxedCommands: false`여도 샌드박스 밖에서 돌고, `filesystem.allowWrite` 같은 배열과 `Edit` 허용 규칙은 설정 범위 사이에서 병합된다 → 사용자·프로젝트 설정이 프로필을 넓힐 수 있다. 성진의 현재 설정에는 `sandbox` 키가 없다 | settings-reference.md, sandboxing.md, `~/.claude/settings.json` |
| 사실 | 백그라운드를 끈 작업자가 Monitor로 20초마다 줄을 내는 명령을 걸고 "STARTED"로 답한 뒤 stdin을 닫아도, 프로세스는 끝나지 않고 약 10분 동안 출력 줄마다 `origin: task-notification` 후속 턴 30개를 돌렸다(감시 대상이 끝날 때까지 계속될 모양, 프로세스 그룹 SIGINT로 정리) | exp14 |
| 사실 | `--disallowedTools Monitor`는 지연 도구인 Monitor를 실제로 없앤다(init tools에 없음, `ToolSearch select:Monitor` → "No matching deferred tools found"). 사용자 환경 작업자에게는 CronCreate·SendMessage·PushNotification 같은 지연 도구가 보인다 | exp17 |
| 사실 | 스트림 입력 `-p`는 첫 메시지를 받기 전에는 SessionStart 훅 이벤트만 내고, `system/init`은 첫 메시지 뒤에 나온다 | exp15 |
| 사실 | `--include-hook-events`: SessionStart·UserPromptSubmit·PreToolUse·PostToolUse·Stop 훅마다 `system/hook_started`·`hook_response`(`hook_event`, `outcome`, `output`)가 나온다(상속된 Orca 훅 포함). 실행 중 턴에 들어온 메시지를 `UserPromptSubmit` 훅이 막으면 `hook_response` 출력에 `decision: block`이 보이고 그 uuid는 어떤 result에도 없다; 자기 턴을 여는 메시지가 막히면 `num_turns: 0`인 success result가 그 uuid와 함께 온다 | exp16 |
| 사실 | `-p` 작업자도 교차 세션 메시징의 inbox 소켓을 열고 목록에 나온다. 기본 inbound는 보류(-p는 승인 대화가 없어 5분 뒤 버림), `--settings`의 `crossSessionInbound: accept`면 받는다. 에이전트 팀은 대화형에서만 팀원을 만들고 `-p`(SDK 포함)에서는 만들지 않는다 | cross-session-messaging.md, agent-teams.md |
| 사실 | 문서: `-p` resume에서 Claude Code가 worktree 재진입을 거부하면(사라진 worktree 제외) resume을 멈추고, stream-json이면 `error_during_execution` result의 `errors`에 이유. `WebFetch(domain:…)` 허용 규칙은 샌드박스 명령의 허용 도메인에도 더해진다 | worktrees.md, settings-reference.md, sandboxing.md |
| 사실 | `-p --input-format stream-json` 세션의 백그라운드 명령 시간 제한은 기본 30분, `timeout`으로 최대 2시간(텍스트 프롬프트 `-p`는 10분). 전경 명령 기본 2분·상한 10분(`BASH_DEFAULT_TIMEOUT_MS`·`BASH_MAX_TIMEOUT_MS`). `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`은 `run_in_background`를 없애고 시간 초과된 명령·서브에이전트·긴 MCP 호출을 백그라운드로 옮기지 않지만 Monitor와 MCP task는 여전히 백그라운드 | tools-reference.md, env-vars.md |
| 사실 | (0단계 a) 최종 작업자 설정 + `BASH_DEFAULT_TIMEOUT_MS=8000`·`BASH_MAX_TIMEOUT_MS=15000`: `timeout` 없는 12초 명령은 8초에 `Exit code 143 / Command timed out after 8s`, `timeout=60000`을 준 25초 명령은 15초에 같은 오류. 둘 다 백그라운드로 옮겨지지 않음 → 600000·3600000이면 10분·1시간까지 전경 | 구현 세션 exp_a |
| 사실 | (0단계 c) 최종 작업자 설정(백그라운드 꺼짐, Monitor 등 금지)에서 `sleep 45 && echo ok`는 막히지 않고 45초 뒤 `ok` → J5에 대기 문장을 넣지 않는다 | 구현 세션 exp_c |
| 사실 | (0단계 d) `{"continue": false, "stopReason": …}` UserPromptSubmit 훅: 턴을 여는 메시지와 실행 중에 보낸 `priority:"next"` 메시지(이번엔 첫 턴이 끝난 뒤 자기 턴으로 처리됨) 모두 `system/informational`의 `prompt_submit_outcome: {kind: "stopped_by_hook", prompt_kept: true, reason}` 뒤에 `num_turns: 0`·`terminal_reason` 없는 success result가 그 uuid와 함께 옴. 문구 `Operation stopped by hook: <reason>` → J1b("필드가 있으면 kind 무관") 그대로 | 구현 세션 exp_d |
| 사실 | (0단계 J11) 문서상 최소 버전: `--permission-prompts` 2.1.259, `user_message_uuids` 2.1.259, 훅이 끝낸 `num_turns: 0` result의 uuid 에코 2.1.265(typescript.md "Before v0.3.265, the success result … lacked it when the turn sent no API request"), `local_command` 2.1.268, `-p` worktree 재진입 거부 result 2.1.260, **`claude -p --resume`로 들어간 worktree에 샌드박스 보호가 적용되지 않던 버그 수정 2.1.314**(changelog) → 하한 2.1.314(검증 버전과 같음). 선택 필드: `startup_failure_reason` 2.1.274, `usage_report` 2.1.273(doctor quota만) | 문서·changelog |
| 사실 | (PR ① 스모크) read-only 묶음에서 `python3 -m unittest -q 2>&1; echo "EXIT=$?"`와 `for f in *.py; do echo $f; done`는 `permission_denied`(reason `mode`, "don't ask mode"), `python3 -m unittest -q`·`cd "<경로>" && …`·`ls \| wc -l`·`echo $HOME`·`echo $(pwd)`·`FOO=1 python3 …`·`… \|\| true`는 실행. `--allowedTools Bash`를 더하면 루프·`$?`도 실행되고 `touch`는 `Operation not permitted`, curl은 프록시 403으로 샌드박스가 그대로 막음 | 구현 세션 실측 |
| 결정 | read-only·write 프로필에 `--allowedTools Bash`(모든 셸 형태를 승인, 경계는 샌드박스). 대가: 사용자 `sandbox.excludedCommands`는 샌드박스 밖에서 승인 없이 돈다(`profile_exceptions`가 보고) | 성진(클로드 추천, 위 실측) |
| 판단 | **J1 런 = `claude -p` 프로세스 하나.** 감독은 첫 프롬프트와 `send`로 넣은 메시지마다 `uuid`를 붙여 stdin에 쓴다. **stdin을 닫는 때**(J2의 같은 잠금 아래, inbox가 비었을 때만): (a) 전달한 모든 uuid가 어떤 result의 `user_message_uuids`에 나타났거나(exp12), (b) 지금까지 본 마지막 result가 task-notification이 아니고 마지막으로 전달한 메시지보다 스트림에서 뒤에 있으며, 그 뒤 **stdout에 `IDLE_GRACE` 10초 동안 아무 줄도 오지 않고, 끝나지 않은 `hook_started`도 없을 때**(result 뒤에 오는 `command_lifecycle`·훅 줄은 유예 시계를 다시 맞출 뿐 (b)를 막지 않는다 — exp12·exp16). 훅 활동을 보려고 모든 턴에 `--include-hook-events`를 넣는다(cli-reference.md; log는 훅 줄을 기본으로 숨김) — 상속된 `UserPromptSubmit` 훅이 느려도(기본 시간 제한 30초) 그동안 `hook_started`가 열려 있어 닫지 않는다. (b)로 닫으면서 어떤 result에도 나타나지 않은 uuid는 meta `unanswered`로 남긴다 — 실행 중 턴에 도착해 `UserPromptSubmit` 훅이 막은 메시지(typescript.md: 그 uuid는 어떤 result에도 없음; 자기 턴을 여는 메시지는 막혀도 `num_turns: 0` result가 온다), uuid 필드 없는 result가 여기로 온다. 64개 상한은 런당 `send`를 16개로 막아 닿지 않게 한다(넘으면 거부, `instead`: 새 `resume`). 대기 중 메시지가 있으면 다음 턴이 즉시 시작하므로(exp2·12) 유예가 정상 흐름을 끊지 않는다. 훅 이벤트는 `UserPromptSubmit`에도 나온다(exp16). (b)의 "이벤트"는 stdout에 오는 모든 줄(훅·`command_lifecycle`·`informational` 포함)이다. 백그라운드 작업이 꺼져 있고 Monitor가 금지돼 있으므로 CLI는 곧 종료하고(남을 수 있는 것은 MCP task — J3), 종료 시 런이 끝난다. 모든 턴의 `--disallowedTools`는 하나의 플래그 뒤에 이름을 모아 넘긴다(프로필의 Edit·Write·NotebookEdit 포함) | 클로드(exp2·12·14, 코덱스 F2·F3·R2-2) |
| 판단 | **J1b 최종 답** = 스트림 순서로 마지막 전달 메시지 **이후**에 온, `origin.kind`가 task-notification이 아닌 마지막 result(그 `result`·`structured_output`·`is_error`). 고른 result가 답한 메시지를 `answered`(uuid와 그 메시지의 앞 80자)로, 어떤 result에도 나오지 않은 메시지를 `unanswered`로 result 헤더에 싣는다. 마지막 메시지가 `unanswered`면 헤더가 `last_message_unanswered: true`를 말하고, 텍스트는 그 전 메시지에 대한 답임을 `answered`가 보여 준다(마지막 send의 답처럼 보이지 않게). uuid 필드가 아예 없는 result면 `answered: null`·`answer_unconfirmed: true`. init 전에 온 error result(`startup_failure_reason` 또는 시작 오류)는 답이 아니라 `failed`의 `error`. **훅이 끝낸 메시지.** 판정 신호는 `prompt_submit_outcome`을 가진 `system/informational`(exp16에서 `kind: blocked_by_hook`; 문서에 없는 필드라 kind 값과 무관하게 이 필드가 있으면 "훅이 끝냄"으로 본다). 그 필드가 없는 CLI·경우의 대비: `local_command`가 없고 그 턴에 assistant 이벤트가 하나도 없는 `num_turns: 0` success result는 `possibly_blocked`로 표시하고 attention을 건다(`/compact`·`/usage` 같은 로컬 명령은 `local_command`와 함께 `num_turns: 0`을 내므로 제외 — typescript.md). uuid 연결: 턴을 여는 메시지는 뒤따르는 `num_turns: 0` result의 `user_message_uuids`로, 실행 중 들어온 메시지는 바로 앞의 `command_lifecycle.command_uuid`로(exp16). 런 판정은 **마지막으로 전달한 메시지**를 기준으로 한다: 그것이 훅에 끝났으면 그 메시지의 result를 답으로 고르지 않고, 앞의 진짜 답이 있으면 그 답과 상태를 유지하며 `last_message_blocked`를 세우고, 진짜 답이 하나도 없으면 `failed`·`error: blocked_by_hook`. 막힌 메시지는 모두 헤더 `blocked_by_hook`(uuid·훅 이유)에. 0단계에서 `continue: false`로 끝내는 훅도 실측해 같은 필드가 오는지 확인한다. task-notification result는 `followups`(개수와 log의 `result … origin=task-notification` 줄)로 따로 | 클로드(exp3, 코덱스 F4·R2-1) |
| 판단 | **J2 `send`.** inbox(레지스트리 런 디렉터리) 넣기와 감독의 "가져가 stdin에 쓰기"·"닫기 결정"은 모두 같은 런 잠금 아래. 닫기는 inbox가 비었고 쓰는 중인 메시지가 없을 때만 → 넣기에 성공한 메시지는 반드시 전달되거나, 감독이 그 전에 죽으면 meta에 `undelivered`로 남는다(`status`가 보여 줌). 닫힌 뒤 오는 `send`는 거부(`instead`: `resume`). 응답은 감독의 전달 기록(uuid·시각·priority)을 최대 10초 기다려 `delivered` true/false. 기본 priority `next`(exp12: 진행 중 도구를 끊지 않고 같은 턴에서 읽힘), `--interrupt`면 `now`(exp2: 턴을 끊음) | 클로드(exp2·12, 코덱스 F3) |
| 판단 | **J3 `finishing`.** stdin을 닫았는데 프로세스가 아직 살아 있으면(Monitor는 금지했으므로 MCP task 등 남은 경로) 상태 `finishing`과 남은 작업(`task_started` 중 끝나지 않은 것)을 보인다. 최종 답(J1b)은 이미 정해졌으므로, `finishing`이 120초를 넘으면 그 자체가 attention(`reason: finishing`) — `result --wait`가 답과 함께 돌아와 오케스트레이터가 기다릴지 `stop`할지 정한다(후속 턴이 이벤트를 계속 내 600초 무활동이 안 걸리는 경우까지 덮음). `stop`·`--timeout`이 끝낸다 | 클로드(코덱스 R2-4, sonnet R4-1, exp14) |
| 판단 | **J4 `start` 응답.** 핸들(`run_id`, `session_id`)은 즉시 정해지지만, 응답은 첫 `system/init` 또는 프로세스 종료까지 최대 15초 기다린 뒤 돌려준다: 시작 실패(인증·잘못된 플래그)를 늦은 실패가 아니라 응답으로, init의 실제 `permissionMode`·`model`·`cwd`(worktree 경로)를 보이기 위해. 요청한 모드와 다르면 `mode_mismatch` | 클로드 |
| 판단 | **J5 작업자 상황 설명.** 고정 사실은 `--append-system-prompt`로 매 턴(기록된 프롬프트와 같은 텍스트라 압축 후에도 같음): 비대화형이라 질문에 답할 사람이 없음(합리적으로 해석하고 가정을 밝힘), 최종 메시지가 호출자가 받는 것, git은 호출자 몫(결정 행), 이 스킬로 작업자를 띄울 수 없음. 배치·worktree 사실(그룹 이름·크기, worktree 경로·기준 커밋·호출자 트리의 미커밋 파일 수)은 그 턴 프롬프트 앞에 붙인다 — resume 때 낡지 않게 | 클로드 |
| 판단 | **J6 재귀 금지.** 감독이 작업자 env에 `CLAUDE_SKILL_RUN=<run_id>`를 넣고, CLI는 그 값이 있으면 `start`·`resume`·`batch`·`send`·`stop`·`clean`을 거부(조회 명령은 허용). 시도 자체를 줄이려고 `--disallowedTools "Skill(claude)" "Skill(claude:claude)"`도 넣는다(exp12: 없는 이름이어도 시작함) | 클로드 |
| 판단 | **J7 작업자 env** = 감독 env에서 부모 세션 정체성만 지움: `CLAUDE_CODE_SESSION_ID`, `CLAUDE_CODE_MESSAGING_SOCKET`, `CLAUDE_CODE_MESSAGING_TOKEN`, `CLAUDE_CODE_BRIDGE_SESSION_ID`, `CLAUDE_PID`, `CLAUDE_EFFORT`, `CLAUDE_CODE_SESSION_ATTENDED`. 더함: `CLAUDE_SKILL_RUN`, `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`, `BASH_DEFAULT_TIMEOUT_MS=600000`, `BASH_MAX_TIMEOUT_MS=3600000`(결정 행; 셸에 더 큰 값이 있으면 덮지 않음; settings `env`가 이 값들을 덮으면 `profile_exceptions`로 보고). `CLAUDE_CODE_PLUGIN_DIRS`·`CLAUDECODE` 등 나머지는 유지(사용자 환경). 호출자 세션 id는 meta `caller_session_id`로 기록 | 클로드 |
| 판단 | **J8 batch worktree.** 멤버 이름 `<group>-<index>`, `--worktree <이름>`과 `--settings`의 `worktree.baseRef: "head"`(결정 행). 대상: 새 시작(resume 아님), 프로필 `write`·`auto`, git 저장소에 커밋이 있음, 멤버에게 자기 `cwd`가 없음. 이름이 이미 있는 worktree면 Claude Code가 그것을 연다(worktrees.md) — 그룹 이름 예약이 살아 있는 동안 재사용되지 않으므로 `clean`이 남긴 worktree와 같은 이름의 새 그룹은 refuse | 클로드(worktrees.md, exp10) |
| 판단 | **J9 `clean`.** 멤버마다: 살아 있으면(J16) 거부하고 `stop` 호출을 줌 → 지울 수 있는지 판정: 추적 파일 변경이 없고, untracked·ignored 항목은 **시작 생성물이거나 `.worktreeinclude` 복사본뿐**이어야 한다(`git worktree remove`는 ignored 파일을 말없이 지우므로). 시작 생성물 = 그 worktree를 만든 **첫 런의 첫 `system/init`**을 감독이 받은 순간(SessionStart 훅은 끝났고 도구 호출은 아직 — exp15·exp16 순서) worktree의 `git status --porcelain --ignored --untracked-files=all` 항목 중 `.worktreeinclude` 복사본(본 체크아웃 같은 경로와 크기·바이트가 같은 ignored 파일 — 따로 판정하므로)을 뺀 것마다(파일 단위; 디렉터리로 접히지 않게) 종류와 내용 해시(링크면 대상)를 그 런의 meta `startup_artifacts`로 **한 번만** 기록한 것(복사본을 빼서 기록이 작고 빠르다 — 기록하는 동안 작업자가 이미 돌고 있으므로 창을 짧게)(사용자 훅의 `.claude/histories` 등 — exp10·exp13). 같은 런의 뒤 턴 init(`send --interrupt` 등)이나 이어 간 런(resume)은 이 기록을 쓰지도 덮지도 않고, `clean`은 그룹 매니페스트의 멤버 첫 런 기록만 읽는다. 각 항목은 기록 뒤 바뀌지 않았을 때만 지울 수 있다. 예외 하나: Claude Code가 첫 샌드박스 Bash 때 만드는 빈 `.claude/.cc-writes/`(exp6·exp13 생성 시각, git은 빈 디렉터리를 보이지 않음)는 비어 있으면 지울 수 있다. 복사본 = 본 체크아웃의 같은 경로 파일과 바이트가 같은 ignored 파일 → 잠금 해제 → `git worktree remove`(조건을 이미 확인했으므로 필요하면 `--force`) → 기준 커밋 이후 커밋이 없으면 브랜치 `worktree-<이름>` 삭제. 남기는 경우는 `kept`에 이유와 경로(ignored는 최상위 디렉터리 단위로 요약). `--force`는 미커밋·untracked·ignored 변경을 버린다. 커밋이 있는 브랜치는 어떤 경우에도 지우지 않고 이름을 알려 준다. 다 지워지면 그룹 이름 해제 | 클로드(코덱스 F6) |
| 판단 | **J10 상태.** 저장: `starting` `running` `finishing` `completed` `failed` `interrupted` `timed_out` `orphaned`. 표시용 파생: `retrying`(마지막 이벤트가 `system/api_retry`; 감독이 재시도 연속 구간의 시작 시각을 meta `retrying_since`에 기록), `stalled`(끝나지 않은 모든 상태 — `starting`·`running`·`finishing` — 에서 마지막 이벤트 후 `STALL_SECONDS` = 600초, 권고일 뿐 아무것도 죽이지 않음 — `in_progress` 도구와 함께). `attention`(결정 행의 일찍 깨우기) = `stalled` 또는 `retrying_since` 후 120초 또는 최신 rate_limit `status: rejected` 또는 `finishing` 120초(J3); 같은 상태로 다시 깨우지 않도록 `--wait`는 시작 시점에 이미 걸린 attention은 무시하고 새로 생긴 것만 본다(이미 stalled인 런을 다시 기다리면 다음 10분 동안 이벤트가 없을 때 다시 깨움). `failed`는 종료 코드≠0 또는 마지막 주 스레드 result가 `is_error`/`subtype≠success`, `error`에 result의 `errors`·`api_error_status`·`terminal_reason` 요약 | 클로드 |
| 판단 | **J11 버전 하한.** 하한 = 스킬이 **의존하는** 플래그·필드의 문서상 최소 버전 중 최댓값. 지금 아는 것: `--permission-prompts` v2.1.259, `user_message_uuids` v2.1.259(SDK v0.3.N = CLI v2.1.N, typescript.md), `-p` worktree 재진입 거부 result v2.1.260 → **적어도 2.1.260**. 0단계에서 argv의 모든 플래그(`--include-hook-events` 등)와 파서가 의존하는 모든 필드를 문서에서 "Requires Claude Code v…"/"Agent SDK v0.3.…"로 찾아 값을 확정해 `claude_cli`에 상수로. `startup_failure_reason`(v2.1.274)처럼 있으면 쓰고 없어도 되는 필드는 하한에 넣지 않고 선택 필드로 파싱. 하한 미만이면 런을 만들기 전에 거부하고 `doctor` blocker, 검증 버전(2.1.314) 미만은 `doctor` 경고 | 클로드(headless.md, typescript.md, worktrees.md) |
| 판단 | **J12 한도.** `doctor`가 `claude -p --safe-mode --no-session-persistence --output-format stream-json --verbose /usage`로 신선한 한도를 읽는다(safe-mode는 훅·플러그인을 띄우지 않는다; 실측으로 동작 확인). `status`는 감독이 이벤트에서 기록한 최신 `rate_limit` 값을 비용 없이 보인다(관측 시각과 함께) | 클로드(exp2, exp11) |
| 판단 | **J13 노출하지 않는 것:** `models` 명령(카탈로그 CLI가 없음 — `--model`은 그대로 넘기고 잘못된 모델은 작업자의 `model_not_found` 실패로 보임), resume `--force`(살아 있으면 `send`), `--add-dir`·`--name`·`--fork-session` | 클로드 |
| 판단 | **J14 `files_edited`** = Edit·Write·NotebookEdit 호출 중 오류 아닌 결과의 경로. Bash가 쓴 파일은 보이지 않음을 help와 헤더가 말한다(worktree 멤버는 `clean` 전 `git status`로 확인할 수 있음을 note로) | 클로드 |
| 판단 | 런의 기본 작업 디렉터리 = 현재 체크아웃의 git 최상위(비 git이면 현재 디렉터리), `--cwd`로 바꿈. 레지스트리는 본 체크아웃(worktree에서 불러도 하나) | 클로드(codex 0.11에서 배운 함정) |
| 판단 | **J16 살아 있음** = 저장 상태가 끝이 아니거나, 끝(특히 `orphaned`)이어도 기록된 claude pid가 같은 pgid로 아직 살아 있음(`still_writing`, pid 재사용은 pgid로 거름). `resume`·`clean`·같은 세션의 새 런은 살아 있는 런이 있으면 거부. `send`는 반대로 **감독이 살아 있고 stdin이 열린** 런에만 받는다. 거부의 `instead`는 상태로 정해 서로를 가리키지 않게 한다: `resume` 거부 — 감독이 살아 있고 stdin이 열렸으면 `send`, 그 밖의 살아 있는 런(`finishing`·orphan)이면 `stop` 후 `resume`; `send` 거부 — 끝난 런이면 `resume`, `finishing`이면 `result --wait`(답은 이미 있음) 또는 `stop` 후 `resume`, orphan이면 `stop` 후 `resume`. `stop`은 orphan의 프로세스 그룹도 신호한다. 감독이 죽은 런의 상태 기록은 compare-and-set(감독이 쓴 진짜 결과가 이김) | 클로드(코덱스 F7) |
| 판단 | **J17 worktree 멤버의 resume.** meta에 실행 디렉터리(`launch_cwd`, 본 체크아웃)와 worktree 경로를 따로 기록. resume은 `launch_cwd`에서 실행하고(Claude Code가 worktree로 복귀, exp10), 기록된 worktree가 없어졌거나 git이 그것을 worktree로 모르면 **거부**(worktrees.md: 사라진 worktree면 실행 디렉터리에서 조용히 재개됨 → 격리 깨짐; `instead`: 새 `start`). 존재하지만 Claude Code가 재진입을 거부하는 경우는 `-p`에서 Claude Code가 스스로 resume을 멈추고 `error_during_execution` result를 낸다(worktrees.md "-p … stops the resume … except a gone worktree") → `failed`. init은 첫 메시지 뒤에야 나오므로(exp15) 그 전에는 cwd를 확인할 수 없다: init의 `cwd`가 기록된 worktree와 다르면 감독이 즉시 `stop` 사다리로 끝내고 `failed`·`error: cwd_mismatch`로 기록하며, 오류 문구가 "SessionStart 훅과 첫 도구 호출이 실행 디렉터리에서 이미 돌았을 수 있음"을 말한다. **보장 범위:** 사전 검사와 시작 사이에 이 스킬의 `clean`이 worktree를 지우는 경합은 막힌다(새 런은 spawn 전에 세션 잠금 아래 게시되고, `clean`은 살아 있는 런의 worktree를 지우지 않음). 스킬 밖의 무엇이 그 몇 초 사이에 worktree를 지우는 경우는 막지 않고 위 오류로만 알린다 | 클로드(코덱스 F8·R2-5·R3-3) |
| 판단 | 테스트는 레포 `tests/`, 러너 `unittest`(stdlib), 스킬 코드는 stdlib만(PEP 723 `requires-python >=3.11`, `dependencies = []`). 개발 기록은 커밋·PR·CHANGELOG, 계획 파일은 커밋하지 않는다 | 클로드(codex 선례) |
| 판단 | 이 계획은 승인 전에 코덱스(gpt-6.1-terra, high, read-only)가 리뷰한다(아래 "계획 리뷰 기록") | 클로드 |

## 아키텍처

```
오케스트레이터 클로드 ── Bash: uv run ".../cli.py" start …  ──▶ 응답 {run_id, session_id, state, next}
        │                                                         (next = result --run <id> --wait, 백그라운드로)
        │                 ┌──────────── 분리 감독 (cli.py __supervise --run-dir) ────────────┐
        │                 │  새 세션 리더(프로세스 그룹) · meta.json 갱신 · 마감 시각          │
        │   send ──▶ inbox ─▶ stdin ─▶ claude -p --input-format stream-json                │
        │                 │                    --output-format stream-json --verbose         │
        │                 │                    --session-id|--resume · 프로필 · 모델 · effort  │
        │                 │          stdout ─▶ events.jsonl (감독이 읽으며 result·init·        │
        │                 │                    rate_limit·api_retry를 meta에 반영)             │
        │                 │          stderr ─▶ stderr.log                                     │
        │                 └──── 보낸 메시지가 모두 답해지면 stdin 닫기 → 종료 → 상태 기록 ─────┘
        └── status · log · result (--wait) · stop(SIGINT→SIGTERM→SIGKILL, 프로세스 그룹) · batch · clean · doctor
```

## 구현 후 디렉터리 구조

```
claude in claude/                        (레포 = 플러그인 루트)
├── .claude/
│   ├── skills/claude/                   ← ~/.claude/skills/claude 심링크 대상, 플러그인 skills 루트
│   │   ├── SKILL.md                     # 한 파일, 영어. references/·data/ 없음(아래 SKILL.md 절)
│   │   └── scripts/
│   │       ├── cli.py                   # 유일한 진입점(PEP 723). 파서·help(Prints:/Exits:)·인자만으로 하는 검사·분기·출력·종료 코드
│   │       └── claude/                  # 유일한 패키지. __init__.py 독스트링 = 트리 지도
│   │           ├── runs/                # feature: start·resume·send·stop + 런 엔진
│   │           │   ├── __init__.py      # 입구(__all__)
│   │           │   ├── commands.py      # start / resume(REF 해석) / send / stop, 응답의 next
│   │           │   ├── settings.py      # 프로필·model·effort·schema·cwd: 플래그 > 세션 기록 > 스킬 기본
│   │           │   ├── create.py        # 거부(비용 0) → 세션 잠금 안에서 게시 → 감독 spawn → init 대기
│   │           │   └── supervisor.py    # claude 실행·stdout 펌프·inbox 전달·stdin 닫기 규칙·마감·결과 기록, 신호 사다리
│   │           ├── batch/               # feature: batch·clean (→ runs: 유일한 기능 간 간선)
│   │           │   ├── __init__.py
│   │           │   ├── commands.py
│   │           │   ├── tasks.py         # --task / --tasks-file(JSONL) 검증
│   │           │   ├── spawn.py         # 멤버 생성, worktree 이름·대상 판정
│   │           │   └── clean.py         # J9
│   │           ├── observe/             # feature: status·log·result
│   │           │   ├── __init__.py
│   │           │   ├── rows.py          # 런 행, 파생 상태(retrying·stalled), 그룹 상태
│   │           │   ├── status.py
│   │           │   ├── log.py
│   │           │   ├── result.py        # 런·그룹, --schema, --wait
│   │           │   └── wait.py          # result --wait의 침묵 대기
│   │           ├── doctor.py            # feature: doctor
│   │           ├── claude_cli/          # system: Claude Code가 소유한 형식 전부
│   │           │   ├── __init__.py
│   │           │   ├── argv.py          # 프로필 → 플래그, start/resume argv, 작업자 env(J7), 상황 설명 텍스트(J5), worktree 이름→경로·브랜치(J8)
│   │           │   ├── stream.py        # stdin 메시지 인코딩(uuid·priority), stdout 이벤트 해석: 요약·log 줄·result·init·rate_limit·api_retry·task
│   │           │   └── install.py       # claude --version·하한(J11), auth status, 샌드박스 전제, /usage 한도(J12)
│   │           ├── git/                 # system: git CLI
│   │           │   ├── __init__.py
│   │           │   ├── repo.py          # 최상위·본 체크아웃(worktree list --porcelain 첫 기록; bare·서브모듈 예외)·미커밋 수
│   │           │   └── worktree.py      # list·unlock·remove·기준 이후 커밋 수·브랜치 삭제
│   │           ├── registry/            # store: <본 체크아웃>/.claude-runs
│   │           │   ├── __init__.py
│   │           │   ├── runs.py          # run 디렉터리 claim, meta 원자 쓰기·CAS, reap(감독 사망 → orphaned), 세션 찾기
│   │           │   ├── groups.py        # 매니페스트 claim(이름 예약)·멤버 기록·해제
│   │           │   ├── inbox.py         # send 큐: 넣기·가져가기·닫기(런 잠금 아래)
│   │           │   └── locks.py         # flock, 원자 JSON 쓰기
│   │           ├── errors.py            # Refusal(인자 문제인지 여부 포함)
│   │           └── util.py              # 시간·텍스트 자르기·NFC·pid 생존(pgid 확인)·자기 호출 문자열
├── tests/                               # 스킬 밖. 단위 입구(+ cli.build_parser)만 import
│   ├── support/{harness.py, fake_claude/claude, fixtures/*.jsonl}
│   ├── test_structure.py test_cli_contract.py test_install.py
│   ├── test_argv.py test_stream.py test_settings.py test_git.py test_registry.py
│   ├── test_run_lifecycle.py test_send.py test_resume.py test_stop.py
│   ├── test_observe.py test_batch.py test_clean.py test_doctor.py test_races.py
│   ├── smoke_real_claude.py             # S5 (CLAUDE_SKILL_REAL=1)
│   └── e2e/{scenarios.md, run_e2e.py}   # S6
├── .claude-plugin/{plugin.json, marketplace.json}
├── README.md CHANGELOG.md CONTRIBUTING.md LICENSE SECURITY.md CLAUDE.md(→ AGENTS.md 심링크)
└── .gitignore                           # .tmp/ .claude-runs/ .claude/plans/ .claude/histories .claude/worktrees/ __pycache__/ *.py[cod] .DS_Store
```

`.claude-runs/<run_id>/`: `meta.json`, `events.jsonl`(stdout 그대로), `stderr.log`, `supervisor.log`, `inbox/`. `.claude-runs/.groups/<name>.json`, `.claude-runs/.locks/`. 런 id = `YYYYMMDD-HHMMSS-<label|run>-<4hex>`. 세션 id = 감독이 아니라 `create`가 정하는 uuid4.

## 명령 표면 (0.1.0)

최상위 10개 + 숨긴 `__supervise`. 모든 명령은 stdout에 JSON 한 줄(또는 help가 말하는 텍스트), 종료 코드 0 성공 / 1 상태가 거부했거나 요청한 일이 실패(`error`) / 2 명령줄을 바꿔야 함(`error`+`help`) / 3 `doctor` blocker. 모든 호출은 `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" <command> …`.

| 명령 | 인자 | 출력 요지 |
|---|---|---|
| `start` | `[PROMPT]`(또는 `--prompt-file`·stdin), `--profile {read-only,write,auto}`(기본 write), `--model`(기본 sonnet), `--effort {low,medium,high,xhigh,max}`(기본 high), `--schema FILE`, `--timeout SEC`, `--label`, `--cwd`, `--project`, `--runs-dir` | `run_id`, `session_id`, `state`, `next`, `profile`, `permission_mode`(init 실제값), `mode_mismatch`, `model`, `cwd`, `concurrent_writers`(같은 디렉터리의 살아 있는 쓰는 런), `events` |
| `resume` | `REF PROMPT`(PROMPT는 위치 인자·`--prompt-file`·stdin 중 하나로 **필수** — 비면 exit 2), 위와 같은 설정 플래그(주면 그 턴부터 바뀌어 기록), `--profile`은 레지스트리에 없는 세션이면 필수 | start와 같음 + `profile_changed_from`. 세션에 살아 있는 런이 있으면 거부(`instead`는 J16의 상태별 규칙) |
| `send` | `REF MESSAGE`(또는 `--message-file`), `--interrupt` | `run_id`, `message_uuid`, `priority`, `delivered`. 끝난 턴이면 거부(`instead`: `resume`) |
| `batch` | `--group NAME`, `--task …`(반복) \| `--tasks-file JSONL`(필드: prompt, kind start\|resume, resume, label, profile, model, effort, schema, cwd), `--worktree`, 그룹 기본값 플래그들 | `group`, `spawned`, `requested`, `next`(result --group --wait), `runs[]`(멤버별 run_id·state·cwd·worktree·profile·error), `worktrees` 설명 |
| `status` | `[--run REF \| --group NAME]` | 목록(살아 있는 런 전부 + 최신 20, `runs_truncated`, `groups`, 최신 `rate_limit`) / 런 전체 행 / 그룹 행들·`group_state` |
| `log` | `--run REF` | 텍스트(아래 log 형식), 끝줄 `run=<id> state=<state>` |
| `result` | `--run REF \| --group NAME`, `--wait`, `--wait-timeout SEC` | `--wait`는 끝나거나 attention(결정 행)이 새로 생기면 돌아온다 — 그때 헤더에 `attention`과 같은 대기의 `next`. 런: JSON 헤더(`state`, `exit_code`, `error`, `attention`, `answered`, `unanswered`, `last_message_unanswered`, `permission_denials`, `files_edited`, `tool_calls`, `usage`, `cost_usd`, `followups`, `profile_exceptions`, `message_bytes`, 진행 중이면 `note`) + 최종 메시지 텍스트(J1b). `--schema` 런: 들여쓴 JSON 한 문서(`json` = J1b가 고른 result의 `structured_output`, 살아 있으면 null, 끝났는데 없으면 거부). 그룹: 헤더(`group_state`, `overlaps`, `totals`, `members`, attention이 생긴 멤버 목록) + 멤버별 `--- [i:label] run=… state=… bytes=…` 구분선과 4000B로 자른 메시지. 그룹 `--wait`는 모든 멤버가 끝나거나 어느 멤버에게든 attention이 새로 생기면 돌아온다 |
| `stop` | `--run REF …` \| `--group NAME` | 런마다 `signals_sent`, `state`, `session_id` |
| `clean` | `--group NAME`, `--force` | `removed`, `kept`(이유·`occupied_by`·남긴 브랜치), `name_released` |
| `doctor` | — | `ok`, `blockers`, `warnings`, claude 경로·버전·하한, `auth`(loggedIn·authMethod·subscription), 샌드박스 전제, `quota`(/usage), `skill_dir`, 레지스트리·살아 있는 런·남은 worktree, 상속 환경 주의(`defaultMode`, `sandbox.excludedCommands` 등 read-only를 약하게 하는 사용자 설정) |

**log 형식(한 이벤트 한 줄, 실패만 발췌):** `init model=… mode=… cwd=…`(모드·모델이 바뀔 때만 다시) / `msg <주 스레드 텍스트 전문>` / `bash exit=<n> out=<bytes>B <명령 300자>`(실패면 출력 앞뒤 1200B 들여쓰기) / `edit|write <상대 경로>` / `read <경로>` / `grep|glob <패턴>` / `fetch <url>` / `search <질의>` / `skill <이름>` / `agent <type> <설명> tools=<n> out=<bytes>B`(하위 에이전트 도구는 세기만) / `mcp <server>/<tool> ok|error` / `running <도구> <요약>`(결과 없는 진행 중 호출) / `denied <도구> <입력 120자>` / `sent <priority> <메시지 120자>` / `task <started|completed|stopped> <설명>` / `retry attempt=<a>/<max> error=<분류> status=<http>` / `ratelimit <상태> 5h=<%> 7d=<%>`(상태가 바뀔 때만) / `compact` / `result <subtype> turns=<n> terminal=<reason> cost=$<x>`(후속 턴이면 `origin=task-notification`) / 끝줄.

## 권한 프로필 → argv (claude_cli/argv.py가 유일한 소유자)

모든 턴 공통: `claude -p --input-format stream-json --output-format stream-json --verbose --include-hook-events --permission-prompts none --model <m> --effort <e> --append-system-prompt <J5 고정 사실> --disallowedTools "Skill(claude)" "Skill(claude:claude)" Monitor SendMessage PushNotification CronCreate RemoteTrigger`(프로필의 Edit·Write·NotebookEdit도 같은 플래그 뒤에), 새 런은 `--session-id <uuid>`, 이어 가는 런은 `--resume <uuid>`, 스키마가 있으면 `--json-schema <파일 내용>`, batch worktree 새 멤버는 `--worktree <group>-<i>`와 `worktree.baseRef: "head"`(같은 `--settings` 객체에 합침).

| 프로필 | 플래그 | 할 수 있는 것(help가 말할 문장) |
|---|---|---|
| `read-only` | `--permission-mode dontAsk`, `--disallowedTools Edit Write NotebookEdit`, `--settings` 샌드박스: `enabled`·`autoAllowBashIfSandboxed`·`failIfUnavailable` true, `allowUnsandboxedCommands` false, `filesystem.denyWrite [<cwd>]`, `filesystem.allowWrite ["~/.cache"]` | 무엇이든 읽고, 셸 명령은 샌드박스 안에서 돌린다: 쓰기는 TMPDIR과 `~/.cache`뿐, 네트워크는 네 설정이 허용한 호스트만(기본 없음) → 테스트·빌드를 실행해 결과를 가져올 수 있다. 편집 도구 없음. 훅·MCP 도구·WebFetch는 샌드박스 밖이고 네 권한 규칙을 따른다. 프로필은 네 설정 위에 거는 제한이고, 설정이 넓힌 곳은 `profile_exceptions`가 말한다 |
| `write` | `--permission-mode acceptEdits`, 위 샌드박스에서 `denyWrite` 없음 | 작업 디렉터리 안 편집·셸 쓰기, 네트워크는 read-only와 같음. 디렉터리 밖 편집은 거부되어 `permission_denials`에(설정이 허용한 경로는 예외로 보고) |
| `auto` | `--permission-mode auto`(샌드박스 설정을 넣지 않음) | Claude Code 분류기가 호출마다 검토: 네트워크·디렉터리 밖 쓰기 가능. 분류기가 막은 호출은 거부로 남음. 모델이 auto를 못 쓰면 init 모드가 다르고 `mode_mismatch` |

## 단위 입구 (`__all__`, 나머지는 숨김)

| 단위 | 입구 | 숨기는 것 |
|---|---|---|
| `claude_cli` | `build_argv(record, kind, …)`, `worker_env(base_env, run_id)`, `PROFILES`, `worker_context()`, `turn_preamble(batch, worktree)`, `encode_user_message(text, uuid, priority)`, `read_events(path)`, `summarize(events)`(행에 쓰는 요약: 상태 단서·in_progress·denials·usage·rate_limit·retry·results·files_edited·마지막 메시지), `log_lines(events, rel_to)`, `final_result(events)`, `answered_uuids(events)`, `worktree_location(repo, name)`, `profile_exceptions(cwd, profile)`, `claude_version()`, `version_floor_check()`, `auth_status()`, `sandbox_prereqs()`, `quota()` | stream-json 필드 이름·메시지 종류, 프로필의 플래그·설정 JSON, Bash 결과 텍스트에서 exit code 읽기, `.claude/worktrees`·`worktree-` 이름 규칙, 설정 파일 위치·키(예외 탐지), 버전 문자열 해석 |
| `git` | `toplevel(path)`, `main_checkout(path)`, `uncommitted_count(path)`, `worktree_entries(repo)`, `unlock_and_remove(repo, path, force)`, `commits_beyond(repo, branch, base)`, `delete_branch(repo, branch)` | porcelain 해석, bare·서브모듈 예외, NFC |
| `registry` | `resolve_runs_dir`, `ensure_runs_dir`, `publish_run(…, check, make_meta)`(세션 잠금 안 check+claim), `read_meta`, `update_meta`, `record_if_active`(CAS), `reap`, `is_live`, `iter_runs`, `find_run(ref)`(run id·session id·prefix), `live_runs`, 그룹 `claim_group`·`record_members`·`group_view`·`release_group`·`list_groups`, inbox `enqueue`·`take`·`close` | 잠금·원자 쓰기·스테이징 이름·id claim·CAS |
| `runs` | `start`, `resume`, `send`, `stop`, `create_run`(batch용), `settings_for`, `supervise`, `end_group` | 4단계 생성, stdin 닫기 규칙, 신호 사다리 |
| `batch` | `batch`, `clean`, `TASK_FIELDS` | 멤버 생성 순서·이름 예약·worktree 대상 판정 |
| `observe` | `status`, `log`, `result`, `STALL_SECONDS`, `LISTING_ROWS`, `GROUP_MESSAGE_CAP` | 행 구성, 파생 상태, 대기 |

import 방향: feature → system·store → shared. 기능 간 간선은 `batch → runs` 하나. `cli.py`는 위 입구만 부르고 결정 로직을 갖지 않는다(프로필 선택·상속·stdin 닫기·clean 판정은 단위 안).

## SKILL.md 섹션 구조 (한 파일, 영어, 목표 60줄 이하)

references/는 두지 않는다: 모든 경로(단일 위임·배치·대기·문제 해결)가 짧고, 프로필·출력·플래그의 세부는 `--help`가 소유한다(interface over document). S6 대조에서 한 갈래만 쓰는 긴 내용이 생기면 그때 references로 옮기는 것을 성진과 정한다.

- frontmatter: `name: claude`. `description`: 클로드 작업자(헤드리스 Claude Code 세션)를 백그라운드로 시작하고 서브에이전트처럼 관리 — 진행 추적, 방향 전환(send), 정지·이어 시키기, 여럿을 한 그룹으로, 텍스트/스키마 결과 대기·회수, 한도 확인 — 를 언제 쓰는지; 트리거(영어 + 한국어: 클로드 작업자, 클로드한테 시켜, 클로드로 병렬, 백그라운드 클로드, 작업자 띄워, headless claude, claude -p 작업자 등); "Not for": Claude Code 기능·내장 Agent 도구·에이전트 팀·`claude --bg` 자체에 대한 질문, Claude API/SDK. codex·다른 모델 언급 없음. `allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)`
- `# Claude workers as managed subagents` — 호출 형식(한 줄 전체, 변수·`$(…)`·파이프·`\` 금지 이유 = 사전 승인 매칭), 응답은 찍힌 그대로 읽음, `--help`가 계약
- `## Handing work over` — 프로필이 작업자가 할 수 있는 일과 가져올 수 있는 증거를 정함(read-only도 테스트를 돌림); 작업자는 내 클로드 환경 전체(CLAUDE.md·스킬·훅·MCP)를 갖고 일함 — 프롬프트에 쓰지 않은 입력; git은 내 몫(작업자는 바꾼 것을 보고); resume vs 새 start; 검증 루프는 작업이 바닥낼 수 있는 술어에서 멈춤; 대응표(`Agent` → `start` + `next` 백그라운드 / `Workflow parallel()` → `batch` / 실행 중 서브에이전트에 말 걸기 → `send` / 멈추기 → `stop` / 팀원끼리 대화·공유 작업 목록 → 없음, 라운드: batch → 수집 → 서로의 발견을 넣어 resume)
- `## Several workers at once` — 배치의 쓸모, 격리는 시작할 때(`--worktree`: 내 로컬 HEAD에서, 미커밋 변경 없음, 무시 파일은 `.worktreeinclude`), 작업자 N개는 같은 구독 한도를 N배로 씀(넓은 배치 전에 한도), 그룹은 세션보다 오래 감, `result --group`, worktree 변경을 내 트리로 옮기는 건 내 몫, `clean`
- `## Waiting, steering and collecting` — `next.command`를 백그라운드로(알림이 오면 출력 파일이 결과, 일을 지어내지 않음); 끝나기 전에 돌아온 결과의 `attention`은 판단할 순간 — 다시 기다릴지(`next`), `send`로 고칠지, `stop`할지; 방향이 틀리면 `send`(`--interrupt`는 진행 중 턴을 끊음), 결과를 읽은 것은 확인한 것이 아님, `permission_denials`는 작업자가 못 한 일 — 다른 프로필로 다시 할지 판단, 이번 턴뿐이면 전경 `--wait-timeout`
- `## When something goes wrong` — `doctor`; `retrying`·`stalled`·`finishing`·`mode_mismatch`가 뜻하는 것과 볼 필드; `stderr_tail`; 세션을 직접 열어 보려면 `claude --resume <session_id>`; `uv`·경로 문제

문장마다 S6 대조(draft vs control)로 행동을 바꾸는지 확인하고, 바꾸지 않는 문장은 빼는 쪽으로 성진과 정한다.

## 테스트 seam (coding 스킬)

기대값은 구현 밖(이 장부의 실측·Claude 문서·손으로 만든 예)에서, 러너 종료 코드·실패 출력은 파이프로 가리지 않는다, red는 의도한 동작이 없어서여야 한다(새 단위는 빈 입구부터).

- **S1 CLI 서브프로세스 + PATH의 가짜 `claude`**(주 seam): `tests/support/fake_claude/claude`(파이썬)가 argv·cwd·env·stdin 메시지를 기록하고 시나리오(프롬프트 안의 표식 `[[fake:<이름>]]`)에 따라 실측 형식의 stream-json을 낸다 — init(argv의 `--permission-mode`·`--session-id`·cwd 반영), 도구 호출·결과, 지연, 메시지마다 `user_message_uuids`를 가진 result, `priority:"now"`면 aborted_tools 후 새 턴, SIGINT면 error_during_execution 후 exit 0, SIGTERM exit 143, 백그라운드 후속 턴(origin task-notification), api_retry·rate_limit_event, `--resume`(가짜 세션 저장소에 없으면 "No conversation found"), `--worktree`(실제 `git worktree add -b worktree-<n>` + lock), `/usage`(usage_report), `--version`, `auth status`. fixture 줄은 이번 실측 이벤트에서 잘라 쓴다(실제 CLI 출력이 출처).
  - 대상 계약: start 응답·argv(프로필별 플래그 문자열은 장부 실측값), resume이 프로필·스키마·effort·모델·settings JSON·disallowedTools·append-system-prompt·env를 재주입(가짜가 기록한 argv·env), 세션에 살아 있는 런이 있으면 resume 거부, send 전달·uuid·priority·닫힌 뒤 거부, stdin 닫기 규칙(J1: 메시지 두 개 중 하나만 답해졌으면 열려 있음; uuid 없는 result면 닫음), 최종 답 선택(J1b: task-notification 후속 result가 마지막이어도 원래 답·structured_output), finishing·completed·failed·interrupted·timed_out·orphaned, `--wait`의 attention 귀환(이벤트 파일 mtime을 과거로 돌린 런, 재시도 연속 fixture, rate_limit rejected fixture)과 끝난 런, result 헤더·스키마 JSON·그룹, log 줄 형식, batch·worktree 이름·baseRef·대상 판정, clean J9 전부(복사된 ignored 파일과 훅이 만든 시작 생성물(심링크)은 `--force` 없이 지움, 작업자가 만든 untracked 파일·새·바뀐 ignored 파일은 남김, 작업자가 파일을 만든 뒤 `send --interrupt`로 새 턴(새 init)이 돌았거나 그 멤버를 resume한 뒤에도 그 파일은 남김, 접힌 디렉터리 안에 작업자가 만든 파일도 남김), worktree가 사라진 멤버 resume 거부(J17), `blocked_by_hook`(exp16의 informational fixture: 진짜 답 없이 턴을 여는 메시지가 막히면 `failed`, 답이 있은 뒤 막힌 턴 여는 메시지·실행 중 send는 앞 답 유지 + `last_message_blocked`; `local_command`가 있는 `num_turns: 0` result는 막힘이 아님; 필드 없는 `num_turns: 0`·assistant 없음은 `possibly_blocked`), stdin을 닫은 뒤에도 후속 턴을 내는 가짜로 `finishing` 120초 attention, `finishing` 런에서 resume·send 거부의 `instead`가 서로를 가리키지 않음, 프롬프트 없는 resume exit 2, `--disallowedTools` 목록(Monitor·SendMessage·PushNotification·CronCreate·RemoteTrigger·스킬 자신), 재귀 금지(J6), env 정리(J7), 하한 미만 거부(J11), `profile_exceptions`(임시 HOME과 프로젝트 settings에 예외를 심어).
- **S2 단위 입구(프로세스 안):** `claude_cli`(argv·env·stream 해석·설정 예외 탐지 — 실측 fixture 입력, 손으로 쓴 기대 줄), `runs.settings_for`(플래그 > 기록 > 기본, 레지스트리에 없는 세션), `observe`의 attention 판정(주입한 `now`로 600초·120초 경계), `git`(실제 임시 저장소: linked worktree·bare·서브모듈의 본 체크아웃, 기준 이후 커밋, ignored 파일 비교), `registry`(CAS·reap·inbox 닫기), `runs.end_group`(`kill=` 주입).
- **S3 레이스(실제 프로세스):** 같은 세션 resume 둘이 동시에 → 하나만; send와 stdin 닫기 경합 → 전달되거나 거부되거나 둘 중 하나(유실 없음, 넣기에 성공했는데 전달 안 된 것은 `undelivered`로 보임); 같은 그룹 이름 batch 둘; 감독 SIGKILL → reap가 orphaned, claude가 아직 쓰면 살아 있음으로 resume·clean 거부(J16).
- **S4 구조·계약:** `test_structure`(두 최상위 이름, KINDS·import 방향·FEATURE_EDGES {(batch, runs)}, 입구 밖 접근 금지 — 테스트 포함, `sys.path` 편집 금지), `test_cli_contract`(모든 인자에 help, 명령마다 짧은 usage와 `Prints:`·`Exits:`, 루트 지도 10개), `test_install`(SKILL.md가 가리키는 명령·플래그·필드가 존재, `allowed-tools` 패턴과 `invocation()`이 같은 모양).
- **S5 진짜 claude 스모크**(`CLAUDE_SKILL_REAL=1`, haiku, TMPDIR 밖에 만든 임시 git 저장소): start→result; schema; send 방향 전환; stop→resume(작업자가 중단을 앎); resume init의 `permissionMode`가 프로필대로(재주입 증거); read-only(테스트 실행·심은 버그 보고·**작업자 도구가 만든 변경 0**·허용 안 된 호스트 차단), write(cwd 밖 거부), auto; batch `--worktree`(`.worktreeinclude` 복사, baseRef head로 로컬 커밋 포함) → clean; doctor quota.
- **S6 헤드리스 e2e**(skill-maker "기본값과의 대조"): 오케스트레이터 = `claude -p --model sonnet --setting-sources project,local`(사용자 레벨의 살아 있는 `claude` 스킬과 전역 CLAUDE.md의 라우팅이 대조를 오염하지 않게 — 작업자는 스킬 CLI가 띄우므로 여전히 사용자 환경 전부), 시나리오마다 임시 프로젝트에서. 스킬은 하네스가 변형별로 만든 임시 플러그인(`.claude-plugin/plugin.json`을 하네스가 씀 — PR ⑥의 매니페스트와 무관)으로 `--plugin-dir`에 싣고, `--allowedTools`에 `Skill(claude:claude)`와 그 변형의 `Bash(uv run "<변형 경로>/scripts/cli.py" *)`. 변형 draft와 control(frontmatter + 호출 문단만). 시나리오: ① 조사 위임 후 결과로 답하기 ② 독립 작업 3개 배치 후 모아 요약 ③ 잘못된 방향으로 가는 작업자를 send로 고치기 ④ 권한 거부·실패하는 작업자를 알아차리고 보고 ⑤ 파일을 바꾸지 말고 테스트를 실제로 돌려 버그 찾기(read-only). 측정: 한 줄 호출(파이프·변수 없음), `next`를 백그라운드로, 폴링 루프 없음, denials·실패를 보고, ⑤에서 read-only로 테스트 실행·트리 변경 0. 세션 10개(5 × 2). 거부·환경 탓 실패는 증거로 쓰지 않고 다시 돌린다.
- **"작업자 도구가 만든 변경 0"의 측정**(S5·PR ①·S6 ⑤): 테스트 도우미 `tree_snapshot(dir)` = `.git`과 레지스트리 `.claude-runs/`(스킬 자신의 저장소 — 따로 검증)를 뺀 모든 항목의 상대 경로 → (종류, 파일이면 sha256, 링크면 대상). ① 대상 런 전 스냅샷 A ② 같은 환경·같은 디렉터리·같은 프로필에서 "`true`를 Bash로 한 번 실행하고 OK라고 답하라" 런(Claude Code의 `.claude/.cc-writes/`는 첫 샌드박스 Bash 때 생기므로 — exp6·exp13 생성 시각) 뒤 스냅샷 B → 시작 생성물 = B−A와 B에서 바뀐 항목(Claude Code의 `.claude/.cc-writes/`, 사용자 훅의 `.claude/histories` 등 — exp6·exp13) ③ 대상 런 뒤 스냅샷 C. C와 B가 시작 생성물 밖에서 하나라도 다르면(새 항목·내용 변경·삭제·링크 대상 변경) 실패. 시작 생성물은 별도 증거로 기록한다. 도우미 자체를 "기준선 디렉터리 안 새 파일", "기존 파일 내용 변경"으로 한 번씩 깨서 잡는지 확인한다.
- 하지 않는 것: 문장 해시, JSON 키 순서, 내부 함수 모킹, 진짜 claude를 기본 스위트에서 부르기.
- 검증되지 않는 것(핸드오프에): 훅이 끝낸 메시지 판정이 기대는 `prompt_submit_outcome`은 문서에 없는 필드(exp16 실측뿐, 0단계에서 `continue: false`도 확인; 없으면 `possibly_blocked`로 대비), 가짜 claude 뒤에 숨은 실제 CLI 계약(S5가 일부만), Linux 샌드박스(bwrap), claude.ai 외 인증, Claude Code 업데이트로 바뀌는 이벤트 형식(하한·`unparsed_events`로 대비), 수십 세션의 실사용 품질.

## 단계 (PR별, 완료 판정)

모든 PR: `main`에서 브랜치 → 논리 단위 커밋(경로 명시 스테이징, `git add -A` 금지) → 푸시 → PR(본문 `## 무엇을 바꿨나`/`## 왜`/`## 영향`/`## 검증`, 커밋·PR 제목 `<타입>: <한국어>`) → 코덱스 리뷰(아래 프로토콜) → `gh pr merge --squash` → `git pull`. 동작은 red 먼저, 구조와 동작은 다른 커밋.

**0. 준비와 남은 실측 (main 직접 커밋: 스캐폴딩만)**
- 심링크 삭제(맨 위). `git init`, `.gitignore`(트리 절), LICENSE(Apache-2.0), 빈 README, `git remote add origin https://github.com/tjdwls101010/claude-in-claude.git`, `chore: 레포를 초기화한다`를 main에 커밋·푸시. (메모리 피드백 "스킬은 다른 스킬과 독립 — 라우팅은 성진의 CLAUDE.md 몫"은 계획 세션에서 이미 저장함: `skills-independent-routing-in-claude-md`.)
- 하한 확정(J11): argv 플래그와 파서가 의존하는 필드마다 문서의 최소 버전을 표로 만들어 PR ① 본문에, 최댓값을 상수로.
- 실측(scratchpad, haiku, 결과를 PR ① 본문과 장부에): (a) `BASH_DEFAULT_TIMEOUT_MS`·`BASH_MAX_TIMEOUT_MS`를 짧게(예: 8000·15000) 둔 작업자에서 `timeout` 없는 명령은 기본값에서, `timeout`을 준 명령은 상한에서 끊기고 백그라운드로 옮겨지지 않는지(= 600000·3600000이면 10분·1시간까지 전경으로 돈다는 근거) (b)는 계획 세션에서 끝남(exp16) — S1 fixture로 그 이벤트 순서를 옮긴다. (c) 최종 작업자 설정(백그라운드 꺼짐, Monitor 등 금지 목록) 아래에서 `sleep 45 && echo ok`가 막히는지 — 막히면(exp3에서는 "use Monitor / run_in_background"로 막힘, 둘 다 이제 없음) J5 고정 사실에 "기다려야 하면 `until <확인>; do sleep 2; done`처럼 확인하며 기다리는 전경 명령으로"를 한 문장 넣는다. (d) `{"continue": false, "stopReason": …}`를 내는 프로젝트 `UserPromptSubmit` 훅으로 턴을 여는 메시지·실행 중 메시지를 각각 보내 `system/informational`의 `prompt_submit_outcome`이 오는지와 그 kind(J1b).
- 완료 판정: origin main에 초기 커밋, 실측 결과 기록, J1·J7을 결과에 맞춰 확정(바뀌면 성진에게 AskUserQuestion).

**PR ① `feat: 레지스트리와 런 엔진으로 작업자를 시작하고 결과를 받는다`** (`feat/run-engine`)
- 범위: `cli.py`(start·status·log·result·stop·__supervise), `claude_cli`(argv·stream·install의 버전), `git/repo.py`, `registry`(runs·locks·inbox 빈 입구), `runs`(settings·create·supervisor·commands의 start·stop), `observe`, `errors`·`util`; 테스트 S1(start·result·log·status·stop·상태 전이·env·재귀 금지·하한), S2, S3(세션 잠금·reap), S4(structure·cli_contract), 가짜 claude.
- 완료 판정: 각 동작 커밋의 red 이유가 커밋 본문에, `python3 -m unittest discover -s tests` exit 0(수·시간 기록), 실제 claude로 read-only `start`→`next` 백그라운드→결과 한 바퀴(작업자 도구가 만든 변경 0, 측정은 테스트 seam 절), 옮김 없음이므로 대신 핵심 규칙 하나(J1 stdin 닫기)를 일부러 깨 S1이 빨개지는지 확인, 코덱스 리뷰 멈춤 조건.

**PR ② `feat: 작업자를 이어 시키고 실행 중에 방향을 바꾼다`** (`feat/resume-send`)
- 범위: `resume`(재주입, 레지스트리에 없는 세션은 `--profile` 필수, 살아 있으면 거부+`instead`), `send`(inbox, `--interrupt`, 닫힌 뒤 거부), 감독의 J1 규칙 완성, 스키마 재주입, `finishing`.
- 완료 판정: S1·S3 해당 항목 red→green, S5의 resume 재주입·send·stop→resume 통과, 코덱스 리뷰 멈춤 조건.

**PR ③ `feat: 작업자 여럿을 한 그룹으로 돌리고 worktree로 격리한다`** (`feat/batch`)
- 범위: `batch`(tasks 검증, 멤버 생성, worktree 이름·baseRef·대상), `clean`(J9), `git/worktree.py`, `result --group`·`status --group`·overlaps.
- 완료 판정: S1·S3(그룹 이름 경합)·S2(git) green, S5 batch `--worktree`→clean 실제 통과, 코덱스 리뷰 멈춤 조건.

**PR ④ `feat: 한도와 재시도를 보이고 doctor로 환경을 진단한다`** (`feat/doctor-quota`)
- 범위: `doctor`(J11·J12·인증·샌드박스 전제·상속 환경 주의), status의 `rate_limit`·`retrying`·`stalled`, log의 retry·ratelimit 줄.
- 완료 판정: S1 green, 실제 `doctor` exit 0과 quota 값이 `claude -p /usage`와 일치, 코덱스 리뷰 멈춤 조건.

**PR ⑤ `docs: SKILL.md를 쓴다`** (`docs/skill-md`)
- `skill-maker`를 `Skill`로 연다. 섹션 구조대로 쓰고, `claude -p "/skill-doctor"`로 이웃 스킬과 트리거 겹침 확인(겹치면 이 스킬의 description만 고치고 결과를 성진에게). S6 10세션. 코덱스가 skill-maker의 다섯 프로퍼티로 전문 리뷰 → 저울질해 반영. 성진에게 **전문** 승인(텍스트를 채팅에 보이고 다음 턴에 AskUserQuestion; 부분 승인·침묵은 승인이 아님).
- 완료 판정: `claude plugin validate --strict "<repo>/.claude/skills"`(심링크면 대상의 부모) exit 0, S4 green, S6 결과(draft vs control 차이로 각 판단 문장의 근거)를 PR 본문에, 60줄 이하, 성진 명시 승인.

**PR ⑥ `chore(release): v0.1.0`** (`chore/release-0.1.0`)
- README(개요·기능·Quick Start: 설치, 권한 규칙 `Skill(claude)`/`Skill(claude:claude)`와 `Bash(uv run "<skill dir>/scripts/cli.py" *)`, 첫 실행, 사용 예, 상태, 범위 밖), CONTRIBUTING(트리·테스트·S5·S6 실행법), CHANGELOG `[0.1.0]`, SECURITY, `plugin.json`(name `claude`, version 0.1.0, skills `./.claude/skills/`)·`marketplace.json`(name `claude-in-claude`). 머지 후 스쿼시 SHA로 `git tag v0.1.0` → 푸시 → `gh release create v0.1.0 --verify-tag --notes-file <파일>`. `~/.claude/skills/claude` 심링크(없으면).
- 완료 판정: S5 다시 통과, README의 모든 명령을 실제 실행, `gh release view v0.1.0`, 살아 있는 스킬로 `start`→`next` 백그라운드→알림→결과 한 바퀴.

**레포 밖 성진 설정(성진 결정):** PR ① 머지 직후 `~/.claude/skills/claude` 심링크를 만들고, `~/.claude/settings.json`을 백업한 뒤 `permissions.allow`에 `"Skill(claude)"`와 `"Bash(uv run \"/Users/seongjin/.claude/skills/claude/scripts/cli.py\" *)"` 두 줄만 더한다(다른 항목은 건드리지 않음). PR ⑥ 뒤 전역 `~/.claude/CLAUDE.md`의 "스킬을 여는 순간"에 성진이 정한 라우팅 — **위임·검증의 기본값은 `codex`, 성진이 명시적으로 요청하거나 codex를 쓸 수 없을 때 `claude`** — 을 담는 문장을 초안으로 보여 주고 승인받은 뒤에만 고친다(스킬 자체는 이 라우팅을 담지 않는다).

**핸드오프(성진에게):** S6 요약, 검증되지 않는 것(테스트 seam 절), "사용자 환경 전부"의 비용(Orca 훅이 작업자마다, `.claude/histories` 심링크가 worktree마다), 넣지 않은 것과 다시 넣을 조건, 승인이 실사용 성능의 증거는 아님.

## 코덱스 리뷰 프로토콜 (PR마다)

1. `codex` 스킬로 `start --sandbox read-only --model gpt-6.1-terra --effort high --schema <repo>/.tmp/review-schema.json --label review-pr<n> --prompt-file <repo>/.tmp/review-pr<n>.md`. **코덱스 쿼터는 2026-11-04 17:09까지 소진**(이 계획 4라운드에서 확인) — 그 전에는 처음부터 sonnet 리뷰어(`Agent`, model sonnet, 같은 프롬프트, 파일 수정 금지 명시)로 하고, PR ① 머지 뒤에는 이 스킬 자체(`start --profile read-only --model sonnet --schema …`)를 리뷰어로 써도 된다(그 경우 다른 모델 계열의 시각이 없다는 점을 PR 본문에 적는다). 지적 schema: `{id, file, line, claim, evidence, reachable_in_ordinary_use, violates_contract, severity}`. 프롬프트: PR 목적, `git diff main...HEAD`, 이 PR의 계약·완료 판정, 이 계획 경로, 소비자가 실제로 받는 것(`--help`·에러·실제 실행 trace), "테스트를 실행해 재현하라".
2. 지적마다 재현해 판단. 계약을 깨면 고친다(동작이면 red 먼저). 기각은 이유와 함께 PR `## 검증`에.
3. 다음 라운드는 같은 스레드를 resume해 "수정이 버티는가, 수정이 만든 회귀가 있는가"만 묻고 기각 목록을 넘긴다.
4. 멈춤: `reachable_in_ordinary_use`이거나 `violates_contract`인 지적 0. 같은 불변식에서 되풀이되면 근본 원인을 고친다. 계획의 결정과 충돌하는 지적은 성진에게 AskUserQuestion.

## skill-maker 프레임 대조 (완료 판정에 그대로)

- **다섯 프로퍼티:** principle over rail(프로필 문장은 "할 수 있는 일과 가져올 증거"라는 이유로), interface over document(프로필 세부·출력·상태·실패는 help와 거부 응답이 소유), for the model(실측 수치·발견 경위는 커밋·PR·CHANGELOG), dense(코덱스 리뷰), colleague over autopilot(git·worktree 병합·한도는 사람/호출자 몫임을 말하고, 결과가 보여 주지 않는 것 — Bash 쓰기, 확인 안 한 결과 — 을 넘길 때 말하게).
- **기본값과의 대조:** S6 control로 판단 문장이 행동을 바꾸는지.
- **이웃 스킬:** `skill-doctor`.
- **번들 코드 규칙:** 두 최상위 이름 / `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py"` + PEP 723 / 명령은 숨길 일이 있을 때만 / `cli.py`에 결정 로직 없음 / 명령별 help가 출력·실패를 스스로 / stdout은 결과만(진행·진단은 stderr) / 단위 = 깊은 모듈 / system(`claude_cli`·`git`)이 형식을 다 가짐 / import 한 방향 / 테스트는 스킬 밖 / 구조 테스트. 상태 위치(`data/` 대신 프로젝트 `.claude-runs/`)는 성진이 정한 어긋남.
- **완료 조건:** SKILL.md 전문 승인 / `claude plugin validate --strict` exit 0 / 바꾼 코드가 제 계약대로·`--help`가 동작과 일치·구조 테스트 / 다른 모델 계열(Codex) 리뷰를 저울질해 반영 / 개발 기록은 스킬 밖.

## 검증 (전체)

- `python3 -m unittest discover -s tests`(Python ≥3.11) exit 0, 수·시간을 PR ⑥ 본문에.
- 구조 테스트 green, `claude plugin validate --strict` exit 0.
- S5 전 항목, S6 10세션.
- 살아 있는 스킬로 `doctor` exit 0, `start`→`next` 백그라운드→알림→결과, `send`, `stop`→`resume`, `batch --worktree`→`result --group`→`clean`.

## 범위 밖

Agent SDK, `claude --bg`/agent view 연동, 에이전트 팀·작업자 간 메시징·교차 세션 inbound, `--max-turns`·`--max-budget-usd`, fork, `--agent`, 이미지 플래그, 단일 런 worktree, `models` 명령, bypass 프로필, 작업자의 작업자, 다른 위임 도구와의 라우팅, Linux·Windows 검증, `data/`로 상태 이전.

## 계획 리뷰 기록

코덱스 gpt-6.1-terra/high/read-only, 런 `20261031-082341-plan-review-aa97`(스레드 `01a18f20-50ce-72b0-b95d-dfae1375ca35`, 레지스트리 scratchpad). 1라운드 8건, 모두 근거 확인 후 반영:

| # | 지적 | 처리 |
|---|---|---|
| F1 | 기본 대기가 멈춘 작업자를 알리지 못함 | 결정 행 "`result --wait`는 주의가 필요하면 일찍 돌아온다"(성진 결정, 10분), J10 attention |
| F2 | uuid 없는 버전의 개수 대체 규칙이 합쳐진 턴에서 끝나지 않음 | 하한 v2.1.259가 uuid 에코를 보장, uuid 없는 result면 닫음(J1) |
| F3 | inbox에 들어갔지만 아직 안 가져간 메시지를 두고 닫을 수 있음 | 닫기는 같은 잠금 아래 inbox가 빌 때만, `undelivered`(J2) |
| F4 | 마지막 result를 고르면 task-notification 답이 덮어씀 | J1b 최종 답 선택, `followups` |
| F5 | 사용자 설정의 샌드박스 예외가 프로필을 넓힘 | 결정 행 `profile_exceptions`(성진 결정), help 문장 |
| F6 | clean이 ignored 파일을 말없이 지움 | J9: 복사본과 같은 ignored만 지울 수 있음, 나머지는 `--force` |
| F7 | orphan인데 claude가 살아 있으면 resume·clean이 진행될 수 있음 | J16 살아 있음 정의 |
| F8 | worktree가 지워진 멤버 resume이 본 체크아웃에서 조용히 재개 | J17 거부와 `cwd_mismatch` |

2라운드(같은 스레드, 런 `20261031-082825-plan-review-r2-9033`): F1~F8 중 수정이 버티지 않는 곳과 새 결함 7건. 모두 확인 후 반영:

| # | 지적 | 처리 |
|---|---|---|
| R2-1 | uuid 없는 result로 닫으면 최종 답을 고를 규칙이 없음 | J1b: 마지막 전달 이후 task-notification 아닌 마지막 result, `answer_unconfirmed`, 시작 오류는 `failed` |
| R2-2 | 훅이 막은 send·64개 상한이면 uuid가 영영 안 나타나 stdin이 열린 채 | J1 (b) 5초 유예 닫기, `unanswered` |
| R2-3 | J16이 살아 있는 런의 `send`를 거부해 send 계약과 모순 | J16: send는 감독이 살아 있고 stdin이 열린 런에만 |
| R2-4 | `finishing` 중 무활동은 attention이 안 생김 | J10: 끝나지 않은 모든 상태에 stalled, J3 문구 |
| R2-5 | 존재하지만 재진입이 거부된 worktree | 문서: `-p`는 스스로 멈추고 error result(worktrees.md); exp15: init은 첫 메시지 뒤 → init 불일치면 즉시 stop·`cwd_mismatch` |
| R2-6 | 네트워크 허용(allowedDomains·WebFetch domain 규칙)이 예외 목록에서 빠짐 | `profile_exceptions`에 추가, 프로필 문장 "네 설정이 허용한 호스트만" |
| R2-7 | 사용자 훅 생성물 때문에 "트리 변경 0"이 실패 | "작업자 도구가 만든 변경 0"과 시작 생성물 기준선 측정 |

3라운드(런 `20261031-083109-plan-review-r3-d7d7`): 4건, 모두 반영:

| # | 지적 | 처리 |
|---|---|---|
| R3-1 | 5초 유예가 느린 `UserPromptSubmit` 훅 처리 중에 닫을 수 있음 | `--include-hook-events`, 훅 이벤트도 활동, 열린 `hook_started`가 있으면 닫지 않음, 유예 10초, send 16개 상한, 0단계 실측 (b) |
| R3-2 | 마지막 메시지 uuid가 없을 때 답 선택·표시 미정 | J1b `answered`·`unanswered`·`last_message_unanswered`, result 헤더 |
| R3-3 | init 후 정지는 이미 생긴 변경을 막지 못함 | J17 보장 범위 명시(clean 경합은 막힘, 스킬 밖 삭제는 오류로만), 오류 문구 |
| R3-4 | git status 경로 비교는 기준선 안 변경을 놓침 | `tree_snapshot` 내용 비교, 도우미를 일부러 깨서 확인 |

4라운드는 **코덱스 쿼터 소진(2026-11-04 17:09까지)**으로 sonnet 리뷰어(`Agent`, general-purpose, 읽기만)가 했다 — 다른 모델 계열의 시각이 아니라는 점이 한계. 9건(중간 4·낮음 5), 모두 확인 후 반영:

| # | 지적 | 처리 |
|---|---|---|
| R4-1 | `finishing`(Monitor)이 답이 있는데도 `--wait`를 붙듦 | Monitor 금지(성진 결정, exp14·17) + J3 `finishing` 120초 attention |
| R4-2 | `.cc-writes`는 첫 샌드박스 Bash 때 생겨 "Reply OK" 기준선에 안 잡힘 | 기준선 런이 `true`를 Bash로 한 번 실행 |
| R4-3 | `finishing` 런에서 resume·send 거부의 `instead`가 서로를 가리킴 | J16 상태별 `instead` |
| R4-4 | `permissions.additionalDirectories`가 예외 목록에서 빠짐 | `profile_exceptions`에 추가(+ settings `env`의 timeout·background 변수) |
| R4-5 | 훅에 막힌 턴 여는 메시지가 `completed`로 보임 | J1b `blocked_by_hook`, 마지막 메시지가 막혔으면 `failed` |
| R4-6 | `tree_snapshot`이 `.claude-runs/`를 포함 | 스냅샷에서 제외 |
| R4-7 | `timeout` 없는 명령은 여전히 2분에 끊김 | `BASH_DEFAULT_TIMEOUT_MS=600000` 추가, 0단계 (a) 확장 |
| R4-8 | J1 문장이 편집으로 붙어 깨짐, "주요 이벤트" 미정의 | 문장 분리, (b)의 이벤트 = stdout의 모든 줄 |
| R4-9 | 프롬프트 없는 `resume`의 동작 미정 | PROMPT 필수(exit 2) |

5라운드(같은 sonnet 리뷰어, 좁게): R4 수정은 대부분 버팀. 새 결함 5건(높음 1·낮음 4), 모두 반영:

| # | 지적 | 처리 |
|---|---|---|
| R5-1 | 뒤 턴 init·resume이 `startup_artifacts`를 덮으면 작업자 파일을 `clean`이 `--force` 없이 지움 | 첫 런의 첫 init에서 한 번만 기록, 뒤 init·resume은 안 씀, `clean`은 첫 런 기록만 |
| R5-2 | 접힌 디렉터리 항목의 해시 미정, `.cc-writes`는 init 뒤에 생김 | `--untracked-files=all` 파일 단위 해시, 빈 `.cc-writes`는 예외로 지울 수 있음 |
| R5-3 | J1 (b)의 "주요 이벤트"가 여전히 미정 → 문자 그대로면 닫지 못함 | "마지막 result가 마지막 전달 뒤 + stdout 무활동 10초"로 다시 씀 |
| R5-4 | `num_turns: 0`만으로 막힘 판정 → 로컬 명령을 오판, 실행 중 send 막힘을 `failed`로 | `informational`의 `blocked_by_hook`로만, 턴을 여는 메시지가 막혔을 때만 `failed` |
| R5-5 | 새 설정에서 전경 `sleep` 대기가 막히는지 미측정 | 0단계 실측 (c), 막히면 J5에 한 문장 |

6라운드(같은 리뷰어, J9·J1 (b)·J1b만): J1 (b)와 J9의 R5 수정은 버팀. 새 3건(중간 1·낮음 2, 모두 일상 사용에서 닿지 않거나 계약을 깨지 않음), 반영:

| # | 지적 | 처리 |
|---|---|---|
| R6-1 | 판정이 문서에 없는 `prompt_submit_outcome` 하나에 기댐, `continue: false` 미측정 | 필드가 있으면 kind 무관 "훅이 끝냄", 없을 때 `possibly_blocked`+attention, 0단계 실측, 검증되지 않는 것에 기록 |
| R6-2 | 답이 있은 뒤 막힌 턴 여는 메시지가 규칙 밖, uuid 연결 미정 | 마지막 전달 메시지 기준 규칙, `last_message_blocked`, uuid 연결 방법 명시 |
| R6-3 | 시작 스냅샷이 느리면 그 사이 작업자 파일이 시작 생성물로 | `.worktreeinclude` 복사본을 스냅샷에서 빼 기록을 작게 |

**계획 리뷰 멈춤:** 라운드마다 심각도가 내려가(1: 높음 8 → 4: 높음 0 → 6: 일상 사용에서 닿는 계약 위반 0) 여기서 멈춘다. 남는 세부는 PR별 리뷰(아래 프로토콜)와 S1 테스트가 맡는다.
