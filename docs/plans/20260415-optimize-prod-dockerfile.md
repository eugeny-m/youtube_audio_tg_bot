# Optimize prod.Dockerfile

## Overview
- `prod.Dockerfile` currently copies the entire directory into the image (`COPY . /app`) and `.dockerignore` misses several unnecessary files (media/, scripts, tar.gz archives)
- The Dockerfile has suboptimal layer ordering, no apt cache cleanup, and no security hardening (runs as root)
- Optimizing reduces image size, speeds up SCP transfers to the remote server, and improves build cache utilization
- Constraint: keep `python:3.12` base image (no switch to slim/alpine)

## Context (from discovery)
- files/components involved: `prod.Dockerfile`, `.dockerignore`, `build_project.sh`, `release.sh`
- related patterns: image built with `docker buildx build --platform=linux/amd64`, saved to tar.gz, SCP'd to remote server
- dependencies: ffmpeg and nodejs/npm required at runtime (for pytubefix potoken generation)
- `.dockerignore` already excludes: tests/, docs/, __pycache__/, .git/, .venv/, .idea/, .pytest_cache/, .ralphex/, .DS_Store, *.pyc, *.md, dev_loop.py, requirements-dev.txt, logs/, temp_dir/, .env, .env.*, docker-compose*.yml, config/
- `.dockerignore` missing: media/, build_project.sh, release.sh, deliver_files.sh, Dockerfile, prod.Dockerfile, *.tar.gz, *.sh

## Development Approach
- **testing approach**: Regular (implement, then verify with docker build)
- complete each task fully before moving to the next
- make small, focused changes
- **CRITICAL: every task MUST include new/updated tests** for code changes in that task
- **CRITICAL: all tests must pass before starting next task** - no exceptions
- **CRITICAL: update this plan file when scope changes during implementation**
- run tests after each change
- maintain backward compatibility

## Testing Strategy
- **unit tests**: not applicable (Dockerfile/dockerignore changes — no Python code modified)
- **verification**: run `docker buildx build --platform=linux/amd64 -f prod.Dockerfile .` to confirm image builds successfully
- **size comparison**: compare image size before and after optimization

## Progress Tracking
- mark completed items with `[x]` immediately when done
- add newly discovered tasks with + prefix
- document issues/blockers with warning prefix
- update plan if implementation deviates from original scope

## Solution Overview
- **Key change**: replace `COPY . /app` with explicit `COPY` for each required directory/file — only runtime code enters the image
- Expand `.dockerignore` as a safety net (in case someone adds `COPY .` back)
- Optimize `prod.Dockerfile` layer order: combine apt-get commands, clean apt cache, add `--no-cache-dir` to pip
- Add non-root user for security hardening

## Technical Details
- Layer optimization: merge `apt-get update && install && cleanup` into single RUN to reduce layers
- Explicit COPY: copy only `bot/`, `core/`, `services/`, `storage/`, `main.py`, `requirements.txt` instead of everything
- Non-root user: create `appuser`, chown /app, switch with `USER appuser`
- No multi-stage build (constraint: keep python:3.12 base)

## What Goes Where
- **Implementation Steps** (`[ ]` checkboxes): .dockerignore and prod.Dockerfile changes, verification
- **Post-Completion**: manual verification of deployed container on remote server

## Implementation Steps

### Task 1: Expand .dockerignore to exclude all non-runtime files

**Files:**
- Modify: `.dockerignore`

- [ ] add `media/` to .dockerignore (downloaded audio files, not needed in image)
- [ ] add `*.tar.gz` to exclude saved docker archives
- [ ] add `*.sh` to exclude all shell scripts (build_project.sh, release.sh, deliver_files.sh)
- [ ] add `Dockerfile` and `prod.Dockerfile` to exclude Dockerfiles themselves
- [ ] add `.claude/` to exclude Claude Code config if present
- [ ] verify .dockerignore by inspecting what `COPY . /app` would include (no tests needed — infrastructure file)

### Task 2: Optimize prod.Dockerfile layers and caching

**Files:**
- Modify: `prod.Dockerfile`

- [ ] combine apt-get update + install into single RUN with `&& rm -rf /var/lib/apt/lists/*` cleanup
- [ ] add `--no-cache-dir` to pip install commands
- [ ] remove `COPY . /app` and replace with explicit COPY for each required item:
  - `COPY bot/ /app/bot/`
  - `COPY core/ /app/core/`
  - `COPY services/ /app/services/`
  - `COPY storage/ /app/storage/`
  - `COPY main.py /app/main.py`
  - no other files/directories should be copied — this is the primary optimization
- [ ] add non-root user: `RUN useradd --create-home appuser && chown -R appuser:appuser /app` + `USER appuser`
- [ ] verify image builds: `docker buildx build --platform=linux/amd64 -f prod.Dockerfile .`

### Task 3: Verify acceptance criteria

- [ ] verify image builds successfully with `docker buildx build --platform=linux/amd64 -f prod.Dockerfile .`
- [ ] compare image size before/after: `docker images | grep youtube_tg`
- [ ] verify the container starts correctly: `docker run --rm youtube_tg:latest python -c "import bot; import services; import core; import storage; print('OK')"`
- [ ] run existing project tests to confirm no regressions: `pytest tests/`

### Task 4: [Final] Update documentation

- [ ] update CLAUDE.md if new patterns discovered
- [ ] move this plan to `docs/plans/completed/`

## Post-Completion
*Items requiring manual intervention or external systems - no checkboxes, informational only*

**Manual verification:**
- deploy new image to remote server via `release.sh` and verify bot starts correctly
- monitor bot operation for first few hours after deployment
- compare tar.gz archive size with previous releases
