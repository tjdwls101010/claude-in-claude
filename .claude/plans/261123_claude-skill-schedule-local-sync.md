# claude 스킬: 예약 결과를 로컬에 반영 (0.4.0)

> **구현 세션 첫 동작:** `ToolSearch("select:TaskCreate,TaskUpdate,TaskList")`로 트래커를 열고 아래 "단계"를 태스크로 만든다(description = 그 단계의 완료 판정). `coding`·`skill-maker`는 `Skill`로 연다.

> **작업 위치 — 스킬 코드는 본 체크아웃에서 고치지 않는다.** `~/.claude/skills/claude`는 이 레포 본 체크아웃(`/Users/seongjin/Coding/claude in claude`)으로의 심링크이고, 볼트(`/Users/seongjin/💎Obsidian`, `tjdwls101010/Obsidian`)의 예약 39개가 발화할 때마다 그 경로의 `cli.py`를 부른다(`매일_MACRO_개장전점검` 월~금 21:00 KST, 종목 예약은 21:30·21:45 KST). 반쯤 고친 트리가 그 순간 불리면 무인 실행이 빨갛게 끝난다. 그래서 PR ①·②는 `git worktree`(별도 디렉터리)에서 하고, 검증은 그 worktree의 `cli.py`를 경로로 직접 불러서 한다. worktree에서는 `Skill("claude")`로 스킬을 부르지 않는다(어느 사본이 잡힐지 모른다). 본 체크아웃을 `git pull`하기 전에 `gh run list --repo tjdwls101010/Obsidian --status in_progress`·`--status queued`가 비었고 한 시간 안에 발화가 없는지 본다.

> **이 계획의 승인이 겸하는 허락:** 실제 예약 스모크(`tests/smoke_real_schedule.py`, CONTRIBUTING.md의 private 저장소·러너 절차)를 돌리는 것. 볼트의 워크플로·프롬프트·체크아웃은 건드리지 않는다.

## 승인 전에 볼 것: 성진이 고르지 않았지만 쓰면서 체감할 판단

질문으로 합의한 것이 아니라 클로드가 근거(와 codex 검토)를 들어 정한 것이다. 바꾸고 싶으면 승인 전에 말한다.

