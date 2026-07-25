# setup.ps1 - Cricket Video Intelligence Platform Setup

Write-Host "`nSetting up Cricket Video Intelligence Platform..." -ForegroundColor Cyan

# Step 1: Create directories
Write-Host "`nStep 1: Creating directories..." -ForegroundColor Yellow
@("src", "tests", "config", "data", "output", "logs", "scripts", "specs", "memory", "docs", "contracts") | ForEach-Object { 
    if (-not (Test-Path $_)) {
        mkdir $_ -Force | Out-Null
        Write-Host "  OK: $_" -ForegroundColor Green
    }
}

# Step 2: Create .gitignore
Write-Host "`nStep 2: Creating .gitignore..." -ForegroundColor Yellow
@"
__pycache__/
*.py[cod]
*$py.class
venv/
env/
.vscode/
.idea/
*.mp4
*.mkv
*.db
*.sqlite
data/large_videos/
output/highlights/
logs/*.log
.env
"@ | Out-File -Encoding UTF8 .gitignore
Write-Host "  OK: .gitignore created" -ForegroundColor Green

# Step 3: Create README.md
Write-Host "`nStep 3: Creating README.md..." -ForegroundColor Yellow
@"
# Cricket Video Intelligence Platform

An offline AI-powered platform that analyzes cricket match broadcasts and generates customized highlight videos.

## Key Features
- Analyze 3-4 hour match in 40 minutes
- Detect events with 95% accuracy
- Remove 90% of replay footage
- 100% offline
- CPU-only

## Target Hardware
- CPU: Intel Core i3-1115G4
- RAM: 8 GB
- OS: Windows 11

## Contributors
- Mullais (mullais.kt@gmail.com)

Status: Spec-Kit Initialization Phase
"@ | Out-File -Encoding UTF8 README.md
Write-Host "  OK: README.md created" -ForegroundColor Green

# Step 4: Create requirements.txt
Write-Host "`nStep 4: Creating requirements.txt..." -ForegroundColor Yellow
@"
opencv-python==4.8.1.78
scenedetect==0.6.1
ffmpeg-python==0.2.1
pytesseract==0.3.10
pillow==10.0.0
numpy==1.24.3
pandas==2.0.3
sqlalchemy==2.0.20
pydantic==2.0.0
pyyaml==6.0.1
python-dotenv==1.0.0
tqdm==4.66.1
loguru==0.7.0
"@ | Out-File -Encoding UTF8 requirements.txt
Write-Host "  OK: requirements.txt created" -ForegroundColor Green

# Step 5: Create requirements-dev.txt
Write-Host "`nStep 5: Creating requirements-dev.txt..." -ForegroundColor Yellow
@"
-r requirements.txt
pytest==7.4.0
pytest-cov==4.1.0
pytest-mock==3.11.1
black==23.9.1
pylint==2.17.5
flake8==6.0.0
mypy==1.4.1
sphinx==7.1.2
sphinx-rtd-theme==1.3.0
ipython==8.14.0
jupyter==1.0.0
"@ | Out-File -Encoding UTF8 requirements-dev.txt
Write-Host "  OK: requirements-dev.txt created" -ForegroundColor Green

# Step 6: Create .gitattributes
Write-Host "`nStep 6: Creating .gitattributes..." -ForegroundColor Yellow
@"
* text=auto
*.py text eol=lf
*.pyw text eol=lf
*.sh text eol=lf
*.bat text eol=crlf
*.cmd text eol=crlf
*.ps1 text eol=crlf
*.json text eol=lf
*.yaml text eol=lf
*.yml text eol=lf
*.csv text eol=lf
*.mp4 binary
*.mkv binary
*.db binary
*.sqlite binary
"@ | Out-File -Encoding UTF8 .gitattributes
Write-Host "  OK: .gitattributes created" -ForegroundColor Green

# Step 7: Create .editorconfig
Write-Host "`nStep 7: Creating .editorconfig..." -ForegroundColor Yellow
@"
root = true

[*]
end_of_line = lf
insert_final_newline = true
charset = utf-8

[*.py]
indent_style = space
indent_size = 4
max_line_length = 100

[*.{yml,yaml}]
indent_style = space
indent_size = 2

[*.json]
indent_style = space
indent_size = 2

[*.md]
trim_trailing_whitespace = false
"@ | Out-File -Encoding UTF8 .editorconfig
Write-Host "  OK: .editorconfig created" -ForegroundColor Green

# Step 8: Create .gitkeep files
Write-Host "`nStep 8: Creating .gitkeep files..." -ForegroundColor Yellow
@("data", "output", "logs", "contracts") | ForEach-Object { 
    New-Item -ItemType File -Path "$_\.gitkeep" -Force | Out-Null
    Write-Host "  OK: $_\.gitkeep created" -ForegroundColor Green
}

# Step 9: Git configuration
Write-Host "`nStep 9: Configuring Git..." -ForegroundColor Yellow
git config user.name "Mullais"
git config user.email "mullais.kt@gmail.com"
Write-Host "  OK: Git configured (Mullais, mullais.kt@gmail.com)" -ForegroundColor Green

# Step 10: Git commit
Write-Host "`nStep 10: Creating initial commit..." -ForegroundColor Yellow
git add .
git commit -m "Initial commit: Cricket Video Intelligence Platform scaffold - initialize project structure for offline cricket analysis"
Write-Host "  OK: Commit created" -ForegroundColor Green

# Final summary
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "SETUP COMPLETE!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan

Write-Host "`nProject Location:" -ForegroundColor Yellow
Write-Host "  $(Get-Location)" -ForegroundColor White

Write-Host "`nGit Status:" -ForegroundColor Yellow
git log --oneline -1

Write-Host "`nNEXT STEPS:" -ForegroundColor Yellow
Write-Host "  1. code .                              (Open in VS Code)" -ForegroundColor White
Write-Host "  2. npm install -g @spec-kit/cli        (Install Spec-Kit)" -ForegroundColor White
Write-Host "  3. speckit init                        (Initialize Spec-Kit)" -ForegroundColor White
Write-Host "  4. Add PRD to docs/PRD.md" -ForegroundColor White
Write-Host "  5. Create Spec-Kit spec files" -ForegroundColor White
Write-Host "  6. claude /speckit.tasks               (Generate tasks)" -ForegroundColor White

Write-Host "`nAuthor: Mullais (mullais.kt@gmail.com)" -ForegroundColor Cyan
Write-Host "`n"