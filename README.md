# PromptDiff

**Semantic diff for LLM prompts** — compare prompt versions like `git diff`, but for behavior.

You changed your system prompt. Did it make things better or worse? PromptDiff runs both versions against your test cases, compares the outputs semantically, and tells you exactly what changed.

## Why PromptDiff?

Prompt engineering is iterative. You tweak a word, add an instruction, restructure the format — but how do you know if it actually helped? Manual A/B testing is slow and error-prone. PromptDiff automates the comparison:

- **Run both prompt versions** against the same test inputs through any OpenAI-compatible API
- **Semantic comparison** using sentence embeddings (or lexical fallback) to detect behavioral changes
- **LLM-as-judge** (optional) to classify changes as improvements or regressions
- **CI-friendly** — exit code 1 on regressions, JSON output for automation
- **Rich terminal reports** with color-coded diffs, similarity scores, latency/token deltas

## Installation

```bash
pip install promptdiff

# with semantic similarity (recommended)
pip install "promptdiff[semantic]"
```

## Quick Start

Create two prompt files and a test cases file:

```bash
# prompt_v1.txt
You are a helpful coding assistant. Answer clearly and concisely.

# prompt_v2.txt
You are a senior engineer. Answer step by step. Always include code examples.

# test_cases.jsonl
{"input": "How do I reverse a string in Python?"}
{"input": "What's the difference between a list and a tuple?"}
{"input": "Explain closures."}
```

Run the comparison:

```bash
promptdiff compare prompt_v1.txt prompt_v2.txt test_cases.jsonl
```

Output:

```
┌─────────────────── PromptDiff Summary ───────────────────┐
│ 3 cases: 1 unchanged, 2 regressed                       │
│ avg similarity: 72.31%  |  avg latency delta: +45ms  |  │
│ avg token delta: +38                                     │
└──────────────────────────────────────────────────────────-┘

 #  │   │ Input                                │ Similarity │ Latency │ Tokens
  2 │ - │ What's the difference between a li... │     65.2%  │  +120ms │   +52
  3 │ - │ Explain closures.                     │     71.8%  │   +30ms │   +41
```

## Usage

### Basic comparison

```bash
promptdiff compare prompt_a.txt prompt_b.txt tests.jsonl
```

### With LLM-as-judge

When outputs differ, use an LLM judge to decide if the change is an improvement or regression:

```bash
promptdiff compare prompt_a.txt prompt_b.txt tests.jsonl --judge
```

### Custom model / API

Works with any OpenAI-compatible API (Ollama, vLLM, LiteLLM, Together, etc.):

```bash
promptdiff compare prompt_a.txt prompt_b.txt tests.jsonl \
  --model llama-3.1-8b \
  --base-url http://localhost:11434/v1
```

### CI integration

Fail the build if any regressions are detected:

```bash
promptdiff compare prompt_a.txt prompt_b.txt tests.jsonl \
  --fail-on-regression --json-output results.json
```

### Adjust sensitivity

Lower threshold = more permissive (fewer false regressions):

```bash
promptdiff compare prompt_a.txt prompt_b.txt tests.jsonl --threshold 0.7
```

### All options

```
Options:
  -m, --model TEXT          Model for running prompts (default: gpt-4o-mini)
  --base-url TEXT           Custom API base URL
  --api-key TEXT            API key (default: OPENAI_API_KEY env)
  -t, --threshold FLOAT     Similarity threshold for 'unchanged' (default: 0.85)
  --judge / --no-judge      Use LLM-as-judge for changed cases
  --judge-model TEXT        Judge model (default: gpt-4o-mini)
  -v, --verbose             Show detailed output for changed cases
  --show-unchanged          Include unchanged cases in report
  -o, --json-output PATH    Write JSON results to file
  -c, --concurrency INT     Max concurrent API calls (default: 5)
  --no-semantic             Use lexical similarity instead of embeddings
  --fail-on-regression      Exit code 1 if regressions found
```

## Test Case Formats

PromptDiff supports multiple formats for test inputs:

| Format | Example |
|--------|---------|
| `.jsonl` | `{"input": "your question"}` per line |
| `.json` | `["q1", "q2"]` or `[{"input": "q1"}]` |
| `.yaml` | List of strings or objects with `input` key |
| `.txt` | One test case per line |

## Python API

```python
import asyncio
from promptdiff import PromptRunner, PromptDiff, DiffReport
from promptdiff.runner import RunConfig

config = RunConfig(model="gpt-4o-mini")
runner = PromptRunner(config)

prompt_a = "You are helpful."
prompt_b = "You are a senior engineer. Be detailed."
inputs = ["How do I sort a list in Python?", "What is a mutex?"]

results_a = asyncio.run(runner.run_batch(prompt_a, inputs))
results_b = asyncio.run(runner.run_batch(prompt_b, inputs))

differ = PromptDiff(threshold=0.85)
diffs, summary = differ.compare_batch(results_a, results_b)

report = DiffReport()
report.print_full(diffs, summary, verbose=True)
```

