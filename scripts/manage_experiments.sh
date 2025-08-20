#!/bin/bash

# Experiment Management Tool for Fluid ODE Simulation
# This script provides various management functions for experiment directories

set -e

# Change to project root directory
cd "$(dirname "$0")/.."

echo "========================================="
echo "   Experiment Management Tool"
echo "========================================="
echo ""

# Default values
EXPERIMENTS_DIR="data/experiments"
ACTION="list"
LIMIT=10
SORT_BY="time"
VERBOSE=false

# Function to format file size
format_size() {
    local size=$1
    if [ $size -lt 1024 ]; then
        echo "${size}B"
    elif [ $size -lt 1048576 ]; then
        echo "$(( size / 1024 ))KB"
    else
        echo "$(( size / 1048576 ))MB"
    fi
}

# Function to list experiments
list_experiments() {
    echo "Listing experiments (sorted by $SORT_BY):"
    echo ""
    
    if [ ! -d "$EXPERIMENTS_DIR" ]; then
        echo "No experiments directory found."
        return
    fi
    
    # Count total experiments
    TOTAL=$(find $EXPERIMENTS_DIR -maxdepth 1 -name "experiment_*" -type d 2>/dev/null | wc -l | tr -d ' ')
    
    if [ $TOTAL -eq 0 ]; then
        echo "No experiments found."
        return
    fi
    
    echo "Total experiments: $TOTAL"
    echo "Showing: $([ $LIMIT -lt $TOTAL ] && echo $LIMIT || echo $TOTAL) most recent"
    echo ""
    
    # Get list of experiments with details
    echo "┌────────────────────────────┬──────────────────────┬──────────┬───────────┬─────────┐"
    echo "│ Experiment Name            │ Date & Time          │ Size     │ Requests  │ Status  │"
    echo "├────────────────────────────┼──────────────────────┼──────────┼───────────┼─────────┤"
    
    # Sort experiments based on criteria
    case $SORT_BY in
        time)
            EXPERIMENTS=$(ls -dt $EXPERIMENTS_DIR/experiment_* 2>/dev/null | head -$LIMIT)
            ;;
        size)
            EXPERIMENTS=$(du -s $EXPERIMENTS_DIR/experiment_* 2>/dev/null | sort -rn | head -$LIMIT | cut -f2)
            ;;
        name)
            EXPERIMENTS=$(ls -d $EXPERIMENTS_DIR/experiment_* 2>/dev/null | sort -r | head -$LIMIT)
            ;;
        *)
            EXPERIMENTS=$(ls -dt $EXPERIMENTS_DIR/experiment_* 2>/dev/null | head -$LIMIT)
            ;;
    esac
    
    for exp_dir in $EXPERIMENTS; do
        if [ -d "$exp_dir" ]; then
            # Extract experiment name
            EXP_NAME=$(basename $exp_dir)
            
            # Get creation time from directory name
            TIMESTAMP=$(echo $EXP_NAME | sed 's/experiment_\([0-9]*_[0-9]*\)_.*/\1/')
            DATE_TIME=$(echo $TIMESTAMP | sed 's/\([0-9]\{4\}\)\([0-9]\{2\}\)\([0-9]\{2\}\)_\([0-9]\{2\}\)\([0-9]\{2\}\)\([0-9]\{2\}\)/\1-\2-\3 \4:\5:\6/')
            
            # Get directory size
            DIR_SIZE=$(du -sb $exp_dir 2>/dev/null | cut -f1)
            SIZE_STR=$(format_size $DIR_SIZE)
            
            # Check for request count from meta file
            REQ_COUNT="N/A"
            if [ -f "$exp_dir/experiment_meta.yaml" ]; then
                REQ_COUNT=$(grep "total_requests:" $exp_dir/experiment_meta.yaml 2>/dev/null | sed 's/.*: //' || echo "N/A")
            fi
            
            # Check completion status
            STATUS="✓"
            if [ -f "$exp_dir/summary.txt" ]; then
                if grep -q "完成请求数: 0" $exp_dir/summary.txt 2>/dev/null; then
                    STATUS="✗"
                fi
            else
                STATUS="?"
            fi
            
            # Format and print row
            printf "│ %-26s │ %-20s │ %8s │ %9s │ %7s │\n" \
                "${EXP_NAME:0:26}" "$DATE_TIME" "$SIZE_STR" "$REQ_COUNT" "$STATUS"
        fi
    done
    
    echo "└────────────────────────────┴──────────────────────┴──────────┴───────────┴─────────┘"
    echo ""
    echo "Legend: ✓ = Complete, ✗ = Failed, ? = Unknown"
}

