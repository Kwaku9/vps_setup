#!/bin/sh
# unbound-stats: host resolver health for node-exporter's textfile collector.
# Managed by Ansible (roles/tailscale/files/unbound-stats.sh), run every minute
# from cron by the tailscale role.
#
# Reads `unbound-control stats_noreset` over the local control socket and
# probes the dnscrypt-proxy fallback, then writes unbound.prom atomically
# (temp file + rename): node-exporter drops a whole file it cannot parse, so a
# half-written file would blank every series in it.
#
# unbound_up says whether unbound answered the control socket. When it did not,
# only the health series are written, and the last-success timestamp is carried
# over from the previous file so staleness stays measurable.
set -u

DIR="${UNBOUND_TEXTFILE_DIR:-/opt/compose/textfile-collector}"
FALLBACK="${DNS_FALLBACK_ADDR:-127.0.0.2}"
PROBE_NAME="${DNS_PROBE_NAME:-one.one.one.one}"
OUT="$DIR/unbound.prom"
TMP="$OUT.$$.tmp"

[ -d "$DIR" ] || exit 0
trap 'rm -f "$TMP"' EXIT

now=$(date +%s)

if stats=$(timeout 10 unbound-control stats_noreset 2>/dev/null) && [ -n "$stats" ]; then
    up=1
    last=$now
else
    up=0
    stats=""
    last=$(awk '/^unbound_collector_last_success_timestamp_seconds /{print $2}' "$OUT" 2>/dev/null)
    last=${last:-0}
fi

# The probe targets the fallback directly, so it never appears in unbound's log.
if timeout 5 nslookup "$PROBE_NAME" "$FALLBACK" >/dev/null 2>&1; then
    fallback_up=1
else
    fallback_up=0
fi

{
    echo "# HELP unbound_up 1 if unbound answered unbound-control stats on its control socket."
    echo "# TYPE unbound_up gauge"
    echo "unbound_up $up"
    echo "# HELP unbound_collector_last_success_timestamp_seconds Last time unbound-stats read unbound's counters."
    echo "# TYPE unbound_collector_last_success_timestamp_seconds gauge"
    echo "unbound_collector_last_success_timestamp_seconds $last"
    echo "# HELP dns_fallback_up 1 if the dnscrypt-proxy fallback resolved the probe name."
    echo "# TYPE dns_fallback_up gauge"
    echo "dns_fallback_up $fallback_up"

    printf '%s\n' "$stats" | awk -F= '
    function add(fam, type, help, labels, val) {
        if (!(fam in ftype)) { order[++n] = fam; ftype[fam] = type; fhelp[fam] = help }
        lines[fam] = lines[fam] fam labels " " val "\n"
    }
    NF == 2 && $2 ~ /^[0-9.eE+-]+$/ {
        k = $1; v = $2
        if      (k == "total.num.queries")            add("unbound_queries_total", "counter", "Queries received.", "", v)
        else if (k == "total.num.cachehits")          add("unbound_cache_hits_total", "counter", "Queries answered from cache.", "", v)
        else if (k == "total.num.cachemiss")          add("unbound_cache_misses_total", "counter", "Queries that needed recursion.", "", v)
        else if (k == "total.num.prefetch")           add("unbound_prefetches_total", "counter", "Cache prefetches.", "", v)
        else if (k == "total.num.expired")            add("unbound_expired_answers_total", "counter", "Answers served from expired cache.", "", v)
        else if (k == "total.num.recursivereplies")   add("unbound_recursive_replies_total", "counter", "Replies sent after recursion.", "", v)
        else if (k == "total.num.queries_timed_out")  add("unbound_queries_timed_out_total", "counter", "Queries dropped after waiting too long.", "", v)
        else if (k == "total.requestlist.avg")        add("unbound_requestlist_avg", "gauge", "Average pending recursive requests.", "", v)
        else if (k == "total.requestlist.max")        add("unbound_requestlist_max", "gauge", "Peak pending recursive requests.", "", v)
        else if (k == "total.requestlist.exceeded")   add("unbound_requestlist_exceeded_total", "counter", "Requests dropped because the list was full.", "", v)
        else if (k == "total.requestlist.current.all") add("unbound_requestlist_current", "gauge", "Pending recursive requests now.", "", v)
        else if (k == "total.recursion.time.avg")     add("unbound_recursion_time_avg_seconds", "gauge", "Mean recursion time.", "", v)
        else if (k == "total.recursion.time.median")  add("unbound_recursion_time_median_seconds", "gauge", "Median recursion time.", "", v)
        else if (k == "time.up")                      add("unbound_uptime_seconds", "gauge", "Seconds since unbound started.", "", v)
        else if (k == "num.answer.secure")            add("unbound_answers_secure_total", "counter", "DNSSEC-validated answers.", "", v)
        else if (k == "num.answer.bogus")             add("unbound_answers_bogus_total", "counter", "Answers that failed DNSSEC validation.", "", v)
        else if (k == "num.rrset.bogus")              add("unbound_rrset_bogus_total", "counter", "RRsets marked bogus by the validator.", "", v)
        else if (k == "unwanted.queries")             add("unbound_unwanted_queries_total", "counter", "Queries refused by access control.", "", v)
        else if (k == "unwanted.replies")             add("unbound_unwanted_replies_total", "counter", "Unsolicited replies (possible spoofing).", "", v)
        else if (k ~ /^num\.query\.type\./)   { sub(/^num\.query\.type\./, "", k);   add("unbound_query_types_total", "counter", "Queries by record type.", "{type=\"" k "\"}", v) }
        else if (k ~ /^num\.query\.class\./)  { sub(/^num\.query\.class\./, "", k);  add("unbound_query_classes_total", "counter", "Queries by class.", "{class=\"" k "\"}", v) }
        else if (k ~ /^num\.query\.opcode\./) { sub(/^num\.query\.opcode\./, "", k); add("unbound_query_opcodes_total", "counter", "Queries by opcode.", "{opcode=\"" k "\"}", v) }
        else if (k ~ /^num\.answer\.rcode\./) { sub(/^num\.answer\.rcode\./, "", k); add("unbound_answer_rcodes_total", "counter", "Answers by response code.", "{rcode=\"" k "\"}", v) }
        else if (k ~ /^num\.query\.(tcp|tls|ipv6|https)$/) { sub(/^num\.query\./, "", k); add("unbound_query_transport_total", "counter", "Queries by transport.", "{transport=\"" k "\"}", v) }
        else if (k ~ /^mem\.cache\./) { sub(/^mem\.cache\./, "", k); add("unbound_memory_cache_bytes", "gauge", "Cache memory.", "{cache=\"" k "\"}", v) }
        else if (k ~ /^mem\.mod\./)   { sub(/^mem\.mod\./, "", k);   add("unbound_memory_module_bytes", "gauge", "Module memory.", "{module=\"" k "\"}", v) }
        else if (k ~ /^(msg|rrset|infra|key)\.cache\.count$/) { sub(/\.cache\.count$/, "", k); add("unbound_cache_entries", "gauge", "Entries per cache.", "{cache=\"" k "\"}", v) }
    }
    END {
        for (i = 1; i <= n; i++) {
            f = order[i]
            print "# HELP " f " " fhelp[f]
            print "# TYPE " f " " ftype[f]
            printf "%s", lines[f]
        }
    }'
} > "$TMP" && chmod 0644 "$TMP" && mv "$TMP" "$OUT"
