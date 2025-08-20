"""
控制策略基类
"""
from abc import ABC, abstractmethod
from typing import List, Optional
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.request import Request
from core.system_state import SystemState


class ControlPolicy(ABC):
    """
    控制策略接口
    """
    
    @abstractmethod
    def select_from_waiting(self, waiting: List[Request], 
                           available_memory: int) -> List[Request]:
        """
        从等待队列选择请求进入批次
        
        Args:
            waiting: 等待队列
            available_memory: 可用内存
            
        Returns:
            选中的请求列表
        """
        pass
    
    @abstractmethod
    def select_swap_victims(self, running: List[Request], 
                          memory_needed: int) -> List[Request]:
        """
        选择要交换出去的请求（Swapping模式）
        
        Args:
            running: 当前RUNNING状态的请求
            memory_needed: 需要释放的内存量
            
        Returns:
            要交换的请求列表
        """
        pass
    
    @abstractmethod
    def select_sacrifice_victims(self, running: List[Request], 
                               memory_needed: int) -> List[Request]:
        """
        选择要牺牲的请求（Sacrifice模式）
        
        Args:
            running: 当前RUNNING状态的请求
            memory_needed: 需要释放的内存量
            
        Returns:
            要牺牲的请求列表
        """
        pass
    
    @abstractmethod
    def construct_next_batch(self, state: SystemState, 
                           current_time: float) -> None:
        """
        构建下一个批次
        
        Args:
            state: 系统状态
            current_time: 当前时间
        """
        pass