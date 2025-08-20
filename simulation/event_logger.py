"""
事件记录器和CSV输出
"""
import csv
import os
from typing import List, Dict, Any
from pathlib import Path
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.request import Request
from core.system_state import SystemSnapshot


class EventLogger:
    """
    事件记录器，负责将仿真数据输出到CSV文件
    """
    
    def __init__(self, output_dir: str = "data/output"):
        """
        初始化记录器
        
        Args:
            output_dir: 输出目录
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def save_batch_snapshots(self, snapshots: List[SystemSnapshot], 
                           filename: str = "batch_snapshots.csv"):
        """
        保存批次快照
        
        Args:
            snapshots: 快照列表
            filename: 输出文件名
        """
        filepath = self.output_dir / filename
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # 写入表头
            writer.writerow([
                'time', 'batch_id', 'batch_count', 'batch_tokens', 
                'running_count', 'waiting_count', 'swapped_count', 
                'gpu_memory_used', 'memory_utilization',
                'batch_duration', 'completed_count', 'batch_sacrifice_count'
            ])
            
            # 写入数据
            for snap in snapshots:
                # batch_count是实际执行的批次大小（从RUNNING中选择的子集）
                # 这个值在select_execution_batch中设置
                batch_count = snap.actual_batch_count
                
                writer.writerow([
                    f"{snap.time:.4f}",
                    snap.batch_id,
                    batch_count,  # 实际执行的请求数（受B约束）
                    snap.total_tokens_in_batch,  # 实际执行批次的token总数
                    len(snap.running_ids),  # running队列大小（GPU上的所有请求）
                    len(snap.waiting_queue_ids),
                    len(snap.swapped_queue_ids),
                    snap.gpu_memory_used,  # GPU上所有请求的内存总和
                    f"{snap.gpu_memory_used / snap.system_memory_total:.4f}",
                    f"{snap.batch_duration:.4f}",
                    snap.num_completed,
                    snap.batch_sacrifice_count  # 本批次的sacrifice数量
                ])
        
        print(f"批次快照已保存到: {filepath}")
    
    def save_request_traces(self, requests: List[Request], 
                          filename: str = "request_traces.csv"):
        """
        保存请求轨迹
        
        Args:
            requests: 完成的请求列表
            filename: 输出文件名
        """
        filepath = self.output_dir / filename
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # 写入表头
            writer.writerow([
                'req_id', 'arrival_time', 'prefill_length', 'decode_length',
                'completion_time', 'total_delay', 'waiting_time', 'execution_time',
                'swap_count', 'total_swapped_time', 'sacrifice_count'
            ])
            
            # 写入数据
            for req in requests:
                writer.writerow([
                    req.req_id,
                    f"{req.arrival_time:.4f}",
                    req.prefill_length,
                    req.decode_length,
                    f"{req.completion_time:.4f}" if req.completion_time else "N/A",
                    f"{req.total_delay:.4f}" if req.total_delay else "N/A",
                    f"{req.waiting_time:.4f}" if req.waiting_time else "N/A",
                    f"{req.execution_time:.4f}" if req.execution_time else "N/A",
                    req.swap_count,
                    f"{req.total_swapped_time:.4f}",
                    req.sacrifice_count
                ])
        
        print(f"请求轨迹已保存到: {filepath}")
    
    def save_events(self, events: List[Dict[str, Any]], 
                   filename: str = "events.csv"):
        """
        保存事件日志
        
        Args:
            events: 事件列表
            filename: 输出文件名
        """
        filepath = self.output_dir / filename
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # 写入表头
            writer.writerow(['time', 'batch_id', 'event_type', 'req_id', 'details'])
            
            # 写入数据
            for event in events:
                details_str = str(event['details']).replace(',', ';')
                writer.writerow([
                    f"{event['time']:.4f}",
                    event['batch_id'],
                    event['event_type'],
                    event['req_id'],
                    details_str
                ])
        
        print(f"事件日志已保存到: {filepath}")
    
    def save_queue_timeline(self, snapshots: List[SystemSnapshot], 
                          filename: str = "queue_timeline.csv"):
        """
        保存队列状态时间线
        
        Args:
            snapshots: 快照列表
            filename: 输出文件名
        """
        filepath = self.output_dir / filename
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # 写入表头
            writer.writerow(['time', 'batch_id', 'queue_type', 'req_ids'])
            
            # 写入数据
            for snap in snapshots:
                # WAITING队列
                if snap.waiting_queue_ids:
                    writer.writerow([
                        f"{snap.time:.4f}",
                        snap.batch_id,
                        'waiting',
                        str(snap.waiting_queue_ids)
                    ])
                
                # RUNNING批次
                if snap.running_ids:
                    writer.writerow([
                        f"{snap.time:.4f}",
                        snap.batch_id,
                        'running',
                        str(snap.running_ids)
                    ])
                
                # SWAPPED队列
                if snap.swapped_queue_ids:
                    writer.writerow([
                        f"{snap.time:.4f}",
                        snap.batch_id,
                        'swapped',
                        str(snap.swapped_queue_ids)
                    ])
        
        print(f"队列时间线已保存到: {filepath}")
    
    def save_memory_events(self, events: List[Dict[str, Any]], 
                         snapshots: List[SystemSnapshot],
                         filename: str = "memory_events.csv"):
        """
        保存内存事件
        
        Args:
            events: 事件列表
            snapshots: 快照列表
            filename: 输出文件名
        """
        filepath = self.output_dir / filename
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # 写入表头
            writer.writerow([
                'time', 'batch_id', 'event', 'req_id', 
                'decode_position', 'memory_change', 'gpu_memory_after'
            ])
            
            # 创建时间到内存使用的映射
            time_to_memory = {snap.time: snap.gpu_memory_used for snap in snapshots}
            
            # 写入内存相关事件
            for event in events:
                if event['event_type'] in ['swap_out', 'swap_in', 'arrival', 'completion']:
                    memory_change = 0
                    decode_position = 0
                    
                    if event['event_type'] == 'swap_out':
                        memory_change = -event['details'].get('memory_freed', 0)
                        decode_position = event['details'].get('decode_position', 0)
                    elif event['event_type'] == 'swap_in':
                        # swap_in的内存变化需要从请求信息计算
                        memory_change = event['details'].get('memory_restored', 0)
                        decode_position = event['details'].get('decode_position', 0)
                    
                    gpu_memory = time_to_memory.get(event['time'], 0)
                    
                    writer.writerow([
                        f"{event['time']:.4f}",
                        event['batch_id'],
                        event['event_type'],
                        event['req_id'],
                        decode_position,
                        memory_change,
                        gpu_memory
                    ])
        
        print(f"内存事件已保存到: {filepath}")
    
    def save_all(self, simulation_results: Dict[str, Any]):
        """
        保存所有仿真结果
        
        Args:
            simulation_results: 仿真结果字典
        """
        # 保存各种CSV文件
        self.save_batch_snapshots(simulation_results['snapshots'])
        self.save_request_traces(simulation_results['requests'])
        self.save_events(simulation_results['events'])
        self.save_queue_timeline(simulation_results['snapshots'])
        self.save_memory_events(simulation_results['events'], 
                              simulation_results['snapshots'])
        
        # 保存汇总统计
        self.save_summary(simulation_results)
    
    def save_summary(self, results: Dict[str, Any], 
                    filename: str = "summary.txt"):
        """
        保存仿真汇总
        
        Args:
            results: 仿真结果
            filename: 输出文件名
        """
        filepath = self.output_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("=== 仿真汇总报告 ===\n\n")
            
            # 基本信息
            f.write("基本信息:\n")
            f.write(f"  总时间: {results['total_time']:.2f}\n")
            f.write(f"  总批次数: {results['total_batches']}\n")
            f.write(f"  完成请求数: {results['completed_requests']}\n\n")
            
            # 系统统计
            if 'statistics' in results:
                f.write("系统统计:\n")
                stats = results['statistics']
                for key, value in stats.items():
                    f.write(f"  {key}: {value}\n")
                f.write("\n")
            
            # 性能指标
            if 'metrics' in results:
                f.write("性能指标:\n")
                metrics = results['metrics']
                for key, value in metrics.items():
                    if isinstance(value, float):
                        f.write(f"  {key}: {value:.4f}\n")
                    else:
                        f.write(f"  {key}: {value}\n")
        
        print(f"汇总报告已保存到: {filepath}")