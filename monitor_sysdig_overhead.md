```monitor_sysdig_overhead.sh``` is as following: 

```
#!/usr/bin/env bash
set -u

if [ $# -lt 2 ]; then
    echo "用法: $0 <cps|cps+sysdig> <duration_seconds> [--interval 30] [--sysdig-pid PID] [--cps-pid PID] [--scap PATH] [--sysdig-log PATH]"
    echo "示例:"
    echo "  $0 cps 300"
    echo "  $0 cps+sysdig 300 --sysdig-pid \$(pidof sysdig) --scap ./capture.scap"
    exit 1
fi

MODE="$1"
DURATION="$2"
shift 2

INTERVAL=30
SYSDIG_PID=""
CPS_PID=""
SCAP_PATH=""
SYSDIG_LOG=""

while [ $# -gt 0 ]; do
    case "$1" in
        --interval)
            INTERVAL="$2"
            shift 2
            ;;
        --sysdig-pid)
            SYSDIG_PID="$2"
            shift 2
            ;;
        --cps-pid)
            CPS_PID="$2"
            shift 2
            ;;
        --scap)
            SCAP_PATH="$2"
            shift 2
            ;;
        --sysdig-log)
            SYSDIG_LOG="$2"
            shift 2
            ;;
        *)
            echo "未知参数: $1"
            exit 1
            ;;
    esac
done

if [ "$MODE" != "cps" ] && [ "$MODE" != "cps+sysdig" ]; then
    echo "错误: mode 必须是 cps 或 cps+sysdig"
    exit 1
fi

OUT_FILE="./${MODE}.txt"

# cps+sysdig 模式下，如果没指定 sysdig pid，则自动找一个
if [ "$MODE" = "cps+sysdig" ] && [ -z "$SYSDIG_PID" ]; then
    SYSDIG_PID="$(pgrep -x sysdig | head -n 1 || true)"
fi

NCPU="$(nproc)"
CLK_TCK="$(getconf CLK_TCK)"

now_ms() {
    date '+%Y-%m-%d %H:%M:%S'
}

get_proc_cpu_jiffies() {
    local pid="$1"
    if [ -z "$pid" ] || [ ! -r "/proc/$pid/stat" ]; then
        echo "NA"
        return
    fi

    # /proc/<pid>/stat 的第 2 列 comm 可能含括号；先去掉 comm 之前内容
    local stat rest
    stat="$(cat "/proc/$pid/stat" 2>/dev/null || true)"
    rest="${stat#*) }"
    # rest 的第 12/13 个字段对应原始 stat 的 utime/stime，即 field14/field15
    awk '{print $12 + $13}' <<< "$rest"
}

get_proc_rss_kb() {
    local pid="$1"
    if [ -z "$pid" ] || [ ! -r "/proc/$pid/status" ]; then
        echo "NA"
        return
    fi
    awk '/VmRSS:/ {print $2}' "/proc/$pid/status"
}

get_proc_write_bytes() {
    local pid="$1"
    if [ -z "$pid" ] || [ ! -r "/proc/$pid/io" ]; then
        echo "NA"
        return
    fi
    awk '/write_bytes:/ {print $2}' "/proc/$pid/io"
}

get_system_cpu() {
    local line user nice system idle iowait irq softirq steal
    read -r line < /proc/stat
    # 解析 "cpu  user nice system idle iowait irq softirq steal ..."
    set -- $line
    shift   # 去掉第一个字段 "cpu"
    user=$1; nice=$2; system=$3; idle=$4; iowait=$5; irq=$6; softirq=$7; steal=$8
    local idle_all=$((idle + iowait))
    local non_idle=$((user + nice + system + irq + softirq + steal))
    local total=$((idle_all + non_idle))
    echo "$total $idle_all"
}

get_disk_write_sectors() {
    local sectors=0
    while read -r _ _ _ name _ _ _ _ _ writes _; do
        case "$name" in
            sd*|vd*|xvd*|nvme*n*|mmcblk*)
                sectors=$((sectors + writes))
                ;;
        esac
    done < /proc/diskstats
    echo "$sectors"
}

get_scap_size_bytes() {
    if [ -n "$SCAP_PATH" ] && [ -f "$SCAP_PATH" ]; then
        stat -c%s "$SCAP_PATH"
    else
        echo "NA"
    fi
}

get_drop_stats_best_effort() {
    # 输出: captured dropped
    # 1) 尝试从 sysdig/falco stats 文件读取，路径不同版本可能不同
    local candidates=(
        "/proc/sysdig/stats"
        "/proc/sysdig_probe/stats"
        "/proc/falco/stats"
        "/proc/scap/stats"
    )

    for f in "${candidates[@]}"; do
        if [ -r "$f" ]; then
            local captured dropped
            captured="$(grep -Ei 'captured|n_evts|events' "$f" 2>/dev/null | grep -Eo '[0-9]+' | tail -n 1 || true)"
            dropped="$(grep -Ei 'drop|dropped' "$f" 2>/dev/null | grep -Eo '[0-9]+' | tail -n 1 || true)"
            if [ -n "$captured" ] && [ -n "$dropped" ]; then
                echo "$captured $dropped"
                return
            fi
        fi
    done

    # 2) 尝试从 sysdig log 解析。不同版本输出不同，所以这里只做宽松解析
    if [ -n "$SYSDIG_LOG" ] && [ -f "$SYSDIG_LOG" ]; then
        local dropped captured
        dropped="$(grep -Ei 'drop|dropped' "$SYSDIG_LOG" | grep -Eo '[0-9]+' | tail -n 1 || true)"
        captured="$(grep -Ei 'captured|events' "$SYSDIG_LOG" | grep -Eo '[0-9]+' | tail -n 1 || true)"
        if [ -n "$captured" ] && [ -n "$dropped" ]; then
            echo "$captured $dropped"
            return
        fi
    fi

    echo "NA NA"
}

calc_percent() {
    awk -v num="$1" -v den="$2" 'BEGIN {
        if (den <= 0 || num == "NA" || den == "NA") print "NA";
        else printf "%.3f", (num / den) * 100.0;
    }'
}

calc_rate_mb_s() {
    awk -v bytes="$1" -v sec="$2" 'BEGIN {
        if (bytes == "NA" || sec <= 0) print "NA";
        else printf "%.6f", bytes / sec / 1024.0 / 1024.0;
    }'
}

exec > >(tee "$OUT_FILE") 2>&1

echo "============================================================"
echo "Sysdig/CPS overhead monitor"
echo "Mode: $MODE"
echo "Duration: ${DURATION}s"
echo "Interval: ${INTERVAL}s"
echo "Output: $OUT_FILE"
echo "Sysdig PID: ${SYSDIG_PID:-NA}"
echo "CPS PID: ${CPS_PID:-NA}"
echo "SCAP path: ${SCAP_PATH:-NA}"
echo "Sysdig log: ${SYSDIG_LOG:-NA}"
echo "Start time: $(now_ms)"
echo "============================================================"
echo ""

if [ "$MODE" = "cps+sysdig" ] && [ -z "$SYSDIG_PID" ]; then
    echo "警告: 未找到 sysdig PID。sysdig CPU / RSS / write_bytes 将显示 NA。"
    echo ""
fi

prev_total_idle=($(get_system_cpu))
prev_total="${prev_total_idle[0]}"
prev_idle="${prev_total_idle[1]}"

prev_disk_sectors="$(get_disk_write_sectors)"
prev_sysdig_jiffies="$(get_proc_cpu_jiffies "$SYSDIG_PID")"
prev_cps_jiffies="$(get_proc_cpu_jiffies "$CPS_PID")"
prev_sysdig_write="$(get_proc_write_bytes "$SYSDIG_PID")"
prev_scap_size="$(get_scap_size_bytes)"
prev_drop_stats=($(get_drop_stats_best_effort))
prev_captured="${prev_drop_stats[0]}"
prev_dropped="${prev_drop_stats[1]}"

elapsed=0
sample_id=0

printf "%-8s %-20s %-12s %-14s %-14s %-14s %-14s %-14s %-14s %-16s %-16s %-16s\n" \
    "sample" "time" "sysCPU%" "sysdigCPU%" "cpsCPU%" "sysdigRSS_MB" "cpsRSS_MB" \
    "diskWrite_MBps" "sysdigWrite_MBps" "scapGrowth_MBps" "dropRate%" "cpsLoopJitter"

while [ "$elapsed" -lt "$DURATION" ]; do
    sleep "$INTERVAL"
    elapsed=$((elapsed + INTERVAL))
    sample_id=$((sample_id + 1))

    cur_total_idle=($(get_system_cpu))
    cur_total="${cur_total_idle[0]}"
    cur_idle="${cur_total_idle[1]}"

    total_delta=$((cur_total - prev_total))
    idle_delta=$((cur_idle - prev_idle))
    sys_cpu="$(awk -v td="$total_delta" -v id="$idle_delta" 'BEGIN {
        if (td <= 0) print "NA";
        else printf "%.3f", (td - id) / td * 100.0;
    }')"

    cur_disk_sectors="$(get_disk_write_sectors)"
    disk_bytes_delta=$(( (cur_disk_sectors - prev_disk_sectors) * 512 ))
    disk_write_mbps="$(calc_rate_mb_s "$disk_bytes_delta" "$INTERVAL")"

    cur_sysdig_jiffies="$(get_proc_cpu_jiffies "$SYSDIG_PID")"
    if [ "$cur_sysdig_jiffies" != "NA" ] && [ "$prev_sysdig_jiffies" != "NA" ]; then
        sysdig_cpu="$(awk -v d="$((cur_sysdig_jiffies - prev_sysdig_jiffies))" -v hz="$CLK_TCK" -v sec="$INTERVAL" 'BEGIN {
            printf "%.3f", d / hz / sec * 100.0;
        }')"
    else
        sysdig_cpu="NA"
    fi

    cur_cps_jiffies="$(get_proc_cpu_jiffies "$CPS_PID")"
    if [ "$cur_cps_jiffies" != "NA" ] && [ "$prev_cps_jiffies" != "NA" ]; then
        cps_cpu="$(awk -v d="$((cur_cps_jiffies - prev_cps_jiffies))" -v hz="$CLK_TCK" -v sec="$INTERVAL" 'BEGIN {
            printf "%.3f", d / hz / sec * 100.0;
        }')"
    else
        cps_cpu="NA"
    fi

    sysdig_rss_kb="$(get_proc_rss_kb "$SYSDIG_PID")"
    cps_rss_kb="$(get_proc_rss_kb "$CPS_PID")"

    sysdig_rss_mb="$(awk -v kb="$sysdig_rss_kb" 'BEGIN { if (kb=="NA") print "NA"; else printf "%.3f", kb/1024.0; }')"
    cps_rss_mb="$(awk -v kb="$cps_rss_kb" 'BEGIN { if (kb=="NA") print "NA"; else printf "%.3f", kb/1024.0; }')"

    cur_sysdig_write="$(get_proc_write_bytes "$SYSDIG_PID")"
    if [ "$cur_sysdig_write" != "NA" ] && [ "$prev_sysdig_write" != "NA" ]; then
        sysdig_write_mbps="$(calc_rate_mb_s "$((cur_sysdig_write - prev_sysdig_write))" "$INTERVAL")"
    else
        sysdig_write_mbps="NA"
    fi

    cur_scap_size="$(get_scap_size_bytes)"
    if [ "$cur_scap_size" != "NA" ] && [ "$prev_scap_size" != "NA" ]; then
        scap_growth_mbps="$(calc_rate_mb_s "$((cur_scap_size - prev_scap_size))" "$INTERVAL")"
    else
        scap_growth_mbps="NA"
    fi

    cur_drop_stats=($(get_drop_stats_best_effort))
    cur_captured="${cur_drop_stats[0]}"
    cur_dropped="${cur_drop_stats[1]}"

    if [ "$cur_captured" != "NA" ] && [ "$cur_dropped" != "NA" ] && [ "$prev_captured" != "NA" ] && [ "$prev_dropped" != "NA" ]; then
        cap_delta=$((cur_captured - prev_captured))
        drop_delta=$((cur_dropped - prev_dropped))
        denom=$((cap_delta + drop_delta))
        drop_rate="$(calc_percent "$drop_delta" "$denom")"
    else
        drop_rate="NA"
    fi

    # 没有 CPS 程序时间戳时，不能真实计算 CPS loop jitter
    cps_loop_jitter="NA"

    printf "%-8s %-20s %-12s %-14s %-14s %-14s %-14s %-14s %-14s %-16s %-16s %-16s\n" \
        "$sample_id" "$(now_ms)" "$sys_cpu" "$sysdig_cpu" "$cps_cpu" "$sysdig_rss_mb" "$cps_rss_mb" \
        "$disk_write_mbps" "$sysdig_write_mbps" "$scap_growth_mbps" "$drop_rate" "$cps_loop_jitter"

    prev_total="$cur_total"
    prev_idle="$cur_idle"
    prev_disk_sectors="$cur_disk_sectors"
    prev_sysdig_jiffies="$cur_sysdig_jiffies"
    prev_cps_jiffies="$cur_cps_jiffies"
    prev_sysdig_write="$cur_sysdig_write"
    prev_scap_size="$cur_scap_size"
    prev_captured="$cur_captured"
    prev_dropped="$cur_dropped"
done

echo ""
echo "============================================================"
echo "End time: $(now_ms)"
echo "Saved to: $OUT_FILE"
echo "Note:"
echo "  cpsLoopJitter=NA because CPS application timestamps are not available."
echo "  dropRate%=NA means the current sysdig/falco stack did not expose periodic drop counters."
echo "============================================================"
```
I use the following commands to test, first of all, we need to open three Terminals, Terminal A, B, and C, and we need to test Cyber-Physical System (raw) and Cyber-Physical System (using sysdig to monitor).

