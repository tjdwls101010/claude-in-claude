# claude 스킬: 예약 이름을 준 그대로 (`schedule --name`, 0.3.0)

> **구현 세션 첫 동작:** 하네스가 만든 심링크 `.claude/plans/merry-wondering-kernighan-of-1cf8a2bb-bcc6-45e4-b338-18597ab790f0.md`(이 파일을 가리킴)를 지운다. 이 파일(`261122_claude-skill-schedule-naming.md`)만 보고 구현한다.

> 이어서 `ToolSearch("select:TaskCreate,TaskUpdate,TaskList")`로 트래커를 열고 아래 "단계"를 태스크로 만든다(description = 그 단계의 완료 판정). `coding`·`skill-maker`는 `Skill`로 연다. 리뷰는 아래 "리뷰 프로토콜"대로 한다.

> **작업 위치 — 스킬 코드는 본 체크아웃에서 고치지 않는다.** `~/.claude/skills/claude`는 이 레포 본 체크아웃(`/Users/seongjin/Coding/claude in claude`)으로의 심링크이고, 볼트의 예약이 발화할 때마다 그 경로의 `cli.py`를 부른다(조사 시점의 다음 발화 2026-11-28 10:00). 반쯤 고친 트리가 그 순간 불리면 무인 실행이 빨갛게 끝나고, 볼트의 예약은 모두 `auto` 프로필 일회성이라 재시도되지 않는다. 그래서 **PR ①·②는 `git worktree`(별도 디렉터리)에서 하고**, 실제 검증은 그 worktree의 `cli.py`를 경로로 직접 불러서 한다(워크플로에는 부른 `cli.py`의 경로가 박힌다 — `util.entry_path`). worktree에서는 `Skill("claude")`로 스킬을 부르지 않는다(어느 쪽 사본이 잡힐지 알 수 없다). **본 체크아웃을 0.3.0으로 `git pull`하기 전에** 볼트에서 `schedule --list`와 `gh run list --repo tjdwls101010/Obsidian --status in_progress`·`--status queued`를 보고, 실행·대기 중인 잡이 없고 한 시간 안에 발화가 없을 때 당긴다. PR ⓪은 스킬 코드를 건드리지 않으므로 본 체크아웃에서 해도 된다.

> **이 계획의 승인이 겸하는 허락(성진, 2026-11-22):** ① 구현 세션은 실제 검증을 위해 private 임시 저장소(`tjdwls101010/claude-schedule-probe`)를 만들고, 임시 self-hosted 러너를 설치해 LaunchAgent 서비스로 돌리고(plist에서 `SessionCreate` 제거), 임시 디스패처 LaunchAgent를 설치할 수 있다. 끝나면 서비스 제거 → 러너 등록 해제 → 저장소 삭제 → `~/Library/LaunchAgents`·`~/Library/Logs`의 임시 항목 삭제까지 마친다. 성진의 기존 러너와 예약은 건드리지 않는다. ② `.claude/plans/`의 계획 파일을 **있는 그대로** 공개 저장소에 커밋한다. ③ 릴리스 뒤 마지막 단계로 볼트(`tjdwls101010/Obsidian`)의 예약을 새 양식으로 옮긴다 — **옮길 이름 표를 성진이 승인한 뒤에만**(아래 "볼트 이전").

## 승인 전에 볼 것: 성진이 고르지 않았지만 쓰면서 체감할 판단

아래는 질문으로 합의한 것이 아니라 클로드가 근거를 들어 정한 것이다. 승인은 이것들도 받아들이는 것이므로, 바꾸고 싶으면 승인 전에 말한다.

- **옛 예약은 모양까지 그대로 둔다**(D3·D10): `claude-<name>.yml`로 만들어진 예약은 고친 스킬에서도 그대로 돌고, 같은 `--name`으로 다시 부르면 파일을 옮기지 않고 그 파일을 고치며, Actions 표시 이름도 `claude · <name>` 그대로다. 새 양식으로 바꾸려면 새 이름으로 예약하고 옛 것을 지운다(볼트 이전이 하는 일).
- **볼트 이전의 실제 크기**: 오늘 하이픈형으로 바꾼 일회성 27개(모두 `auto`·worktree)를 다시 옮기는 일이고, 볼트 main에 커밋이 54개 생긴다.
- **이름은 80자까지, 이모지는 두 자로 센다**(D1): 디스패처 plist 파일명이 가장 긴 owner·repo에서도 이 맥의 파일명 한도(255)에 들어가게.
- **이름에 못 쓰는 것**(D1): `/ \ : * ? " < > |`, `${{`, 제어 문자·보이지 않는 서식 문자·특수 공백, `-`나 공백으로 시작, `.`이나 공백으로 끝. `${{`는 GitHub가 워크플로 파일 안에서 계산하려 들어 워크플로가 깨진다(실측).
- **Windows 장치 이름으로는 새 예약을 못 만든다**(D4): `con`, `nul`, `aux`, `prn`, `com1`…`lpt9`(성진이 고른 "Windows에서 체크아웃이 깨지는 이름 거부"를 끝까지 적용; 옛 예약에는 적용하지 않는다).
- **대소문자·한글 정규화만 다른 이름은 거부한다**(D4·D11): GitHub에서는 두 파일이지만 이 맥에서는 상태 디렉터리·디스패처·체크아웃 파일이 하나로 겹쳐, 한 예약이 다른 예약의 회차를 "이미 실행됨"으로 건너뛰거나 디스패처를 지울 수 있다.
- **`--worktree` 예약의 그룹·브랜치 이름은 ASCII 슬러그다**(D5): `261128_SS_외국인순매수` → 그룹 `261128-ss-<런 id>-1`, 브랜치 `worktree-261128-ss-<런 id>-1-1`. 한글뿐인 이름은 `schedule-<런 id>-1`. 볼트의 예약이 모두 worktree라 summary의 "Continue on your Mac"에 이 이름이 보인다.
- **`schedule --list`는 접두사 대신 파일 첫 줄로 예약을 찾는다**(D7): 기본 브랜치의 워크플로 파일 전부를 한 번에 읽는다. 손으로 쓴 워크플로는 헤더가 없어 목록에 나오지 않는다. 행에 `file`이 더해지고, GitHub가 아직 등록하지 않은 파일의 `state`는 `unknown`이다.
- **SKILL.md는 바뀌지 않는다**(성진 결정 + 확인): 이름에 관한 사실은 `schedule --help`가 말한다. `references/`도 여전히 없다(K29).
- **대조 실험을 한 장면 돌린다**(테스트 seam의 S6 시나리오 10): SKILL.md에 문장을 넣지 않기로 했으므로, "양식을 말로 들은 모델이 `--help`만 읽고 그 이름 그대로 예약하는가"를 한 번 확인한다. SKILL.md에 문장을 넣을지 정하려는 것이 아니다 — 실패해도 문장은 넣지 않고 그 출력을 성진에게 보여 준다. 빼고 싶으면 승인 전에 말한다.
- **공개 플러그인의 동작 변경이다**: 0.3.0부터 누구의 새 예약이든 접두사 없이 `<name>.yml`이 된다(CHANGELOG에 명시). 손으로 쓴 `claude-X.yml`이 있는 저장소에서 `--name X`는 이제 거부되지 않고 `X.yml`을 만든다.
- **계획 파일이 공개된다**: 이 파일과 이전 계획 셋에 든 private 저장소 이름, 러너·LaunchAgent 이름, 볼트의 예약 이름(티커)이 공개 이력에 남는다(성진 결정).

## Context

`claude` 스킬 0.2.0의 `schedule`은 예약 이름을 `^[a-z0-9][a-z0-9-]{0,23}$`로만 받고, 워크플로 파일을 `claude-<name>.yml`, Actions 표시 이름을 `claude · <name>`으로 고정한다. 성진은 옵시디언 볼트의 예약을 `yymmdd_{티커}_{설명}`(예: `261128_SS_외국인순매수`)으로 부르고 싶지만 밑줄·대문자·한글·접두사 없음이 모두 막혀 있다. Actions 목록과 `.github/workflows/`는 사람이 "무엇이 언제 예약돼 있나"를 훑는 화면이고 그 정렬·식별 방식은 저장소마다 다르므로, 스킬은 양식을 정하지 않고 **준 이름을 그대로** 파일명과 표시 이름에 쓴다. 양식 자체(관례)는 스킬에 넣지 않는다 — 사람이 말하거나 자기 지시문에 둔다.

제한의 출처는 GitHub가 아니라 스킬 내부였다: 이름을 worktree 그룹 이름에 그대로 재사용해서 24자·소문자가 됐고, 접두사는 목록 조회를 싸게 하려던 것이다. 실측에서 GitHub Actions·`gh`·launchd는 한글·공백·이모지 이름을 모두 받았다. 그래서 재작성이 아니라 **이름이 흐르는 배관만** 고친다. 조심할 곳은 둘이다: 이미 커밋된 0.2.0 워크플로가 고친 `cli.py`를 옛 플래그로 계속 부른다는 것(호환), 이름이 자유로워지면 이 맥에서 서로 다른 예약의 로컬 키가 겹칠 수 있다는 것(소유 확인).

## 합의 장부

