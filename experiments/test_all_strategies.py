#!/usr/bin/env python3
"""
测试所有策略组合的脚本
运行4种组合：swap+aggressive, swap+conservative, sacrifice+aggressive, sacrifice+conservative
"""
import subprocess
import sys
import os
import yaml
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_strategy_combination(mode: str, strategy: str, output_base: str = "data/experiments"):
    """
    运行特定的策略组合
    
    Args:
        mode: 'swap' 或 'sacrifice'
        strategy: 'aggressive' 或 'conservative'
        output_base: 输出基础目录
    """
    print(f"\n{'='*60}")
    print(f"运行策略组合: {mode.upper()} + {strategy.upper()}")
    print(f"{'='*60}")
    
    # 创建输出目录名
    output_dir = os.path.join(output_base, f"test_{mode}_{strategy}")
    
    # 运行命令
    cmd = [
        sys.executable,
        "experiments/run_advanced.py",
        "--config", "config/advanced_test.yaml",
        "--mode", mode,
        "--strategy", strategy,
        "--output-dir", output_dir
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(result.stdout)
        
        # 读取结果摘要
        summary_file = os.path.join(output_dir, "summary.txt")
        if os.path.exists(summary_file):
            print(f"\n策略 {mode}+{strategy} 的结果摘要:")
            with open(summary_file, 'r') as f:
                print(f.read())
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"错误：运行 {mode}+{strategy} 失败")
        print(f"错误输出：{e.stderr}")
        return False


def compare_results(output_base: str = "data/experiments"):
    """
    比较不同策略组合的结果
    """
    print(f"\n{'='*60}")
    print("策略性能对比")
    print(f"{'='*60}\n")
    
    combinations = [
        ("swap", "aggressive"),
        ("swap", "conservative"),
        ("sacrifice", "aggressive"),
        ("sacrifice", "conservative")
    ]
    
    results = {}
    
    for mode, strategy in combinations:
        output_dir = os.path.join(output_base, f"test_{mode}_{strategy}")
        meta_file = os.path.join(output_dir, "experiment_meta.yaml")
        
        if not os.path.exists(meta_file):
            print(f"警告：找不到 {mode}+{strategy} 的结果")
            continue
        
        with open(meta_file, 'r') as f:
            meta = yaml.safe_load(f)
        
        # 读取性能指标
        summary_file = os.path.join(output_dir, "summary.txt")
        metrics = {}
        
        if os.path.exists(summary_file):
            with open(summary_file, 'r') as f:
                lines = f.readlines()
                for line in lines:
                    if "平均延迟" in line:
                        metrics['avg_delay'] = float(line.split(':')[1].strip())
                    elif "Token吞吐量" in line:
                        metrics['throughput'] = float(line.split(':')[1].split()[0])
                    elif "总交换出次数" in line:
                        metrics['swap_count'] = int(line.split(':')[1].strip())
        
        results[f"{mode}+{strategy}"] = {
            'completed': meta.get('completed_requests', 0),
            'total_time': meta.get('total_time', 0),
            **metrics
        }
    
    # 打印对比表格
    print(f"{'策略组合':<20} {'完成请求':<10} {'总时间':<10} {'平均延迟':<10} {'吞吐量':<10}")
    print("-" * 60)
    
    for name, data in results.items():
        print(f"{name:<20} {data.get('completed', 0):<10} "
              f"{data.get('total_time', 0):<10.2f} "
              f"{data.get('avg_delay', 0):<10.2f} "
              f"{data.get('throughput', 0):<10.2f}")


def main():
    """
    主函数：测试所有策略组合
    """
    print("开始测试所有策略组合...")
    
    # 确保输出目录存在
    output_base = "data/experiments/strategy_comparison"
    os.makedirs(output_base, exist_ok=True)
    
    # 运行所有组合
    success_count = 0
    total_count = 4
    
    for mode in ['swap', 'sacrifice']:
        for strategy in ['aggressive', 'conservative']:
            if run_strategy_combination(mode, strategy, output_base):
                success_count += 1
    
    print(f"\n测试完成：{success_count}/{total_count} 成功")
    
    # 如果所有测试都成功，进行对比
    if success_count == total_count:
        compare_results(output_base)
    else:
        print("部分测试失败，跳过对比分析")


if __name__ == "__main__":
    main()