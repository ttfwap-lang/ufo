#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
VirtualBox MCP Server
Provides MCP tools for managing Oracle VirtualBox VMs via VBoxManage CLI.
Supports: VM creation, configuration, start/stop, snapshots, networking, and ISO management.
"""

import logging
import os
import shutil
import subprocess
from typing import Optional

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from ufo.client.mcp.mcp_registry import MCPRegistry

logger = logging.getLogger(__name__)


def _find_vboxmanage() -> str:
    """Locate VBoxManage.exe on the system."""
    # Check common install locations
    candidates = [
        r"C:\Program Files\Oracle\VirtualBox\VBoxManage.exe",
        r"C:\Program Files (x86)\Oracle\VirtualBox\VBoxManage.exe",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path

    # Check PATH
    found = shutil.which("VBoxManage") or shutil.which("VBoxManage.exe")
    if found:
        return found

    raise ToolError(
        "VBoxManage.exe not found. Install Oracle VirtualBox from https://www.virtualbox.org/wiki/Downloads"
    )


def _run_vbox(args: list, timeout: int = 60) -> str:
    """Execute a VBoxManage command and return stdout."""
    vboxmanage = _find_vboxmanage()
    cmd = [vboxmanage] + args
    logger.info(f"[VBox] Executing: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip()
            raise ToolError(f"VBoxManage failed (exit {result.returncode}): {error_msg}")
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        raise ToolError(f"VBoxManage command timed out after {timeout}s: {' '.join(args)}")
    except FileNotFoundError:
        raise ToolError("VBoxManage.exe not found on this system.")


@MCPRegistry.register_factory_decorator("VirtualBoxExecutor")
@MCPRegistry.register_factory_decorator("virtualbox_mcp_server")
def create_virtualbox_mcp_server(*args, **kwargs) -> FastMCP:
    """Create and return the VirtualBox MCP server instance."""

    mcp = FastMCP("UFO VirtualBox MCP Server")

    @mcp.tool()
    def list_vms(running_only: bool = False) -> str:
        """
        List all registered VirtualBox VMs.
        :param running_only: If True, only show currently running VMs.
        :return: List of VMs with their names and UUIDs.
        """
        subcmd = "runningvms" if running_only else "vms"
        return _run_vbox(["list", subcmd])

    @mcp.tool()
    def show_vm_info(vm_name: str) -> str:
        """
        Show detailed information about a specific VM.
        :param vm_name: Name or UUID of the VM.
        :return: Full VM configuration details.
        """
        return _run_vbox(["showvminfo", vm_name, "--machinereadable"])

    @mcp.tool()
    def create_vm(
        name: str,
        os_type: str = "Ubuntu_64",
        ram_mb: int = 4096,
        cpus: int = 2,
        disk_gb: int = 50,
        base_folder: Optional[str] = None,
    ) -> str:
        """
        Create a new VM with disk, storage controller, and basic configuration.
        :param name: Name for the new VM.
        :param os_type: OS type identifier (e.g., Ubuntu_64, Windows11_64, Debian_64). Use list_os_types to see all.
        :param ram_mb: RAM in megabytes (default: 4096).
        :param cpus: Number of virtual CPUs (default: 2).
        :param disk_gb: Virtual disk size in gigabytes (default: 50).
        :param base_folder: Optional base folder for VM files. Defaults to VirtualBox default.
        :return: Summary of created VM.
        """
        results = []

        # 1. Create the VM
        create_args = ["createvm", "--name", name, "--ostype", os_type, "--register"]
        if base_folder:
            create_args.extend(["--basefolder", base_folder])
        results.append(_run_vbox(create_args))

        # 2. Configure RAM, CPUs, video, and basic settings
        modify_args = [
            "modifyvm", name,
            "--memory", str(ram_mb),
            "--cpus", str(cpus),
            "--vram", "128",
            "--graphicscontroller", "vmsvga",
            "--audio-driver", "default",
            "--boot1", "dvd",
            "--boot2", "disk",
            "--boot3", "none",
            "--boot4", "none",
            "--clipboard-mode", "bidirectional",
            "--draganddrop", "bidirectional",
        ]
        results.append(_run_vbox(modify_args))

        # 3. Add SATA storage controller
        results.append(_run_vbox([
            "storagectl", name,
            "--name", "SATA Controller",
            "--add", "sata",
            "--controller", "IntelAhci",
            "--portcount", "4",
        ]))

        # 4. Create virtual hard disk
        # Determine VM folder path
        vm_info = _run_vbox(["showvminfo", name, "--machinereadable"])
        vm_folder = None
        for line in vm_info.splitlines():
            if line.startswith("CfgFile="):
                cfg_path = line.split("=", 1)[1].strip('"')
                vm_folder = os.path.dirname(cfg_path)
                break

        if not vm_folder:
            vm_folder = os.path.join(os.path.expanduser("~"), "VirtualBox VMs", name)

        disk_path = os.path.join(vm_folder, f"{name}.vdi")
        results.append(_run_vbox([
            "createmedium", "disk",
            "--filename", disk_path,
            "--size", str(disk_gb * 1024),  # Convert GB to MB
            "--format", "VDI",
            "--variant", "Standard",
        ]))

        # 5. Attach disk to SATA controller
        results.append(_run_vbox([
            "storageattach", name,
            "--storagectl", "SATA Controller",
            "--port", "0",
            "--device", "0",
            "--type", "hdd",
            "--medium", disk_path,
        ]))

        # 6. Add IDE controller for DVD/ISO
        results.append(_run_vbox([
            "storagectl", name,
            "--name", "IDE Controller",
            "--add", "ide",
        ]))

        return f"VM '{name}' created successfully.\n" + "\n".join(r for r in results if r)

    @mcp.tool()
    def attach_iso(vm_name: str, iso_path: str) -> str:
        """
        Attach an ISO image to a VM's DVD drive for installation.
        :param vm_name: Name of the VM.
        :param iso_path: Absolute path to the ISO file.
        :return: Confirmation message.
        """
        if not os.path.isfile(iso_path):
            raise ToolError(f"ISO file not found: {iso_path}")

        return _run_vbox([
            "storageattach", vm_name,
            "--storagectl", "IDE Controller",
            "--port", "0",
            "--device", "0",
            "--type", "dvddrive",
            "--medium", iso_path,
        ]) or f"ISO '{os.path.basename(iso_path)}' attached to VM '{vm_name}'."

    @mcp.tool()
    def start_vm(vm_name: str, headless: bool = False) -> str:
        """
        Start a VM.
        :param vm_name: Name of the VM to start.
        :param headless: If True, start in headless mode (no GUI window).
        :return: Confirmation message.
        """
        vm_type = "headless" if headless else "gui"
        return _run_vbox(["startvm", vm_name, "--type", vm_type], timeout=120)

    @mcp.tool()
    def stop_vm(vm_name: str, force: bool = False) -> str:
        """
        Stop a running VM.
        :param vm_name: Name of the VM to stop.
        :param force: If True, power off immediately. If False, send ACPI shutdown.
        :return: Confirmation message.
        """
        action = "poweroff" if force else "acpipowerbutton"
        return _run_vbox(["controlvm", vm_name, action])

    @mcp.tool()
    def configure_network(
        vm_name: str,
        adapter: int = 1,
        mode: str = "nat",
        bridge_adapter: Optional[str] = None,
    ) -> str:
        """
        Configure a VM's network adapter.
        :param vm_name: Name of the VM.
        :param adapter: Adapter number (1-4, default: 1).
        :param mode: Network mode: 'nat', 'bridged', 'intnet', 'hostonly', 'natnetwork'.
        :param bridge_adapter: Required for 'bridged' mode — name of the host network adapter.
        :return: Confirmation message.
        """
        args = ["modifyvm", vm_name]
        nic_key = f"--nic{adapter}"

        if mode == "nat":
            args.extend([nic_key, "nat"])
        elif mode == "bridged":
            if not bridge_adapter:
                # Auto-detect first available bridge adapter
                host_info = _run_vbox(["list", "bridgedifs"])
                for line in host_info.splitlines():
                    if line.startswith("Name:"):
                        bridge_adapter = line.split(":", 1)[1].strip()
                        break
                if not bridge_adapter:
                    raise ToolError("No bridged network adapters found on host.")
            args.extend([nic_key, "bridged", f"--bridgeadapter{adapter}", bridge_adapter])
        elif mode == "intnet":
            args.extend([nic_key, "intnet"])
        elif mode == "hostonly":
            args.extend([nic_key, "hostonlynet"])
        elif mode == "natnetwork":
            args.extend([nic_key, "natnetwork"])
        else:
            raise ToolError(f"Unknown network mode: {mode}. Use: nat, bridged, intnet, hostonly, natnetwork")

        return _run_vbox(args) or f"Network adapter {adapter} on '{vm_name}' set to '{mode}'."

    @mcp.tool()
    def take_snapshot(vm_name: str, snapshot_name: str, description: str = "") -> str:
        """
        Take a snapshot of a VM.
        :param vm_name: Name of the VM.
        :param snapshot_name: Name for the snapshot.
        :param description: Optional description.
        :return: Confirmation message.
        """
        args = ["snapshot", vm_name, "take", snapshot_name]
        if description:
            args.extend(["--description", description])
        return _run_vbox(args, timeout=300)

    @mcp.tool()
    def restore_snapshot(vm_name: str, snapshot_name: str) -> str:
        """
        Restore a VM to a previous snapshot.
        :param vm_name: Name of the VM.
        :param snapshot_name: Name of the snapshot to restore.
        :return: Confirmation message.
        """
        return _run_vbox(["snapshot", vm_name, "restore", snapshot_name])

    @mcp.tool()
    def delete_vm(vm_name: str, delete_files: bool = True) -> str:
        """
        Unregister and optionally delete all files for a VM.
        :param vm_name: Name of the VM to delete.
        :param delete_files: If True, also delete all associated disk images and files.
        :return: Confirmation message.
        """
        args = ["unregistervm", vm_name]
        if delete_files:
            args.append("--delete")
        return _run_vbox(args) or f"VM '{vm_name}' has been removed."

    @mcp.tool()
    def list_os_types() -> str:
        """
        List all supported OS types for VM creation.
        :return: List of OS type identifiers and descriptions.
        """
        return _run_vbox(["list", "ostypes"])

    @mcp.tool()
    def enable_rdp(vm_name: str, port: int = 3389) -> str:
        """
        Enable VRDP (VirtualBox Remote Desktop) on a VM for remote access.
        :param vm_name: Name of the VM.
        :param port: RDP port number (default: 3389).
        :return: Confirmation message.
        """
        return _run_vbox([
            "modifyvm", vm_name,
            "--vrde", "on",
            "--vrdeport", str(port),
        ]) or f"VRDP enabled on VM '{vm_name}' at port {port}."

    return mcp

if __name__ == "__main__":
    import logging
    # Suppress output that might corrupt JSON
    logging.basicConfig(level=logging.ERROR)
    mcp = create_virtualbox_mcp_server()
    mcp.run()