| 종류 | 내용 | 출처 |
|---|---|---|
| 결정 | 계획 파일명은 `261122_claude-skill-schedule-naming.md`(이전 계획들의 관례), 하네스 경로는 이 파일을 가리키는 심링크 | 성진(파일명을 먼저 바꾸라는 요청), `.claude/plans/` |
| 사실 | 이름 규칙은 `NAME_RULE = ^[a-z0-9][a-z0-9-]{0,23}$` 하나이고 `schedule`·`unschedule`·`cli.py`가 같은 문구로 거부한다. 밑줄·대문자·한글·25자 이상은 모두 exit 2. (`$`가 끝 줄바꿈 앞에서도 맞아 `"foo\n"`도 통과한다) | `schedule/spec.py:18`, `cli.py:444,450`, 코덱스 재현 |
| 사실 | 이름 하나가 닿는 곳: 워크플로 파일 `claude-<name>.yml`(`github/workflow.py:17`), 표시 이름 `name: claude · <name>`과 `run-name: <name> · …`(`workflow.py:95-96`, 따옴표 없는 YAML 스칼라), `concurrency.group: claude-<name>`(`:114`), 두 스텝의 `--name`·`--workflow` 플래그(`:60-65`), LaunchAgent 라벨 `claude-schedule.<owner>-<repo>.<name>`과 로그 경로(`spec.py:29`, `define.py:23`), 로컬 상태 `.claude-runs/.schedules/<name>/`(그 `state.json`에 `name`이 있다)와 잠금 `schedule-<name>.lock`(`registry/schedules.py:20-30`), worktree 그룹 `<name>-<run id>-<attempt>`(`execute.py:120,174` — worktree 런의 라벨은 이 그룹 이름이다, `batch/spawn.py:54`), worktree가 아닌 런의 라벨(→ 런 id 슬러그 `[^a-z0-9-]+` → `-`, 24자, `registry/runs.py:118`), summary 제목(`summary.py:119-133`), summary의 안내 문장 속 한 겹 백틱 명령(`execute.py:155,360-365,404`), 주석 제목(`github/job.py`가 `%`·`:`·`,`를 이스케이프), 턴 앞머리(K11) | 코드, 두 리뷰 |
| 사실 | 24자 한도의 출처는 K10 하나다: worktree 그룹 이름(40자, `registry/groups.py:14`)에 11자리 런 id와 attempt를 붙여야 해서 | `spec.py:17` 주석, `261117_claude-skill-schedule.md` K10 |
| 사실 | 접두사 `claude-`가 하는 일은 둘: `schedule --list`가 `actions/workflows` 목록에서 파일명 접두사로 후보를 고르는 것(`define.py:258`, `github/api.py:135`), 소유 판정에서 `spec.name == 파일명에서 접두사와 .yml을 뗀 것`(`define.py:73`). 소유의 실제 근거는 첫 줄 `HEADER`와 `# spec:` 줄이다(`workflow.py:135`; `parse_spec`은 `name`의 타입을 보지 않는다) | 코드 |
| 사실 | 커밋된 워크플로는 기록된 절대 경로의 `cli.py`를 `__scheduled run\|finish --name … --workflow claude-<name>.yml …`로 부른다 → **이미 커밋된 0.2.0 워크플로가 새 코드를 옛 플래그로 부른다**. 숨긴 `__scheduled`의 플래그와 `# spec:` 키는 호환 표면이다. 일회성의 Finish는 넘겨받은 `--workflow` 대신 `workflow_file(name)`으로 파일명을 다시 만든다(`execute.py:357`). Finish는 worktree 그룹을 다시 계산하지 않고 잡 기록(`rec["group"]`)에서 읽는다(`execute.py:465`). 기록되는 `cli`는 부른 경로 그대로다(심링크를 풀지 않는다, `util.py:103`) | `workflow.py:59-66`, `execute.py`, `cli.py:305-318`, 두 리뷰 |
| 사실 | 지금 `unschedule`은 원격 파일이 없어도 디스패처 plist를 지우고 상태 디렉터리를 지운다(`define.py:214-237`); `remove_agent`는 라벨이 로드돼 있지 않아도 그 경로의 plist가 있으면 지운다(`launchd/agents.py:83`). 디스패처 라벨은 `<owner>-<repo>.<name>`을 이어 붙인 것이라 저장소 경계가 모호하다(`a/b.c`의 `d`와 `a/b`의 `c.d`, `a-b/c`와 `a/b-c`가 같은 라벨) | 코드, 코덱스 재현 |
| 사실 | 볼트의 예약은 지금도 한글 프롬프트(스텝 env)와 이모지가 든 프로젝트 경로(`--project /Users/seongjin/💎Obsidian`, `run:` 줄의 셸 인자)를 러너 잡으로 넘기며 돌고 있다 → 비ASCII 인자가 러너·bash·`uv run`을 지나 `cli.py`에 그대로 닿는다는 것은 이미 운영으로 확인된 사실이다 | 볼트의 워크플로, 볼트 실행 이력 |
| 사실 | 볼트(`tjdwls101010/Obsidian`)에는 스킬이 쓴 예약이 28개 있다: 오늘(2026-11-22) 볼트 세션이 `inv-<티커>-<yymmdd>`에서 `<yymmdd>-<티커>-<설명>`으로 바꾼 일회성 27개(모두 `"profile": "auto"`, `"worktree": true`, spec의 `cli`는 `/Users/seongjin/.claude/skills/claude/scripts/cli.py`; 가장 이른 것 `261128-skh-flow`가 2026-11-28 10:00)와 이미 지난 `inv-ant-2611` 하나. 볼트의 `CLAUDE.md`·스킬 문서에는 예약 이름 관례가 적혀 있지 않고, 과거 이름이 `inv-ss-2611`, `inv-ss-2701a`처럼 흔들려 뒤에 고친 이력이 있다 | `gh api …/contents/.github/workflows`, 볼트 `git log`, claude 리뷰의 볼트 grep |
| 사실 | 볼트 세션은 이름 바꾸기를 스스로 했다: 워크플로들의 `# spec:`을 모아 프롬프트를 파일로 쓰고 `schedule --name <새 이름> --prompt-file … --at … --profile … --model … --effort … --timeout …` 뒤 `unschedule --name <옛 이름>`. 옮겨진 다섯 개를 옛 spec과 비교하니 `name`·`definition` 말고 달라진 키가 없었다(`timeout` 5400 유지). 커밋 메시지는 볼트 관례(`chore: 예약 작업자 <옛>를 <새>로 이름 변경` / `chore: 이름 바꾼 예약 작업자 <옛> 제거`). 그 세션에서 성진은 "`-`보다는 `_`가 좋긴한데, 그렇게는 안되는거야?"라고 물었다 | 볼트 세션 기록(`de160a26…jsonl`), `git show`로 비교 |
| 사실 | 스킬은 공개 플러그인(`headless-workers` 0.2.0, 저장소 `tjdwls101010/claude-in-claude`는 PUBLIC)이고 `~/.claude/skills/claude`는 이 레포로의 심링크다. SKILL.md는 다섯 섹션이고 이름 형식을 말하는 문장이 없다. `references/`는 없다(K29). 태그 `v0.1.0`·`v0.2.0`이 있고 지금 스크립트는 `v0.2.0`과 같다. 버전 키는 `.claude-plugin/plugin.json`에만 있다. `.gitignore`가 `.claude/plans/`를 무시한다 | `.claude-plugin/`, `git tag`, `.gitignore`, 코덱스 확인 |
| 결정 | **이름은 하나다.** `--name`이 워크플로 파일명(`<name>.yml`)과 Actions 표시 이름에 그대로 쓰이고, 밑줄·대문자·한글을 받는다(예: `261128_SS_외국인순매수`). 파일명 ASCII + 별도 `--title` 안은 택하지 않았다 | 성진(클로드 추천, 2026-11-22) |
| 결정 | **접두사를 없앤다**: 파일명의 `claude-`, 표시 이름의 `claude · `. 묶어 보고 싶은 저장소는 이름을 직접 그렇게 짓는다. 기본 유지 + 끄는 플래그 안, 표시 이름에서만 떼는 안은 택하지 않았다 | 성진(클로드 추천, 2026-11-22) |
| 결정 | **양식(관례)은 스킬에 넣지 않는다.** 저장소에 패턴을 저장해 CLI가 강제하는 장치도, 스킬 안의 양식 설정도 만들지 않는다("이러한 관례는 이후에 사용자가 직접 말하던가 하겠지. 굳이 스킬에 넣을 필요가 있나") | 성진(2026-11-22) |
| 결정 | **SKILL.md에 이름에 관한 문장을 싣지 않는다.** 이름의 뜻(파일명이자 Actions 이름)과 바꿀 때의 사실은 `schedule --help`에만 적는다. e2e 대조로 정하는 안(클로드 추천)과 실험 없이 싣는 안은 택하지 않았다 | 성진(2026-11-22) |
| 결정 | **Windows에서 체크아웃이 깨지는 문자도 거부한다**: `\ : * ? " < > \|`와 이름 끝의 점·공백. 스킬이 깨지는 것만 거부하는 안은 택하지 않았다. 넓히는 것은 뒤에도 쉽고 좁히는 것은 기존 예약을 깬다 | 성진(클로드 추천, 2026-11-22) |
| 결정 | 계획 세션에서 GitHub(private 임시 저장소)와 launchd(임시 LaunchAgent)를 실측한다. 구현 세션의 실제 검증도 **임시 저장소 + 임시 러너**로 한다(볼트 러너에서 하는 안, 자동 테스트만 하는 안은 택하지 않았다) | 성진(클로드 추천, 2026-11-22) |
| 결정 | **볼트의 기존 예약 이전은 구현 세션의 마지막 단계**(클로드 추천은 계획 밖이었다). 새 이름의 설명은 **구현 세션이 각 프롬프트의 사건을 한글로 짧게 써서 '옛 이름 → 새 이름' 표로 제안하고, 성진이 고치거나 승인한 뒤에만 실행**한다. 티커는 대문자. 이미 돌고 꺼진 일회성은 그대로 두고, 발화가 임박했거나 실행 중인 예약은 건너뛴다 | 성진(2026-11-22) |
| 결정 | **`.claude/plans/`를 gitignore에서 빼고 계획 파일을 있는 그대로 전부 커밋한다**(공개 저장소임을 알고; 클로드 추천은 민감한 부분을 가리고 올리는 것이었다). 코드 주석의 `K10`·`probe 11` 같은 번호가 가리킬 문서가 저장소에 생긴다 | 성진(2026-11-22) |
| 결정 | **구현 세션의 리뷰·검증 위임은 `codex`가 아니라 `claude` 스킬로, 모델은 sonnet.** 코덱스 한도가 찼고, 검증용으로 opus·fable까지 쓸 필요는 없다 | 성진(2026-11-22) |
| 사실 | (N1) Contents API는 워크플로 파일명으로 거의 모든 문자를 받았고 Actions가 전부 `active`로 등록했다: 한글 NFC·NFD(서로 다른 경로로 남음), 대문자/소문자(서로 다른 파일), 공백, 이모지, 앞·뒤 점, `+ & ' , @ = ~ ! ( ) [ ] { } $ ; : " * < > \| \ ^` 와 백틱. `name:`과 `concurrency.group`을 JSON 문자열(YAML 큰따옴표)로, `run-name:`을 `"<JSON 이스케이프한 이름> · ${{ inputs.source \|\| github.event_name }}"`로 쓰면 그 이름 그대로 표시된다(런 제목 `261128_SS_외국인순매수 · dispatcher`) | 실측(scratchpad `probe/p1_put.json`, `p2_workflows.json`, `p4_runs.json`) |
| 사실 | (N1) `gh api`에 경로를 날것으로 주면 `#`은 뒤가 잘려 다른 파일(`a`)이 생기고, `?`는 쿼리로 읽혀 422, `%`는 URL 파싱 오류다. 파일명을 `urllib.parse.quote(file, safe="")`로 인코딩하면 Contents GET/PUT/DELETE와 `actions/workflows/<file>` 조회·enable·disable이 모든 이름에서 된다(`a#b c.yml` 포함). 지금 `github/api.py`는 파일명도 `?ref=<branch>`도 인코딩하지 않는다 | 실측(`p1_put.json`, `p3_dispatch.json`), `github/api.py:94-132` |
| 사실 | (N2) `gh workflow run <파일명> --repo … --ref main -f source=dispatcher`는 한글·공백·이모지·`#`·`%`·`?` 이름 모두에서 런을 만들었다(39개 전부 `success`). 실패는 둘: 이름이 `-`로 시작하면 gh가 플래그로 읽는다(`unknown shorthand flag`), 경로가 255자를 넘으면 HTTP 422 | 실측(`p3_dispatch.json`, `p4_runs.json`) |
| 사실 | (N2) **워크플로 경로(`.github/workflows/<file>`)는 유니코드 255자까지다.** 넘는 파일도 커밋·등록은 되지만 깨진 워크플로가 되어, 그 뒤 **저장소의 모든 push마다 실패한 런이 하나씩 생긴다**(실측 29회). 한글 90자(270바이트) 이름은 문제없었다 — 한도는 바이트가 아니라 문자 수 | 실측(`p4_runs.json`의 `failure` 29건, 오류 문구 "Workflow files paths can be at most 255 unicode characters") |
| 사실 | (N3) 기본 브랜치의 워크플로 디렉터리 **전부의 이름·종류·본문**을 GraphQL 한 번으로 받는다: `repository(owner:, name:) { object(expression: $e) { ... on Tree { entries { name type object { ... on Blob { byteSize isTruncated text } } } } } }`, `$e = "<branch>:.github/workflows"`(변수로 넘긴다) → 39개 모두 `text`가 왔고 `isTruncated` 없음. 디렉터리가 없으면 `{"data":{"repository":{"object":null}}}`, 저장소가 없으면 `data.repository: null`과 `errors[].type: "NOT_FOUND"`(stderr에 `gh: Could not resolve to a Repository …`) | 실측(`p5_graphql.json`, 2026-11-22) |
| 사실 | (N4) **파일명을 바꾸면 GitHub에는 새 워크플로다.** 지운 워크플로는 `actions/workflows` 목록에서 빠지고 파일명으로 조회하면 `state: "deleted"`이며, 그 런들은 옛 경로·옛 `workflow_id`로 남는다 | 실측(`Case_Test.yml` 삭제 뒤 조회) |
| 사실 | (N5) launchd는 라벨에 한글·공백·이모지·따옴표·`$ & ;`·한글 150자를 받았다: `bootstrap`·`print`·`kickstart`·`bootout` 모두 0, 남은 것 없음 → 디스패처 라벨에 이름을 그대로 쓸 수 있다 | 실측(`p6_launchd.py`) |
| 사실 | (N6) 이 맥의 파일시스템(APFS)은 **정규화와 대소문자를 구분하지 않는다**: NFC로 만든 디렉터리가 NFD 경로로도 존재하고 `Case_Test`가 `case_test`로도 존재한다. GitHub에서는 그 둘이 서로 다른 파일이다. 파일명 한도는 UTF-16 단위 255(한글·ASCII 255자 가능·256자 실패, 이모지는 2단위라 250개에서 실패) | 실측 |
| 사실 | (N7) summary 제목에 이름을 날것으로 넣으면 `_a_ *b* [c](x) <e>`가 강조·링크·태그로 렌더링되고(`<e>`는 사라짐), ASCII 구두점을 백슬래시로 이스케이프하면 글자 그대로 나온다. `261128_SS_외국인순매수`와 `270225_NVDA_Q4 실적 (가이던스)`는 이스케이프 전후가 같게 보인다 | 실측(`gh api -X POST markdown -f mode=gfm`) |
| 사실 | (N8) **이름에 `${{`가 있으면 워크플로를 만들 수 없다.** 최상위 `name:`에 날것으로 쓰면 "The expression is not closed", `${{ '${{' }}`로 이스케이프해 쓰면 "A template expression is not allowed in this context" — 두 경우 모두 파일은 커밋·등록되지만 디스패치가 HTTP 422이고 push마다 실패한 런이 생긴다 | 실측(`tpl-raw-name.yml`, `tpl-esc-name.yml`, `tpl-raw-all.yml`, 2026-11-22; 두 리뷰의 지적) |
| 사실 | 실측에 쓴 임시 저장소는 지웠고(조회 404) 임시 LaunchAgent·로그는 남지 않았다. 구현 세션이 같은 방식으로 다시 만든다(맨 위 허락) | 실측(2026-11-22) |
| 판단 | **이름 바꾸기 명령은 만들지 않는다**(Model over machinery): 모델이 지금 명령만으로 설정을 잃지 않고 옮겼다(위 볼트 세션). 이력이 갈리는 것은 GitHub의 성질이라 명령으로도 못 막는다 | 클로드 |
| 판단 | **D1 이름 규칙.** 먼저 NFC로 정규화하고(이후 모든 곳에서 그 꼴; 응답의 `name`이 그것), 다음만 거부한다(exit 2) — 각각 이유가 있다: 빈 이름; UTF-16 단위 80 초과(디스패처 plist 파일명 `claude-schedule.<owner ≤39>-<repo ≤100>.<name>.plist`가 이 맥의 255 단위에 들어가야 한다: 고정 163 + 80 = 243; 92까지 가능하지만 80으로 둔다. 워크플로 경로는 최대 102자라 N2의 255자도 만족); `/`(경로가 된다); `\ : * ? " < > \|`와 끝의 `.`·공백(Windows 체크아웃, 성진 결정); `${{`(N8); 제어 문자(Cc)·줄/문단 구분자(Zl, Zp)·U+0020이 아닌 공백(Zs)·비할당/대리/사용자 영역(Cn, Cs, Co)·**U+200C와 U+200D를 뺀** 서식 문자(Cf) — 보이지 않는 차이나 방향 뒤집기를 만드는 문자이고, 두 결합자는 이모지(👩‍💻)와 일부 문자 체계가 쓰므로 받는다; `-`로 시작(gh가 파일 인자를 플래그로 읽는다, N2 — 디스패처의 argv와 스킬이 출력하는 모든 `gh workflow …` 명령에 파일명이 인자로 들어간다); 공백으로 시작(보이지 않는 차이). 그 밖의 문자(모든 문자 체계의 글자·숫자·결합 기호, `_ - .` 공백, 이모지, `+ & ' , @ = ~ ! ( ) [ ] { } $ ; # % ^`, 백틱)는 받는다. 0.2.0이 실제로 만든 이름(`[a-z0-9-]`)은 모두 새 규칙도 통과한다. 보이지 않는 문자를 전부 막지는 못한다(결합 기호 U+034F 등) — 한계로 둔다. **규칙이 사는 곳은 그 사실의 주인을 따른다**(skill-maker의 "남이 가진 시스템의 지식은 그 이름의 서브패키지에"; 지금 코드의 `unsafe_text`·`calendar_entries`가 같은 방식이다): 워크플로 파일명과 `gh`가 받지 못하는 것(`/`, `${{`, 경로 255자, 선두 `-`, 저장소 파일명으로서의 Windows 금지 문자·끝의 점과 공백)은 `github/workflow.py`가 "이 이름이 워크플로 파일이 될 수 없는 이유"를 돌려주는 함수로 갖고(D4의 장치 이름도 여기), plist 파일명 길이는 `launchd`가 갖고, 대소문자·정규화를 무시한 파일명 키(D4·D11이 함께 쓴다)는 `util.py`에 둔다; `schedule/spec.py`의 `check_name`은 정규화하고 이들을 불러 거부로 바꾸는 한 곳이며, 보이지 않는 문자·선두 공백처럼 어느 시스템의 것도 아닌 규칙만 스스로 갖는다. `cli.py`의 중복 검사는 지운다. **거부 메시지는 규칙이 아니라 이유를 말한다**(예: "`${{` starts an expression GitHub evaluates inside a workflow file", "`:` cannot be checked out on Windows") — 모델이 사람에게 왜 안 되는지 옮길 수 있게 | 클로드(N1·N2·N5·N6·N8, 성진 결정, 코덱스 11, 프레임 감사) |
| 판단 | **D2 파일과 표시.** 새 예약의 파일은 `<name>.yml`, `name:`은 이름 그대로, `run-name:`은 `<name> · <mode\|source\|event>`(지금과 같은 꼴에서 접두사만 없음). YAML로 쓰는 법: `name:`과 `concurrency.group`은 `json.dumps(text, ensure_ascii=False)`(이름에 `${{`가 없으므로 `_escape`가 할 일이 없다); **`run-name:`은 이름 부분만 JSON 이스케이프하고 고정 표현식을 같은 큰따옴표 안에 이스케이프 없이 붙인다** — 줄 전체를 기존 `_string`에 넣으면 고정 표현식의 `${{`까지 무력화되어 제목에 표현식 글자가 그대로 나온다. 지금은 따옴표 없는 스칼라라 `#`·따옴표가 든 이름에서 YAML이 깨진다. `concurrency.group`은 `claude-<name>` 그대로 둔다(저장소 전체에서 겹치면 안 되는 내부 키라 네임스페이스를 유지). 파일명은 spec 줄에 기록하지 않는다 — 파일이 놓인 경로가 사실이고, 스텝의 `--workflow`가 실행기에 그것을 넘긴다 | 클로드(N1·N8, 두 리뷰) |
| 판단 | **D3 이미 있는 예약 찾기(옛 형식 호환).** `--name X`의 후보 파일은 `X.yml`, 그리고 `X`가 옛 규칙(`[a-z0-9][a-z0-9-]{0,23}` 전체 일치)에 맞으면 `claude-X.yml`. 각 후보를 읽어 **이 예약의 파일**인지 본다: `HEADER`로 시작하고 spec이 읽히고 `spec.name`이 문자열 `X`와 같다. ① 하나만 이 예약의 파일이면 그것(옛 파일이면 제자리 수정 — 옮기면 이력이 갈린다, N4) ② 둘 다면 두 경로를 말하며 거부 ③ 없으면 새 예약이고 파일은 `X.yml` — 그런데 `X.yml`이 이미 있으면(남이 썼거나 다른 예약의 파일) 거부("exists and is not this schedule; choose another --name"). 후보가 `HEADER`로 시작하는데 spec 줄이 읽히지 않으면 지금처럼 거부("fix or delete the file"). `HEADER`가 없는 `claude-X.yml`은 이 예약과 무관하므로 무시한다(0.2.0은 거부했다 — `X.yml`을 만들 것이라 충돌이 없다). 경로에 파일이 아니라 디렉터리가 있으면(Contents API가 목록을 준다) "있고 이 예약이 아님"으로 다룬다. `unschedule`도 같은 선택을 쓰고, ③에서는 `workflow: absent`(단 `X.yml`이 있고 이 예약이 아니면 지금처럼 거부). 걸어 보기: 옛 `foo`(`claude-foo.yml`)와 손으로 쓴 `foo.yml`이 함께 있으면 `--name foo` → ①(옛 파일); 옛 `foo`가 있을 때 `--name claude-foo` → 후보 `claude-foo.yml`(spec.name이 `foo`라 이 예약 아님)과 `claude-claude-foo.yml`(없음) → ③에서 `claude-foo.yml`이 이미 있어 거부; 옛 `foo`와 옛 `claude-foo`(`claude-claude-foo.yml`)가 함께 있으면 `--name claude-foo` → ① | 클로드(코덱스 6, claude 리뷰) |
| 판단 | **D4 겹치는 이름 거부(새 예약을 만들 때).** 만들기 전에 기본 브랜치의 워크플로 디렉터리 전부(N3)를 보고, `키(s) = NFC(casefold(NFC(s)))`로 ① 새 파일명과 키가 같은 다른 항목(파일·디렉터리·심링크 무엇이든)이 있거나 ② 스킬이 쓴 다른 예약의 `spec.name`이 새 이름과 키가 같으면 거부한다(exit 1, 겹치는 상대를 말함). 이유: 이 맥에서 둘은 상태 디렉터리·잠금·디스패처 plist·체크아웃 파일이 하나다(N6). ②는 옛 `claude-foo.yml`(이름 `foo`)과 새 이름 `Foo`의 겹침도 잡는다. 같은 자리에서 Windows 장치 이름(`CON`·`PRN`·`AUX`·`NUL`·`COM`/`LPT` + `0-9`·`¹²³`, 첫 점 앞 부분, 대소문자 무시)도 거부한다 — 새 파일을 만들 때만이라 옛 예약 `claude-aux.yml`은 영향이 없다. **검사는 두 번**: 잠금 전의 `refusals_first`에서(거부가 이 맥에 아무것도 쓰지 않는다는 기존 성질 유지, `--dry-run`도 여기서) 그리고 잠금 안에서 커밋 직전에(잠금 파일도 대소문자를 구분하지 않아 같은 맥의 `foo`·`Foo` 동시 생성이 직렬화된다) — 409 뒤 재시도에서도 다시. `casefold`는 APFS보다 넓게 접을 수 있다(ß = ss): 더 거부할 뿐이다. 서로 다른 맥에서 동시에 처음 만드는 경합은 막지 않는다(한계) | 클로드(N6, 코덱스 7·11) |
| 판단 | **D5 기계가 쓰는 키.** 이름을 그대로 쓰는 곳: LaunchAgent 라벨과 로그 경로(N5), `.schedules/<name>/`와 `schedule-<name>.lock`, worktree가 아닌 런의 라벨, `origin.name`, 턴 앞머리. **worktree 그룹만 슬러그**: `<slug>-<run id>-<attempt>`, slug = 이름을 소문자로 바꾸고 `[^a-z0-9-]+`를 `-`로, 양끝 `-` 제거, **전체가 40자에 들어가게 `40 − len("-<run id>-<attempt>")`로 자르고** 다시 끝 `-` 제거, 비면 `schedule` — 그룹 이름 규칙(`registry/groups.py`)과 Claude Code `--worktree`·git 브랜치 이름이 받는 범위에 머문다. 그룹은 런 id로 유일하므로 슬러그가 겹쳐도 충돌하지 않는다. worktree 런에서 예약 이름은 `origin.name`으로 남는다(라벨은 그룹 이름). 한 곳(`schedule/spec.py`의 `worktree_group`)에서 만들고 `execute.py`의 Run 쪽 두 군데(`:120`, `:174`)가 그것을 쓴다; Finish는 지금처럼 잡 기록의 `group`을 읽으므로 옛 코드의 Run이 만든 그룹도 정리한다 | 클로드(코덱스 12) |
| 판단 | **D6 GitHub 호출.** `github/api.py`가 파일명을 경로에 넣을 때 항상 `quote(file, safe="")`로, `ref` 값도 `quote`로 인코딩한다(N1). `list_workflows(repo, prefix)`는 없애고 둘로 바꾼다: `list_workflow_files(repo, branch)` → `[{file, kind, text}]`(N3의 GraphQL 한 번; `kind`는 blob·tree 등, `text`는 `.yml`/`.yaml` blob의 본문 — GraphQL이 본문을 주지 않았거나 잘랐으면 그 파일만 `read_workflow`로 다시 읽어 채운다; 디렉터리가 없으면 빈 목록)와 `workflow_states(repo)` → `{file: state}`(지금의 쪽수 넘기는 `actions/workflows`). `data.repository: null`과 그 밖의 GraphQL `errors`는 `api.py` 안에서 `GitHubError`로 바꾼다. `read_workflow`는 Contents API가 목록(디렉터리)을 줄 때를 구분해 알린다 | 클로드(N1·N3, 코덱스 5·7·8) |
| 판단 | **D7 `schedule --list`.** 워크플로 파일 전부에서 `HEADER`로 시작하고 spec이 읽히며 `name`이 문자열인 것만 행으로 낸다(접두사 무관, 옛 형식 포함), `name` 다음 `file` 순으로 정렬. 행에 `file`을 더한다. `state`는 `workflow_states`에서: `active`, 그 밖의 값은 `disabled`, GitHub가 그 파일의 워크플로를 아직 모르면 `unknown`. `orphans`는 D11의 소유 확인을 거친 것만. 스킬이 사람이 붙여 넣을 명령으로 내는 문자열은 이름·파일명을 `shlex.quote`로 감싼다: `schedule`의 `next.command`·`warnings`, `--list`의 `fix`, 실행기의 주석·summary 안내(`gh workflow enable/disable <file>`, `unschedule --name <name>`, `schedule --name <name> --project …`). summary 안의 그런 명령은 `summary._code`로 감싸고, `_code`는 본문의 가장 긴 백틱 연속보다 긴 구분자를 쓰게 고친다(지금은 두 겹까지만) | 클로드(코덱스 4·8) |
| 판단 | **D8 실행기(옛 플래그 호환).** `__scheduled`는 받은 `--name`을 검사·정규화하지 않는다(워크플로가 준 그대로). 일회성 Finish(`_end_one_off`)는 넘겨받은 `--workflow`를 쓰고, 없을 때만 `claude-<name>.yml`로 되돌아간다 → 옛 워크플로(`--workflow claude-X.yml`)와 새 워크플로(`--workflow X.yml`)가 각자 자기 파일을 끈다. 디스패처 라벨·상태 키는 이름이라 옛 예약도 그대로 맞는다. 업그레이드 순간에 돌던 잡은 Run이 옛 코드, Finish가 새 코드일 수 있다: Finish는 그룹을 잡 기록에서 읽고 `definition` 비교(K8)가 그대로라 성립한다(S5에서 실측) | 클로드(두 리뷰) |
| 판단 | **D9 summary 제목.** 이름을 제목에 넣을 때 **`-`를 뺀** ASCII 구두점 앞에 백슬래시를 둔다(N7; `-`는 줄 중간에서 뜻이 없고, 빼야 기존 fixture의 `nightly-docs`가 그대로다). `@멘션`·`#123`·`www.` 자동 링크·`$수식$`도 이것으로 막힌다. 성진이 고른 샘플 B의 모양은 그대로다. 이스케이프는 `schedule/summary.py`의 한 함수로 두고 제목에 쓴다; 구현 때 `summary.py`·`execute.py`에서 이름이 마크다운 본문에 날것으로 들어가는 다른 자리를 grep으로 찾아, 글이면 같은 함수를, 명령이면 D7의 `_code`를 쓴다 | 클로드(N7, 두 리뷰) |
| 판단 | **D10 옛 예약은 모양도 그대로.** 파일이 `claude-<name>.yml`인 예약은 표시 이름을 `claude · <name>`으로 렌더링한다 — 이 줄도 새 렌더러의 `json.dumps` 따옴표 꼴(`name: "claude · <name>"`)로 쓰고, 그 밖의 줄은 새 렌더러와 같다(0.2.0의 따옴표 없는 줄을 흉내 내지 않는다). 이유: 표시 이름을 바꾸면 그 이름에 걸린 것(`workflow_run.workflows: ["claude · nightly"]`, 사람의 눈)이 조용히 어긋나고, 파일명과 표시 이름이 한 쌍으로 남는 편이 "옛 예약은 제자리"와 맞는다. 따옴표 때문에 본문은 달라지므로, 옛 예약을 다시 부르면(`merge`가 받아 주는 경우 — 지난 일회성은 지금처럼 새 `--at`가 필요하다) 플래그가 같아도 한 번은 `committed`이고 `definition`도 새로 뽑힌다(K8 그대로) | 클로드(코덱스 10) |
| 판단 | **D11 이 맥의 키는 그 예약의 것일 때만 건드린다.** 이름이 자유로워지면 이 맥의 키(대소문자·정규화 무시 파일명, 이어 붙인 라벨)가 다른 예약의 것과 같은 경로일 수 있다. 그래서 ① `launchd`가 plist를 덮어쓰거나 지우기 전에 **그 plist가 누구 것인지**를 내준다(`agent_identity(label)` → 그 경로의 plist에 적힌 `Label`과 `ProgramArguments`, 없으면 None); `schedule`·`unschedule`·일회성 Finish·`--list`의 orphans는 `Label`이 요청한 라벨과 글자까지 같고 argv의 `--repo`가 이 저장소일 때만 자기 것으로 본다 ② `registry`의 상태 삭제는 `state.json`의 `name`이 요청한 이름과 글자까지 같을 때만 한다 ③ 자기 것이 아닌 것이 그 자리에 있으면: `schedule`은 커밋 전에 거부(exit 1, 상대를 말함), `unschedule`은 원격에서 이 예약의 파일을 못 찾았을 때 아무것도 지우지 않고 거부("no schedule `Foo`; this Mac holds `foo`"), Finish는 디스패처를 건드리지 않고 summary 경고로 남긴다. 비교는 모두 글자 그대로다(plist의 `--repo`는 `schedule`이 쓴 GitHub의 정식 철자이고 Finish의 `GITHUB_REPOSITORY`도 그렇다). 판정할 수 없는 경우: **읽을 수 없는 plist나 `--repo`가 없는 plist는 자기 것이 아니다**(덮어쓰지도 지우지도 않고 경로를 말한다); **`state.json`이 없거나 읽히지 않는 상태 디렉터리는 지운다**(남의 것이라는 증거가 없고 든 것은 summary·스키마 사본뿐이다). 0.2.0이 설치한 plist는 `Label`과 `--repo`가 그대로 있고 0.2.0이 쓴 `state.json`에는 항상 `name`이 있으므로(`registry/schedules.py`의 `_rebuild`) 자기 것으로 읽힌다. 라벨 형식은 바꾸지 않는다(옛 디스패처와 Finish가 같은 식으로 라벨을 만든다) | 클로드(코덱스 1·2) |
| 판단 | **명령 표면은 늘지 않는다.** 새 명령·새 플래그 없음. 바뀌는 것은 `--name`이 받는 범위, 새 예약의 파일명·표시 이름, `--list` 행의 `file`과 `state: unknown`, 거부 사유(겹치는 이름, 장치 이름, 이 맥의 키를 다른 예약이 쥠) | 클로드 |