## How It Works

1. **Run**: Both prompts are sent to the LLM with each test input (concurrently, with rate limiting)
2. **Compare**: Outputs are compared using semantic similarity (sentence-transformers) or lexical similarity (Jaccard)
3. **Classify**: Cases below the similarity threshold are marked as "changed". Optionally, an LLM judge decides if the change is an improvement or regression
4. **Report**: Results are displayed with color-coded terminal output and optional JSON export

## Development

```bash
git clone https://github.com/he-yufeng/PromptDiff.git
cd PromptDiff
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,semantic]"
pytest
```

## License

MIT

---

# PromptDiff

**LLM prompt 的语义 diff 工具** — 像 `git diff` 一样对比 prompt 版本，但比较的是行为。

你改了 system prompt，效果是变好了还是变差了？PromptDiff 把两个版本的 prompt 跑同一组测试用例，语义级别对比输出差异，告诉你到底改了什么。

## 为什么需要 PromptDiff？

Prompt 工程是个反复迭代的过程。改个措辞、加个指令、调整格式 — 但怎么知道改完是变好了？手动 A/B 测试又慢又容易出错。PromptDiff 自动化这个对比过程：

- **双版本并发执行** — 同一组测试输入，通过任何 OpenAI 兼容 API 运行两个 prompt 版本
- **语义级对比** — 用 sentence-transformers 向量余弦相似度检测行为变化（也支持词法 fallback）
- **LLM 裁判** — 可选功能，用另一个 LLM 判断变化是改进还是退步
- **CI 友好** — 检测到退步时退出码为 1，支持 JSON 输出供自动化流程使用
- **Rich 终端报告** — 彩色差异表、相似度分数、延迟/token 变化一目了然

## 安装

```bash
pip install promptdiff

# 带语义相似度（推荐）
pip install "promptdiff[semantic]"
```

## 快速开始

准备两个 prompt 文件和一个测试用例文件：

```bash
# prompt_v1.txt
你是一个编程助手，简洁地回答问题。

# prompt_v2.txt
你是一个资深工程师，分步骤回答问题，务必包含代码示例。

# test_cases.jsonl
{"input": "Python 怎么反转字符串？"}
{"input": "list 和 tuple 有什么区别？"}
{"input": "解释一下闭包。"}
```

运行对比：

```bash
promptdiff compare prompt_v1.txt prompt_v2.txt test_cases.jsonl
```

## 用法

### 基本对比

```bash
promptdiff compare prompt_a.txt prompt_b.txt tests.jsonl
```

### 使用 LLM 裁判

当输出有差异时，让 LLM 判断变化是改进还是退步：

```bash
promptdiff compare prompt_a.txt prompt_b.txt tests.jsonl --judge
```

### 自定义模型 / API

支持任何 OpenAI 兼容 API（Ollama、vLLM、LiteLLM、Together 等）：

```bash
promptdiff compare prompt_a.txt prompt_b.txt tests.jsonl \
  --model llama-3.1-8b \
  --base-url http://localhost:11434/v1
```

### CI 集成

检测到退步时让构建失败：

```bash
promptdiff compare prompt_a.txt prompt_b.txt tests.jsonl \
  --fail-on-regression --json-output results.json
```

## 测试用例格式

| 格式 | 示例 |
|------|------|
| `.jsonl` | 每行一个 `{"input": "你的问题"}` |
| `.json` | `["q1", "q2"]` 或 `[{"input": "q1"}]` |
| `.yaml` | 字符串列表或含 `input` 键的对象列表 |
| `.txt` | 每行一个测试用例 |

## Python API

```python
import asyncio
from promptdiff import PromptRunner, PromptDiff, DiffReport
from promptdiff.runner import RunConfig

config = RunConfig(model="gpt-4o-mini")
runner = PromptRunner(config)

prompt_a = "你是一个编程助手。"
prompt_b = "你是一个资深工程师，回答要详细。"
inputs = ["Python 怎么排序？", "什么是互斥锁？"]

results_a = asyncio.run(runner.run_batch(prompt_a, inputs))
results_b = asyncio.run(runner.run_batch(prompt_b, inputs))

differ = PromptDiff(threshold=0.85)
diffs, summary = differ.compare_batch(results_a, results_b)

report = DiffReport()
report.print_full(diffs, summary, verbose=True)
```

## 工作原理

1. **执行**: 两个 prompt 分别与每个测试输入并发发送给 LLM（带并发控制）
2. **对比**: 用语义相似度（sentence-transformers）或词法相似度（Jaccard）比较输出
3. **分类**: 低于阈值的标记为"变化"，可选 LLM 裁判判断是改进还是退步
4. **报告**: 彩色终端输出 + 可选 JSON 导出

## 开发

```bash
git clone https://github.com/he-yufeng/PromptDiff.git
cd PromptDiff
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,semantic]"
pytest
```

## 许可证

MIT
