Option Explicit

' ==============================================================================
' BankFidelity Admin Launcher (Elevated UAC Dispatcher)
' Architecture: Financial-Grade Zero-Trust Desktop Entrypoint
' ==============================================================================

Dim fso, shApp, wshShell, scriptDir, targetBat, desktopPath, errNum, errDesc

On Error Resume Next

' 1. Instantiate Core FileSystemObject
Set fso = CreateObject("Scripting.FileSystemObject")
If Err.Number <> 0 Then
    MsgBox "FATAL: Failed to initialize Scripting.FileSystemObject: " & Err.Description, vbCritical, "BankFidelity Security Guard"
    WScript.Quit 5 ' ERROR_ACCESS_DENIED / IO
End If

' 2. Determine Secure Script Directory
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
targetBat = fso.BuildPath(scriptDir, "01_BankFidelity_Terminal.bat")

' Fallback to user Desktop folder if moved
If Not fso.FileExists(targetBat) Then
    Set wshShell = CreateObject("WScript.Shell")
    If Err.Number = 0 And Not (wshShell Is Nothing) Then
        desktopPath = wshShell.SpecialFolders("Desktop")
        targetBat = fso.BuildPath(desktopPath, "01_BankFidelity_Terminal.bat")
    End If
End If

' 3. Pre-Flight Verification: Validate target executable existence
If Not fso.FileExists(targetBat) Then
    MsgBox "SECURITY ALERT: Target launcher not found at:" & vbCrLf & targetBat & vbCrLf & vbCrLf & _
           "Please ensure 01_BankFidelity_Terminal.bat exists in the same directory.", vbCritical, "BankFidelity Pre-Flight Failure"
    Set fso = Nothing
    Set wshShell = Nothing
    WScript.Quit 2 ' ERROR_FILE_NOT_FOUND
End If

' 4. Instantiate Shell Application for UAC Elevation
Set shApp = CreateObject("Shell.Application")
If Err.Number <> 0 Then
    MsgBox "FATAL: Failed to initialize Shell.Application COM interface: " & Err.Description, vbCritical, "BankFidelity Elevation Failure"
    Set fso = Nothing
    Set wshShell = Nothing
    WScript.Quit 1
End If

' 5. Dispatch Elevated Process (runas verb via cmd.exe wrapper)
shApp.ShellExecute "cmd.exe", "/c """ & targetBat & """", scriptDir, "runas", 1
errNum = Err.Number
errDesc = Err.Description

' 6. Robust Error Handling
If errNum <> 0 Then
    If errNum = 1223 Then
        ' 1223 = ERROR_CANCELLED (User cancelled UAC elevation prompt)
        MsgBox "Elevation request was declined by the user. BankFidelity Terminal cannot start with required administrative privileges.", vbExclamation, "BankFidelity Security Warning"
    Else
        MsgBox "Failed to execute elevated target:" & vbCrLf & errDesc & " (Error " & Hex(errNum) & ")", vbCritical, "BankFidelity Dispatch Error"
    End If
End If

' 7. Mandatory COM Cleanup to Prevent Resource Leaks
Set fso = Nothing
Set shApp = Nothing
Set wshShell = Nothing

If errNum <> 0 Then
    WScript.Quit errNum
Else
    WScript.Quit 0
End If
