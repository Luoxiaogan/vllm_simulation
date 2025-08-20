"""
仿真器基类
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.request import Request
from core.system_state import SystemState, SystemSnapshot
from control.base_policy import ControlPolicy


class BaseSimulator(ABC):
    """
    仿真器基类
    """
    
    def __init__(self, config: Dict[str, Any], control_policy: ControlPolicy):
        """
        初始化仿真器
        
        Args:
            config: 系统配置
            control_policy: 控制策略
        """
        # 系统参数
        self.M_total = config['system']['M_total']
        self.B = config['system']['B']
        self.d_0 = config['system']['d_0']
        self.d_1 = config['system']['d_1']
        
        # 控制策略
        self.control_policy = control_policy
        
        # 系统状态
        self.state = SystemState(self.M_total, self.B)
        
        # 时间管理
        self.time = 0.0
        self.batch_id = 0
        
        # 数据记录
        self.snapshots: List[SystemSnapshot] = []
        self.events: List[Dict[str, Any]] = []
    
    def calculate_batch_duration(self) -> float:
        """
        计算当前批次的执行时间
        
        Returns:
            批次执行时间
        """
        batch_tokens = self.state.batch_token_count
        return self.d_0 + self.d_1 * batch_tokens
    
    def advance_decode_positions(self):
        """
        推进所有运行中请求的解码位置
        """
        for req in self.state.running:
            req.current_decode_position += 1
    
    def extract_completed_requests(self) -> List[Request]:
        """
        提取并处理完成的请求
        
        Returns:
            完成的请求列表
        """
        completed = []
        for req in self.state.running[:]:
            if req.is_completed:
                self.state.complete_request(req, self.time)
                completed.append(req)
                self.log_event('completion', req.req_id, {
                    'decode_length': req.decode_length,
                    'total_delay': req.total_delay
                })
        return completed
    
    def log_event(self, event_type: str, req_id: int, details: Dict[str, Any]):
        """
        记录事件
        
        Args:
            event_type: 事件类型
            req_id: 请求ID
            details: 事件详情
        """
        self.events.append({
            'time': self.time,
            'batch_id': self.batch_id,
            'event_type': event_type,
            'req_id': req_id,
            'details': details
        })
    
    def record_snapshot(self):
        """
        记录系统快照
        """
        duration = self.calculate_batch_duration()
        snapshot = self.state.get_snapshot(self.time, self.batch_id, duration)
        self.snapshots.append(snapshot)
    
    @abstractmethod
    def handle_memory_pressure(self):
        """
        处理内存压力（子类实现）
        """
        pass
    
    @abstractmethod
    def step(self) -> bool:
        """
        执行一个仿真步骤
        
        Returns:
            是否继续仿真
        """
        pass
    
    @abstractmethod
    def run(self, requests: List[Request]) -> Dict[str, Any]:
        """
        运行仿真
        
        Args:
            requests: 请求列表
            
        Returns:
            仿真结果
        """
        pass