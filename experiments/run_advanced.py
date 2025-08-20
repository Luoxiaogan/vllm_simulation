"""
运行高级策略仿真实验
支持Swap/Sacrifice模式和Aggressive/Conservative策略
"""
import sys
import os
import yaml
import csv
import time
import random
from datetime import datetime
from pathlib import Path
import argparse

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.request import Request
from core.system_state import SystemState
from control.advanced_policy import AdvancedPolicy
from simulation.vllm_simulator import VLLMSimulator
from simulation.event_logger import EventLogger


def load_config(config_path: str = "config/advanced_test.yaml") -> dict:
    """
    加载配置文件
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        配置字典
    """
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    return config


def load_requests(csv_path: str, L_filter: int = None) -> list:
    """
    从CSV文件加载请求
    
    Args:
        csv_path: CSV文件路径
        L_filter: 最大decode长度过滤
        
    Returns:
        请求列表
    """
    requests = []
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        req_id = 0
        
        for row in reader:
            arrival_time = float(row['arrival_time'])
            prefill_length = int(row['prefill_length'])
            decode_length = int(row['decode_length'])
            
            # 应用过滤
            if L_filter and decode_length > L_filter:
                continue
            
            req = Request(
                req_id=req_id,
                arrival_time=arrival_time,
                prefill_length=prefill_length,
                decode_length=decode_length
            )
            requests.append(req)
            req_id += 1
    
    print(f"加载了 {len(requests)} 个请求")
    return requests


