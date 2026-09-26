#!/usr/bin/env bash
# gx10_survey.sh - READ-ONLY efficiency survey of the gx10. Changes nothing, reads no message
# content, no secrets (never opens ~/ufo-galaxy/.secrets). Every section is bounded by a timeout so
# a sick box still produces a report. Output is plain text sections "##### name".
#   bash gx10_survey.sh > survey.txt
set -u
sec() { echo; echo "##### $*"; }
t() { timeout "${T:-15}" "$@" 2>&1; }

sec "host"
uname -srm; uptime; echo "cpus: $(nproc)"; lscpu 2>/dev/null | grep -E "Model name|Thread|Core|Socket|max MHz" | head -6
sec "pressure (avg10/60/300)"
for r in cpu io memory; do echo "$r: $(paste -sd' ' /proc/pressure/$r 2>/dev/null)"; done

sec "memory"
free -m; swapon --show 2>/dev/null
grep -E "Dirty|Writeback|AnonPages|Mapped|Shmem|HugePages_Total|Hugepagesize" /proc/meminfo
sysctl vm.swappiness vm.min_free_kbytes vm.overcommit_memory vm.dirty_ratio vm.vfs_cache_pressure 2>/dev/null
echo "--- top RSS"; ps -eo pid,rss,pcpu,etime,comm --sort=-rss | head -12 | awk '{printf "%-8s %8.1f GB  cpu%-6s %-12s %s\n",$1,$2/1048576,$3,$4,$5}'
echo "--- swap holders"; for f in /proc/[0-9]*/status; do awk '/^Name:/{n=$2} /^VmSwap:/{if($2>50000)print $2/1024" MB", n}' "$f" 2>/dev/null; done | sort -rn | head -8

sec "cpu: what is burning it (2 samples 5s apart)"
top -bn2 -d 5 -o %CPU 2>/dev/null | awk '/^top -/{n++} n==2' | head -20
echo "--- loadavg $(cat /proc/loadavg)"
echo "--- threads: $(ps -eLf 2>/dev/null | wc -l) total, top by thread count:"; ps -eo nlwp,comm --sort=-nlwp | head -6

sec "gpu"
T=10 t nvidia-smi --query-gpu=name,driver_version,clocks.sm,clocks.max.sm,clocks.mem,power.draw,power.limit,temperature.gpu,utilization.gpu,utilization.memory,clocks_throttle_reasons.active --format=csv
T=10 t nvidia-smi -q -d PERFORMANCE | sed -n '/Clocks Event Reasons/,/^$/p;/Clocks Throttle Reasons/,/^$/p' | head -20
T=10 t nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
T=10 t nvidia-smi -q -d POWER | grep -E "Power Management|Power Draw|Power Limit|Default Power|Max Power|Current Power" | head -8

sec "docker: cpu/mem/net/io now"
T=25 t docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}'
echo "--- restarts / health / age"
for c in $(docker ps -a --format '{{.Names}}' 2>/dev/null); do
  docker inspect -f '{{.Name}} restarts={{.RestartCount}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}-{{end}} status={{.State.Status}} started={{.State.StartedAt}} restartpolicy={{.HostConfig.RestartPolicy.Name}}' "$c" 2>/dev/null
done
echo "--- images / disk"; T=20 t docker system df

sec "vLLM live metrics (Prometheus)"
for port in 8000 8002 8005; do
  m=$(curl -s --max-time 5 "http://127.0.0.1:$port/metrics" 2>/dev/null)
  [ -z "$m" ] && { echo ":$port no metrics"; continue; }
  echo ":$port"
  echo "$m" | grep -E '^vllm:(num_requests_running|num_requests_waiting|num_preemptions_total|gpu_cache_usage_perc|kv_cache_usage_perc|prefix_cache_(hits|queries)_total|request_success_total|spec_decode_num_(accepted|draft)_tokens_total|prompt_tokens_total|generation_tokens_total|time_to_first_token_seconds_(sum|count)|e2e_request_latency_seconds_(sum|count)|request_queue_time_seconds_(sum|count)|time_per_output_token_seconds_(sum|count))' | sed 's/{[^}]*}//' | head -30
done

