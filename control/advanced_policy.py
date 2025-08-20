"""
高级控制策略实现
支持Swap/Sacrifice模式和Aggressive/Conservative策略
"""
from typing import List, Optional, Dict, Any
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.request import Request, SwapEvent, SacrificeEvent
from core.system_state import SystemState
from .base_policy import ControlPolicy


class AdvancedPolicy(ControlPolicy):
    """
    高级策略：
    - 抢占模式：Swap 或 Sacrifice
    - 抢占策略：Aggressive 或 Conservative
    - 队列策略：FCFS
    - Victim选择：LIFO（基于进入RUNNING的时间）
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化高级策略
        
        Args:
            config: 配置字典，包含：
                - preemption_mode: "swap" 或 "sacrifice"
                - preemption_strategy: "aggressive" 或 "conservative"
                - allow_waiting_preempt: bool, WAITING是否可以触发抢占
        """
        self.preemption_mode = config.get('preemption_mode', 'swap')
        self.preemption_strategy = config.get('preemption_strategy', 'conservative')
        self.allow_waiting_preempt = config.get('allow_waiting_preempt', False)
        
        # 验证配置
        assert self.preemption_mode in ['swap', 'sacrifice'], \
            f"Invalid preemption_mode: {self.preemption_mode}"
        assert self.preemption_strategy in ['aggressive', 'conservative'], \
            f"Invalid preemption_strategy: {self.preemption_strategy}"
    
    def select_from_waiting(self, waiting: List[Request], 
                           available_memory: int) -> List[Request]:
        """
        FCFS方式从等待队列选择请求
        """
        selected = []
        for req in waiting:
            if req.memory_requirement <= available_memory:
                selected.append(req)
                available_memory -= req.memory_requirement
        return selected
    
    def select_swap_victims(self, running: List[Request], 
                          memory_needed: int) -> List[Request]:
        """
        LIFO方式选择swap victims
        """
        return self._select_victims_lifo(running, memory_needed)
    
    def select_sacrifice_victims(self, running: List[Request], 
                               memory_needed: int) -> List[Request]:
        """
        LIFO方式选择sacrifice victims
        """
        return self._select_victims_lifo(running, memory_needed)
    
    def _select_victims_lifo(self, running: List[Request], 
                            memory_needed: int) -> List[Request]:
        """
        LIFO选择victim的通用逻辑
        """
        if not running:
            return []
        
        # 按进入RUNNING的时间降序排序（最晚的在前）
        sorted_batch = sorted(
            running, 
            key=lambda r: r.enter_running_times[-1] if r.enter_running_times else 0,
            reverse=True
        )
        
        victims = []
        freed_memory = 0
        
        for req in sorted_batch:
            if freed_memory >= memory_needed:
                break
            victims.append(req)
            freed_memory += req.current_memory_usage
        
        return victims
    
    def construct_next_batch(self, state: SystemState, 
                           current_time: float) -> None:
        """
        构建下一个批次
        根据策略选择不同的准入控制逻辑
        """
        # Phase 1: 处理内存增长（预防性检查）
        self._handle_memory_growth(state, current_time)
        
        # Phase 2: 准入控制（根据策略选择）
        if self.preemption_strategy == "aggressive":
            self._admission_control_aggressive(state, current_time)
        else:
            self._admission_control_conservative(state, current_time)
    
    def _handle_memory_growth(self, state: SystemState, current_time: float):
        """
        处理内存增长：如果仅执行现有RUNNING请求就会超内存，则先抢占
        """
        if state.gpu_memory_used + len(state.running) > state.M_total:
            memory_needed = (state.gpu_memory_used + len(state.running)) - state.M_total
            
            if self.preemption_mode == 'swap':
                victims = self.select_swap_victims(state.running, memory_needed)
                for victim in victims:
                    self._do_swap_out(victim, state, current_time)
            else:  # sacrifice
                victims = self.select_sacrifice_victims(state.running, memory_needed)
                for victim in victims:
                    self._do_sacrifice(victim, state, current_time)
    
    def _admission_control_conservative(self, state: SystemState, current_time: float):
        """
        保守准入控制：最小化抢占
        """
        # 1. 优先处理SWAPPED队列（如果是swap模式）
        if self.preemption_mode == 'swap' and state.swapped:
            self._try_admit_without_preemption(
                state.swapped, state, current_time, is_swapped=True
            )
        
        # 2. 处理WAITING队列（包括sacrifice模式下的高优先级请求）
        self._try_admit_without_preemption(
            state.waiting, state, current_time, is_swapped=False
        )
        
        # 注意：Conservative策略下不进行任何抢占
        # 完全依赖请求自然完成来释放内存
        # 这样可以避免系统震荡，保持稳定性
    
    def _admission_control_aggressive(self, state: SystemState, current_time: float):
        """
        激进准入控制：vLLM风格，严格优先级
        """
        # 1. SWAPPED队列（最高优先级，仅swap模式）
        if self.preemption_mode == 'swap':
            for req in list(state.swapped):
                if not self._try_admit_with_preemption(req, state, current_time, from_swapped=True):
                    break  # 即使抢占也无法接纳
        
        # 2. WAITING队列
        # 在sacrifice模式下，队首的是被牺牲的请求，有最高优先级
        for req in list(state.waiting):
            # 判断是否允许为WAITING请求抢占
            allow_preempt = (self.allow_waiting_preempt or 
                           self.preemption_mode == 'sacrifice')  # sacrifice模式总是允许
            
            if allow_preempt:
                if not self._try_admit_with_preemption(req, state, current_time, from_swapped=False):
                    break
            else:
                # 只接纳能直接放下的
                if not self._try_admit_direct(req, state, current_time):
                    # 不能接纳，但继续尝试后面更小的请求
                    continue
    
    def _try_admit_without_preemption(self, queue: List[Request], 
                                     state: SystemState, 
                                     current_time: float,
                                     is_swapped: bool = False):
        """
        尝试在不抢占的情况下接纳请求
        """
        admitted = []
        for req in queue[:]:  # 使用切片避免修改时的问题
            # 检查内存（考虑执行后的增长）
            required_memory = req.memory_requirement + 1
            if required_memory <= state.available_memory:
                admitted.append(req)
                # 临时减少可用内存（用于后续请求的检查）
                state.M_total -= required_memory  # 临时修改
        
        # 恢复M_total
        for req in admitted:
            state.M_total += req.memory_requirement + 1
        
        # 执行实际的接纳
        for req in admitted:
            if is_swapped:
                # 从swapped恢复
                state.swapped.remove(req)
                state.admit_to_batch(req, current_time)
                state.total_swapped_in += 1
                if req.swap_events:
                    req.swap_events[-1].swap_in_time = current_time
            else:
                # 从waiting接纳
                state.waiting.remove(req)
                state.admit_to_batch(req, current_time)
    
    def _try_admit_direct(self, request: Request, 
                         state: SystemState, 
                         current_time: float) -> bool:
        """
        尝试直接接纳请求（不抢占）
        """
        required_memory = request.memory_requirement + 1
        if required_memory <= state.available_memory:
            state.waiting.remove(request)
            state.admit_to_batch(request, current_time)
            return True
        return False
    
    def _try_admit_with_preemption(self, request: Request,
                                  state: SystemState,
                                  current_time: float,
                                  from_swapped: bool = False) -> bool:
        """
        尝试接纳请求，必要时进行抢占
        """
        # 1. 检查是否可以直接接纳
        required_memory = request.memory_requirement + 1
        if required_memory <= state.available_memory:
            # 可以直接接纳
            if from_swapped:
                state.swapped.remove(request)
                state.admit_to_batch(request, current_time)
                state.total_swapped_in += 1
                if request.swap_events:
                    request.swap_events[-1].swap_in_time = current_time
            else:
                state.waiting.remove(request)
                state.admit_to_batch(request, current_time)
            return True
        
        # 2. 需要抢占
        memory_needed = required_memory - state.available_memory
        
        # 3. 选择victims
        if self.preemption_mode == 'swap':
            victims = self.select_swap_victims(state.running, memory_needed)
        else:
            victims = self.select_sacrifice_victims(state.running, memory_needed)
        
        # 检查是否能释放足够内存
        freed_memory = sum(v.current_memory_usage for v in victims)
        if freed_memory < memory_needed:
            return False  # 即使抢占所有可能的请求也不够
        
        # 4. 执行抢占
        for victim in victims:
            if self.preemption_mode == 'swap':
                self._do_swap_out(victim, state, current_time)
            else:
                self._do_sacrifice(victim, state, current_time)
        
        # 5. 接纳请求
        if from_swapped:
            state.swapped.remove(request)
            state.admit_to_batch(request, current_time)
            state.total_swapped_in += 1
            if request.swap_events:
                request.swap_events[-1].swap_in_time = current_time
        else:
            state.waiting.remove(request)
            state.admit_to_batch(request, current_time)
        
        return True
    
    def _do_swap_out(self, request: Request, state: SystemState, current_time: float):
        """
        执行swap out操作
        """
        swap_event = SwapEvent(
            swap_out_time=current_time,
            decode_position=request.current_decode_position,
            memory_size=request.current_memory_usage
        )
        request.swap_events.append(swap_event)
        state.swap_out(request, current_time)
    
    def _do_sacrifice(self, request: Request, state: SystemState, current_time: float):
        """
        执行sacrifice操作
        """
        state.sacrifice_request(request, current_time)
    
    def __repr__(self) -> str:
        return f"AdvancedPolicy({self.preemption_mode}+{self.preemption_strategy})"