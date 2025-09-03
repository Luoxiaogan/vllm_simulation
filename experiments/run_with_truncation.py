#!/usr/bin/env python3
"""
运行支持截断点切换的仿真实验
支持两种模式：
1. explore模式：完整运行，在图上标记候选截断点
2. truncate模式：运行到截断点，切换参数继续
"""

import argparse
import csv
import os
import yaml
import subprocess
from typing import Dict, List, Any, Optional
from datetime import datetime
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.request import Request
from core.system_state import SystemState
from core.constants import RequestStatus
from control.advanced_policy import AdvancedPolicy
from simulation.vllm_simulator import VLLMSimulator
from simulation.vllm_simulator_with_truncation import VLLMSimulatorWithTruncation
from simulation.event_logger import EventLogger
from visualization.draw import plot_queue_dynamics, plot_sacrifice_dynamics
from data.input.generate_requests_using_type import parse_types_string


def load_config(config_path: str) -> Dict:
    """加载配置文件"""
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    return config


def generate_requests_if_needed(config: Dict) -> str:
    """
    如果配置中启用了生成，则生成请求数据
    
    Returns:
        生成的请求文件路径
    """
    if 'generation' not in config or not config['generation'].get('enabled', False):
        return config['data']['request_file']
    
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
        
        # 更新配置中的请求文件路径
        config['data']['request_file'] = gen_config['output']
        print(f"\n已更新请求文件路径为: {gen_config['output']}")
        
        return gen_config['output']
        
    except subprocess.CalledProcessError as e:
        print(f"数据生成失败: {e}")
        if e.stderr:
            print(f"错误输出: {e.stderr}")
        raise


def load_requests(csv_path: str, L_filter: int = None) -> List[Request]:
    """
    从CSV文件加载请求
    """
    requests = []
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            # 如果设置了L_filter，跳过decode_length > L_filter的请求
            decode_length = int(row['decode_length'])
            if L_filter and decode_length > L_filter:
                continue
                
            req = Request(
                req_id=i,
                arrival_time=float(row['arrival_time']),
                prefill_length=int(row['prefill_length']),
                decode_length=decode_length
            )
            requests.append(req)
    
    # 重新编号
    for i, req in enumerate(requests):
        req.req_id = i
    
    return requests