- **갱신 대상은 저장소의 기본 브랜치(main) 하나다.** 체크아웃이 main이면 작업 트리까지 fast-forward하고, 다른 브랜치에 있으면 파일은 그대로 두고 로컬 `main` 브랜치만 앞으로 옮긴다(summary가 "파일은 바뀌지 않았다"고 구별해 말한다). 지금 체크아웃된 다른 브랜치는 끌어오지 않는다 — 예약이 머지하는 곳은 main이고, 다른 브랜치를 당기는 건 이 실행과 무관한 변경이다.
- **덮어쓰지 않는다.** stash·reset·rebase·force를 쓰지 않는다. 로컬에서 고친 파일, git이 무시하는 로컬 파일, 로컬에만 있는 커밋, 진행 중인 merge·rebase가 있으면 아무것도 바꾸지 않고 summary와 Actions 경고에 이유·파일·그 상황에 맞는 직접 할 명령을 적는다. 다음 실행이 끝날 때 다시 시도된다.
- **볼트처럼 늘 미커밋 파일이 있는 체크아웃에서도 갱신된다**(겹치지 않으면, 실측). 성진이 Obsidian을 연 채로도 실행 끝에 노트가 바뀔 수 있다.
- **실행이 실패·시간 초과로 끝나도 갱신한다**(이미 머지된 것은 GitHub에 있다). 작업자가 체크아웃 자체에서 일하는(worktree 없는) 런이 이 프로젝트에 살아 있으면 갱신하지 않는다 — 그 작업자의 발밑을 바꾸게 되므로. 이 규칙은 `schedule`·`unschedule` 뒤의 갱신에도 같다.
- **갱신 중 저장소의 git 훅(post-merge 등)은 돌리지 않는다.** 무인 잡에서 사람의 훅이 잡의 환경으로 도는 것을 피한다. 훅이 할 일이 있으면 사람이 다음에 git을 쓸 때 돈다.
- **`schedule`·`unschedule`도 실행한 직후 같은 규칙으로 로컬을 갱신한다**(성진 선택). 커밋이 없었던 호출(`unchanged`)에서도 갱신을 시도하므로, 한 번 실패한 갱신은 같은 명령을 다시 부르면 복구된다. 응답에 `local`이 생기고, 갱신 실패는 종료 코드를 바꾸지 않는다. `--no-pull`은 예약 **실행**에만 적용된다.
- **머지가 끝난 예약 worktree를 지울 때, 커밋되지 않은 잔여물은 지우지 않고 git 안에 보존한다.** index 상태와 작업 트리 전체(미추적·무시 파일 포함)를 커밋 두 개로 담아 `refs/claude/leftovers/<그룹>-<번호>`에 두고, 담긴 내용이 작업 트리와 같은지 확인한 뒤에만 worktree를 지운다. summary가 되살리는 명령(`git worktree add <경로> <커밋>`)을 준다. 무시 파일이 100 MiB를 넘거나, 충돌 중인 index·submodule·중첩 저장소가 있으면 지우지 않고 남긴다. 볼트의 worktree는 SessionStart 훅이 고치는 `.claude/histories` 하나 때문에 매번 남았다 — "잃을 것이 있으면 남긴다"는 지금 규칙으로는 정리가 일어나지 않는다.
- **"머지가 끝났다"는 GitHub에 묻는다**: worktree의 마지막 커밋이 이 저장소 기본 브랜치로 머지된 PR의 head 커밋과 정확히 같거나, 방금 받은 기본 브랜치에 이미 들어 있으면 끝난 것이다(스쿼시 머지는 git만으로 알 수 없다; PR #204의 head = 그 worktree HEAD `bdf961f`, 실측). PR이 열려 있으면 남기고 summary가 PR 번호를 말한다. GitHub 조회가 실패하면 남긴다.
- **브랜치 삭제**: worktree의 `worktree-<그룹>` 브랜치(기준 이후 커밋 없음)와, worktree가 체크아웃하던 작업자의 브랜치(예: `docs/macro-261123-2`)를 그 tip이 머지된 PR head와 정확히 같고 다른 곳에서 체크아웃돼 있지 않을 때 지운다. 내용은 GitHub의 PR에 그대로 있다(`git fetch origin pull/<N>/head`로 되살린다 — summary가 말한다).
- **지난 예약 worktree도 치운다, 단 자기 `Finish`가 끝난 그룹만.** 각 `Finish`는 자기 그룹 처리가 끝나면 그룹에 "끝남" 표시를 남기고, 다른 `Finish`는 이 표시가 있고 살아 있는 런이 없는 예약 그룹만 다시 판정한다. 성진이 PR을 다음 날 손으로 머지해도 그다음 실행이 치운다. 표시가 없는 옛 그룹(0.4.0 전)과 손으로 띄운 `batch` 그룹은 건드리지 않는다.
- **작업자에게 한 줄을 더 알린다**(예약 실행의 앞머리): 끝나면 잡이 `<project>`의 기본 브랜치를 GitHub에서 갱신하려 하고 그 결과는 summary에 남으니 직접 pull하지 말라. 11/23 MACRO 작업자는 볼트 pull을 시도하다 워크트리 격리에 막혀 "성진이 직접 pull해야" 한다고 보고했다. `--no-pull` 예약에는 붙이지 않는다.
- **볼트에는 아무것도 바꾸지 않는다.** 워크플로 39개는 `Finish`에서 심링크 경로의 `cli.py`를 플래그 없이 부르므로 머지된 다음 발화부터 켜진다. 같은 이름으로 `schedule`을 다시 불러도 켜진 예약의 워크플로 파일은 바이트가 그대로다(아래 CLI).

## Context

예약 작업자는 이 맥의 self-hosted 러너에서 돌고, 볼트의 예약들(모두 `auto`·`--worktree`)은 프롬프트의 Git 절대로 `.claude/worktrees/<그룹>`에서 브랜치 → PR → `gh pr merge --squash`까지 한다. 그래서 결과는 GitHub main에만 있고 볼트 체크아웃은 성진이 pull할 때까지 뒤처진다. 성진의 목표: **예약이 GitHub에 남긴 결과는 로컬에도 있어야 하고, 넣을 수 없으면 왜 못 넣었는지 알 수 있어야 한다.** 작업자 안에서는 할 수 없다(11/23 19:58 MACRO: "이 세션의 워크트리 격리가 볼트에 대한 git 명령을 거부했다"). 워크트리 밖에서 도는 `Finish` 스텝이 맡는다. 같은 목표로 `schedule`·`unschedule`이 GitHub에 직접 커밋하는 워크플로 파일도 로컬로 당기고, 내용이 이미 GitHub에 들어간 예약 worktree는 치운다.

스킬은 특정 예약(MACRO)에 맞추지 않는다(성진): 모든 예약에 같은 규칙, 끄는 스위치 하나.

## 합의 장부

| 종류 | 내용 | 출처 |
|---|---|---|
| 결정 | 원하는 것 = 작업자가 GitHub에서 머지한 결과를 스킬이 로컬로 당긴다. 스킬은 GitHub에 쓰지 않는다. 버린 대안: 워크트리 변경을 스킬이 로컬 main에 머지 / 스킬이 PR·머지·pull 전부 | 성진(질문 1) |
| 결정 | 기본으로 켠다, 예약마다 `--no-pull`로 끈다. 버린 대안: 예약마다 켜기(기존 39개를 각각 다시 커밋해야 하고 빠뜨린 예약에서 목표가 깨진다) | 성진(질문 2) |
| 결정 | 추가 범위: `schedule`·`unschedule` 뒤 로컬 갱신, 머지 끝난 worktree 정리. 버린 것: 실행 전 갱신, macOS 알림 | 성진(질문 2) |
| 결정 | 갱신 시점은 실행이 끝날 때만. 버린 대안: 실행 중 1분마다 — 다시 열 조건: 머지 뒤 오래 도는 예약에서 지연이 실제 문제가 될 때 | 성진(질문 3) |
| 결정 | 스킬은 특정 예약 사례에 맞추지 않는다 | 성진 |
| 결정 | 볼트 `.github/workflows`는 고치지 않는다 | 성진 질문에 대한 확인 |
| 결정 | SKILL.md는 바꾸지 않는다 — 아래 「SKILL.md」 절의 문장을 구현 세션이 써서 보였고 성진이 뺐다. 같은 사실은 `schedule --help` 한 문단과 작업자 앞머리가 말한다 | 성진(구현 중, 2026-11-23) |
| 결정 | 실제 스모크는 임시 private 저장소와 임시 러너에서 돌리고 끝나면 모두 지운다(기존 러너·예약은 건드리지 않는다) | 성진(구현 중, 2026-11-23) |
| 사실 | 워크플로는 `uv run /Users/seongjin/.claude/skills/claude/scripts/cli.py __scheduled finish …`를 부르고(볼트 `매일_MACRO_개장전점검.yml:201`), 그 경로는 이 레포로의 심링크다 | `ls -la ~/.claude/skills` |
| 사실 | `Finish` env에 `GH_TOKEN: ${{ github.token }}`, 반복 예약은 `permissions: {}`. github.com 자격 증명 도우미가 `gh auth git-credential`이라 `GH_TOKEN`이 env에 있으면 git이 그것으로 인증한다: 가짜 토큰 → `Authentication failed`; 빼면 keyring 로그인으로 성공 | `github/workflow.py:111-118`, `~/.gitconfig`, 실측 |
| 사실 | 러너 서비스 env에서 keyring 로그인이 쓰인다: 11/23 작업자(K9로 `GH_TOKEN` 제거)가 같은 러너에서 push·`gh pr merge` 성공 | 볼트 `.claude-runs/20261123-195855-…/summary.md` |
| 사실 | `merge --ff-only`: 겹치지 않는 미커밋 → 성공(유지); 겹치는 수정 → exit 1 `Your local changes to the following files would be overwritten by merge:`; 겹치는 미추적 → exit 1 `The following untracked working tree files would be overwritten by merge:`; 갈라짐 → exit 128 `Not possible to fast-forward`; **무시된 로컬 파일은 기본으로 덮어쓴다, `--no-overwrite-ignore`면 exit 1로 지킨다**; 로컬이 앞서 있으면 exit 0 `Already up to date.` | 실측(클로드, codex R01·R02) |
| 사실 | `git fetch origin <b>:<b>`(+ 없이): 체크아웃 안 된 브랜치만 fast-forward, 다른 worktree에 체크아웃 → exit 128 `refusing to fetch into branch`, ff 아님 → exit 1 `[rejected]`; rebase 중인 브랜치도 사용 중으로 거부. `git fetch origin`(refspec 없이)은 `remote.origin.fetch` 설정에 따라 `origin/main`을 안 바꿀 수 있다 | 실측(클로드, codex R02·R03) |
| 사실 | `git ls-remote --symref origin HEAD` → `ref: refs/heads/main	HEAD` | 실측(볼트) |
| 사실 | 11/23 MACRO worktree HEAD `bdf961f` = PR #204의 `headRefOid`(merged) | `GH_TOKEN= gh pr list --state merged --head docs/macro-261123-2 …` |
| 사실 | 볼트 worktree가 남은 이유는 `.claude/histories`(추적 파일, SessionStart 훅이 고침)의 ` M` 하나. `clean`은 추적 파일 변경이 있으면 남긴다. 작업자는 worktree 안에서 자기 브랜치로 바꿔 커밋하므로 `worktree-<그룹>` 브랜치에는 커밋이 없다 | summary Changes, `batch/clean.py:clean_member` |
| 사실 | `git diff HEAD --binary` 하나로는 stage된 변경을 잃는다(stage 뒤 작업 트리만 되돌린 `MM` 파일 → 빈 패치) | codex R08 실측 |
| 사실 | 볼트 체크아웃은 평소 `main`이고 늘 미커밋 | `git status -sb` |
| 사실 | K20: `Finish` 단계는 독립, exit 1은 "정지 미확인"·"step summary 못 씀" 둘뿐. K27: worktree 없는 런의 Changes는 전후 스냅숏 비교 — 갱신은 스냅숏 뒤. K10: `Finish`는 매니페스트 `origin.job`이 자기 잡인 그룹만 정리. concurrency·정의 잠금은 예약 이름별 | `schedule/execute.py`, `github/workflow.py:157-160`, `schedule/define.py` |
| 사실 | `schedule`은 프로젝트를 주 체크아웃으로 정규화하고 GitHub `origin`을 요구한다 | `schedule/define.py:40-50` |
| 판단 | 기본 브랜치만, 명시 refspec으로 fetch, 받은 OID 고정, `--no-overwrite-ignore`, 훅 끔, git의 거부가 안전장치 | 클로드 + codex R01–R04 |
| 판단 | 잔여물은 git 커밋으로 `refs/claude/leftovers/…`에 보존·검증 뒤 제거(버린 대안: 패치+파일 이동 — stage 손실, 부분 이동, symlink·경로 바이트 문제) | 클로드(codex R08 반영) |
| 판단 | 지난 그룹 정리는 자기 `Finish`가 남긴 "끝남" 표시가 있는 그룹만(K10의 명시적 확장) | codex R06 |

## 구현 후 디렉터리 구조 (바뀌는 파일만)

skill-maker 「Code the skill bundles」 레이아웃은 이미 지켜지고 있다(`scripts/cli.py` 하나, 패키지 `claude/`, `tests/test_structure.py`). 새 단위는 git 시스템 서브패키지 안의 모듈 하나다.

```
.claude/skills/claude/
├── SKILL.md                         # 「Scheduling a worker」에 한 문장
└── scripts/
    ├── cli.py                       # schedule --pull/--no-pull, __scheduled --no-pull, 도움말
    └── claude/
        ├── git/
        │   ├── __init__.py          # sync_default, preserve_leftovers 공개
        │   ├── repo.py              # run_git(env=) 인자, git_busy(path)
        │   ├── sync.py              # 새: 기본 브랜치를 origin에 맞춤(fetch, ff, 거부 분류)
        │   └── worktree.py          # preserve_leftovers(worktree, ref) 추가
        ├── github/api.py            # pull_evidence(repo, sha, default) 추가
        ├── batch/clean.py           # clean(..., landed=None)
        ├── registry/groups.py       # 그룹 매니페스트에 finished 표시 쓰기/읽기
        ├── claude_cli/argv.py       # turn_preamble: 예약 + pull이면 한 문장
        └── schedule/
            ├── define.py            # schedule·unschedule 뒤 sync → reply.local
            ├── execute.py           # Finish: sync 단계, 그룹 정리·훑기, finished 표시
            ├── spec.py              # pull 기본 True
            └── summary.py           # Local checkout 행, worktree 정리 문구
        (github/workflow.py: spec 기록에 pull은 False일 때만, 그때 두 스텝에 --no-pull)
tests/ … (아래 seam), README.md, CHANGELOG.md, .claude-plugin/plugin.json
```

import 방향: `schedule`(기능) → `git`·`github`(시스템)·`registry`(저장소)·`batch`(기능, 이미 있는 간선 K10). `batch.clean`은 `github`을 부르지 않고 판정 함수 `landed`를 받는다.

## 단위 입구 (바뀌는 것)

### `git.sync_default(checkout, *, fetch_only=False, expect_repo=None) -> dict`
결과: `{status, branch, files_updated(bool), from, to, commits:[{sha7, subject}] (최대 20, 그 이상은 count), reason, files(최대 20), instead}`. `status` ∈ `updated`(작업 트리까지) · `ref_updated`(브랜치만, 파일 그대로) · `current`(로컬 OID == 원격 OID) · `not_updated`(안전 때문에 보류, 이유 있음) · `failed`(인증·네트워크·잠금 등) · `fetched`(`fetch_only`). 예외를 던지지 않는다.

1. `top = toplevel(checkout)`; 아니면 `failed`. `expect_repo`(잡의 `owner/name`)가 주어지면 `origin` URL을 `repo_from_remote`로 대조, 다르거나 없으면 `not_updated`.
2. 기본 브랜치: `ls-remote --symref origin HEAD`. 실패하면 `failed`(로컬 `origin/HEAD`로 대신하지 않는다).
3. `git fetch --no-recurse-submodules origin +refs/heads/<b>:refs/remotes/origin/<b>` 그리고 그 OID를 `rev-parse`로 고정(`remote`). 이후 모든 판정과 갱신은 이 OID로.
4. 진행 중인 git 작업(`git_busy`: `MERGE_HEAD`, `rebase-merge`/`rebase-apply`, `CHERRY_PICK_HEAD`, `REVERT_HEAD`, `BISECT_LOG`, unmerged index — `rev-parse --git-path`로 찾음) → `not_updated`.
5. 현재 브랜치 == `<b>`: 로컬 OID == remote → `current`; remote가 로컬의 조상 아님 → `not_updated`("로컬에만 커밋 N개" 또는 갈라짐); 아니면 `git -c core.hooksPath=/dev/null merge --ff-only --no-overwrite-ignore <remote OID>` → `updated`, 거부 문구 분류(겹친 수정·미추적·무시 → `files`).
6. 현재 브랜치 ≠ `<b>`(detached 포함): 로컬 `refs/heads/<b>`가 없으면 `not_updated`("로컬에 <b> 없음"); 있으면 `git fetch origin refs/heads/<b>:refs/heads/<b>`(+ 없음) → `ref_updated`/`current`/거부 분류(다른 곳에 체크아웃, ff 아님).
7. `instead`는 원인과 현재 브랜치에 맞춰 만든다(예: main에 있을 때 `git -C <top> merge --ff-only origin/main`, 다른 브랜치일 때 `git -C <top> fetch origin main:main`, 겹친 파일이면 "그 파일을 커밋하거나 옮긴 뒤").

모든 git 자식 프로세스: env = `scrub_job_env(os.environ)`(K9의 `JOB_HANDLES` 전부 제거) + `GIT_TERMINAL_PROMPT=0`, `GIT_ASKPASS=`/`SSH_ASKPASS=` 비움, `GIT_SSH_COMMAND="ssh -o BatchMode=yes"`(설정돼 있지 않을 때만); 타임아웃 ls-remote·fetch 120초, merge 60초. 작업 트리 경로는 미리 구한 `top`을 쓴다(하위 디렉터리가 갱신으로 사라질 수 있다). 같은 저장소의 동기화는 레지스트리의 `.locks/sync.lock` 아래에서 하나씩(잠금 안에서 3–6을 한다).

`sync_default`를 부르는 쪽은 그 전에 레지스트리의 살아 있는 런 중 cwd가 `top` 안이고 worktree가 아닌 것이 있는지 보고, 있으면 부르지 않고 `not_updated`("run X가 이 체크아웃에서 일하는 중")로 보고한다(`Finish`에서는 자기 런을 제외하고, 자기 런의 정지가 확인되지 않았으면 자기 런도 포함).

### `git.preserve_leftovers(worktree, ref) -> {commit, index_commit, counts, bytes} | {kept_because}`
index를 `write-tree`로 커밋(`index_commit`, 부모 HEAD), 임시 `GIT_INDEX_FILE`에 `add -A --force`(무시 파일 포함)로 작업 트리 전체를 커밋(`commit`, 부모 `index_commit`), `update-ref ref commit`. `git diff --quiet <commit>`(임시 index 기준)로 작업 트리와 같은지 확인. 보류 조건: 무시 파일 합계 > 100 MiB, unmerged index, submodule 변경, 중첩 저장소 → `kept_because`. `.worktreeinclude` 사본과 변하지 않은 startup 산출물은 잔여물로 치지 않는다(`leftovers()`와 같은 규칙) — 그것만 있으면 보존 없이 지운다.

### `github.pull_evidence(repo, sha, default) -> {kind, number?, url?}`
`gh api --paginate repos/{repo}/commits/{sha}/pulls` → `merged`(merged_at 있음, `head.sha == sha`, `base.ref == default`, base repo == `repo`) · `open`(같은 조건, 열림) · `other_base` · `none` · `unknown`(조회 실패). env는 `JOB_HANDLES`를 뺀 것(사용자 로그인). 일회성 끄기의 `actions: write` 호출은 지금대로 `GH_TOKEN`.

### `batch.clean(…, landed=None)`
`landed`가 None이면 지금과 똑같다(사용자 `clean` 명령은 바뀌지 않는다). 주어지면 멤버 worktree마다: HEAD가 기준 커밋과 다르고 `landed(head)`가 `{landed: True, label, ref}`를 주면 — 다른 checkout·live run이 그 경로를 쓰지 않는지(기존 검사), detached HEAD면 head SHA 증거가 정확히 있는지 확인 → `preserve_leftovers`(보류면 남김) → worktree 제거 → `worktree-<그룹>` 브랜치(기준 이후 커밋 없음) 삭제 → worktree가 체크아웃하던 브랜치는 tip == head이고 다른 worktree에 체크아웃돼 있지 않을 때 삭제. `landed`가 `{landed: False, open_pr: N}`이면 남기고 그 번호를 `kept`에. 응답 `removed` 항목에 `landed`(PR 번호 또는 `on <b>`), `leftovers`(`ref`, `commit`, 개수).

### `Finish` 순서 (K20 확장, 각 단계는 독립이고 실패는 WARNING으로 모인다)
정지 → (두 번째 `reap` 실패도 정지 미확인으로) → Changes 스냅숏 → **sync**(`--no-pull`이면 `fetch_only`; 위 live-run 규칙) → 자기 그룹 정리(`landed` = remote OID의 조상이면 `on <b>`, 아니면 `pull_evidence`) → 자기 그룹 매니페스트에 `finished` 표시 → **지난 그룹 훑기**(이 레지스트리의 그룹 중 `origin.kind == "schedule"`, `finished` 표시 있음, 같은 저장소, 살아 있는 런 없음, `spawning` 아님; 그룹 잠금 안에서 다시 확인; 한 번에 최대 10개·합계 60초) → 일회성 끄기 → summary. check·건너뜀·거부 잡에서는 sync·훑기를 하지 않는다(거부 잡의 기존 자기 그룹 해제와 일회성 처리는 그대로). sync가 `not_updated`·`failed`면 `::warning::` 하나. 종료 코드 규칙(K20)은 그대로.

### `turn_preamble`
`origin.kind == "schedule"`이고 `origin.pull`이면 한 문장: "[When you end, this job tries to fast-forward the default branch of {project} from GitHub and reports the result in the run summary, so do not pull that checkout yourself.]"(문구는 다듬되 뜻은 같게). `origin`에 `pull`과 `project`를 넣는다.

## CLI 표면 (바뀌는 것만)

| 명령 | 인자 | stdout | 종료 코드 |
|---|---|---|---|
| `schedule` | `--pull` / `--no-pull` 상호 배타, 생략하면 기록값 유지(새 예약은 켜짐). 도움말: 예약 **실행**이 끝날 때(성패 무관) 저장소 기본 브랜치를 GitHub에서 fast-forward — 체크아웃돼 있으면 작업 트리까지, 아니면 브랜치만; 고친 파일·무시 파일과 겹치거나, 로컬에만 커밋이 있거나, 진행 중인 git 작업이나 이 체크아웃에서 일하는 런이 있으면 건드리지 않고 summary가 말함; 훅은 돌지 않음; `--no-pull`은 그 체크아웃의 기본 브랜치에서 사람이 직접 일할 때 고르는 것(그래도 원격 참조는 받는다). `--worktree` 도움말에 정리 규칙 추가(커밋이 기본 브랜치에 들어갔거나 그 커밋이 기본 브랜치로 머지된 PR의 head면 지운다, 커밋 안 된 잔여물은 `refs/claude/leftovers/…`에 보존; 열린 PR이면 남긴다) | 기존 + `settings.pull`, `local`(아래), `--dry-run`·`--list`엔 `local` 없음 | 변화 없음 |
| `unschedule` | 변화 없음 | 기존 + `local` | 변화 없음 |
| `__scheduled` (숨김) | `--no-pull` 추가(없으면 켜짐) | — | 변화 없음 |

`local`: `sync_default`의 결과 그대로. 정의 명령에서는 커밋했으면 그 커밋 SHA가 로컬 기본 브랜치에 들어왔는지 `contains_commit`(bool)을 더한다. 거부(종료 1·2)된 호출에는 `local`이 없다. `committed`·`unchanged`·`deleted`·`absent` 모두 갱신을 시도한다(실패한 갱신을 같은 명령의 재호출로 복구).

호환: 워크플로 `# spec:` 기록에 `pull`은 **False일 때만** 쓴다 — 켜진 예약을 다시 `schedule`해도 렌더링이 바이트까지 같아 `unchanged`가 유지되고 `definition`이 바뀌지 않는다. 기록에 키가 없으면 True. 기존 워크플로는 `--no-pull`이 없으므로 켜진 것으로 돈다.

summary: 표에 **Local checkout** 행(Changes 표시 여부와 무관하게, read-only 런에도): `main fast-forwarded b2bf728 → c851…, 2 commits from GitHub` / `main moved to … (you are on <x>; files unchanged)` / `already matched GitHub` / `not updated: <이유>` / `--no-pull: left as it is`. `not_updated`·`failed`는 WARNING 알림에 파일과 `instead`. 커밋 제목은 Changes 근처 작은 목록(최대 20). 커밋 제목·경로·stderr는 기존 `code_span`·이스케이프와 크기 한도 안에서. worktree 행의 "your checkout is not touched"는 "the worker did not touch your checkout"으로. worktree 정리 문구: "removed: its commits landed in #204; uncommitted files kept as `refs/claude/leftovers/…` (`git worktree add <path> <commit>` brings them back); branch `docs/…` deleted (`git fetch origin pull/204/head`)" / "kept: PR #N is open" / "kept: <kept_because>" / 기존 문구.

## SKILL.md (섹션 구조는 그대로, 한 문장) — 구현 중 성진이 뺐다(합의 장부)

「Scheduling a worker」 문단 끝에 한 문장(뜻): 예약 실행은 끝날 때 프로젝트 체크아웃의 기본 브랜치를 GitHub에 맞추므로(로컬 편집·로컬 커밋 위로는 하지 않는다) 작업자가 거기 머지한 것이 로컬에 온다 — 프롬프트에 pull을 시키지 않는다(worktree의 작업자는 할 수 없다); 사람이 그 체크아웃의 기본 브랜치에서 직접 일한다면 `--no-pull`은 그 사람이 고를 일이다.
- 자리를 얻은 속성: **Colleague over autopilot**(사람의 체크아웃이 실행마다 바뀐다 = 사람이 정할 비용) + **Interface over document**의 예외(프롬프트를 쓰는 시점, 즉 호출 전에 계획을 바꾸는 사실; `--help`는 호출 시점에 읽힌다). 근거: 실제 실패 — 11/23 MACRO 프롬프트에 호출 세션이 pull 지시를 넣었고 작업자는 격리 때문에 실행하지 못했다.
- 나머지 사실(겹칠 때의 동작, 잔여물 보존, 판정 규칙)은 `schedule --help`와 summary가 말한다(Interface over document, Dense). `references/`는 없다(그대로).

## 판단별 근거 (계획·커밋에 남고 스킬 본문에는 없다)

| 판단 | 자리(속성) | 근거 |
|---|---|---|
| 로컬 갱신을 스킬 코드가 한다 | Model over machinery: 작업자 도구에 없는 reach(worktree 격리 밖) | 11/23 작업자 보고 |
| 잡 핸들을 뺀 env로 git·gh | 코드 안의 사실(조용한 실패) | 가짜 토큰 실측 |
| 덮어쓰지 않음(`--no-overwrite-ignore`, 진행 중 작업·live run이면 보류), 훅 끔 | 되돌릴 수 없음 + 무인 → 미리 정함 | ff 실측, codex R01·R03·R04·R05 |
| 기본 브랜치만, OID 고정 | 실행이 머지하는 곳; 오래된 참조로 판정하지 않음 | 프롬프트 Git 절, codex R02 |
| 잔여물을 git 커밋으로 보존 후 정리 | 무인 → 삭제 대신 보존 | `.claude/histories`, codex R08 |
| 정확한 PR head + 기본 브랜치 base로 판정 | 스쿼시 머지는 git으로 판정 불가 | PR #204 실측, codex R07 |
| 지난 그룹은 `finished` 표시가 있을 때만 | K10 소유권의 명시적 확장 | codex R06 |
| 작업자 앞머리 한 줄 | 작업자가 틀린 보고를 하지 않게 | 11/23 최종 메시지 |
| SKILL.md 한 문장 | 위 SKILL.md 절 | 위 |

## 테스트 seam (구현 세션은 `coding` 스킬을 열고 정한다 — 아래는 걸 곳)

기대값은 실제 캡처에서(`tests/support/fixtures/`): git 거부 문구는 실제 git으로 만든 임시 저장소에서 캡처, `gh api repos/<o>/<r>/commits/<sha>/pulls` 응답은 **공개 저장소**(이 레포 `tjdwls101010/claude-in-claude`의 머지된 PR 하나와 열린 PR이 있으면 그것)에서 캡처 — 볼트의 PR 내용은 fixture에 넣지 않는다.

- `test_git`(실제 git, 임시 bare origin): main 체크아웃 → `updated`·commits; 겹치지 않는 미커밋 유지; 겹친 수정·미추적·**무시 파일** → `not_updated`·`files`·내용 그대로; 로컬 앞섬·갈라짐 → `not_updated`; 다른 브랜치 → `ref_updated`·작업 트리 그대로; 로컬 main 없음; main이 다른 worktree에 체크아웃; rebase·merge 진행 중; `remote.origin.fetch`가 다른 브랜치만 받게 설정돼도 갱신됨(명시 refspec); `ls-remote` 실패 → `failed`; `origin`이 다른 저장소 → `not_updated`; post-merge 훅이 돌지 않음; env의 `GH_TOKEN`·`GITHUB_OUTPUT`을 자식이 받지 않음(가짜 자격 도우미로 기록); 하위 디렉터리를 checkout으로 줘도 동작. `preserve_leftovers`: stage된 변경(`MM`)·미추적·무시·symlink·한글 경로가 `git worktree add <path> <commit>`과 index 커밋으로 되살아남; 100 MiB 초과·submodule·unmerged → 보류.
- `test_clean`: `landed` 참 → 보존·worktree·두 브랜치 제거; open PR → 남김·번호; 조회 실패 → 남김; 다른 worktree가 브랜치를 체크아웃 → 브랜치 남김; `landed=None` → 기존 테스트 전부 무변.
- `test_scheduled_run`(가짜 `gh`, 로컬 bare origin을 `origin`으로): Finish가 sync를 Changes 뒤에 함(worktree 없는 런의 Changes에 당긴 커밋 없음); `--no-pull` → 체크아웃 그대로; 실패·시간 초과 런도 sync; 정지 미확인 + worktree 없음 → sync 안 함; 다른 worktree 없는 live run이 있으면 `not_updated`; sync 실패 → WARNING·`::warning::`·exit 0; 지난 그룹 훑기(표시 있음·머지 → 정리, 표시 없음 → 무시, 열린 PR → 남음, 수동 batch 무시, spawning 무시, 메타 손상 무시); check·건너뜀·거부는 sync 없음; 작업자 stdin 앞머리(pull일 때만); 두 번째 `reap` 실패 → 정지 미확인 경로; Local checkout 행이 read-only 런에도.
- `test_schedule_define`(로컬 bare origin + 가짜 API): `committed`·`unchanged`·`deleted`·`absent`에서 `local`; `--dry-run`엔 없음; 갱신 실패여도 exit 0; 켜진 예약 재호출 → `unchanged`(바이트 동일).
- `test_workflow`: `pull` False일 때만 기록·두 스텝 `--no-pull`; 키 없는 기록은 켜짐.
- `test_summary`: Local checkout 행 각 상태, 정리 문구, 긴 커밋 목록·특수문자 이스케이프.
- `test_cli_contract`: 도움말이 위 표와 맞음.
- `smoke_real_schedule` — PR ①: `--worktree` 쓰기 예약의 작업자가 브랜치 push → PR → `gh pr merge --squash`(프롬프트로 지시) → `Finish` 뒤 로컬 main == origin/main, 파일이 체크아웃에 있음; 로컬 체크아웃에 겹치는 편집을 둔 두 번째 런 → WARNING, 그 파일 그대로. 기존 "커밋하지 않은 파일이 있는 worktree는 남는다" 시나리오는 그대로 둔다(PR ①에서는 정리가 없다). PR ②: 같은 PR 머지 시나리오에 의도한 미커밋 파일 → worktree 제거, `refs/claude/leftovers/…`에서 그 파일 복원; 열린 PR 시나리오 → 남음. 러너 서비스 env의 keyring 인증은 여기서만 확인된다.

## 단계 (PR별, 완료 판정)

**PR ① `feat: 예약 실행이 끝나면 로컬 기본 브랜치를 GitHub에 맞춘다`** (worktree에서). 커밋은 결정 하나에 하나: (a) `git.sync_default`와 테스트 (b) `Finish` sync 단계·Local checkout 행·`::warning::` (c) `--pull/--no-pull`·spec·워크플로 인자 (d) `schedule`·`unschedule`의 `local` (e) 작업자 앞머리 (f) SKILL.md 한 문장·README 예약 절·CHANGELOG `Unreleased`. 판정: 위 seam 중 PR ① 몫 통과, 전체 스위트 `python3 -m unittest discover -s tests` 통과, `claude plugin validate --strict "<worktree>/.claude/skills"` exit 0, 스모크 PR ① 시나리오 통과, 이 계획 파일을 PR에 포함, SKILL.md 문장을 성진에게 보여 승인받음, 리뷰 반영 뒤 `gh pr merge --squash`.

**PR ② `feat: 결과가 GitHub에 들어간 예약 worktree를 치운다`** (main 갱신 뒤 새 worktree에서). 커밋: (a) `preserve_leftovers` (b) `github.pull_evidence` (c) `clean(landed)` (d) `Finish`의 자기 그룹 판정·`finished` 표시·지난 그룹 훑기·summary 문구·`--worktree` 도움말 (e) README·CHANGELOG. 판정: seam·전체 스위트·validate exit 0, 스모크 PR ② 시나리오 통과.

**PR ③ `chore(release): v0.4.0`** — CHANGELOG 날짜, `.claude-plugin/plugin.json` 버전. 판정: validate exit 0, 태그 `v0.4.0`. 머지 뒤 "작업 위치"의 확인을 하고 본 체크아웃 `git pull`, worktree 제거(제거 전 `grep -rl "<worktree 경로>" ~/Library/LaunchAgents`가 빈지).

## 리뷰 (PR ①·②)

머지 전 `codex` 스킬로 리뷰를 건다(다른 모델 계열, read-only). 프롬프트: PR 목적, `git diff main...HEAD`, 이 계획 경로, 계약(`--help`, summary 실제 출력), "테스트를 실행해 재현하라". 계획 리뷰의 R01–R12가 구현에서 지켜졌는지 확인하게 한다. 지적 가운데 성진이 정한 결정(기본 켬·끝날 때만·범위)을 바꾸는 것은 반영하기 전에 성진에게 묻는다.

## skill-maker 프레임 대조 (완료 판정에 그대로)

- 성진 승인: 이 계획(ExitPlanMode), 그리고 PR ① 머지 전 SKILL.md 문장 전체.
- 각 action 줄이 Principle over rail 통과: 덮어쓰지 않음·잔여물 보존·훅 끔은 "되돌릴 수 없음 + 무인 실행"이 이유이고, 나머지는 사실 서술.
- 명령: 새 명령 없음, 플래그 하나(`--no-pull`) — Model over machinery(worktree 밖 reach).
- `claude plugin validate --strict "<checkout>/.claude/skills"` exit 0(심링크 대상의 부모).
- 코드가 자기 계약과 맞음(`test_cli_contract`), 구조 테스트 통과(새 모듈·간선이 방향 규칙 안).
- 개발 기록(실측, 버린 대안, 11/23 사례, codex 지적)은 이 계획 파일과 커밋 본문에; 스킬 본문에는 없다.
- 다른 모델 계열 리뷰: 계획은 codex가 검토(아래 기록), 구현은 위 리뷰.

## 검증 (전체)

1. `python3 -m unittest discover -s tests` 전부 통과(약 7분) — 수치를 PR `## 검증`에.
2. `claude plugin validate --strict "<worktree>/.claude/skills"` exit 0.
3. 실제 예약 스모크(`tests/`에서 `CLAUDE_SKILL_REAL=1 CLAUDE_SKILL_REAL_GITHUB=1 CLAUDE_SKILL_REAL_SCHEDULE_PROJECT=<checkout> python3 -m unittest smoke_real_schedule`) — PR별 시나리오.
4. 릴리스 뒤 첫 볼트 발화의 summary에 Local checkout 행이 있고 볼트 `git rev-parse main` == `origin/main`인지 성진과 확인(핸드오프에 적는다 — 구현 세션이 기다릴 필요는 없다).

## 검증되지 않는 것 (핸드오프에)

- 러너 서비스 env의 keyring 인증은 스모크 러너에서만; 볼트 러너는 첫 발화가 증명한다.
- Obsidian이 열린 채 파일이 바뀌는 경험(겹치면 git이 거부하므로 손실은 없다).
- LFS·외부 필터를 쓰는 저장소: 필터는 설정대로 돈다; 실패하면 `failed`로 보고될 뿐 따로 검증하지 않았다. sparse checkout은 범위 밖 파일을 만들지 않는다(정상).
- `refs/claude/leftovers/*`의 누적 — 지우는 정책 없음(`git for-each-ref refs/claude/leftovers`로 보이고 `git update-ref -d`로 지운다; README에 한 줄).
- 0.4.0 전에 남은 볼트의 옛 worktree·그룹(`inv-ant-2611-…`)은 `finished` 표시가 없어 자동으로 치워지지 않는다 — 필요하면 `clean --group`.

## 범위 밖 (다시 볼 조건과 함께)

- 실행 중 갱신 — 머지 뒤 오래 도는 예약에서 지연이 실제 문제가 될 때.
- 실행 전 갱신(worktree가 최신 main에서 시작) — 프롬프트마다 "fetch 뒤 origin/main에서" 줄이 부담이 될 때.
- 갱신 실패 macOS 알림 — summary를 보지 않아 놓친 일이 생길 때.
- 볼트 프롬프트의 pull 관련 줄 정리 — 무해하므로 성진이 원할 때.
- 사용자 `clean` 명령에 "머지된 것은 치움" 옵션 — 손으로 띄운 batch에서도 필요해질 때.

## 계획 리뷰 기록

codex(read-only, 2026-11-23, run `20261123-215024-plan-review-39f7`): "승인 보류" + 지적 12개. 모두 반영, 성진 결정을 바꾸는 것 없음.
- R01 무시 파일 덮어쓰기 → `--no-overwrite-ignore`, 테스트.
- R02 오래된 참조·`current` 오판 → 명시 refspec fetch, OID 고정, ls-remote 실패 시 대체하지 않음, 상태 세분.
- R03 경로·origin·진행 중 작업 → `top` 고정, `expect_repo` 대조, `git_busy`.
- R04 훅·자격 증명·잡 핸들 → 훅 끔, `scrub_job_env`, askpass·BatchMode, 타임아웃, submodule 재귀 끔. LFS 별도 정책은 넣지 않고 "검증되지 않는 것"에 적음(반만 반영: 보류 대신 보고).
- R05 동시 실행 → 저장소 단위 sync 잠금, worktree 없는 live run 있으면 보류(세 호출점 공통).
- R06 지난 그룹 소유권 → `finished` 표시가 있는 그룹만, 그룹 잠금 안 재확인.
- R07 PR 판정·브랜치 삭제 → `pull_evidence`의 merged/open/other_base/none/unknown, base 대조, 삭제 조건. 작업자 브랜치 삭제는 유지(정확한 PR head 일치 + 미사용; GitHub에서 되살릴 수 있음) — 관리 브랜치만 지우라는 제안은 받지 않음: 볼트에 작업자 브랜치가 매일 쌓이는 것이 이번 목표의 일부.
- R08 잔여물 보존 → 패치·이동 대신 git 커밋 + 검증 + 보류 조건.
- R09 시간 예산 → 훑기 상한, 두 번째 `reap`.
- R10 CLI·호환 → `pull`은 False일 때만 기록, opt-out은 실행에만, 정의 명령 `local` 표.
- R11 사용자 문구 → 앞머리 문구, `ref_updated` 구별, 원인별 `instead`, Local checkout 행 독립.
- R12 스모크 배치 → PR별 시나리오 분리, 기존 시나리오 보존, 로컬 bare origin.

## 구현 기록 (PR ①)

계획과 달라진 것과 그 이유. 결정별 근거는 각 커밋 본문에 있다.

- **갱신 규칙의 자리**: `git` 계층(system)은 `github`·`registry`를 import할 수 없다(구조 테스트). 그래서 잡 핸들 제거, origin 대조, 막는 런 판정, 잠금은 `schedule/local.py`의 `sync_local`이 맡는다. `git.sync_default`는 env와 `guard`(바꾸기 직전에 다시 묻는 콜백)를 받는다. 잠금은 `registry.sync_lock`(`.locks/sync.lock`)이다.
- **`remote_url`**: `git remote get-url`(insteadOf 적용 후) 대신 설정값을 읽고, 여럿이면 첫 번째를 쓴다. 테스트가 bare 저장소를 GitHub 자리에 세울 수 있고, 대조한 저장소와 받아 오는 저장소가 일치한다.
- **SKILL.md**: 바꾸지 않는다(성진). 같은 사실은 `schedule --help`의 "Your checkout" 문단과 작업자 앞머리가 말한다.
- **스모크**: 작업자가 PR을 머지하는 대신 테스트가 Contents API로 커밋을 올린다(`test_what_lands_on_github_reaches_the_checkout`). 임시 저장소 `claude-schedule-probe`와 임시 러너에서 통과했다.
- **codex 리뷰 4라운드**(R1 블로커 6과 should-fix 5, R2 블로커 1과 6, R3 블로커 1과 3, R4 should-fix 1)를 모두 반영했다. 계획보다 늘어난 것:
  - 사람의 git 설정을 무력화하는 플래그(`--no-autostash --no-squash --refmap= --no-write-fetch-head`)와 바꾼 뒤의 확인
  - 막는 런의 판정: git이 그 디렉터리를 이 체크아웃에 두는가(samefile, 사라진 경로는 상위로), 그리고 Finish가 변경을 읽기 전인 예약 런(`changes_read_at`, 옛 런은 summary.md)
  - Run이 스냅숏부터 런 게시까지 sync 잠금을 잡는 것(`start`가 `on_published`를 넘긴다)
- **받아들이지 않은 지적**: 다른 레지스트리(`--runs-dir`)의 런까지 보는 체크아웃 단위 잠금(LS04 일부). `start`의 concurrent writers 검사와 같은 범위에 두고 `성진:`으로 남겼다.
- **PR ②에 넘기는 것**: `--no-pull` 예약은 Finish에서 갱신 대신 받기만(`fetch_only`) 해야 정리 판정에 쓸 원격 커밋을 안다. PR ①에서는 `--no-pull`이면 git을 건드리지 않는다.

## 구현 기록 (PR ②)

- **리뷰어**: codex가 PR ② 리뷰 도중 사용량 한도에 걸려(2026-11-24 11:22까지), 첫 지적(보존 중 PermissionError) 하나를 낸 뒤 Claude 작업자(opus, read-only)가 2라운드를 대신했다. 다른 모델 계열의 시각은 PR ②의 대부분에 없다.
- **보존(`preserve_leftovers`)이 계획보다 늘어난 것**:
  - 임시 index를 실제 index의 복사본에서 시작한다. `read-tree`로 만들면 볼트 규모(추적 파일 24,738개, 17 GiB)에서 30초 제한에 걸렸다.
  - ref는 만들기만 하고 옮기지 않는다(`-2`, `-3`…).
  - `.worktreeinclude` 패턴에 걸리는 파일은 담지 않고, 바뀌었으면 worktree를 남긴다.
  - 담은 뒤 `hash-object --no-filters`로 디스크와 바이트를 대조한다.
  - 100 MiB 상한은 남은 것 전부를 센다.
- **브랜치 삭제**: 그룹 시작 때의 로컬 브랜치 목록(`worktree.branches_before`)에 없던 브랜치만 런이 만든 것으로 본다. 기본 브랜치는 지우지 않는다. reflog 시각으로 가리던 첫 시도는 초 단위와 gc에 틀려 버렸다.
- **다시 보기(sweep)**: `finished_at` 뒤에 바뀐 worktree(`last_changed`: index mtime, HEAD reflog 최신 항목 시각, 남은 항목 mtime)는 사람이 일하는 중일 수 있어 남긴다. 그래서 우리 자신의 status는 `GIT_OPTIONAL_LOCKS=0`으로 index를 쓰지 않는다.
- **기존 결함 수리**: git은 읽지 못한 디렉터리를 경고만 하고 건너뛰어, `clean`(사람의 명령 포함)이 그런 worktree를 지울 수 있었다. `status_entries`가 그 경고를 보면 None이다.
