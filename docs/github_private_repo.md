# GitHub Private Repository Setup

本项目建议使用 GitHub 私有仓库协作。

## 1. 登录 GitHub CLI

在 Windows PowerShell 中执行：

```powershell
& "C:\Program Files\GitHub CLI\gh.exe" auth login
```

推荐选择：

```text
GitHub.com
HTTPS
Login with a web browser
```

登录完成后检查：

```powershell
& "C:\Program Files\GitHub CLI\gh.exe" auth status
```

## 2. 创建私有仓库并推送

在本项目目录执行：

```powershell
& "C:\Program Files\GitHub CLI\gh.exe" repo create quadruped-robot-competition --private --source . --remote origin --push
```

## 3. 添加队员

仓库创建后，在 GitHub 页面：

```text
Settings -> Collaborators -> Add people
```

只添加参赛队员账号。

## 4. Jetson 拉取

在 Jetson 上：

```bash
cd ~
git clone https://github.com/<owner>/quadruped-robot-competition.git
cd quadruped-robot-competition
bash scripts/check_jetson_env.sh
python3 scripts/realsense_smoke_test.py
```

如果是私有仓库，Jetson 需要配置 GitHub SSH key 或使用 HTTPS token。

