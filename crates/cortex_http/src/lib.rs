//! Tiny project-agnostic loopback-only HTTP/1.1 client used by local Cortex providers.
//!
//! This transport intentionally supports only unencrypted loopback HTTP endpoints;
//! external network/provider transports remain separate policy-controlled concerns.

use serde_json::Value;
use std::collections::BTreeMap;
use std::io::{BufRead, BufReader, ErrorKind, Read, Write};
use std::net::{IpAddr, TcpStream, ToSocketAddrs};
use std::time::Duration;

#[derive(Clone, Debug)]
pub struct HttpClient {
    connect_timeout: Duration,
    io_timeout: Option<Duration>,
}

impl Default for HttpClient {
    fn default() -> Self {
        Self {
            connect_timeout: Duration::from_secs(5),
            io_timeout: Some(Duration::from_secs(600)),
        }
    }
}

impl HttpClient {
    pub fn with_timeout(timeout: Duration) -> Self {
        Self {
            connect_timeout: Duration::from_secs(5),
            io_timeout: Some(timeout),
        }
    }

    pub fn with_timeouts(connect_timeout: Duration, io_timeout: Duration) -> Self {
        Self {
            connect_timeout,
            io_timeout: Some(io_timeout),
        }
    }

    pub fn without_io_timeout() -> Self {
        Self {
            connect_timeout: Duration::from_secs(5),
            io_timeout: None,
        }
    }

    pub fn io_timeout(&self) -> Option<Duration> {
        self.io_timeout
    }

    pub fn get(&self, url: &str) -> Result<HttpResponse, HttpError> {
        self.request("GET", url, &[], &[])
    }

    pub fn post_json(&self, url: &str, value: &Value) -> Result<HttpResponse, HttpError> {
        let body = serde_json::to_vec(value).map_err(|error| HttpError(error.to_string()))?;
        self.request("POST", url, &[("Content-Type", "application/json")], &body)
    }

    pub fn post_json_stream(
        &self,
        url: &str,
        value: &Value,
        on_chunk: &mut dyn FnMut(&[u8]) -> Result<(), HttpError>,
    ) -> Result<(), HttpError> {
        let body = serde_json::to_vec(value).map_err(|error| HttpError(error.to_string()))?;
        self.request_stream(
            "POST",
            url,
            &[
                ("Content-Type", "application/json"),
                ("Accept", "text/event-stream"),
            ],
            &body,
            on_chunk,
        )
    }

    pub fn request_stream(
        &self,
        method: &str,
        url: &str,
        headers: &[(&str, &str)],
        body: &[u8],
        on_chunk: &mut dyn FnMut(&[u8]) -> Result<(), HttpError>,
    ) -> Result<(), HttpError> {
        let parsed = ParsedUrl::parse(url)?;
        parsed.require_loopback()?;
        let address = format!("{}:{}", parsed.host, parsed.port);
        let socket = address
            .to_socket_addrs()
            .map_err(|error| HttpError(error.to_string()))?
            .find(|addr| addr.ip().is_loopback())
            .ok_or_else(|| HttpError("provider endpoint did not resolve to loopback".into()))?;

        let mut stream = TcpStream::connect_timeout(&socket, self.connect_timeout)
            .map_err(|error| HttpError(format!("connect failed: {error}")))?;
        stream
            .set_read_timeout(self.io_timeout)
            .map_err(|error| HttpError(error.to_string()))?;
        stream
            .set_write_timeout(self.io_timeout)
            .map_err(|error| HttpError(error.to_string()))?;

        let mut request = format!(
            "{method} {} HTTP/1.1\r\nHost: {}:{}\r\nConnection: close\r\nContent-Length: {}\r\n",
            parsed.path_and_query,
            parsed.host,
            parsed.port,
            body.len()
        );
        for (name, value) in headers {
            request.push_str(name);
            request.push_str(": ");
            request.push_str(value);
            request.push_str("\r\n");
        }
        request.push_str("\r\n");
        stream
            .write_all(request.as_bytes())
            .map_err(|error| HttpError(error.to_string()))?;
        if !body.is_empty() {
            stream
                .write_all(body)
                .map_err(|error| HttpError(error.to_string()))?;
        }
        stream
            .flush()
            .map_err(|error| HttpError(error.to_string()))?;

        let mut reader = BufReader::new(stream);
        let mut status_line = String::new();
        reader
            .read_line(&mut status_line)
            .map_err(|error| HttpError(error.to_string()))?;
        let status = status_line
            .split_whitespace()
            .nth(1)
            .ok_or_else(|| HttpError("missing HTTP status code".into()))?
            .parse::<u16>()
            .map_err(|error| HttpError(error.to_string()))?;
        let mut response_headers = BTreeMap::new();
        loop {
            let mut line = String::new();
            reader
                .read_line(&mut line)
                .map_err(|error| HttpError(error.to_string()))?;
            if line == "\r\n" || line.is_empty() {
                break;
            }
            if let Some((name, value)) = line.split_once(':') {
                response_headers.insert(name.trim().to_ascii_lowercase(), value.trim().to_string());
            }
        }

        if !(200..300).contains(&status) {
            let mut body = Vec::new();
            reader
                .read_to_end(&mut body)
                .map_err(|error| HttpError(error.to_string()))?;
            return Err(HttpError(format!(
                "HTTP {status}: {}",
                String::from_utf8_lossy(&body)
            )));
        }

        let chunked = response_headers
            .get("transfer-encoding")
            .map(|value| value.to_ascii_lowercase().contains("chunked"))
            .unwrap_or(false);
        if chunked {
            stream_chunked_body(&mut reader, on_chunk)
        } else if let Some(length) = response_headers
            .get("content-length")
            .and_then(|value| value.parse::<usize>().ok())
        {
            stream_sized_body(&mut reader, length, on_chunk)
        } else {
            stream_until_eof(&mut reader, on_chunk)
        }
    }