## 구현 후 디렉터리 구조 (바뀌는 파일만)

```
.gitignore                         `.claude/plans/` 줄 삭제 (PR ⓪)
.claude/plans/                     계획 넷 커밋 (PR ⓪에 셋, 이 파일은 PR ①)
.claude/skills/claude/
├── SKILL.md                       (변경 없음)
└── scripts/
    ├── cli.py                     schedule·unschedule의 도움말, 이름 중복 검사 제거
    └── claude/
        ├── schedule/
        │   ├── __init__.py        __all__에서 NAME_RULE 삭제
        │   ├── spec.py            check_name(D1: 정규화 + 각 주인의 규칙을 거부로), 옛 이름 판별, worktree_group(D5)
        │   ├── define.py          파일 찾기(D3), 겹침·장치 이름(D4), --list(D7), 소유 확인(D11), 명령 문자열 인용
        │   ├── execute.py         --workflow 사용(D8), worktree_group, 소유 확인(D11), 안내 문자열
        │   └── summary.py         제목의 이름 이스케이프(D9), _code의 구분자(D7)
        ├── github/
        │   ├── __init__.py        __all__: list_workflows 삭제, list_workflow_files·workflow_states·legacy_workflow_file 추가
        │   ├── api.py             파일명·ref 인코딩, list_workflow_files, workflow_states, 디렉터리 응답(D6)
        │   └── workflow.py        workflow_file = <name>.yml, legacy_workflow_file, 워크플로 파일명이 될 수 없는 이유(D1·D4), name·run-name·group의 YAML(D2), 옛 파일의 표시 이름(D10), parse_spec의 name 타입
        ├── launchd/agents.py      agent_identity; 라벨이 plist 파일명이 될 수 있는지(D1); remove_agent·install_agent가 남의 plist를 건드리지 않게(D11)
        ├── registry/schedules.py  remove_schedule_state가 state.json의 name을 확인(D11)
        └── util.py                대소문자·정규화를 무시한 파일명 키(D4·D11)
tests/
├── support/fake_gh/gh             인코딩된 경로를 구성요소별로 한 번 디코딩, `api graphql` 응답(world.json의 files에서), 런 제목을 워크플로 본문의 run-name에서
├── support/fixtures/github/       graphql-workflows.json · graphql-workflows-nodir.json · graphql-repo-404.json (0단계 캡처), workflow-0.2.0.yml (v0.2.0 코드의 --dry-run 본문)
├── support/fixtures/summary/      title-escaped.html (0단계: GitHub가 렌더링한 제목)
├── test_workflow.py  test_schedule_define.py  test_scheduled_run.py  test_summary.py  test_launchd.py  test_schedule_state.py  test_cli_contract.py
└── smoke_real_schedule.py         파일명 계산을 새 규칙으로, 한글 이름 예약 추가
README.md  SECURITY.md  CONTRIBUTING.md   `claude-NAME.yml`을 말하는 줄 (PR ①)
CHANGELOG.md  .claude-plugin/plugin.json  0.3.0 (PR ②)
```

