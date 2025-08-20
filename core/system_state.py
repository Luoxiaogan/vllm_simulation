"""
系统状态管理
"""
from typing import List, Set, Optional, Dict, Any
from dataclasses import dataclass, field
from .request import Request
from .constants import RequestStatus


@dataclass
class SystemSnapshot:
    """
    系统状态快照，记录某一时刻的完整状态
    """
    time: float
    batch_id: int
    
    # 队列状态
    waiting_queue_ids: List[int]
    running_ids: List[int]
    swapped_queue_ids: List[int]
    
    # 内存状态
    total_tokens_in_batch: int  # 实际执行批次的token数
    gpu_memory_used: int  # GPU上所有请求的内存总和
    system_memory_total: int
    
    # 执行信息
    batch_duration: float
    next_time: float
    
    # 统计信息
    num_completed: int
    num_admitted: int
    num_swapped_out: int
    num_swapped_in: int
    
    # 实际执行批次信息（有默认值的字段必须在最后）
    actual_batch_count: int = 0  # 实际执行的请求数（可能小于running_count）
    batch_sacrifice_count: int = 0  # 本批次期间的sacrifice数量（非累计）


class SystemState:
    """
    系统状态管理器
    """
    
    def __init__(self, M_total: int, B: int):
        """
        初始化系统状态
        
        Args:
            M_total: GPU系统总内存（tokens）
            B: 批次token预算上限
        """
        self.M_total = M_total
        self.B = B
        
        # 请求队列
        self.waiting: List[Request] = []
        self.running: List[Request] = []
        self.swapped: List[Request] = []
        self.completed_requests: List[Request] = []
        
        # 统计信息
        self.total_completed = 0
        self.total_admitted = 0
        self.total_swapped_out = 0
        self.total_swapped_in = 0
        self.total_sacrifices = 0  # 累计sacrifice次数
        self.batch_sacrifices = 0  # 当前批次的sacrifice次数
        
        # 实际执行批次信息（区分于RUNNING列表）
        self.actual_batch_tokens = 0
        self.actual_batch_count = 0
    
    @property
    def gpu_memory_used(self) -> int:
        """
        当前GPU内存使用量
        """
        return sum(req.current_memory_usage for req in self.running)
    
    @property
    def batch_token_count(self) -> int:
        """
        当前批次的token总数（用于计算执行时间）
        """
        return self.gpu_memory_used
    
    @property
    def available_memory(self) -> int:
        """
        可用GPU内存
        """
        return self.M_total - self.gpu_memory_used
    
    @property
    def is_memory_overloaded(self) -> bool:
        """
        是否内存超载
        """
        return self.gpu_memory_used > self.M_total
    
    @property
    def is_batch_full(self) -> bool:
        """
        批次是否已满
        """
        return self.gpu_memory_used >= self.B
    
    def can_admit(self, request: Request) -> bool:
        """
        检查是否可以接纳请求到批次中
        
        Args:
            request: 待检查的请求
            
        Returns:
            是否可以接纳
        """
        return request.memory_requirement <= self.available_memory
    
    def add_to_waiting(self, request: Request):
        """
        添加请求到等待队列
        """
        request.status = RequestStatus.WAITING
        self.waiting.append(request)
    
    def admit_to_batch(self, request: Request, current_time: float):
        """
        接纳请求到执行批次
        
        Args:
            request: 要接纳的请求
            current_time: 当前时间
            
        Raises:
            RuntimeError: 如果内存不足
        """
        # 安全检查：验证内存约束（只检查M_total，不检查B）
        if not self.can_admit(request):
            raise RuntimeError(f"内存不足，无法接纳请求 {request.req_id}。"
                             f"需要: {request.memory_requirement}, "
                             f"可用: {self.available_memory}")
        
        # B约束应该在批次构建阶段考虑，而不是在准入控制阶段
        # 这里只确保不超过物理内存M_total
        
        request.status = RequestStatus.RUNNING
        request.enter_running_times.append(current_time)
        self.running.append(request)
        self.total_admitted += 1
    
    def remove_from_batch(self, request: Request, current_time: float):
        """
        从批次中移除请求
        
        Args:
            request: 要移除的请求
            current_time: 当前时间
        """
        if request in self.running:
            request.exit_running_times.append(current_time)
            self.running.remove(request)
    
    def swap_out(self, request: Request, current_time: float):
        """
        将请求交换到CPU
        
        Args:
            request: 要交换的请求
            current_time: 当前时间
        """
        self.remove_from_batch(request, current_time)
        request.status = RequestStatus.SWAPPED
        self.swapped.append(request)
        self.total_swapped_out += 1
    
    def swap_in(self, request: Request, current_time: float):
        """
        将请求从CPU恢复到GPU
        
        Args:
            request: 要恢复的请求
            current_time: 当前时间
        """
        if request in self.swapped:
            self.swapped.remove(request)
            self.admit_to_batch(request, current_time)
            self.total_swapped_in += 1
    
    def sacrifice_request(self, request: Request, current_time: float):
        """
        牺牲请求（Sacrifice/Recompute模式）
        请求被移出GPU，解码进度重置，放回等待队列前端
        
        Args:
            request: 要牺牲的请求
            current_time: 当前时间
        """
        from .request import SacrificeEvent
        
        # 记录sacrifice事件
        sacrifice_event = SacrificeEvent(
            time=current_time,
            decode_position=request.current_decode_position,
            memory_freed=request.current_memory_usage
        )
        request.sacrifice_events.append(sacrifice_event)
        
        # 从running批次中移除
        self.remove_from_batch(request, current_time)
        
        # 重置解码进度
        request.current_decode_position = 0
        
        # 放回等待队列的前端（高优先级）
        request.status = RequestStatus.WAITING
        self.waiting.insert(0, request)  # 插入到队首
        
        # 更新sacrifice计数器
        self.total_sacrifices += 1
        self.batch_sacrifices += 1
    
    def complete_request(self, request: Request, current_time: float):
        """
        标记请求完成
        
        Args:
            request: 完成的请求
            current_time: 当前时间
        """
        self.remove_from_batch(request, current_time)
        request.status = RequestStatus.COMPLETED
        request.completion_time = current_time
        self.completed_requests.append(request)
        self.total_completed += 1
    
    def get_snapshot(self, time: float, batch_id: int, 
                    batch_duration: float) -> SystemSnapshot:
        """
        获取当前系统状态快照
        
        Args:
            time: 当前时间
            batch_id: 批次ID
            batch_duration: 批次执行时间
            
        Returns:
            系统快照
        """
        return SystemSnapshot(
            time=time,
            batch_id=batch_id,
            waiting_queue_ids=[req.req_id for req in self.waiting],
            running_ids=[req.req_id for req in self.running],
            swapped_queue_ids=[req.req_id for req in self.swapped],
            # 使用实际执行批次的token数，而不是所有RUNNING的token数
            total_tokens_in_batch=self.actual_batch_tokens if self.actual_batch_tokens > 0 else self.batch_token_count,
            gpu_memory_used=self.gpu_memory_used,
            system_memory_total=self.M_total,
            batch_duration=batch_duration,
            next_time=time + batch_duration,
            num_completed=self.total_completed,
            num_admitted=self.total_admitted,
            num_swapped_out=self.total_swapped_out,
            num_swapped_in=self.total_swapped_in,
            # actual_batch_count在最后，因为它有默认值
            actual_batch_count=self.actual_batch_count if self.actual_batch_count > 0 else len(self.running),
            batch_sacrifice_count=self.batch_sacrifices
        )
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        获取系统统计信息
        
        Returns:
            统计信息字典
        """
        return {
            'total_requests': len(self.waiting) + len(self.running) + 
                            len(self.swapped) + len(self.completed_requests),
            'waiting_count': len(self.waiting),
            'running_count': len(self.running),
            'swapped_count': len(self.swapped),
            'completed_count': len(self.completed_requests),
            'total_admitted': self.total_admitted,
            'total_swapped_out': self.total_swapped_out,
            'total_swapped_in': self.total_swapped_in,
            'gpu_memory_used': self.gpu_memory_used,
            'gpu_memory_total': self.M_total,
            'memory_utilization': self.gpu_memory_used / self.M_total if self.M_total > 0 else 0
        }
    
    def __repr__(self) -> str:
        return (f"SystemState(waiting={len(self.waiting)}, "
                f"running={len(self.running)}, "
                f"swapped={len(self.swapped)}, "
                f"completed={len(self.completed_requests)}, "
                f"memory={self.gpu_memory_used}/{self.M_total})")