    pub fn request(
        &self,
        method: &str,
        url: &str,
        headers: &[(&str, &str)],
        body: &[u8],
    ) -> Result<HttpResponse, HttpError> {
        let parsed = ParsedUrl::parse(url)?;
        parsed.require_loopback()?;
        let address = format!("{}:{}", parsed.host, parsed.port);
        let socket = address
            .to_socket_addrs()
            .map_err(|error| HttpError(error.to_string()))?
            .find(|addr| addr.ip().is_loopback())
            .ok_or_else(|| HttpError("provider endpoint did not resolve to loopback".into()))?;

        let mut stream = TcpStream::connect_timeout(&socket, self.connect_timeout)
            .map_err(|error| HttpError(format!("connect failed: {error}")))?;
        stream
            .set_read_timeout(self.io_timeout)
            .map_err(|error| HttpError(error.to_string()))?;
        stream
            .set_write_timeout(self.io_timeout)
            .map_err(|error| HttpError(error.to_string()))?;

        let mut request = format!(
            "{method} {} HTTP/1.1\r\nHost: {}:{}\r\nConnection: close\r\nContent-Length: {}\r\n",
            parsed.path_and_query,
            parsed.host,
            parsed.port,
            body.len()
        );
        for (name, value) in headers {
            request.push_str(name);
            request.push_str(": ");
            request.push_str(value);
            request.push_str("\r\n");
        }
        request.push_str("\r\n");

        stream
            .write_all(request.as_bytes())
            .map_err(|error| HttpError(error.to_string()))?;
        if !body.is_empty() {
            stream
                .write_all(body)
                .map_err(|error| HttpError(error.to_string()))?;
        }
        stream
            .flush()
            .map_err(|error| HttpError(error.to_string()))?;

        let bytes = read_http_response(&mut stream, self.io_timeout)?;
        HttpResponse::parse(&bytes)
    }
}

fn stream_chunked_body(
    reader: &mut BufReader<TcpStream>,
    on_chunk: &mut dyn FnMut(&[u8]) -> Result<(), HttpError>,
) -> Result<(), HttpError> {
    loop {
        let mut size_line = String::new();
        reader
            .read_line(&mut size_line)
            .map_err(|error| HttpError(error.to_string()))?;
        if size_line.is_empty() {
            return Err(HttpError("chunked stream ended before zero chunk".into()));
        }
        let size_text = size_line.split(';').next().unwrap_or(&size_line).trim();
        let size =
            usize::from_str_radix(size_text, 16).map_err(|error| HttpError(error.to_string()))?;
        if size == 0 {
            loop {
                let mut trailer = String::new();
                reader
                    .read_line(&mut trailer)
                    .map_err(|error| HttpError(error.to_string()))?;
                if trailer == "\r\n" || trailer.is_empty() {
                    break;
                }
            }
            return Ok(());
        }
        let mut chunk = vec![0u8; size];
        reader
            .read_exact(&mut chunk)
            .map_err(|error| HttpError(error.to_string()))?;
        let mut terminator = [0u8; 2];
        reader
            .read_exact(&mut terminator)
            .map_err(|error| HttpError(error.to_string()))?;
        if terminator != *b"\r\n" {
            return Err(HttpError("chunk terminator missing".into()));
        }
        on_chunk(&chunk)?;
    }
}