`runs/`, `batch/`, `observe/`, `doctor.py`는 바뀌지 않는다. `tests/e2e/run_e2e.py`의 기존 시나리오 6–9는 파일명 접두사에 기대지 않으므로(응답의 `files` 값을 순회) 그대로 두고, 시나리오 10 하나를 더한다(`tests/e2e/scenarios.md`에도 한 줄). `tests/test_structure.py`의 간선도 그대로다(`schedule → github, launchd, registry, runs, batch, observe`; `github`·`launchd`·`registry`는 `schedule`을 import하지 않는다).

## 단위 입구 (바뀌는 것)

- `claude.github`: `list_workflows` 삭제 → `list_workflow_files(repo, branch)`, `workflow_states(repo)` 추가. `workflow_file(name)`은 `<name>.yml`을, 새 `legacy_workflow_file(name)`은 `claude-<name>.yml`을 돌려준다. `render_workflow(spec)`은 `spec["file"]`(스텝의 `--workflow`에 쓸 파일명; 옛 파일이면 표시 이름도 옛 꼴)을 받는다.
- `claude.github`에 하나 더: 이름이 워크플로 파일명이 될 수 없으면 그 이유를 돌려주는 함수(이름은 구현 때; `unsafe_text`와 같은 꼴 — 문제면 이유, 아니면 None).
- `claude.launchd`: `agent_identity(label)`과, 라벨이 plist 파일명 한도를 넘으면 알리는 함수 추가; `remove_agent`·`install_agent`는 그 경로의 plist가 다른 `Label`의 것이면 건드리지 않고 그렇게 답한다.
- `claude.registry`: `remove_schedule_state`가 다른 이름의 상태면 지우지 않고 그렇게 답한다.
- `claude.schedule`: `__all__`에서 `NAME_RULE`을 뺀다. `schedule`·`unschedule`은 받은 이름을 스스로 정규화·검사한다.
- `cli.py`: 도메인 로직 없이 `--name`을 그대로 넘긴다(지금의 `NAME_RULE.match` 두 군데 삭제).

