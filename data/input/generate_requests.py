"""
生成测试请求数据
"""
import csv
import random
import numpy as np
from pathlib import Path
import argparse


def generate_requests(
    num_requests: int = 100,
    arrival_rate: float = 0.5,
    prefill_length_range: tuple = (200, 200),
    decode_length_range: tuple = (100, 100),
    seed: int = 42,
    output_file: str = "requests.csv"
):
    """
    生成请求数据
    
    Args:
        num_requests: 请求数量
        arrival_rate: 平均到达率（请求/时间单位）
        prefill_length_range: prefill长度范围
        decode_length_range: decode长度范围
        seed: 随机种子
        output_file: 输出文件名
    """
    random.seed(seed)
    np.random.seed(seed)
    
    # 确保输出目录存在
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    requests = []
    current_time = 0.0
    
    for i in range(num_requests):
        # 生成到达时间（指数分布）
        inter_arrival_time = np.random.exponential(1.0 / arrival_rate)
        current_time += inter_arrival_time
        
        # 生成prefill和decode长度
        # 使用不同的分布来创建更真实的负载
        
        # 80%的请求是"短"请求，20%是"长"请求
        if random.random() < 0.8:
            # 短请求
            prefill_length = random.randint(prefill_length_range[0], 
                                          prefill_length_range[0] + 50)
            decode_length = random.randint(decode_length_range[0],
                                         decode_length_range[0] + 30)
        else:
            # 长请求
            prefill_length = random.randint(prefill_length_range[1] - 50,
                                          prefill_length_range[1])
            decode_length = random.randint(decode_length_range[1] - 20,
                                         decode_length_range[1])
        
        requests.append({
            'arrival_time': round(current_time, 4),
            'prefill_length': prefill_length,
            'decode_length': decode_length
        })
    
    # 写入CSV文件
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['arrival_time', 'prefill_length', 'decode_length'])
        writer.writeheader()
        writer.writerows(requests)
    
    print(f"生成了 {num_requests} 个请求")
    print(f"到达时间范围: 0.0 - {current_time:.2f}")
    print(f"平均到达率: {num_requests / current_time:.2f} 请求/时间单位")
    print(f"文件已保存到: {output_path}")
    
    # 输出统计信息
    prefill_lengths = [r['prefill_length'] for r in requests]
    decode_lengths = [r['decode_length'] for r in requests]
    
    print("\n统计信息:")
    print(f"Prefill长度: 平均={np.mean(prefill_lengths):.1f}, "
          f"最小={min(prefill_lengths)}, 最大={max(prefill_lengths)}")
    print(f"Decode长度: 平均={np.mean(decode_lengths):.1f}, "
          f"最小={min(decode_lengths)}, 最大={max(decode_lengths)}")
    
    return requests


def generate_heavy_load(
    num_requests: int = 200,
    output_file: str = "requests_heavy.csv"
):
    """
    生成高负载场景的请求
    """
    return generate_requests(
        num_requests=num_requests,
        arrival_rate=2.0,  # 更高的到达率
        prefill_length_range=(50, 300),
        decode_length_range=(20, 150),
        output_file=output_file
    )


def generate_bursty_load(
    num_bursts: int = 5,
    burst_size: int = 20,
    output_file: str = "requests_bursty.csv"
):
    """
    生成突发负载场景的请求
    """
    random.seed(42)
    np.random.seed(42)
    
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    requests = []
    current_time = 0.0
    
    for burst_id in range(num_bursts):
        # 突发之间的间隔
        if burst_id > 0:
            current_time += np.random.uniform(5, 10)
        
        # 生成突发请求
        burst_start_time = current_time
        for i in range(burst_size):
            # 突发内的请求几乎同时到达
            current_time = burst_start_time + np.random.uniform(0, 0.5)
            
            prefill_length = random.randint(30, 150)
            decode_length = random.randint(20, 80)
            
            requests.append({
                'arrival_time': round(current_time, 4),
                'prefill_length': prefill_length,
                'decode_length': decode_length
            })
    
    # 按到达时间排序
    requests.sort(key=lambda x: x['arrival_time'])
    
    # 写入CSV文件
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['arrival_time', 'prefill_length', 'decode_length'])
        writer.writeheader()
        writer.writerows(requests)
    
    print(f"生成了 {len(requests)} 个突发请求（{num_bursts} 个突发）")
    print(f"文件已保存到: {output_path}")
    
    return requests


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成仿真请求数据")
    parser.add_argument("--num_requests", type=int, default=100,
                       help="请求数量")
    parser.add_argument("--arrival_rate", type=float, default=0.5,
                       help="平均到达率")
    parser.add_argument("--scenario", type=str, default="normal",
                       choices=["normal", "heavy", "bursty"],
                       help="负载场景")
    parser.add_argument("--output", type=str, default="requests.csv",
                       help="输出文件名")
    
    args = parser.parse_args()
    
    if args.scenario == "normal":
        generate_requests(
            num_requests=args.num_requests,
            arrival_rate=args.arrival_rate,
            output_file=args.output
        )
    elif args.scenario == "heavy":
        generate_heavy_load(
            num_requests=args.num_requests,
            output_file=args.output
        )
    elif args.scenario == "bursty":
        generate_bursty_load(
            output_file=args.output
        )