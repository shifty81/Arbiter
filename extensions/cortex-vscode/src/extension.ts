import * as vscode from "vscode";
import * as net from "net";
import * as path from "path";
import * as fs from "fs";

const PROTOCOL_VERSION = 1;
let bridge: net.Server | undefined;

interface RpcRequest {
  protocol_version: number;
  id: string;
  method: string;
  params?: any;
  auth_token?: string;
}

interface RpcResponse {
  protocol_version: number;
  id: string;
  ok: boolean;
  result: any;
  error?: string;
}

export function activate(context: vscode.ExtensionContext) {
  context.subscriptions.push(
    vscode.commands.registerCommand("cortex.startBridge", () => startBridge()),
    vscode.commands.registerCommand("cortex.stopBridge", () => stopBridge()),
    vscode.commands.registerCommand("cortex.askAboutSelection", () => askAboutSelection())
  );
}

export function deactivate() {
  stopBridge();
}

async function startBridge() {
  if (bridge) {
    vscode.window.showInformationMessage("Cortex VS Code bridge is already running.");
    return;
  }

  const port = vscode.workspace.getConfiguration("cortex").get<number>("bridgePort", 7338);
  bridge = net.createServer(socket => {
    if (!socket.remoteAddress || !isLoopback(socket.remoteAddress)) {
      socket.destroy();
      return;
    }

    let buffer = "";
    socket.setEncoding("utf8");
    socket.on("data", chunk => {
      buffer += chunk;
      for (;;) {
        const newline = buffer.indexOf("\n");
        if (newline < 0) break;
        const line = buffer.slice(0, newline).trim();
        buffer = buffer.slice(newline + 1);
        if (!line) continue;
        void handleLine(line).then(response => {
          socket.write(JSON.stringify(response) + "\n");
        });
      }
    });
  });

  bridge.on("error", error => {
    vscode.window.showErrorMessage(`Cortex bridge error: ${error.message}`);
    bridge = undefined;
  });

  bridge.listen(port, "127.0.0.1", () => {
    vscode.window.showInformationMessage(`Cortex VS Code bridge listening on 127.0.0.1:${port}`);
  });
}

function stopBridge() {
  if (bridge) {
    bridge.close();
    bridge = undefined;
  }
}

async function handleLine(line: string): Promise<RpcResponse> {
  let request: RpcRequest;
  try {
    request = JSON.parse(line) as RpcRequest;
  } catch (error) {
    return fail("invalid-request", String(error));
  }

  if (request.protocol_version !== PROTOCOL_VERSION) {
    return fail(request.id, "Unsupported Cortex protocol version.");
  }

  const token = readProjectToken();
  if (!token || request.auth_token !== token) {
    return fail(request.id, "Cortex bridge authentication failed.");
  }

  try {
    const result = await dispatch(request.method, request.params ?? {});
    return ok(request.id, result);
  } catch (error) {
    return fail(request.id, error instanceof Error ? error.message : String(error));
  }
}

async function dispatch(method: string, params: any): Promise<any> {
  switch (method) {
    case "vscode.workspace_info":
      return workspaceInfo();

    case "vscode.open_file": {
      const uri = safeWorkspaceUri(String(params.path ?? ""));
      const doc = await vscode.workspace.openTextDocument(uri);
      const editor = await vscode.window.showTextDocument(doc);
      const line = Math.max(0, Number(params.line ?? 1) - 1);
      const character = Math.max(0, Number(params.character ?? 1) - 1);
      const position = new vscode.Position(line, character);
      editor.selection = new vscode.Selection(position, position);
      editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenterIfOutsideViewport);
      return { uri: uri.toString(), line: line + 1, character: character + 1 };
    }

    case "vscode.get_diagnostics": {
      const rows: any[] = [];
      for (const [uri, diagnostics] of vscode.languages.getDiagnostics()) {
        if (!isWorkspaceUri(uri)) continue;
        for (const diagnostic of diagnostics) {
          rows.push({
            uri: uri.toString(),
            severity: vscode.DiagnosticSeverity[diagnostic.severity].toLowerCase(),
            source: diagnostic.source ?? null,
            code: diagnostic.code ?? null,
            message: diagnostic.message,
            range: {
              start: { line: diagnostic.range.start.line, character: diagnostic.range.start.character },
              end: { line: diagnostic.range.end.line, character: diagnostic.range.end.character }
            }
          });
        }
      }
      return { diagnostics: rows };
    }

    case "vscode.apply_workspace_edit": {
      if (!Array.isArray(params.edits)) throw new Error("edits must be an array");
      const edit = new vscode.WorkspaceEdit();
      for (const item of params.edits) {
        const uri = safeWorkspaceUri(String(item.path ?? ""));
        const start = new vscode.Position(Number(item.start?.line ?? 0), Number(item.start?.character ?? 0));
        const end = new vscode.Position(Number(item.end?.line ?? start.line), Number(item.end?.character ?? start.character));
        edit.replace(uri, new vscode.Range(start, end), String(item.new_text ?? ""));
      }
      const applied = await vscode.workspace.applyEdit(edit);
      return { applied };
    }

    case "vscode.save_all": {
      const saved = await vscode.workspace.saveAll(false);
      return { saved };
    }

    case "vscode.execute_command": {
      const command = String(params.command ?? "");
      if (!command.startsWith("open2d") && !command.startsWith("workbench.action.files.")) {
        throw new Error(`VS Code command not permitted by bridge policy: ${command}`);
      }
      const result = await vscode.commands.executeCommand(command, ...(Array.isArray(params.args) ? params.args : []));
      return { result: result ?? null };
    }

    default:
      throw new Error(`Unknown VS Code bridge method: ${method}`);
  }
}

