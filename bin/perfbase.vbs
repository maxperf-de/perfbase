
Set WSHShell=WScript.CreateObject("WScript.Shell") 
Set Shell=WScript.CreateObject("Shell.Application") 

Set objArgs = WScript.Arguments
WScript.StdOut.Write(objArgs.Count)
For Each strArg in objArgs
    WScript.StdOut.Write(strArg)
Next

WSHShell.popup "Done!"
