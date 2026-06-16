[![English](https://img.shields.io/badge/lang-English-blue)](README.md)

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

### 不调用 LLM，先检查输入文件

```bash
promptdiff validate prompt_a.txt tests.jsonl --min-cases 5
```

这个命令会先确认 prompt 非空，并检查 JSON / JSONL / YAML 测试用例是否都有合法的 `input` 字段，避免 CI 还没发现数据坏了就先花钱调用模型。

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

如果允许少量变化，但要严格控制回归比例、延迟和 token 成本，可以直接设置预算门禁：

```bash
promptdiff compare prompt_a.txt prompt_b.txt tests.jsonl \
  --max-regression-rate 0.05 \
  --min-avg-similarity 0.90 \
  --max-error-rate 0.01 \
  --max-avg-latency-increase 150 \
  --max-avg-token-increase 20 \
  --json-output results.json
```

任一预算超标时命令会返回退出码 1，JSON 结果里也会记录具体失败原因。

### 生成 Markdown 报告贴到 PR

把保存下来的结果文件转成一份 Markdown 摘要，可以直接贴进 PR comment 或作为 CI 产物上传。这一步完全离线，不会再调用模型：

```bash
promptdiff compare prompt_a.txt prompt_b.txt tests.jsonl -o results.json
promptdiff report results.json -o report.md
```

不加 `--output` 时报告直接打到 stdout，方便接到 `gh pr comment` 这类步骤里。报告包含一张汇总表、预算门禁的结论，以及按严重程度排序的最差 case。用 `--top` 控制最多列出几条。

### 先看最危险的 case

终端报告默认按严重程度排序：先显示 prompt 运行错误，再显示相似度最低的回归 case，然后才是改进和未变化的 case。这样 review 时不用从几十条样例里自己找重点。如果你想保留测试用例原始顺序：

```bash
promptdiff compare prompt_a.txt prompt_b.txt tests.jsonl --sort input
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
