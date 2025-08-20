# Fluid ODE Simulation for LLM Serving

A simulation system for modeling LLM serving with fluid ODEs in the Operations Research framework.

## Quick Start

```bash
# 1. Generate test data
python data/input/generate_requests.py

# 2. Run advanced strategy simulation (default: swap + conservative)
python experiments/run_advanced.py

# 3. Test different strategy combinations
python experiments/run_advanced.py --mode sacrifice --strategy aggressive

# 4. Generate visualizations
python visualization/plot_dynamics.py
```

## System Parameters

### Core System Configuration (`config/config.yaml`)

#### System Parameters
- **`M_total`** (int): Total GPU memory in tokens (default: 10000)
  - Controls when swapping is triggered
  - Larger values reduce swapping but may affect batch size
- **`B`** (int): Maximum batch token budget (default: 2000)
  - Upper limit for tokens processed in a single batch
  - Affects throughput vs latency tradeoff
- **`d_0`** (float): Base batch execution time (default: 1.0)
  - Fixed overhead per batch regardless of size
- **`d_1`** (float): Per-token execution time coefficient (default: 0.001)
  - Marginal time cost per token
  - Total batch time = d_0 + d_1 * batch_size

#### Control Strategy Parameters

The system supports 4 strategy combinations: (swap/sacrifice) × (conservative/aggressive)

- **`preemption_mode`** (string): Preemption mode
  - `"swap"`: Preserve KV cache and progress, swap to CPU (default)
  - `"sacrifice"`: Clear KV cache, reset progress
- **`preemption_strategy`** (string): Preemption strategy
  - `"conservative"`: Preempt only when necessary (default)
  - `"aggressive"`: Actively preempt for high-priority requests
- **`allow_waiting_preempt`** (bool): Whether WAITING requests can trigger preemption (default: false)
- **`queue_policy`** (string): Queue scheduling policy - `"FCFS"`
- **`victim_policy`** (string): Victim selection policy - `"LIFO"`

#### Data Configuration
- **`request_file`** (string): Input request CSV file path
- **`experiments_dir`** (string): Experiments directory (auto-generates timestamped subdirectories)
- **`L_filter`** (int/null): Maximum decode length filter (null = no filter)

#### Experiment Configuration
- **`seed`** (int): Random seed for reproducibility (default: 42)
- **`verbose`** (bool): Enable detailed logging (default: true)
- **`progress_interval`** (int): Progress report interval in batches (default: 100)

### Request Generation Parameters

When using `data/input/generate_requests.py`:

- **`--num_requests`** (int): Number of requests to generate (default: 100)
- **`--arrival_rate`** (float): Average arrival rate in requests/time unit (default: 0.5)
- **`--scenario`** (string): Load scenario type
  - `"normal"`: Standard load with mixed request lengths
  - `"heavy"`: High arrival rate (2.0) with longer requests
  - `"bursty"`: Burst pattern with periods of intense load
- **`--output`** (string): Output filename (default: "requests.csv")

#### Request Distribution (Normal Scenario)
- 80% short requests:
  - prefill_length: 10-60 tokens
  - decode_length: 10-40 tokens
- 20% long requests:
  - prefill_length: 150-200 tokens
  - decode_length: 80-100 tokens

## Output Files

All output files are saved in `data/experiments/experiment_YYYYMMDD_HHMMSS_XXXX/` directory:

### 1. **batch_snapshots.csv**
System state after each batch execution:
- `time`: Cumulative simulation time
- `batch_id`: Unique batch identifier
- `batch_count`: Actual executed requests (subset constrained by B)
- `batch_tokens`: Total tokens in execution batch
- `running_count`: All requests in GPU memory (≥ batch_count)
- `waiting_count`: Requests in waiting queue
- `swapped_count`: Requests swapped to CPU
- `completed_count`: Total completed requests
- `gpu_memory_used`: Current GPU memory usage
- `memory_utilization`: GPU memory utilization ratio
- `batch_duration`: Execution time of this batch

### 2. **request_traces.csv**
Complete lifecycle trace for each request:
- `req_id`: Unique request identifier
- `arrival_time`: When request arrived at decode node
- `prefill_length`: Size of prefill KV cache
- `decode_length`: Number of tokens to decode
- `completion_time`: When request completed
- `total_delay`: End-to-end latency
- `waiting_time`: Time spent waiting
- `execution_time`: Time spent executing
- `swap_count`: Number of times swapped out
- `total_swapped_time`: Total time swapped
- `sacrifice_count`: Number of times sacrificed

### 3. **events.csv**
Detailed event log:
- `time`: Event timestamp
- `batch_id`: Batch ID
- `event_type`: Type of event (arrival, completion, swap_out, swap_in, etc.)
- `req_id`: Request involved
- `details`: Additional event information

### 4. **queue_timeline.csv**
Queue state timeline:
- `time`: Timestamp
- `batch_id`: Batch ID
- `queue_type`: Queue type (waiting/running/swapped)
- `req_ids`: List of request IDs in queue

### 5. **memory_events.csv**
Memory management events:
- `time`: Event timestamp
- `batch_id`: Batch ID
- `event`: Event type (swap_out/swap_in/arrival/completion)
- `req_id`: Related request
- `decode_position`: Decode position
- `memory_change`: Memory change
- `gpu_memory_after`: GPU memory after event

### 6. **summary.txt**
Human-readable summary report with:
- Basic statistics (total time, batches, completions)
- System statistics (queue lengths, swap counts)
- Performance metrics (throughput, latency, utilization)
- Sacrifice statistics (if using sacrifice mode)

### 7. **config_used.yaml**
Complete configuration snapshot used for the experiment

