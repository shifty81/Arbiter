//! Project-agnostic loopback JSON-lines RPC transport for Cortex services, clients and adapters.

use cortex_protocol::{
    CortexStreamEvent, RpcRequest, RpcResponse, RpcStreamFrame, CORTEX_PROTOCOL_VERSION,
};
use serde_json::Value;
use std::io::{BufRead, BufReader, Write};
use std::net::{IpAddr, SocketAddr, TcpListener, TcpStream};
use std::time::{Duration, Instant};

pub trait RpcHandler {
    fn handle(&mut self, request: RpcRequest) -> RpcResponse;

    fn handle_stream(
        &mut self,
        request: RpcRequest,
        _emit: &mut dyn FnMut(CortexStreamEvent) -> Result<(), String>,
    ) -> RpcResponse {
        self.handle(request)
    }
}

pub struct RpcServer {
    listener: TcpListener,
}

impl RpcServer {
    pub fn bind(address: SocketAddr) -> Result<Self, String> {
        if !address.ip().is_loopback() {
            return Err("Cortex RPC may only bind to loopback".into());
        }
        let listener = TcpListener::bind(address).map_err(|e| e.to_string())?;
        Ok(Self { listener })
    }

    pub fn local_addr(&self) -> Result<SocketAddr, String> {
        self.listener.local_addr().map_err(|e| e.to_string())
    }

    pub fn serve<H: RpcHandler>(&self, handler: &mut H) -> Result<(), String> {
        self.serve_while(handler, || true)
    }

    pub fn serve_while<H, F>(&self, handler: &mut H, mut keep_running: F) -> Result<(), String>
    where
        H: RpcHandler,
        F: FnMut() -> bool,
    {
        self.listener
            .set_nonblocking(true)
            .map_err(|e| e.to_string())?;
        while keep_running() {
            match self.listener.accept() {
                Ok((stream, peer)) => {
                    if peer.ip().is_loopback() {
                        // A client may close/reset its connection immediately after
                        // receiving a response. That is a per-peer transport failure,
                        // not a fatal RPC-listener failure. Keep the service alive for
                        // subsequent Desktop/provider requests.
                        if let Err(error) = handle_stream(stream, handler) {
                            eprintln!("Cortex RPC peer {peer} disconnected: {error}");
                        }
                    }
                }
                Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                    std::thread::sleep(Duration::from_millis(100));
                }
                Err(error) => return Err(error.to_string()),
            }
        }
        Ok(())
    }
}

fn handle_stream<H: RpcHandler>(stream: TcpStream, handler: &mut H) -> Result<(), String> {
    let read = stream.try_clone().map_err(|e| e.to_string())?;
    let mut reader = BufReader::new(read);
    let mut writer = stream;
    loop {
        let mut line = String::new();
        let count = reader.read_line(&mut line).map_err(|e| e.to_string())?;
        if count == 0 {
            break;
        }
        let parsed = serde_json::from_str::<RpcRequest>(line.trim());
        match parsed {
            Ok(request) if request.protocol_version == CORTEX_PROTOCOL_VERSION => {
                if request.method.ends_with(".stream") {
                    let request_id = request.id.clone();
                    let mut emit = |event: CortexStreamEvent| -> Result<(), String> {
                        write_stream_frame(
                            &mut writer,
                            &RpcStreamFrame::event(request_id.clone(), event),
                        )
                    };
                    let response = handler.handle_stream(request, &mut emit);
                    write_stream_frame(
                        &mut writer,
                        &RpcStreamFrame::response(request_id, response),
                    )?;
                } else {
                    let response = handler.handle(request);
                    write_response(&mut writer, &response)?;
                }
            }
            Ok(request) => {
                let response =
                    RpcResponse::error(request.id, "unsupported Cortex protocol version");
                write_response(&mut writer, &response)?;
            }
            Err(error) => {
                let response = RpcResponse::error("invalid-request", error.to_string());
                write_response(&mut writer, &response)?;
            }
        }
    }
    Ok(())
}

fn write_response(writer: &mut TcpStream, response: &RpcResponse) -> Result<(), String> {
    let mut bytes = serde_json::to_vec(response).map_err(|e| e.to_string())?;
    bytes.push(b'\n');
    writer.write_all(&bytes).map_err(|e| e.to_string())?;
    writer.flush().map_err(|e| e.to_string())
}

fn write_stream_frame(writer: &mut TcpStream, frame: &RpcStreamFrame) -> Result<(), String> {
    let mut bytes = serde_json::to_vec(frame).map_err(|e| e.to_string())?;
    bytes.push(b'\n');
    writer.write_all(&bytes).map_err(|e| e.to_string())?;
    writer.flush().map_err(|e| e.to_string())
}

pub fn call(address: SocketAddr, request: &RpcRequest) -> Result<RpcResponse, String> {
    if !address.ip().is_loopback() {
        return Err("Cortex RPC client may only target loopback".into());
    }
    let mut stream =
        TcpStream::connect_timeout(&address, Duration::from_secs(5)).map_err(|e| e.to_string())?;
    let read_timeout =
        stream_timeout_from_env("CORTEX_RPC_READ_TIMEOUT_SECONDS", Duration::from_secs(300));
    stream
        .set_read_timeout(Some(read_timeout))
        .map_err(|e| e.to_string())?;

    let mut bytes = serde_json::to_vec(request).map_err(|e| e.to_string())?;
    bytes.push(b'\n');
    stream.write_all(&bytes).map_err(|e| e.to_string())?;
    stream.flush().map_err(|e| e.to_string())?;
    let mut line = String::new();
    BufReader::new(stream).read_line(&mut line).map_err(|e| {
        if matches!(
            e.kind(),
            std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock
        ) {
            format!(
                "Cortex RPC timed out after {} seconds without a service response",
                read_timeout.as_secs()
            )
        } else {
            e.to_string()
        }
    })?;
    serde_json::from_str(line.trim()).map_err(|e| e.to_string())
}

