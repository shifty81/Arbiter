CTX-NORM-04
===========

Purpose:
- preserve compatibility with older ProjectControlCenter processes that call InvokeRootPatchIntake.ps1 -Apply;
- keep no-patch intake from exiting the controller process;
- detect patches that replace active control-center scripts;
- automatically relaunch the root utility after future controller self-updates;
- display an explicit Controller version in the banner.

Important for the current NORM-03 transition:
The currently open pre-NORM-03 PowerShell window must still be closed once because its controller code was loaded before NORM-03 was applied. A fresh launch loads the new controller from disk.
