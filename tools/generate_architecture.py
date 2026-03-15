#!/usr/bin/env python3
"""
AICortex Cloud Infrastructure Architecture Diagram Generator

Generates a comprehensive draw.io XML file with togglable layers:
  1. Infrastructure (always visible) - pods, containers, VPS boundary
  2. User Transaction Flow - end-to-end user journey
  3. Container Networking - Podman bridge, aardvark-dns, pod IPs
  4. Security Layers - WAF, firewall, TLS, auth, encryption
  5. Observability Pipeline - metrics, logs, traces, SIEM
  6. AI Model Ecosystem - providers, model routing, TTS, AWS GPU inference
  7. Claude Code & MCP - CLI agents, MCP tool servers
  8. Engineering Details - IPs, ports, versions, env vars

Usage:
    python3 tools/generate_architecture.py
    # Output: architecture.drawio
"""

import xml.etree.ElementTree as ET
from xml.dom import minidom
import html
import sys
import os

# ============================================================================
# STYLE CONSTANTS
# ============================================================================

# Color palette
COLORS = {
    "bg_vps": "#F5F5F5",
    "bg_pod_ai": "#E3F2FD",
    "bg_pod_auth": "#F3E5F5",
    "bg_pod_mon": "#FFF3E0",
    "bg_pod_sec": "#FFEBEE",
    "bg_pod_mgmt": "#E8F5E9",
    "bg_pod_front": "#ECEFF1",
    "bg_cloudflare": "#FFF8E1",
    "bg_provider": "#FAFAFA",
    "bg_claude": "#EDE7F6",
    "container_running": "#C8E6C9",
    "container_stopped": "#FFCDD2",
    "container_db": "#BBDEFB",
    "stroke_pod": "#90A4AE",
    "stroke_user_flow": "#1565C0",
    "stroke_security": "#C62828",
    "stroke_observability": "#2E7D32",
    "stroke_ai_model": "#E65100",
    "stroke_claude": "#6A1B9A",
    "stroke_internal": "#757575",
    "firewall": "#D32F2F",
    "tls": "#1B5E20",
    "highlight": "#FF6F00",
    # Networking layer
    "stroke_networking": "#00897B",
    # AWS
    "aws_orange": "#FF9900",
    "aws_fill": "#FFF8F0",
    "aws_vpc": "#E8F4FD",
    "aws_gpu_fill": "#C8E6C9",
}

STYLES = {
    # Shapes
    "title": "text;html=1;align=center;verticalAlign=middle;resizable=0;points=[];autosize=1;strokeColor=none;fillColor=none;fontSize=24;fontStyle=1;fontColor=#263238;",
    "subtitle": "text;html=1;align=center;verticalAlign=middle;resizable=0;points=[];autosize=1;strokeColor=none;fillColor=none;fontSize=14;fontColor=#546E7A;",
    "user": "shape=mxgraph.basic.user;fillColor=#1565C0;fontColor=#FFFFFF;strokeColor=#0D47A1;fontSize=12;fontStyle=1;",
    "internet": "ellipse;shape=cloud;whiteSpace=wrap;html=1;fillColor=#F5F5F5;strokeColor=#BDBDBD;fontSize=13;fontStyle=1;",
    "cloudflare_zone": f"rounded=1;whiteSpace=wrap;html=1;fillColor={COLORS['bg_cloudflare']};strokeColor=#F9A825;strokeWidth=2;fontSize=13;fontStyle=1;arcSize=8;container=1;collapsible=0;",
    "cf_service": "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#F9A825;fontSize=11;arcSize=12;",
    "cf_access": "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFE082;strokeColor=#F57F17;fontSize=11;fontStyle=1;arcSize=12;",
    "vps_boundary": f"rounded=1;whiteSpace=wrap;html=1;fillColor={COLORS['bg_vps']};strokeColor=#78909C;strokeWidth=3;dashed=1;dashPattern=8 4;fontSize=14;fontStyle=1;verticalAlign=top;arcSize=4;container=1;collapsible=0;",
    "firewall_bar": f"rounded=1;whiteSpace=wrap;html=1;fillColor={COLORS['firewall']};strokeColor=#B71C1C;fontSize=11;fontColor=#FFFFFF;fontStyle=1;arcSize=4;",
    "pod": "rounded=1;whiteSpace=wrap;html=1;strokeWidth=2;fontSize=12;fontStyle=1;verticalAlign=top;arcSize=6;container=1;collapsible=0;",
    "container": "rounded=1;whiteSpace=wrap;html=1;fontSize=10;arcSize=10;",
    "container_db": f"shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;size=8;fillColor={COLORS['container_db']};strokeColor=#42A5F5;fontSize=10;",
    "standalone": "rounded=1;whiteSpace=wrap;html=1;fontSize=11;arcSize=10;strokeWidth=2;",
    "provider": f"rounded=1;whiteSpace=wrap;html=1;fillColor={COLORS['bg_provider']};strokeColor=#BDBDBD;fontSize=11;arcSize=8;container=1;collapsible=0;",
    "provider_model": "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#E0E0E0;fontSize=9;arcSize=12;",
    "mcp_server": "rounded=1;whiteSpace=wrap;html=1;fillColor=#EDE7F6;strokeColor=#7E57C2;fontSize=10;arcSize=10;",
    "shield": "shape=mxgraph.basic.shield;fillColor=#FFCDD2;strokeColor=#C62828;fontSize=10;fontStyle=1;",
    "lock": "shape=mxgraph.signs.safety.padlock;fillColor=#1B5E20;strokeColor=#1B5E20;fontSize=9;fontColor=#1B5E20;",
    "legend_box": "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#E0E0E0;fontSize=10;verticalAlign=top;arcSize=6;container=1;collapsible=0;",
    "legend_item": "rounded=1;whiteSpace=wrap;html=1;fontSize=9;arcSize=12;",
    "label": "text;html=1;align=center;verticalAlign=middle;resizable=0;points=[];autosize=1;strokeColor=none;fillColor=none;fontSize=9;fontColor=#78909C;",
    "engineering_label": "text;html=1;align=left;verticalAlign=middle;resizable=0;points=[];autosize=1;strokeColor=none;fillColor=#FFFDE7;fontSize=8;fontColor=#37474F;",
    # Edges
    "edge_user": f"edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;strokeColor={COLORS['stroke_user_flow']};strokeWidth=3;flowAnimation=1;",
    "edge_security": f"edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;strokeColor={COLORS['stroke_security']};strokeWidth=2;dashed=1;dashPattern=4 4;",
    "edge_observability": f"edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;strokeColor={COLORS['stroke_observability']};strokeWidth=2;flowAnimation=1;",
    "edge_ai": f"edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;strokeColor={COLORS['stroke_ai_model']};strokeWidth=2;flowAnimation=1;",
    "edge_claude": f"edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;strokeColor={COLORS['stroke_claude']};strokeWidth=2;flowAnimation=1;dashed=1;dashPattern=8 4;",
    "edge_internal": f"edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;strokeColor={COLORS['stroke_internal']};strokeWidth=1;",
    "edge_tls": f"edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;strokeColor={COLORS['tls']};strokeWidth=2;flowAnimation=1;",
    # Networking layer edges
    "edge_dns": f"edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;strokeColor={COLORS['stroke_networking']};strokeWidth=2;dashed=1;dashPattern=6 3;",
    "edge_pod_network": f"edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;strokeColor=#1565C0;strokeWidth=1;dashed=1;dashPattern=3 3;",
    "network_annotation": f"text;html=1;align=center;verticalAlign=middle;resizable=0;points=[];autosize=1;strokeColor=none;fillColor=none;fontSize=9;fontColor={COLORS['stroke_networking']};fontStyle=1;",
    # AWS styles
    "aws_cloud": f"rounded=1;whiteSpace=wrap;html=1;fillColor={COLORS['aws_fill']};strokeColor={COLORS['aws_orange']};strokeWidth=3;fontSize=14;fontStyle=1;verticalAlign=top;arcSize=6;container=1;collapsible=0;",
    "aws_vpc": f"rounded=1;whiteSpace=wrap;html=1;fillColor={COLORS['aws_vpc']};strokeColor=#1976D2;strokeWidth=2;dashed=1;dashPattern=8 4;fontSize=12;fontStyle=1;verticalAlign=top;arcSize=4;container=1;collapsible=0;",
    "aws_subnet": "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#43A047;strokeWidth=1;dashed=1;fontSize=10;fontStyle=1;verticalAlign=top;arcSize=4;container=1;collapsible=0;",
    "aws_subnet_private": "rounded=1;whiteSpace=wrap;html=1;fillColor=#F3E5F5;strokeColor=#1565C0;strokeWidth=1;dashed=1;fontSize=10;fontStyle=1;verticalAlign=top;arcSize=4;container=1;collapsible=0;",
    "aws_service": f"rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor={COLORS['aws_orange']};fontSize=10;arcSize=10;",
    "aws_gpu": f"rounded=1;whiteSpace=wrap;html=1;fillColor={COLORS['aws_gpu_fill']};strokeColor=#2E7D32;fontSize=10;fontStyle=1;arcSize=10;strokeWidth=2;",
    "aws_lambda": "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFF3E0;strokeColor=#F57C00;fontSize=9;arcSize=12;",
    "aws_storage": f"shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;size=8;fillColor=#FFFFFF;strokeColor={COLORS['aws_orange']};fontSize=10;",
    "edge_aws": f"edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;strokeColor={COLORS['aws_orange']};strokeWidth=2;flowAnimation=1;",
    "edge_aws_dashed": f"edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;strokeColor={COLORS['aws_orange']};strokeWidth=2;dashed=1;dashPattern=6 3;",
}


