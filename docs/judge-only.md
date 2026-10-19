# 独立仿真与精选官测

默认路径是 ConfusionMulGrad / judge-only：无需 SSH 或物理 NPU，但真实独立仿真仍需 Linux/CANN Worker。面板预演不需要这些环境。

## 从空工程开始

按 README 运行官方模板导入工具，再启动服务。模板按逐文件 SHA256 校验，保留 34 文件工程和 7 文件编辑清单。模板变化时导入器拒绝覆盖，需先人工核验新版本；不要更新哈希以掩盖差异。官方模板仅在本机使用，不随源码发行。

每队独立生成、编译、验证和修正，然后学习公开方法。学习后的代码需要重新仿真。团队模型工作、仿真队列、官测彼此独立；默认 4 个模型任务并发和 1 个仿真槽位，队伍无需整批结束。

实验提交后最多等待 `AWORKER_LAB_SIMULATION_WAIT_SECONDS`（默认 2 秒），未结束则返回 `pending=true` 和真实任务 ID。团队简短报告排队并结束本轮，释放模型槽给其他队；后台继续仿真，调度器在本队实验结束后安排读取反馈。排队回执不代表通过，重试会复用本队正在进行的任务。

## 已接入的 Worker 与实验工具

工作台 Python 3.13 与 CANN Worker 的 Python 分开管理；已验收环境为 Ubuntu 22.04 / WSL2、CANN 9.0.0 和 Ascend910B4 仿真库。不安装或分发 NPU 驱动。安装 CANN 前应自行阅读并接受其许可；不要把 CANN 安装器和二进制加入 Git。

检查环境：

```sh
python3 tools/check_simulator_environment.py --output /tmp/justkernel-preflight.json
```

在 Linux 安装匹配的 CANN Toolkit、910B ops / simulator 库及编译依赖，为 Worker 建立独立 Python 环境并安装 NumPy 与固定版本的 CPU PyTorch。功能参照使用题面的 FP32 PyTorch 运算；大归约时不能用 NumPy 的不同求和顺序替代并据此判错。独立 Worker 的 Python 需兼容 CANN；工作台本身仍要求 Python 3.13+。

```sh
uv pip install --python PYTHON 'numpy>=2,<3'
uv pip install --python PYTHON 'torch==2.14.1+cpu' --index-url https://download.pytorch.org/whl/cpu
```

Linux x86_64 的工作台环境也可用 `uv sync --locked --extra simulator` 安装可选依赖；普通面板及预演不需要 PyTorch。按实际 CANN 版本完成官方环境配置，再运行：

```sh
bash tools/start_simulator_worker.sh LINUX_ROOT CANN_ROOT PYTHON SHARED_SPOOL 2
```

