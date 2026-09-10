import pytest

from terminal_topology import TopologyError, bind_certificate, resolve_pane


def test_certificate_binding_requires_two_channels():
    pane = {"bridge_id": "pane_1", "title": "cert", "certificate": None}
    topology = {"panes": [pane]}
    result = bind_certificate(topology, "cert", {"pid": 7, "process_start_time": "s", "process_image": "pwsh"}, "cert output")
    assert result["bridge_id"] == "pane_1"


def test_certificate_binding_rejects_ambiguous_title():
    with pytest.raises(TopologyError, match="2 panes"):
        bind_certificate({"panes": [{"title": "cert"}, {"title": "cert"}]}, "cert", {"pid": 7, "process_start_time": "s", "process_image": "pwsh"}, "cert")


def test_resolve_pane_rejects_stale_id():
    with pytest.raises(TopologyError, match="STALE_PANE"):
        resolve_pane({"panes": []}, "pane_missing")
