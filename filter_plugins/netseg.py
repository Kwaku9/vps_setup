"""Ansible filters for the zone moves (network/zones.yml + netseg_moved_zones in all.yml).

netseg_pods(doc, moved, flat)  -> {pod: {zone, network, ip, host}} for every pod in the model.
    A pod whose zone is in `moved` gets its zone network, its fixed IP and the dial name `<pod>.zone` (served by the
    host's Unbound); every other pod stays on `flat` under its own name, with no fixed IP.
netseg_dns_records(doc, moved) -> [(pod, ip)] for the Unbound `.zone` records: only moved pods, so a name never points
    at an address nothing is listening on.
"""

ZONE_SUFFIX = "zone"


def _check(doc, moved):
    unknown = sorted(set(moved) - set(doc["zones"]))
    if unknown:
        raise ValueError(f"netseg_moved_zones names zones that are not in network/zones.yml: {unknown}")


def netseg_pods(doc, moved, flat):
    moved = list(moved or [])
    _check(doc, moved)
    out = {}
    for key, zone in doc["zones"].items():
        for pod, spec in (zone.get("pods") or {}).items():
            if key in moved:
                out[pod] = {"zone": key, "network": [zone["name"]], "ip": spec["ip"], "host": f"{pod}.{ZONE_SUFFIX}"}
            else:
                out[pod] = {"zone": key, "network": [flat], "ip": None, "host": pod}
    return out


def netseg_dns_records(doc, moved):
    moved = list(moved or [])
    _check(doc, moved)
    return [(pod, spec["ip"]) for key, zone in doc["zones"].items() if key in moved
            for pod, spec in (zone.get("pods") or {}).items()]


class FilterModule(object):
    def filters(self):
        return {"netseg_pods": netseg_pods, "netseg_dns_records": netseg_dns_records}
