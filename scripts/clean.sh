#!/bin/bash

# Cleanup script for Fluid ODE Simulation
# This script cleans up generated files and directories

# Change to project root directory
cd "$(dirname "$0")/.."

echo "========================================="
echo "   Fluid ODE Simulation - Cleanup"
echo "========================================="
echo ""

# Function to safely remove directory/file
safe_remove() {
    local path=$1
    local description=$2
    
    if [ -e "$path" ]; then
        echo "Removing ${description}: ${path}"
        rm -rf "$path"
    else
        echo "Skipping ${description} (not found): ${path}"
    fi
}

# Function to ask for confirmation
confirm() {
    local prompt=$1
    local default=${2:-n}
    
    if [ "$default" = "y" ]; then
        prompt="${prompt} [Y/n]: "
    else
        prompt="${prompt} [y/N]: "
    fi
    
    read -p "$prompt" response
    response=${response:-$default}
    
    case "$response" in
        [yY][eE][sS]|[yY])
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

# Parse command line arguments
CLEAN_OUTPUT=false
CLEAN_INPUT=false
CLEAN_EXPERIMENTS=false
CLEAN_SCENARIOS=false
CLEAN_PIPELINE=false
CLEAN_ALL=false
FORCE=false
KEEP_RECENT=0

while [[ $# -gt 0 ]]; do
    case $1 in
        --output)
            CLEAN_OUTPUT=true
            shift
            ;;
        --input)
            CLEAN_INPUT=true
            shift
            ;;
        --experiments)
            CLEAN_EXPERIMENTS=true
            shift
            ;;
        --scenarios)
            CLEAN_SCENARIOS=true
            shift
            ;;
        --pipeline)
            CLEAN_PIPELINE=true
            shift
            ;;
        --all)
            CLEAN_ALL=true
            shift
            ;;
        --keep-recent)
            KEEP_RECENT=$2
            shift 2
            ;;
        --force)
            FORCE=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --output       Clean data/output directory (legacy)"
            echo "  --input        Clean generated input files"
            echo "  --experiments  Clean data/experiments directory"
            echo "  --scenarios    Clean data/scenarios directory"
            echo "  --pipeline     Clean data/full_pipeline_* directories"
            echo "  --all          Clean all generated files"
            echo "  --keep-recent N Keep N most recent experiments"
            echo "  --force        Skip confirmation prompts"
            echo "  --help         Show this help message"
            echo ""
            echo "If no options specified, defaults to cleaning experiments."
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# If no specific options, default to experiments
if [ "$CLEAN_OUTPUT" = false ] && [ "$CLEAN_INPUT" = false ] && \
   [ "$CLEAN_EXPERIMENTS" = false ] && [ "$CLEAN_SCENARIOS" = false ] && \
   [ "$CLEAN_PIPELINE" = false ] && [ "$CLEAN_ALL" = false ]; then
    CLEAN_EXPERIMENTS=true
fi

# If --all is specified, enable all cleaning
if [ "$CLEAN_ALL" = true ]; then
    CLEAN_OUTPUT=true
    CLEAN_INPUT=true
    CLEAN_EXPERIMENTS=true
    CLEAN_SCENARIOS=true
    CLEAN_PIPELINE=true
fi

# Show what will be cleaned
echo "Cleanup targets:"
[ "$CLEAN_OUTPUT" = true ] && echo "  ✓ data/output/ (legacy)"
[ "$CLEAN_INPUT" = true ] && echo "  ✓ data/input/*.csv"
[ "$CLEAN_EXPERIMENTS" = true ] && echo "  ✓ data/experiments/experiment_*"
[ "$CLEAN_SCENARIOS" = true ] && echo "  ✓ data/scenarios/"
[ "$CLEAN_PIPELINE" = true ] && echo "  ✓ data/full_pipeline_*/"
[ "$KEEP_RECENT" -gt 0 ] && echo "  (Keeping $KEEP_RECENT most recent experiments)"
echo ""

# Confirm unless --force is used
if [ "$FORCE" = false ]; then
    if ! confirm "Proceed with cleanup?"; then
        echo "Cleanup cancelled."
        exit 0
    fi
fi

echo ""
echo "Starting cleanup..."
echo ""

# Clean data/output (legacy)
if [ "$CLEAN_OUTPUT" = true ]; then
    safe_remove "data/output/*" "legacy output files"
    # Recreate empty directory
    mkdir -p data/output
fi

# Clean generated input files
if [ "$CLEAN_INPUT" = true ]; then
    echo "Cleaning generated input files..."
    for file in data/input/*.csv; do
        if [ -f "$file" ]; then
            echo "  Removing: $file"
            rm "$file"
        fi
    done
fi

# Clean experiments directory
if [ "$CLEAN_EXPERIMENTS" = true ]; then
    echo "Cleaning experiments directory..."
    
    if [ "$KEEP_RECENT" -gt 0 ]; then
        echo "  Keeping $KEEP_RECENT most recent experiments"
        
        # Get all experiment directories sorted by time (newest first)
        EXPERIMENTS=($(ls -dt data/experiments/experiment_* 2>/dev/null))
        
        # Remove all but the most recent N
        COUNT=0
        for exp_dir in "${EXPERIMENTS[@]}"; do
            COUNT=$((COUNT + 1))
            if [ $COUNT -gt $KEEP_RECENT ]; then
                safe_remove "$exp_dir" "experiment directory"
            else
                echo "  Keeping: $exp_dir"
            fi
        done
    else
        # Remove all experiments
        for exp_dir in data/experiments/experiment_*; do
            if [ -d "$exp_dir" ]; then
                safe_remove "$exp_dir" "experiment directory"
            fi
        done
    fi
fi

# Clean scenarios directory
if [ "$CLEAN_SCENARIOS" = true ]; then
    safe_remove "data/scenarios" "scenarios directory"
fi

# Clean pipeline directories
if [ "$CLEAN_PIPELINE" = true ]; then
    echo "Cleaning pipeline directories..."
    for dir in data/full_pipeline_*; do
        if [ -d "$dir" ]; then
            safe_remove "$dir" "pipeline directory"
        fi
    done
fi

# Clean Python cache
echo ""
if confirm "Also clean Python cache files (__pycache__, *.pyc)?" "n"; then
    echo "Cleaning Python cache..."
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true
    find . -type f -name "*.pyo" -delete 2>/dev/null || true
    echo "Python cache cleaned."
fi

echo ""
echo "========================================="
echo "   Cleanup Complete!"
echo "========================================="
echo ""

# Show disk space saved (if available on macOS/Linux)
if command -v du &> /dev/null; then
    echo "Remaining disk usage in data/:"
    du -sh data/* 2>/dev/null | grep -v "\.py$" || echo "  (empty)"
    
    # Show remaining experiments
    if [ -d "data/experiments" ]; then
        EXP_COUNT=$(ls -d data/experiments/experiment_* 2>/dev/null | wc -l | tr -d ' ')
        if [ "$EXP_COUNT" -gt 0 ]; then
            echo ""
            echo "Remaining experiments: $EXP_COUNT"
            ls -lt data/experiments/experiment_* 2>/dev/null | head -5
        fi
    fi
fi