### 8. **experiment_meta.yaml**
Experiment metadata (time, paths, strategy combination, etc.)

## Usage Examples

### Basic Simulation
```bash
# Generate standard load and run simulation
python data/input/generate_requests.py --num_requests 100
python experiments/run_advanced.py
python visualization/plot_dynamics.py
```

### High Load Testing
```bash
# Generate heavy load scenario
python data/input/generate_requests.py --scenario heavy --num_requests 200
python experiments/run_advanced.py --requests data/input/requests.csv
```

### Strategy Combination Testing
```bash
# Test different strategy combinations
# Swap + Conservative (default)
python experiments/run_advanced.py

# Swap + Aggressive
python experiments/run_advanced.py --mode swap --strategy aggressive

# Sacrifice + Conservative
python experiments/run_advanced.py --mode sacrifice --strategy conservative

# Sacrifice + Aggressive
python experiments/run_advanced.py --mode sacrifice --strategy aggressive

# Or automatically test all 4 combinations
python experiments/test_all_strategies.py
```

### Experiment Management
```bash
# List all experiments
ls data/experiments/

# View latest experiment summary
cat data/experiments/experiment_*/summary.txt

# Clean old experiment results
bash scripts/clean.sh
```

## Shell Scripts

Located in `scripts/` directory:

- **`clean.sh`**: Clean output directory
- **`manage_experiments.sh`**: Experiment management tool

## Visualization

The `visualization/plot_dynamics.py` script generates two main plots:

1. **system_dynamics.png**: 6-panel system metrics over time
   - Queue states (waiting/running/swapped)
   - GPU memory usage
   - Memory utilization percentage
   - Batch execution times
   - Cumulative completions
   - Throughput (moving average)

2. **request_timeline.png**: Gantt-style chart showing:
   - Request lifecycles (waiting time in blue, execution in green)
   - Swap events marked with "S:n" labels
   - Sample of 20 requests for clarity

## Advanced Configuration

### Custom Request Patterns
Create custom request files with specific patterns:
```python
# In Python script or notebook
import csv

requests = [
    {"arrival_time": 0.0, "prefill_length": 100, "decode_length": 50},
    {"arrival_time": 0.5, "prefill_length": 150, "decode_length": 30},
    # ... more requests
]

with open("custom_requests.csv", "w") as f:
    writer = csv.DictWriter(f, fieldnames=["arrival_time", "prefill_length", "decode_length"])
    writer.writeheader()
    writer.writerows(requests)
```

### Modifying Control Policies
Edit `control/advanced_policy.py` to implement custom scheduling or preemption strategies.

### Analyzing Results
Use pandas to analyze CSV outputs:
```python
import pandas as pd

# Find the latest experiment directory
import glob
import os

exp_dirs = glob.glob("data/experiments/experiment_*")
latest_exp = max(exp_dirs, key=os.path.getmtime)

# Load and analyze results
traces = pd.read_csv(f"{latest_exp}/request_traces.csv")
print(f"Average latency: {traces['total_delay'].mean():.2f}")
print(f"P95 latency: {traces['total_delay'].quantile(0.95):.2f}")
print(f"Swap rate: {(traces['swap_count'] > 0).mean():.2%}")
print(f"Sacrifice rate: {(traces['sacrifice_count'] > 0).mean():.2%}")
```

## Project Structure

```
fluid_ode_simulation/
├── config/              # Configuration files
│   ├── config.yaml          # Main configuration (supports 4 strategy combinations)
│   └── advanced_test.yaml   # Test configuration (smaller parameters)
├── core/               # Core data structures
│   ├── request.py      # Request class
│   └── system_state.py # System state management
├── simulation/         # Simulation engine
│   ├── vllm_simulator.py      # Unified simulator (supports all 4 strategy combinations)
│   └── event_logger.py        # Event logging and CSV output
├── control/            # Control policies
│   ├── base_policy.py         # Policy base class
│   └── advanced_policy.py     # Advanced policy (implements 4 combinations)
├── data/              
│   ├── input/         # Input data generation
│   │   └── generate_requests.py
│   └── experiments/   # Experiment results
│       └── experiment_*  # Timestamped experiment directories
├── experiments/        # Experiment scripts
│   ├── run_advanced.py        # Main run script
│   └── test_all_strategies.py # Test all strategy combinations
├── visualization/      # Plotting tools
│   └── plot_dynamics.py
├── scripts/           # Shell scripts
│   ├── clean.sh             # Cleanup script
│   └── manage_experiments.sh # Experiment management tool
└── CLAUDE.md          # Detailed technical documentation
```

## Troubleshooting

### Common Issues

1. **How to choose strategy combination?**
   - **swap + conservative**: Stable load, long requests
   - **swap + aggressive**: Balanced performance, vLLM default
   - **sacrifice + conservative**: Short requests, simple and efficient
   - **sacrifice + aggressive**: Burst load, strict priorities

2. **Difference between batch_count and running_count?**
   - `batch_count`: Actually executed requests (constrained by B)
   - `running_count`: All requests in GPU memory
   - Relationship: `batch_count ≤ running_count`

3. **Memory overflow**: Reduce `B` parameter or increase `M_total` in config

4. **Slow simulation**: Reduce number of requests or increase arrival intervals

### Performance Tips

- For large-scale experiments, disable verbose output
- Use binary search for parameter tuning
- Monitor `data/experiments/*/summary.txt` for quick metrics
- Adjust `progress_interval` for less frequent updates

## References

- **CLAUDE.md**: Complete technical documentation with ODE equations
- **fluid_modeling.tex**: Theoretical fluid model derivation
- Related papers: PagedAttention, vLLM, SGLang

## License

This project is for research and educational purposes.