## 문서 (섹션 구조)

**SKILL.md — 변경 없음.** 다섯 섹션 그대로: `# Claude workers as managed subagents`(호출 문단) / `## Handing work over` / `## Several workers at once` / `## Waiting, steering and collecting` / `## Scheduling a worker` / `## When something goes wrong`. 이름 형식을 말하는 문장이 지금도 없고, 성진이 싣지 않기로 했다. 구현 세션은 다섯 섹션을 다시 읽어 새 동작과 어긋나는 문장이 없음을 확인만 한다(없으면 PR 본문에 "SKILL.md 변경 없음, 확인함").

**`references/` — 없음**(K29 유지; `test_install`이 없음을 단정).

**`schedule --help`**(계약; 지금의 문단 구조 유지):
- 설명 1문단: `Commits .github/workflows/NAME.yml …`(접두사 삭제), 나머지 그대로.
- 설명 2문단(다시 부를 때): 그대로.
- `Prints:` — `--list` 행에 `file` 추가, `state`에 `unknown`(GitHub has not registered the file yet) 추가. 나머지 그대로.
- `Exits:` — 1에 추가: "a name that differs from another workflow file or schedule only by letter case or Unicode form (one file on a Mac), a name Windows reserves (con, nul, com1 …), a dispatcher or state on this Mac that belongs to another schedule"; "a workflow of that name the skill did not write" → "a NAME.yml that is not this schedule". 2의 "a name that breaks the rule" 그대로.
- `--name NAME`: "the schedule's name, used as given for the workflow file (.github/workflows/NAME.yml) and its title in Actions; a different name is a different workflow, and past runs stay with the old one. Up to 80 characters (an emoji counts as two); no `/ \ : * ? \" < > |`, no `${{`, no control or invisible characters; not starting with `-` or a space, not ending with `.` or a space" (구현 때 실제 거부와 맞춘다).
- epilog: 그대로.

**`unschedule --help`**: "a claude-NAME.yml this skill did not write" → "a workflow file of that name that is not this schedule, or a name this Mac holds for another schedule". `--name` 설명 그대로.

**README.md**: `## Scheduling`의 그림 한 줄(`.github/workflows/claude-NAME.yml` → `NAME.yml`)과 예시 블록(밑줄·대문자 이름 예 하나). 섹션 구조는 그대로.

**SECURITY.md**: 13행 "writing a file other than `.github/workflows/claude-NAME.yml`" → `NAME.yml`(0.2.0의 예약은 `claude-NAME.yml`).

**CONTRIBUTING.md**: `## 3. Tests`의 S5 real schedules 줄(`claude-smoke-*.yml` → `smoke-*.yml`).

**CHANGELOG.md**(PR ②): `## 0.3.0` — Changed: 이름이 준 그대로 파일명·Actions 이름이 됨(받는 범위, 80자), 새 예약에 접두사 없음, 0.2.0 예약은 파일·표시 이름 그대로 계속 동작·수정됨, `--list` 행의 `file`과 `state: unknown`, 손으로 쓴 `claude-X.yml`이 더는 `--name X`를 막지 않음. Fixed: `unschedule`·일회성 Finish가 이 맥에서 경로가 같은 다른 예약의 디스패처·상태를 지울 수 있던 것.

## 테스트 seam (구현 세션은 `coding` 스킬을 열고 정한다 — 아래는 걸 곳)

기댓값은 손으로 쓴 YAML 줄·실측 캡처·합의된 규칙표에서 온다. 테스트는 지금처럼 실제 CLI를 서브프로세스로 몰고 fake `gh`·`launchctl`을 PATH 앞에 둔다. fake `launchctl`은 `print`·`bootout`·`bootstrap`만 안다 — 정시 발화는 S5에서만 확인한다.

