#!/bin/sh
# Push podman container metrics to VictoriaMetrics
# Replaces podman-exporter (hardcoded 10s timeout incompatible with 35+ containers)
# Runs via cron every 60 seconds
VM_URL="http://localhost:8428/api/v1/import/prometheus"
TMPFILE=$(mktemp)

pb() {
    echo "$1" | awk '{gsub(/GB/,"*1073741824"); gsub(/MB/,"*1048576"); gsub(/kB/,"*1024"); gsub(/B/,"*1"); print}' | bc 2>/dev/null | cut -d. -f1
}

# Container info: id, name, pod, image, state, created
podman ps -a --format "{{.ID}}|{{.Names}}|{{.PodName}}|{{.Image}}|{{.Status}}|{{.CreatedAt}}" --no-trunc 2>/dev/null | while IFS="|" read -r id name pod image status created; do
    case "$name" in *-infra) continue;; esac
    state="running"
    echo "$status" | grep -qi "exited\|stopped\|dead" && state="exited"
    case "$state" in running) sv=2;; exited) sv=5;; stopped) sv=3;; paused) sv=4;; *) sv=0;; esac
    # Parse created timestamp to epoch (strip nanoseconds for busybox date)
    csec=$(date -d "$(echo "$created" | cut -d. -f1)" +%s 2>/dev/null || echo 0)
    echo "podman_container_info{id=\"${id}\",name=\"${name}\",pod_name=\"${pod}\",image=\"${image}\"} 1" >> "$TMPFILE"
    echo "podman_container_state{id=\"${id}\",name=\"${name}\"} ${sv}" >> "$TMPFILE"
    echo "podman_container_created_seconds{id=\"${id}\",name=\"${name}\"} ${csec}" >> "$TMPFILE"
done

# Stats: cpu, memory, net I/O, block I/O, pids
podman stats --no-stream --format "{{.ID}}|{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.NetIO}}|{{.BlockIO}}|{{.PIDs}}" --no-trunc 2>/dev/null | while IFS="|" read -r id name cpuraw memraw netraw blockraw pids; do
    case "$name" in *-infra) continue;; esac

    # CPU (convert percent to fractional seconds approximation)
    cpu=$(echo "$cpuraw" | sed 's/%//')

    # Memory
    usage=$(echo "$memraw" | awk -F' / ' '{print $1}')
    limit=$(echo "$memraw" | awk -F' / ' '{print $2}')
    mu=$(pb "$usage")
    ml=$(pb "$limit")

    # Network I/O
    netin=$(echo "$netraw" | awk -F' / ' '{print $1}')
    netout=$(echo "$netraw" | awk -F' / ' '{print $2}')
    ni=$(pb "$netin")
    no=$(pb "$netout")

    # Block I/O
    blockin=$(echo "$blockraw" | awk -F' / ' '{print $1}')
    blockout=$(echo "$blockraw" | awk -F' / ' '{print $2}')
    bi=$(pb "$blockin")
    bo=$(pb "$blockout")

    # CPU percent as gauge
    cpuval=$(echo "$cpuraw" | sed 's/%//')
    echo "podman_container_cpu_percent{id=\"${id}\",name=\"${name}\"} ${cpuval:-0}" >> "$TMPFILE"
    echo "podman_container_mem_usage_bytes{id=\"${id}\",name=\"${name}\"} ${mu:-0}" >> "$TMPFILE"
    echo "podman_container_mem_limit_bytes{id=\"${id}\",name=\"${name}\"} ${ml:-0}" >> "$TMPFILE"
    echo "podman_container_net_input_total{id=\"${id}\",name=\"${name}\"} ${ni:-0}" >> "$TMPFILE"
    echo "podman_container_net_output_total{id=\"${id}\",name=\"${name}\"} ${no:-0}" >> "$TMPFILE"
    echo "podman_container_block_input_total{id=\"${id}\",name=\"${name}\"} ${bi:-0}" >> "$TMPFILE"
    echo "podman_container_block_output_total{id=\"${id}\",name=\"${name}\"} ${bo:-0}" >> "$TMPFILE"
    echo "podman_container_pids{id=\"${id}\",name=\"${name}\"} ${pids:-0}" >> "$TMPFILE"
done

curl -s --data-binary @"$TMPFILE" "$VM_URL" 2>/dev/null
rm -f "$TMPFILE"