# Function to show experiment details
show_details() {
    local exp_name=$1
    
    if [ -z "$exp_name" ]; then
        # Show latest experiment
        exp_dir=$(ls -dt $EXPERIMENTS_DIR/experiment_* 2>/dev/null | head -1)
        if [ -z "$exp_dir" ]; then
            echo "No experiments found."
            return
        fi
    else
        exp_dir="$EXPERIMENTS_DIR/$exp_name"
        if [ ! -d "$exp_dir" ]; then
            echo "Experiment not found: $exp_name"
            return
        fi
    fi
    
    echo "Experiment Details: $(basename $exp_dir)"
    echo "═══════════════════════════════════════════"
    echo ""
    
    # Show metadata
    if [ -f "$exp_dir/experiment_meta.yaml" ]; then
        echo "Metadata:"
        echo "─────────"
        cat $exp_dir/experiment_meta.yaml | sed 's/^/  /'
        echo ""
    fi
    
    # Show configuration
    if [ -f "$exp_dir/config_used.yaml" ] && [ "$VERBOSE" = true ]; then
        echo "Configuration:"
        echo "──────────────"
        cat $exp_dir/config_used.yaml | head -20 | sed 's/^/  /'
        echo "  ..."
        echo ""
    fi
    
    # Show summary
    if [ -f "$exp_dir/summary.txt" ]; then
        echo "Summary:"
        echo "────────"
        cat $exp_dir/summary.txt | sed 's/^/  /'
        echo ""
    fi
    
    # List files
    echo "Files:"
    echo "──────"
    ls -lh $exp_dir/*.csv $exp_dir/*.txt $exp_dir/*.yaml $exp_dir/*.png 2>/dev/null | \
        awk '{print "  " $9 " (" $5 ")"}' | sed "s|$exp_dir/||g"
    echo ""
    
    # Show total size
    TOTAL_SIZE=$(du -sh $exp_dir | cut -f1)
    echo "Total Size: $TOTAL_SIZE"
}

# Function to compare experiments
compare_experiments() {
    local exp1=$1
    local exp2=$2
    
    if [ -z "$exp1" ] || [ -z "$exp2" ]; then
        echo "Usage: $0 compare <experiment1> <experiment2>"
        return
    fi
    
    exp1_dir="$EXPERIMENTS_DIR/$exp1"
    exp2_dir="$EXPERIMENTS_DIR/$exp2"
    
    if [ ! -d "$exp1_dir" ]; then
        echo "Experiment not found: $exp1"
        return
    fi
    
    if [ ! -d "$exp2_dir" ]; then
        echo "Experiment not found: $exp2"
        return
    fi
    
    echo "Comparing Experiments:"
    echo "═════════════════════"
    echo "  Experiment 1: $exp1"
    echo "  Experiment 2: $exp2"
    echo ""
    
    # Compare summaries
    echo "Performance Metrics Comparison:"
    echo "───────────────────────────────"
    
    # Extract metrics from summary files
    if [ -f "$exp1_dir/summary.txt" ] && [ -f "$exp2_dir/summary.txt" ]; then
        echo "                        Experiment 1    Experiment 2    Difference"
        echo "                        ────────────    ────────────    ──────────"
        
        # Extract and compare key metrics
        for metric in "总时间" "总批次数" "完成请求数" "平均延迟" "最大延迟" "吞吐量"; do
            val1=$(grep "$metric" $exp1_dir/summary.txt | head -1 | sed 's/.*: //' | sed 's/[^0-9.]//g')
            val2=$(grep "$metric" $exp2_dir/summary.txt | head -1 | sed 's/.*: //' | sed 's/[^0-9.]//g')
            
            if [ -n "$val1" ] && [ -n "$val2" ]; then
                diff=$(echo "scale=2; $val2 - $val1" | bc 2>/dev/null || echo "N/A")
                printf "%-22s %12s    %12s    %10s\n" "$metric:" "$val1" "$val2" "$diff"
            fi
        done
    else
        echo "  Summary files not found for comparison."
    fi
    
    echo ""
    
    # Compare configurations
    if [ "$VERBOSE" = true ]; then
        echo "Configuration Differences:"
        echo "─────────────────────────"
        if [ -f "$exp1_dir/config_used.yaml" ] && [ -f "$exp2_dir/config_used.yaml" ]; then
            diff -u $exp1_dir/config_used.yaml $exp2_dir/config_used.yaml | head -50 || echo "  No differences found."
        else
            echo "  Configuration files not found."
        fi
        echo ""
    fi
}

# Function to archive old experiments
archive_experiments() {
    local days=$1
    
    if [ -z "$days" ]; then
        days=7
    fi
    
    echo "Archiving experiments older than $days days..."
    echo ""
    
    # Create archive directory
    ARCHIVE_DIR="$EXPERIMENTS_DIR/archive"
    mkdir -p $ARCHIVE_DIR
    
    # Find and archive old experiments
    COUNT=0
    for exp_dir in $EXPERIMENTS_DIR/experiment_*; do
        if [ -d "$exp_dir" ]; then
            # Check age
            if [ $(find "$exp_dir" -maxdepth 0 -mtime +$days 2>/dev/null | wc -l) -gt 0 ]; then
                EXP_NAME=$(basename $exp_dir)
                echo "  Archiving: $EXP_NAME"
                
                # Create tar.gz archive
                tar -czf "$ARCHIVE_DIR/${EXP_NAME}.tar.gz" -C "$EXPERIMENTS_DIR" "$EXP_NAME" 2>/dev/null
                
                # Remove original directory
                rm -rf "$exp_dir"
                COUNT=$((COUNT + 1))
            fi
        fi
    done
    
    if [ $COUNT -eq 0 ]; then
        echo "No experiments to archive."
    else
        echo ""
        echo "Archived $COUNT experiment(s) to $ARCHIVE_DIR/"
    fi
}

# Function to export experiment data
export_experiment() {
    local exp_name=$1
    local output=$2
    
    if [ -z "$exp_name" ]; then
        echo "Usage: $0 export <experiment_name> [output_file]"
        return
    fi
    
    exp_dir="$EXPERIMENTS_DIR/$exp_name"
    if [ ! -d "$exp_dir" ]; then
        echo "Experiment not found: $exp_name"
        return
    fi
    
    if [ -z "$output" ]; then
        output="${exp_name}_export.tar.gz"
    fi
    
    echo "Exporting experiment: $exp_name"
    echo "Output file: $output"
    echo ""
    
    tar -czf "$output" -C "$EXPERIMENTS_DIR" "$exp_name"
    
    if [ $? -eq 0 ]; then
        SIZE=$(ls -lh "$output" | awk '{print $5}')
        echo "Export complete: $output ($SIZE)"
    else
        echo "Export failed."
    fi
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        list)
            ACTION="list"
            shift
            ;;
        details|show)
            ACTION="details"
            EXPERIMENT_NAME=$2
            shift 2
            ;;
        compare)
            ACTION="compare"
            EXP1=$2
            EXP2=$3
            shift 3
            ;;
        archive)
            ACTION="archive"
            ARCHIVE_DAYS=$2
            shift 2
            ;;
        export)
            ACTION="export"
            EXPORT_NAME=$2
            EXPORT_OUTPUT=$3
            shift 3
            ;;
        stats)
            ACTION="stats"
            shift
            ;;
        --limit)
            LIMIT=$2
            shift 2
            ;;
        --sort)
            SORT_BY=$2
            shift 2
            ;;
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [ACTION] [OPTIONS]"
            echo ""
            echo "Actions:"
            echo "  list                    List all experiments (default)"
            echo "  details [name]          Show details of an experiment"
            echo "  compare <exp1> <exp2>   Compare two experiments"
            echo "  archive [days]          Archive experiments older than N days (default: 7)"
            echo "  export <name> [output]  Export experiment to tar.gz"
            echo "  stats                   Show overall statistics"
            echo ""
            echo "Options:"
            echo "  --limit N              Limit number of experiments shown (default: 10)"
            echo "  --sort [time|size|name] Sort experiments by criteria (default: time)"
            echo "  --verbose, -v          Show more details"
            echo "  --help, -h             Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0 list --limit 20"
            echo "  $0 details experiment_20241215_143022_1234"
            echo "  $0 compare experiment_1 experiment_2 --verbose"
            echo "  $0 archive 30"
            echo "  $0 export experiment_20241215_143022_1234 my_experiment.tar.gz"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Execute the requested action
case $ACTION in
    list)
        list_experiments
        ;;
    details)
        show_details "$EXPERIMENT_NAME"
        ;;
    compare)
        compare_experiments "$EXP1" "$EXP2"
        ;;
    archive)
        archive_experiments "$ARCHIVE_DAYS"
        ;;
    export)
        export_experiment "$EXPORT_NAME" "$EXPORT_OUTPUT"
        ;;
    stats)
        echo "Overall Statistics:"
        echo "═══════════════════"
        echo ""
        
        if [ -d "$EXPERIMENTS_DIR" ]; then
            TOTAL=$(find $EXPERIMENTS_DIR -maxdepth 1 -name "experiment_*" -type d 2>/dev/null | wc -l | tr -d ' ')
            TOTAL_SIZE=$(du -sh $EXPERIMENTS_DIR 2>/dev/null | cut -f1)
            
            echo "  Total experiments: $TOTAL"
            echo "  Total disk usage: $TOTAL_SIZE"
            
            if [ $TOTAL -gt 0 ]; then
                echo ""
                echo "  Latest experiment:"
                LATEST=$(ls -dt $EXPERIMENTS_DIR/experiment_* 2>/dev/null | head -1)
                if [ -n "$LATEST" ]; then
                    echo "    $(basename $LATEST)"
                fi
                
                echo ""
                echo "  Oldest experiment:"
                OLDEST=$(ls -dt $EXPERIMENTS_DIR/experiment_* 2>/dev/null | tail -1)
                if [ -n "$OLDEST" ]; then
                    echo "    $(basename $OLDEST)"
                fi
            fi
            
            # Check for archived experiments
            if [ -d "$EXPERIMENTS_DIR/archive" ]; then
                ARCHIVED=$(ls $EXPERIMENTS_DIR/archive/*.tar.gz 2>/dev/null | wc -l | tr -d ' ')
                if [ $ARCHIVED -gt 0 ]; then
                    echo ""
                    echo "  Archived experiments: $ARCHIVED"
                fi
            fi
        else
            echo "  No experiments directory found."
        fi
        ;;
    *)
        list_experiments
        ;;
esac

echo ""
echo "========================================="
echo "   Done!"
echo "========================================="