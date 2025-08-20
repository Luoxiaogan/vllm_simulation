"""
系统动态可视化
"""
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os
import glob
from pathlib import Path


def find_latest_experiment(base_dir: str = "data/experiments") -> str:
    """
    Find the latest experiment directory
    
    Args:
        base_dir: Base directory containing experiments
        
    Returns:
        Path to latest experiment directory
    """
    pattern = os.path.join(base_dir, "experiment_*")
    exp_dirs = glob.glob(pattern)
    
    if not exp_dirs:
        # Fallback to old output directory
        if os.path.exists("data/output"):
            return "data/output"
        raise ValueError(f"No experiment directories found in {base_dir}")
    
    # Sort by modification time
    latest = max(exp_dirs, key=os.path.getmtime)
    return latest


def plot_system_dynamics(output_dir: str = None):
    """
    Plot system dynamics
    
    Args:
        output_dir: Output directory (if None, use latest experiment)
    """
    if output_dir is None:
        output_dir = find_latest_experiment()
        print(f"Using experiment directory: {output_dir}")
    # 读取数据
    snapshots = pd.read_csv(f"{output_dir}/batch_snapshots.csv")
    
    # 创建图形
    fig, axes = plt.subplots(3, 2, figsize=(12, 10))
    fig.suptitle('LLM Service System Dynamics Simulation', fontsize=14, fontweight='bold')
    
    # 1. 队列长度
    ax = axes[0, 0]
    ax.plot(snapshots['time'], snapshots['waiting_count'], label='Waiting', color='blue')
    ax.plot(snapshots['time'], snapshots['running_count'], label='Running', color='green')
    ax.plot(snapshots['time'], snapshots['swapped_count'], label='Swapped', color='orange')
    ax.set_xlabel('Time')
    ax.set_ylabel('Number of Requests')
    ax.set_title('Queue States')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # 2. 内存使用
    ax = axes[0, 1]
    ax.plot(snapshots['time'], snapshots['gpu_memory_used'], label='GPU Memory Used', color='red')
    ax.axhline(y=10000, color='black', linestyle='--', label='Memory Limit')
    ax.fill_between(snapshots['time'], 0, snapshots['gpu_memory_used'], alpha=0.3, color='red')
    ax.set_xlabel('Time')
    ax.set_ylabel('Tokens')
    ax.set_title('GPU Memory Usage')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # 3. 内存利用率
    ax = axes[1, 0]
    ax.plot(snapshots['time'], snapshots['memory_utilization'] * 100, color='purple')
    ax.set_xlabel('Time')
    ax.set_ylabel('Utilization (%)')
    ax.set_title('Memory Utilization')
    ax.grid(True, alpha=0.3)
    
    # 4. 批次执行时间
    ax = axes[1, 1]
    ax.plot(snapshots['time'], snapshots['batch_duration'], color='brown')
    ax.set_xlabel('Time')
    ax.set_ylabel('Duration')
    ax.set_title('Batch Execution Time')
    ax.grid(True, alpha=0.3)
    
    # 5. 累计完成数
    ax = axes[2, 0]
    ax.plot(snapshots['time'], snapshots['completed_count'], color='green', linewidth=2)
    ax.set_xlabel('Time')
    ax.set_ylabel('Completed Requests')
    ax.set_title('Cumulative Completions')
    ax.grid(True, alpha=0.3)
    
    # 6. 吞吐量（移动平均）
    ax = axes[2, 1]
    window = min(20, len(snapshots) // 4)
    if window > 1:
        throughput = snapshots['completed_count'].diff() / snapshots['time'].diff()
        throughput_ma = throughput.rolling(window=window).mean()
        ax.plot(snapshots['time'], throughput_ma, color='teal')
    ax.set_xlabel('Time')
    ax.set_ylabel('Requests/Time Unit')
    ax.set_title(f'Throughput ({window}-batch Moving Average)')
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # 保存图片
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path / 'system_dynamics.png', dpi=150, bbox_inches='tight')
    print(f"System dynamics plot saved to: {output_path / 'system_dynamics.png'}")
    
    plt.show()


def plot_request_timeline(output_dir: str = None, sample_size: int = 20):
    """
    Plot request timeline
    
    Args:
        output_dir: Output directory (if None, use latest experiment)
        sample_size: Number of requests to sample
    """
    if output_dir is None:
        output_dir = find_latest_experiment()
        print(f"Using experiment directory: {output_dir}")
    # 读取数据
    traces = pd.read_csv(f"{output_dir}/request_traces.csv")
    
    # 采样请求
    if len(traces) > sample_size:
        sampled = traces.sample(n=sample_size, random_state=42).sort_values('req_id')
    else:
        sampled = traces
    
    # 创建图形
    fig, ax = plt.subplots(figsize=(12, 8))
    
    # 绘制每个请求的时间线
    for idx, row in sampled.iterrows():
        req_id = row['req_id']
        y_pos = req_id
        
        # 等待时间（蓝色）
        if pd.notna(row['waiting_time']) and row['waiting_time'] > 0:
            ax.barh(y_pos, row['waiting_time'], 
                   left=row['arrival_time'], height=0.8,
                   color='blue', alpha=0.6)
        
        # 执行时间（绿色）
        if pd.notna(row['execution_time']) and pd.notna(row['completion_time']):
            exec_start = row['arrival_time'] + (row['waiting_time'] if pd.notna(row['waiting_time']) else 0)
            ax.barh(y_pos, row['execution_time'],
                   left=exec_start, height=0.8,
                   color='green', alpha=0.6)
        
        # 标记swap次数
        if row['swap_count'] > 0:
            ax.text(row['completion_time'] if pd.notna(row['completion_time']) else row['arrival_time'],
                   y_pos, f" S:{int(row['swap_count'])}", 
                   va='center', fontsize=8, color='red')
    
    ax.set_xlabel('Time')
    ax.set_ylabel('Request ID')
    ax.set_title(f'Request Timeline (Sample of {len(sampled)} requests)')
    ax.legend(['Waiting Time', 'Execution Time'], loc='upper right')
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # 保存图片
    output_path = Path(output_dir)
    plt.savefig(output_path / 'request_timeline.png', dpi=150, bbox_inches='tight')
    print(f"Request timeline saved to: {output_path / 'request_timeline.png'}")
    
    plt.show()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Plot system dynamics")
    parser.add_argument("--experiment-dir", type=str, default=None,
                       help="Experiment directory (default: latest)")
    parser.add_argument("--output_dir", type=str, default=None,
                       help="Output directory (deprecated, use --experiment-dir)")
    parser.add_argument("--sample_size", type=int, default=20,
                       help="Request timeline sample size")
    
    args = parser.parse_args()
    
    # Handle backward compatibility
    exp_dir = args.experiment_dir or args.output_dir
    
    plot_system_dynamics(exp_dir)
    plot_request_timeline(exp_dir, args.sample_size)