pub fn call_stream(
    address: SocketAddr,
    request: &RpcRequest,
    on_event: &mut dyn FnMut(CortexStreamEvent),
) -> Result<RpcResponse, String> {
    if !address.ip().is_loopback() {
        return Err("Cortex RPC client may only target loopback".into());
    }
    let mut stream =
        TcpStream::connect_timeout(&address, Duration::from_secs(5)).map_err(|e| e.to_string())?;
    let long_agent_stream = matches!(
        request.method.as_str(),
        "agent.inspect.stream" | "agent.plan.stream" | "agent.apply.stream" | "agent.repair.stream"
    );
    let idle_timeout = stream_timeout_from_env(
        "CORTEX_RPC_STREAM_READ_TIMEOUT_SECONDS",
        if long_agent_stream {
            Duration::from_secs(300)
        } else {
            Duration::from_secs(180)
        },
    );
    let total_timeout = stream_timeout_from_env(
        "CORTEX_RPC_STREAM_TOTAL_TIMEOUT_SECONDS",
        if long_agent_stream {
            Duration::from_secs(3600)
        } else {
            Duration::from_secs(600)
        },
    );
    let started = Instant::now();

    let mut bytes = serde_json::to_vec(request).map_err(|e| e.to_string())?;
    bytes.push(b'\n');
    stream.write_all(&bytes).map_err(|e| e.to_string())?;
    stream.flush().map_err(|e| e.to_string())?;

    let mut reader = BufReader::new(stream);
    loop {
        let elapsed = started.elapsed();
        if elapsed >= total_timeout {
            return Err(format!(
                "Cortex streaming RPC exceeded the total timeout of {} seconds",
                total_timeout.as_secs()
            ));
        }
        let remaining = total_timeout.saturating_sub(elapsed);
        let read_timeout = idle_timeout.min(remaining);
        reader
            .get_mut()
            .set_read_timeout(Some(read_timeout))
            .map_err(|e| e.to_string())?;

        let mut line = String::new();
        let count = reader.read_line(&mut line).map_err(|e| {
            if matches!(
                e.kind(),
                std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock
            ) {
                format!(
                    "Cortex streaming RPC timed out after {} seconds without provider/service output",
                    read_timeout.as_secs()
                )
            } else {
                e.to_string()
            }
        })?;
        if count == 0 {
            return Err("Cortex streaming RPC closed before a final response".into());
        }
        let raw = line.trim();
        if let Ok(frame) = serde_json::from_str::<RpcStreamFrame>(raw) {
            match frame {
                RpcStreamFrame::Event { event, .. } => on_event(event),
                RpcStreamFrame::Response { response, .. } => return Ok(response),
            }
            continue;
        }
        // Pre-streaming Cortex services return a normal RpcResponse here.
        // Preserve that response so callers receive the real compatibility/method
        // error instead of an opaque `missing field frame` serde failure.
        if let Ok(response) = serde_json::from_str::<RpcResponse>(raw) {
            return Ok(response);
        }
        return Err(format!("invalid Cortex streaming RPC frame: {raw}"));
    }
}

fn stream_timeout_from_env(name: &str, default: Duration) -> Duration {
    std::env::var(name)
        .ok()
        .and_then(|value| value.trim().parse::<u64>().ok())
        .filter(|seconds| *seconds > 0)
        .map(|seconds| Duration::from_secs(seconds.clamp(1, 3600)))
        .unwrap_or(default)
}

pub fn default_address(port: u16) -> SocketAddr {
    SocketAddr::new(IpAddr::V4(std::net::Ipv4Addr::LOCALHOST), port)
}

pub fn request(id: impl Into<String>, method: impl Into<String>, params: Value) -> RpcRequest {
    RpcRequest {
        protocol_version: CORTEX_PROTOCOL_VERSION,
        id: id.into(),
        method: method.into(),
        params,
        auth_token: None,
    }
}

pub fn request_with_token(
    id: impl Into<String>,
    method: impl Into<String>,
    params: Value,
    auth_token: impl Into<String>,
) -> RpcRequest {
    RpcRequest {
        protocol_version: CORTEX_PROTOCOL_VERSION,
        id: id.into(),
        method: method.into(),
        params,
        auth_token: Some(auth_token.into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::Shutdown;
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::Arc;

    struct EchoHandler;

    impl RpcHandler for EchoHandler {
        fn handle(&mut self, request: RpcRequest) -> RpcResponse {
            RpcResponse::ok(request.id, serde_json::json!({"ok": true}))
        }
    }

    #[test]
    fn aborted_peer_does_not_terminate_listener() {
        let server = RpcServer::bind(default_address(0)).unwrap();
        let address = server.local_addr().unwrap();
        let running = Arc::new(AtomicBool::new(true));
        let server_running = Arc::clone(&running);
        let thread = std::thread::spawn(move || {
            let mut handler = EchoHandler;
            server
                .serve_while(&mut handler, || server_running.load(Ordering::SeqCst))
                .unwrap();
        });

        let mut aborted = TcpStream::connect(address).unwrap();
        aborted.write_all(b"{not-json}\n").unwrap();
        let _ = aborted.shutdown(Shutdown::Both);
        drop(aborted);
        std::thread::sleep(Duration::from_millis(150));

        let response = call(
            address,
            &request("after-abort", "health", serde_json::json!({})),
        )
        .expect("RPC listener should survive a disconnected peer");
        assert!(response.ok);

        running.store(false, Ordering::SeqCst);
        thread.join().unwrap();
    }
}
