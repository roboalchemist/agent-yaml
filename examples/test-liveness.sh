#!/bin/bash
# Simple liveness check for agent-yaml

set -e

echo "🔍 Running agent-yaml liveness check..."

# Cleanup
rm -f /tmp/liveness-test.txt

# Validate
echo "Validating workflow..."
agent-yaml validate examples/liveness-check.yaml

# Run
echo "Executing workflow..."
agent-yaml run examples/liveness-check.yaml

# Check result
if [ -f "/tmp/liveness-test.txt" ]; then
    echo "✅ Liveness check passed!"
    cat /tmp/liveness-test.txt
    echo ""
    echo "Cleanup: rm /tmp/liveness-test.txt"
else
    echo "❌ Liveness check failed - no output file created"
    exit 1
fi