fn stream_sized_body(
    reader: &mut BufReader<TcpStream>,
    mut remaining: usize,
    on_chunk: &mut dyn FnMut(&[u8]) -> Result<(), HttpError>,
) -> Result<(), HttpError> {
    let mut buffer = [0u8; 16 * 1024];
    while remaining > 0 {
        let wanted = remaining.min(buffer.len());
        let count = reader
            .read(&mut buffer[..wanted])
            .map_err(|error| HttpError(error.to_string()))?;
        if count == 0 {
            return Err(HttpError(
                "stream ended before Content-Length bytes arrived".into(),
            ));
        }
        on_chunk(&buffer[..count])?;
        remaining -= count;
    }
    Ok(())
}

fn stream_until_eof(
    reader: &mut BufReader<TcpStream>,
    on_chunk: &mut dyn FnMut(&[u8]) -> Result<(), HttpError>,
) -> Result<(), HttpError> {
    let mut buffer = [0u8; 16 * 1024];
    loop {
        let count = reader
            .read(&mut buffer)
            .map_err(|error| HttpError(error.to_string()))?;
        if count == 0 {
            return Ok(());
        }
        on_chunk(&buffer[..count])?;
    }
}

fn read_http_response(
    stream: &mut TcpStream,
    timeout: Option<Duration>,
) -> Result<Vec<u8>, HttpError> {
    let mut bytes = Vec::new();
    let mut buffer = [0u8; 16 * 1024];

    loop {
        match stream.read(&mut buffer) {
            Ok(0) => break,
            Ok(count) => {
                bytes.extend_from_slice(&buffer[..count]);

                if let Some(header_end) = find_bytes(&bytes, b"\r\n\r\n") {
                    let body_start = header_end + 4;
                    let header_text = std::str::from_utf8(&bytes[..header_end])
                        .map_err(|error| HttpError(error.to_string()))?;
                    let headers = parse_header_map(header_text);

                    if let Some(content_length) = headers
                        .get("content-length")
                        .and_then(|value| value.parse::<usize>().ok())
                    {
                        let expected = body_start.saturating_add(content_length);
                        if bytes.len() >= expected {
                            bytes.truncate(expected);
                            return Ok(bytes);
                        }
                    }

                    if headers
                        .get("transfer-encoding")
                        .map(|value| value.to_ascii_lowercase().contains("chunked"))
                        .unwrap_or(false)
                        && chunked_body_complete(&bytes[body_start..])?
                    {
                        return Ok(bytes);
                    }
                }
            }
            Err(error) if matches!(error.kind(), ErrorKind::TimedOut | ErrorKind::WouldBlock) => {
                let detail = timeout
                    .map(|value| format!(" after {} seconds", value.as_secs()))
                    .unwrap_or_default();
                return Err(HttpError(format!(
                    "provider response timed out{detail} (received {} bytes)",
                    bytes.len()
                )));
            }
            Err(error) => return Err(HttpError(error.to_string())),
        }
    }

    if bytes.is_empty() {
        Err(HttpError(
            "provider closed the connection without an HTTP response".into(),
        ))
    } else {
        Ok(bytes)
    }
}

fn parse_header_map(header_text: &str) -> BTreeMap<String, String> {
    let mut headers = BTreeMap::new();
    for line in header_text.split("\r\n").skip(1) {
        if let Some((name, value)) = line.split_once(':') {
            headers.insert(name.trim().to_ascii_lowercase(), value.trim().to_string());
        }
    }
    headers
}

