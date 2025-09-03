#!/usr/bin/env python3
"""
对比图生成脚本
生成不同准入控制阈值的性能对比图

使用方法：
    python plot_comparison.py

输出：
    - performance_comparison.png: 性能指标对比图（吞吐量和延迟）
    - arrival_completion_comparison.png: 到达完成动态对比图
"""

import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import re


def extract_threshold(dirname):
    """从目录名提取threshold值"""
    match = re.search(r'threshold=([\d.]+)', dirname)
    if match:
        return float(match.group(1))
    return None


def get_experiment_dirs():
    """获取所有实验目录并按threshold排序"""
    base_dir = Path(__file__).parent
    dirs = []
    
    for d in base_dir.iterdir():
        if d.is_dir() and 'threshold=' in d.name:
            threshold = extract_threshold(d.name)
            if threshold is not None:
                dirs.append((threshold, d))
    
    # 按threshold排序
    dirs.sort(key=lambda x: x[0])
    return dirs


def plot_performance_comparison():
    """
    绘制性能指标对比图
    图1：Average Decode Throughput和Average Latency随时间变化
    """
    print("生成性能指标对比图...")
    
    # 获取所有实验目录
    exp_dirs = get_experiment_dirs()
    if not exp_dirs:
        print("没有找到实验数据目录")
        return
    
    # 创建图形
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))
    
    # 使用更鲜明的颜色对比
    # 手动定义颜色，从冷色到暖色
    color_list = ['#0000FF', '#008000', '#00CED1', '#FFA500', 
                  '#FF6347', '#DC143C', '#FF1493', '#8B008B']
    colors = color_list[:len(exp_dirs)]
    
    for idx, (threshold, exp_dir) in enumerate(exp_dirs):
        # 读取request_traces.csv
        request_file = exp_dir / 'request_traces.csv'
        if not request_file.exists():
            print(f"跳过 {exp_dir.name}: 缺少request_traces.csv")
            continue
        
        df_requests = pd.read_csv(request_file)
        
        # 过滤已完成的请求
        df_completed = df_requests[df_requests['completion_time'].notna()].copy()
        if df_completed.empty:
            print(f"跳过 {exp_dir.name}: 没有已完成的请求")
            continue
        
        # 按completion_time排序
        df_completed = df_completed.sort_values('completion_time')
        
        # 计算累积指标
        times = []
        avg_throughputs = []
        avg_latencies = []
        
        # 按时间窗口计算（每100个请求为一个点，避免数据过密）
        window_size = max(1, len(df_completed) // 100)
        
        for i in range(window_size, len(df_completed) + 1, window_size):
            subset = df_completed.iloc[:i]
            current_time = subset['completion_time'].iloc[-1]
            
            # 累积解码吞吐量
            total_decode = subset['decode_length'].sum()
            avg_throughput = total_decode / current_time if current_time > 0 else 0
            
            # 累积平均延迟
            avg_latency = subset['total_delay'].mean()
            
            times.append(current_time)
            avg_throughputs.append(avg_throughput)
            avg_latencies.append(avg_latency)
        
        # 绘制曲线
        label = f'threshold={threshold:.2f}' if threshold < 1.0 else f'threshold={threshold:.1f}'
        ax1.plot(times, avg_throughputs, color=colors[idx], label=label, linewidth=1.5)
        ax2.plot(times, avg_latencies, color=colors[idx], label=label, linewidth=1.5)
    
    # 设置第一个子图（吞吐量）
    ax1.set_xlabel('Time', fontsize=11)
    ax1.set_ylabel('Average Decode Throughput (tokens/time)', fontsize=11)
    ax1.set_title('Average Decode Throughput Over Time', fontsize=12, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='best', ncol=2, fontsize=9)
    
    # 设置第二个子图（延迟）
    ax2.set_xlabel('Time', fontsize=11)
    ax2.set_ylabel('Average Latency', fontsize=11)
    ax2.set_title('Average Latency Over Time', fontsize=12, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc='best', ncol=2, fontsize=9)
    
    # 添加总标题
    fig.suptitle('Performance Metrics Comparison - Different Admission Control Thresholds', 
                 fontsize=14, fontweight='bold')
    
    plt.tight_layout()
    
    # 保存图形
    output_path = Path(__file__).parent / 'performance_comparison.png'
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"性能指标对比图已保存到: {output_path}")
    plt.close()


