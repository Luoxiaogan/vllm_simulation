#!/usr/bin/env python3
"""
分析sacrifice模式的实验结果
"""
import pandas as pd
import sys
import os

def analyze_sacrifice_experiment(experiment_dir):
    """
    分析sacrifice实验的结果
    """
    print("="*60)
    print("Sacrifice模式分析")
    print("="*60)
    
    # 1. 分析请求轨迹
    traces_file = os.path.join(experiment_dir, "request_traces.csv")
    if os.path.exists(traces_file):
        df_traces = pd.read_csv(traces_file)
        
        print("\n1. Sacrifice统计:")
        print(f"   总请求数: {len(df_traces)}")
        print(f"   被sacrifice过的请求数: {(df_traces['sacrifice_count'] > 0).sum()}")
        print(f"   平均sacrifice次数: {df_traces['sacrifice_count'].mean():.2f}")
        print(f"   最大sacrifice次数: {df_traces['sacrifice_count'].max()}")
        print(f"   中位数sacrifice次数: {df_traces['sacrifice_count'].median():.0f}")
        
        # 找出被sacrifice最多的请求
        print("\n2. 被sacrifice最多的10个请求:")
        top_sacrificed = df_traces.nlargest(10, 'sacrifice_count')[
            ['req_id', 'prefill_length', 'decode_length', 'sacrifice_count', 'total_delay']
        ]
        print(top_sacrificed.to_string(index=False))
        
        # 分析sacrifice分布
        print("\n3. Sacrifice次数分布:")
        bins = [0, 1, 10, 50, 100, 200, 500, 1000, float('inf')]
        labels = ['0', '1-9', '10-49', '50-99', '100-199', '200-499', '500-999', '1000+']
        df_traces['sacrifice_bin'] = pd.cut(df_traces['sacrifice_count'], bins=bins, labels=labels, right=False)
        distribution = df_traces['sacrifice_bin'].value_counts().sort_index()
        for bin_label, count in distribution.items():
            percentage = (count / len(df_traces)) * 100
            print(f"   {bin_label:10s}: {count:5d} ({percentage:5.1f}%)")
    
    # 2. 分析事件日志
    events_file = os.path.join(experiment_dir, "events.csv")
    if os.path.exists(events_file):
        df_events = pd.read_csv(events_file)
        
        # 统计事件类型
        print("\n4. 事件类型统计:")
        event_counts = df_events['event_type'].value_counts()
        for event_type, count in event_counts.items():
            print(f"   {event_type:20s}: {count:10d}")
        
        # 分析sacrifice事件的时间分布
        sacrifice_events = df_events[df_events['event_type'] == 'sacrifice']
        if len(sacrifice_events) > 0:
            print("\n5. Sacrifice事件时间分析:")
            print(f"   第一次sacrifice时间: {sacrifice_events['time'].min():.2f}")
            print(f"   最后一次sacrifice时间: {sacrifice_events['time'].max():.2f}")
            print(f"   Sacrifice频率: {len(sacrifice_events) / (sacrifice_events['time'].max() - sacrifice_events['time'].min()):.2f} 次/时间单位")
    
    # 3. 分析批次快照
    snapshots_file = os.path.join(experiment_dir, "batch_snapshots.csv")
    if os.path.exists(snapshots_file):
        df_snapshots = pd.read_csv(snapshots_file)
        
        print("\n6. 系统状态分析:")
        print(f"   平均running数: {df_snapshots['running_count'].mean():.2f}")
        print(f"   平均waiting数: {df_snapshots['waiting_count'].mean():.2f}")
        print(f"   平均内存利用率: {df_snapshots['memory_utilization'].mean():.2%}")
        print(f"   最大内存利用率: {df_snapshots['memory_utilization'].max():.2%}")
        
        # 检测异常情况
        high_waiting = df_snapshots[df_snapshots['waiting_count'] > 100]
        if len(high_waiting) > 0:
            print(f"\n   警告：有{len(high_waiting)}个批次的waiting队列超过100!")
            
        low_memory = df_snapshots[df_snapshots['memory_utilization'] < 0.5]
        if len(low_memory) > 0:
            percentage = (len(low_memory) / len(df_snapshots)) * 100
            print(f"   警告：{percentage:.1f}%的时间内存利用率低于50%!")
    
    print("\n" + "="*60)
    print("分析建议:")
    
    # 根据数据给出建议
    if os.path.exists(traces_file):
        avg_sacrifice = df_traces['sacrifice_count'].mean()
        if avg_sacrifice > 10:
            print("⚠️  Sacrifice次数过高！建议：")
            print("   1. 切换到conservative策略")
            print("   2. 增加GPU内存(M_total)")
            print("   3. 减少批次预算(B)")
            print("   4. 考虑使用swap模式代替sacrifice")
        elif avg_sacrifice > 5:
            print("⚠️  Sacrifice次数偏高，建议优化参数")
        else:
            print("✓  Sacrifice次数在合理范围内")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        # 使用最新的实验目录
        experiment_dir = "data/experiments/experiment_20250819_151133_2020"
    else:
        experiment_dir = sys.argv[1]
    
    if not os.path.exists(experiment_dir):
        print(f"错误：找不到实验目录 {experiment_dir}")
        sys.exit(1)
    
    analyze_sacrifice_experiment(experiment_dir)