sec "disk"
df -hT -x tmpfs -x devtmpfs -x squashfs -x overlay 2>/dev/null
lsblk -o NAME,ROTA,SIZE,TYPE,MOUNTPOINT 2>/dev/null | head -12
echo "--- model dirs"; T=25 t du -sh /srv/models/* 2>/dev/null | sort -rh | head -8
echo "--- io wait now"; T=8 t vmstat 1 4 | tail -4

sec "network"
ip -br a; ip route | head -6
for i in $(ls /sys/class/net | grep -v -E "^(lo|docker|br-|veth)"); do echo "$i: $(cat /sys/class/net/$i/speed 2>/dev/null || echo ?) Mb/s  mtu $(cat /sys/class/net/$i/mtu 2>/dev/null)  state $(cat /sys/class/net/$i/operstate 2>/dev/null)"; done
ss -s | head -3
echo "--- tailscale"; T=10 t tailscale status 2>/dev/null | head -8
echo "--- LISTENING (bind address matters: 0.0.0.0/:: = whole LAN)"
ss -ltnH 2>/dev/null | awk '{print $4}' | sed -E 's/:([0-9]+)$/ \1/' | sort -k2 -n | awk '{printf "%s:%s\n",$1,$2}' | tr '\n' ' '; echo
echo "--- tcp retrans/errors"; nstat -az 2>/dev/null | grep -E "TcpRetransSegs|TcpExtTCPTimeouts|TcpAttemptFails|TcpExtListenDrops|TcpExtListenOverflows" | head
echo "--- congestion/qdisc"; sysctl net.ipv4.tcp_congestion_control net.core.default_qdisc net.ipv4.tcp_slow_start_after_idle 2>/dev/null

sec "systemd: who wakes the box up"
echo "--- user timers"; systemctl --user list-timers --all --no-pager 2>/dev/null | head -12
echo "--- system timers (top)"; systemctl list-timers --no-pager 2>/dev/null | head -10
echo "--- failed units"; systemctl --failed --no-pager 2>/dev/null | head -8; systemctl --user --failed --no-pager 2>/dev/null | head -8
echo "--- user services"; systemctl --user list-units --type=service --state=running --no-pager 2>/dev/null | head -14

sec "watchdog / scanner cost"
for f in ~/ufo-watchdog/watchdog.log ~/ufo-watchdog/CHANGES.md; do
  [ -f "$f" ] && { echo "$f: $(wc -l < "$f") lines, $(du -h "$f" | cut -f1)"; }
done
echo "--- watchdog actions in the last day"; grep -E "ACTION|ERROR" ~/ufo-watchdog/watchdog.log 2>/dev/null | tail -n 12 | cut -c1-170
echo "--- last passes (duration = gaps between stamps)"; tail -n 6 ~/ufo-watchdog/watchdog.log 2>/dev/null | cut -c1-140
echo "--- memguard log"; tail -n 6 ~/ufo-galaxy/logs/memguard.log 2>/dev/null

sec "kernel / journal: OOM kills, hung tasks, thermal"
(T=10 t sudo -n dmesg -T 2>/dev/null || T=10 t dmesg -T 2>/dev/null) | grep -i -E "oom|out of memory|killed process|hung task|blocked for more|thermal|throttl|nvrm|xid" | tail -n 15
echo "--- journal errors (last 6h, count by unit)"; T=15 t journalctl --since "-6h" -p err --no-pager -o cat 2>/dev/null | wc -l
T=15 t journalctl --since "-6h" -p err --no-pager 2>/dev/null | awk '{print $5}' | sed 's/\[.*//' | sort | uniq -c | sort -rn | head -8

sec "ollama / other model servers"
systemctl --user is-active ollama 2>/dev/null; systemctl is-active ollama 2>/dev/null
T=5 t curl -s --max-time 4 http://127.0.0.1:11434/api/ps | head -c 300; echo
for p in 8000 8002 8004 8005 7861 5001 4000; do
  code=$(curl -s -o /dev/null -w '%{http_code} %{time_total}s' --max-time 4 "http://127.0.0.1:$p/" 2>/dev/null); echo ":$p -> ${code:-none}"
done

sec "local API latency on the box (no tunnel): 20x GET /v1/models"
for p in 8000 8002; do
  curl -s -o /dev/null -w '%{time_total}\n' --max-time 5 --parallel-max 1 $(for i in $(seq 20); do printf 'http://127.0.0.1:%s/v1/models ' "$p"; done) 2>/dev/null \
   | sort -n | awk -v p="$p" '{a[NR]=$1} END{printf ":%s min %.1fms  median %.1fms  max %.1fms\n", p, a[1]*1000, a[int(NR/2)+1]*1000, a[NR]*1000}'
done
echo SURVEY_DONE
