@echo off
REM =============================================================
REM  Petal & Co — load CI env into the current terminal session.
REM  Usage (from the repo root):   ci\load-ci-env.bat
REM
REM  Reads ci\.env (KEY=VALUE per line, # for comments) and sets
REM  each variable for THIS terminal only (session-scoped — closing
REM  the window clears them; nothing is written with setx).
REM
REM  Safe to commit: this file holds NO secrets. The values live in
REM  ci\.env, which is gitignored.
REM =============================================================

if not exist "%~dp0.env" (
  echo [load-ci-env] ci\.env not found.
  echo [load-ci-env] Copy ci\.env.example to ci\.env and fill it in first.
  goto :eof
)

for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%~dp0.env") do set "%%A=%%B"

echo [load-ci-env] CI environment loaded for this session.
echo [load-ci-env] This terminal is now in CI mode - open a NEW terminal for normal dev work.