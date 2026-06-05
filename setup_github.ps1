# setup_github.ps1
$RepoName = "waynes-video"
$RepoDir  = "C:\projects\YT\smartcat-yt-automation-public"

Set-Location $RepoDir

# Step 1: remove old .git
Write-Host "=== Step 1: Remove old .git ===" -ForegroundColor Cyan
if (Test-Path ".git") {
    Remove-Item -Recurse -Force ".git"
    Write-Host "Done." -ForegroundColor Green
}

# Step 2: git init
Write-Host "=== Step 2: git init ===" -ForegroundColor Cyan
git init -b main
git config user.name  "waynelim1983-afk"
git config user.email "waynelim1983@gmail.com"

# Step 3: git add + commit
Write-Host "=== Step 3: git add + commit ===" -ForegroundColor Cyan
git add .
Write-Host "--- Files to commit ---" -ForegroundColor Gray
git status --short
Write-Host ""

# Check for secrets
$secrets = git ls-files | Select-String -Pattern "credentials|session\.json|\.env" -Quiet
if ($secrets) {
    Write-Host "WARNING: possible secret files detected!" -ForegroundColor Red
    git ls-files | Select-String "credentials|session\.json|\.env"
    Write-Host "Press any key to cancel..."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}

git commit -m "Initial public release"

# Step 4: create GitHub public repo
Write-Host "=== Step 4: Create GitHub Public Repo ===" -ForegroundColor Cyan

if (Get-Command gh -ErrorAction SilentlyContinue) {
    Write-Host "gh CLI found, creating repo..." -ForegroundColor Green
    gh repo create $RepoName --public --source=. --remote=origin --push
    Write-Host "Done! https://github.com/waynelim1983-afk/$RepoName" -ForegroundColor Yellow
} else {
    Write-Host "gh CLI not found. Manual steps:" -ForegroundColor Yellow
    Write-Host "  1. Go to https://github.com/new"
    Write-Host "  2. Repository name: $RepoName"
    Write-Host "  3. Select Public, do NOT initialize"
    Write-Host "  4. Click Create repository"
    Write-Host "  5. Run these commands:"
    Write-Host ""
    Write-Host "     git remote add origin https://github.com/waynelim1983-afk/$RepoName.git" -ForegroundColor Cyan
    Write-Host "     git push -u origin main" -ForegroundColor Cyan
}

Write-Host "Press any key to exit..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
