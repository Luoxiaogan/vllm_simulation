#!/usr/bin/env python3
"""
Visualization tool for experiment results
Usage: python draw.py --csv /path/to/batch_snapshots.csv
"""

import argparse
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


def plot_queue_dynamics(csv_path: str, arrival_end: float = None, 
                       M_total: int = None, B_total: int = None,
                       d_0: float = None, d_1: float = None,
                       num_requests: int = None, state_save_batches: list = None):
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
        state_save_batches: List of batch IDs where state was saved (optional)
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
    # Use single y-axis for all request counts
    ax1.set_xlabel('Time', fontsize=12)
    ax1.set_ylabel('Number of Requests', fontsize=12)
    
    # Plot waiting and running counts
    ax1.plot(df['time'], df['waiting_count'], 
            label='Waiting', color='blue', linewidth=2, marker='o', markersize=3)
    ax1.plot(df['time'], df['running_count'], 
            label='Running', color='green', linewidth=2, marker='s', markersize=3)
    
    # Plot sacrifice counts as bars (if available)
    if has_sacrifice:
        # Use bar chart for per-batch sacrifice count
        ax1.bar(df['time'], df['batch_sacrifice_count'], 
                color='red', alpha=0.5, width=df['time'].diff().median() * 0.8,
                label='Sacrifices per Batch')
    
    # Add vertical line for arrival end time if provided
    if arrival_end is not None:
        ax1.axvline(x=arrival_end, color='black', linestyle='--', linewidth=2, 
                   alpha=0.7, label=f'Arrival End ({arrival_end:.1f})')
    
    # Add vertical lines for state save batches if provided
    if state_save_batches:
        # Find the times corresponding to these batch IDs
        state_save_info = []
        for batch_id in state_save_batches:
            # Find the row with this batch_id
            batch_rows = df[df['batch_id'] == batch_id]
            if not batch_rows.empty:
                save_time = batch_rows['time'].iloc[0]
                state_save_info.append((batch_id, save_time))
                ax1.axvline(x=save_time, color='red', linestyle='--', linewidth=1.5, 
                           alpha=0.6)
        
        # Create a combined legend label with batch IDs and times
        if state_save_info:
            batch_ids_str = str([b for b, _ in state_save_info])
            times_str = ', '.join([f'{t:.0f}' for _, t in state_save_info])
            legend_label = f'State Save {batch_ids_str}\n(t={times_str})'
            # Add a dummy line for the legend
            ax1.plot([], [], color='red', linestyle='--', linewidth=1.5, 
                    alpha=0.6, label=legend_label)
    
    # Set legend
    ax1.legend(loc='upper left', fontsize=10)
    
    # Set title and grid
    ax1.set_title('Queue Dynamics and Sacrifice Events', fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3, linestyle='--')
    ax1.set_ylim(bottom=0)
    
    # ========== Bottom subplot: Memory and token usage ==========
    # Use single y-axis for both batch tokens and GPU memory (both are token counts)
    ax3.set_xlabel('Time', fontsize=12)
    ax3.set_ylabel('Number of Tokens', fontsize=12)
    
    # Plot batch tokens
    ax3.plot(df['time'], df['batch_tokens'], 
            label='Batch Tokens (after execution)', color='tab:blue', linewidth=2, marker='o', markersize=3)
    
    # Plot GPU memory used
    ax3.plot(df['time'], df['gpu_memory_used'], 
            label='GPU Memory Used', color='tab:orange', linewidth=2, marker='s', markersize=3)
    
    # Add horizontal line for B_total if provided
    if B_total is not None:
        ax3.axhline(y=B_total, color='tab:blue', linestyle=':', linewidth=2, 
                   alpha=0.7, label=f'B_total ({B_total:,})')
    
    # Add horizontal line for M_total if provided
    if M_total is not None:
        ax3.axhline(y=M_total, color='tab:orange', linestyle=':', linewidth=2, 
                   alpha=0.7, label=f'M_total ({M_total:,})')
    
    # Add vertical line for arrival end time if provided
    if arrival_end is not None:
        ax3.axvline(x=arrival_end, color='black', linestyle='--', linewidth=2, 
                   alpha=0.7, label=f'Arrival End')
    
    # Add legend
    ax3.legend(loc='upper left', fontsize=10)
    
    # Set y-axis limits
    ax3.set_ylim(bottom=0)
    
    # Optionally set upper limit based on max of M_total and data
    if M_total is not None:
        max_val = max(M_total * 1.1, df['gpu_memory_used'].max() * 1.1)
        ax3.set_ylim(top=max_val)
    
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
    
    # # Also save as PDF for publication quality
    # pdf_path = os.path.join(exp_dir, 'queue_dynamics.pdf')
    # plt.savefig(pdf_path, bbox_inches='tight')
    # print(f"PDF saved to: {pdf_path}")
    
    # Close the figure to free memory (no display)
    plt.close(fig)
    
    # 如果存在sacrifice数据，绘制sacrifice动态图
    plot_sacrifice_dynamics(exp_dir, request_file=None)


