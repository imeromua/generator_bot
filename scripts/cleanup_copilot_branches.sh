#!/bin/bash
# Script to delete all Copilot-generated branches from GitHub
# Usage: ./scripts/cleanup_copilot_branches.sh

set -e

echo "🧹 Cleaning up Copilot branches..."
echo ""

# List of all Copilot branches to delete
BRANCHES=(
    "copilot/add-admin-audit-log"
    "copilot/add-dynamic-config-management"
    "copilot/add-interactive-graphs"
    "copilot/add-longest-outage-tile"
    "copilot/add-pull-to-refresh"
    "copilot/add-settings-card-admin"
    "copilot/add-settings-page-webapp"
    "copilot/add-system-configuration-ui"
    "copilot/add-telegram-push-notifications"
    "copilot/add-time-remaining-tile"
    "copilot/check-miniapp-functionality"
    "copilot/cleanup-code-after-bot-disable"
    "copilot/create-bot-miniapp-documentation"
    "copilot/find-errors-in-window-logic"
    "copilot/finish-miniapp-development"
    "copilot/fix-analytics-report-fields"
    "copilot/fix-app-visibility-issue"
    "copilot/fix-bot-and-miniapp-errors"
    "copilot/fix-bugs-in-telegram-webapp"
    "copilot/fix-calculation-bug-to"
    "copilot/fix-critical-issues-webapp"
    "copilot/fix-css-tab-size-issue"
    "copilot/fix-excel-download-issue"
    "copilot/fix-excel-download-issues"
    "copilot/fix-excel-report-crash"
    "copilot/fix-excel-report-download"
    "copilot/fix-excel-report-downloads-android"
    "copilot/fix-excel-reports-attachment"
    "copilot/fix-forecast-day-calculation"
    "copilot/fix-fuel-balance-report-issue"
    "copilot/fix-inline-buttons-fuel-notification"
    "copilot/fix-maintenance-hour-display"
    "copilot/fix-menu-tabs-overflow"
    "copilot/fix-merge-conflict-webapp-html"
    "copilot/fix-monkeypatch-imports"
    "copilot/fix-pdf-report-error-handling"
    "copilot/fix-tests-and-ensure-passing"
    "copilot/fix-transaction-manager-issue"
    "copilot/full-refactor-architecture-generation-bot"
    "copilot/implement-bot-miniapp"
    "copilot/implement-user-management-features"
    "copilot/migrate-to-fastapi"
    "copilot/refactor-entrypoints-structure"
    "copilot/refactor-webapp-server-structure"
    "copilot/replace-pdf-with-excel-reports"
    "copilot/sync-with-google-sheets"
    "copilot/update-analytics-download-button"
    "copilot/update-service-worker-cache-version"
)

DELETED=0
FAILED=0

for BRANCH in "${BRANCHES[@]}"; do
    echo "🗑  Deleting: $BRANCH"
    if git push origin --delete "$BRANCH" 2>/dev/null; then
        ((DELETED++))
        echo "   ✅ Deleted"
    else
        ((FAILED++))
        echo "   ❌ Failed (might not exist or already deleted)"
    fi
    echo ""
done

echo "="*50
echo "✅ Deleted: $DELETED branches"
if [ $FAILED -gt 0 ]; then
    echo "⚠️  Failed: $FAILED branches"
fi
echo "="*50
echo ""
echo "🎉 Cleanup complete!"
