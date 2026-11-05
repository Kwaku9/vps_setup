"""Live pod names reach every service, managed or not (2026-11-05).

Before: managed services kept their hand-typed profiles.yaml pod (often none),
and unmanaged ones got the bare pod ID, so the Services tab filed trading-pod's
containers under "standalone".
"""
from types import SimpleNamespace

from ops_dashboard.api.dependencies import merge_live_containers
from ops_dashboard.models import EndpointType, Service, ServicePlatform


def _state(**services):
    return SimpleNamespace(services=dict(services))


def _managed(name, pod=None):
    return Service(name=name, platform=ServicePlatform.VPS, endpoint_type=EndpointType.POD, pod=pod)


def test_managed_service_gets_live_pod_name():
    state = _state(ibeam=_managed("ibeam"))
    merge_live_containers(state, [{"Names": ["ibeam"], "Pod": "06a541baaadf", "PodName": "trading-pod"}])
    assert state.services["ibeam"].pod == "trading-pod"
    assert state.services["ibeam"].managed is True


def test_live_pod_name_overrides_stale_profile_value():
    state = _state(litellm=_managed("litellm", pod="ai-stack-pod"))
    merge_live_containers(state, [{"Names": ["litellm"], "PodName": "ai-gateway-pod"}])
    assert state.services["litellm"].pod == "ai-gateway-pod"


def test_unmanaged_container_gets_name_not_id():
    state = _state()
    merge_live_containers(state, [{"Names": ["piper-tts"], "Pod": "deadbeef1234", "PodName": "ai-gateway-pod"}])
    assert state.services["piper-tts"].pod == "ai-gateway-pod"
    assert state.services["piper-tts"].managed is False


def test_container_outside_any_pod_stays_standalone():
    state = _state(traefik=_managed("traefik"))
    merge_live_containers(state, [{"Names": ["traefik"], "Pod": "", "PodName": ""}])
    assert state.services["traefik"].pod is None


def test_missing_podname_does_not_erase_known_pod():
    # Control: an older podman (no --pod) must not wipe a pod we already know.
    state = _state(ibeam=_managed("ibeam", pod="trading-pod"))
    merge_live_containers(state, [{"Names": ["ibeam"], "Pod": "06a541baaadf"}])
    assert state.services["ibeam"].pod == "trading-pod"
