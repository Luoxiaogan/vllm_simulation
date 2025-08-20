"""
请求类定义
"""
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from .constants import RequestStatus


@dataclass
class SwapEvent:
    """交换事件记录"""
    swap_out_time: float
    swap_in_time: Optional[float] = None
    decode_position: int = 0
    memory_size: int = 0


@dataclass
class SacrificeEvent:
    """牺牲事件记录"""
    time: float
    decode_position: int
    memory_freed: int


@dataclass
class Request:
    """
    请求类，追踪请求的完整生命周期
    """
    # 基础属性
    req_id: int
    arrival_time: float
    prefill_length: int
    decode_length: int
    
    # 状态管理
    status: str = RequestStatus.WAITING
    current_decode_position: int = 0
    
    # 时间戳记录
    enter_running_times: List[float] = field(default_factory=list)
    exit_running_times: List[float] = field(default_factory=list)
    completion_time: Optional[float] = None
    
    # Swapping模式事件
    swap_events: List[SwapEvent] = field(default_factory=list)
    
    # Sacrifice模式事件
    sacrifice_events: List[SacrificeEvent] = field(default_factory=list)
    
    @property
    def current_memory_usage(self) -> int:
        """
        当前占用的GPU内存（仅RUNNING状态）
        """
        if self.status == RequestStatus.RUNNING:
            return self.prefill_length + self.current_decode_position
        return 0
    
    @property
    def memory_requirement(self) -> int:
        """
        进入RUNNING所需的内存
        """
        return self.prefill_length + self.current_decode_position
    
    @property
    def total_tokens_generated(self) -> int:
        """
        已生成的总token数
        """
        return self.current_decode_position
    
    @property
    def is_completed(self) -> bool:
        """
        是否已完成解码
        """
        return self.current_decode_position >= self.decode_length
    
    @property
    def remaining_decode_length(self) -> int:
        """
        剩余需要解码的长度
        """
        return max(0, self.decode_length - self.current_decode_position)
    
    @property
    def total_delay(self) -> Optional[float]:
        """
        端到端延迟
        """
        if self.completion_time is not None:
            return self.completion_time - self.arrival_time
        return None
    
    @property
    def waiting_time(self) -> Optional[float]:
        """
        等待时间（首次进入RUNNING前的时间）
        """
        if self.enter_running_times:
            return self.enter_running_times[0] - self.arrival_time
        return None
    
    @property
    def execution_time(self) -> Optional[float]:
        """
        执行时间（首次进入RUNNING到完成的时间）
        """
        if self.completion_time is not None and self.enter_running_times:
            return self.completion_time - self.enter_running_times[0]
        return None
    
    @property
    def swap_count(self) -> int:
        """
        被交换的次数
        """
        return len(self.swap_events)
    
    @property
    def sacrifice_count(self) -> int:
        """
        被牺牲的次数
        """
        return len(self.sacrifice_events)
    
    @property
    def total_swapped_time(self) -> float:
        """
        总的swapped状态时间
        """
        total = 0.0
        for event in self.swap_events:
            if event.swap_in_time is not None:
                total += event.swap_in_time - event.swap_out_time
        return total
    
    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典格式，用于输出
        """
        return {
            'req_id': self.req_id,
            'arrival_time': self.arrival_time,
            'prefill_length': self.prefill_length,
            'decode_length': self.decode_length,
            'status': self.status,
            'current_decode_position': self.current_decode_position,
            'completion_time': self.completion_time,
            'total_delay': self.total_delay,
            'waiting_time': self.waiting_time,
            'execution_time': self.execution_time,
            'swap_count': self.swap_count,
            'sacrifice_count': self.sacrifice_count,
            'total_swapped_time': self.total_swapped_time
        }
    
    def __repr__(self) -> str:
        return (f"Request(id={self.req_id}, status={self.status}, "
                f"decode={self.current_decode_position}/{self.decode_length}, "
                f"memory={self.memory_requirement})")