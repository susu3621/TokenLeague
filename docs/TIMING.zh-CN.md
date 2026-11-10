# 项目与会话耗时分析

入口：`/timing`。管理员可查看全员，普通用户只查看本人；用户详情页也提供 `/users/<id>/timing` 的个人入口。

可按时间窗口、自定义 UTC 日期、项目、会话、Agent、模型筛选，点击项目和会话继续下钻。项目、会话、工具、慢轮次四个表格均支持表头排序、上一页、下一页、页码提示和直接跳页。筛选、排序、分页保存在 URL 中，可分享链接或使用浏览器前进、后退。

原有排行榜、用户详情和管理表格也提供表头排序与分页。Token 缩写仅用于展示，排序使用原始计数；动态刷新数据后会重新应用排序和分页。

## 数字表示什么

- **轮次耗时**：从一次真实用户提问到该轮回答结束。Claude 的工具结果不会被算成新提问，同一轮的多条回答也不会重复累加。只采集已完成轮次。
- **P50 / P95**：完整落在所选窗口内的轮次耗时分位数，使用最近秩法；缺失样本不补零。P95 是观察长尾的入口，不能单独证明某个工具是根因。
- **累计执行时间**：所有已完成轮次与时间窗口交集的时长之和。多会话并行会累加。
- **去重活跃时间**：合并重叠区间后，只计一次的活跃时长。累计执行时间除以它，得到有效并发度。它表示记录到的 Agent 活动重叠程度，不是人类节省时间或硬件并行度。
- **会话间隙**：同一会话内最早轮次开始与最晚轮次结束之间，未被已记录轮次覆盖的部分。单独展示，不计入执行耗时，也不能当作测得的人工等待。
- **首 Token 延迟**：仅使用日志明确给出的 `time_to_first_token_ms`。首条消息的写入时间不能替代首 Token 时间。
- **工具归属耗时**：原生模型与工具计时优先于封装调用和模型间隔估算；同级重叠工具等分归属，各分项合计等于累计执行时间。原始调用延迟独立统计，可能包含审批等待或嵌套封装，不能直接相加。
- **计时覆盖**：已计时会话与既有 Token 会话的并集作为已观测会话。历史记录没有计时时，标为待补录，不会用整段会话跨度推算执行时间。

## 来源差异

Codex 优先使用 `task_complete.duration_ms`；没有该字段时，从匹配的 `task_started` 与 `task_complete` 时间戳估算。首 Token 延迟只在日志明确提供时统计。

新版 Codex 日志的 `event_msg.item_completed` 包含 `started_at_ms`、`completed_at_ms` 和原生活动类型，能够统计终端命令、MCP 调用、文件修改、等待、网络访问和上下文压缩。同一调用若同时出现在原生事件和调用/返回记录里，会去重；嵌套编排区间的归属优先级低于原生执行区间。

旧日志可按 `call_id` 配对 `function_call` / `custom_tool_call` 与对应输出，得到调用到返回的区间，不解析工具输出文本里的耗时。模型事件之间的区间只作为估算，可能包含请求、调度和网络延迟，不等同于纯模型计算时间；它们不会覆盖已经测得的工具区间。缺少可归属证据的剩余时间仍保留为未观测。

这些指标描述活动的墙钟区间；后台任务可能与模型活动并行。归属占比可用于定位排查方向，不能单独证明 CPU 瓶颈或阻塞路径。

Claude 按真实用户提问划分轮次，以最终回答的时间戳结束。通过 `tool_use.id` 与 `tool_result.tool_use_id` 配对工具区间。内容块之间的时间可估算思考、回答生成、工具调用生成；首个内容块包含请求延迟，并非纯模型计算时间。没有结果的工具调用和未结束的轮次不伪装成完成记录。主会话中的 sidechain 记录不会混入主轮次。

其他 Agent 的旧 Token 数据仍正常统计，本次先为 Codex 与 Claude 提供计时采集；未接入来源通过覆盖情况显示，避免把未知当作零耗时。

方法参考：[agent-usage-analyzer](https://github.com/daguix/agent-usage-analyzer)，尤其是最近秩分位数、重叠区间合并与并发工具归属思路。此实现直接解析 TokenLeague 的本地日志，不需要安装该 CLI。

## 启用与补录

先部署服务并执行迁移，再升级客户端 Hook：

```bash
python3 scripts/run_migrations.py
bash scripts/install_hooks.sh --codex --claude --global
```

迁移 `007_add_turn_timings.py` 新增独立的 `turn_timings` 表和查询索引；不修改原有 Token 记录。客户端安装脚本同时复制共用计时解析模块。团队中每台开发机都需更新 Hook。

历史补录使用已有环境变量 `TOKENLEAGUE_API_URL` 与当前用户的 `TOKENLEAGUE_HOOK_KEY`。先本地预览，再上传：

```bash
python3 scripts/backfill_timing.py --source all --dry-run
python3 scripts/backfill_timing.py --source all
```

如果曾用旧版脚本补录后，Codex 项目全部显示为未观测，更新仓库后重新执行相同命令即可补充明细。也可以只处理一个项目：

```bash
python3 scripts/backfill_timing.py --source codex --project-name data-platform
```

计时解析版本随记录保存；旧版 Hook 或脚本不会覆盖新版已经补全的明细。更新 Hook 后，新轮次会自动使用新解析器。

可使用 `--source codex|claude|all`、`--days 7`、`--limit 10`、`--codex-root PATH`、`--claude-root PATH`。`--days` 只筛选文件的修改时间，不截断文件中的历史轮次。Claude 支持 `$CLAUDE_CONFIG_DIR/projects`；子 Agent 文件以自身文件 ID 单独计为会话。

计时补录只写 `/api/ingest/turn-timing`，不重放 Token。记录以用户、Agent、会话、轮次联合标识 upsert，相同历史重复补录不会增加次数。一次写入失败会停止本次补录，不在同次运行中自动重发。

上传字段仅包含会话/轮次/项目/模型标识、版本、时间戳、工具名称、固定工具类别以及计时来源；不上传 Prompt、回答、原始命令、命令参数、文件路径或工具输出。只报告元数据和解析汇总。

## API

- `POST /api/ingest/turn-timing`：使用 `X-Hook-Key` 上报完整轮次，严格校验区间和非负数值。
- `GET /api/timing`：登录后查看当前权限范围的汇总、分布和计时覆盖。
- `GET /api/users/<id>/timing`：查看本人或管理员授权范围内的个人报告。
- `view=projects|sessions|tools|turns`：增加对应表格；支持 `sort`、`order=asc|desc`、`page`、`page_size`（最多 100）。
- 时间筛选支持 `window=today|week|month|quarter|all`，或成对提供 `from`、`to` 的 ISO 时间戳，使用左闭右开区间。页面的结束日期包含整天，转换为次日 UTC 00:00 的 API 上界。
- 维度筛选支持 `project_name`、`session_id`、`agent_type`、`agent_version`、`model_name`。管理员可用 `user_id` 限定成员；普通用户不能扩大自己的范围。

采集记录的完整耗时供慢轮次查询；若轮次跨越窗口，活动时长按交集统计，但该轮次不进入 P50、P95 与分布样本。工具调用的样本数按窗口内开始的调用计算，延迟分位数仅用窗口内完整调用。