def plot_arrival_completion_comparison():
    """
    绘制到达完成动态对比图
    图2：累积和窗口化的外部到达与完成
    """
    print("生成到达完成动态对比图...")
    
    # 获取所有实验目录
    exp_dirs = get_experiment_dirs()
    if not exp_dirs:
        print("没有找到实验数据目录")
        return
    
    # 创建2x2子图
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
    
    # 使用更鲜明的颜色对比
    color_list = ['#0000FF', '#008000', '#00CED1', '#FFA500', 
                  '#FF6347', '#DC143C', '#FF1493', '#8B008B']
    colors = color_list[:len(exp_dirs)]
    
    # 系统参数（所有实验相同）
    d_0 = 0.003
    d_1 = 0.00032
    B_max = 10000  # 近似最大批次token数
    
    # 计算时间窗口
    ws = 20
    interval = (d_0 + d_1 * B_max) * ws
    interval = max(interval, 20.0)  # 至少20个时间单位
    
    # 存储所有实验的最大时间，用于统一横轴
    max_time = 0
    arrival_end_time = 0
    
    # 第一遍：获取最大时间
    for threshold, exp_dir in exp_dirs:
        batch_file = exp_dir / 'batch_snapshots.csv'
        if batch_file.exists():
            df_batch = pd.read_csv(batch_file)
            if not df_batch.empty:
                max_time = max(max_time, df_batch['time'].max())
        
        # 获取arrival_end时间（从events.csv）
        events_file = exp_dir / 'events.csv'
        if events_file.exists():
            df_events = pd.read_csv(events_file)
            arrival_events = df_events[df_events['event_type'] == 'arrival']
            if not arrival_events.empty:
                arrival_end_time = max(arrival_end_time, arrival_events['time'].max())
    
    # 创建统一的时间窗口
    time_windows = np.arange(0, max_time + interval, interval)
    window_centers = (time_windows[:-1] + time_windows[1:]) / 2
    
    # 第二遍：绘制数据
    for idx, (threshold, exp_dir) in enumerate(exp_dirs):
        # 读取events.csv
        events_file = exp_dir / 'events.csv'
        if not events_file.exists():
            print(f"跳过 {exp_dir.name}: 缺少events.csv")
            continue
        
        df_events = pd.read_csv(events_file)
        
        # 分离arrival和completion事件
        arrival_events = df_events[df_events['event_type'] == 'arrival'].copy()
        completion_events = df_events[df_events['event_type'] == 'completion'].copy()
        
        if arrival_events.empty and completion_events.empty:
            print(f"跳过 {exp_dir.name}: 没有有效事件")
            continue
        
        # 排序
        arrival_events = arrival_events.sort_values('time')
        completion_events = completion_events.sort_values('time')
        
        # 获取当前实验的仿真结束时间
        batch_file = exp_dir / 'batch_snapshots.csv'
        simulation_end = max_time  # 默认值
        if batch_file.exists():
            df_batch = pd.read_csv(batch_file)
            if not df_batch.empty:
                simulation_end = df_batch['time'].max()
        
        label = f'threshold={threshold:.2f}' if threshold < 1.0 else f'threshold={threshold:.1f}'
        color = colors[idx]
        
        # 子图1：累积外部到达
        if not arrival_events.empty:
            times = arrival_events['time'].values
            cumulative = np.arange(1, len(times) + 1)
            ax1.plot(times, cumulative, color=color, label=label, linewidth=1.5)
        
        # 子图2：累积完成
        if not completion_events.empty:
            times = completion_events['time'].values
            cumulative = np.arange(1, len(times) + 1)
            ax2.plot(times, cumulative, color=color, label=label, linewidth=1.5)
        
        # 子图3和4：窗口化的到达率和完成率
        arrival_windowed = []
        completion_windowed = []
        
        for i in range(len(time_windows) - 1):
            window_start = time_windows[i]
            window_end = time_windows[i + 1]
            
            # 统计窗口内的到达数
            arrivals_in_window = len(arrival_events[
                (arrival_events['time'] >= window_start) & 
                (arrival_events['time'] < window_end)
            ])
            arrival_rate = arrivals_in_window / interval
            arrival_windowed.append(arrival_rate)
            
            # 统计窗口内的完成数
            completions_in_window = len(completion_events[
                (completion_events['time'] >= window_start) & 
                (completion_events['time'] < window_end)
            ])
            completion_rate = completions_in_window / interval
            completion_windowed.append(completion_rate)
        
        # 绘制窗口化的率
        if arrival_windowed:
            ax3.plot(window_centers, arrival_windowed, color=color, 
                    label=label, linewidth=1.5, alpha=0.8)
        if completion_windowed:
            ax4.plot(window_centers, completion_windowed, color=color, 
                    label=label, linewidth=1.5, alpha=0.8)
        
        # 添加仿真结束标记线（使用相同颜色的虚线）
        for ax in [ax1, ax2, ax3, ax4]:
            ax.axvline(x=simulation_end, color=color, linestyle=':', 
                      alpha=0.5, linewidth=0.8)
    
    # 添加到达结束标记线（所有实验相同，红色虚线）
    for ax in [ax1, ax2, ax3, ax4]:
        ax.axvline(x=arrival_end_time, color='red', linestyle='--', 
                  alpha=0.7, label='Arrival End', linewidth=1.2)
    
    # 设置子图1
    ax1.set_xlabel('Time', fontsize=11)
    ax1.set_ylabel('Cumulative External Arrivals', fontsize=11)
    ax1.set_title('Cumulative External Arrivals', fontsize=12, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='best', fontsize=8, ncol=2)
    
    # 设置子图2
    ax2.set_xlabel('Time', fontsize=11)
    ax2.set_ylabel('Cumulative Completions', fontsize=11)
    ax2.set_title('Cumulative Completions', fontsize=12, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc='best', fontsize=8, ncol=2)
    
    # 设置子图3
    ax3.set_xlabel('Time', fontsize=11)
    ax3.set_ylabel('External Arrival Rate (requests/time)', fontsize=11)
    ax3.set_title('Windowed External Arrival Rate', fontsize=12, fontweight='bold')
    ax3.grid(True, alpha=0.3)
    ax3.legend(loc='best', fontsize=8, ncol=2)
    
    # 设置子图4
    ax4.set_xlabel('Time', fontsize=11)
    ax4.set_ylabel('Completion Rate (requests/time)', fontsize=11)
    ax4.set_title('Windowed Completion Rate', fontsize=12, fontweight='bold')
    ax4.grid(True, alpha=0.3)
    ax4.legend(loc='best', fontsize=8, ncol=2)
    
    # 添加总标题
    fig.suptitle('Arrival & Completion Dynamics - Different Admission Control Thresholds', 
                 fontsize=14, fontweight='bold')
    
    plt.tight_layout()
    
    # 保存图形
    output_path = Path(__file__).parent / 'arrival_completion_comparison.png'
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"到达完成动态对比图已保存到: {output_path}")
    plt.close()


