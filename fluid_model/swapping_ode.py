"""
Swapping模式ODE系统
"""
import numpy as np
from typing import Callable, Dict, Any, List, Tuple
from scipy.integrate import odeint
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class SwappingODESystem:
    """
    Swapping模式的流体ODE系统
    
    根据fluid_modeling.tex，系统方程：
    dQ/dt = λ(t) - S_q(t)
    dZ_i/dt = X_i(t)r_i(t)/(d_0+d_1*B(t)) - S_{Z,i}(t)
    dX_i/dt = [X_{i-1}(t)(1-r_{i-1}-q_{i-1}) - X_i(t)]/(d_0+d_1*B(t)) + S_q(t)p_i(t) + S_{Z,i}(t)
    """
    
    def __init__(self, L: int, d_0: float, d_1: float, 
                 lambda_func: Callable, B_limit: float, M_total: float):
        """
        初始化ODE系统
        
        Args:
            L: 最大解码长度
            d_0: 批次执行基础时间
            d_1: 批次执行时间系数
            lambda_func: 到达率函数 λ(t)
            B_limit: 批次token预算
            M_total: 系统总内存
        """
        self.L = L
        self.d_0 = d_0
        self.d_1 = d_1
        self.lambda_func = lambda_func
        self.B_limit = B_limit
        self.M_total = M_total
        
        # 状态向量维度: Q + X_1...X_L + Z_1...Z_L
        self.state_dim = 1 + L + L
        
        # 参数函数（需要从仿真数据估计）
        self.p_i_func = None  # 队列请求分布
        self.q_i_func = None  # 完成概率
        self.r_i_func = None  # swap概率
        
        # 控制函数
        self.S_q_func = None  # 从队列进入批次的速率
        self.S_Z_func = None  # 从交换队列恢复的速率
    
    def set_parameter_functions(self, p_i: Callable, q_i: Callable, r_i: Callable):
        """
        设置参数函数
        
        Args:
            p_i: 队列请求分布函数 p_i(t, i)
            q_i: 完成概率函数 q_i(t, i)
            r_i: swap概率函数 r_i(t, i)
        """
        self.p_i_func = p_i
        self.q_i_func = q_i
        self.r_i_func = r_i
    
    def set_control_functions(self, S_q: Callable, S_Z: Callable):
        """
        设置控制函数
        
        Args:
            S_q: 队列调度速率 S_q(t, state)
            S_Z: 交换恢复速率 S_Z(t, state, i)
        """
        self.S_q_func = S_q
        self.S_Z_func = S_Z
    
    def compute_B(self, X: np.ndarray) -> float:
        """
        计算当前批次的总token数
        
        Args:
            X: X_i状态向量
            
        Returns:
            B(t) = Σ i * X_i(t)
        """
        B = 0.0
        for i in range(1, self.L + 1):
            B += i * X[i-1]
        return B
    
    def ode_system(self, state: np.ndarray, t: float) -> np.ndarray:
        """
        ODE系统右端函数
        
        Args:
            state: 状态向量 [Q, X_1, ..., X_L, Z_1, ..., Z_L]
            t: 时间
            
        Returns:
            状态导数向量
        """
        # 解析状态向量
        Q = state[0]
        X = state[1:self.L+1]
        Z = state[self.L+1:2*self.L+1]
        
        # 计算当前批次token数
        B_t = self.compute_B(X)
        
        # 计算批次执行速率
        if B_t > 0:
            execution_rate = 1.0 / (self.d_0 + self.d_1 * B_t)
        else:
            execution_rate = 0.0
        
        # 获取参数值
        lambda_t = self.lambda_func(t)
        
        # 初始化导数向量
        dstate_dt = np.zeros_like(state)
        
        # dQ/dt = λ(t) - S_q(t)
        S_q = self.S_q_func(t, state) if self.S_q_func else min(Q, self.B_limit)
        dstate_dt[0] = lambda_t - S_q
        
        # dX_i/dt 和 dZ_i/dt
        for i in range(1, self.L + 1):
            idx_X = i  # X_i的索引
            idx_Z = self.L + i  # Z_i的索引
            
            # 获取参数
            p_i = self.p_i_func(t, i) if self.p_i_func else 1.0/self.L
            q_i = self.q_i_func(t, i) if self.q_i_func else (1.0 if i >= self.L else 0.0)
            r_i = self.r_i_func(t, i) if self.r_i_func else 0.1
            
            # 前一个状态的参数（X_0 = 0）
            if i > 1:
                q_prev = self.q_i_func(t, i-1) if self.q_i_func else 0.0
                r_prev = self.r_i_func(t, i-1) if self.r_i_func else 0.1
                X_prev = X[i-2]
            else:
                q_prev = 0.0
                r_prev = 0.0
                X_prev = 0.0
            
            # 控制变量
            S_Z_i = self.S_Z_func(t, state, i) if self.S_Z_func else min(Z[i-1], self.B_limit)
            
            # dX_i/dt
            flow_in = X_prev * (1 - r_prev - q_prev) * execution_rate
            flow_out = X[i-1] * execution_rate
            admission = S_q * p_i
            restoration = S_Z_i
            
            dstate_dt[idx_X] = flow_in - flow_out + admission + restoration
            
            # dZ_i/dt
            swap_out = X[i-1] * r_i * execution_rate
            swap_in = S_Z_i
            
            dstate_dt[idx_Z] = swap_out - swap_in
        
        return dstate_dt
    
    def solve(self, initial_state: np.ndarray, time_points: np.ndarray) -> np.ndarray:
        """
        求解ODE系统
        
        Args:
            initial_state: 初始状态
            time_points: 时间点
            
        Returns:
            解矩阵，每行是一个时间点的状态
        """
        solution = odeint(self.ode_system, initial_state, time_points)
        return solution
    
    def get_initial_state(self, Q_0: float = 0.0) -> np.ndarray:
        """
        获取初始状态向量
        
        Args:
            Q_0: 初始队列长度
            
        Returns:
            初始状态向量
        """
        initial = np.zeros(self.state_dim)
        initial[0] = Q_0
        return initial


def create_default_control_functions(B_limit: float, M_total: float) -> Tuple[Callable, Callable]:
    """
    创建默认的控制函数
    
    Args:
        B_limit: 批次预算
        M_total: 总内存
        
    Returns:
        (S_q_func, S_Z_func)
    """
    def S_q_func(t: float, state: np.ndarray) -> float:
        """默认队列调度：尽可能多地接纳请求"""
        Q = state[0]
        # 简化：假设平均每个请求占用B_limit/10的内存
        return min(Q, B_limit / 50)
    
    def S_Z_func(t: float, state: np.ndarray, i: int) -> float:
        """默认交换恢复：优先恢复"""
        L = (len(state) - 1) // 2
        Z = state[L+1:2*L+1]
        if i <= L:
            return min(Z[i-1], B_limit / 100)
        return 0.0
    
    return S_q_func, S_Z_func