# SqlGraph

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![SQLGlot](https://img.shields.io/badge/parser-SQLGlot-green.svg)](https://github.com/tobymao/sqlglot)

> ## 🚧 本仓库正在改造中
>
> 源代码已**临时下线**，SqlGraph 正在准备以 **字节跳动开源组织** 的形式对外发布。
>
> 迁移完成后，完整实现将重新发布到此处。感谢你的耐心，敬请稍后再来查看。

[English](README.md) | 简体中文

---

**把数据仓库 SQL 加工成一张可交互的知识图谱。**

SqlGraph 通过静态解析一整个目录的 SQL，构建出一张属性图。它不仅刻画 *表/字段血缘*，更把 **SQL 语句与加工逻辑本身** 建模为图节点。跨 SQL 的相同逻辑会通过内容指纹识别，并且只有在输出字段语义一致时才会收敛 —— 让你一眼看清仓库里哪些计算被重复使用，同时避免误合并不同指标别名。

## SqlGraph 能做什么

- **表达式级知识图谱** —— SQL 文件、表、字段、加工逻辑都是一等图节点。
- **相同逻辑自动去重** —— 相同表达式共享 128 位内容指纹，Transform 节点按 `表达式指纹 + 输出字段名` 合并。
- **物理列精确依赖** —— 每个转换节点都精确连接它读取的物理列与产出的输出列。
- **图友好输出** —— 可导出 HTML、CSV、JSON、GraphRAG 载荷与 NetworkX，服务下游分析与 AI 工作流。

## 当前状态

代码正在为字节跳动开源发布进行改造。文档、安装说明与示例将随源代码重新发布一并回归。

## 许可证

[Apache 2.0](LICENSE)