fn chunked_body_complete(input: &[u8]) -> Result<bool, HttpError> {
    let mut cursor = 0usize;

    loop {
        let Some(line_end_rel) = find_bytes(&input[cursor..], b"\r\n") else {
            return Ok(false);
        };
        let line_end = cursor + line_end_rel;
        let size_text =
            std::str::from_utf8(&input[cursor..line_end]).map_err(|e| HttpError(e.to_string()))?;
        let size_text = size_text.split(';').next().unwrap_or(size_text).trim();
        let size = usize::from_str_radix(size_text, 16).map_err(|e| HttpError(e.to_string()))?;
        cursor = line_end + 2;

        if size == 0 {
            if input.get(cursor..cursor + 2) == Some(&b"\r\n"[..]) {
                return Ok(true);
            }
            return Ok(find_bytes(&input[cursor..], b"\r\n\r\n").is_some());
        }

        if cursor + size + 2 > input.len() {
            return Ok(false);
        }
        cursor += size;
        if input.get(cursor..cursor + 2) != Some(&b"\r\n"[..]) {
            return Err(HttpError("chunk terminator missing".into()));
        }
        cursor += 2;
    }
}

#[derive(Clone, Debug)]
pub struct HttpResponse {
    pub status: u16,
    pub headers: BTreeMap<String, String>,
    pub body: Vec<u8>,
}

impl HttpResponse {
    fn parse(raw: &[u8]) -> Result<Self, HttpError> {
        let split = find_bytes(raw, b"\r\n\r\n")
            .ok_or_else(|| HttpError("invalid HTTP response".into()))?;
        let header_bytes = &raw[..split];
        let mut body = raw[split + 4..].to_vec();
        let header_text =
            std::str::from_utf8(header_bytes).map_err(|error| HttpError(error.to_string()))?;
        let mut lines = header_text.split("\r\n");
        let status_line = lines
            .next()
            .ok_or_else(|| HttpError("missing HTTP status".into()))?;
        let status = status_line
            .split_whitespace()
            .nth(1)
            .ok_or_else(|| HttpError("missing HTTP status code".into()))?
            .parse::<u16>()
            .map_err(|error| HttpError(error.to_string()))?;
        let headers = parse_header_map(header_text);

        if headers
            .get("transfer-encoding")
            .map(|value| value.to_ascii_lowercase().contains("chunked"))
            .unwrap_or(false)
        {
            body = decode_chunked(&body)?;
        }

        Ok(Self {
            status,
            headers,
            body,
        })
    }

    pub fn ensure_success(self) -> Result<Self, HttpError> {
        if (200..300).contains(&self.status) {
            Ok(self)
        } else {
            let text = String::from_utf8_lossy(&self.body);
            Err(HttpError(format!("HTTP {}: {}", self.status, text)))
        }
    }

    pub fn text(&self) -> Result<String, HttpError> {
        String::from_utf8(self.body.clone()).map_err(|error| HttpError(error.to_string()))
    }

    pub fn json(&self) -> Result<Value, HttpError> {
        serde_json::from_slice(&self.body).map_err(|error| HttpError(error.to_string()))
    }
}

#[derive(Clone, Debug)]
struct ParsedUrl {
    host: String,
    port: u16,
    path_and_query: String,
}

impl ParsedUrl {
    fn parse(value: &str) -> Result<Self, HttpError> {
        let rest = value
            .strip_prefix("http://")
            .ok_or_else(|| HttpError("only http:// loopback URLs are supported".into()))?;
        let (authority, path) = rest
            .split_once('/')
            .map(|(authority, path)| (authority, format!("/{path}")))
            .unwrap_or((rest, "/".into()));
        let (host, port) = if authority.starts_with('[') {
            let end = authority
                .find(']')
                .ok_or_else(|| HttpError("invalid IPv6 URL".into()))?;
            let host = authority[1..end].to_string();
            let port = authority[end + 1..]
                .strip_prefix(':')
                .unwrap_or("80")
                .parse::<u16>()
                .map_err(|error| HttpError(error.to_string()))?;
            (host, port)
        } else if let Some((host, port)) = authority.rsplit_once(':') {
            (
                host.to_string(),
                port.parse::<u16>()
                    .map_err(|error| HttpError(error.to_string()))?,
            )
        } else {
            (authority.to_string(), 80)
        };
        if host.trim().is_empty() {
            return Err(HttpError("URL host is empty".into()));
        }
        Ok(Self {
            host,
            port,
            path_and_query: path,
        })
    }

    fn require_loopback(&self) -> Result<(), HttpError> {
        if self.host.eq_ignore_ascii_case("localhost") {
            return Ok(());
        }
        if let Ok(ip) = self.host.parse::<IpAddr>() {
            if ip.is_loopback() {
                return Ok(());
            }
        }
        Err(HttpError(format!(
            "non-loopback provider endpoint denied: {}",
            self.host
        )))
    }
}