def generate_experiment_dir(base_dir: str = "data/experiments") -> str:
    """
    生成带时间戳的实验目录名
    
    Args:
        base_dir: 基础目录
        
    Returns:
        实验目录路径
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    random_suffix = random.randint(1000, 9999)
    exp_name = f"experiment_{timestamp}_{random_suffix}"
    exp_dir = os.path.join(base_dir, exp_name)
    
    # 确保目录不存在
    while os.path.exists(exp_dir):
        random_suffix = random.randint(1000, 9999)
        exp_name = f"experiment_{timestamp}_{random_suffix}"
        exp_dir = os.path.join(base_dir, exp_name)
    
    return exp_dir


def run_experiment(config_path: str = "config/advanced_test.yaml", 
                  request_file: str = None,
                  output_dir: str = None):
    """
    运行高级策略仿真实验
    
    Args:
        config_path: 配置文件路径
        request_file: 请求文件路径（覆盖配置文件中的路径）
        output_dir: 输出目录（如果为None则自动生成）
    """
    print("=== 高级策略仿真实验 ===\n")
    
    # 加载配置
    print("加载配置...")
    config = load_config(config_path)
    
    # 设置输出目录
    if output_dir is None:
        output_dir = generate_experiment_dir()
    
    # 创建输出目录
    os.makedirs(output_dir, exist_ok=True)
    
    # 保存使用的配置到实验目录
    config_snapshot_path = os.path.join(output_dir, "config_used.yaml")
    with open(config_snapshot_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    
    print(f"\n实验输出目录: {output_dir}")
    
    # 确定请求文件路径
    if request_file:
        csv_path = request_file
    else:
        csv_path = config['data']['request_file']
    
    # 加载请求
    print(f"从 {csv_path} 加载请求...")
    requests = load_requests(csv_path, config['data'].get('L_filter'))
    
    if not requests:
        print("错误：没有加载到请求")
        return
    
    # 显示配置信息
    print("\n系统配置:")
    print(f"  GPU总内存: {config['system']['M_total']} tokens")
    print(f"  批次预算: {config['system']['B']} tokens")
    print(f"  执行时间: {config['system']['d_0']} + {config['system']['d_1']} * B(t)")
    
    print("\n控制策略:")
    print(f"  抢占模式: {config['control']['preemption_mode']}")
    print(f"  抢占策略: {config['control']['preemption_strategy']}")
    print(f"  允许WAITING抢占: {config['control'].get('allow_waiting_preempt', False)}")
    print(f"  队列策略: {config['control']['queue_policy']}")
    print(f"  Victim选择: {config['control']['victim_policy']}")
    
    # 创建控制策略
    print("\n初始化系统...")
    policy = AdvancedPolicy(config['control'])
    
    # 创建仿真器
    simulator = VLLMSimulator(config, policy)
    
    # 运行仿真
    print("\n开始仿真...")
    print(f"策略组合: {policy}")
    start_time = time.time()
    
    results = simulator.run(requests)
    
    end_time = time.time()
    elapsed = end_time - start_time
    
    # 显示结果摘要
    print("\n=== 仿真完成 ===")
    print(f"实际运行时间: {elapsed:.2f} 秒")
    print(f"仿真时间: {results['total_time']:.2f} 时间单位")
    print(f"总批次数: {results['total_batches']}")
    print(f"完成请求数: {results['completed_requests']}")
    
    if 'metrics' in results:
        print("\n性能指标:")
        metrics = results['metrics']
        print(f"  平均延迟: {metrics['avg_delay']:.2f}")
        print(f"  最大延迟: {metrics['max_delay']:.2f}")
        print(f"  平均等待时间: {metrics['avg_waiting_time']:.2f}")
        print(f"  平均交换次数: {metrics['avg_swap_count']:.2f}")
        print(f"  请求吞吐量: {metrics['throughput_requests']:.2f} 请求/时间单位")
        print(f"  Token吞吐量: {metrics['throughput_tokens']:.2f} tokens/时间单位")
    
    if 'statistics' in results:
        print("\n系统统计:")
        stats = results['statistics']
        print(f"  总接纳次数: {stats['total_admitted']}")
        print(f"  总交换出次数: {stats['total_swapped_out']}")
        print(f"  总交换入次数: {stats['total_swapped_in']}")
        print(f"  内存利用率: {stats['memory_utilization']:.2%}")
    
    # 计算额外的策略相关指标
    if results['requests']:
        total_sacrifices = sum(req.sacrifice_count for req in results['requests'])
        if total_sacrifices > 0:
            print(f"\nSacrifice统计:")
            print(f"  总sacrifice次数: {total_sacrifices}")
            print(f"  平均每请求sacrifice: {total_sacrifices/len(results['requests']):.2f}")
    
    # 保存结果
    print("\n保存结果...")
    logger = EventLogger(output_dir)
    logger.save_all(results)
    
    # 保存实验元信息
    meta_info = {
        'experiment_time': datetime.now().isoformat(),
        'config_path': config_path,
        'request_file': csv_path,
        'total_requests': len(requests),
        'completed_requests': results['completed_requests'],
        'total_time': results['total_time'],
        'output_dir': output_dir,
        'preemption_mode': config['control']['preemption_mode'],
        'preemption_strategy': config['control']['preemption_strategy']
    }
    
    meta_path = os.path.join(output_dir, 'experiment_meta.yaml')
    with open(meta_path, 'w') as f:
        yaml.dump(meta_info, f, default_flow_style=False, allow_unicode=True)
    
    print(f"\n实验完成！")
    print(f"结果保存在: {output_dir}")
    return results


def main():
    """
    主函数
    """
    parser = argparse.ArgumentParser(description="运行高级策略仿真")
    parser.add_argument("--config", type=str, default="config/advanced_test.yaml",
                       help="配置文件路径")
    parser.add_argument("--requests", type=str, default=None,
                       help="请求文件路径（覆盖配置文件）")
    parser.add_argument("--output-dir", type=str, default=None,
                       help="输出目录（默认自动生成）")
    
    # 快速设置策略的参数
    parser.add_argument("--mode", type=str, choices=['swap', 'sacrifice'],
                       help="抢占模式（覆盖配置文件）")
    parser.add_argument("--strategy", type=str, choices=['aggressive', 'conservative'],
                       help="抢占策略（覆盖配置文件）")
    
    args = parser.parse_args()
    
    # 如果通过命令行指定了策略，修改配置
    if args.mode or args.strategy:
        config = load_config(args.config)
        if args.mode:
            config['control']['preemption_mode'] = args.mode
        if args.strategy:
            config['control']['preemption_strategy'] = args.strategy
        
        # 保存修改后的配置到临时文件
        temp_config = "config/temp_config.yaml"
        with open(temp_config, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
        args.config = temp_config
    
    # 运行实验
    run_experiment(args.config, args.requests, args.output_dir)


if __name__ == "__main__":
    main()