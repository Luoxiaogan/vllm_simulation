#!/usr/bin/env python3
"""
Visualization tool for experiment results
Usage: python draw.py --csv /path/to/batch_snapshots.csv
"""

import argparse
import os
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path


def plot_queue_dynamics(csv_path: str, arrival_end: float = None, 
                       M_total: int = None, B_total: int = None,
                       d_0: float = None, d_1: float = None,
                       num_requests: int = None):
    """
    Plot system dynamics in two subplots (2x1 layout)
    
    Args:
        csv_path: Path to batch_snapshots.csv file
        arrival_end: Time when request arrivals end (optional)
        M_total: Total GPU memory capacity (optional)
        B_total: Batch token budget (optional)
        d_0: Base batch execution time (optional)
        d_1: Per-token execution time coefficient (optional)
        num_requests: Total number of requests (optional)
    """
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found")
        return
    
    # Load data
    df = pd.read_csv(csv_path)
    
    # Check if batch_sacrifice_count column exists
    has_sacrifice = 'batch_sacrifice_count' in df.columns
    
    # Calculate statistics
    total_time = float(df['time'].iloc[-1]) if len(df) > 0 else 0
    completed_count = int(df['completed_count'].iloc[-1]) if len(df) > 0 else 0
    
    # Calculate average rates
    avg_arrival_rate = num_requests / arrival_end if (arrival_end and arrival_end > 0) else 0
    avg_completion_rate = completed_count / total_time if total_time > 0 else 0
    
    # Create figure with 2x1 subplot layout
    fig, (ax1, ax3) = plt.subplots(2, 1, figsize=(14, 12))
    
    # Add super title with system parameters and statistics
    title_lines = []
    
    # Line 1: System parameters
    params = []
    if M_total is not None:
        params.append(f"M={M_total:,}")
    if B_total is not None:
        params.append(f"B={B_total:,}")
    if d_0 is not None and d_1 is not None:
        params.append(f"Exec Time: {d_0} + {d_1}×B(t)")
    
    if params:
        title_lines.append("System Config: " + "  |  ".join(params))
    
    # Line 2: Statistics
    stats = []
    if num_requests is not None:
        stats.append(f"Requests: {num_requests}")
    stats.append(f"Sim Time: {total_time:.1f}")
    if avg_arrival_rate > 0:
        stats.append(f"λ_arr: {avg_arrival_rate:.2f}/t")
    if avg_completion_rate > 0:
        stats.append(f"λ_comp: {avg_completion_rate:.2f}/t")
    if completed_count > 0 and num_requests:
        completion_ratio = (completed_count / num_requests * 100)
        stats.append(f"Completed: {completed_count}/{num_requests} ({completion_ratio:.1f}%)")
    
    if stats:
        title_lines.append("Simulation Stats: " + "  |  ".join(stats))
    
    # Set the suptitle with multiple lines
    if title_lines:
        suptitle_text = "\n".join(title_lines)
        fig.suptitle(suptitle_text, fontsize=11, fontweight='bold', y=0.99, 
                    bbox=dict(boxstyle="round,pad=0.5", facecolor="lightgray", alpha=0.3))
    
    # ========== Top subplot: Queue dynamics ==========
    # Primary y-axis: Queue counts
    ax1.plot(df['time'], df['waiting_count'], 
            label='Waiting', color='blue', linewidth=2, marker='o', markersize=3)
    ax1.plot(df['time'], df['running_count'], 
            label='Running', color='green', linewidth=2, marker='s', markersize=3)
    
    # Secondary y-axis: Sacrifice counts (if available)
    if has_sacrifice:
        ax2 = ax1.twinx()
        ax2.bar(df['time'], df['batch_sacrifice_count'], 
                color='red', alpha=0.5, width=df['time'].diff().median() * 0.8,
                label='Batch Sacrifices')
        ax2.set_ylabel('Sacrifices per Batch', fontsize=11, color='red')
        ax2.tick_params(axis='y', labelcolor='red')
        ax2.set_ylim(bottom=0)
        
        # Combine legends from both axes
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=10)
    else:
        ax1.legend(loc='upper left', fontsize=10)
    
    # Set labels and title for top subplot
    ax1.set_xlabel('Time', fontsize=12)
    ax1.set_ylabel('Number of Requests', fontsize=12)
    ax1.set_title('Queue Dynamics and Sacrifice Events', fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3, linestyle='--')
    ax1.set_ylim(bottom=0)
    
    # Add vertical line for arrival end time if provided
    if arrival_end is not None:
        ax1.axvline(x=arrival_end, color='black', linestyle='--', linewidth=2, 
                   alpha=0.7, label=f'Arrival End ({arrival_end:.1f})')
        # Update legend to include the vertical line
        if has_sacrifice:
            lines1, labels1 = ax1.get_legend_handles_labels()
            lines2, labels2 = ax2.get_legend_handles_labels()
            ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=10)
        else:
            ax1.legend(loc='upper left', fontsize=10)
    
    # ========== Bottom subplot: Memory and token usage ==========
    # Primary y-axis: Batch tokens
    color = 'tab:blue'
    ax3.set_xlabel('Time', fontsize=12)
    ax3.set_ylabel('Batch Tokens', fontsize=12, color=color)
    ax3.plot(df['time'], df['batch_tokens'], 
            label='Batch Tokens', color=color, linewidth=2, marker='o', markersize=3)
    ax3.tick_params(axis='y', labelcolor=color)
    ax3.set_ylim(bottom=0)
    
    # Add horizontal line for B_total if provided
    if B_total is not None:
        ax3.axhline(y=B_total, color=color, linestyle=':', linewidth=2, 
                   alpha=0.7, label=f'B_total ({B_total})')
    
    # Secondary y-axis: GPU memory usage
    ax4 = ax3.twinx()
    color = 'tab:orange'
    ax4.set_ylabel('GPU Memory Used', fontsize=12, color=color)
    ax4.plot(df['time'], df['gpu_memory_used'], 
            label='GPU Memory Used', color=color, linewidth=2, marker='s', markersize=3)
    ax4.tick_params(axis='y', labelcolor=color)
    ax4.set_ylim(bottom=0)
    
    # Add horizontal line for M_total if provided
    if M_total is not None:
        ax4.axhline(y=M_total, color=color, linestyle=':', linewidth=2, 
                   alpha=0.7, label=f'M_total ({M_total})')
    
    # Add vertical line for arrival end time if provided
    if arrival_end is not None:
        ax3.axvline(x=arrival_end, color='black', linestyle='--', linewidth=2, 
                   alpha=0.7, label=f'Arrival End')
    
    # Combine legends for bottom subplot
    lines3, labels3 = ax3.get_legend_handles_labels()
    lines4, labels4 = ax4.get_legend_handles_labels()
    ax3.legend(lines3 + lines4, labels3 + labels4, loc='upper left', fontsize=10)
    
    # Set title for bottom subplot
    ax3.set_title('Memory and Token Usage', fontsize=14, fontweight='bold')
    ax3.grid(True, alpha=0.3, linestyle='--')
    
    # Adjust layout to prevent label cutoff and make room for suptitle
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    
    # Get directory path from CSV path
    exp_dir = os.path.dirname(csv_path)
    
    # Save figure
    output_path = os.path.join(exp_dir, 'queue_dynamics.png')
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"Figure saved to: {output_path}")
    
    # Also save as PDF for publication quality
    pdf_path = os.path.join(exp_dir, 'queue_dynamics.pdf')
    plt.savefig(pdf_path, bbox_inches='tight')
    print(f"PDF saved to: {pdf_path}")
    
    # Show plot (optional, can be commented out for headless environments)
    plt.show()


def main():
    """
    Main function
    """
    parser = argparse.ArgumentParser(
        description='Visualize experiment results',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        '--csv', 
        type=str, 
        required=True,
        help='Path to batch_snapshots.csv file (e.g., /path/to/experiment/batch_snapshots.csv)'
    )
    parser.add_argument(
        '--arrival_end',
        type=float,
        default=None,
        help='Time when request arrivals end (optional, adds vertical line marker)'
    )
    
    args = parser.parse_args()
    
    # Validate file exists
    if not os.path.isfile(args.csv):
        print(f"Error: File {args.csv} does not exist")
        return
    
    print(f"Processing CSV file: {args.csv}")
    if args.arrival_end is not None:
        print(f"Marking arrival end time at: {args.arrival_end}")
    
    # Plot queue dynamics (without M_total and B_total when called from command line)
    plot_queue_dynamics(args.csv, args.arrival_end)


if __name__ == "__main__":
    main()