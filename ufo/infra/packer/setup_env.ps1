# =============================================================================
# UFO Fleet — Headless Environment Setup Script (PowerShell)
# =============================================================================
#
# Configures a pristine Windows environment for headless UI automation.
# Ensures the agent has an interactive desktop session without interference
# from UAC, lock screens, or power saving features.
#
# Variables injected by Packer:
#   $env:UFO_SERVICE_USER
#   $env:UFO_SERVICE_PASS
# =============================================================================

Write-Host ">>> Configuring UFO Headless Automation Environment..."

$User = $env:UFO_SERVICE_USER
$Pass = $env:UFO_SERVICE_PASS

if ([string]::IsNullOrEmpty($User)) { $User = "UFO_Service" }

# ---------------------------------------------------------------------------
# 1. Disable User Account Control (UAC)
# ---------------------------------------------------------------------------
# Prevents the "Secure Desktop" dimming which completely breaks vision
# models and UI automation bounding boxes.
Write-Host ">>> Disabling UAC..."
Set-ItemProperty -Path "REGISTRY::HKEY_LOCAL_MACHINE\Software\Microsoft\Windows\CurrentVersion\Policies\System" -Name "EnableLUA" -Value 0
Set-ItemProperty -Path "REGISTRY::HKEY_LOCAL_MACHINE\Software\Microsoft\Windows\CurrentVersion\Policies\System" -Name "PromptOnSecureDesktop" -Value 0
Set-ItemProperty -Path "REGISTRY::HKEY_LOCAL_MACHINE\Software\Microsoft\Windows\CurrentVersion\Policies\System" -Name "ConsentPromptBehaviorAdmin" -Value 0

# ---------------------------------------------------------------------------
# 2. Configure AutoAdminLogon
# ---------------------------------------------------------------------------
# Ensures the VM immediately drops into an active desktop session on boot.
Write-Host ">>> Configuring Auto-Login for $User..."
Set-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' -Name 'AutoAdminLogon' -Value '1'
Set-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' -Name 'DefaultUserName' -Value $User
if (-not [string]::IsNullOrEmpty($Pass)) {
    Set-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' -Name 'DefaultPassword' -Value $Pass
}

# ---------------------------------------------------------------------------
# 3. Disable Power Savings & Lock Screens
# ---------------------------------------------------------------------------
Write-Host ">>> Disabling power savings and lock screens..."
# Monitor & sleep timeouts
powercfg -change -monitor-timeout-ac 0
powercfg -change -standby-timeout-ac 0
powercfg -change -hibernate-timeout-ac 0

# Disable Screensaver
New-ItemProperty -Path 'HKCU:\Control Panel\Desktop' -Name 'ScreenSaveActive' -Value '0' -PropertyType String -Force | Out-Null
New-ItemProperty -Path 'HKCU:\Control Panel\Desktop' -Name 'ScreenSaverIsSecure' -Value '0' -PropertyType String -Force | Out-Null

# Disable lock screen
$lockKey = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\Personalization"
if (-not (Test-Path $lockKey)) { New-Item -Path $lockKey -Force | Out-Null }
Set-ItemProperty -Path $lockKey -Name "NoLockScreen" -Value 1

# ---------------------------------------------------------------------------
# 4. Strict Display Resolution (1920x1080)
# ---------------------------------------------------------------------------
# UI automation bounding boxes must be absolutely deterministic.
Write-Host ">>> Forcing 1920x1080 resolution..."
# Native PowerShell resolution changing is difficult without C# compilation.
# We compile a tiny C# snippet on the fly to call ChangeDisplaySettings.

$Code = @"
using System;
using System.Runtime.InteropServices;
public class Display {
    [DllImport("user32.dll")]
    public static extern int ChangeDisplaySettings(ref DEVMODE devMode, int flags);

    [StructLayout(LayoutKind.Sequential)]
    public struct DEVMODE {
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmDeviceName;
        public short dmSpecVersion;
        public short dmDriverVersion;
        public short dmSize;
        public short dmDriverExtra;
        public int dmFields;
        public int dmPositionX;
        public int dmPositionY;
        public int dmDisplayOrientation;
        public int dmDisplayFixedOutput;
        public short dmColor;
        public short dmDuplex;
        public short dmYResolution;
        public short dmTTOption;
        public short dmCollate;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmFormName;
        public short dmLogPixels;
        public short dmBitsPerPel;
        public int dmPelsWidth;
        public int dmPelsHeight;
        public int dmDisplayFlags;
        public int dmDisplayFrequency;
    }

    public static void SetResolution(int width, int height) {
        DEVMODE dm = new DEVMODE();
        dm.dmSize = (short)Marshal.SizeOf(typeof(DEVMODE));
        dm.dmPelsWidth = width;
        dm.dmPelsHeight = height;
        dm.dmFields = 0x00080000 | 0x00100000; // DM_PELSWIDTH | DM_PELSHEIGHT
        ChangeDisplaySettings(ref dm, 0);
    }
}
"@
Add-Type -TypeDefinition $Code -Language CSharp
[Display]::SetResolution(1920, 1080)

Write-Host ">>> Environment prep complete!"