最后的 `2` 是并行实验槽数（1–8，省略默认 1），允许不同团队重叠编译和准备。**性能采集始终只有 1 槽**：官方工具不支持在同一个 Device 同时拉起多个采集任务，不能将实验槽数当作性能仿真并行数。等待采集锁的时间不计入实验执行预算；它也不是 NPU 耗时。进一步并行采集需要独立并经过验证的 Device 环境。参见 [官方约束](https://github.com/Ascend/msopprof/blob/master/docs/zh/user_guide/msopprof_simulator_user_guide.md)。

新流水线重复运行启动器可更新实验槽数，正在执行的实验自然收尾；`pool-control.json` 保存实际容量。旧 Worker 需要一次受控交接，保留未完成回执并按原冻结源码重排。面板区分排队、编译、等待采集和执行用例。调度器与测量适配器分别记录 SHA256；测量或校验代码改变后，旧证据不再满足新版本送测门槛。

默认实验分两段：全部选定输入运行 PVModel 功能仿真并校验两个输出；全部通过后，按输入包固定选择每种归约轴类别中元素数最少的一个代表点，运行 CAModel / `msopprof` 详细性能采集。代表点由控制器决定，团队不能通过只挑简单点来通过完整送测门槛。不同团队的功能仿真可以并行，详细性能采集仍共用一个独占槽。

功能仿真默认每点最多 **1800 秒**、整次实验最多 **3600 秒**，可在本机 `.env` 分别配置 `AWORKER_LAB_SIMULATION_CASE_TIMEOUT_SECONDS` 和 `AWORKER_LAB_SIMULATION_TIMEOUT_SECONDS`（30–3600 秒）。这是 CPU 上的墙钟执行预算，不是 NPU 耗时；大输入不再因统一的 600 秒限制而反复被中止。总体预算始终优先，超时仍记为失败，输入、精度校验和完整送测门槛不变。编译和详细性能采集的单阶段上限仍为 600 秒。预算随请求冻结，旧请求保留原预算；升级启动器后正常重启工作台与 Linux Worker，新请求才使用新默认值。

参数使用实际绝对路径。`LINUX_ROOT` 是原始构建、仿真输出、缓存和临时文件目录；`CANN_ROOT` 是 CANN 根目录；`PYTHON` 是兼容 CANN 的独立 Python。`SHARED_SPOOL` 对应工作台 `.justkernel/simulator`，Windows / WSL 通过同一个目录交换请求和回执。具体布局以面板的环境状态和 Worker 诊断为准。新目录不自动迁移旧记录，重复启动保留正在运行的 Worker。

Windows 盘符的默认 WSL 挂载权限可能被官方 profiler 拒绝。为仿真选择有正常 Linux 私有权限的目录；必要时只对专用目录配置启用 metadata、正确 UID/GID 和私有 umask 的 DrvFS 挂载。不要关闭 profiler 检查或修改全部磁盘权限。[WSL 文件权限说明](https://learn.microsoft.com/en-us/windows/wsl/file-permissions)。

- `simulate_kernel(hypothesis, case_ids?, learned_from?)` 冻结本队源码，执行真实实验并返回诊断。默认运行全部 **15 个暂拟本地 case**；显式子集仅作探针。
- `read_simulation_results(job_id?, team?)` 查看日志、逐点结果和 CSV 预览。原始 trace 在 Linux 实验目录保留。
- 将 `AWORKER_LAB_REQUIRE_SIMULATION=true` 保持开启（`.env.example` 已设置）。缺环境时等待，不静默退回源码猜测；不把未测代码当作通过候选。
- 候选门槛要求**同队、同源码、同输入包、同 Worker / adapter 版本、同一完整实验**全部通过。旧 9 点记录或其他队的通过记录不能代替。
- 学习不能替代自己的实验。每队首次独立通过前不注入跨队代码与收件箱；本队诊断始终可见。

官方共 15 个点，本地也拟定 15 组，但隐藏 shape 与数值未确认，逐点对应数仍为 0。它们验证公开语义的覆盖面，不是官方隐藏输入的替身。CPU 仿真指标不换算成 NPU 耗时或官方分数。

## 官测与每日预算

在面板「Judger」连接官方窗口，由人类完成登录和网站要求的参赛授权。后续由 Judger 提交已冻结、已复核、已独立提名且仿真证据匹配的候选。仅上传官方允许的 7 个文件，其余 34 文件快照用于身份核验。原队继续改码，不影响已冻结的送测版本。

macOS / Linux 或没有可用 Chrome / Edge 时安装配套浏览器：

```sh
uv run python -m playwright install chromium
```

Linux 另需图形桌面 / 显示服务及浏览器系统依赖。浏览器使用项目独立临时上下文，沙箱开启，不读取已有浏览器档案、不导出 Cookie。可选本机 Linux/WSLg 桥接：

```sh
bash tools/start_judge_bridge.sh LINUX_ROOT PYTHON SHARED_BRIDGE OFFICIAL_URL
```

工作台 `.env` 用 `AWORKER_LAB_JUDGE_BRIDGE` 指向同一个共享目录；只适用于可信本机共享目录，不是公网 RPC。首次登录状态以面板核验结果为准。

独立筛选器最多提名一个挑战者，Judger 不逐队轮流送测。默认**全局每天最多 50 次尝试**，上海时间零点换日；发送前持久化记账，失败 / 限流 / 不确定尝试也计入。重启、换算子和暂停不清零。默认至少间隔 60 秒、一次等待一个回执；不确定提交不自动重发。

额度用完只停止新提交，团队继续搜索，已有回执继续跟踪。可以分别暂停搜索或官测。官方终态反馈通过 A2A 持久投递，确认和去重；收到更新的队伍在后续模型步骤读取。只有官方 Pass 且分数更优才更新已验证冠军。

单主队的官测反馈同时进入持久化修正任务，主队自己的回执不受“先仿真再学习其他队”的门槛限制。主力登记一个实验计划，直接改码并运行本地探针，再推进到同源码完整验证；独立 Judger 接收合格的冻结版本，无需等待主队整轮结束。已测源码不重复自动提交；独立源码审查退回的缺陷也会进入修正任务。任务只有阅读/分析而没有源码变化或新实验时停止重复派发，原因显示在面板；不会把消息送达等同于修复成功。

[官方题目](https://cannjudge.cn/public/ladder_october/confusionmulgrad) · [官方榜单](https://cannjudge.cn/public/ladder_october/confusionmulgrad/ranking)

## 监督与回放

点击团队查看实际模型、当前步骤、公开答复、Todo、工具调用、源码版本和本队实验；Token 仅展示提供商实际返回的用量，不读取隐藏推理。A2A 已送达数字是消息投递确认次数，不是队伍数或 Token。

导出事件后可离线导入回放，不发起模型、仿真或官测请求。未来成绩不会提前显示；源码页注明导出时最终快照。切到回放不会停止后台持续优化。先暂停搜索和官测，再导出适合对外展示且已脱敏的记录。

## 接口

所有路径以 `http://127.0.0.1:4173/api/lab` 为前缀，受本机同源控制。

| 接口 | 作用 |
| --- | --- |
| `POST /control/teams/auto` | `{"count":8}` 创建独立团队，尚不调用模型 |
| `POST /control/swarm/start` | `{"teams":["gpt-001"],"prompt":"实现并复核算子"}` 启动真实模型工作 |
| `POST /control/swarm/continuous` | `{"enabled":true,"teams":null}` 启动所有活动团队的持续循环；`false` 暂停派发 |
| `GET /control/swarm/continuous` | 持续搜索计划、每队轮次与失败退避状态 |
| `GET /workspace/judge` | 公榜快照、冻结候选、关联提交、能力状态 |
| `POST /workspace/judge/sync` | 同步官方公开题面、榜单与已关联结果 |
| `POST /workspace/judge/watch` | `{"enabled":true}` 开启定期同步 |
| `POST /workspace/judge/session/open` | `{"enabled":true,"max_submissions":50}` 打开项目官方窗口并开启精选官测 |
| `POST /workspace/judge/session/check` | 验证该窗口的官方登录身份，不返回凭据 |
| `POST /workspace/judge/session/close` | 暂停自动官测，关闭项目登录上下文 |
| `POST /workspace/judge/automation` | `{"enabled":false,"max_submissions":50}` 暂停 / 开启官测及设置全局每日预算 |
| `POST /workspace/judge/candidates/{id}/submit` | 只允许当前已提名、已复核的挑战候选，受相同额度限制 |
| `POST /workspace/judge/stage` | `{"team":"gpt-001"}` 冻结完整候选 |
| `GET /workspace/judge/packages/{id}` | 下载同一冻结版本 ZIP |
| `GET /workspace/judge/candidates/{id}` | 读取冻结源码供检查与跨队学习 |
| `POST /workspace/judge/track` | `{"candidate_id":"…","submission_id":"…"}` 关联真实提交 |
| `POST /workspace/judge/candidates/{id}/feedback` | 将官方反馈派给原队，开始一次修正轮次 |

## 工具版本

官方 [msopprof simulator 指南](https://github.com/Ascend/msopprof/blob/master/docs/zh/user_guide/msopprof_simulator_user_guide.md)需要匹配 CANN 与目标芯片的仿真库，还要占用 CPU 和内存。`simulate_kernel` 已从能力检查改为实际队列工具，底层执行 `msopprof simulator --soc-version=Ascend910B4`；没有新鲜的 Worker 心跳或工具版本不匹配时明确返回 unavailable。
