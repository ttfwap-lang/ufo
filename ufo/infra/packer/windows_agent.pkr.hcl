# =============================================================================
# UFO Fleet — Windows Agent Golden Image (Packer HCL)
# =============================================================================
#
# Builds a Windows Server 2022 VM image pre-configured for headless UI
# automation: auto-login desktop session, disabled UAC, locked 1920x1080
# resolution, and the UFO Event Daemon as a scheduled task.
#
# Usage:
#   packer init infra/packer/
#   packer build -var "admin_password=<secret>" infra/packer/windows_agent.pkr.hcl
#
# Supports builders: azure-arm, vsphere-iso, hyperv-iso, virtualbox-iso
# =============================================================================

packer {
  required_plugins {
    azure = {
      source  = "github.com/hashicorp/azure"
      version = "~> 2"
    }
  }
}

# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------

variable "subscription_id" {
  type        = string
  description = "Azure subscription ID"
  default     = env("AZURE_SUBSCRIPTION_ID")
}

variable "resource_group" {
  type        = string
  description = "Resource group for the managed image"
  default     = "rg-ufo-fleet"
}

variable "image_name" {
  type        = string
  description = "Name of the output golden image"
  default     = "ufo-agent-win2022"
}

variable "admin_username" {
  type    = string
  default = "UFO_Service"
}

variable "admin_password" {
  type      = string
  sensitive = true
}

variable "vm_size" {
  type        = string
  description = "Azure VM size for the build"
  default     = "Standard_D4s_v5"
}

variable "ufo_repo_url" {
  type        = string
  description = "Git URL for the UFO codebase"
  default     = "https://github.com/org/ufo.git"
}

variable "ufo_branch" {
  type    = string
  default = "main"
}

# ---------------------------------------------------------------------------
# Source: Azure ARM (Windows Server 2022)
# ---------------------------------------------------------------------------

source "azure-arm" "windows_agent" {
  subscription_id = var.subscription_id

  managed_image_name                = var.image_name
  managed_image_resource_group_name = var.resource_group

  os_type         = "Windows"
  image_publisher = "MicrosoftWindowsServer"
  image_offer     = "WindowsServer"
  image_sku       = "2022-datacenter-g2"

  communicator   = "winrm"
  winrm_use_ssl  = true
  winrm_insecure = true
  winrm_timeout  = "10m"
  winrm_username = var.admin_username

  vm_size = var.vm_size

  # Temp resource group (auto-cleaned)
  temp_resource_group_name = "rg-packer-temp-ufo"
  location                 = "eastus2"

  # Generalize the image
  azure_tags = {
    purpose     = "ufo-fleet-agent"
    managed_by  = "packer"
    created     = timestamp()
  }
}

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

build {
  name    = "ufo-agent"
  sources = ["source.azure-arm.windows_agent"]

  # --- Phase 1: OS Configuration (UAC, auto-login, power, resolution) ---
  provisioner "powershell" {
    script = "${path.root}/setup_env.ps1"
    environment_vars = [
      "UFO_SERVICE_USER=${var.admin_username}",
      "UFO_SERVICE_PASS=${var.admin_password}",
    ]
  }

  # --- Phase 2: Install Python & Dependencies ---
  provisioner "powershell" {
    inline = [
      "Write-Host '>>> Installing Python 3.11...'",
      "$pythonUrl = 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe'",
      "$installer = 'C:\\temp\\python_installer.exe'",
      "New-Item -ItemType Directory -Force -Path 'C:\\temp' | Out-Null",
      "Invoke-WebRequest -Uri $pythonUrl -OutFile $installer",
      "Start-Process -Wait -FilePath $installer -ArgumentList '/quiet InstallAllUsers=1 PrependPath=1 TargetDir=C:\\Python311'",
      "Remove-Item $installer -Force",
      "",
      "Write-Host '>>> Python installed:'",
      "C:\\Python311\\python.exe --version",
    ]
  }

  # --- Phase 3: Clone UFO & Install Requirements ---
  provisioner "powershell" {
    inline = [
      "Write-Host '>>> Cloning UFO repository...'",
      "git clone --branch ${var.ufo_branch} --depth 1 ${var.ufo_repo_url} C:\\ufo\\ufo",
      "",
      "Write-Host '>>> Creating Python virtual environment...'",
      "C:\\Python311\\python.exe -m venv C:\\ufo\\ufo\\python_env",
      "",
      "Write-Host '>>> Installing requirements...'",
      "C:\\ufo\\ufo\\python_env\\Scripts\\pip.exe install -r C:\\ufo\\ufo\\requirements.txt",
      "",
      "Write-Host '>>> UFO deployment complete.'",
    ]
  }

  # --- Phase 4: Register UFO Event Daemon as Scheduled Task ---
  provisioner "powershell" {
    inline = [
      "Write-Host '>>> Registering UFOEventDaemon scheduled task...'",
      "",
      "$action = New-ScheduledTaskAction `",
      "  -Execute 'C:\\ufo\\ufo\\python_env\\Scripts\\python.exe' `",
      "  -Argument '-m ufo.fleet.event_daemon' `",
      "  -WorkingDirectory 'C:\\ufo\\ufo'",
      "",
      "$trigger = New-ScheduledTaskTrigger -AtLogon",
      "",
      "$principal = New-ScheduledTaskPrincipal `",
      "  -UserId '${var.admin_username}' `",
      "  -LogonType Interactive `",
      "  -RunLevel Highest",
      "",
      "$settings = New-ScheduledTaskSettingsSet `",
      "  -AllowStartIfOnBatteries `",
      "  -DontStopIfGoingOnBatteries `",
      "  -StartWhenAvailable `",
      "  -RestartCount 3 `",
      "  -RestartInterval (New-TimeSpan -Minutes 1)",
      "",
      "Register-ScheduledTask `",
      "  -TaskName 'UFOEventDaemon' `",
      "  -Action $action `",
      "  -Trigger $trigger `",
      "  -Principal $principal `",
      "  -Settings $settings `",
      "  -Description 'UFO Agent Event Daemon - headless UI automation worker' `",
      "  -Force",
      "",
      "Write-Host '>>> Scheduled task registered successfully.'",
    ]
  }

  # --- Phase 5: Sysprep / Generalize ---
  provisioner "powershell" {
    inline = [
      "Write-Host '>>> Running Sysprep for image generalization...'",
      "& $env:SystemRoot\\System32\\Sysprep\\Sysprep.exe /oobe /generalize /quiet /quit /mode:vm",
      "",
      "while ($true) {",
      "  $imageState = (Get-ItemProperty HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Setup\\State).ImageState",
      "  Write-Host \"Image state: $imageState\"",
      "  if ($imageState -eq 'IMAGE_STATE_GENERALIZE_RESEAL_TO_OOBE') { break }",
      "  Start-Sleep -Seconds 10",
      "}",
      "Write-Host '>>> Sysprep complete. Image ready for capture.'",
    ]
  }
}
