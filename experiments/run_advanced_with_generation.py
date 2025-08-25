"""
运行高级策略仿真实验（带数据生成功能）
支持Swap/Sacrifice模式和Aggressive/Conservative策略
可通过配置文件一站式完成数据生成和实验运行
"""
import sys
import os
import yaml
import csv
import time
import random
import subprocess
from datetime import datetime
from pathlib import Path
import argparse

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.request import Request
from core.system_state import SystemState
from core.constants import RequestStatus
from core.state_manager import (
    save_state_to_csv, 
    load_initial_state_from_csv, 
    parse_single_type
)
from control.advanced_policy import AdvancedPolicy
from simulation.vllm_simulator import VLLMSimulator
from simulation.vllm_simulator_with_state import VLLMSimulatorWithState
from simulation.event_logger import EventLogger
from visualization.draw import plot_queue_dynamics


def load_config(config_path: str = "config/config_with_generation.yaml") -> dict:
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


def run_experiment(config_path: str = "config/config_with_generation.yaml", 
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
    
    # 初始化变量
    initial_time = 0.0  # 系统初始时间
    initial_requests = []  # 从状态文件加载的请求
    generated_requests = []  # 新生成的请求
    all_requests = []  # 所有请求
    
    # 1. 处理初始状态加载（如果启用）
    if config.get('initial_state', {}).get('enabled', False):
        print("\n=== 加载初始状态 ===")
        state_file = config['initial_state']['state_file']
        
        if not state_file:
            print("错误：未指定状态文件路径")
            return
        
        # 获取request type（如果需要统一类型）
        request_type = None
        if 'generation' in config and config['generation'].get('types'):
            types_str = config['generation']['types']
            request_type = parse_single_type(types_str)
            if request_type:
                print(f"使用统一类型: prefill={request_type['prefill_length']}, decode={request_type['decode_length']}")
        
        # 加载状态
        try:
            initial_requests, initial_time = load_initial_state_from_csv(state_file, request_type)
            print(f"成功加载 {len(initial_requests)} 个请求")
            print(f"系统初始时间: {initial_time:.2f}")
            
            # 统计各状态的请求数
            waiting_count = sum(1 for r in initial_requests if r.status == RequestStatus.WAITING)
            running_count = sum(1 for r in initial_requests if r.status == RequestStatus.RUNNING)
            swapped_count = sum(1 for r in initial_requests if r.status == RequestStatus.SWAPPED)
            
            print(f"状态分布: WAITING={waiting_count}, RUNNING={running_count}, SWAPPED={swapped_count}")
            
        except Exception as e:
            print(f"加载初始状态失败: {e}")
            return
    
    # 2. 检查是否需要生成新数据
    if 'generation' in config and config['generation'].get('enabled', False):
        print("\n=== 数据生成阶段 ===")
        gen_config = config['generation']
        
        # 构建生成命令
        cmd = [
            'python', 'data/input/generate_requests_using_type.py',
            '--types', gen_config['types'],
            '--num_requests', str(gen_config['num_requests']),
            '--output', gen_config['output'],
            '--seed', str(gen_config.get('seed', 42))
        ]
        
        print(f"生成命令: {' '.join(cmd)}")
        print(f"生成参数:")
        print(f"  类型定义: {gen_config['types']}")
        print(f"  请求数量: {gen_config['num_requests']}")
        print(f"  输出文件: {gen_config['output']}")
        print(f"  随机种子: {gen_config.get('seed', 42)}")
        
        # 执行数据生成
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            print("\n数据生成成功!")
            if result.stdout:
                print("生成输出:", result.stdout)
            
            # 如果是继续生成模式，加载生成的请求并调整时间
            if initial_time > 0 or initial_requests:
                # 加载刚生成的请求
                generated_requests = load_requests(gen_config['output'], config['data'].get('L_filter'))
                
                # 调整时间偏移
                if initial_time > 0:
                    print(f"\n调整新生成请求的到达时间，偏移量: {initial_time:.2f}")
                    for req in generated_requests:
                        req.arrival_time += initial_time
                    
                    if generated_requests:
                        print(f"新请求时间范围: {generated_requests[0].arrival_time:.2f} - {generated_requests[-1].arrival_time:.2f}")
            else:
                # 正常模式，更新配置中的请求文件路径
                config['data']['request_file'] = gen_config['output']
                print(f"已更新请求文件路径为: {gen_config['output']}")
            
        except subprocess.CalledProcessError as e:
            print(f"\n数据生成失败!")
            print(f"错误信息: {e.stderr}")
            return
        except Exception as e:
            print(f"\n数据生成时发生错误: {e}")
            return
    
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
    
    # 3. 合并所有请求
    if initial_requests and generated_requests:
        # 合并初始状态和新生成的请求
        all_requests = initial_requests + generated_requests
        all_requests.sort(key=lambda r: r.arrival_time)
        print(f"\n合并请求: 初始={len(initial_requests)}, 新生成={len(generated_requests)}, 总计={len(all_requests)}")
    elif initial_requests:
        # 只有初始状态
        all_requests = initial_requests
        print(f"\n使用初始状态请求: {len(all_requests)}")
    elif generated_requests:
        # 只有新生成的请求
        all_requests = generated_requests
        print(f"\n使用新生成请求: {len(all_requests)}")
    else:
        # 从文件加载（原有逻辑）
        if request_file:
            csv_path = request_file
        else:
            csv_path = config['data']['request_file']
        
        print(f"从 {csv_path} 加载请求...")
        all_requests = load_requests(csv_path, config['data'].get('L_filter'))
    
    if not all_requests:
        print("错误：没有加载到请求")
        return
    
    print(f"总请求数: {len(all_requests)}")
    
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
    
    # 判断是否使用带状态的仿真器
    use_state_simulator = (
        config.get('initial_state', {}).get('enabled', False) or
        config.get('state_save', {}).get('enabled', False)
    )
    
    if use_state_simulator:
        print("使用支持状态管理的仿真器")
        
        # 准备初始请求（如果有的话）
        initial_requests_for_sim = None
        if initial_requests:
            # 筛选出需要在初始状态中的请求
            initial_requests_for_sim = [
                req for req in all_requests 
                if req.status in [RequestStatus.WAITING, RequestStatus.RUNNING, RequestStatus.SWAPPED]
            ]
        
        # 创建带状态管理的仿真器
        simulator = VLLMSimulatorWithState(
            config=config,
            control_policy=policy,
            initial_time=initial_time,
            initial_requests=initial_requests_for_sim,
            state_save_config=config.get('state_save', {}),
            output_dir=output_dir
        )
    else:
        # 使用普通仿真器
        simulator = VLLMSimulator(config, policy)
    
    # 运行仿真
    print("\n开始仿真...")
    print(f"策略组合: {policy}")
    start_time = time.time()
    
    results = simulator.run(all_requests)
    
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
        else:
            print("\n没有发生sacrifice操作")
    
    # 保存结果
    print("\n保存结果...")
    logger = EventLogger(output_dir)
    logger.save_all(results)
    
    # 保存实验元信息
    meta_info = {
        'experiment_time': datetime.now().isoformat(),
        'config_path': config_path,
        'request_file': config['data']['request_file'],
        'total_requests': len(all_requests),
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
    
    # 生成可视化图表
    print("\n生成可视化图表...")
    
    # 获取请求到达结束时间（读取请求CSV文件的最后一行）
    arrival_end = None
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if rows:
                last_row = rows[-1]
                arrival_end = float(last_row['arrival_time'])
                print(f"请求到达结束时间: {arrival_end:.2f}")
    except Exception as e:
        print(f"无法获取请求到达结束时间: {e}")
    
    # 调用可视化函数，传递所有系统参数
    batch_snapshots_path = os.path.join(output_dir, 'batch_snapshots.csv')
    if os.path.exists(batch_snapshots_path):
        try:
            # 从配置中获取系统参数
            M_total = config['system']['M_total']
            B_total = config['system']['B']
            d_0 = config['system']['d_0']
            d_1 = config['system']['d_1']
            num_reqs = len(all_requests)
            
            print(f"系统参数: M_total={M_total}, B={B_total}, d_0={d_0}, d_1={d_1}")
            arrival_end_str = f"{arrival_end:.2f}" if arrival_end else "N/A"
            print(f"请求统计: 总数={len(all_requests)}, 到达结束时间={arrival_end_str}")
            
            # 获取状态保存的批次ID（如果有）
            state_save_batches = None
            if 'state_save' in config and config['state_save'].get('enabled', False):
                state_save_batches = config['state_save'].get('batch_ids', [])
                if state_save_batches:
                    print(f"状态保存批次: {state_save_batches}")
            
            # 调用可视化函数
            plot_queue_dynamics(
                csv_path=batch_snapshots_path, 
                arrival_end=arrival_end, 
                M_total=M_total, 
                B_total=B_total,
                d_0=d_0,
                d_1=d_1,
                num_requests=num_reqs,
                state_save_batches=state_save_batches
            )
            print("可视化图表已生成")
        except Exception as e:
            print(f"生成可视化图表失败: {e}")
    else:
        print("找不到batch_snapshots.csv文件，跳过可视化")
    
    return results


def main():
    """
    主函数
    """
    parser = argparse.ArgumentParser(description="运行高级策略仿真（支持自动数据生成）")
    parser.add_argument("--config", type=str, default="config/config_with_generation.yaml",
                       help="配置文件路径（默认包含数据生成配置）")
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