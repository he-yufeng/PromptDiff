<div align="center">

<img src="docs/banner.png" alt="PromptDiff — LLM prompt 的语义 diff" width="100%">

[![Python](https://img.shields.io/badge/python-3.10+-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![CI](https://github.com/he-yufeng/PromptDiff/actions/workflows/ci.yml/badge.svg)](https://github.com/he-yufeng/PromptDiff/actions)

[**快速开始**](#快速开始) · [**用法**](#用法) · [English](README.md)

</div>

<p align="center"><img src="docs/demo.png" alt="promptdiff compare" width="620"></p>

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

想要 JUnit XML 接测试看板？加 `--format junit` 就能从同一份已存结果重新生成，不调用模型、不必为同一次对比再花一次钱：

```bash
promptdiff report results.json --format junit -o junit.xml
```

`report --check` 会重新套用 compare 时记录的回归预算，预算没过就以非零码退出。这样可以让一个 CI job 跑较贵的 `compare` 并上传 `results.json`，再让后面一个便宜的 job 离线发评论 + 卡门禁：

```bash
promptdiff report results.json -o report.md --check   # 预算没过则退出 1
```

每条回归还会标上严重程度，一眼就能区分"擦边变化"和"整段重写"。等级取决于输出相似度比该次运行的阈值低多少：minor（刚刚低于）、moderate、major；运行报错一律算 major。报告里既有每条 case 的等级，也有一行汇总，比如 `Severity: 1 major, 2 moderate`。阈值会写进结果 JSON，所以 `report` 离线也能还原出同样的等级。

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

## 后续规划

「跨测试用例做 A/B」这条主线已经稳定，接下来想做更宽的对比和更顺的评审：

- **多版本扫描**：一次运行里对比两个以上 prompt（v1 vs v2 vs v3），出一张矩阵报告，调优时不必局限于两两对比。
- **成对裁判模式**：让 LLM 裁判逐个 case 两两选出赢家，而不是各自和阈值比较——对主观质量更稳。
- **可插拔相似度后端**：在 sentence-transformers 和 Jaccard 之外，允许自定义打分器（embedding API 或领域指标），应对两种默认都不合适的输出。
- **GitHub Action**：一个现成 action，在 prompt 文件变更时跑 PromptDiff 并把 Markdown 报告贴成 PR 评论，让 prompt 改动像代码一样被评审。

## 开发

```bash
git clone https://github.com/he-yufeng/PromptDiff.git
cd PromptDiff
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,semantic]"
pytest
```

## 相关项目

PromptDiff 是我用来盯 prompt 改动的工具之一，下面是几个相关的：

- **[CoreCoder](https://github.com/he-yufeng/CoreCoder)** — 想搞懂一个 coding agent 到底怎么运作？把整套约 1000 行引擎从头读到尾，而不是当黑箱。
- **[RepoWiki](https://github.com/he-yufeng/RepoWiki)** — 被丢进一个陌生代码库？它给你一份带「从哪读起」路径的 wiki，一个可自托管的 DeepWiki 替代。
- **[LiteBench](https://github.com/he-yufeng/LiteBench)** — 一条命令给任意 LLM 跑基准：内置 HumanEval、GSM8K、MMLU，也能加你自己的任务。
- **[FlightBox](https://github.com/he-yufeng/FlightBox)** — 让不确定的 LLM 调用变得可复现：录一次，在测试里回放和比对。

## 许可证

MIT
