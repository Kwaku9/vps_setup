#!/bin/sh
# Trivy Container Vulnerability Scanner
# Scans all running Podman container images and pushes metrics to VictoriaMetrics
# Designed to run as a daily cron job

set -e

VM_PUSH_URL="http://localhost:8428/api/v1/import/prometheus"
METRICS_FILE="/tmp/trivy_metrics.prom"
TRIVY_CACHE="/var/cache/trivy"
SCAN_START=$(date +%s)

mkdir -p "$TRIVY_CACHE"

# Initialize metrics file
cat > "$METRICS_FILE" <<'HEADER'
# HELP trivy_vulnerabilities_total Total vulnerabilities across all images by severity
# TYPE trivy_vulnerabilities_total gauge
# HELP trivy_vulnerability_count Vulnerabilities per image by severity
# TYPE trivy_vulnerability_count gauge
# HELP trivy_images_scanned Total images scanned
# TYPE trivy_images_scanned gauge
# HELP trivy_images_with_critical Images with at least one CRITICAL vulnerability
# TYPE trivy_images_with_critical gauge
# HELP trivy_scan_timestamp Unix timestamp of last scan
# TYPE trivy_scan_timestamp gauge
# HELP trivy_scan_errors Number of scan errors
# TYPE trivy_scan_errors gauge
# HELP trivy_vulnerability_id Individual vulnerability details
# TYPE trivy_vulnerability_id gauge
# HELP trivy_vulnerability_detail_timestamp Unix timestamp of detail scan
# TYPE trivy_vulnerability_detail_timestamp gauge
HEADER

# Get unique images from running containers
images=$(podman ps --format '{{.Image}}' | sort -u)
image_count=$(echo "$images" | wc -l | tr -d ' ')
images_with_critical=0
scan_errors=0

# Totals per severity
total_critical=0
total_high=0
total_medium=0
total_low=0

echo "$(date '+%Y-%m-%d %H:%M:%S') Starting Trivy scan of $image_count images"

for image in $images; do
    # Sanitize image name for use in labels
    safe_image=$(echo "$image" | sed 's/"/\\"/g')

    # Extract repo and tag
    image_repo=$(echo "$image" | sed 's/:.*$//' | sed 's|.*/||')
    image_tag=$(echo "$image" | grep -o ':[^:]*$' | sed 's/://' || echo "latest")

    echo "  Scanning: $image"

    # Run Trivy scan with low priority
    json_file="/tmp/trivy_scan_${image_count}.json"
    if nice -n 19 trivy image --format json --quiet \
        --cache-dir "$TRIVY_CACHE" \
        --severity CRITICAL,HIGH,MEDIUM,LOW \
        --skip-db-update \
        "$image" > "$json_file" 2>/dev/null; then

        # Count vulnerabilities per severity
        for sev in CRITICAL HIGH MEDIUM LOW; do
            count=$(jq "[.Results[]?.Vulnerabilities[]? | select(.Severity==\"$sev\")] | length" "$json_file" 2>/dev/null || echo "0")
            echo "trivy_vulnerability_count{image=\"${safe_image}\",severity=\"${sev}\"} ${count}" >> "$METRICS_FILE"

            # Add to totals
            case $sev in
                CRITICAL) total_critical=$((total_critical + count)) ;;
                HIGH)     total_high=$((total_high + count)) ;;
                MEDIUM)   total_medium=$((total_medium + count)) ;;
                LOW)      total_low=$((total_low + count)) ;;
            esac
        done

        # Check if image has CRITICAL vulns
        crit_count=$(jq "[.Results[]?.Vulnerabilities[]? | select(.Severity==\"CRITICAL\")] | length" "$json_file" 2>/dev/null || echo "0")
        if [ "$crit_count" -gt 0 ] 2>/dev/null; then
            images_with_critical=$((images_with_critical + 1))
        fi

        # Extract individual CVE details (limit to CRITICAL and HIGH to keep metrics manageable)
        jq -r '
            .Results[]? |
            .Target as $target |
            .Vulnerabilities[]? |
            select(.Severity == "CRITICAL" or .Severity == "HIGH") |
            "trivy_vulnerability_id{image_repository=\"'"${image_repo}"'\",image_tag=\"'"${image_tag}"'\",severity=\"\(.Severity)\",vuln_id=\"\(.VulnerabilityID)\",resource=\"\(.PkgName // "unknown")\",installed_version=\"\(.InstalledVersion // "")\",fixed_version=\"\(.FixedVersion // "")\",vuln_title=\"\(.Title // "" | gsub("[\"\\\\]"; "_") | .[0:80])\"} 1"
        ' "$json_file" 2>/dev/null >> "$METRICS_FILE"
    else
        scan_errors=$((scan_errors + 1))
        echo "    ERROR scanning $image"
        # Still emit zero counts for failed scans
        for sev in CRITICAL HIGH MEDIUM LOW; do
            echo "trivy_vulnerability_count{image=\"${safe_image}\",severity=\"${sev}\"} 0" >> "$METRICS_FILE"
        done
    fi

    rm -f "$json_file"
done

# Write summary metrics
SCAN_END=$(date +%s)
SCAN_DURATION=$((SCAN_END - SCAN_START))

cat >> "$METRICS_FILE" <<EOF
trivy_vulnerabilities_total{severity="CRITICAL"} ${total_critical}
trivy_vulnerabilities_total{severity="HIGH"} ${total_high}
trivy_vulnerabilities_total{severity="MEDIUM"} ${total_medium}
trivy_vulnerabilities_total{severity="LOW"} ${total_low}
trivy_images_scanned ${image_count}
trivy_images_with_critical ${images_with_critical}
trivy_scan_timestamp ${SCAN_END}
trivy_scan_errors ${scan_errors}
trivy_vulnerability_detail_timestamp ${SCAN_END}
EOF

# Push to VictoriaMetrics
curl -s -X POST "$VM_PUSH_URL" -d @"$METRICS_FILE"

echo "$(date '+%Y-%m-%d %H:%M:%S') Scan complete: ${image_count} images, ${total_critical} CRITICAL, ${total_high} HIGH, ${total_medium} MEDIUM, ${total_low} LOW (${SCAN_DURATION}s)"
