from argparse import ArgumentParser
import networkx as nx
from streamz import Stream
from ProvGraph import *
import matplotlib.pyplot as plt
import json
import time, sched
import multiprocessing
from multiprocessing.managers import BaseManager
import schedule
from CacheGraph import *

from queue import Queue
from threading import Thread
import sys

sys.path.append('../training')
from config import *

import threading
import statistics

def get_keys(d, value):
    return [k for k, v in d.items() if v == value]


def extract_string(s):
    arr = []
    r = ''
    inside = True
    for n, i in enumerate(s):
        if i == '"' and (s[n - 1] != '\\' or n == 0):
            arr.append(i)
            if len(arr) % 2 == 0:
                inside = False
            else:
                inside = True
        r += i
        if i == '}' and not inside:
            return r


def get_orgs(line):
    # match_obj = re.match(r'(.*)\\"org_log\\":(.*)',line)
    # org = extract_string(match_obj.group(2).replace('\\\\','\\').replace('\\*','\*').replace('\\$','\$').replace('\\"','\"'))
    org_logs = json.loads(line)
    # org_logs['log_id'] = cnt
    return org_logs

# 0517 add -----------------------------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------------------------------------
# under

def _percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    k = (len(values) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[f]
    return values[f] + (values[c] - values[f]) * (k - f)


def _summary_ms(values):
    if not values:
        return {
            "count": 0,
            "mean_ms": None,
            "median_ms": None,
            "p95_ms": None,
            "p99_ms": None,
        }
    return {
        "count": len(values),
        "mean_ms": statistics.mean(values),
        "median_ms": statistics.median(values),
        "p95_ms": _percentile(values, 95),
        "p99_ms": _percentile(values, 99),
    }

# above
# --------------------------------------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------------------------------------

'''
def log_parser(q, dataset, anomaly_cutoff, Delta):
    proGraph = ProvGraph(dataset)
    start_time = None  # 改为记录第一个日志的时间戳
    point_start = time.time()
    thread_list = []
'''

# --------------------------------------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------------------------------------
# under

def log_parser(q, dataset, anomaly_cutoff, Delta):
    proGraph = ProvGraph(dataset)
    start_time = None
    point_start = time.perf_counter()
    wall_start = time.time()
    thread_list = []

    stats_lock = threading.Lock()
    stats = {
        "events_processed": 0,
        "windows_processed": 0,

        # event-level stages
        "json_parse_ms": [],
        "graph_add_ms": [],

        # window-level stages
        "window_update_ms": [],
        "window_total_inference_ms": [],

        # output/evaluation stages
        "alert_graph_output_ms": [],
        "recall_eval_ms": [],
    }

    window_id = 0
    window_parse_ms = 0.0
    window_graph_add_ms = 0.0
    window_events = 0

    def timed_update(proGraph, anomaly_cutoff, meta):
        t0 = time.perf_counter()
        proGraph.update(anomaly_cutoff)
        t1 = time.perf_counter()

        update_ms = (t1 - t0) * 1000.0
        total_ms = meta["parse_ms"] + meta["graph_add_ms"] + update_ms

        with stats_lock:
            stats["window_update_ms"].append(update_ms)
            stats["window_total_inference_ms"].append(total_ms)

        print(
            "NODLINK_STAGE "
            f"window_id={meta['window_id']} "
            f"events={meta['events']} "
            f"parse_ms={meta['parse_ms']:.3f} "
            f"graph_add_ms={meta['graph_add_ms']:.3f} "
            f"update_ms={update_ms:.3f} "
            f"window_total_inference_ms={total_ms:.3f}",
            flush=True,
        )

    def launch_update(reason):
        nonlocal window_id, window_parse_ms, window_graph_add_ms, window_events

        proGraph.thread_lock.acquire()

        meta = {
            "window_id": window_id,
            "reason": reason,
            "events": window_events,
            "parse_ms": window_parse_ms,
            "graph_add_ms": window_graph_add_ms,
        }

        print(
            f"start_update reason={reason} "
            f"window_id={window_id} events={window_events}",
            flush=True,
        )

        t = threading.Thread(target=timed_update, args=(proGraph, anomaly_cutoff, meta))
        t.start()
        thread_list.append(t)

        with stats_lock:
            stats["windows_processed"] += 1

        window_id += 1
        window_parse_ms = 0.0
        window_graph_add_ms = 0.0
        window_events = 0

# above
# --------------------------------------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------------------------------------

    while True:
        log_line = q.recv()

# --------------------------------------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------------------------------------
# under

        if log_line == "end":
            if window_events > 0:
                launch_update("end")
            break
# above
# --------------------------------------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------------------------------------

        '''
        if log_line == "end":
            proGraph.thread_lock.acquire()
            print("start_update")
            t = threading.Thread(target=proGraph.update, args=(anomaly_cutoff,))
            t.start()
            thread_list.append(t)
            break

        else:
            org_log = get_orgs(log_line)

            # 获取日志时间戳（纳秒）
            current_timestamp = org_log.get('evt.time', 0)

            # 初始化起始时间戳
            if start_time is None:
                start_time = current_timestamp

            # 处理节点
            if org_log['evt.type'] in APTLOG_TYPE.FILE_OP and org_log['proc.cmdline'] is not None and org_log[
                'fd.name'] is not None:
                proGraph.graph_add_node_mgr(org_log, APTLOG_KEY.FILE, org_log['evt.type'])
            elif org_log['evt.type'] in APTLOG_TYPE.PROCESS_OP and org_log['proc.pcmdline'] is not None and org_log[
                'proc.cmdline'] is not None:
                proGraph.graph_add_node_mgr(org_log, APTLOG_KEY.PROCESS, org_log['evt.type'])
            elif org_log['evt.type'] in APTLOG_TYPE.NET_OP and org_log['proc.cmdline'] is not None and org_log[
                'fd.name'] is not None:
                proGraph.graph_add_node_mgr(org_log, APTLOG_KEY.NET, org_log['evt.type'])
        '''

# --------------------------------------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------------------------------------
# under

        else:
            t_parse0 = time.perf_counter()
            org_log = get_orgs(log_line)
            t_parse1 = time.perf_counter()

            parse_ms = (t_parse1 - t_parse0) * 1000.0

            with stats_lock:
                stats["events_processed"] += 1
                stats["json_parse_ms"].append(parse_ms)

            window_parse_ms += parse_ms
            window_events += 1

            current_timestamp = org_log.get('evt.time', 0)

            if start_time is None:
                start_time = current_timestamp

            t_add0 = time.perf_counter()

            if org_log['evt.type'] in APTLOG_TYPE.FILE_OP and org_log['proc.cmdline'] is not None and org_log['fd.name'] is not None:
                proGraph.graph_add_node_mgr(org_log, APTLOG_KEY.FILE, org_log['evt.type'])
            elif org_log['evt.type'] in APTLOG_TYPE.PROCESS_OP and org_log['proc.pcmdline'] is not None and org_log['proc.cmdline'] is not None:
                proGraph.graph_add_node_mgr(org_log, APTLOG_KEY.PROCESS, org_log['evt.type'])
            elif org_log['evt.type'] in APTLOG_TYPE.NET_OP and org_log['proc.cmdline'] is not None and org_log['fd.name'] is not None:
                proGraph.graph_add_node_mgr(org_log, APTLOG_KEY.NET, org_log['evt.type'])

            t_add1 = time.perf_counter()
            graph_add_ms = (t_add1 - t_add0) * 1000.0

            with stats_lock:
                stats["graph_add_ms"].append(graph_add_ms)

            window_graph_add_ms += graph_add_ms

# above
# --------------------------------------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------------------------------------


        # 计算时间差（纳秒转秒：除以1e9）
        # Delta 参数是秒，需要转换比较
        
        # if start_time is not None:
        if start_time is not None and current_timestamp is not None:

            time_diff_seconds = (current_timestamp - start_time) / 1e9

            '''
            if time_diff_seconds >= Delta:
                proGraph.thread_lock.acquire()
                print(f"start_update (time diff: {time_diff_seconds:.2f}s)")
                t = threading.Thread(target=proGraph.update, args=(anomaly_cutoff,))
                t.start()
                thread_list.append(t)
                start_time = current_timestamp  # 重置起始时间戳
            '''

# --------------------------------------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------------------------------------
# under
            if time_diff_seconds >= Delta:
                launch_update(f"time_window_{time_diff_seconds:.2f}s")
                start_time = current_timestamp
# above
# --------------------------------------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------------------------------------

    for t in thread_list:
        t.join()

    '''
    point_end = time.time()
    print('cost time:', point_end - point_start)
    '''

# --------------------------------------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------------------------------------
# under
    point_end = time.perf_counter()
    online_detection_total_ms = (point_end - point_start) * 1000.0
    print(f"NODLINK_ONLINE_DETECTION_TOTAL_MS={online_detection_total_ms:.3f}", flush=True)
# above
# --------------------------------------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------------------------------------

    ####### analyze the result ########
    ####### you can rewrite this part ##########
    ####### 1. check if the anomaly grpah is highly ranked ########

    # print(cnt)
    cnt = 0
    for i in proGraph.node_set:
        if i in proGraph.attack_process and proGraph.nodes[i]['score'] != 0:
            cnt += 1
            print(i, proGraph.GetNodeName(i), proGraph.nodes[i]['score'])
        elif i in proGraph.attack_process and proGraph.nodes[i]['score'] == 0:
            print(i, proGraph.GetNodeName(i), proGraph.nodes[i]['score'])

    # for i in proGraph.attack_process:
    #     print('attack: ',i,proGraph.nodes[i]['score'])
    if (len(proGraph.attack_process) > 0):
        print('rate: ', cnt / len(proGraph.attack_process))

    cnt = 0
    for i, g in enumerate(proGraph.graph_cache):
# --------------------------------------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------------------------------------
# under
        t_alert0 = time.perf_counter()
# above
# --------------------------------------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------------------------------------
        g.graph = proGraph.final_graph_taylor(g.graph)

        for k in g.graph.nodes():
            # if (g.graph.in_degree(k) == 1 and g.graph.degree(k) == 1 ):
            #     removelist.append(k)
            if proGraph.GetNodeType(k) == APTLOG_NODE_TYPE.PROCESS:
                g.graph.nodes[k]['label'] = proGraph.GetNodeName(k)
                g.graph.nodes[k]['score'] = proGraph.GetNodeScore(k)
                g.graph.nodes[k]['shape'] = 'box'
            elif proGraph.GetNodeType(k) == APTLOG_NODE_TYPE.NET:
                g.graph.nodes[k]['label'] = proGraph.GetNodeName(k)
                g.graph.nodes[k]['shape'] = 'diamond'
                g.graph.nodes[k]['score'] = 0
            else:
                g.graph.nodes[k]['label'] = proGraph.GetNodeName(k)
                g.graph.nodes[k]['shape'] = 'ellipse'
                g.graph.nodes[k]['score'] = 0

        for i in proGraph.taylor_map:
            origion = i
            while i in proGraph.taylor_map:
                i = proGraph.taylor_map[i]
            proGraph.taylor_map[origion] = i

        flag = False
        tmp_hit = set()
        for node in g.graph.nodes():
            if node in proGraph.attack_process:
                flag = True
                tmp_hit.add(node)
            x = get_keys(proGraph.taylor_map, node)
            if len(x) != 0:
                for n in x:
                    if n in proGraph.attack_process:
                        flag = True
                        tmp_hit.add(n)

                        # removelist = []
        for k in g.graph.nodes():
            # if g.graph.out_degree(k) == 0 and proGraph.GetNodeType(k) != APTLOG_NODE_TYPE.PROCESS:
            #     removelist.append(k)
            if proGraph.GetNodeType(k) == APTLOG_NODE_TYPE.PROCESS:
                g.graph.nodes[k]['label'] = proGraph.GetNodeName(k) + ' ' + str(proGraph.GetNodeScore(k))
            else:
                g.graph.nodes[k]['label'] = proGraph.GetNodeName(k) + ' ' + str(proGraph.GetNodeScore(k))
        # g.graph.remove_nodes_from(removelist)

        if flag:
            print(g.GetGraphScore(), 'attack', tmp_hit, len(g.graph.nodes()))
            proGraph.hit |= tmp_hit
        if not flag:
            # sort(key = lambda x: x.graph['score'],reverse = True)
            print(g.GetGraphScore(), 'benign', len(g.graph.nodes()))

        result_graph = ''
        max_len = 0
        for x in nx.weakly_connected_components(g.graph):
            if len(x) > max_len:
                max_len = len(x)
                result_graph = g.graph.subgraph(x)

        for k in result_graph.nodes():
            result_graph.nodes[k]['label'] = result_graph.nodes[k]['label'].replace(':', '')

        nx.drawing.nx_pydot.write_dot(result_graph, dataset + '/' + str(cnt) + '.dot')
# --------------------------------------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------------------------------------
# under
        t_alert1 = time.perf_counter()
        alert_ms = (t_alert1 - t_alert0) * 1000.0
        with stats_lock:
            stats["alert_graph_output_ms"].append(alert_ms)
        print(
            f"NODLINK_STAGE alert_graph_output graph_id={cnt} "
            f"nodes={len(g.graph.nodes())} "
            f"alert_output_ms={alert_ms:.3f}",
            flush=True,
        )
# above
# --------------------------------------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------------------------------------
        cnt += 1
    if (len(proGraph.attack_process) > 0):
        print("recall: ", len(proGraph.hit) / len(proGraph.attack_process))
        print(set(proGraph.attack_process) - proGraph.hit)
    '''
    recall_end = time.time()
    print('cost time:', recall_end - point_start)
    '''
# --------------------------------------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------------------------------------
# under
    recall_end = time.perf_counter()
    total_including_recall_ms = (recall_end - point_start) * 1000.0
    recall_eval_ms = total_including_recall_ms - online_detection_total_ms

    with stats_lock:
        stats["recall_eval_ms"].append(recall_eval_ms)

    events_processed = stats["events_processed"]
    online_sec = online_detection_total_ms / 1000.0 if online_detection_total_ms > 0 else 0.0
    throughput_eps = events_processed / online_sec if online_sec > 0 else None

    metric_summary = {
        "events_processed": events_processed,
        "windows_processed": stats["windows_processed"],

        "online_detection_total_ms": online_detection_total_ms,
        "total_including_recall_ms": total_including_recall_ms,

        "events_processed_per_second": throughput_eps,
        "nodlink_throughput_eps": throughput_eps,

        "stage_summary": {
            "json_parse": _summary_ms(stats["json_parse_ms"]),
            "cache_building_graph_add": _summary_ms(stats["graph_add_ms"]),
            "window_update": _summary_ms(stats["window_update_ms"]),
            "total_inference_per_window": _summary_ms(stats["window_total_inference_ms"]),
            "alert_graph_output": _summary_ms(stats["alert_graph_output_ms"]),
            "recall_eval": _summary_ms(stats["recall_eval_ms"]),
        }
    }
    print("NODLINK_METRIC_JSON=" + json.dumps(metric_summary, sort_keys=True), flush=True)
    print(f"NODLINK_TOTAL_INCLUDING_RECALL_MS={total_including_recall_ms:.3f}", flush=True)
# above
# --------------------------------------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------------------------------------

    x = set(proGraph.attack_process) - proGraph.hit
    for i in x:
        print(proGraph.GetNodeName(i))
    print(len(proGraph.node_set), len(proGraph.filtered))
    out_process = open(dataset + '/detected-process.txt', 'w')
    for i in proGraph.filtered:
        if i in proGraph.attack_process:
            out_process.write(i + ',1,' + proGraph.GetNodeName(i) + '\n')
        else:
            out_process.write(i + ',0,' + proGraph.GetNodeName(i) + '\n')
    out_process.close()


def proc_send(q, event_file):
    for line in open(event_file):
        q.send(line)
    q.send("end")


if __name__ == "__main__":
    multiprocessing.set_start_method('spawn')

    # parser = ArgumentParser(description="Multi arm bandits")
    parser = ArgumentParser(description="Nodlink sysdig online detection with adaptive sealing")
    # parser.add_argument("--d", type=str, default="hw17", help="model dict name")
    # parser.add_argument("--t", type=float,default=28, help="threshold")
    # parser.add_argument("--f", type=str, help="anomaly date for detection")
    # parser.add_argument("--w", type=float, default=10, help="detection window")
    parser.add_argument("--d", type=str, default="../model", help="model dict name")
    parser.add_argument("--t", type=float, default=30.65, help="threshold")
    parser.add_argument("--f", type=str, help="anomaly date for detection")
    parser.add_argument("--w", type=float, default=10, help="detection window")

    args = parser.parse_args()
    dataset = args.d
    anomaly_cutoff = args.t
    Delta = args.w
    if args.f:
        stream_file = args.f
    else:
        stream_file = dataset + "/shell-180s-v1.json"

    pipe = multiprocessing.Pipe()
    t1 = multiprocessing.Process(target=proc_send, args=(pipe[0], stream_file,))
    t2 = multiprocessing.Process(target=log_parser, args=(pipe[1], dataset, anomaly_cutoff, Delta,))
    start_time = time.time()

    t1.start()
    t2.start()

    t1.join()
    t2.join()

    end_time = time.time()
    print(end_time - start_time)

