@echo off
cd /d C:\GitHub\ai-core

git config --global user.name "gooadmin-gif"
git config --global user.email "gooadmin@gmail.com"

REM 初回のみ（すでに git init 済みならコメントアウトまたは削除）
if not exist ".git" (
    git init
    git branch -M main
    git remote add origin https://github.com/gooadmin-gif/ai-core.git
)

git add .
git commit -m "Update ai-core directory and mathlib/eval scripts"
git push -u origin main

pause