**TEST 1, monitor CPS raw, we use baseline to be a example and we run 300s. In terminal A,**
```bash
./scripts/run_rpi_experiment.sh --mode baseline --duration-sec 320
```
After runing this CPS process, it will print three pids like,
```bash
[run_rpi_experiment] controller pid=1229
[run_rpi_experiment] gateway pid=1230
[run_rpi_experiment] sensor pid=1231
```
In terminal B,
```bash
# ./monitor_sysdig_overhead.sh cps 300 --cps-pid $(pidof your_cps_binary)
./monitor_sysdig_overhead.sh cps 300 --cps-pid 1229 1230 1231
```
------
**TEST 2, monitor CPS+Sysdig, we also use baseline to be a example and also run 300s. In terminal B**
```bash
sudo sysdig -w cps+sysdig.scap
```
In terminal A,
```bash
./scripts/run_rpi_experiment.sh --mode baseline --duration-sec 320
```
We also use the following bash print as an example,
```bash
[run_rpi_experiment] controller pid=1229
[run_rpi_experiment] gateway pid=1230
[run_rpi_experiment] sensor pid=1231
```
In terminal C,
```bash
./monitor_sysdig_overhead.sh cps+sysdig 300 --cps-pid 1229 1230 1231 --sysdig-pid $(pidof sysdig) --scap ./cps+sysdig.scap
```
Remamber that Terminal B and Terminal C are under the same dictory.

Finally, we will get two txt, ```cps.txt``` and ```cps+sysdig.txt```