- **이름 규칙표**(`test_schedule_define.Refusals`): 받는 이름(`261128_SS_외국인순매수`, `270225_NVDA_Q4 실적 (가이던스)`, `💎 weekly`, `👩‍💻 review`, `a#b%c`, `.hidden`, 80단위 꽉 찬 이름, 옛 이름 `nightly-review`)과 거부하는 이름(빈 것, 81단위, 이모지 41개, `a/b`, `Q4: x?`, `a\|b`, `x${{y`, `-draft`(`--name=-draft`로 준다), ` lead`, `trail `, `trail.`, 탭·줄바꿈·U+200B·U+00A0·U+202E가 든 이름) — 표는 D1에서 직접. NFD로 준 이름이 NFC 파일명으로 커밋되는지.
- **렌더링**(`test_workflow`, 렌더러 단위 — D1이 거부하는 `:`·`"`도 렌더러는 안전하게 쓰는지 여기서만 본다): 이름에 `#`, `'`, `"`, `:`, 한글, 공백이 있을 때 `name:`·`run-name:`·`group:`·`--name`·`--workflow` 줄이 손으로 쓴 기댓값과 같다(run-name의 고정 표현식이 날것으로 남는지 포함). 옛 파일명이면 `name:`이 `claude · <name>`.
- **찾기·호환**(`test_schedule_define`): 새 예약은 `<name>.yml`; fixture `workflow-0.2.0.yml`이 놓인 저장소에서 같은 이름으로 다시 부르면 `claude-<name>.yml`이 제자리에서 바뀌고(표시 이름 유지) `<name>.yml`은 생기지 않는다; `unschedule`이 옛 파일을 지운다; D3의 걸어 보기 셋; **기존 테스트 셋(`:321`, `:352`, `:359` 근처, 손으로 쓴 `claude-mine.yml`·`claude-code-review.yml`)은 대상을 `mine.yml`·`code-review.yml`로 옮기고, `claude-X.yml` 쪽은 "무시되고 `X.yml`이 만들어진다"를 단정하도록 바꾼다**; 겹침(파일 키, 디렉터리 항목, 예약 이름 키, 옛·새 섞임)과 장치 이름 거부가 `--dry-run`에서도 나고 이 맥에 아무것도 쓰지 않는다; fake gh의 호출 기록에 인코딩된 경로(`a%23b%25c.yml`)와 인코딩된 `ref`가 남는다; `next.command`가 공백 든 이름을 인용한다.
- **목록**(`test_schedule_define.Listing`): 옛·새·손으로 쓴 워크플로가 섞인 저장소에서 스킬 것만 `file`과 함께 정렬되어 나온다; Actions에 없는 파일은 `state: unknown`; `"name": ["x"]`인 spec은 행이 되지 않고 죽지도 않는다; 본문이 없는 GraphQL 항목은 다시 읽힌다. 기존 `test_many_workflows_are_all_listed`는 `workflow_states`의 둘째 쪽 호출과 그 상태를 확인하는 것으로 바꾼다(파일 발견은 이제 GraphQL).
- **소유 확인**(`test_launchd`, `test_schedule_state`, `test_schedule_define.Unschedule`): `foo`가 살아 있을 때 `unschedule --name Foo`가 거부되고 `foo`의 plist·상태가 그대로다(대소문자 무시 파일시스템에서; 테스트의 임시 디렉터리가 구분하는 볼륨이면 건너뛴다고 적는다); 다른 저장소의 `--repo`가 적힌 plist가 같은 라벨 경로에 있으면 `schedule`이 거부하고, `--list`의 orphans에 나오지 않는다; 0.2.0이 쓴 plist는 자기 것으로 읽힌다.
- **실행기**(`test_scheduled_run`; 일회성은 `test_schedule_define.OneOff`): 옛 플래그(`--workflow claude-nightly.yml`)로 온 일회성이 그 파일을 끄고, 새 플래그는 새 파일을 끈다; 한글 이름의 `--worktree` 런이 그룹 `261128-ss-<id>-1`로 뜨고 Finish가 잡 기록의 그룹을 정리한다; 한글뿐인 이름은 `schedule-<id>-1`; 14자리 런 id에서도 그룹이 40자 이하다; 프로젝트가 없을 때의 주석·안내가 이름을 인용한다.
- **summary**(`test_summary`): 마크다운 문자가 든 이름의 제목이 0단계에서 GitHub가 렌더링한 fixture와 같은 글자를 내도록 이스케이프되고, 기존 fixture(`summary/scheduled_write.md`, 제목 `nightly-docs`)는 그대로 통과한다; 백틱이 든 파일명의 안내 명령이 코드 스팬으로 남는다.
- **계약**(`test_cli_contract`): 새 단언 하나 — 규칙표의 거부 이름마다 `schedule --name <그것> --dry-run`이 exit 2이고, `schedule --help`의 `--name` 문장이 그 거부를 이름 붙이는 낱말(`/`, `${{`, `80`, `-`)을 담는다. `test_install`: `references/` 없음 그대로.
- **구조**(`test_structure`): 그대로 통과. 새 테스트는 단위의 입구(`__all__`에 있는 이름)나 CLI로만 들어간다 — `schedule/spec.py`·`summary.py`의 안쪽 함수(`check_name`, `worktree_group`, 제목 이스케이프)를 직접 import하지 않고 `schedule`·`__scheduled`·`render_summary`를 통해 본다(`test_tests_reach_units_only_through_their_interface`가 지킨다).
- **S6 대조 한 장면**(`tests/e2e/run_e2e.py`에 시나리오 10 추가, fake gh·launchctl, sonnet 오케스트레이터): 사용자가 대화에서 양식을 말한다("이 저장소의 예약 이름은 `yymmdd_티커_설명`이야. NVDA 실적 다음 날 2027-02-25 09:00에 재분석을 예약해 줘"). 검사: 커밋된 파일이 `270225_NVDA_….yml` 꼴이고(모델이 습관대로 소문자·하이픈 슬러그로 바꾸지 않았다), 호출이 한 줄이며 이름이 인용돼 있다. SKILL.md에 문장이 없어도 `--help`만으로 충분한지를 보는 것이다 — skill-maker의 "사실이 충분한지는 그 사실을 주고 다시 돌려 본다". 통과하면 PR 본문에 결과를 적고 끝이다. 실패하면 SKILL.md에 문장을 넣지 않고(성진 결정) 실패한 출력을 성진에게 그대로 보여 준다.

## 단계 (PR별, 완료 판정)

**PR ⓪ `chore: 계획 파일을 저장소에 남긴다`** (본 체크아웃에서 브랜치로; 스킬 코드 무관) — `.gitignore`에서 `.claude/plans/` 줄을 지우고, `261031_claude-skill.md`·`261117_claude-skill-schedule.md`·`261119_claude-skill-schedule-session.md`를 있는 그대로 커밋한다. 하네스 심링크 둘(`fancy-crunching-dongarra.md`, `merry-wondering-kernighan-of-…md`)은 커밋하지 않고 지운다. 이 파일은 여기 넣지 않는다(PR ①과 함께 간다). 판정: `git ls-files .claude/plans`가 그 셋이고 `git status`에 이 파일만 미추적으로 남는다. 머지 뒤 본 체크아웃 `git pull`(코드 변경이 없어 시각 제약 없음).

**worktree 준비** — `git worktree add`로 PR ①의 브랜치를 본 체크아웃 밖에 만들고, 이 계획 파일을 본 체크아웃에서 그 worktree의 같은 경로로 **옮긴다**(본 체크아웃에 미추적 사본이 남으면 나중의 pull을 막는다). 이후 이 파일의 경로는 worktree 안이다.

**0단계 — 캡처(임시 저장소, 커밋 없음).** 임시 저장소를 만들고: ① N3의 GraphQL 응답을 워크플로가 있을 때(blob 둘 이상 + 디렉터리 항목 하나)·`.github/workflows`가 없을 때·저장소가 없을 때 각각 캡처(exit code·stdout·stderr; 토큰·이메일 가림) ② `git worktree add --detach <scratch> v0.2.0`으로 푼 0.2.0 코드의 `schedule --dry-run`이 내는 `workflow_text`를 fixture `workflow-0.2.0.yml`로 저장(경로는 fixture 관례대로 치환) ③ `gh api -X POST markdown -f mode=gfm`에 D9로 이스케이프한 제목(구두점 많은 이름 하나, `@name`·`#1`·`www.x.com`·`$a$` 포함)을 보내 받은 HTML을 `summary/title-escaped.html`로 저장하고, 이름이 글자 그대로인지 눈으로 확인. 판정: fixture가 있고 각 파일이 실제 호출에서 왔다.

**PR ① `feat: 예약 이름을 준 그대로 파일명과 Actions 이름에 쓴다`** (worktree에서; 커밋은 결정 하나에 하나, 각 커밋은 실패하는 테스트 먼저. 호환을 먼저 깔고 파일명을 마지막에 바꾼다 — 중간 커밋 어디서도 옛 예약이 깨지지 않게)
1. 실행기가 넘겨받은 `--workflow`를 쓴다(D8), 파일명·`ref` 인코딩(D6 앞부분) — 판정: 옛 플래그 테스트·인코딩 테스트 통과, 기존 스위트 그대로.
2. 이 맥의 키 소유 확인(D11) — 판정: 소유 확인 테스트 통과. 기존 `Listing.test_list`가 심는 고아 plist(`Label`만 있다)에는 `ProgramArguments`와 `--repo`를 더한다(`--repo`가 없는 plist는 이제 남의 것이라 orphans에 나오지 않는다).
3. 목록을 헤더로 찾는다(D6 뒷부분, D7): `list_workflow_files`·`workflow_states`, `--list`의 `file`·`state: unknown` — 판정: 목록 테스트 통과, `list_workflows`가 코드에 없다.
4. 이름 규칙(D1), 새 파일명·표시·YAML(D2), 옛 형식 찾기와 옛 표시 이름(D3·D10), 겹침·장치 이름(D4), worktree 그룹(D5) — 한 커밋(이름 규칙만 풀고 파일을 못 찾으면 중간 상태가 깨진다) — 판정: 규칙표·렌더링·찾기·실행기 테스트 통과, `cli.py`에 `NAME_RULE`이 없다.
5. summary 제목과 안내 명령(D9, D7의 인용) — 판정: summary 테스트 통과.
6. 도움말·README·SECURITY·CONTRIBUTING·smoke·S6 시나리오 10 — 판정: S6 시나리오 10을 한 번 돌린 결과가 PR 본문에 있다(통과, 또는 실패한 출력을 성진에게 보였다); `test_cli_contract`·`test_install` 통과, `grep -rn "claude-NAME\|claude · " .claude/skills README.md SECURITY.md CONTRIBUTING.md`가 옛 형식을 설명하는 줄만 남긴다.
7. 전체 스위트 `python3 -m unittest discover -s tests` 통과(약 7분), `claude plugin validate --strict "<worktree>/.claude/skills"` exit 0.
8. 실제 검증(아래 "검증"의 S5) — 판정: 여섯 항목이 모두 기대대로이고 임시 자원이 지워졌다. PR 본문 `## 검증`에 명령과 결과를 적는다.
9. 리뷰 프로토콜 → 이 계획 파일을 커밋에 넣고 → 머지(`gh pr merge --squash`).

