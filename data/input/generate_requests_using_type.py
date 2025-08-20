"""
基于多请求类型生成测试请求数据
支持不同类型的独立泊松到达过程
"""
import csv
import random
import numpy as np
from pathlib import Path
import argparse
import ast
from typing import List, Tuple


def parse_types_string(types_str: str) -> List[Tuple[int, int, float]]:
    """
    解析类型字符串，如 "{(20,20,4),(10,10,2)}"
    
    Args:
        types_str: 格式化的类型字符串
        
    Returns:
        List of (prefill_length, decode_length, rate) tuples
    """
    try:
        # 移除外层大括号并解析
        types_str = types_str.strip('{}')
        # 使用ast.literal_eval安全解析元组列表
        types_list = ast.literal_eval(f"[{types_str}]")
        
        # 验证每个元组都有3个元素
        for i, t in enumerate(types_list):
            if len(t) != 3:
                raise ValueError(f"类型 {i+1} 必须包含3个元素: (prefill_length, decode_length, rate)")
            if not all(isinstance(x, (int, float)) for x in t):
                raise ValueError(f"类型 {i+1} 的所有元素必须是数字")
            if t[2] <= 0:
                raise ValueError(f"类型 {i+1} 的到达率必须大于0")
                
        return types_list
    except Exception as e:
        raise ValueError(f"无法解析类型字符串: {e}")


def generate_requests_by_type(
    request_types: List[Tuple[int, int, float]],
    num_requests: int = 100,
    seed: int = 42,
    output_file: str = "requests_typed.csv"
):
    """
    基于多种请求类型生成请求数据，每种类型有独立的泊松到达过程
    
    Args:
        request_types: [(prefill_length, decode_length, rate), ...] 请求类型列表
        num_requests: 总请求数量
        seed: 随机种子
        output_file: 输出文件名
    """
    random.seed(seed)
    np.random.seed(seed)
    
    # 确保输出目录存在
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 计算每种类型的权重（基于到达率）
    total_rate = sum(rate for _, _, rate in request_types)
    type_weights = [rate / total_rate for _, _, rate in request_types]
    
    # 根据权重分配每种类型的请求数量
    type_counts = []
    remaining_requests = num_requests
    
    for i, weight in enumerate(type_weights[:-1]):
        count = int(num_requests * weight)
        type_counts.append(count)
        remaining_requests -= count
    
    # 最后一种类型获得剩余的请求数
    type_counts.append(remaining_requests)
    
    print(f"请求类型分布:")
    for i, ((prefill, decode, rate), count) in enumerate(zip(request_types, type_counts)):
        print(f"  类型{i+1}: prefill={prefill}, decode={decode}, rate={rate:.2f} -> {count} 请求")
    
    all_requests = []
    
    # 为每种类型生成独立的泊松到达序列
    for type_idx, ((prefill_length, decode_length, rate), count) in enumerate(zip(request_types, type_counts)):
        if count <= 0:
            continue
            
        # 为这种类型生成到达时间序列
        current_time = 0.0
        type_requests = []
        
        for _ in range(count):
            # 泊松过程的到达间隔（指数分布）
            inter_arrival_time = np.random.exponential(1.0 / rate)
            current_time += inter_arrival_time
            
            type_requests.append({
                'arrival_time': current_time,
                'prefill_length': prefill_length,
                'decode_length': decode_length,
                'type_id': type_idx
            })
        
        all_requests.extend(type_requests)
    
    # 按到达时间排序所有请求
    all_requests.sort(key=lambda x: x['arrival_time'])
    
    # 重新编号并四舍五入时间
    for i, request in enumerate(all_requests):
        request['arrival_time'] = round(request['arrival_time'], 4)
        request['request_id'] = i
    
    # 写入CSV文件
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['arrival_time', 'prefill_length', 'decode_length'])
        writer.writeheader()
        
        # 只写入仿真需要的字段
        for request in all_requests:
            writer.writerow({
                'arrival_time': request['arrival_time'],
                'prefill_length': request['prefill_length'],
                'decode_length': request['decode_length']
            })
    
    # 统计和输出信息
    max_time = all_requests[-1]['arrival_time'] if all_requests else 0
    actual_total_rate = len(all_requests) / max_time if max_time > 0 else 0
    
    print(f"\n生成完成:")
    print(f"总请求数: {len(all_requests)}")
    print(f"时间范围: 0.0 - {max_time:.2f}")
    print(f"实际平均到达率: {actual_total_rate:.3f} 请求/时间单位")
    print(f"理论平均到达率: {total_rate:.3f} 请求/时间单位")
    print(f"文件已保存到: {output_path}")
    
    # 按类型统计
    type_stats = {}
    for request in all_requests:
        type_id = request['type_id']
        if type_id not in type_stats:
            type_stats[type_id] = []
        type_stats[type_id].append(request)
    
    print(f"\n各类型统计:")
    for type_id in sorted(type_stats.keys()):
        requests_of_type = type_stats[type_id]
        prefill, decode, rate = request_types[type_id]
        
        if len(requests_of_type) > 1:
            times = [r['arrival_time'] for r in requests_of_type]
            actual_rate = len(requests_of_type) / (max(times) - min(times)) if len(times) > 1 else 0
        else:
            actual_rate = 0
            
        print(f"  类型{type_id+1}: {len(requests_of_type)} 请求, "
              f"实际到达率: {actual_rate:.3f} (理论: {rate:.3f})")
    
    return all_requests


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="基于多类型生成仿真请求数据")
    parser.add_argument("--types", type=str, required=True,
                       help="请求类型定义，格式: '{(prefill1,decode1,rate1),(prefill2,decode2,rate2),...}'")
    parser.add_argument("--num_requests", type=int, default=100,
                       help="总请求数量")
    parser.add_argument("--output", type=str, default="requests_typed.csv",
                       help="输出文件名")
    parser.add_argument("--seed", type=int, default=42,
                       help="随机种子")
    
    args = parser.parse_args()
    
    try:
        # 解析请求类型
        request_types = parse_types_string(args.types)
        
        # 生成请求
        generate_requests_by_type(
            request_types=request_types,
            num_requests=args.num_requests,
            seed=args.seed,
            output_file=args.output
        )
        
    except ValueError as e:
        print(f"错误: {e}")
        print("\n使用示例:")
        print("python generate_requests_using_type.py --types '{(20,20,4),(10,10,2)}' --num_requests 100 --output test.csv")
        exit(1)