param(
    [string]$Repo = "jiek860/xiaoliu-app",
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"

$checks = @(
    "static",
    "test",
    "ci-required",
    "compat-required",
    "windows-build-required",
    "portable-required",
    "security-required",
    "codeql-analyze"
)

$body = @{
    required_status_checks = @{
        strict = $true
        contexts = $checks
    }
    enforce_admins = $true
    required_pull_request_reviews = @{
        dismiss_stale_reviews = $true
        require_code_owner_reviews = $false
        required_approving_review_count = 1
    }
    restrictions = $null
    required_linear_history = $false
    allow_force_pushes = $false
    allow_deletions = $false
    block_creations = $false
    required_conversation_resolution = $true
    lock_branch = $false
    allow_fork_syncing = $true
} | ConvertTo-Json -Depth 10

Write-Host "Configuring branch protection for $Repo/$Branch ..."
$body | gh api --method PUT "repos/$Repo/branches/$Branch/protection" --input - | Out-Null
Write-Host "Branch protection configured."
Write-Host "Required checks:"
$checks | ForEach-Object { Write-Host "  - $_" }
