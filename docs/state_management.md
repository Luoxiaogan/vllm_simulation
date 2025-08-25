# 状态管理功能文档

## 概述
状态管理功能允许在仿真过程中保存系统状态快照，并从保存的状态恢复继续仿真。这对于长时间仿真的断点续传、实验复现和状态分析非常有用。

## 功能特性

### 1. 状态保存
- 在指定的批次ID保存完整系统状态
- 保存所有请求的详细信息（包括WAITING、RUNNING、SWAPPED状态）
- 记录当前时间和批次信息
- CSV格式便于分析和调试

### 2. 状态加载
- 从CSV文件加载初始状态
- 自动进行时间归一化（调整arrival_time）
- 支持指定统一的请求类型（prefill和decode长度）
- 系统从正确的时间点继续运行

### 3. 继续生成
- 支持在加载状态后继续生成新请求
- 自动调整新请求的到达时间（加上初始时间偏移）
- 保持时间连续性

## 配置说明

### 状态保存配置
```yaml
state_save:
  enabled: true           # 启用状态保存
  batch_ids: [100, 500, 1000]  # 在这些批次保存状态
  save_completed: true    # 是否包含已完成的请求
```

### 初始状态配置
```yaml
initial_state:
  enabled: true          # 启用初始状态加载
  state_file: "path/to/state_batch_XXX.csv"  # 状态文件路径
  continue_generation: true  # 是否继续生成新请求
```

## 使用示例

### 1. 保存状态
```yaml
# config/save_state.yaml
generation:
  enabled: true
  types: "{(20,20,5.1)}"
  num_requests: 10000

state_save:
  enabled: true
  batch_ids: [500, 1000, 2000]

# 运行
python experiments/run_advanced_with_generation.py --config config/save_state.yaml
```

### 2. 从状态恢复
```yaml
# config/load_state.yaml
initial_state:
  enabled: true
  state_file: "data/experiments/xxx/states/state_batch_1000.csv"
  
generation:
  enabled: false  # 不生成新请求，只运行已有请求
```

### 3. 恢复并继续生成
```yaml
# config/continue_from_state.yaml
initial_state:
  enabled: true
  state_file: "data/experiments/xxx/states/state_batch_1000.csv"
  
generation:
  enabled: true
  types: "{(20,20,5.1)}"  # 使用相同类型
  num_requests: 5000      # 额外生成5000个请求
```

## 实现细节

### 时间归一化
1. 找到所有请求的最小arrival_time
2. 所有时间减去最小值（归一化到0）
3. 系统初始时间 = max_arrival_time - min_arrival_time
4. 仿真从初始时间开始，而不是0

### 内存管理
- GPU内存使用自动计算（不能直接设置）
- 基于RUNNING队列中请求的current_memory_usage总和

### 队列管理
- WAITING、RUNNING、SWAPPED队列根据请求状态自动分配
- COMPLETED请求不加入队列（但保留在请求列表中用于统计）

## 文件格式

### 状态CSV文件
```csv
# Batch ID: 100
# Current Time: 156.78
# Save Time: 2024-08-25T11:35:00
# Total Requests: 10000
# WAITING: 500, RUNNING: 100, SWAPPED: 50
#
req_id,status,arrival_time,prefill_length,decode_length,current_decode_position,...
```

## 注意事项

1. **请求类型一致性**：建议使用相同的请求类型（prefill和decode长度）以保证仿真一致性
2. **内存约束**：加载状态时会自动检查GPU内存使用是否超限
3. **时间连续性**：新生成的请求会自动调整时间偏移，保证到达时间的连续性
4. **批次ID**：状态保存基于批次ID而不是时间，更直观和可控

## 相关文件

- `core/state_manager.py`: 状态管理核心功能
- `simulation/vllm_simulator_with_state.py`: 支持状态管理的仿真器
- `experiments/run_advanced_with_generation.py`: 集成的实验运行脚本
- `config/config_with_generation.yaml`: 配置文件模板