def plot_individual_metrics():
    """
    生成6个独立的子图
    """
    print("\n生成独立子图...")
    
    # 获取所有实验目录
    exp_dirs = get_experiment_dirs()
    if not exp_dirs:
        print("没有找到实验数据目录")
        return
    
    # 使用更鲜明的颜色对比
    color_list = ['#0000FF', '#008000', '#00CED1', '#FFA500', 
                  '#FF6347', '#DC143C', '#FF1493', '#8B008B']
    colors = color_list[:len(exp_dirs)]
    
    # 系统参数
    d_0 = 0.003
    d_1 = 0.00032
    B_max = 10000
    ws = 20
    interval = (d_0 + d_1 * B_max) * ws
    interval = max(interval, 20.0)
    
    # 获取最大时间和arrival_end时间
    max_time = 0
    arrival_end_time = 0
    
    for threshold, exp_dir in exp_dirs:
        batch_file = exp_dir / 'batch_snapshots.csv'
        if batch_file.exists():
            df_batch = pd.read_csv(batch_file)
            if not df_batch.empty:
                max_time = max(max_time, df_batch['time'].max())
        
        events_file = exp_dir / 'events.csv'
        if events_file.exists():
            df_events = pd.read_csv(events_file)
            arrival_events = df_events[df_events['event_type'] == 'arrival']
            if not arrival_events.empty:
                arrival_end_time = max(arrival_end_time, arrival_events['time'].max())
    
    time_windows = np.arange(0, max_time + interval, interval)
    window_centers = (time_windows[:-1] + time_windows[1:]) / 2
    
    # 图1：Average Decode Throughput
    fig, ax = plt.subplots(figsize=(12, 6))
    for idx, (threshold, exp_dir) in enumerate(exp_dirs):
        request_file = exp_dir / 'request_traces.csv'
        if not request_file.exists():
            continue
        df_requests = pd.read_csv(request_file)
        df_completed = df_requests[df_requests['completion_time'].notna()].copy()
        if df_completed.empty:
            continue
        df_completed = df_completed.sort_values('completion_time')
        
        times = []
        avg_throughputs = []
        window_size = max(1, len(df_completed) // 100)
        
        for i in range(window_size, len(df_completed) + 1, window_size):
            subset = df_completed.iloc[:i]
            current_time = subset['completion_time'].iloc[-1]
            total_decode = subset['decode_length'].sum()
            avg_throughput = total_decode / current_time if current_time > 0 else 0
            times.append(current_time)
            avg_throughputs.append(avg_throughput)
        
        label = f'threshold={threshold:.2f}' if threshold < 1.0 else f'threshold={threshold:.1f}'
        ax.plot(times, avg_throughputs, color=colors[idx], label=label, linewidth=2)
    
    ax.set_xlabel('Time', fontsize=12)
    ax.set_ylabel('Average Decode Throughput (tokens/time)', fontsize=12)
    ax.set_title('Average Decode Throughput Over Time', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    ax.legend(loc='best', fontsize=10)
    plt.tight_layout()
    plt.savefig('avg_decode_throughput.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("  - avg_decode_throughput.png")
    
    # 图2：Average Latency
    fig, ax = plt.subplots(figsize=(12, 6))
    for idx, (threshold, exp_dir) in enumerate(exp_dirs):
        request_file = exp_dir / 'request_traces.csv'
        if not request_file.exists():
            continue
        df_requests = pd.read_csv(request_file)
        df_completed = df_requests[df_requests['completion_time'].notna()].copy()
        if df_completed.empty:
            continue
        df_completed = df_completed.sort_values('completion_time')
        
        times = []
        avg_latencies = []
        window_size = max(1, len(df_completed) // 100)
        
        for i in range(window_size, len(df_completed) + 1, window_size):
            subset = df_completed.iloc[:i]
            current_time = subset['completion_time'].iloc[-1]
            avg_latency = subset['total_delay'].mean()
            times.append(current_time)
            avg_latencies.append(avg_latency)
        
        label = f'threshold={threshold:.2f}' if threshold < 1.0 else f'threshold={threshold:.1f}'
        ax.plot(times, avg_latencies, color=colors[idx], label=label, linewidth=2)
    
    ax.set_xlabel('Time', fontsize=12)
    ax.set_ylabel('Average Latency', fontsize=12)
    ax.set_title('Average Latency Over Time', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    ax.legend(loc='best', fontsize=10)
    plt.tight_layout()
    plt.savefig('avg_latency.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("  - avg_latency.png")
    
    # 准备数据用于后续4个图
    all_data = []
    for idx, (threshold, exp_dir) in enumerate(exp_dirs):
        events_file = exp_dir / 'events.csv'
        if not events_file.exists():
            continue
        
        df_events = pd.read_csv(events_file)
        arrival_events = df_events[df_events['event_type'] == 'arrival'].copy()
        completion_events = df_events[df_events['event_type'] == 'completion'].copy()
        
        batch_file = exp_dir / 'batch_snapshots.csv'
        simulation_end = max_time
        if batch_file.exists():
            df_batch = pd.read_csv(batch_file)
            if not df_batch.empty:
                simulation_end = df_batch['time'].max()
        
        all_data.append({
            'threshold': threshold,
            'color': colors[idx],
            'arrival_events': arrival_events.sort_values('time'),
            'completion_events': completion_events.sort_values('time'),
            'simulation_end': simulation_end
        })
    
    # 图3：Cumulative External Arrivals
    fig, ax = plt.subplots(figsize=(12, 6))
    for data in all_data:
        if not data['arrival_events'].empty:
            times = data['arrival_events']['time'].values
            cumulative = np.arange(1, len(times) + 1)
            label = f"threshold={data['threshold']:.2f}" if data['threshold'] < 1.0 else f"threshold={data['threshold']:.1f}"
            ax.plot(times, cumulative, color=data['color'], label=label, linewidth=2)
            ax.axvline(x=data['simulation_end'], color=data['color'], linestyle=':', alpha=0.5, linewidth=1)
    
    ax.axvline(x=arrival_end_time, color='red', linestyle='--', alpha=0.7, label='Arrival End', linewidth=2)
    ax.set_xlabel('Time', fontsize=12)
    ax.set_ylabel('Cumulative External Arrivals', fontsize=12)
    ax.set_title('Cumulative External Arrivals Over Time', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    ax.legend(loc='best', fontsize=10)
    plt.tight_layout()
    plt.savefig('cumulative_arrivals.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("  - cumulative_arrivals.png")
    
    # 图4：Cumulative Completions
    fig, ax = plt.subplots(figsize=(12, 6))
    for data in all_data:
        if not data['completion_events'].empty:
            times = data['completion_events']['time'].values
            cumulative = np.arange(1, len(times) + 1)
            label = f"threshold={data['threshold']:.2f}" if data['threshold'] < 1.0 else f"threshold={data['threshold']:.1f}"
            ax.plot(times, cumulative, color=data['color'], label=label, linewidth=2)
            ax.axvline(x=data['simulation_end'], color=data['color'], linestyle=':', alpha=0.5, linewidth=1)
    
    ax.axvline(x=arrival_end_time, color='red', linestyle='--', alpha=0.7, label='Arrival End', linewidth=2)
    ax.set_xlabel('Time', fontsize=12)
    ax.set_ylabel('Cumulative Completions', fontsize=12)
    ax.set_title('Cumulative Completions Over Time', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    ax.legend(loc='best', fontsize=10)
    plt.tight_layout()
    plt.savefig('cumulative_completions.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("  - cumulative_completions.png")
    
    # 图5：Windowed External Arrival Rate
    fig, ax = plt.subplots(figsize=(12, 6))
    for data in all_data:
        arrival_windowed = []
        for i in range(len(time_windows) - 1):
            window_start = time_windows[i]
            window_end = time_windows[i + 1]
            arrivals_in_window = len(data['arrival_events'][
                (data['arrival_events']['time'] >= window_start) & 
                (data['arrival_events']['time'] < window_end)
            ])
            arrival_rate = arrivals_in_window / interval
            arrival_windowed.append(arrival_rate)
        
        if arrival_windowed:
            label = f"threshold={data['threshold']:.2f}" if data['threshold'] < 1.0 else f"threshold={data['threshold']:.1f}"
            ax.plot(window_centers, arrival_windowed, color=data['color'], 
                   label=label, linewidth=2, alpha=0.9)
            ax.axvline(x=data['simulation_end'], color=data['color'], linestyle=':', alpha=0.5, linewidth=1)
    
    ax.axvline(x=arrival_end_time, color='red', linestyle='--', alpha=0.7, label='Arrival End', linewidth=2)
    ax.set_xlabel('Time', fontsize=12)
    ax.set_ylabel('External Arrival Rate (requests/time)', fontsize=12)
    ax.set_title('Windowed External Arrival Rate', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    ax.legend(loc='best', fontsize=10)
    plt.tight_layout()
    plt.savefig('windowed_arrival_rate.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("  - windowed_arrival_rate.png")
    
    # 图6：Windowed Completion Rate
    fig, ax = plt.subplots(figsize=(12, 6))
    for data in all_data:
        completion_windowed = []
        for i in range(len(time_windows) - 1):
            window_start = time_windows[i]
            window_end = time_windows[i + 1]
            completions_in_window = len(data['completion_events'][
                (data['completion_events']['time'] >= window_start) & 
                (data['completion_events']['time'] < window_end)
            ])
            completion_rate = completions_in_window / interval
            completion_windowed.append(completion_rate)
        
        if completion_windowed:
            label = f"threshold={data['threshold']:.2f}" if data['threshold'] < 1.0 else f"threshold={data['threshold']:.1f}"
            ax.plot(window_centers, completion_windowed, color=data['color'], 
                   label=label, linewidth=2, alpha=0.9)
            ax.axvline(x=data['simulation_end'], color=data['color'], linestyle=':', alpha=0.5, linewidth=1)
    
    ax.axvline(x=arrival_end_time, color='red', linestyle='--', alpha=0.7, label='Arrival End', linewidth=2)
    ax.set_xlabel('Time', fontsize=12)
    ax.set_ylabel('Completion Rate (requests/time)', fontsize=12)
    ax.set_title('Windowed Completion Rate', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    ax.legend(loc='best', fontsize=10)
    plt.tight_layout()
    plt.savefig('windowed_completion_rate.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("  - windowed_completion_rate.png")


def main():
    """主函数"""
    print("=" * 60)
    print("准入控制阈值对比图生成器")
    print("=" * 60)
    
    # 切换到脚本所在目录
    os.chdir(Path(__file__).parent)
    
    # 生成图1：性能指标对比
    plot_performance_comparison()
    
    # 生成图2：到达完成动态对比
    plot_arrival_completion_comparison()
    
    # 生成独立的6个子图
    plot_individual_metrics()
    
    print("\n所有图形生成完成！")


if __name__ == '__main__':
    main()