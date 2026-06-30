# Release Notes - v2.0.1

AI 驱动智能旅行攻略生成器 `v2.0.1` 正式发布！本次更新修复了 Web App 端用户生成攻略时因后台线程调用 `signal.signal()` 导致程序崩溃的 BUG。

## 🔍 问题背景

当用户通过 Web App（`http://localhost:8080`）提交任务时，后端通过 `threading.Thread` 在**后台线程**中运行 `run_pipeline()` 工序链。而 `run_pipeline()` 中注册了 Ctrl+C 信号处理器用于 CLI 模式的优雅中断保护：

```python
signal.signal(signal.SIGINT, _signal_handler)
```

但 Python 的 `signal.signal()` **只能在主线程中调用**，在 Thread 子线程中调用会抛出 `ValueError: signal only works in main thread`，导致用户生成攻略任务直接崩溃。

## 🛠️ 修复内容

`pipeline/run_pipeline.py` 中两处 `signal.signal()` 调用增加了主线程保护：

| 位置 | 修改前 | 修改后 |
|:---|:---|:---|
| **信号注册** (L704-708) | 无条件调用 `signal.signal()` | `if threading.current_thread() is threading.main_thread():` 保护 |
| **信号恢复** (L808) | 无条件恢复原始 handler | 仅当 `original_handler` 非 None 且为主线程时恢复 |

**效果**：
- **CLI 模式**（`python pipeline/run_pipeline.py`）— Ctrl+C 优雅中断保护**不受影响**
- **Web App 模式**（`python webapp/main.py`）— 后台线程不再因信号注册崩溃

## 📈 如何升级

```bash
git pull origin main
```

如已验证无误，无需额外操作；如有旧版本 Web App 进程，重启即可生效：

```bash
# 重启 Web App
python webapp/main.py
```
