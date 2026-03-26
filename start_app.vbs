Option Explicit

Dim shell, fso, appDir, pythonw, launcher, url
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

appDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = appDir & "\.venv\Scripts\pythonw.exe"
launcher = appDir & "\scripts\launch_server.pyw"
url = "http://127.0.0.1:8000/?launch=" & CStr(Timer * 1000)

If Not fso.FileExists(pythonw) Then
  MsgBox "Virtual environment not found in " & appDir & "." & vbCrLf & _
         "Run setup first: python -m venv .venv, then install requirements.", _
         vbCritical, "Local Media Downloader"
  WScript.Quit 1
End If

If Not fso.FileExists(launcher) Then
  MsgBox "Launcher script not found: " & launcher, vbCritical, "Local Media Downloader"
  WScript.Quit 1
End If

' Stop any previous server bound to port 8000.
shell.Run "powershell.exe -NoProfile -Command ""Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }""", 0, True

' Start the server without a console window.
shell.Run """" & pythonw & """ """ & launcher & """", 0, False

If WaitForServer("http://127.0.0.1:8000/") Then
  shell.Run "rundll32 url.dll,FileProtocolHandler " & url, 0, False
Else
  MsgBox "Server failed to start on port 8000." & vbCrLf & _
         "Check server.stderr.log for details.", _
         vbCritical, "Local Media Downloader"
  WScript.Quit 1
End If

Function WaitForServer(testUrl)
  Dim http, i
  WaitForServer = False

  For i = 1 To 30
    WScript.Sleep 500
    On Error Resume Next
    Set http = CreateObject("MSXML2.XMLHTTP")
    http.Open "GET", testUrl, False
    http.Send
    If Err.Number = 0 Then
      If http.Status = 200 Then
        WaitForServer = True
        Exit Function
      End If
    End If
    On Error GoTo 0
  Next
End Function
