# Cortex VS Code Bridge

This extension is a thin trusted IDE adapter for the standalone Cortex service.

Development:

```powershell
npm install
npm run compile
```

Then load `extensions/cortex-vscode` as an Extension Development Host and run **Cortex: Start VS Code Bridge**.

Default loopback ports:

- Cortex service: `7337`
- VS Code bridge: `7338`