def plot_sacrifice_dynamics(exp_dir: str, request_file: str = None):
    """
    绘制sacrifice动态图并保存分布数据
    
    Args:
        exp_dir: 实验目录路径
        request_file: 原始请求文件路径（用于获取max_decode_length）
    """
    # 检查sacrifice_snapshot.csv是否存在
    sacrifice_csv = os.path.join(exp_dir, 'sacrifice_snapshot.csv')
    if not os.path.exists(sacrifice_csv):
        return  # 没有sacrifice事件，跳过
    
    # 读取sacrifice数据
    df_sacrifice = pd.read_csv(sacrifice_csv)
    if df_sacrifice.empty:
        return
    
    print(f"Processing sacrifice data: {len(df_sacrifice)} events")
    
    # 检查是否有新的上下文列
    has_context = 'running_count_same_position' in df_sacrifice.columns and \
                  'total_running_count' in df_sacrifice.columns
    
    # 获取max_decode_position用于绘图
    # 实际被sacrifice的最大位置
    actual_max_position = int(df_sacrifice['current_decode_position'].max())
    
    # 理论最大decode长度（如果有请求文件）
    theoretical_max_length = None
    if request_file and os.path.exists(request_file):
        df_requests = pd.read_csv(request_file)
        # decode_length是长度，位置是0到length-1
        theoretical_max_length = int(df_requests['decode_length'].max()) - 1
    
    # 用于绘图的最大位置：取实际最大位置，但不超过理论最大值
    if theoretical_max_length is not None:
        max_decode_position = min(actual_max_position, theoretical_max_length)
    else:
        max_decode_position = actual_max_position
    
    print(f"Actual max sacrifice position: {actual_max_position}")
    if theoretical_max_length is not None:
        print(f"Theoretical max position (decode_length-1): {theoretical_max_length}")
    print(f"Using max position for plotting: {max_decode_position}")
    
    # 创建子图：如果有上下文数据则3x1，否则2x1
    if has_context:
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 16))
    else:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 12))
    
    # ========== 第一个子图：双纵轴 ==========
    # 获取所有唯一时间点并排序
    unique_times = sorted(df_sacrifice['time'].unique())
    
    # 统计每个时间点的sacrifice数量和浪费tokens
    time_stats = []
    for t in unique_times:
        df_t = df_sacrifice[df_sacrifice['time'] == t]
        time_stats.append({
            'time': t,
            'count': len(df_t),
            'memory_freed': df_t['memory_freed'].sum()
        })
    df_stats = pd.DataFrame(time_stats)
    
    # 左纵轴：请求数量（柱状图）
    ax1_left = ax1
    bar_width = np.diff(unique_times).mean() * 0.8 if len(unique_times) > 1 else 1.0
    ax1_left.bar(df_stats['time'], df_stats['count'], 
                 width=bar_width, color='blue', alpha=0.5, 
                 label='Sacrificed Requests per Time')
    ax1_left.set_xlabel('Time', fontsize=12)
    ax1_left.set_ylabel('Number of Sacrificed Requests', color='blue', fontsize=12)
    ax1_left.tick_params(axis='y', labelcolor='blue')
    
    # 右纵轴：累计浪费的tokens（线图）
    ax1_right = ax1.twinx()
    cumulative_wasted = df_stats['memory_freed'].cumsum()
    ax1_right.plot(df_stats['time'], cumulative_wasted, 
                   color='red', linewidth=2, marker='o', markersize=4,
                   label='Cumulative Wasted Tokens')
    ax1_right.set_ylabel('Cumulative Wasted Tokens', color='red', fontsize=12)
    ax1_right.tick_params(axis='y', labelcolor='red')
    
    # 添加图例
    lines1, labels1 = ax1_left.get_legend_handles_labels()
    lines2, labels2 = ax1_right.get_legend_handles_labels()
    ax1_left.legend(lines1 + lines2, labels1 + labels2, loc='upper left')
    
    ax1.set_title('Sacrifice Events and Wasted Tokens Over Time', fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3, linestyle='--')
    
    # ========== 第二个子图：概率分布 ==========
    # 创建概率矩阵（时间 x 位置）
    prob_matrix_list = []
    
    # 为每个sacrifice事件计算到该时间点的累积分布
    # 这样如果有899个事件，就会有899行
    for idx in range(len(df_sacrifice)):
        current_time = df_sacrifice.iloc[idx]['time']
        
        # 获取到当前时间为止的所有sacrifice事件（包括当前）
        df_until_now = df_sacrifice.iloc[:idx+1]
        
        # 统计各decode_position的数量
        position_counts = df_until_now['current_decode_position'].value_counts()
        total_count = len(df_until_now)
        
        # 创建这个时间点的概率行
        row_data = {'time': current_time}
        for pos in range(max_decode_position + 1):
            prob = position_counts.get(pos, 0) / total_count if total_count > 0 else 0
            row_data[f'position_{pos}'] = prob
        
        prob_matrix_list.append(row_data)
    
    # 转换为DataFrame
    prob_matrix = pd.DataFrame(prob_matrix_list)
    
    if not prob_matrix.empty:
        # 绘制所有decode positions的概率分布线条
        # 使用matplotlib的默认颜色循环
        # 获取默认的颜色循环
        prop_cycle = plt.rcParams['axes.prop_cycle']
        colors = prop_cycle.by_key()['color']
        
        # 绘制所有位置的线条
        for pos in range(max_decode_position + 1):
            col_name = f'position_{pos}'
            if col_name in prob_matrix.columns:
                # 获取这个位置的概率序列
                probs = prob_matrix[col_name].astype(float)
                times = prob_matrix['time'].astype(float)
                
                # 绘制所有线条，即使概率很小
                # 使用颜色循环
                color = colors[pos % len(colors)]
                ax2.plot(times, probs, 
                        color=color, linewidth=0.8, alpha=0.8,
                        label=f'Pos {pos}')
        
        ax2.set_xlabel('Time', fontsize=12)
        ax2.set_ylabel('Probability', fontsize=12)
        ax2.set_ylim([0, 1])
        ax2.set_title('Distribution of Sacrifice Positions Over Time (Cumulative)', 
                     fontsize=14, fontweight='bold')
        
        # 显示图例（可能会很多，使用小字体和多列）
        ax2.legend(bbox_to_anchor=(1.05, 1), loc='upper left', 
                  ncol=3, fontsize=6)
        
        ax2.grid(True, alpha=0.3, linestyle='--')
    
    # ========== 第三个子图：条件概率时间序列（如果有上下文数据）==========
    if has_context:
        # 计算每个时间点每个位置的条件概率
        # P(sacrifice | position, time) = 对该时间该位置的所有事件，先算每行概率再平均
        
        # 获取所有唯一时间点
        unique_times = sorted(df_sacrifice['time'].unique())
        
        # 创建时间-位置-概率映射
        time_position_prob = {}
        
        for t in unique_times:
            time_events = df_sacrifice[df_sacrifice['time'] == t]
            time_position_prob[t] = {}
            
            # 对每个decode_position计算条件概率
            for pos in time_events['current_decode_position'].unique():
                pos_events = time_events[time_events['current_decode_position'] == pos]
                
                # 计算每行的条件概率（1/running_count_same_position）
                # 这表示：在该位置有N个请求时，这个请求被选中sacrifice的概率
                row_probs = 1.0 / pos_events['running_count_same_position']
                
                # 求平均作为该时间该位置的条件概率
                avg_prob = row_probs.mean()
                
                time_position_prob[t][pos] = avg_prob
        
        # 准备绘图数据
        # 为每个出现过的decode_position创建一条时间序列线
        all_positions = sorted(set(
            pos for time_dict in time_position_prob.values() 
            for pos in time_dict.keys()
        ))
        
        # 使用matplotlib的默认颜色循环
        prop_cycle = plt.rcParams['axes.prop_cycle']
        colors = prop_cycle.by_key()['color']
        
        # 绘制每个位置的概率时间序列
        for i, pos in enumerate(all_positions):
            times = []
            probs = []
            
            for t in unique_times:
                if pos in time_position_prob[t]:
                    times.append(t)
                    probs.append(time_position_prob[t][pos])
            
            if times:  # 只绘制有数据的位置
                color = colors[i % len(colors)]
                ax3.plot(times, probs, 
                        color=color, linewidth=1.5, alpha=0.8,
                        marker='o', markersize=3,
                        label=f'Position {pos}')
        
        ax3.set_xlabel('Time', fontsize=12)
        ax3.set_ylabel('Conditional Probability P(sacrifice | position, time)', fontsize=12)
        ax3.set_ylim([0, 1])
        ax3.set_title('Conditional Probability of Sacrifice Over Time', 
                     fontsize=14, fontweight='bold')
        
        # 添加图例（可能会很多，使用小字体和多列）
        if len(all_positions) > 10:
            ax3.legend(bbox_to_anchor=(1.05, 1), loc='upper left', 
                      ncol=2, fontsize=6)
        else:
            ax3.legend(loc='upper right', fontsize=8)
        
        ax3.grid(True, alpha=0.3, linestyle='--')
    
    # 调整布局
    plt.tight_layout()
    
    # 保存图片
    output_path = os.path.join(exp_dir, 'sacrifice_dynamics.png')
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"Sacrifice dynamics saved to: {output_path}")
    plt.close(fig)
    
    # 保存分布数据到CSV（宽格式矩阵）
    if not prob_matrix.empty:
        dist_csv_path = os.path.join(exp_dir, 'sacrifice_distribution.csv')
        prob_matrix.to_csv(dist_csv_path, index=False)
        print(f"Sacrifice distribution saved to: {dist_csv_path}")
    
    # 如果有上下文数据，保存条件概率时间序列
    if has_context and time_position_prob:
        # 保存条件概率时间序列（宽格式：时间 x 位置）
        cond_prob_csv_path = os.path.join(exp_dir, 'sacrifice_conditional_prob_timeline.csv')
        
        # 获取所有位置
        all_positions_for_csv = sorted(set(
            pos for time_dict in time_position_prob.values() 
            for pos in time_dict.keys()
        ))
        
        # 创建宽格式数据
        cond_prob_rows = []
        for t in sorted(time_position_prob.keys()):
            row = {'time': t}
            for pos in all_positions_for_csv:
                col_name = f'position_{pos}'
                # 如果该时间该位置有概率，使用它；否则为0
                row[col_name] = time_position_prob[t].get(pos, 0.0)
            cond_prob_rows.append(row)
        
        # 写入CSV
        if cond_prob_rows:
            fieldnames = ['time'] + [f'position_{pos}' for pos in all_positions_for_csv]
            
            import csv
            with open(cond_prob_csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(cond_prob_rows)
            
            print(f"Conditional probability timeline saved to: {cond_prob_csv_path}")


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