# ============================================================================
# DIAGRAM BUILDER
# ============================================================================

class DiagramBuilder:
    def __init__(self):
        self.cells = []
        self._id_counter = 100

    def _next_id(self):
        self._id_counter += 1
        return str(self._id_counter)

    def add_cell(self, id=None, value="", style="", vertex=True, edge=False,
                 parent="1", x=0, y=0, w=100, h=50,
                 source=None, target=None, relative=False):
        if id is None:
            id = self._next_id()
        self.cells.append({
            "id": id, "value": value, "style": style,
            "vertex": vertex, "edge": edge, "parent": parent,
            "x": x, "y": y, "w": w, "h": h,
            "source": source, "target": target, "relative": relative,
        })
        return id

    def add_edge(self, id=None, value="", style="", parent="1",
                 source=None, target=None):
        if id is None:
            id = self._next_id()
        self.cells.append({
            "id": id, "value": value, "style": style,
            "vertex": False, "edge": True, "parent": parent,
            "source": source, "target": target, "relative": True,
        })
        return id

    def to_xml(self):
        mxfile = ET.Element("mxfile", {
            "host": "app.diagrams.net",
            "modified": "2026-02-17T00:00:00.000Z",
            "agent": "AICortex Architecture Generator",
            "version": "25.0.3",
            "type": "device",
        })
        diagram = ET.SubElement(mxfile, "diagram", {
            "id": "main",
            "name": "AICortex Cloud Infrastructure",
        })
        model = ET.SubElement(diagram, "mxGraphModel", {
            "dx": "2400", "dy": "1600",
            "grid": "1", "gridSize": "10", "guides": "1",
            "tooltips": "1", "connect": "1", "arrows": "1",
            "fold": "1", "page": "1", "pageScale": "1",
            "pageWidth": "7400", "pageHeight": "4800",
            "math": "0", "shadow": "0",
        })
        root = ET.SubElement(model, "root")

        # Root cells
        ET.SubElement(root, "mxCell", {"id": "0"})
        ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

        # Layers
        layers = [
            ("layer_security", "Security Layers", "1"),
            ("layer_userflow", "User Transaction Flow", "1"),
            ("layer_networking", "Container Networking", "0"),
            ("layer_observability", "Observability Pipeline", "1"),
            ("layer_aimodels", "AI Model Ecosystem", "1"),
            ("layer_claude", "Claude Code &amp; MCP", "1"),
            ("layer_engineering", "Engineering Details", "0"),
        ]
        for lid, lname, visible in layers:
            ET.SubElement(root, "mxCell", {
                "id": lid, "value": lname,
                "style": "locked=0;",
                "parent": "0", "visible": visible,
            })

        # All diagram cells
        for c in self.cells:
            attrs = {"id": c["id"], "value": c["value"], "style": c["style"]}
            if c.get("parent"):
                attrs["parent"] = c["parent"]
            if c.get("vertex"):
                attrs["vertex"] = "1"
            if c.get("edge"):
                attrs["edge"] = "1"
            if c.get("source"):
                attrs["source"] = c["source"]
            if c.get("target"):
                attrs["target"] = c["target"]
            if c.get("connectable") == False:
                attrs["connectable"] = "0"

            cell = ET.SubElement(root, "mxCell", attrs)

            if c.get("edge"):
                geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
            elif c.get("vertex"):
                geo_attrs = {
                    "x": str(c.get("x", 0)),
                    "y": str(c.get("y", 0)),
                    "width": str(c.get("w", 100)),
                    "height": str(c.get("h", 50)),
                    "as": "geometry",
                }
                ET.SubElement(cell, "mxGeometry", geo_attrs)

        # Pretty print
        rough = ET.tostring(mxfile, encoding="unicode")
        dom = minidom.parseString(rough)
        return dom.toprettyxml(indent="  ", encoding=None)


# ============================================================================
# BUILD THE DIAGRAM
# ============================================================================