**PR ② `chore(release): v0.3.0`** — CHANGELOG, `.claude-plugin/plugin.json`의 버전(`marketplace.json`에는 버전 키가 없다; 설명 문구에 버전이 있으면 그것만). 판정: `claude plugin validate --strict` exit 0, 태그 `v0.3.0`. 머지 뒤 맨 위 "작업 위치"의 확인을 하고 본 체크아웃 `git pull`, 그다음 worktree 제거(제거 전 `grep -rl "<worktree 경로>" ~/Library/LaunchAgents`가 비었는지 본다).

**볼트 이전(다른 저장소, PR 없음 — 스킬이 볼트 기본 브랜치에 직접 커밋한다).** PR ②가 머지되고 본 체크아웃이 0.3.0으로 당겨진 뒤에, **설치된 경로로** 부른다: `uv run "/Users/seongjin/.claude/skills/claude/scripts/cli.py" … --project "/Users/seongjin/💎Obsidian"`. 워크플로에는 부른 `cli.py`의 경로가 박히므로 worktree의 것으로 부르면 worktree를 지운 뒤 볼트의 예약이 전부 깨진다.
1. 볼트의 `schedule --list`로 현재 예약을 읽고, 옮길 대상을 고른다: `state`가 active이고 앞으로 발화할 것(`at`이 미래이거나 `cron`). 이미 돌고 꺼진 일회성(`inv-ant-2611` 등), 살아 있는 런이 있는 예약, 다음 발화가 한 시간 안인 예약은 뺀다(뺀 것과 이유를 표에 적는다).
2. 각 대상의 `# spec:`에서 프롬프트를 읽어 사건을 한글로 짧게 쓴 **'옛 이름 → 새 이름' 표**(`yymmdd_TICKER_설명`, yymmdd = 발화일, 티커 대문자)를 만들어 `AskUserQuestion`의 `preview`로 보여 주고 승인받는다. 성진이 고치면 고친 표로 다시 보여 준다. **승인 전에는 아무것도 바꾸지 않는다.**
3. 예약마다 차례로: ㉠ 직전에 `schedule --list`와 `gh run list --workflow <옛 파일> --status in_progress`로 1의 제외 조건을 다시 본다(걸리면 건너뛰고 표에 적는다) ㉡ `schedule --name <새 이름> --prompt-file <spec의 프롬프트> --at\|--cron … --profile … --model … --effort … --timeout … [--worktree] [--runs-on …] [--schema <spec의 스키마 파일>] --message "chore: 예약 작업자 <옛>를 <새>로 이름 변경"` ㉢ 응답의 `workflow.status == committed`, `dispatcher.status == installed`를 확인하고, 새 워크플로의 spec을 옛 spec과 비교한다 — `name`·`definition` 밖의 **모든** 키가 같아야 한다(`cli`·`project`·`timezone` 포함: 설치된 경로로 불렀다면 같다) ㉣ 모두 맞으면 `unschedule --name <옛> --message "chore: 이름 바꾼 예약 작업자 <옛> 제거"`를 부르고 응답이 `workflow.status == deleted`, `dispatcher.status ∈ {removed, absent}`인지 확인한다(exit 0은 "시도했다"일 뿐이다). ㉢이 어긋나면 **방금 만든 새 예약을 `unschedule`로 되돌리고** 옛 것은 그대로 둔 채 그 예약에서 멈추고 보고한다. ㉣이 어긋나면 멈추고 보고한다(그 상태로 다음으로 가면 같은 시각에 디스패처가 둘이다).
4. 판정: `schedule --list`에서 옮긴 예약이 모두 새 이름·`dispatcher: loaded`·`state: active`이고, 옮긴 옛 이름의 행이 없고, `orphans`가 비었다; 옮긴 수 + 건너뛴 수 = 표의 행 수; 새 예약 하나에 `gh workflow run '<파일>' --repo tjdwls101010/Obsidian -f mode=check`를 돌려 볼트의 실제 러너에서 check가 초록이다(모델 호출 없음). 볼트의 작업 트리는 건드리지 않는다(로컬 `git pull`은 성진 몫이라고 보고에 적는다).

## 리뷰 프로토콜 (PR ①)

구현을 마치면 **`claude` 스킬 작업자(`--model sonnet`, `--profile read-only`)로** 리뷰를 건다 — 코덱스는 한도가 차서 쓰지 않고, opus·fable까지 쓸 필요는 없다(성진, 2026-11-22). 부를 때는 본 체크아웃에 설치된 스킬 경로(`~/.claude/skills/claude/scripts/cli.py`)를 쓰고 `--project`로 worktree를 가리킨다. 같은 모델 계열이라 다른 계열의 시각이 없다는 것을 PR 본문에 적는다. 리뷰어에게는 diff와 이 계획의 "합의 장부"를 주고 결론은 주지 않는다. 볼 것: ① D1–D11이 코드와 같은가 ② 옛 0.2.0 워크플로가 새 코드에서 깨지는 경로 ③ 도움말이 동작과 다른 곳 ④ skill-maker의 여섯 성질(특히 Interface over document, Model over machinery) ⑤ 이름이 인용 없이 셸·YAML·마크다운·URL로 들어가는 남은 자리. 지적은 그대로 받지 않고 근거를 확인해 반영 여부를 정하고, 반영하지 않은 것은 이유와 함께 PR 본문에 적는다. 리뷰는 "보통의 사용에서 닿는 결함이 더 나오지 않는다"에서 멈춘다.

## skill-maker 프레임 대조 (완료 판정에 그대로)

구현 세션은 `skill-maker`를 `Skill`로 열고, PR ①을 올리기 전에 아래 표를 한 줄씩 실제 diff와 대조해 PR 본문에 결과를 적는다. 어긋난 줄이 있으면 고치거나, 고치지 않는 이유를 성진에게 가져간다(조용히 벗어나지 않는다).

**여섯 성질**

- **Principle over rail**: SKILL.md에 행동 지시를 더하지 않는다. 이름 규칙의 거부는 각각 실측된 이유(D1)가 있고 그 이유보다 넓지 않으며, 거부 메시지가 그 이유를 말한다.
- **Interface over document**: 이름이 무엇에 쓰이고 무엇을 받는지는 `--help`와 거부 메시지가 말한다. SKILL.md에 사본이 없다. 호출 전에 계획을 바꿔야 하는 사실(다른 이름은 다른 워크플로이고 이력은 옛 이름에 남는다)은 이름을 정하는 바로 그 호출에서 읽히는 `--name` 설명에 둔다.
- **Model over machinery**: 양식 엔진·패턴 설정·이름 바꾸기 명령을 만들지 않는다(모델이 지금 명령으로 옳게 했다는 실측이 있다). 새 명령·플래그 0. D4·D11은 새 능력이 아니라 "여러 곳을 일관되게 써야 하는 쓰기"를 기존 명령 안에서 지키는 것이다.
- **For the model, not the maintainer**: 실측 번호·경위·어느 리뷰어가 찾았는지는 이 계획과 커밋 본문에만. 도움말·거부 메시지·summary에는 모델과 사람이 행동에 쓰는 사실만(버전 이야기 "0.2.0 이전 예약은…"도 도움말에 넣지 않는다 — `--list`의 `file`과 응답의 `workflow.path`가 보여 준다).
- **Dense**: 도움말의 `--name` 문장은 규칙과 "다른 이름은 다른 워크플로" 한 절. 한도 숫자(80)는 도움말(인터페이스)에만 있고 SKILL.md에는 없다.
- **Colleague over autopilot**: 이름은 사람의 것이라는 판단을 스킬이 대신 내리지 않는다(양식 없음). 사람이 없는 실행(일회성 Finish)이 남의 디스패처를 만났을 때의 행동은 미리 정했다(건드리지 않고 summary 경고, D11). 볼트 이전에서 이름 표는 성진이 승인한다.

**스킬이 싣는 코드("Code the skill bundles")**

- 트리: `SKILL.md` + `scripts/cli.py` + 패키지 `scripts/claude/` 그대로. 새 최상위 이름·새 서브패키지 없음. 스킬 폴더에는 실행 중인 모델이 쓰는 것만(fixture·테스트·캡처는 `tests/`).
- `cli.py`: 명령 표면(파서·도움말·분기·종료 코드)만 갖고 도메인 로직이 없다 — 지금 있는 이름 검사 두 줄을 지워 이 규칙에 더 가까워진다. `sys.path`를 건드리지 않는다.
- `--help` 두 단계: 최상위 지도는 그대로(명령이 늘지 않는다). `schedule --help`·`unschedule --help`가 각자 인자·출력(`Prints:`)·실패(`Exits:`)를 스스로 말한다. 닫힌 집합은 choices 그대로.
- stdout은 JSON 한 줄, stderr는 진단, 종료 코드 0·1·2의 뜻 그대로. 새 거부는 "명령줄을 바꿔야 함"이면 2(이름 규칙), 상태 때문이면 1(겹침·소유).
- 단위는 깊은 모듈: 바깥은 `__all__`만 쓴다. 남이 가진 시스템의 지식은 그 서브패키지에(GitHub의 파일명·표현식·경로 한도와 GraphQL/REST의 모양은 `github/`, plist와 라벨은 `launchd/`), 상태는 `registry/`, 기능이 그것들을 묶는다(`schedule/`). import는 기능 → 저장소 → 시스템 → 공용 한 방향. `tests/test_structure.py`가 이것을 지키고, 테스트도 입구로만 들어간다.
- 상태: 레지스트리는 지금처럼 프로젝트의 `.claude-runs/`(0.1.0에서 합의된 자리)이고 이 계획은 자리를 옮기지 않는다.

**끝났다고 말하기 전에("When the skill is done")**

- 스킬 글: SKILL.md는 바뀌지 않는다 — "더할 것이 없다"는 성진의 결정과 S6 시나리오 10의 결과가 그 근거다. 바뀌는 모델용 글은 `--help`와 거부 메시지이고, PR ① 본문에 바뀐 도움말 전문을 실어 성진이 통째로 읽고 승인하게 한다.
- 성진이 붙든 이의(밑줄·접두사·한글·양식은 사람 몫·문장 없음)가 각각 D1·D2·결정 행에 자리가 있다. `claude plugin validate --strict "<…>/.claude/skills"` exit 0; 고친 코드가 자기 계약(도움말)과 맞음(`test_cli_contract`); 구조 테스트 통과; 리뷰(구현 리뷰는 `claude` sonnet 작업자 — 다른 모델 계열의 리뷰는 계획 단계에서 코덱스가 한 번 했고 구현 단계에는 없다는 위험을 PR 본문에 적는다); 개발 기록은 이 계획(이제 저장소에 있다)과 커밋 본문.

## 검증 (전체)

