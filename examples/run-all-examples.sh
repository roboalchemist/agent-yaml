#!/bin/bash
# Runner script for all agent-yaml examples
# Executes examples in order, captures logs, and cleans up

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
LOG_DIR="/tmp/agent-yaml-examples-logs"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
MASTER_LOG="$LOG_DIR/run-all-$TIMESTAMP.log"

# Examples to run (in order)
EXAMPLES=(
    "01-basic.yaml:Basic Task Execution:60"
    "02-sequential.yaml:Sequential Tasks + Variables:90"
    "03-parallel.yaml:Parallel Execution + Includes:120"
    "04-todolist-loop.yaml:TodoList Loop + Checkpointing:150"
    "05-csv-loop.yaml:CSV Loop + Filtering:150"
    "06-glob-loop.yaml:Glob Loop + Error Handling:150"
    "07-comprehensive.yaml:Comprehensive Feature Test:300"
    "08-advanced-features.yaml:Advanced Features (gitroot, ensure, checkpoint):180"
    "09-gemini.yaml:Gemini CLI Agent:300"
    "10-qwen.yaml:Qwen CLI Agent:300"
    "11-codex.yaml:Codex CLI Agent:300"
    "12-loop-filtering.yaml:Loop Filtering & Sorting:180"
)

# Statistics
TOTAL_EXAMPLES=${#EXAMPLES[@]}
PASSED=0
FAILED=0
START_TIME=$(date +%s)

echo -e "${BLUE}════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}     Agent-YAML Progressive Examples Test Suite${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════${NC}"
echo ""
echo "Total Examples: $TOTAL_EXAMPLES"
echo "Log Directory: $LOG_DIR"
echo "Master Log: $MASTER_LOG"
echo "Started: $(date)"
echo ""

# Create log directory
mkdir -p "$LOG_DIR"

# Cleanup function
cleanup() {
    echo ""
    echo -e "${YELLOW}🧹 Cleaning up test directories...${NC}"
    for i in {01..12}; do
        if [ -d "/tmp/agent-yaml-test-$i" ]; then
            rm -rf "/tmp/agent-yaml-test-$i"
            echo "   Removed: /tmp/agent-yaml-test-$i"
        fi
    done
    echo -e "${GREEN}✓ Cleanup complete${NC}"
}

# Trap to ensure cleanup on exit
trap cleanup EXIT

# Function to run a single example
run_example() {
    local example_file=$1
    local description=$2
    local timeout=$3
    local example_num=$(echo $example_file | grep -o '^[0-9]\+')
    local log_file="$LOG_DIR/example-$example_num.log"

    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}Example $example_num: $description${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    # Validate
    echo -n "  [1/3] Validating... "
    if agent-yaml validate "examples/$example_file" > "$log_file" 2>&1; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗${NC}"
        echo "  ⚠️  Validation failed! See $log_file"
        # Show last few lines of validation error
        echo "  📋 Error:"
        tail -3 "$log_file" 2>/dev/null | sed 's/^/     /'
        return 1
    fi

    # Dry run
    echo -n "  [2/3] Dry run... "
    if agent-yaml run "examples/$example_file" --dry-run --verbose >> "$log_file" 2>&1; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗${NC}"
        echo "Dry run failed! See $log_file"
        return 1
    fi

    # Execute
    echo -n "  [3/3] Executing... "
    local exec_start=$(date +%s)
    if timeout ${timeout}s agent-yaml run "examples/$example_file" --verbose >> "$log_file" 2>&1; then
        local exec_end=$(date +%s)
        local exec_time=$((exec_end - exec_start))
        echo -e "${GREEN}✓${NC} (${exec_time}s)"

        # Check output
        local output_dir="/tmp/agent-yaml-test-$example_num"
        if [ -d "$output_dir" ]; then
            local file_count=$(find "$output_dir" -type f 2>/dev/null | wc -l | tr -d ' ')
            echo "  📁 Output: $output_dir ($file_count files)"

            # Show summary if it exists (handle glob expansion safely)
            shopt -s nullglob
            local summaries=("$output_dir"/*summary*.txt "$output_dir"/*SUMMARY*.txt)
            shopt -u nullglob

            for summary in "${summaries[@]}"; do
                if [ -f "$summary" ]; then
                    echo ""
                    echo "  📋 Summary from $(basename "$summary"):"
                    sed 's/^/     /' "$summary"
                fi
            done
        fi

        return 0
    else
        local exec_end=$(date +%s)
        local exec_time=$((exec_end - exec_start))
        echo -e "${RED}✗${NC} (${exec_time}s)"
        echo "  ⚠️  Execution failed! See $log_file"

        # Show last few lines of error log
        if [ -f "$log_file" ]; then
            echo "  📋 Last 5 lines:"
            tail -5 "$log_file" 2>/dev/null | sed 's/^/     /'
        fi

        return 1
    fi
}

# Main execution loop
echo -e "${YELLOW}Starting progressive examples...${NC}"
echo ""

for example_spec in "${EXAMPLES[@]}"; do
    IFS=':' read -r file description timeout <<< "$example_spec"

    if run_example "$file" "$description" "$timeout"; then
        ((PASSED++))
        echo -e "${GREEN}✓ Example $(echo $file | grep -o '^[0-9]\+') passed${NC}"
    else
        ((FAILED++))
        example_num=$(echo $file | grep -o '^[0-9]\+')
        echo -e "${RED}✗ Example $example_num failed${NC}"

        # Note CLI tool requirements
        if [[ "$example_num" == "09" ]]; then
            echo "  ℹ️  Requires gemini CLI tool (install or skip)"
        elif [[ "$example_num" == "10" ]]; then
            echo "  ℹ️  Requires qwen CLI tool (install or skip)"
        elif [[ "$example_num" == "11" ]]; then
            echo "  ℹ️  Requires codex CLI tool (install or skip)"
        elif [[ "$example_num" == "08" ]]; then
            echo "  ℹ️  Requires git and python3 (should be installed)"
        fi

        # Ask if user wants to continue (auto-continue if --continue-on-error)
        if [ "$1" != "--continue-on-error" ]; then
            echo ""
            read -p "Continue with remaining examples? (y/n) " -n 1 -r
            echo ""
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                echo "Stopping due to failure"
                break
            fi
        fi
    fi
    echo ""
done

# Final summary
END_TIME=$(date +%s)
TOTAL_TIME=$((END_TIME - START_TIME))

echo -e "${BLUE}════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}               Final Summary${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════${NC}"
echo ""
echo "Total Examples: $TOTAL_EXAMPLES"
echo -e "Passed: ${GREEN}$PASSED${NC}"
echo -e "Failed: ${RED}$FAILED${NC}"
echo "Total Time: ${TOTAL_TIME}s"
echo ""
echo "Logs saved to: $LOG_DIR"
echo "Master log: $MASTER_LOG"
echo ""

# Create master summary log
cat > "$MASTER_LOG" <<EOF
Agent-YAML Examples Test Run
=============================
Timestamp: $(date)
Total Examples: $TOTAL_EXAMPLES
Passed: $PASSED
Failed: $FAILED
Total Time: ${TOTAL_TIME}s

Individual Logs:
$(ls -1 $LOG_DIR/example-*.log | sed 's/^/  - /')

Results:
EOF

for example_spec in "${EXAMPLES[@]}"; do
    IFS=':' read -r file description timeout <<< "$example_spec"
    num=$(echo $file | grep -o '^[0-9]\+')
    echo "  $num. $description" >> "$MASTER_LOG"
done

echo "Master summary written to: $MASTER_LOG"
echo ""

# Exit with appropriate code
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}🎉 All examples passed successfully!${NC}"
    exit 0
else
    echo -e "${RED}❌ Some examples failed. Check logs for details.${NC}"
    exit 1
fi