function workspaceInfo() {
  const editor = vscode.window.activeTextEditor;
  return {
    folders: (vscode.workspace.workspaceFolders ?? []).map(folder => ({
      name: folder.name,
      uri: folder.uri.toString()
    })),
    active_file: editor?.document.uri.toString() ?? null,
    selection: editor ? {
      start: { line: editor.selection.start.line, character: editor.selection.start.character },
      end: { line: editor.selection.end.line, character: editor.selection.end.character },
      text: editor.document.getText(editor.selection)
    } : null,
    visible_editors: vscode.window.visibleTextEditors.map(item => item.document.uri.toString())
  };
}

function safeWorkspaceUri(relativePath: string): vscode.Uri {
  if (!relativePath || path.isAbsolute(relativePath) || relativePath.split(/[\\/]+/).includes("..")) {
    throw new Error(`Unsafe project-relative path: ${relativePath}`);
  }
  const folder = vscode.workspace.workspaceFolders?.[0];
  if (!folder) throw new Error("No VS Code workspace folder is open.");
  return vscode.Uri.joinPath(folder.uri, ...relativePath.split(/[\\/]+/));
}

function isWorkspaceUri(uri: vscode.Uri): boolean {
  return (vscode.workspace.workspaceFolders ?? []).some(folder => {
    const rel = path.relative(folder.uri.fsPath, uri.fsPath);
    return rel !== "" && !rel.startsWith("..") && !path.isAbsolute(rel);
  });
}

async function askAboutSelection() {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showWarningMessage("Open a source file before asking Cortex about a selection.");
    return;
  }

  const selected = editor.document.getText(editor.selection);
  const prompt = selected
    ? `Inspect this selected project code and explain any actionable issues:\n\n${selected}`
    : `Inspect the active project source file ${editor.document.uri.fsPath}.`;

  const port = vscode.workspace.getConfiguration("cortex").get<number>("cortexPort", 7337);
  const token = readProjectToken();
  if (!token) {
    vscode.window.showErrorMessage("Cortex RPC token is unavailable. Start Cortex for this project first.");
    return;
  }

  const response = await callCortex(port, {
    protocol_version: PROTOCOL_VERSION,
    id: `vscode-${Date.now()}`,
    method: "agent.ask",
    params: { prompt },
    auth_token: token
  });

  if (response.ok) {
    const text = String(response.result?.text ?? response.result ?? "");
    const document = await vscode.workspace.openTextDocument({ language: "markdown", content: text });
    await vscode.window.showTextDocument(document, { preview: true });
  } else {
    vscode.window.showErrorMessage(`Cortex: ${response.error ?? "request failed"}`);
  }
}

function callCortex(port: number, request: RpcRequest): Promise<RpcResponse> {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection({ host: "127.0.0.1", port }, () => {
      socket.write(JSON.stringify(request) + "\n");
    });
    let buffer = "";
    socket.setEncoding("utf8");
    socket.on("data", chunk => {
      buffer += chunk;
      const newline = buffer.indexOf("\n");
      if (newline >= 0) {
        const line = buffer.slice(0, newline).trim();
        socket.end();
        try {
          resolve(JSON.parse(line) as RpcResponse);
        } catch (error) {
          reject(error);
        }
      }
    });
    socket.on("error", reject);
  });
}

function readProjectToken(): string | undefined {
  const folder = vscode.workspace.workspaceFolders?.[0];
  if (!folder) return undefined;
  const tokenPath = path.join(folder.uri.fsPath, ".open2d", "cortex", "rpc.token");
  try {
    const token = fs.readFileSync(tokenPath, "utf8").trim();
    return token.length >= 24 ? token : undefined;
  } catch {
    return undefined;
  }
}

function isLoopback(address: string): boolean {
  return address === "127.0.0.1" || address === "::1" || address === "::ffff:127.0.0.1";
}

function ok(id: string, result: any): RpcResponse {
  return { protocol_version: PROTOCOL_VERSION, id, ok: true, result };
}

function fail(id: string, error: string): RpcResponse {
  return { protocol_version: PROTOCOL_VERSION, id, ok: false, result: null, error };
}
