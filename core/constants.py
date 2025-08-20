"""
常量定义
"""

# 请求状态
class RequestStatus:
    WAITING = "waiting"      # 等待调度
    RUNNING = "running"      # 执行中
    SWAPPED = "swapped"      # 已交换到CPU
    COMPLETED = "completed"  # 已完成

# 服务器模式
class ServerMode:
    SWAPPING = "swapping"    # 交换模式
    SACRIFICE = "sacrifice"  # 牺牲模式

# 控制策略
class QueuePolicy:
    FCFS = "FCFS"           # First-Come-First-Served
    PRIORITY = "priority"    # 优先级队列

class VictimPolicy:
    LIFO = "LIFO"           # Last-In-First-Out
    FIFO = "FIFO"           # First-In-First-Out
    RANDOM = "random"        # 随机选择
    LRU = "LRU"             # Least Recently Used