def build_diagram():
    b = DiagramBuilder()

    # ========================================================================
    # TITLE
    # ========================================================================
    b.add_cell("title", "<b>AICortex Cloud</b> — Full Infrastructure Architecture", STYLES["title"],
               x=1600, y=10, w=800, h=40)
    b.add_cell("subtitle",
               "Alpine Linux VPS (REDACTED_IP) | Podman Pods | Cloudflare Tunnel | enterprise_network REDACTED_CIDR | AWS GPU Inference (us-east-1)",
               STYLES["subtitle"], x=1400, y=50, w=1200, h=30)

    # ========================================================================
    # LAYER: INFRASTRUCTURE — External Zone
    # ========================================================================

    # -- Users --
    user_id = b.add_cell("user", "Users /<br/>Browsers", STYLES["user"],
                         x=1900, y=100, w=80, h=80)

    # -- Internet Cloud --
    internet_id = b.add_cell("internet", "Internet", STYLES["internet"],
                             x=1700, y=200, w=480, h=70)

    # -- Cloudflare Zone --
    cf_zone = b.add_cell("cf_zone", "<b>Cloudflare</b> — *.REDACTED_DOMAIN", STYLES["cloudflare_zone"],
                         x=900, y=310, w=2200, h=130)
    cf_dns = b.add_cell("cf_dns", "<b>DNS</b><br/>CNAME *.REDACTED_DOMAIN<br/>→ Tunnel", STYLES["cf_service"],
                        parent="cf_zone", x=30, y=35, w=200, h=70)
    cf_waf = b.add_cell("cf_waf", "<b>WAF</b><br/>OWASP Rules<br/>Bot Protection", STYLES["cf_service"],
                        parent="cf_zone", x=260, y=35, w=200, h=70)
    cf_ddos = b.add_cell("cf_ddos", "<b>DDoS</b><br/>L3/L4/L7<br/>Rate Limiting", STYLES["cf_service"],
                         parent="cf_zone", x=490, y=35, w=200, h=70)
    cf_ssl = b.add_cell("cf_ssl", "<b>Edge TLS</b><br/>Full (Strict)<br/>HTTPS Only", STYLES["cf_service"],
                        parent="cf_zone", x=720, y=35, w=200, h=70)

    # Security layer: Cloudflare Access
    cf_access = b.add_cell("cf_access", "<b>Cloudflare Access</b><br/>Zero Trust Policies<br/>Email OTP + Authentik IDP",
                           STYLES["cf_access"], parent="layer_security", x=1870, y=345, w=280, h=70)

    # -- Cloudflare Tunnel (inside VPS) --
    cf_tunnel = b.add_cell("cf_tunnel", "<b>cloudflared</b><br/>Cloudflare Tunnel (QUIC)",
                           STYLES["standalone"].replace("BDBDBD", "F9A825") + f"fillColor=#FFF8E1;strokeColor=#F9A825;fontStyle=1;",
                           x=1800, y=530, w=280, h=60)

    # ========================================================================
    # VPS BOUNDARY
    # ========================================================================
    vps_id = b.add_cell("vps", "<b>VPS — REDACTED_IP</b>  |  Alpine Linux  |  Podman Rootless",
                        STYLES["vps_boundary"], x=80, y=480, w=3700, h=1680)

    # -- Firewall Bar --
    fw_id = b.add_cell("fw", "iptables FIREWALL — Policy: DROP | Allow: 22 (SSH), 80 (HTTP), 443 (HTTPS), ICMP",
                       STYLES["firewall_bar"], parent="layer_security", x=180, y=492, w=3500, h=28)

    # -- Traefik --
    traefik_id = b.add_cell("traefik",
                            "<b>Traefik v3.6</b><br/>Reverse Proxy + TLS Termination<br/>Let's Encrypt (Cloudflare DNS Challenge)",
                            STYLES["standalone"] + f"fillColor=#E3F2FD;strokeColor=#1565C0;fontStyle=1;strokeWidth=3;",
                            x=1600, y=620, w=680, h=70)

    # ========================================================================
    # AI STACK POD
    # ========================================================================
    pod_ai = b.add_cell("pod_ai", f"<b>ai-stack-pod</b>",
                        STYLES["pod"] + f"fillColor={COLORS['bg_pod_ai']};strokeColor=#42A5F5;",
                        x=500, y=750, w=1300, h=540)

    # OpenWebUI (PROMINENT - this is REDACTED_DOMAIN)
    owui = b.add_cell("owui",
                      "<b>REDACTED_DOMAIN</b><br/>(OpenWebUI v0.8.1)<br/>AI Chat Hub<br/>OIDC Auth | Group Access Control",
                      STYLES["container"] + f"fillColor=#1565C0;strokeColor=#0D47A1;fontColor=#FFFFFF;fontStyle=1;fontSize=12;strokeWidth=2;",
                      parent="pod_ai", x=30, y=40, w=340, h=130)

    litellm = b.add_cell("litellm",
                         "<b>LiteLLM</b><br/>AI Proxy Gateway<br/>Multi-Provider Routing<br/>Per-User Spend Tracking",
                         STYLES["container"] + f"fillColor=#E8F5E9;strokeColor=#43A047;fontStyle=1;",
                         parent="pod_ai", x=30, y=195, w=340, h=110)

    kokoro = b.add_cell("kokoro",
                        "<b>Kokoro TTS</b><br/>Text-to-Speech<br/>CPU Inference<br/>OpenAI-compat /v1/audio/speech",
                        STYLES["container"] + f"fillColor=#FFF3E0;strokeColor=#FB8C00;fontStyle=1;",
                        parent="pod_ai", x=400, y=40, w=280, h=110)

    ai_pg = b.add_cell("ai_pg", "<b>PostgreSQL 16</b><br/>LiteLLM DB + n8n DB",
                       STYLES["container_db"],
                       parent="pod_ai", x=400, y=185, w=280, h=80)

    n8n_claude = b.add_cell("n8n_claude",
                            "<b>n8n-claude</b><br/>Workflow Automation<br/>Claude CLI Integration",
                            STYLES["container"] + f"fillColor=#E8EAF6;strokeColor=#5C6BC0;",
                            parent="pod_ai", x=710, y=40, w=260, h=90)

    # SearXNG (standalone, in ai-stack area)
    searxng = b.add_cell("searxng", "<b>SearXNG</b><br/>Web Search",
                         STYLES["container"] + f"fillColor=#EFEBE9;strokeColor=#8D6E63;",
                         parent="pod_ai", x=710, y=155, w=260, h=60)

    # Pod port labels (engineering layer)
    b.add_cell("ai_ports", ":8080 (WebUI) | :4000 (LiteLLM) | :5678 (n8n) | :8880 (TTS) | :5432 (PG)",
               STYLES["engineering_label"], parent="layer_engineering", x=500, y=1270, w=420, h=20)

    # ========================================================================
    # AUTHENTICATION POD
    # ========================================================================
    pod_auth = b.add_cell("pod_auth", "<b>authentication-pod</b>",
                          STYLES["pod"] + f"fillColor={COLORS['bg_pod_auth']};strokeColor=#AB47BC;",
                          x=1900, y=750, w=700, h=300)

    auth_server = b.add_cell("auth_server",
                             "<b>Authentik Server</b><br/>2025.10<br/>Identity Provider (IDP)<br/>OIDC / OAuth2 / SAML",
                             STYLES["container"] + f"fillColor=#CE93D8;strokeColor=#8E24AA;fontStyle=1;",
                             parent="pod_auth", x=20, y=40, w=300, h=110)

    auth_worker = b.add_cell("auth_worker",
                             "<b>Authentik Worker</b><br/>Background Tasks<br/>Email, Flows, Policies",
                             STYLES["container"] + f"fillColor=#E1BEE7;strokeColor=#AB47BC;",
                             parent="pod_auth", x=350, y=40, w=300, h=80)

    auth_pg = b.add_cell("auth_pg", "<b>PostgreSQL 16</b><br/>Users, Flows, Tokens<br/>(No Redis — 2025.10)",
                         STYLES["container_db"],
                         parent="pod_auth", x=140, y=170, w=340, h=80)

    b.add_cell("auth_ports", ":9000 (HTTP) | :9443 (HTTPS) | :9300 (metrics)",
               STYLES["engineering_label"], parent="layer_engineering", x=1920, y=1035, w=350, h=20)

    # ========================================================================
    # METRICS POD (formerly monitoring-pod, split into metrics/logs/tempo)
    # ========================================================================
    pod_mon = b.add_cell("pod_mon", "<b>metrics-pod</b>",
                         STYLES["pod"] + f"fillColor={COLORS['bg_pod_mon']};strokeColor=#FF9800;",
                         x=2700, y=750, w=1000, h=600)

    grafana = b.add_cell("grafana",
                         "<b>Grafana 12.3.1</b><br/>Dashboards<br/>OIDC Auth",
                         STYLES["container"] + f"fillColor=#FFE0B2;strokeColor=#F57C00;fontStyle=1;",
                         parent="pod_mon", x=20, y=40, w=220, h=90)

    prometheus = b.add_cell("prometheus",
                            "<b>Prometheus v3.8.1</b><br/>Metrics (15d)<br/>Recording Rules",
                            STYLES["container"] + f"fillColor=#FFF3E0;strokeColor=#FF9800;fontStyle=1;",
                            parent="pod_mon", x=260, y=40, w=230, h=90)

    loki = b.add_cell("loki",
                      "<b>Loki 3.6.3</b><br/>Logs (7d)<br/>Multitenancy",
                      STYLES["container"] + f"fillColor=#FFF3E0;strokeColor=#FF9800;",
                      parent="pod_mon", x=510, y=40, w=200, h=90)

    tempo = b.add_cell("tempo",
                       "<b>Tempo 2.9.0</b><br/>Traces (7d)<br/>OTLP + Correlation",
                       STYLES["container"] + f"fillColor=#FFF3E0;strokeColor=#FF9800;",
                       parent="pod_mon", x=730, y=40, w=230, h=90)

    alloy = b.add_cell("alloy",
                       "<b>Alloy v1.12.2</b><br/>OTLP Gateway<br/>Log/Metric/Trace Collector<br/>Container Discovery",
                       STYLES["container"] + f"fillColor=#FFE082;strokeColor=#F9A825;fontStyle=1;fontSize=10;",
                       parent="pod_mon", x=20, y=160, w=300, h=110)

    checkmk = b.add_cell("checkmk",
                         "<b>CheckMK 2.4.0</b><br/>Infrastructure<br/>Monitoring",
                         STYLES["container"] + f"fillColor=#FFF3E0;strokeColor=#FF9800;",
                         parent="pod_mon", x=350, y=160, w=200, h=80)

    node_exp = b.add_cell("node_exp",
                          "<b>Node Exporter</b><br/>Host Metrics",
                          STYLES["container"] + f"fillColor=#FFF3E0;strokeColor=#FF9800;",
                          parent="pod_mon", x=580, y=160, w=180, h=60)

    cf_exporter = b.add_cell("cf_exporter",
                             "<b>CF Exporter</b><br/>Zone Analytics",
                             STYLES["container"] + f"fillColor=#FFF8E1;strokeColor=#F9A825;",
                             parent="pod_mon", x=780, y=160, w=180, h=60)

    b.add_cell("mon_ports", ":3000 (Grafana) | :9090 (Prom) | :3100/3200 (Loki) | :4317-4318 (OTLP) | :5000 (CMK)",
               STYLES["engineering_label"], parent="layer_engineering", x=2720, y=1335, w=500, h=20)

    # Observability data flow labels inside monitoring pod
    b.add_cell("obs_label_m", "Metrics", STYLES["label"] + "fontColor=#E65100;fontStyle=1;",
               parent="layer_observability", x=2970, y=830, w=60, h=20)
    b.add_cell("obs_label_l", "Logs", STYLES["label"] + "fontColor=#E65100;fontStyle=1;",
               parent="layer_observability", x=3220, y=830, w=40, h=20)
    b.add_cell("obs_label_t", "Traces", STYLES["label"] + "fontColor=#E65100;fontStyle=1;",
               parent="layer_observability", x=3440, y=830, w=50, h=20)

    # ========================================================================
    # SECURITY POD
    # ========================================================================
    pod_sec = b.add_cell("pod_sec", "<b>security-pod</b>",
                         STYLES["pod"] + f"fillColor={COLORS['bg_pod_sec']};strokeColor=#EF5350;",
                         x=100, y=1400, w=900, h=330)

    wazuh_mgr = b.add_cell("wazuh_mgr",
                           "<b>Wazuh Manager</b><br/>4.14.3 — SIEM<br/>FIM, Rootkit, Rules",
                           STYLES["container"] + f"fillColor=#FFCDD2;strokeColor=#EF5350;fontStyle=1;",
                           parent="pod_sec", x=20, y=40, w=250, h=100)

    wazuh_idx = b.add_cell("wazuh_idx",
                           "<b>Wazuh Indexer</b><br/>OpenSearch<br/>Alert Storage",
                           STYLES["container"] + f"fillColor=#FFCDD2;strokeColor=#EF5350;",
                           parent="pod_sec", x=290, y=40, w=250, h=80)

    wazuh_dash = b.add_cell("wazuh_dash",
                            "<b>Wazuh Dashboard</b><br/>Security Analytics",
                            STYLES["container"] + f"fillColor=#FFCDD2;strokeColor=#EF5350;",
                            parent="pod_sec", x=20, y=170, w=250, h=70)

    trivy = b.add_cell("trivy",
                       "<b>Trivy 0.68.2</b><br/>Vuln Scanner<br/>Image Scanning",
                       STYLES["container"] + f"fillColor=#FFCDD2;strokeColor=#EF5350;",
                       parent="pod_sec", x=290, y=170, w=250, h=70)

    # Host-level security (security layer)
    tetragon = b.add_cell("tetragon",
                          "<b>Tetragon v1.6</b><br/>eBPF Kernel Security<br/>Process + File + Network",
                          STYLES["container"] + f"fillColor=#FFEBEE;strokeColor=#C62828;fontStyle=1;",
                          parent="layer_security", x=600, y=1470, w=260, h=80)

    fail2ban = b.add_cell("fail2ban",
                          "<b>Fail2ban</b><br/>SSH Protection<br/>5 retries / 1h ban",
                          STYLES["container"] + f"fillColor=#FFEBEE;strokeColor=#C62828;",
                          parent="layer_security", x=100, y=1780, w=220, h=70)

    wazuh_agent = b.add_cell("wazuh_agent",
                             "<b>Wazuh Agent</b><br/>Host Monitor<br/>FIM + Log Analysis",
                             STYLES["container"] + f"fillColor=#FFEBEE;strokeColor=#C62828;",
                             parent="layer_security", x=360, y=1780, w=220, h=70)

    b.add_cell("sec_ports", ":1514-1515 (agent) | :5601 (dashboard) | :9200 (indexer) | :55000 (API)",
               STYLES["engineering_label"], parent="layer_engineering", x=120, y=1720, w=400, h=20)

    # ========================================================================
    # MANAGEMENT POD
    # ========================================================================
    pod_mgmt = b.add_cell("pod_mgmt", "<b>management-pod</b>",
                          STYLES["pod"] + f"fillColor={COLORS['bg_pod_mgmt']};strokeColor=#66BB6A;",
                          x=1100, y=1400, w=350, h=160)

    portainer = b.add_cell("portainer",
                           "<b>Portainer CE 2.33.6</b><br/>Container Management<br/>OIDC Auth",
                           STYLES["container"] + f"fillColor=#C8E6C9;strokeColor=#43A047;fontStyle=1;",
                           parent="pod_mgmt", x=30, y=40, w=290, h=90)

    # ========================================================================
    # FRONTEND POD
    # ========================================================================
    pod_front = b.add_cell("pod_front", "<b>frontend-pod</b>",
                           STYLES["pod"] + f"fillColor={COLORS['bg_pod_front']};strokeColor=#90A4AE;",
                           x=1550, y=1400, w=350, h=160)

    nginx = b.add_cell("nginx",
                       "<b>Nginx 1.29</b><br/>Portal (portal.REDACTED_DOMAIN)<br/>Static Frontend",
                       STYLES["container"] + f"fillColor=#ECEFF1;strokeColor=#78909C;",
                       parent="pod_front", x=30, y=40, w=290, h=80)

    # ========================================================================
    # SHARED SERVICES (standalone containers)
    # ========================================================================
    shared_label = b.add_cell("shared_label", "<b>Shared Services</b> (Standalone Containers)",
                              STYLES["subtitle"] + "fontSize=12;fontColor=#37474F;align=left;",
                              x=100, y=1600, w=350, h=25)

    pg_shared = b.add_cell("pg_shared", "<b>PostgreSQL 16</b><br/>Shared DB<br/>REDACTED_DNS6",
                           STYLES["container_db"] + "fontSize=11;fontStyle=1;",
                           x=100, y=1640, w=220, h=80)

    redis = b.add_cell("redis", "<b>Redis 8</b><br/>Cache<br/>REDACTED_DNS7<br/>requirepass",
                       STYLES["container_db"].replace("BBDEFB", "FFCCBC").replace("42A5F5", "FF7043") + "fontSize=11;",
                       x=360, y=1640, w=200, h=80)

    ansible_ct = b.add_cell("ansible_ct", "<b>ansible-deployment</b><br/>Ansible Controller<br/>IaC Automation",
                            STYLES["standalone"] + f"fillColor=#EDE7F6;strokeColor=#7E57C2;fontSize=10;",
                            x=600, y=1640, w=220, h=70)

    # ========================================================================
    # AI PROVIDERS (External — bottom zone)
    # ========================================================================
    providers_label = b.add_cell("prov_label", "<b>External AI Providers</b> — API Connections via LiteLLM Proxy",
                                STYLES["subtitle"] + "fontSize=13;fontColor=#E65100;fontStyle=1;align=center;",
                                parent="layer_aimodels", x=400, y=1880, w=600, h=25)

    # Provider boxes
    prov_anthropic = b.add_cell("prov_anthropic", "<b>Anthropic</b>",
                               STYLES["provider"] + "strokeColor=#D4A574;fillColor=#FFF8F0;",
                               parent="layer_aimodels", x=100, y=1920, w=280, h=170)
    b.add_cell(None, "claude-sonnet-4-5", STYLES["provider_model"],
               parent="prov_anthropic", x=10, y=30, w=125, h=28)
    b.add_cell(None, "claude-haiku-4-5", STYLES["provider_model"],
               parent="prov_anthropic", x=145, y=30, w=125, h=28)

    prov_openai = b.add_cell("prov_openai", "<b>OpenAI</b>",
                             STYLES["provider"] + "strokeColor=#10A37F;fillColor=#F0FFF8;",
                             parent="layer_aimodels", x=420, y=1920, w=340, h=170)
    b.add_cell(None, "gpt-4o", STYLES["provider_model"], parent="prov_openai", x=10, y=30, w=90, h=28)
    b.add_cell(None, "gpt-4o-mini", STYLES["provider_model"], parent="prov_openai", x=110, y=30, w=100, h=28)
    b.add_cell(None, "o3-mini", STYLES["provider_model"], parent="prov_openai", x=220, y=30, w=90, h=28)
    b.add_cell(None, "DALL-E 3", STYLES["provider_model"] + "fillColor=#FFE0B2;", parent="prov_openai", x=10, y=65, w=90, h=28)

    prov_google = b.add_cell("prov_google", "<b>Google / Vertex AI</b>",
                             STYLES["provider"] + "strokeColor=#4285F4;fillColor=#F0F4FF;",
                             parent="layer_aimodels", x=800, y=1920, w=340, h=170)
    b.add_cell(None, "gemini-2.5-pro", STYLES["provider_model"], parent="prov_google", x=10, y=30, w=120, h=28)
    b.add_cell(None, "gemini-2.5-flash", STYLES["provider_model"], parent="prov_google", x=140, y=30, w=120, h=28)
    b.add_cell(None, "Imagen-3", STYLES["provider_model"] + "fillColor=#FFE0B2;", parent="prov_google", x=10, y=65, w=100, h=28)
    b.add_cell(None, "gemini-image", STYLES["provider_model"] + "fillColor=#FFE0B2;", parent="prov_google", x=120, y=65, w=120, h=28)

    prov_deepseek = b.add_cell("prov_deepseek", "<b>DeepSeek</b>",
                               STYLES["provider"],
                               parent="layer_aimodels", x=1180, y=1920, w=230, h=170)
    b.add_cell(None, "deepseek-r1", STYLES["provider_model"], parent="prov_deepseek", x=10, y=30, w=100, h=28)
    b.add_cell(None, "deepseek-chat", STYLES["provider_model"], parent="prov_deepseek", x=120, y=30, w=100, h=28)

    prov_xai = b.add_cell("prov_xai", "<b>XAI</b>",
                          STYLES["provider"],
                          parent="layer_aimodels", x=1450, y=1920, w=200, h=170)
    b.add_cell(None, "grok-3", STYLES["provider_model"], parent="prov_xai", x=10, y=30, w=80, h=28)
    b.add_cell(None, "grok-3-mini", STYLES["provider_model"], parent="prov_xai", x=100, y=30, w=90, h=28)

    prov_groq = b.add_cell("prov_groq", "<b>Groq</b><br/><i>Fast Inference</i>",
                           STYLES["provider"],
                           parent="layer_aimodels", x=1690, y=1920, w=260, h=170)
    b.add_cell(None, "llama-3.3-70b", STYLES["provider_model"], parent="prov_groq", x=10, y=45, w=110, h=28)
    b.add_cell(None, "qwen3-32b", STYLES["provider_model"], parent="prov_groq", x=130, y=45, w=100, h=28)

    prov_cohere = b.add_cell("prov_cohere", "<b>Cohere</b>",
                             STYLES["provider"],
                             parent="layer_aimodels", x=1990, y=1920, w=240, h=170)
    b.add_cell(None, "command-r-plus", STYLES["provider_model"], parent="prov_cohere", x=10, y=30, w=110, h=28)
    b.add_cell(None, "command-r", STYLES["provider_model"], parent="prov_cohere", x=130, y=30, w=100, h=28)

    prov_openrouter = b.add_cell("prov_openrouter", "<b>OpenRouter</b><br/><i>Multi-Model Aggregator</i>",
                                 STYLES["provider"] + "strokeColor=#6366F1;fillColor=#F0F0FF;",
                                 parent="layer_aimodels", x=2270, y=1920, w=320, h=170)
    b.add_cell(None, "mistral-large", STYLES["provider_model"], parent="prov_openrouter", x=10, y=45, w=100, h=28)
    b.add_cell(None, "llama-3.3-70b", STYLES["provider_model"], parent="prov_openrouter", x=120, y=45, w=100, h=28)
    b.add_cell(None, "flux-klein", STYLES["provider_model"] + "fillColor=#FFE0B2;", parent="prov_openrouter", x=10, y=80, w=90, h=28)
    b.add_cell(None, "gemma-2-27b", STYLES["provider_model"], parent="prov_openrouter", x=110, y=80, w=100, h=28)
    b.add_cell(None, "openrouter/*", STYLES["provider_model"] + "fillColor=#E8EAF6;", parent="prov_openrouter", x=220, y=80, w=90, h=28)

    # ========================================================================
    # CLAUDE CODE & MCP SERVERS (right panel)
    # ========================================================================
    claude_zone = b.add_cell("claude_zone", "<b>Claude Code CLI &amp; MCP Tools</b>",
                             STYLES["pod"] + f"fillColor={COLORS['bg_claude']};strokeColor=#7E57C2;",
                             parent="layer_claude", x=3900, y=480, w=400, h=800)

    claude_cli = b.add_cell("claude_cli",
                            "<b>Claude Code CLI</b><br/>AI Agent (Opus 4.6)<br/>SSH → VPS<br/>Infrastructure Mgmt",
                            STYLES["container"] + f"fillColor=#B39DDB;strokeColor=#5E35B1;fontStyle=1;fontColor=#FFFFFF;",
                            parent="claude_zone", x=30, y=45, w=340, h=110)

    mcp_n8n = b.add_cell("mcp_n8n", "<b>n8n-mcp</b><br/>Workflow Automation<br/>:3002 | Bearer Auth",
                         STYLES["mcp_server"], parent="claude_zone", x=30, y=180, w=160, h=80)

    mcp_gdocs = b.add_cell("mcp_gdocs", "<b>Google Docs MCP</b><br/>Drive + Docs<br/>:9091 | SSE",
                           STYLES["mcp_server"], parent="claude_zone", x=210, y=180, w=160, h=80)

    mcp_ctx7 = b.add_cell("mcp_ctx7", "<b>Context7 MCP</b><br/>Protocol Impl<br/>:3001",
                          STYLES["mcp_server"], parent="claude_zone", x=30, y=280, w=160, h=70)

    mcp_scrapy = b.add_cell("mcp_scrapy", "<b>Scrapy MCP</b><br/>Web Scraping<br/>:8888 | DinD",
                            STYLES["mcp_server"], parent="claude_zone", x=210, y=280, w=160, h=70)

    # Claude -> Ansible connection
    b.add_cell("claude_ansible_label", "IaC:<br/>Playbooks, Roles,<br/>Templates, Deploy",
               STYLES["label"] + "fontSize=9;fontColor=#5E35B1;",
               parent="layer_claude", x=3950, y=1300, w=120, h=60)

    # ========================================================================
    # AWS AI INFERENCE PLATFORM (external zone, right side)
    # ========================================================================

    # AWS Cloud boundary
    aws_cloud = b.add_cell("aws_cloud",
                           "<b>AWS — us-east-1 — AI Inference Platform</b>",
                           STYLES["aws_cloud"],
                           parent="layer_aimodels", x=4500, y=480, w=1200, h=1100)

    # VPC boundary
    aws_vpc = b.add_cell("aws_vpc", "<b>VPC 10.0.0.0/16</b>",
                         STYLES["aws_vpc"],
                         parent="aws_cloud", x=30, y=50, w=1140, h=900)

    # Public subnet
    aws_pub_subnet = b.add_cell("aws_pub_sub", "<b>Public Subnet</b> (10.0.1.0/24)",
                                STYLES["aws_subnet"],
                                parent="aws_vpc", x=20, y=40, w=350, h=160)

    aws_alb = b.add_cell("aws_alb", "<b>Application Load Balancer</b><br/>aws-gpu.REDACTED_DOMAIN<br/>HTTPS :443",
                         STYLES["aws_service"] + "fontStyle=1;",
                         parent="aws_pub_sub", x=20, y=30, w=310, h=70)

    aws_nat = b.add_cell("aws_nat", "<b>NAT Gateway</b><br/>Outbound Internet",
                         STYLES["aws_service"] + "fontSize=9;",
                         parent="aws_pub_sub", x=200, y=110, w=130, h=40)

    # Private subnet
    aws_priv_subnet = b.add_cell("aws_priv_sub", "<b>Private Subnet</b> (10.0.2.0/24)",
                                 STYLES["aws_subnet_private"],
                                 parent="aws_vpc", x=20, y=220, w=1100, h=440)

    # Orchestrator (LiteLLM Proxy)
    aws_orch = b.add_cell("aws_orch",
                          "<b>Orchestrator</b><br/>t3.medium<br/>LiteLLM Proxy + Auto-Router",
                          STYLES["aws_service"] + "fontStyle=1;strokeWidth=2;",
                          parent="aws_priv_sub", x=20, y=40, w=240, h=80)

    # G5 Instance
    aws_g5 = b.add_cell("aws_g5",
                        "<b>g5.12xlarge</b><br/>4x NVIDIA A10G (96GB)<br/>vLLM — 32B/70B Models",
                        STYLES["aws_gpu"],
                        parent="aws_priv_sub", x=320, y=30, w=240, h=100)

    # P4de Instance
    aws_p4de = b.add_cell("aws_p4de",
                          "<b>p4de.24xlarge</b><br/>8x NVIDIA A100 (640GB)<br/>vLLM — DeepSeek R1 671B",
                          STYLES["aws_gpu"] + "fillColor=#FFECB3;strokeColor=#E65100;",
                          parent="aws_priv_sub", x=620, y=30, w=260, h=100)

    # RDS PostgreSQL
    aws_rds = b.add_cell("aws_rds", "<b>RDS PostgreSQL</b><br/>Spend Tracking DB",
                         STYLES["aws_storage"],
                         parent="aws_priv_sub", x=20, y=160, w=200, h=70)

    # EFS
    aws_efs = b.add_cell("aws_efs", "<b>EFS</b><br/>Shared Model Storage<br/>NFS :2049",
                         STYLES["aws_storage"],
                         parent="aws_priv_sub", x=400, y=170, w=200, h=70)

    # Serverless zone (outside private subnet but inside VPC)
    aws_sqs = b.add_cell("aws_sqs", "<b>SQS Queue</b><br/>Heavy Reasoning<br/>Requests",
                         STYLES["aws_service"] + "fontSize=9;",
                         parent="aws_vpc", x=400, y=40, w=170, h=70)

    aws_lambda_up = b.add_cell("aws_lambda_up", "<b>Λ Scale-Up</b><br/>SQS-triggered",
                               STYLES["aws_lambda"],
                               parent="aws_vpc", x=600, y=40, w=130, h=55)

    aws_lambda_down = b.add_cell("aws_lambda_down", "<b>Λ Scale-Down</b><br/>EventBridge 2-min",
                                 STYLES["aws_lambda"],
                                 parent="aws_vpc", x=600, y=110, w=130, h=55)

    # AWS services outside VPC (inside AWS cloud)
    aws_s3 = b.add_cell("aws_s3", "<b>S3</b><br/>Model Weights",
                        STYLES["aws_storage"],
                        parent="aws_cloud", x=30, y=980, w=160, h=60)

    aws_cw = b.add_cell("aws_cw", "<b>CloudWatch</b><br/>Dashboards +<br/>Budget Alerts",
                        STYLES["aws_service"] + "fontSize=9;",
                        parent="aws_cloud", x=230, y=980, w=160, h=60)

    aws_ssm = b.add_cell("aws_ssm", "<b>SSM Parameter Store</b><br/>Secrets",
                         STYLES["aws_service"] + "fontSize=9;",
                         parent="aws_cloud", x=430, y=980, w=170, h=60)

    aws_eb = b.add_cell("aws_eb", "<b>EventBridge</b><br/>Idle Scheduler",
                        STYLES["aws_service"] + "fontSize=9;",
                        parent="aws_cloud", x=640, y=980, w=150, h=60)

    # Cost annotation
    b.add_cell("aws_cost_note",
               "<b>Cost Optimization:</b><br/>"
               "• G5: ~$5.67/hr (on-demand)<br/>"
               "• P4de: ~$40.96/hr (on-demand)<br/>"
               "• Auto scale-down after 2-min idle<br/>"
               "• SQS-triggered scale-up for heavy reasoning",
               "text;html=1;align=left;verticalAlign=top;resizable=0;points=[];autosize=1;"
               "strokeColor=#FF9900;fillColor=#FFF8E1;fontSize=8;fontColor=#37474F;rounded=1;",
               parent="layer_aimodels", x=5720, y=1420, w=250, h=85)

    # --- AWS Internal Connections ---

    # ALB -> Orchestrator
    b.add_edge("e_aws_alb_orch", "HTTP :4000", STYLES["edge_aws"],
               parent="layer_aimodels", source="aws_alb", target="aws_orch")

    # Orchestrator -> GPU instances
    b.add_edge("e_aws_orch_g5", "vLLM :8000", STYLES["edge_aws"],
               parent="layer_aimodels", source="aws_orch", target="aws_g5")
    b.add_edge("e_aws_orch_p4de", "vLLM :8000", STYLES["edge_aws"],
               parent="layer_aimodels", source="aws_orch", target="aws_p4de")

    # Orchestrator -> RDS
    b.add_edge("e_aws_orch_rds", ":5432", STYLES["edge_aws"],
               parent="layer_aimodels", source="aws_orch", target="aws_rds")

    # GPU -> EFS
    b.add_edge("e_aws_g5_efs", "NFS", STYLES["edge_aws"],
               parent="layer_aimodels", source="aws_g5", target="aws_efs")
    b.add_edge("e_aws_p4de_efs", "NFS", STYLES["edge_aws"],
               parent="layer_aimodels", source="aws_p4de", target="aws_efs")

    # SQS -> Lambda scale-up
    b.add_edge("e_aws_sqs_lambda", "trigger", STYLES["edge_aws"],
               parent="layer_aimodels", source="aws_sqs", target="aws_lambda_up")

    # EventBridge -> Lambda scale-down
    b.add_edge("e_aws_eb_lambda", "trigger", STYLES["edge_aws"],
               parent="layer_aimodels", source="aws_eb", target="aws_lambda_down")

    # Orchestrator -> S3
    b.add_edge("e_aws_orch_s3", "weights", STYLES["edge_aws"],
               parent="layer_aimodels", source="aws_orch", target="aws_s3")

    # Orchestrator -> CloudWatch
    b.add_edge("e_aws_orch_cw", "metrics", STYLES["edge_aws"],
               parent="layer_aimodels", source="aws_orch", target="aws_cw")

    # --- Cross-boundary connections (VPS -> AWS) ---

    # VPS LiteLLM -> AWS ALB
    b.add_edge("e_litellm_aws", "<b>HTTPS</b><br/>Self-hosted GPU Inference<br/>api_base: aws-gpu.REDACTED_DOMAIN/v1",
               STYLES["edge_aws"] + "strokeWidth=3;",
               parent="layer_aimodels", source="litellm", target="aws_alb")

    # Fallback: Orchestrator -> External APIs (dashed)
    b.add_cell("aws_fallback_label",
               "<b>Fallback:</b> Orchestrator → External APIs<br/>(Anthropic, DeepSeek) when GPU unavailable",
               "text;html=1;align=left;verticalAlign=middle;resizable=0;points=[];autosize=1;"
               "strokeColor=none;fillColor=none;fontSize=8;fontColor=#FF6F00;fontStyle=2;",
               parent="layer_aimodels", x=4550, y=1600, w=300, h=30)

    # ========================================================================
    # CONNECTIONS — USER TRANSACTION FLOW
    # ========================================================================

    # User -> Internet -> Cloudflare -> Tunnel -> Traefik -> Services
    b.add_edge("e_user_inet", "", STYLES["edge_user"], parent="layer_userflow",
               source="user", target="internet")
    b.add_edge("e_inet_cf", "", STYLES["edge_user"], parent="layer_userflow",
               source="internet", target="cf_zone")
    b.add_edge("e_cf_tunnel", "Encrypted<br/>QUIC Tunnel", STYLES["edge_user"], parent="layer_userflow",
               source="cf_zone", target="cf_tunnel")
    b.add_edge("e_tunnel_traefik", "HTTPS<br/>(noTLSVerify)", STYLES["edge_user"], parent="layer_userflow",
               source="cf_tunnel", target="traefik")

    # Traefik -> Services (user flow)
    b.add_edge("e_traefik_owui", "chat.REDACTED_DOMAIN<br/>→ :8080", STYLES["edge_user"], parent="layer_userflow",
               source="traefik", target="owui")
    b.add_edge("e_traefik_auth", "auth.REDACTED_DOMAIN<br/>→ :9000", STYLES["edge_user"], parent="layer_userflow",
               source="traefik", target="auth_server")
    b.add_edge("e_traefik_grafana", "grafana.REDACTED_DOMAIN<br/>→ :3000", STYLES["edge_user"], parent="layer_userflow",
               source="traefik", target="grafana")
    b.add_edge("e_traefik_portainer", "portainer.REDACTED_DOMAIN", STYLES["edge_internal"],
               parent="layer_userflow", source="traefik", target="portainer")
    b.add_edge("e_traefik_n8n", "n8n.REDACTED_DOMAIN", STYLES["edge_internal"],
               parent="layer_userflow", source="traefik", target="n8n_claude")
    b.add_edge("e_traefik_prom", "prometheus.REDACTED_DOMAIN", STYLES["edge_internal"],
               parent="layer_userflow", source="traefik", target="prometheus")
    b.add_edge("e_traefik_portal", "portal.REDACTED_DOMAIN", STYLES["edge_internal"],
               parent="layer_userflow", source="traefik", target="nginx")
    b.add_edge("e_traefik_kokoro", "tts.REDACTED_DOMAIN", STYLES["edge_internal"],
               parent="layer_userflow", source="traefik", target="kokoro")
    b.add_edge("e_traefik_litellm_route", "litellm.REDACTED_DOMAIN", STYLES["edge_internal"],
               parent="layer_userflow", source="traefik", target="litellm")
    b.add_edge("e_traefik_checkmk", "checkmk.REDACTED_DOMAIN", STYLES["edge_internal"],
               parent="layer_userflow", source="traefik", target="checkmk")

    # OpenWebUI -> LiteLLM -> Providers (AI flow)
    b.add_edge("e_owui_litellm", "<b>API Calls</b><br/>+ x-openwebui-user-email<br/>header (spend tracking)",
               STYLES["edge_ai"], parent="layer_userflow", source="owui", target="litellm")

    # OpenWebUI -> Kokoro TTS
    b.add_edge("e_owui_kokoro", "<b>Text → Speech</b><br/>/v1/audio/speech<br/>AI Voice Output",
               STYLES["edge_ai"], parent="layer_userflow", source="owui", target="kokoro")

    # LiteLLM -> Providers
    for prov_id in ["prov_anthropic", "prov_openai", "prov_google", "prov_deepseek",
                    "prov_xai", "prov_groq", "prov_cohere", "prov_openrouter"]:
        b.add_edge(None, "", STYLES["edge_ai"], parent="layer_aimodels",
                   source="litellm", target=prov_id)

    # ========================================================================
    # CONNECTIONS — AUTHENTICATION / SECURITY
    # ========================================================================

    # OIDC flows
    b.add_edge("e_owui_oidc", "<b>OIDC Login</b><br/>OAuth2 Flow",
               STYLES["edge_security"], parent="layer_security",
               source="owui", target="auth_server")
    b.add_edge("e_grafana_oidc", "OIDC", STYLES["edge_security"], parent="layer_security",
               source="grafana", target="auth_server")
    b.add_edge("e_portainer_oidc", "OIDC", STYLES["edge_security"], parent="layer_security",
               source="portainer", target="auth_server")

    # Auth -> DB
    b.add_edge("e_auth_db", "Users, Sessions,<br/>Flows, Policies", STYLES["edge_internal"],
               source="auth_server", target="auth_pg")
    b.add_edge("e_auth_worker_db", "", STYLES["edge_internal"],
               source="auth_worker", target="auth_pg")

    # Wazuh agent -> manager
    b.add_edge("e_wazuh_agent_mgr", "Agent Enrollment<br/>:1514-1515", STYLES["edge_security"],
               parent="layer_security", source="wazuh_agent", target="wazuh_mgr")

    # TLS indicators
    tls_label1 = b.add_cell("tls_1", "TLS 1.3<br/>Encrypted", STYLES["label"] + "fontColor=#1B5E20;fontStyle=3;fontSize=8;",
                            parent="layer_security", x=1700, y=600, w=70, h=30)
    tls_label2 = b.add_cell("tls_2", "QUIC<br/>Encrypted", STYLES["label"] + "fontColor=#1B5E20;fontStyle=3;fontSize=8;",
                            parent="layer_security", x=1750, y=455, w=60, h=30)

    # MFA indicator
    mfa_label = b.add_cell("mfa_label", "MFA/TOTP<br/>Required for<br/>admins group",
                           STYLES["label"] + "fontColor=#C62828;fontStyle=1;fontSize=8;",
                           parent="layer_security", x=2350, y=870, w=80, h=40)

    # Encryption at rest indicator
    enc_rest = b.add_cell("enc_rest", "Encryption at Rest:<br/>Ansible Vault (AES-256)<br/>GPG Backup Encryption",
                          STYLES["engineering_label"] + "fillColor=#FFEBEE;fontColor=#C62828;fontSize=8;",
                          parent="layer_security", x=100, y=2120, w=200, h=50)

    # ========================================================================
    # CONNECTIONS — OBSERVABILITY PIPELINE
    # ========================================================================

    # Alloy -> backends (within monitoring pod, localhost)
    b.add_edge("e_alloy_prom", "remote_write<br/>:9090/api/v1/write",
               STYLES["edge_observability"], parent="layer_observability",
               source="alloy", target="prometheus")
    b.add_edge("e_alloy_loki", "logs push<br/>:3100 + X-Scope-OrgID",
               STYLES["edge_observability"], parent="layer_observability",
               source="alloy", target="loki")
    b.add_edge("e_alloy_tempo", "OTLP traces<br/>:4320",
               STYLES["edge_observability"], parent="layer_observability",
               source="alloy", target="tempo")

    # Services -> Alloy (OTEL)
    b.add_edge("e_litellm_otel", "OTEL traces<br/>+ Prometheus metrics<br/>callbacks",
               STYLES["edge_observability"], parent="layer_observability",
               source="litellm", target="alloy")
    b.add_edge("e_traefik_otel", "OTEL traces<br/>:4318", STYLES["edge_observability"],
               parent="layer_observability", source="traefik", target="alloy")

    # Alloy container log collection (Docker socket)
    b.add_cell("docker_sock_label", "Podman Socket<br/>(container logs<br/>+ discovery)",
               STYLES["label"] + "fontColor=#2E7D32;fontStyle=1;fontSize=8;",
               parent="layer_observability", x=2730, y=1070, w=90, h=40)

    # Grafana -> datasources
    b.add_edge("e_grafana_prom", "Query Metrics", STYLES["edge_observability"],
               parent="layer_observability", source="grafana", target="prometheus")
    b.add_edge("e_grafana_loki", "Query Logs", STYLES["edge_observability"],
               parent="layer_observability", source="grafana", target="loki")
    b.add_edge("e_grafana_tempo", "Query Traces", STYLES["edge_observability"],
               parent="layer_observability", source="grafana", target="tempo")
    b.add_edge("e_grafana_wazuh", "Wazuh Alerts<br/>(Elasticsearch DS)",
               STYLES["edge_observability"], parent="layer_observability",
               source="grafana", target="wazuh_idx")

    # Wazuh -> Loki (via Alloy file source)
    b.add_edge("e_wazuh_loki", "SIEM Alerts<br/>JSON → Alloy → Loki",
               STYLES["edge_observability"], parent="layer_observability",
               source="wazuh_mgr", target="alloy")

    # Tetragon -> Loki (via Alloy)
    b.add_edge("e_tetragon_loki", "eBPF Events<br/>→ Alloy → Loki",
               STYLES["edge_observability"], parent="layer_observability",
               source="tetragon", target="alloy")

    # Prometheus scrape targets
    b.add_edge("e_prom_node", "scrape :9100", STYLES["edge_observability"],
               parent="layer_observability", source="prometheus", target="node_exp")
    b.add_edge("e_alloy_scrape_traefik", "scrape traefik:8080",
               STYLES["edge_observability"], parent="layer_observability",
               source="alloy", target="traefik")
    b.add_edge("e_alloy_scrape_auth", "scrape :9300",
               STYLES["edge_observability"], parent="layer_observability",
               source="alloy", target="auth_server")
    b.add_edge("e_alloy_scrape_cf", "scrape :2000/metrics",
               STYLES["edge_observability"], parent="layer_observability",
               source="alloy", target="cf_tunnel")

    # Correlation labels
    b.add_cell("corr_label", "<b>Observability Correlation</b><br/>Traces ↔ Logs (traceID)<br/>Traces ↔ Metrics (service.name)<br/>Logs ↔ Traces (regex extraction)",
               STYLES["engineering_label"] + "fillColor=#E8F5E9;fontSize=9;",
               parent="layer_observability", x=3430, y=800, w=240, h=70)

    # ========================================================================
    # CONNECTIONS — CLAUDE CODE & MCP
    # ========================================================================

    # Claude CLI -> SSH -> VPS
    b.add_edge("e_claude_ssh", "<b>SSH</b><br/>Remote Execution", STYLES["edge_claude"],
               parent="layer_claude", source="claude_cli", target="vps")

    # Claude CLI -> MCP servers (via localhost)
    b.add_edge("e_claude_mcp_n8n", "HTTP :3002", STYLES["edge_claude"],
               parent="layer_claude", source="claude_cli", target="mcp_n8n")
    b.add_edge("e_claude_mcp_gdocs", "SSE :9091", STYLES["edge_claude"],
               parent="layer_claude", source="claude_cli", target="mcp_gdocs")
    b.add_edge("e_claude_mcp_ctx7", "HTTP :3001", STYLES["edge_claude"],
               parent="layer_claude", source="claude_cli", target="mcp_ctx7")
    b.add_edge("e_claude_mcp_scrapy", "HTTP :8888", STYLES["edge_claude"],
               parent="layer_claude", source="claude_cli", target="mcp_scrapy")

    # Claude -> Ansible deployment container
    b.add_edge("e_claude_ansible", "Ansible Playbooks<br/>IaC Management", STYLES["edge_claude"],
               parent="layer_claude", source="claude_cli", target="ansible_ct")

    # ========================================================================
    # INTERNAL DATA CONNECTIONS
    # ========================================================================

    # AI stack internal
    b.add_edge("e_litellm_db", "Spend Data<br/>Model Config", STYLES["edge_internal"],
               source="litellm", target="ai_pg")
    b.add_edge("e_n8n_db", "Workflow Data", STYLES["edge_internal"],
               source="n8n_claude", target="ai_pg")
    b.add_edge("e_owui_searxng", "Web Search", STYLES["edge_internal"],
               source="owui", target="searxng")
    b.add_edge("e_n8n_litellm", "API Calls", STYLES["edge_internal"],
               source="n8n_claude", target="litellm")

    # Wazuh internal
    b.add_edge("e_wazuh_mgr_idx", "Index Alerts", STYLES["edge_internal"],
               source="wazuh_mgr", target="wazuh_idx")
    b.add_edge("e_wazuh_dash_idx", "Query", STYLES["edge_internal"],
               source="wazuh_dash", target="wazuh_idx")

    # ========================================================================
    # LEGEND
    # ========================================================================
    legend = b.add_cell("legend", "<b>Legend — Connection Types (Toggle Layers)</b>",
                        STYLES["legend_box"], x=3900, y=1400, w=400, h=400)

    legend_items = [
        ("User Transaction Flow", COLORS["stroke_user_flow"], 30),
        ("Security / Auth / OIDC", COLORS["stroke_security"], 65),
        ("Container Networking", COLORS["stroke_networking"], 100),
        ("Observability Pipeline", COLORS["stroke_observability"], 135),
        ("AI Model / Provider", COLORS["stroke_ai_model"], 170),
        ("AWS Infrastructure", COLORS["aws_orange"], 205),
        ("Claude Code / MCP", COLORS["stroke_claude"], 240),
        ("Internal / Data", COLORS["stroke_internal"], 275),
    ]
    for label, color, yoff in legend_items:
        b.add_cell(None, "",
                   f"rounded=1;whiteSpace=wrap;html=1;fillColor={color};strokeColor={color};",
                   parent="legend", x=20, y=yoff, w=30, h=16)
        b.add_cell(None, label,
                   "text;html=1;align=left;verticalAlign=middle;resizable=0;points=[];autosize=1;strokeColor=none;fillColor=none;fontSize=10;",
                   parent="legend", x=60, y=yoff - 2, w=200, h=20)

    # Animated flow indicator
    b.add_cell(None, "<i>Animated edges ( ───▶ ) = active data flow</i>",
               "text;html=1;align=left;verticalAlign=middle;resizable=0;points=[];autosize=1;strokeColor=none;fillColor=none;fontSize=9;fontColor=#78909C;",
               parent="legend", x=20, y=320, w=300, h=20)
    b.add_cell(None, "<i>Dashed edges ( - - - ) = auth/security boundary</i>",
               "text;html=1;align=left;verticalAlign=middle;resizable=0;points=[];autosize=1;strokeColor=none;fillColor=none;fontSize=9;fontColor=#78909C;",
               parent="legend", x=20, y=340, w=300, h=20)
    b.add_cell(None, "<i>Toggle 'Engineering Details' layer for IPs/ports</i>",
               "text;html=1;align=left;verticalAlign=middle;resizable=0;points=[];autosize=1;strokeColor=none;fillColor=none;fontSize=9;fontColor=#78909C;",
               parent="legend", x=20, y=360, w=300, h=20)

    # ========================================================================
    # ENGINEERING DETAILS LAYER — IP/Port annotations
    # ========================================================================
    eng_items = [
        ("10.89.0.4", 570, 730, "ai-stack-pod IP"),
        ("10.89.0.7", 1970, 730, "auth-pod IP"),
        ("10.89.0.9", 2770, 730, "metrics-pod IP"),
        ("10.89.0.2", 170, 1380, "security-pod IP"),
        ("10.89.0.5", 1170, 1380, "mgmt-pod IP"),
        ("10.89.0.3", 1620, 1380, "frontend-pod IP"),
        ("REDACTED_DNS9 | 0.0.0.0:80,443", 1600, 695, "traefik"),
        ("REDACTED_DNS1 | 127.0.0.1:2000", 1800, 595, "cloudflared"),
        ("REDACTED_DNS6 | 127.0.0.1:5432", 100, 1725, "pg-shared"),
        ("REDACTED_DNS7 | 127.0.0.1:6379", 360, 1725, "redis"),
    ]
    for label, x, y, desc in eng_items:
        b.add_cell(None, label, STYLES["engineering_label"],
                   parent="layer_engineering", x=x, y=y, w=200, h=16)

    # ========================================================================
    # LAYER: CONTAINER NETWORKING
    # ========================================================================

    # Subnet annotation — large background behind all pods
    b.add_cell("net_subnet",
               "<b>enterprise_network</b> — REDACTED_CIDR<br/>Podman Bridge (aardvark-dns)<br/>"
               "All pods share this L2 network. DNS resolves <b>pod names</b> (not container names).",
               "rounded=1;whiteSpace=wrap;html=1;fillColor=#E0F2F1;strokeColor=#00897B;strokeWidth=2;"
               "dashed=1;dashPattern=12 4;fontSize=11;fontColor=#00695C;verticalAlign=bottom;arcSize=4;opacity=40;",
               parent="layer_networking", x=60, y=470, w=3740, h=1310)

    # Pod IP labels (one per pod)
    net_pod_ips = [
        ("ai-stack-pod", "10.89.0.4", 500, 740),
        ("authentication-pod", "10.89.0.7", 1900, 740),
        ("metrics-pod", "10.89.0.9", 2700, 740),
        ("security-pod", "10.89.0.2", 100, 1390),
        ("management-pod", "10.89.0.5", 1100, 1390),
        ("frontend-pod", "10.89.0.3", 1550, 1390),
    ]
    for pod_name, ip, px, py in net_pod_ips:
        b.add_cell(None, f"<b>{ip}</b>",
                   STYLES["network_annotation"],
                   parent="layer_networking", x=px, y=py, w=120, h=18)

    # Standalone container IPs
    net_standalone_ips = [
        ("Traefik", "REDACTED_DNS9", 1600, 610),
        ("cloudflared", "REDACTED_DNS1", 1800, 520),
        ("PostgreSQL (shared)", "REDACTED_DNS6", 100, 1630),
        ("Redis", "REDACTED_DNS7", 360, 1630),
    ]
    for name, ip, sx, sy in net_standalone_ips:
        b.add_cell(None, f"<b>{ip}</b>",
                   STYLES["network_annotation"],
                   parent="layer_networking", x=sx, y=sy, w=120, h=18)

    # Intra-pod localhost annotation
    b.add_cell("net_localhost_ai",
               "Containers share<br/>network namespace<br/>(localhost)",
               STYLES["network_annotation"] + "fontSize=8;fontStyle=0;",
               parent="layer_networking", x=1050, y=1050, w=110, h=40)
    b.add_cell("net_localhost_mon",
               "localhost<br/>namespace",
               STYLES["network_annotation"] + "fontSize=8;fontStyle=0;",
               parent="layer_networking", x=3200, y=1100, w=80, h=30)

    # Port binding annotations (external vs internal)
    b.add_cell("net_bind_ext",
               "<b>0.0.0.0:80,443</b><br/>Public-facing",
               STYLES["network_annotation"] + "fontSize=8;fontColor=#C62828;",
               parent="layer_networking", x=2100, y=630, w=120, h=30)
    b.add_cell("net_bind_int",
               "<b>127.0.0.1</b> only<br/>Internal services",
               STYLES["network_annotation"] + "fontSize=8;fontColor=#1565C0;",
               parent="layer_networking", x=100, y=1730, w=120, h=30)

    # aardvark-dns resolution arrows (Traefik -> pods)
    dns_targets = [
        ("pod_ai", "ai-stack-pod"),
        ("pod_auth", "authentication-pod"),
        ("pod_mon", "metrics-pod"),
        ("pod_sec", "security-pod"),
        ("pod_mgmt", "management-pod"),
        ("pod_front", "frontend-pod"),
    ]
    for target_id, hostname in dns_targets:
        b.add_edge(None, hostname, STYLES["edge_dns"],
                   parent="layer_networking", source="traefik", target=target_id)

    # Tetragon enforcement points (dashed red boundaries)
    b.add_cell("net_tetragon_enforce",
               "Tetragon eBPF<br/>Network Policy<br/>Enforcement",
               "text;html=1;align=center;verticalAlign=middle;resizable=0;points=[];autosize=1;"
               "strokeColor=none;fillColor=none;fontSize=8;fontColor=#C62828;fontStyle=3;",
               parent="layer_networking", x=800, y=1400, w=100, h=40)

    # DNS resolution chain annotation
    b.add_cell("net_dns_chain",
               "<b>DNS Resolution Chain:</b><br/>"
               "Browser → Cloudflare DNS → Tunnel CNAME → cloudflared<br/>"
               "→ Traefik (host matching) → aardvark-dns → Pod IP",
               "text;html=1;align=left;verticalAlign=middle;resizable=0;points=[];autosize=1;"
               f"strokeColor={COLORS['stroke_networking']};fillColor=#E0F2F1;fontSize=9;fontColor=#00695C;rounded=1;",
               parent="layer_networking", x=100, y=2170, w=400, h=50)

    # ========================================================================
    # NETWORK DIAGRAM ANNOTATION
    # ========================================================================
    net_label = b.add_cell("net_label",
                           "<b>enterprise_network</b> — REDACTED_CIDR — Podman Bridge (aardvark-dns)<br/>"
                           "All pods share this network. DNS resolves pod names (not container names).",
                           STYLES["engineering_label"] + "fillColor=#E3F2FD;fontSize=9;",
                           parent="layer_engineering", x=1200, y=2120, w=500, h=35)

    # Spend tracking flow annotation
    spend_label = b.add_cell("spend_label",
                             "<b>End-User Spend Tracking Flow:</b><br/>"
                             "1. User logs in via Authentik OIDC → OpenWebUI<br/>"
                             "2. OpenWebUI sends x-openwebui-user-email header<br/>"
                             "3. LiteLLM maps header → user field (user_header_name)<br/>"
                             "4. Per-user cost tracked in PostgreSQL<br/>"
                             "5. OTEL traces include user metadata",
                             STYLES["engineering_label"] + "fillColor=#E8F5E9;fontSize=9;",
                             parent="layer_aimodels", x=100, y=2120, w=350, h=90)

    # Voice/TTS flow annotation
    tts_label = b.add_cell("tts_label",
                           "<b>AI Voice Pipeline:</b><br/>"
                           "1. AI generates text response<br/>"
                           "2. REDACTED_DOMAIN calls Kokoro TTS<br/>"
                           "   /v1/audio/speech (OpenAI-compatible)<br/>"
                           "3. Kokoro runs CPU inference (containerized)<br/>"
                           "4. Audio streamed back to user browser",
                           STYLES["engineering_label"] + "fillColor=#FFF3E0;fontSize=9;",
                           parent="layer_aimodels", x=500, y=2120, w=300, h=90)

    return b


# ============================================================================
# MAIN
# ============================================================================

def main():
    b = build_diagram()
    xml = b.to_xml()

    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "architecture.drawio")
    with open(out_path, "w") as f:
        f.write(xml)

    print(f"Generated: {out_path}")
    print(f"  Layers: 8 (Infrastructure + 7 togglable)")
    print(f"  Elements: {len(b.cells)}")
    print(f"  Open in https://app.diagrams.net/ or VS Code draw.io extension")


if __name__ == "__main__":
    main()
