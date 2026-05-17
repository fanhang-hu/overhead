After we use sysdig, we need to convert .scap file to .json file, which nodlink can use .json file to detect.

Therefore, we write a shell convert_json.sh, to calculate some overhead, the shell are as follows,

```
#!/usr/bin/env bash
set -euo pipefail

if [ $# -eq 0 ]; then
    echo "错误: 请指定 .scap 文件路径"
    echo "用法: $0 <scap文件路径>"
    echo "示例: $0 ./lateral_high_fidelity+replay_zero.scap"
    exit 1
fi

SCAP_PATH="$1"

if [ ! -f "$SCAP_PATH" ]; then
    echo "错误: .scap 文件不存在: $SCAP_PATH"
    exit 1
fi

SCAP_DIR="$(dirname "$SCAP_PATH")"
SCAP_BASENAME="$(basename "$SCAP_PATH" .scap)"

USV_FILE="${SCAP_DIR}/${SCAP_BASENAME}.usv"
JSONL_FILE="${SCAP_DIR}/${SCAP_BASENAME}.jsonl"
JSON_FILE="${SCAP_DIR}/${SCAP_BASENAME}.json"
V1_JSON_FILE="${SCAP_DIR}/${SCAP_BASENAME}-v1.json"
PROC_CMDLINE_FILE="${SCAP_DIR}/${SCAP_BASENAME}_proc_cmdline.txt"
REPORT_FILE="${SCAP_DIR}/${SCAP_BASENAME}.txt"

DELIM=$'\x1f'
FMT="%evt.args${DELIM}%evt.num${DELIM}%evt.rawtime${DELIM}%evt.type${DELIM}%fd.name${DELIM}%proc.cmdline${DELIM}%proc.name${DELIM}%proc.pcmdline${DELIM}%proc.pname"

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

exec > >(tee "$REPORT_FILE") 2>&1

now_human() {
    date '+%Y-%m-%d %H:%M:%S.%3N'
}

now_sec() {
    date +%s.%N
}

size_bytes() {
    if [ -f "$1" ]; then
        stat -c%s "$1"
    else
        echo 0
    fi
}

size_human() {
    if [ -f "$1" ]; then
        du -h "$1" | cut -f1
    else
        echo "0"
    fi
}

run_timed() {
    local name="$1"
    local cmd="$2"
    local time_file="${tmpdir}/${name}.time"
    local wall_file="${tmpdir}/${name}.wall"

    echo ""
    echo ">>> ${name}"
    local start end wall
    start="$(now_sec)"

    /usr/bin/time -v -o "$time_file" bash -c "$cmd"

    end="$(now_sec)"
    wall="$(awk -v s="$start" -v e="$end" 'BEGIN {printf "%.6f", e-s}')"
    echo "$wall" > "$wall_file"

    echo "    ✓ ${name} 完成"
    echo "    wall_time_sec=${wall}"
    echo "    user_time_sec=$(grep 'User time' "$time_file" | awk -F: '{gsub(/^ +/, "", $2); print $2}')"
    echo "    system_time_sec=$(grep 'System time' "$time_file" | awk -F: '{gsub(/^ +/, "", $2); print $2}')"
    echo "    cpu_percent=$(grep 'Percent of CPU' "$time_file" | awk -F: '{gsub(/^ +/, "", $2); print $2}')"
    echo "    max_rss_kb=$(grep 'Maximum resident set size' "$time_file" | awk -F: '{gsub(/^ +/, "", $2); print $2}')"
}

echo "============================================================"
echo "SCAP → JSON conversion overhead report"
echo "开始时间: $(now_human)"
echo "输入文件: $SCAP_PATH"
echo "输出目录: $SCAP_DIR"
echo "报告文件: $REPORT_FILE"
echo "输出文件:"
echo "  USV:              $USV_FILE"
echo "  JSONL:            $JSONL_FILE"
echo "  JSON array:       $JSON_FILE"
echo "  V1 JSON:          $V1_JSON_FILE"
echo "  proc.cmdline txt: $PROC_CMDLINE_FILE"
echo "============================================================"

TOTAL_START="$(now_sec)"

# 这一步通常不需要 chown 目录。保留但不强制失败。
echo ""
echo ">>> Step 0: 权限检查"
if [ ! -r "$SCAP_PATH" ]; then
    echo "输入文件当前用户不可读，尝试 sudo chown 所在目录"
    sudo chown "$USER:$USER" "$SCAP_PATH" || true
fi

run_timed "step1_sysdig_scap_to_usv" \
    "sysdig -r '$SCAP_PATH' -p '$FMT' > '$USV_FILE'"

run_timed "step2_usv_to_jsonl" \
    "jq -Rc '
split(\"\u001f\") as \$f |
{
  \"evt.args\": (\$f[0] // \"\"),
  \"evt.num\": ((\$f[1] // \"\") | tonumber? // null),
  \"evt.time\": ((\$f[2] // \"\") | tonumber? // null),
  \"evt.type\": (\$f[3] // \"\"),
  \"fd.name\": (\$f[4] // \"\"),
  \"proc.cmdline\": (\$f[5] // \"\"),
  \"proc.name\": (\$f[6] // \"\"),
  \"proc.pcmdline\": (\$f[7] // \"\"),
  \"proc.pname\": (\$f[8] // \"\")
}
' '$USV_FILE' > '$JSONL_FILE'"

run_timed "step3_jsonl_to_json_array" \
    "jq -s '.' '$JSONL_FILE' > '$JSON_FILE'"

run_timed "step4_json_array_to_v1_json" \
    "jq -c '.[]' '$JSON_FILE' > '$V1_JSON_FILE'"

run_timed "step5_extract_unique_proc_cmdline" \
    "jq -r '.[].\"proc.cmdline\" // empty' '$JSON_FILE' | sort -u > '$PROC_CMDLINE_FILE'"

TOTAL_END="$(now_sec)"
TOTAL_WALL="$(awk -v s="$TOTAL_START" -v e="$TOTAL_END" 'BEGIN {printf "%.6f", e-s}')"

EVENT_COUNT="$(wc -l < "$JSONL_FILE" | tr -d ' ')"

# 估算 trace duration：evt.time 是 ns
read FIRST_TS LAST_TS < <(
    awk -F"$DELIM" '
    NR==1 {first=$3}
    {last=$3}
    END {print first, last}
    ' "$USV_FILE"
)

TRACE_DURATION_SEC="$(awk -v f="$FIRST_TS" -v l="$LAST_TS" 'BEGIN {
    if (f == "" || l == "" || l <= f) print "NA";
    else printf "%.6f", (l - f) / 1000000000.0;
}')"

SCAP_BYTES="$(size_bytes "$SCAP_PATH")"
USV_BYTES="$(size_bytes "$USV_FILE")"
JSONL_BYTES="$(size_bytes "$JSONL_FILE")"
JSON_BYTES="$(size_bytes "$JSON_FILE")"
V1_JSON_BYTES="$(size_bytes "$V1_JSON_FILE")"

THROUGHPUT_EPS="$(awk -v n="$EVENT_COUNT" -v t="$TOTAL_WALL" 'BEGIN {
    if (t <= 0) print "NA"; else printf "%.3f", n / t;
}')"

THROUGHPUT_MBPS="$(awk -v b="$SCAP_BYTES" -v t="$TOTAL_WALL" 'BEGIN {
    if (t <= 0) print "NA"; else printf "%.6f", b / t / 1024.0 / 1024.0;
}')"

REALTIME_FACTOR="$(awk -v conv="$TOTAL_WALL" -v dur="$TRACE_DURATION_SEC" 'BEGIN {
    if (dur == "NA" || dur <= 0) print "NA";
    else printf "%.6f", conv / dur;
}')"

JSON_EXPANSION="$(awk -v j="$JSON_BYTES" -v s="$SCAP_BYTES" 'BEGIN {
    if (s <= 0) print "NA"; else printf "%.6f", j / s;
}')"

V1_EXPANSION="$(awk -v j="$V1_JSON_BYTES" -v s="$SCAP_BYTES" 'BEGIN {
    if (s <= 0) print "NA"; else printf "%.6f", j / s;
}')"

echo ""
echo "============================================================"
echo "转换完成统计"
echo "结束时间: $(now_human)"
echo ""
echo "[Core metrics]"
echo "total_wall_time_sec=${TOTAL_WALL}"
echo "event_count=${EVENT_COUNT}"
echo "trace_duration_sec=${TRACE_DURATION_SEC}"
echo "conversion_throughput_events_per_sec=${THROUGHPUT_EPS}"
echo "conversion_throughput_input_MB_per_sec=${THROUGHPUT_MBPS}"
echo "real_time_factor=${REALTIME_FACTOR}"
echo ""
echo "[File sizes]"
echo "scap_bytes=${SCAP_BYTES} ($(size_human "$SCAP_PATH"))"
echo "usv_bytes=${USV_BYTES} ($(size_human "$USV_FILE"))"
echo "jsonl_bytes=${JSONL_BYTES} ($(size_human "$JSONL_FILE"))"
echo "json_bytes=${JSON_BYTES} ($(size_human "$JSON_FILE"))"
echo "v1_json_bytes=${V1_JSON_BYTES} ($(size_human "$V1_JSON_FILE"))"
echo "proc_cmdline_txt_bytes=$(size_bytes "$PROC_CMDLINE_FILE") ($(size_human "$PROC_CMDLINE_FILE"))"
echo ""
echo "[Expansion]"
echo "json_expansion_ratio=json_bytes/scap_bytes=${JSON_EXPANSION}"
echo "v1_json_expansion_ratio=v1_json_bytes/scap_bytes=${V1_EXPANSION}"
echo ""
echo "[Generated files]"
echo "$USV_FILE"
echo "$JSONL_FILE"
echo "$JSON_FILE"
echo "$V1_JSON_FILE"
echo "$PROC_CMDLINE_FILE"
echo ""
echo "报告已保存到: $REPORT_FILE"
echo "============================================================"
```

We use this command to start convert and computer overhead, it will generate a .txt file
```bash
./convert_json.sh ./***.scap
```

The most important data in the .txt file are **conversion_throughput_events_per_sec(how many events can be convert per second)** and **real_time_factor(convert time / monitor time)**.