- **스위트**: worktree에서 `python3 -m unittest discover -s tests` — 전부 통과.
- **S5 실제 예약**(임시 저장소 + 임시 러너, haiku; worktree의 `cli.py`를 경로로 불러서. 프로필은 `write`를 쓴다 — 볼트는 `auto`지만 haiku가 auto 모드를 받지 못하면 `mode_mismatch`가 되고, 이름이 지나는 길은 프로필과 무관하다):
  1. 볼트의 모양 그대로 한 번에: `schedule --name '261128_SS_외국인순매수' --at <3분 뒤> --profile write --worktree --model haiku …` → 응답의 `workflow.path`가 `.github/workflows/261128_SS_외국인순매수.yml`; 디스패처가 정시에 발화; 그룹 `261128-ss-<런 id>-1`의 worktree에서 런이 `completed`; summary 제목이 `✅ 261128_SS_외국인순매수 · completed`; Finish가 worktree를 정리하고(변경이 있으면 남기고 경로·브랜치를 말함) 워크플로를 끄고 디스패처를 지움; `schedule --list`에 `file`과 함께 보임.
  2. 반복 예약의 중복 건너뛰기: 같은 방식의 `--cron` 예약(read-only)에서 디스패처로 한 번 돈 뒤 `gh workflow run … -f source=dispatcher`를 같은 slot에 한 번 더 → 두 번째가 "skipped"(한글 이름의 상태 디렉터리가 slot을 기억한다).
  3. **옛 워크플로를 새 코드가 받는다**: scratch에 심링크 경로 P를 만들어 `v0.2.0` 체크아웃의 `cli.py`를 가리키게 하고, P로 `schedule --name legacy --at <5분 뒤> --profile write --worktree --model haiku`(옛 형식 `claude-legacy.yml`, 옛 디스패처) → **발화 전에 P를 worktree의 `cli.py`로 바꿔 건다** → 0.2.0이 설치한 디스패처가 발화 → 새 코드가 옛 플래그로 Run·Finish → `completed`, `claude-legacy.yml`이 꺼지고 디스패처가 지워짐. 이어서 새 코드로 `schedule --list`(`file: claude-legacy.yml`), `schedule --name legacy --at <새 시각>`(같은 파일이 바뀌고 표시 이름은 `claude · legacy` 그대로, `legacy.yml`은 생기지 않음), `unschedule --name legacy`(그 파일 삭제).
  4. **도는 중의 업그레이드**: P를 다시 0.2.0으로 돌려 옛 일회성을 하나 더 만들고(프롬프트는 2분쯤 걸리는 일), Run 스텝이 도는 동안 P를 worktree로 바꾼다 → 옛 코드의 Run이 끝나고 새 코드의 Finish가 잡 기록의 그룹을 정리하고 `claude-<name>.yml`을 끈다.
  5. 겹침과 소유: `schedule --name '261128_ss_외국인순매수' …`가 exit 1로 거부되고 GitHub에 아무것도 생기지 않는다; 2의 반복 예약(이름 `Weekly_점검`처럼 대문자가 든 것)이 살아 있는 동안 소문자로 바꾼 이름의 `unschedule`이 거부되고 그 plist·상태가 그대로다(일회성은 Finish가 디스패처를 지우므로 이 확인에 쓰지 않는다).
  6. 기호 든 이름 `💎 a#b%c (d)`로 예약 → `mode=check` 런이 초록이고(디스패치·스텝 인자가 이름을 그대로 나름), 프로젝트 경로를 없는 곳으로 준 예약의 check 아닌 런이 빨강으로 끝나며 주석 제목에 이름이 온전하다.
- **`tests/smoke_real_schedule.py`**: 한글 이름 예약을 포함해 통과(위 1을 자동화한 부분).
- **볼트 이전**: 위 "볼트 이전"의 판정.

## 검증되지 않는 것 (핸드오프에)

- 이름을 Actions 사이드바가 어떤 순서로 보여 주는지(날짜를 앞에 두면 시간순이 되리라는 것)는 화면을 보지 않았다.
- Windows·Linux 체크아웃에서의 파일명 동작은 실측하지 않았다(금지 문자와 장치 이름은 Windows의 문서화된 규칙에서 왔다). `casefold` 키가 모든 대소문자 무시 파일시스템의 비교와 같다는 것도 확인하지 않았다(더 넓게 거부하는 쪽이다).
- 겹치는 두 이름을 서로 다른 맥에서 동시에 처음 만드는 경합(D4)은 막지 않는다.
- 보이지 않는 문자를 전부 막지는 못한다(D1).
- 사람이 git에서 워크플로 파일을 직접 옮기거나 이름을 바꾼 경우(스텝의 `--workflow`·디스패처가 옛 파일명을 가리킴)는 다루지 않는다.
- 디스패처 라벨의 저장소 경계는 여전히 모호하다(`a/b.c`의 `d`와 `a/b`의 `c.d`); D11은 남의 것을 건드리지 않게 할 뿐 그런 두 예약이 한 맥에 함께 있게 해 주지는 않는다(나중 것이 거부된다).

## 범위 밖 (다시 볼 조건과 함께)

- **양식 강제·패턴 설정**: 성진 결정. 다시 볼 조건 — 관례를 말해 줬는데도 모델이 어긋난 이름을 짓는 일이 반복될 때.
- **SKILL.md의 이름 문장**: 성진 결정. 다시 볼 조건 — 관례를 말하지 않은 저장소에서 이름이 다시 흔들릴 때(그때 S6 대조로 문장의 효과를 잰다).
- **이름 바꾸기 명령**: 다시 볼 조건 — 모델이 옮기다 설정을 잃는 사례가 나올 때.
- **파일명과 다른 표시 이름(`--title`)**: 성진 결정(한 이름).
- **디스패처 라벨 형식 바꾸기**: 옛 디스패처와의 호환을 깨므로 하지 않는다. 다시 볼 조건 — 위 라벨 모호성으로 실제 거부를 겪을 때.
- **세션 잇기 계획**(`261119_claude-skill-schedule-session.md`): 이 계획과 독립이다.

## 계획 리뷰 기록

초안을 `codex`(gpt-6.2-sol, medium, read-only; 런 `20261122-083013-plan-naming-review-d3e5`)와 `claude` 작업자(opus, high, read-only; 런 `20261122-083015-plan-naming-review-1a79`)가 각각 코드와 대조해 리뷰했다. 두 리뷰어 모두 계획의 줄 번호가 코드와 맞음을 확인했다.

| 지적 | 누가 | 처리 |
|---|---|---|
| `unschedule --name Foo`가 이 맥에서 `foo`의 plist·상태를 지운다 | 코덱스(막음) | 반영 — D11 |
| 디스패처 라벨이 저장소 경계를 넘어 겹친다 | 코덱스(막음), claude(참고) | 부분 반영 — D11의 소유 확인(남의 것을 건드리지 않음). 라벨 형식은 호환 때문에 그대로, 한계에 적음 |
| `run-name`을 `_string`에 넣으면 고정 표현식까지 죽는다 | 둘 다 | 반영 — D2 |
| 이름의 `${{` | 둘 다(추론) | 실측(N8)으로 확인, D1에서 거부 |
| D9의 이스케이프가 기존 fixture(`nightly-docs`)를 깬다; 안내 명령의 백틱 | 둘 다 | 반영 — D9(`-` 제외), D7(`_code`) |
| `?ref=`도 인코딩해야 한다 | 코덱스 | 반영 — D6 |
| D3의 첫 파일 우선이 옛 예약을 가린다 | 코덱스(막음), claude(참고) | 반영 — D3을 "이 예약의 파일 고르기"로 다시 씀 |
| D4가 디렉터리 항목·잘린 본문·잠금 뒤 재확인을 놓친다; `--dry-run`·잠금 전 여부가 정해지지 않았다 | 둘 다 | 반영 — D4·D6 |
| 목록의 미등록·판독 실패·`name` 타입·정렬 | 코덱스 | 반영 — D6·D7 |
| S5의 옛 워크플로 검증이 실제로는 0.2.0 코드를 돌린다; 도는 중의 업그레이드 | 둘 다 | 반영 — S5 3·4(심링크 경로를 바꿔 거는 방식) |
| 옛 예약의 표시 이름을 바꾸면 그 이름에 걸린 연동이 깨진다 | 코덱스 | 반영 — D10을 뒤집어 옛 표시 이름 유지 |
| D1의 길이 산수·ZWJ·`COM¹`·선두 `-`의 근거·"옛 이름 모두 통과"의 범위 | 코덱스, claude | 반영 — D1·D4 |
| 슬러그가 40자를 보장하지 못한다; worktree 런의 라벨은 그룹 이름이다 | 코덱스, claude | 반영 — D5 |
| PR ①의 커밋 순서가 중간에 옛 예약을 깬다; fake의 한계; `OneOff`의 위치 | 코덱스 | 반영 — 단계 순서, 테스트 seam |
| 기존 테스트 셋이 뒤집힌다는 말이 없다 | claude | 반영 — 테스트 seam |
| 볼트 이전: `unschedule` exit 0의 뜻, 직전 재확인, 새 디스패처 확인, 되돌리기, `cli` 경로 | 둘 다 | 반영 — 볼트 이전 3단계 |
| S5가 볼트의 모양(일회성 + worktree)을 지나지 않는다 | claude | 반영 — S5 1(프로필만 `write`로, 이유를 적음) |
| 계획 파일은 gitignore에 걸려 PR에 못 넣는다 | 둘 다 | 성진 결정으로 해소 — PR ⓪ |
| 0단계의 인코딩 응답 캡처는 읽는 데가 없다; e2e는 고칠 것이 없다; `marketplace.json`에 버전 키가 없다; 볼트의 숫자(28개, 10:00) | 둘 다 | 반영 |

개정판의 새 판단(D3·D4·D5·D7·D10·D11, 커밋 순서, S5 3·4, 볼트 이전 3단계)만 `claude` 작업자(sonnet, high, read-only; 런 `20261122-085018-plan-naming-review2-681b`)가 다시 대조했다. 막는 것은 없었고 셋을 반영했다: D11에서 판정할 수 없는 경우(읽을 수 없는 plist, `state.json` 없는 디렉터리)의 답, D10의 옛 표시 이름도 따옴표 꼴로 쓴다는 것, 커밋 2에서 `test_list`의 고아 plist 심기를 고친다는 것(그리고 S5 5의 소유 확인을 반복 예약으로). D3·D4·D5 사이의 모순이나 오동작 입력은 찾지 못했다. 이 2차 리뷰는 같은 모델 계열의 시각이다.
