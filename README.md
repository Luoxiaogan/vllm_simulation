# Fluid ODE Simulation for LLM Serving

A simulation system for modeling LLM serving with fluid ODEs in the Operations Research framework.

## Quick Start

```bash
# 1. Generate test data
python data/input/generate_requests.py

# 2. Run swapping mode simulation
python experiments/run_swapping.py

# 3. Generate visualizations
python visualization/plot_dynamics.py

# Or use the all-in-one script
bash scripts/run_basic.sh
```

## System Parameters

### Core System Configuration (`config/config.yaml`)

#### System Parameters
- **`mode`** (string): Server mode - `"swapping"` or `"sacrifice"` (currently only swapping is implemented)
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
- **`queue_policy`** (string): Queue scheduling policy
  - `"FCFS"`: First-Come-First-Served (default)
  - `"priority"`: Priority-based scheduling (future)
- **`victim_policy`** (string): Swap victim selection policy
  - `"LIFO"`: Last-In-First-Out based on enter_running_time (default)
  - `"FIFO"`: First-In-First-Out
  - `"random"`: Random selection
  - `"LRU"`: Least Recently Used (future)
- **`batch_priority`** (string): Batch construction priority
  - `"standard"`: RUNNING > SWAPPED > WAITING (default)

#### Data Configuration
- **`request_file`** (string): Input request CSV file path
- **`output_dir`** (string): Output directory for results
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

All output files are saved in `data/output/` directory:

### 1. **batch_snapshots.csv**
System state after each batch execution:
- `time`: Cumulative simulation time
- `batch_id`: Unique batch identifier
- `batch_size`: Number of requests in batch
- `batch_tokens`: Total tokens in batch
- `batch_duration`: Execution time of this batch
- `waiting_count`: Requests in waiting queue
- `running_count`: Requests currently running
- `swapped_count`: Requests swapped to CPU
- `completed_count`: Total completed requests
- `gpu_memory_used`: Current GPU memory usage
- `memory_utilization`: GPU memory utilization ratio

### 2. **request_traces.csv**
Complete lifecycle trace for each request:
- `req_id`: Unique request identifier
- `arrival_time`: When request arrived at decode node
- `prefill_length`: Size of prefill KV cache
- `decode_length`: Number of tokens to decode
- `completion_time`: When request completed (or NaN if not completed)
- `first_enter_running_time`: First time entering RUNNING state
- `waiting_time`: Time spent in WAITING state
- `execution_time`: Total time in RUNNING state
- `swap_count`: Number of times swapped out
- `total_delay`: End-to-end latency

### 3. **events.csv**
Detailed event log:
- `time`: Event timestamp
- `event_type`: Type of event (admit, swap_out, swap_in, complete)
- `req_id`: Request involved
- `details`: Additional event information

### 4. **memory_events.csv**
Memory management events:
- `time`: Event timestamp
- `event_type`: swap_out or swap_in
- `req_id`: Request being swapped
- `memory_before`: GPU memory before event
- `memory_after`: GPU memory after event
- `reason`: Why swap occurred

### 5. **summary.txt**
Human-readable summary report with:
- Basic statistics (total time, batches, completions)
- System statistics (queue lengths, swap counts)
- Performance metrics (throughput, latency, utilization)

## Usage Examples

### Basic Simulation
```bash
# Generate standard load and run simulation
python data/input/generate_requests.py --num_requests 100
python experiments/run_swapping.py
python visualization/plot_dynamics.py
```

### High Load Testing
```bash
# Generate heavy load scenario
python data/input/generate_requests.py --scenario heavy --num_requests 200
python experiments/run_swapping.py --requests data/input/requests.csv
```

### Parameter Tuning
```bash
# Edit config/config.yaml to modify parameters, then run:
python experiments/run_swapping.py --config config/config.yaml
```

### Batch Experiments
```bash
# Run experiments with different parameters
bash scripts/run_experiments.sh

# Compare different scenarios
bash scripts/run_scenarios.sh

# Full pipeline with cleanup
bash scripts/run_full_pipeline.sh
```

## Shell Scripts

Located in `scripts/` directory:

- **`run_basic.sh`**: Standard workflow (generate → simulate → visualize)
- **`run_experiments.sh`**: Parameter sweep experiments
- **`run_scenarios.sh`**: Compare normal/heavy/bursty scenarios
- **`run_full_pipeline.sh`**: Complete pipeline with all analyses
- **`clean.sh`**: Clean output directory

All scripts support parameter modification by editing the script files directly.

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
Edit `control/default_policy.py` to implement custom scheduling or swapping strategies.

### Analyzing Results
Use pandas to analyze CSV outputs:
```python
import pandas as pd

# Load and analyze results
traces = pd.read_csv("data/output/request_traces.csv")
print(f"Average latency: {traces['total_delay'].mean():.2f}")
print(f"P95 latency: {traces['total_delay'].quantile(0.95):.2f}")
print(f"Swap rate: {(traces['swap_count'] > 0).mean():.2%}")
```

## Project Structure

```
fluid_ode_simulation/
├── config/              # Configuration files
│   └── config.yaml     # Main configuration
├── core/               # Core data structures
│   ├── request.py      # Request class
│   └── system_state.py # System state management
├── simulation/         # Simulation engine
│   ├── vllm_simulator.py      # Main simulator (supports swap & sacrifice)
│   └── event_logger.py        # Event logging
├── control/            # Control policies
│   └── default_policy.py      # FCFS + LIFO policy
├── data/              
│   ├── input/         # Input data generation
│   │   └── generate_requests.py
│   └── output/        # Simulation outputs
├── experiments/        # Experiment scripts
│   └── run_swapping.py
├── visualization/      # Plotting tools
│   └── plot_dynamics.py
├── scripts/           # Shell scripts for automation
└── CLAUDE.md          # Detailed technical documentation
```

## Troubleshooting

### Common Issues

1. **Negative waiting times**: Fixed in current version - requests now properly wait for their arrival time

2. **No swap_in events**: Known issue - swap restoration mechanism needs tuning

3. **Memory overflow**: Reduce `B` parameter or increase `M_total` in config

4. **Slow simulation**: Reduce number of requests or increase arrival intervals

### Performance Tips

- For large-scale experiments, disable verbose output
- Use binary search for parameter tuning
- Monitor `data/output/summary.txt` for quick metrics
- Adjust `progress_interval` for less frequent updates

## References

- **CLAUDE.md**: Complete technical documentation with ODE equations
- **fluid_modeling.tex**: Theoretical fluid model derivation
- Related papers: PagedAttention, vLLM, SGLang

## License

This project is for research and educational purposes.