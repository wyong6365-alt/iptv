# 广川AI智能工程量清单识别与自主组价平台 V1.0

研发单位：山东广川建设工程有限公司

当前阶段：第一阶段平台基础和山东省建设工程计价引擎已完成并通过测试；界面、文件识别、定额匹配、导出尚未开发。

## 运行后端

```
cd backend
pip install -e ".[dev]"
python -m pytest          # 运行测试
python -m gcpricing       # 启动服务，接口文档 http://127.0.0.1:8765/docs
```

首次启动后调用 `POST /api/auth/setup` 创建管理员。数据默认保存在用户目录下的 `.gcpricing/`。

## 设计文件

| 文件 | 内容 |
| --- | --- |
| [docs/01-architecture.md](docs/01-architecture.md) | 全专业架构设计：平台底座、专业适配器、清单保护、不可竞争费用锁定、计价引擎、AI 匹配、数据库、研发阶段 |
| [docs/02-capability-matrix.md](docs/02-capability-matrix.md) | 专业能力矩阵：16 个专业 × 11 项能力，状态判定规则，V1.0 目标 |
| [docs/03-quota-data-plan.md](docs/03-quota-data-plan.md) | 定额数据规划：计价体系族、候选计价依据清单、导入与校验流程、数据合法性 |
| [docs/04-test-plan.md](docs/04-test-plan.md) | 真实项目测试方案：样本要求、对照基准、指标、与第十七章验收标准的对应 |

已确认事项和遗留问题见 [01-architecture.md 第 14 节](docs/01-architecture.md#14-已确认事项与遗留问题)。
