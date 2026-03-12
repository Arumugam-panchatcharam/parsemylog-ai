"""
Ground Truth Data Generator
============================

Generates synthetic CPE log datasets with known anomalies for validation testing.

Uses real ripgrep-filtered templates from the codebase to create realistic
synthetic data with injected anomalies.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


@dataclass
class GroundTruthLabel:
    """Label for a known anomaly in ground truth dataset."""
    template: str
    timestamp: str
    anomaly_type: str  # "frequency_spike", "novel_template", "sequence_break"
    severity: str  # "low", "medium", "high"
    description: str


@dataclass
class GroundTruthDataset:
    """Complete ground truth dataset with labels."""
    df: pd.DataFrame  # Contains columns: timestamp, template, loglines, is_anomaly
    anomaly_labels: List[GroundTruthLabel]
    baseline_templates: List[str]
    total_lines: int
    normal_lines: int
    anomalous_lines: int


class GroundTruthGenerator:
    """
    Generates synthetic CPE log datasets with known anomalies.
    
    Strategy:
        1. Start with baseline "normal" templates from real RDK logs
        2. Generate temporal sequence with realistic distribution
        3. Inject specific anomaly types at known positions
        4. Return labeled dataset for validation
    
    Anomaly Types:
        - Frequency spike: Repeat an error template 50x in one window
        - Novel template: Insert never-before-seen error message
        - Sequence break: Insert template that violates normal sequence order
    """
    
    def __init__(
        self,
        baseline_templates: Optional[List[str]] = None,
        normal_line_count: int = 1000,
        anomaly_count: int = 50,
        window_minutes: int = 15,
    ):
        """
        Args:
            baseline_templates: Real templates to use as normal baseline.
                              If None, uses built-in RDK-like templates.
            normal_line_count: Number of normal log lines to generate.
            anomaly_count: Number of anomalous log lines to inject.
            window_minutes: Time window size for frequency spike injection.
        """
        self.baseline_templates = baseline_templates or self._get_default_templates()
        self.normal_line_count = normal_line_count
        self.anomaly_count = anomaly_count
        self.window_minutes = window_minutes
    
    def generate(self) -> GroundTruthDataset:
        """
        Generate a complete ground truth dataset.
        
        Returns:
            GroundTruthDataset with labeled anomalies.
        """
        # Generate normal baseline
        normal_data = self._generate_normal_sequence()
        
        # Inject anomalies
        anomalous_data, labels = self._inject_anomalies(normal_data)
        
        # Combine and create DataFrame
        all_data = normal_data + anomalous_data
        all_data.sort(key=lambda x: x["timestamp"])
        
        df = pd.DataFrame(all_data)
        df["is_anomaly"] = df["template"].apply(
            lambda t: any(label.template == t for label in labels)
        )
        
        return GroundTruthDataset(
            df=df,
            anomaly_labels=labels,
            baseline_templates=self.baseline_templates,
            total_lines=len(df),
            normal_lines=self.normal_line_count,
            anomalous_lines=self.anomaly_count,
        )
    
    def _generate_normal_sequence(self) -> List[Dict[str, Any]]:
        """Generate normal log sequence with realistic distribution."""
        data = []
        start_time = datetime(2026, 1, 1, 0, 0, 0)
        
        # Create realistic template frequency distribution
        # 80% common templates, 15% occasional, 5% rare
        common_templates = self.baseline_templates[:max(1, len(self.baseline_templates) // 5)]
        occasional_templates = self.baseline_templates[len(common_templates):max(1, len(self.baseline_templates) // 2)]
        rare_templates = self.baseline_templates[max(1, len(self.baseline_templates) // 2):]
        
        for i in range(self.normal_line_count):
            # Realistic time progression (1-10 seconds between logs)
            timestamp = start_time + timedelta(seconds=random.randint(1, 10) * i)
            
            # Select template based on frequency distribution
            rand = random.random()
            if rand < 0.80:
                template = random.choice(common_templates) if common_templates else self.baseline_templates[0]
            elif rand < 0.95:
                template = random.choice(occasional_templates) if occasional_templates else self.baseline_templates[0]
            else:
                template = random.choice(rare_templates) if rare_templates else self.baseline_templates[0]
            
            data.append({
                "timestamp": timestamp,
                "template": template,
                "loglines": self._template_to_logline(template, i),
            })
        
        return data
    
    def _inject_anomalies(
        self, normal_data: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[GroundTruthLabel]]:
        """Inject different types of anomalies into the dataset."""
        anomalous_data = []
        labels = []
        
        # Get timestamp range
        last_normal_time = normal_data[-1]["timestamp"]
        
        # 1. Frequency Spike (40% of anomalies)
        spike_count = int(self.anomaly_count * 0.4)
        spike_template = random.choice(self.baseline_templates)
        spike_start_time = last_normal_time + timedelta(minutes=5)
        
        for i in range(spike_count):
            timestamp = spike_start_time + timedelta(seconds=i * 2)
            anomalous_data.append({
                "timestamp": timestamp,
                "template": spike_template,
                "loglines": self._template_to_logline(spike_template, len(normal_data) + i),
            })
        
        labels.append(GroundTruthLabel(
            template=spike_template,
            timestamp=spike_start_time.isoformat(),
            anomaly_type="frequency_spike",
            severity="high",
            description=f"Frequency spike: {spike_count} occurrences in {self.window_minutes} min window",
        ))
        
        # 2. Novel Templates (30% of anomalies)
        novel_count = int(self.anomaly_count * 0.3)
        novel_templates = self._generate_novel_templates(novel_count)
        novel_start_time = spike_start_time + timedelta(minutes=10)
        
        for i, novel_template in enumerate(novel_templates):
            timestamp = novel_start_time + timedelta(seconds=i * 5)
            anomalous_data.append({
                "timestamp": timestamp,
                "template": novel_template,
                "loglines": self._template_to_logline(novel_template, len(normal_data) + spike_count + i),
            })
            
            labels.append(GroundTruthLabel(
                template=novel_template,
                timestamp=timestamp.isoformat(),
                anomaly_type="novel_template",
                severity="medium",
                description="Never-before-seen error template",
            ))
        
        # 3. Sequence Breaks (30% of anomalies)
        break_count = int(self.anomaly_count * 0.3)
        # Use templates that typically don't follow each other
        break_start_time = novel_start_time + timedelta(minutes=10)
        
        for i in range(break_count):
            # Create intentionally unusual sequence
            timestamp = break_start_time + timedelta(seconds=i * 3)
            unusual_template = random.choice(self.baseline_templates)
            anomalous_data.append({
                "timestamp": timestamp,
                "template": unusual_template,
                "loglines": self._template_to_logline(unusual_template, len(normal_data) + spike_count + novel_count + i),
            })
        
        if break_count > 0:
            labels.append(GroundTruthLabel(
                template="<sequence_break>",
                timestamp=break_start_time.isoformat(),
                anomaly_type="sequence_break",
                severity="low",
                description=f"Unusual template sequence: {break_count} out-of-order templates",
            ))
        
        return anomalous_data, labels
    
    def _generate_novel_templates(self, count: int) -> List[str]:
        """Generate novel error templates not in baseline."""
        novel_templates = [
            "RDKB_SYSTEM_BOOT_UP_ERROR: Critical boot failure detected <*>",
            "WiFi_HAL_ERROR: Unexpected radio <*> crash with code <*>",
            "MESH_CONN_ERROR: Mesh node <*> unreachable for <*> seconds",
            "DNS_RESOLVER_FAILURE: DNS query timeout for <*> retries",
            "FIREWALL_RULE_VIOLATION: Unauthorized access attempt from <*>",
            "MEMORY_LEAK_DETECTED: Process <*> consuming <*> MB (threshold exceeded)",
            "THERMAL_CRITICAL: Device temperature <*> C exceeds safe limit",
            "WAN_CONNECTION_LOST: ISP link down for <*> minutes",
            "LAN_DHCP_EXHAUSTED: No available IP addresses in pool <*>",
            "FIRMWARE_CORRUPTION: Image verification failed with hash mismatch",
            "TR069_ACS_TIMEOUT: Connection to ACS server <*> timed out",
            "USB_DEVICE_ERROR: Unsupported USB device <*> detected on port <*>",
            "PARENTAL_CONTROL_BLOCK: Access denied for device <*> to site <*>",
            "QOS_BANDWIDTH_EXCEEDED: Traffic limit <*> Mbps exceeded by <*> %",
            "VPN_TUNNEL_FAILURE: IPSec tunnel <*> establishment failed",
        ]
        return novel_templates[:count]
    
    def _get_default_templates(self) -> List[str]:
        """Get default RDK-like log templates for baseline."""
        return [
            "WiFi_INFO: Client <*> connected to SSID <*> on band <*>",
            "WiFi_INFO: Client <*> disconnected from SSID <*>",
            "DHCP_INFO: Lease assigned to <*> with IP <*>",
            "DHCP_INFO: Lease renewed for client <*>",
            "WAN_INFO: WAN connection established with IP <*>",
            "WAN_INFO: DNS servers updated to <*>",
            "LAN_INFO: Interface <*> up with address <*>",
            "SYSTEM_INFO: CPU usage: <*> %",
            "SYSTEM_INFO: Memory usage: <*> MB",
            "FIREWALL_INFO: Port <*> opened for service <*>",
            "MESH_INFO: Mesh topology updated, <*> nodes active",
            "TR069_INFO: Periodic inform sent to ACS",
            "PARENTAL_CONTROL_INFO: Schedule <*> activated for device <*>",
            "QOS_INFO: Bandwidth allocation updated for stream <*>",
            "FIRMWARE_INFO: Version <*> running, uptime <*> hours",
            "WiFi_WARN: High channel utilization <*> % on band <*>",
            "DHCP_WARN: IP conflict detected for address <*>",
            "WAN_WARN: Packet loss <*> % detected on upstream",
            "SYSTEM_WARN: Disk usage above <*> % threshold",
            "MESH_WARN: Node <*> signal strength below <*> dBm",
        ]
    
    def _template_to_logline(self, template: str, line_num: int) -> str:
        """Convert template to realistic log line with parameters."""
        # Replace <*> placeholders with realistic values
        logline = template
        replacements = {
            "<*>": [
                str(random.randint(1, 100)),
                f"{random.randint(1, 255)}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(0, 255)}",
                f"AA:BB:CC:DD:EE:{random.randint(10, 99)}",
                f"{random.randint(1, 24)}",
                f"{random.choice(['2.4GHz', '5GHz'])}",
                f"Guest_{random.randint(1, 10)}",
                "eth0",
                "wlan0",
                str(random.randint(1024, 65535)),
            ]
        }
        
        for placeholder, values in replacements.items():
            while placeholder in logline:
                logline = logline.replace(placeholder, random.choice(values), 1)
        
        return f"[{line_num:06d}] {logline}"


def generate_test_dataset(
    normal_lines: int = 1000,
    anomaly_lines: int = 50,
) -> GroundTruthDataset:
    """
    Convenience function to generate a test dataset.
    
    Args:
        normal_lines: Number of normal log lines.
        anomaly_lines: Number of anomalous log lines.
    
    Returns:
        GroundTruthDataset ready for validation.
    """
    generator = GroundTruthGenerator(
        normal_line_count=normal_lines,
        anomaly_count=anomaly_lines,
    )
    return generator.generate()
