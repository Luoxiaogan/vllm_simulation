"""
系统状态保存和加载管理
用于保存仿真过程中的系统状态快照，以及从快照恢复初始状态
"""
import csv
import os
from typing import List, Tuple, Optional, Dict, Any
from datetime import datetime
from pathlib import Path
import ast

from .request import Request
from .constants import RequestStatus
from .system_state import SystemState


def save_state_to_csv(all_requests: List[Request], 
                      state: SystemState,
                      batch_id: int,
                      current_time: float,
                      output_dir: str) -> str:
    """
    保存系统状态到CSV文件
    
    Args:
        all_requests: 所有请求列表（包括已完成的）
        state: 当前系统状态
        batch_id: 当前批次ID
        current_time: 当前仿真时间
        output_dir: 输出目录
        
    Returns:
        保存的文件路径
    """
    # 创建状态目录
    state_dir = os.path.join(output_dir, 'states')
    os.makedirs(state_dir, exist_ok=True)
    
    # 生成文件名
    filename = f'state_batch_{batch_id}.csv'
    filepath = os.path.join(state_dir, filename)
    
    # 只保存已经到达且未完成的请求（arrival_time <= current_time 且 status != COMPLETED）
    arrived_requests = [req for req in all_requests 
                       if req.arrival_time <= current_time 
                       and req.status != RequestStatus.COMPLETED]
    
    # 准备写入数据
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        # 写入元数据（作为注释）
        f.write(f'# Batch ID: {batch_id}\n')
        f.write(f'# Current Time: {current_time:.4f}\n')
        f.write(f'# Save Time: {datetime.now().isoformat()}\n')
        f.write(f'# Total Arrived Requests: {len(arrived_requests)}\n')
        f.write(f'# Total All Requests: {len(all_requests)}\n')
        f.write(f'# WAITING: {len(state.waiting)}, RUNNING: {len(state.running)}, SWAPPED: {len(state.swapped)}\n')
        f.write('#\n')
        
        # 写入CSV头
        fieldnames = [
            'req_id', 'status', 'arrival_time', 'prefill_length', 'decode_length',
            'current_decode_position', 'first_enter_running_time', 'completion_time',
            'swap_count', 'sacrifice_count'
        ]
        
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        # 写入已到达的请求数据
        for req in arrived_requests:
            # 获取第一次进入running的时间
            first_enter_running = req.enter_running_times[0] if req.enter_running_times else None
            
            row = {
                'req_id': req.req_id,
                'status': req.status,
                'arrival_time': req.arrival_time,
                'prefill_length': req.prefill_length,
                'decode_length': req.decode_length,
                'current_decode_position': req.current_decode_position,
                'first_enter_running_time': first_enter_running if first_enter_running else '',
                'completion_time': req.completion_time if req.completion_time else '',
                'swap_count': len(req.swap_events),
                'sacrifice_count': len(req.sacrifice_events)
            }
            
            writer.writerow(row)
    
    print(f"状态已保存到: {filepath}")
    return filepath


def load_initial_state_from_csv(state_file: str, 
                                request_type: Optional[Dict[str, int]] = None) -> Tuple[List[Request], float]:
    """
    从CSV文件加载初始状态
    
    Args:
        state_file: 状态文件路径
        request_type: 可选的请求类型（包含prefill_length和decode_length），用于覆盖CSV中的值
        
    Returns:
        (requests, initial_time): 请求列表和系统初始时间
    """
    if not os.path.exists(state_file):
        raise FileNotFoundError(f"状态文件不存在: {state_file}")
    
    requests = []
    min_arrival_time = float('inf')
    max_arrival_time = float('-inf')
    
    with open(state_file, 'r', encoding='utf-8') as f:
        # 跳过注释行
        lines = f.readlines()
        data_lines = [line for line in lines if not line.startswith('#')]
        
        # 使用csv.DictReader读取数据
        reader = csv.DictReader(data_lines)
        
        for row in reader:
            # 解析数据
            req_id = int(row['req_id'])
            status = row['status']
            arrival_time = float(row['arrival_time'])
            
            # 如果提供了request_type，使用它覆盖prefill和decode长度
            if request_type:
                prefill_length = request_type['prefill_length']
                decode_length = request_type['decode_length']
            else:
                prefill_length = int(row['prefill_length'])
                decode_length = int(row['decode_length'])
            
            current_decode_position = int(row['current_decode_position'])
            
            # 跟踪最小和最大arrival_time
            min_arrival_time = min(min_arrival_time, arrival_time)
            max_arrival_time = max(max_arrival_time, arrival_time)
            
            # 创建请求对象
            req = Request(
                req_id=req_id,
                arrival_time=arrival_time,  # 稍后会归一化
                prefill_length=prefill_length,
                decode_length=decode_length
            )
            
            # 设置状态和解码位置
            req.status = status
            req.current_decode_position = current_decode_position
            
            # 恢复enter_running_times（如果有）
            if row.get('first_enter_running_time') and row['first_enter_running_time']:
                req.enter_running_times.append(float(row['first_enter_running_time']))
            
            # 恢复completion_time（如果有）
            if row.get('completion_time') and row['completion_time']:
                req.completion_time = float(row['completion_time'])
            
            # 跳过已完成的请求（不加入初始状态）
            if status != RequestStatus.COMPLETED:
                requests.append(req)
    
    # 时间归一化
    if requests:
        # 计算初始时间（系统应该从这个时间开始）
        initial_time = max_arrival_time - min_arrival_time
        
        # 归一化所有arrival_time
        for req in requests:
            req.arrival_time -= min_arrival_time
            
            # 同时调整其他时间戳
            if req.enter_running_times:
                req.enter_running_times = [t - min_arrival_time for t in req.enter_running_times]
            if req.completion_time:
                req.completion_time -= min_arrival_time
        
        print(f"加载了 {len(requests)} 个请求")
        print(f"时间归一化: min={min_arrival_time:.2f}, max={max_arrival_time:.2f}")
        print(f"系统初始时间: {initial_time:.2f}")
    else:
        initial_time = 0.0
        print("警告：没有加载到有效的请求")
    
    return requests, initial_time


def parse_single_type(types_str: str) -> Dict[str, int]:
    """
    解析类型字符串，提取第一个类型的参数
    
    Args:
        types_str: 类型字符串，格式如 "{(20,20,5.1)}"
        
    Returns:
        包含prefill_length和decode_length的字典
    """
    try:
        # 移除大括号并解析
        types_str = types_str.strip('{}')
        # 使用ast.literal_eval安全解析
        types_tuple = ast.literal_eval(types_str)
        
        # 如果是单个元组，转换为列表
        if isinstance(types_tuple, tuple):
            types_list = [types_tuple]
        else:
            types_list = list(types_tuple)
        
        # 获取第一个类型
        first_type = types_list[0]
        
        return {
            'prefill_length': int(first_type[0]),
            'decode_length': int(first_type[1])
        }
    except Exception as e:
        print(f"解析类型字符串失败: {e}")
        return None


def filter_active_requests(requests: List[Request]) -> List[Request]:
    """
    过滤出活跃的请求（非COMPLETED状态）
    
    Args:
        requests: 所有请求列表
        
    Returns:
        活跃请求列表
    """
    return [req for req in requests if req.status != RequestStatus.COMPLETED]