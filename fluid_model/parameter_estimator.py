"""
从仿真数据估计ODE参数
"""
import numpy as np
from typing import Dict, Any, List, Callable, Tuple
import pandas as pd
from collections import defaultdict
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class ParameterEstimator:
    """
    从离散仿真数据估计流体模型参数
    """
    
    def __init__(self, simulation_results: Dict[str, Any], L: int):
        """
        初始化参数估计器
        
        Args:
            simulation_results: 仿真结果
            L: 最大解码长度
        """
        self.results = simulation_results
        self.L = L
        self.events = simulation_results['events']
        self.snapshots = simulation_results['snapshots']
        self.requests = simulation_results['requests']
        
        # 构建时间索引
        self._build_time_index()
    
    def _build_time_index(self):
        """
        构建时间索引，便于查询特定时间窗口的事件
        """
        self.time_to_events = defaultdict(list)
        for event in self.events:
            t = int(event['time'])  # 离散化时间
            self.time_to_events[t].append(event)
        
        self.time_to_snapshot = {}
        for snap in self.snapshots:
            self.time_to_snapshot[snap.time] = snap
    
    def estimate_arrival_rate(self, time_window: float = 10.0) -> Callable:
        """
        估计到达率函数 λ(t)
        
        Args:
            time_window: 时间窗口大小
            
        Returns:
            到达率函数
        """
        # 统计每个时间窗口的到达数
        arrival_counts = defaultdict(int)
        
        for event in self.events:
            if event['event_type'] == 'arrival':
                window = int(event['time'] / time_window)
                arrival_counts[window] += 1
        
        # 创建插值函数
        def lambda_func(t: float) -> float:
            window = int(t / time_window)
            if window in arrival_counts:
                return arrival_counts[window] / time_window
            return 0.0
        
        return lambda_func
    
    def estimate_p_i(self, time_window: float = 10.0) -> Callable:
        """
        估计队列请求的解码位置分布 p_i(t)
        
        Args:
            time_window: 时间窗口大小
            
        Returns:
            分布函数 p_i(t, i)
        """
        # 统计从队列进入批次的请求的解码位置
        admission_positions = defaultdict(lambda: defaultdict(int))
        
        for req in self.requests:
            if req.enter_running_times:
                for enter_time in req.enter_running_times:
                    window = int(enter_time / time_window)
                    # 进入时的解码位置
                    position = req.current_decode_position if req.current_decode_position > 0 else 1
                    admission_positions[window][position] += 1
        
        def p_i_func(t: float, i: int) -> float:
            window = int(t / time_window)
            if window in admission_positions:
                total = sum(admission_positions[window].values())
                if total > 0:
                    return admission_positions[window].get(i, 0) / total
            # 默认均匀分布
            return 1.0 / self.L if i <= self.L else 0.0
        
        return p_i_func
    
    def estimate_q_i(self, time_window: float = 10.0) -> Callable:
        """
        估计完成概率 q_i(t)
        
        Args:
            time_window: 时间窗口大小
            
        Returns:
            完成概率函数 q_i(t, i)
        """
        # 统计各解码位置的完成情况
        completion_stats = defaultdict(lambda: defaultdict(lambda: {'total': 0, 'completed': 0}))
        
        for event in self.events:
            if event['event_type'] == 'completion':
                window = int(event['time'] / time_window)
                decode_length = event['details'].get('decode_length', self.L)
                # 在位置decode_length时完成
                completion_stats[window][decode_length]['completed'] += 1
        
        # 统计各位置的请求数（从快照）
        for snap in self.snapshots:
            window = int(snap.time / time_window)
            # 这里简化处理，假设请求均匀分布在各解码位置
            running_count = len(snap.running_ids)
            if running_count > 0:
                for i in range(1, self.L + 1):
                    completion_stats[window][i]['total'] += running_count / self.L
        
        def q_i_func(t: float, i: int) -> float:
            # 简化：如果达到目标长度则完成
            # 实际应该从数据中学习
            if i >= self.L:
                return 1.0
            return 0.0
        
        return q_i_func
    
    def estimate_r_i(self, time_window: float = 10.0) -> Callable:
        """
        估计swap概率 r_i(t)
        
        Args:
            time_window: 时间窗口大小
            
        Returns:
            swap概率函数 r_i(t, i)
        """
        # 统计各解码位置的swap情况
        swap_stats = defaultdict(lambda: defaultdict(lambda: {'total': 0, 'swapped': 0}))
        
        for event in self.events:
            if event['event_type'] == 'swap_out':
                window = int(event['time'] / time_window)
                position = event['details'].get('decode_position', 0)
                if position > 0:
                    swap_stats[window][position]['swapped'] += 1
        
        # 统计各位置的请求数
        for snap in self.snapshots:
            window = int(snap.time / time_window)
            running_count = len(snap.running_ids)
            if running_count > 0:
                for i in range(1, self.L + 1):
                    swap_stats[window][i]['total'] += running_count / self.L
        
        def r_i_func(t: float, i: int) -> float:
            window = int(t / time_window)
            if window in swap_stats and i in swap_stats[window]:
                stats = swap_stats[window][i]
                if stats['total'] > 0:
                    return stats['swapped'] / stats['total']
            # 默认swap概率
            return 0.1 if i < self.L else 0.0
        
        return r_i_func
    
    def estimate_control_functions(self) -> Tuple[Callable, Callable]:
        """
        估计控制函数 S_q(t) 和 S_Z(t)
        
        Returns:
            (S_q_func, S_Z_func)
        """
        # 统计队列调度速率
        queue_admissions = defaultdict(float)
        for req in self.requests:
            if req.enter_running_times:
                for enter_time in req.enter_running_times:
                    window = int(enter_time)
                    queue_admissions[window] += 1
        
        def S_q_func(t: float, state: np.ndarray) -> float:
            """队列调度速率"""
            window = int(t)
            if window in queue_admissions:
                return queue_admissions[window]
            # 默认：根据队列长度调度
            Q = state[0] if len(state) > 0 else 0
            return min(Q, 10.0)  # 最大调度速率为10
        
        # 统计交换恢复速率
        swap_restorations = defaultdict(lambda: defaultdict(float))
        for event in self.events:
            if event['event_type'] == 'swap_in':
                window = int(event['time'])
                position = event['details'].get('decode_position', 1)
                swap_restorations[window][position] += 1
        
        def S_Z_func(t: float, state: np.ndarray, i: int) -> float:
            """交换恢复速率"""
            window = int(t)
            if window in swap_restorations and i in swap_restorations[window]:
                return swap_restorations[window][i]
            # 默认：优先恢复
            L = (len(state) - 1) // 2 if len(state) > 1 else self.L
            if L > 0 and i <= L:
                Z_i = state[L + i] if len(state) > L + i else 0
                return min(Z_i, 1.0)
            return 0.0
        
        return S_q_func, S_Z_func
    
    def get_all_parameters(self) -> Dict[str, Callable]:
        """
        获取所有估计的参数
        
        Returns:
            参数字典
        """
        return {
            'lambda': self.estimate_arrival_rate(),
            'p_i': self.estimate_p_i(),
            'q_i': self.estimate_q_i(),
            'r_i': self.estimate_r_i(),
            'control': self.estimate_control_functions()
        }