fn find_bytes(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack
        .windows(needle.len())
        .position(|window| window == needle)
}

fn decode_chunked(input: &[u8]) -> Result<Vec<u8>, HttpError> {
    let mut output = Vec::new();
    let mut cursor = 0usize;
    loop {
        let line_end_rel = find_bytes(&input[cursor..], b"\r\n")
            .ok_or_else(|| HttpError("invalid chunked response".into()))?;
        let line_end = cursor + line_end_rel;
        let size_text =
            std::str::from_utf8(&input[cursor..line_end]).map_err(|e| HttpError(e.to_string()))?;
        let size_text = size_text.split(';').next().unwrap_or(size_text).trim();
        let size = usize::from_str_radix(size_text, 16).map_err(|e| HttpError(e.to_string()))?;
        cursor = line_end + 2;
        if size == 0 {
            break;
        }
        if cursor + size > input.len() {
            return Err(HttpError("chunk exceeds response body".into()));
        }
        output.extend_from_slice(&input[cursor..cursor + size]);
        cursor += size;
        if input.get(cursor..cursor + 2) != Some(&b"\r\n"[..]) {
            return Err(HttpError("chunk terminator missing".into()));
        }
        cursor += 2;
    }
    Ok(output)
}

#[derive(Debug, Clone)]
pub struct HttpError(pub String);

impl std::fmt::Display for HttpError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for HttpError {}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;
    use std::thread;
    use std::time::Instant;

    fn read_complete_test_request(stream: &mut TcpStream) {
        let mut request = Vec::new();
        let mut buffer = [0u8; 1024];

        loop {
            let count = stream.read(&mut buffer).unwrap();
            assert!(
                count > 0,
                "test client closed before sending a complete HTTP request"
            );
            request.extend_from_slice(&buffer[..count]);

            let Some(header_end) = find_bytes(&request, b"\r\n\r\n") else {
                continue;
            };
            let header_text = std::str::from_utf8(&request[..header_end]).unwrap();
            let content_length = parse_header_map(header_text)
                .get("content-length")
                .and_then(|value| value.parse::<usize>().ok())
                .unwrap_or(0);
            if request.len() >= header_end + 4 + content_length {
                return;
            }
        }
    }

    #[test]
    fn rejects_non_loopback_urls() {
        assert!(ParsedUrl::parse("http://example.com/api")
            .unwrap()
            .require_loopback()
            .is_err());
    }

    #[test]
    fn decodes_chunked_body() {
        let decoded = decode_chunked(b"4\r\nWiki\r\n5\r\npedia\r\n0\r\n\r\n").unwrap();
        assert_eq!(decoded, b"Wikipedia");
    }

    #[test]
    fn streams_chunked_body_incrementally() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();

        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            read_complete_test_request(&mut stream);
            stream
                .write_all(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\nB\r\ndata: one\n\n\r\nB\r\ndata: two\n\n\r\n0\r\n\r\n",
                )
                .unwrap();
            stream.flush().unwrap();
        });

        let client = HttpClient::with_timeouts(Duration::from_secs(1), Duration::from_secs(1));
        let mut chunks = Vec::<Vec<u8>>::new();
        client
            .post_json_stream(
                &format!("http://127.0.0.1:{}/stream", address.port()),
                &serde_json::json!({"stream": true}),
                &mut |chunk| {
                    chunks.push(chunk.to_vec());
                    Ok(())
                },
            )
            .unwrap();

        assert_eq!(
            chunks,
            vec![b"data: one\n\n".to_vec(), b"data: two\n\n".to_vec()]
        );
        server.join().unwrap();
    }

    #[test]
    fn content_length_does_not_wait_for_connection_close() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();

        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            read_complete_test_request(&mut stream);
            stream
                .write_all(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: keep-alive\r\n\r\n{}",
                )
                .unwrap();
            stream.flush().unwrap();
            thread::sleep(Duration::from_secs(2));
        });

        let client = HttpClient::with_timeouts(Duration::from_secs(1), Duration::from_millis(500));
        let started = Instant::now();
        let response = client
            .get(&format!("http://127.0.0.1:{}/test", address.port()))
            .unwrap();

        assert_eq!(response.body, b"{}");
        assert!(started.elapsed() < Duration::from_secs(1));
        server.join().unwrap();
    }
}
