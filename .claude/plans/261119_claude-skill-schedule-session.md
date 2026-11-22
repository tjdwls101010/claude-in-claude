# claude 스킬: 예약 런과 세션 잇기 (작성 중 — 아직 구현 계획 아님)

> **구현 세션 첫 동작:** 하네스가 만든 심링크 `.claude/plans/fancy-crunching-dongarra.md`(이 파일을 가리킴)를 지운다. 이 파일(`261119_claude-skill-schedule-session.md`)만 보고 구현한다.

> **상태(2026-11-19):** 방향을 성진과 합의하는 중이다. 아래 장부의 "열린 질문"이 닫히기 전에는 이 파일로 구현하지 않는다.

## Context

`claude` 스킬 0.2.0의 `schedule`은 매 회차를 새 세션(`start`)으로만 띄운다. 성진의 질문: 예약 런이 특정 세션을 이어 가게 할 수 있는가, 그게 더 나은가. "세션을 잇는다"는 서로 다른 설계 넷을 가리킬 수 있어서(아래 열린 질문 1), 어느 것을 넣을지부터 합의한다.

## 합의 장부

| 종류 | 내용 | 출처 |
|---|---|---|
| 사실 | 예약 런은 지금 항상 새 세션이다: `schedule/execute.py`의 `_start_worker`가 `runs.start` 또는 한 명짜리 `batch(--worktree)`만 부른다 | `scripts/claude/schedule/execute.py:116` |
| 사실 | `runs.resume()`은 `origin`을 받지 않는다. Finish 스텝은 런을 `origin.job`으로 찾고(`find_by_origin_job`), "예약 실행이고 보는 사람이 없다"는 preamble도 `origin`으로 붙는다 → 예약에서 `resume`을 그대로 부를 수 없다 | `runs/commands.py:34`, `execute.py:428`, `claude_cli/argv.py:37` |
| 사실 | `resume`은 세션에 살아 있는 런이 있으면 거부한다(`refuse_live`, 세션 잠금 아래). 레지스트리가 모르는 프로세스(터미널의 `claude --resume`)는 보지 못한다 | `runs/create.py:35` |
| 사실 | worktree 세션의 `resume`은 그 worktree가 사라졌으면 거부한다. 예약의 Finish는 변경 없는 worktree를 지운다(`_clean_group`) → `--worktree` 예약과 세션 잇기는 그대로는 충돌한다 | `runs/commands.py:53`, `execute.py:307` |
| 사실 | slot 재시도(K4)는 read-only 런이 `failed`·`timed_out`·`orphaned`로 끝났을 때 한 번, 같은 프롬프트로 다시 돈다. 이어 가는 세션이면 반쯤 끝난 턴이 든 대화록 위에 같은 프롬프트가 다시 얹힌다 | `registry/schedules.py:111` |
| 사실 | 예약 정의의 진실은 워크플로 파일의 `# spec:` 줄(K2), 실행 상태는 `.claude-runs/.schedules/<name>/state.json`(런의 `origin`에서 다시 만들 수 있는 캐시) | `github/workflow.py:14`, `registry/schedules.py:1` |
| 사실 | claude 2.1.328: `--resume <id>`, `--fork-session`(resume과 함께, 새 세션 id), `--session-id <uuid>`, `--system-prompt-snapshot`(기본 on: resume은 처음 기록된 시스템 프롬프트를 컴팩션 전까지 그대로 보냄) | `claude --help` (2026-11-19) |
| 사실 | SKILL.md는 다섯 섹션(Handing work over / Several workers at once / Waiting, steering and collecting / Scheduling a worker / When something goes wrong)이고 `references/`는 없다(K29; `test_install`이 없음을 단정) | `.claude/skills/claude/SKILL.md`, `261117_claude-skill-schedule.md` K29 |
| 사실 | 스킬은 `~/.claude/skills/claude` → 이 레포 `.claude/skills/claude` 심링크로 설치돼 있다 | `ls -la ~/.claude/skills/claude` |
| 결정 | 실제로 쓸 상황은 **A: 이미 있는 작업자 세션을 정한 시각에 한 번 잇기**. 반복 예약에서 회차 간에 무엇이 이어져야 하는지는 "아직 모르겠다" → 실측을 보고 정한다. D(대화 중인 세션 잇기)·C(고정 세션의 사본)는 고르지 않았다 | 성진(2026-11-19) |
| 사실 | 작업자 요청은 1시간 캐시를 쓴다(`ephemeral_1h_input_tokens`만 참). 35분·11분 뒤의 `resume`은 첫 요청이 거의 전부 캐시 읽기였다(178,477 읽기 / 5,221 쓰기; 205,030 / 2,879). 1시간 넘게 지난 뒤의 resume 기록은 이 맥의 어느 레지스트리에도 없다 → 콜드 비용은 따로 잰다 | 이 레포 `.claude-runs/20261117-13*-review-pr2-*`의 `events.jsonl` |
| 사실 | **`total_cost_usd`는 resume을 넘어 세션 누적이다.** 같은 세션의 세 런이 0.1193 → 0.1527 → 0.1875(2·3일차 런의 토큰만으로는 1일차보다 비쌀 수 없다: 캐시 쓰기 25,167 vs 4,141). 지금 `result`·`log`·summary는 이 값을 그 런의 비용으로 보인다(`claude_cli/stream.py:333`의 주석은 "한 프로세스 안에서 누적"이라고만 안다) | 실측(scratchpad `sim-chain`, 2026-11-19) |
| 사실 | (반복 대조, sonnet·high·read-only, 같은 프롬프트 "매일 점검: 지난 점검 이후 새로 생긴 것과 이전 항목의 경과", 저장소를 날마다 바꿔 3일) 세 방식의 답 품질은 같았다 — 모두 2·3일차에 해결됨/새 항목/그대로를 맞게 갈랐다. ① **새 세션**: 아무 안내 없이 `.claude-runs/*/events.jsonl`을 스스로 뒤져 이전 답을 찾았다. 셸 호출 3→5→7, 런 입력 합계 13.0만→16.7만→21.5만 토큰, $0.114→0.130→0.141 — 레지스트리의 **모든** 런을 훑으므로 런이 쌓일수록 커진다 ② **같은 세션 잇기**: 첫 요청 문맥 2.9만→3.8만→4.2만 토큰(작은 일인데도 하루 약 4천), 런당 추가 비용 $0.033·$0.035 — 단 1분 간격이라 캐시가 따뜻했다 ③ **새 세션 + 직전 답 파일 경로 한 줄**: 셸 호출 2, 입력 합계 9.4만·9.6만, $0.102·$0.098로 일정 | 실측(scratchpad `sim-fresh`·`sim-chain`·`sim-pointer`) |
| 사실 | `timed_out`으로 끝난 세션을 같은 프롬프트로 `resume`하면 작업자는 처음부터 다시 해서 `completed`로 끝났다(세 단계 모두 재실행, 답에 이전 시도를 언급) → read-only 재시도(K4)는 이어 가는 세션에서도 성립한다 | 실측(scratchpad `sim-retry`, 런 `…retry-a-486b` → `…retry-b-cece`) |
| 사실 | 세션 대화록은 `cleanupPeriodDays`(기본 30일) 동안 쓰이지 않으면 조용히 지워진다 | `.tmp/docs_claude/settings-reference.md` `cleanupPeriodDays` |
| 사실 | (곁가지) 작업자의 셸은 zsh라 따옴표 없는 `grep --include=*.py`가 "no matches found"로 죽고, 세 작업자가 그 결과를 "TODO 없음"으로 보고했다. 이 계획의 범위 밖 | 실측(scratchpad `sim`, 런 `…pointer-d1-89f3`의 `log`) |

### 열린 질문

1. "세션을 잇는다"가 가리키는 설계 넷 중 무엇을 넣는가: (A) 알려진 세션을 정한 시각에 한 번 잇기 (B) 반복 예약이 매 회차 자기 직전 세션에 쌓기 (C) 반복 예약이 매 회차 고정한 브리핑 세션에서 갈라(fork) 시작 (D) 성진과 대화 중인 세션 자체를 헤드리스로 잇기.
2. (1의 답 뒤) 실측: 콜드 캐시에서 resume 비용(1턴 vs N턴), `-p --resume X --fork-session`이 보고하는 세션 id와 `--session-id` 병용, 한 세션에 두 프로세스, 세션 보존 기간(`cleanupPeriodDays`), 러너 잡이 같은 세션 저장소를 보는지.
3. 무인 실행이라 미리 정할 것: 이을 세션이 살아 있거나 없을 때(빨강·건너뜀·새로 시작), 수동 실행·재실행이 사슬을 전진시키는지, slot 재시도, `--worktree`와의 관계, 잇기를 끄는 플래그.
4. `references/`를 두지 않는다는 K29를 유지할지.
