`main_raw.py` is raw nodlink main.py without adding time stamp.

`main_new.py` is added time stamp.

The following is the details of time stamp:
- 记录的 nodlink 检测的时间戳：
- 处理事件的总数：json 文件共有多少行（e.g. 312886）；
- 在线检测的总时间：第一个日志到达到最后一个窗口更新完成，不包含 recall 的计算（e.g. 8792 ms）；
- **nodlink 在线检测阶段的吞吐（e.g. 35588 条/秒）；**
- 包含计算 recall 在内的时间；
- 计算 recall 的时间；
- **graph_add：解析后的事件转换为图节点/边，添加到 provgraph 的时间（e.g. Avg 0.0051 ms/事件）；**
- **window_update：模型推理、异常评分时间（e.g. Avg 164.4 ms/窗口）；**
- 每个窗口的处理总时间（10s 1 个窗口）：解析 json + graph_add + window_update（e.g. Avg 354 ms）；
