#!/usr/bin/env python3
"""
测试准入控制功能
比较有无准入控制的系统行为差异
"""

import argparse
import subprocess
import os
import sys
import yaml
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_experiment(config_file, mode, description):
    """
    运行单个实验
    
    Args:
        config_file: 配置文件路径
        mode: 运行模式 (explore/truncate)
        description: 实验描述
        
    Returns:
        实验输出目录
    """
    print(f"\n{'='*60}")
    print(f"运行实验: {description}")
    print(f"配置文件: {config_file}")
    print(f"模式: {mode}")
    print(f"{'='*60}")
    
    cmd = [
        'python', 'experiments/run_with_truncation.py',
        '--config', config_file,
        '--mode', mode
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        # 打印关键输出
        output_lines = result.stdout.split('\n')
        for line in output_lines:
            if any(keyword in line for keyword in [
                '准入控制', '实验输出目录', '仿真完成', 
                '平均延迟', '请求吞吐量', '拒绝次数', '最大内存使用率'
            ]):
                print(line)
        
        # 提取输出目录
        for line in output_lines:
            if '实验输出目录:' in line:
                output_dir = line.split('实验输出目录:')[1].strip()
                return output_dir
                
    except subprocess.CalledProcessError as e:
        print(f"实验失败: {e}")
        if e.stderr:
            print(f"错误输出: {e.stderr}")
        return None
    
    return None


def compare_results(dir1, dir2):
    """
    比较两个实验的结果
    
    Args:
        dir1: 第一个实验的输出目录
        dir2: 第二个实验的输出目录
    """
    print(f"\n{'='*60}")
    print("结果对比")
    print(f"{'='*60}")
    
    # 读取汇总文件
    summary1_path = os.path.join(dir1, 'summary.txt') if dir1 else None
    summary2_path = os.path.join(dir2, 'summary.txt') if dir2 else None
    
    if summary1_path and os.path.exists(summary1_path):
        print(f"\n实验1 ({dir1}):")
        with open(summary1_path, 'r') as f:
            lines = f.readlines()
            for line in lines:
                if any(keyword in line for keyword in [
                    '平均延迟', '最大延迟', '吞吐量', '内存利用率'
                ]):
                    print(f"  {line.strip()}")
    
    if summary2_path and os.path.exists(summary2_path):
        print(f"\n实验2 ({dir2}):")
        with open(summary2_path, 'r') as f:
            lines = f.readlines()
            for line in lines:
                if any(keyword in line for keyword in [
                    '平均延迟', '最大延迟', '吞吐量', '内存利用率'
                ]):
                    print(f"  {line.strip()}")


def create_test_configs():
    """
    创建测试用的配置文件
    """
    # 基础配置
    base_config = {
        'system': {
            'M_total': 5000,  # 较小的内存，更容易看到准入控制效果
            'B': 5000,
            'd_0': 0.003,
            'd_1': 0.00032
        },
        'control': {
            'queue_policy': 'FCFS',
            'preemption_mode': 'sacrifice',
            'preemption_strategy': 'aggressive',
            'allow_waiting_preempt': False,
            'victim_policy': 'LIFO'
        },
        'data': {
            'request_file': 'data/input/test_admission.csv',
            'experiments_dir': 'data/experiments',
            'L_filter': None
        },
        'experiment': {
            'seed': 42,
            'verbose': True,
            'progress_interval': 50
        },
        'generation': {
            'enabled': True,
            'types': '{(20,20,8.0)}',  # 高到达率，容易触发准入控制
            'num_requests': 5000,
            'output': 'data/input/test_admission.csv',
            'seed': 42
        },
        'explore': {
            'candidate_batches': []
        },
        'regression_interval': [100, 300]
    }
    
    # 无准入控制配置
    config_no_ac = base_config.copy()
    config_no_ac['admission_control'] = {
        'enabled': False
    }
    
    # 有准入控制配置（阈值0.7）
    config_with_ac = base_config.copy()
    config_with_ac['admission_control'] = {
        'enabled': True,
        'threshold': 0.7
    }
    
    # 保存配置文件
    with open('config/test_no_admission.yaml', 'w') as f:
        yaml.dump(config_no_ac, f, default_flow_style=False)
    
    with open('config/test_with_admission.yaml', 'w') as f:
        yaml.dump(config_with_ac, f, default_flow_style=False)
    
    print("测试配置文件已创建:")
    print("  - config/test_no_admission.yaml (无准入控制)")
    print("  - config/test_with_admission.yaml (准入控制阈值: 0.7)")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="测试准入控制功能")
    parser.add_argument("--create-configs", action="store_true",
                       help="创建测试配置文件")
    parser.add_argument("--mode", type=str, default="explore",
                       choices=['explore', 'truncate'],
                       help="运行模式")
    
    args = parser.parse_args()
    
    if args.create_configs:
        create_test_configs()
        return
    
    print("="*60)
    print("准入控制功能测试")
    print("="*60)
    
    # 运行两个实验
    dir1 = run_experiment(
        'config/explore_truncation.yaml',
        'explore',
        '基准实验（无准入控制）'
    )
    
    dir2 = run_experiment(
        'config/explore_truncation_admission_control.yaml',
        'explore',
        '准入控制实验（阈值=0.8）'
    )
    
    # 比较结果
    if dir1 and dir2:
        compare_results(dir1, dir2)
    
    print(f"\n{'='*60}")
    print("测试完成!")
    print(f"{'='*60}")
    
    print("\n建议后续步骤:")
    print("1. 查看生成的可视化图表，比较队列动态差异")
    print("2. 分析batch_snapshots.csv，观察内存使用模式")
    print("3. 尝试不同的阈值设置，找到最优配置")
    print("4. 运行截断模式，测试准入控制与截断的组合效果")


if __name__ == "__main__":
    main()