def run_simulation(config: Dict, mode: str = 'explore') -> Dict[str, Any]:
    """
    运行仿真
    
    Args:
        config: 配置字典
        mode: 运行模式 ('explore' 或 'truncate')
        
    Returns:
        仿真结果
    """
    print(f"\n=== 截断仿真实验 ({mode}模式) ===\n")
    
    # 生成或加载请求数据
    if mode == 'explore':
        # 探索模式：生成初始请求
        print("=== 数据生成阶段 ===")
        csv_path = generate_requests_if_needed(config)
    else:
        # 截断模式：使用初始请求文件
        csv_path = config['data']['request_file']
    
    # 创建输出目录
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    import random
    exp_id = random.randint(1000, 9999)
    output_dir = f"data/experiments/{mode}_{timestamp}_{exp_id}"
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"实验输出目录: {output_dir}")
    
    # 加载请求
    print(f"从 {csv_path} 加载请求...")
    L_filter = config['data'].get('L_filter', None)
    all_requests = load_requests(csv_path, L_filter)
    print(f"加载了 {len(all_requests)} 个请求")
    
    # 初始化系统状态
    state = SystemState(
        M_total=config['system']['M_total'],
        B=config['system']['B']
    )
    # 设置时间参数
    state.d_0 = config['system']['d_0']
    state.d_1 = config['system']['d_1']
    
    # 创建控制策略
    control_policy = AdvancedPolicy(config['control'])
    
    # 打印配置信息
    print(f"\n系统配置:")
    print(f"  GPU总内存: {state.M_total} tokens")
    print(f"  批次预算: {state.B} tokens")
    print(f"  执行时间: {state.d_0} + {state.d_1} * B(t)")
    
    print(f"\n控制策略:")
    print(f"  抢占模式: {config['control']['preemption_mode']}")
    print(f"  抢占策略: {config['control']['preemption_strategy']}")
    print(f"  允许WAITING抢占: {config['control'].get('allow_waiting_preempt', False)}")
    print(f"  队列策略: {config['control']['queue_policy']}")
    print(f"  Victim选择: {config['control']['victim_policy']}")
    
    # 根据模式选择仿真器
    print(f"\n初始化系统...")
    
    # 检查是否启用准入控制
    admission_config = config.get('admission_control', {})
    admission_enabled = admission_config.get('enabled', False)
    
    if admission_enabled:
        # 使用支持准入控制的仿真器
        from simulation.vllm_simulator_with_truncation_admission_control import \
            VLLMSimulatorWithTruncationAdmissionControl
        
        print(f"准入控制已启用，阈值: {admission_config.get('threshold', 1.0)}")
        
        if mode == 'explore':
            # 探索模式 + 准入控制
            print("使用探索模式仿真器（带准入控制）")
            simulator = VLLMSimulatorWithTruncationAdmissionControl(
                config=config,
                control_policy=control_policy,
                truncation_batch_id=None,  # 探索模式不需要截断
                truncation_config=None
            )
        else:
            # 截断模式 + 准入控制
            print("使用截断模式仿真器（带准入控制）")
            truncation_config = config.get('truncation', {})
            truncation_batch_id = truncation_config.get('batch_id')
            
            if not truncation_batch_id:
                raise ValueError("截断模式需要指定 truncation.batch_id")
            
            # 准备截断后的生成配置
            truncation_generation = truncation_config.get('new_generation', {})
            
            simulator = VLLMSimulatorWithTruncationAdmissionControl(
                config=config,
                control_policy=control_policy,
                truncation_batch_id=truncation_batch_id,
                truncation_config={'generation': truncation_generation}
            )
    else:
        # 不使用准入控制
        if mode == 'explore':
            # 探索模式：使用普通仿真器
            print("使用探索模式仿真器")
            simulator = VLLMSimulator(config, control_policy)
        else:
            # 截断模式：使用截断仿真器
            print("使用截断模式仿真器")
            truncation_config = config.get('truncation', {})
            truncation_batch_id = truncation_config.get('batch_id')
            
            if not truncation_batch_id:
                raise ValueError("截断模式需要指定 truncation.batch_id")
            
            # 准备截断后的生成配置
            truncation_generation = truncation_config.get('new_generation', {})
            
            simulator = VLLMSimulatorWithTruncation(
                config=config,
                control_policy=control_policy,
                truncation_batch_id=truncation_batch_id,
                truncation_config={'generation': truncation_generation}
            )
    
    # 运行仿真
    import time
    start_time = time.time()
    results = simulator.run(requests=all_requests)
    elapsed_time = time.time() - start_time
    
    # 打印结果摘要
    print(f"\n=== 仿真完成 ===")
    print(f"实际运行时间: {elapsed_time:.2f} 秒")
    print(f"仿真时间: {results['total_time']:.2f} 时间单位")
    print(f"总批次数: {results['total_batches']}")
    print(f"完成请求数: {results['completed_requests']}")
    
    if 'metrics' in results:
        metrics = results['metrics']
        print(f"\n性能指标:")
        print(f"  平均延迟: {metrics.get('avg_delay', 0):.2f}")
        print(f"  最大延迟: {metrics.get('max_delay', 0):.2f}")
        print(f"  平均等待时间: {metrics.get('avg_waiting_time', 0):.2f}")
        print(f"  平均交换次数: {metrics.get('avg_swap_count', 0):.2f}")
        print(f"  请求吞吐量: {metrics.get('throughput_requests', 0):.2f} 请求/时间单位")
        print(f"  Token吞吐量: {metrics.get('throughput_tokens', 0):.2f} tokens/时间单位")
    
    # 保存配置文件副本（在保存其他结果之前）
    config_copy_path = os.path.join(output_dir, 'config_used.yaml')
    with open(config_copy_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    
    # 保存元信息
    meta_info = {
        'mode': mode,
        'timestamp': timestamp,
        'request_file': csv_path,
        'total_requests': len(all_requests),
        'completed_requests': results['completed_requests'],
        'total_time': results['total_time'],
        'wall_time': elapsed_time,
        'output_dir': output_dir,
        'preemption_mode': config['control']['preemption_mode'],
        'preemption_strategy': config['control']['preemption_strategy']
    }
    
    if mode == 'truncate' and 'truncation' in config:
        meta_info['truncation_batch_id'] = config['truncation']['batch_id']
    
    meta_path = os.path.join(output_dir, 'experiment_meta.yaml')
    with open(meta_path, 'w') as f:
        yaml.dump(meta_info, f, default_flow_style=False, allow_unicode=True)
    
    # 使用EventLogger保存所有结果（与run_advanced.py一致）
    print("\n保存结果...")
    logger = EventLogger(output_dir)
    logger.save_all(results)
    
    print(f"\n实验完成！")
    print(f"结果保存在: {output_dir}")
    
    # 生成可视化图表
    print("\n生成可视化图表...")
    
    # 准备可视化参数
    arrival_end = None
    theoretical_lambda = None
    truncation_info_for_plot = None
    
    if mode == 'explore':
        # 探索模式：获取理论lambda值
        if 'generation' in config and config['generation'].get('enabled'):
            # 从生成配置中获取理论lambda
            types_str = config['generation'].get('types', '')
            try:
                request_types = parse_types_string(types_str)
                # 计算总的理论lambda（所有类型的和）
                theoretical_lambda = sum(rate for _, _, rate in request_types)
                print(f"理论到达率: {theoretical_lambda:.2f} 请求/时间单位")
            except Exception as e:
                print(f"无法解析理论lambda: {e}")
        
        # 获取请求到达结束时间
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
            
    else:
        # 截断模式：准备两个阶段的信息
        if 'truncation_info' in results:
            truncation_time = results['truncation_info'].get('truncation_time', 0)
            new_requests_duration = results['truncation_info'].get('new_requests_duration', 0)
            new_requests_end_time = results['truncation_info'].get('new_requests_end_time', 0)
            arrival_end = new_requests_end_time
            
            # 获取第一阶段的理论lambda（从初始请求文件或生成配置）
            phase1_lambda_theory = None
            phase1_lambda_actual = None
            phase1_requests = 0
            
            # 计算第一阶段的请求数（已到达的）
            phase1_requests = len([req for req in all_requests if req.arrival_time <= truncation_time])
            
            # 获取第一阶段的理论lambda
            # 尝试从初始请求文件的配置获取
            try:
                # 查找初始请求文件的生成参数
                # 例如，如果explore.csv是用(20,20,5.1)生成的
                # 这里我们假设初始文件使用的参数和探索模式一样
                initial_types_str = "{(20,20,5.1)}"  # 默认值，应该从配置中读取
                initial_types = parse_types_string(initial_types_str)
                phase1_lambda_theory = sum(rate for _, _, rate in initial_types)
            except:
                phase1_lambda_theory = 5.1  # 默认值
            
            # 计算第一阶段的实际lambda
            if truncation_time > 0:
                phase1_lambda_actual = phase1_requests / truncation_time
            
            # 获取第二阶段的信息
            phase2_lambda_theory = None
            phase2_lambda_actual = None
            phase2_requests = 0
            
            if 'truncation' in config and 'new_generation' in config['truncation']:
                new_gen = config['truncation']['new_generation']
                phase2_requests = new_gen.get('num_requests', 0)
                
                # 获取第二阶段的理论lambda
                if 'rate_list' in new_gen:
                    # 使用rate_list覆盖的值
                    phase2_lambda_theory = new_gen['rate_list'][0] if new_gen['rate_list'] else 0
                else:
                    # 使用原始的types中的值
                    try:
                        types_str = new_gen.get('types', '')
                        request_types = parse_types_string(types_str)
                        phase2_lambda_theory = sum(rate for _, _, rate in request_types)
                    except:
                        phase2_lambda_theory = 0
                
                # 计算第二阶段的实际lambda
                if new_requests_duration > 0:
                    phase2_lambda_actual = phase2_requests / new_requests_duration
            
            # 构建截断信息字典
            truncation_info_for_plot = {
                'truncation_batch_id': config['truncation'].get('batch_id'),
                'truncation_time': truncation_time,
                'phase1_requests': phase1_requests,
                'phase1_lambda_theory': phase1_lambda_theory,
                'phase1_lambda_actual': phase1_lambda_actual,
                'phase2_requests': phase2_requests,
                'phase2_lambda_theory': phase2_lambda_theory,
                'phase2_lambda_actual': phase2_lambda_actual,
                'new_requests_end_time': new_requests_end_time
            }
            
            print(f"\n截断信息:")
            print(f"  截断时间: {truncation_time:.2f}")
            print(f"  第一阶段: {phase1_requests} 请求, λ_theory={phase1_lambda_theory:.2f}, λ_actual={phase1_lambda_actual:.2f}")
            print(f"  第二阶段: {phase2_requests} 请求, λ_theory={phase2_lambda_theory:.2f}, λ_actual={phase2_lambda_actual:.2f}")
            print(f"  请求到达结束时间: {arrival_end:.2f}")
        else:
            # 如果没有截断信息，尝试从初始请求文件获取
            try:
                with open(csv_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                    if rows:
                        last_row = rows[-1]
                        arrival_end = float(last_row['arrival_time'])
                        print(f"请求到达结束时间（从文件）: {arrival_end:.2f}")
            except Exception as e:
                print(f"无法获取请求到达结束时间: {e}")
    
    # 调用可视化函数
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
            
            # 获取标记点
            mark_batches = None
            if mode == 'explore':
                # 探索模式：标记候选截断点
                mark_batches = config.get('explore', {}).get('candidate_batches', [])
                if mark_batches:
                    print(f"候选截断点: {mark_batches}")
            elif mode == 'truncate':
                # 截断模式：标记实际截断点
                truncation_batch_id = config.get('truncation', {}).get('batch_id')
                if truncation_batch_id:
                    mark_batches = [truncation_batch_id]
                    print(f"截断点: {mark_batches}")
            
            # 获取regression_interval配置
            regression_interval = config.get('regression_interval', None)
            if regression_interval:
                print(f"线性回归区间: {regression_interval}")
            
            # 调用可视化函数，传递mode和额外参数
            plot_queue_dynamics(
                csv_path=batch_snapshots_path, 
                arrival_end=arrival_end, 
                M_total=M_total, 
                B_total=B_total,
                d_0=d_0,
                d_1=d_1,
                num_requests=num_reqs,
                state_save_batches=mark_batches,  # 复用state_save参数来标记截断点
                mode=mode,  # 传递模式
                theoretical_lambda=theoretical_lambda,  # 传递理论lambda（探索模式）
                truncation_info=truncation_info_for_plot,  # 传递截断信息（截断模式）
                request_file=csv_path,  # 传递原始请求文件路径
                regression_interval=regression_interval,  # 传递回归区间
                admission_control=config.get('admission_control')  # 传递准入控制配置
            )
            
            # 如果是sacrifice模式，生成sacrifice相关图表
            if config['control']['preemption_mode'] == 'sacrifice':
                # 调用新的sacrifice可视化函数
                try:
                    plot_sacrifice_dynamics(exp_dir=output_dir, request_file=csv_path)
                    print("Sacrifice动态图表已生成")
                except Exception as e:
                    print(f"生成Sacrifice图表失败: {e}")
            
            print("可视化图表已生成")
        except Exception as e:
            print(f"生成可视化图表失败: {e}")
    else:
        print("找不到batch_snapshots.csv文件，跳过可视化")
    
    return results


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="运行截断仿真实验")
    parser.add_argument("--config", type=str, required=True,
                       help="配置文件路径")
    parser.add_argument("--mode", type=str, choices=['explore', 'truncate'], default='explore',
                       help="运行模式: explore（探索）或 truncate（截断）")
    
    args = parser.parse_args()
    
    # 加载配置
    config = load_config(args.config)
    
    # 运行仿真
    run_simulation(config, mode=args.mode)


if __name__ == "__main__":
    main()