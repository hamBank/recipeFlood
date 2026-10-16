//! The desktop half of browser sign-in (SPEC.md "Desktop app sign-in").
//!
//! The app opens the website's /desktop-login page in the user's browser and
//! listens on a loopback port for the browser to be sent back with a
//! single-use code. This file only collects that code: trading it for a token
//! is an ordinary API call, so the frontend does it (api.js). The code is a
//! credential for the next two minutes, so nothing here logs it, and it is
//! never put in an error message.

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::time::{Duration, Instant};

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use serde::Serialize;
use subtle::ConstantTimeEq;
use tauri_plugin_opener::OpenerExt;
use url::form_urlencoded;

const LOGIN_TIMEOUT: Duration = Duration::from_secs(5 * 60);
// How long to wait for the browser to follow the redirect to /done once the
// code is in hand. The login has succeeded either way, so this only decides
// whether the user sees the confirmation page.
const DONE_GRACE: Duration = Duration::from_secs(5);
// A browser can open a connection and send nothing (speculative preconnect);
// don't let one of those hold up the real request behind it.
const READ_TIMEOUT: Duration = Duration::from_secs(1);
const POLL_INTERVAL: Duration = Duration::from_millis(25);
const MAX_REQUEST_BYTES: usize = 8 * 1024;

const DONE_PAGE: &str = "<!doctype html><html><head><meta charset=\"utf-8\">\
<title>Recipe Flood</title></head><body style=\"font-family:sans-serif;\
text-align:center;margin-top:20vh\"><h1>Signed in to Recipe Flood</h1>\
<p>You can close this tab.</p></body></html>";

#[derive(Debug, PartialEq)]
pub enum CallbackOutcome {
    Code(String),
    WrongState,
    NotCallback,
}

#[derive(Serialize)]
pub struct Callback {
    code: String,
    state: String,
}

/// Same rule as platform.js `setServerUrl`: https anywhere, or plain http
/// only for a local development server. Returns it without a trailing `/`.
pub fn validate_server_url(raw: &str) -> Result<String, String> {
    let url = raw.trim().trim_end_matches('/');
    let ok = match url.strip_prefix("https://") {
        Some(host) => !host.is_empty() && !host.contains(|c: char| c == '/' || c.is_whitespace()),
        None => url
            .strip_prefix("http://localhost")
            .or_else(|| url.strip_prefix("http://127.0.0.1"))
            .is_some_and(|rest| {
                rest.is_empty()
                    || rest
                        .strip_prefix(':')
                        .is_some_and(|port| !port.is_empty() && port.bytes().all(|b| b.is_ascii_digit()))
            }),
    };
    if ok {
        Ok(url.to_string())
    } else {
        Err("Server address must start with https:// (or http://localhost for development)".into())
    }
}

/// 32 random bytes as base64url, 43 characters — inside the backend's
/// `^[A-Za-z0-9_-]{32,128}$`.
pub fn new_state() -> Result<String, String> {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).map_err(|_| "Could not generate a sign-in state".to_string())?;
    Ok(URL_SAFE_NO_PAD.encode(bytes))
}

pub fn login_url(server: &str, port: u16, state: &str) -> String {
    let query = form_urlencoded::Serializer::new(String::new())
        .append_pair("port", &port.to_string())
        .append_pair("state", state)
        .finish();
    format!("{server}/desktop-login?{query}")
}

pub fn parse_callback(path_and_query: &str, expected_state: &str) -> CallbackOutcome {
    let (path, query) = path_and_query.split_once('?').unwrap_or((path_and_query, ""));
    if path != "/callback" {
        return CallbackOutcome::NotCallback;
    }
    let mut code = None;
    let mut state = None;
    for (key, value) in form_urlencoded::parse(query.as_bytes()) {
        match key.as_ref() {
            "code" => code = Some(value.into_owned()),
            "state" => state = Some(value.into_owned()),
            _ => {}
        }
    }
    // Constant-time, so a local process can't learn the state a byte at a
    // time from how fast the app answers.
    let state_ok = state.is_some_and(|s| s.as_bytes().ct_eq(expected_state.as_bytes()).into());
    match code {
        Some(code) if state_ok && !code.is_empty() => CallbackOutcome::Code(code),
        _ => CallbackOutcome::WrongState,
    }
}

fn respond(stream: &mut TcpStream, status: &str, headers: &[(&str, &str)], body: &str) {
    let mut head = format!(
        "HTTP/1.1 {status}\r\nContent-Length: {}\r\nConnection: close\r\n\
         Cache-Control: no-store\r\nReferrer-Policy: no-referrer\r\n",
        body.len()
    );
    for (name, value) in headers {
        head.push_str(&format!("{name}: {value}\r\n"));
    }
    head.push_str("\r\n");
    // The browser may have gone away; there is nothing useful to do then.
    let _ = stream.write_all(head.as_bytes());
    let _ = stream.write_all(body.as_bytes());
    let _ = stream.flush();
}

/// The request target of a GET, or None for anything else / garbage.
fn read_request_target(stream: &mut TcpStream) -> Option<String> {
    stream.set_nonblocking(false).ok()?;
    stream.set_read_timeout(Some(READ_TIMEOUT)).ok()?;
    let mut buf = Vec::new();
    let mut chunk = [0u8; 1024];
    while !buf.windows(2).any(|w| w == b"\r\n") && buf.len() < MAX_REQUEST_BYTES {
        match stream.read(&mut chunk) {
            Ok(0) | Err(_) => break,
            Ok(n) => buf.extend_from_slice(&chunk[..n]),
        }
    }
    let line = String::from_utf8_lossy(&buf);
    let mut parts = line.lines().next()?.split(' ');
    match (parts.next(), parts.next()) {
        (Some("GET"), Some(target)) => Some(target.to_string()),
        _ => None,
    }
}

/// Serve the listener until the browser comes back with the right state
/// (returns its code) or `deadline` passes.
pub fn wait_for_callback(
    listener: &TcpListener,
    expected_state: &str,
    deadline: Instant,
) -> Result<String, String> {
    listener.set_nonblocking(true).map_err(|e| e.to_string())?;
    let mut code: Option<String> = None;
    let mut done_until = deadline;
    loop {
        let now = Instant::now();
        if now >= done_until {
            return code.ok_or_else(|| "Timed out waiting for sign-in".to_string());
        }
        let mut stream = match listener.accept() {
            Ok((stream, _)) => stream,
            Err(_) => {
                std::thread::sleep(POLL_INTERVAL);
                continue;
            }
        };
        let Some(target) = read_request_target(&mut stream) else {
            respond(&mut stream, "400 Bad Request", &[], "Bad request");
            continue;
        };
        if code.is_some() {
            // Past the callback: all that's left is the confirmation page.
            if target == "/done" {
                respond(&mut stream, "200 OK", &[("Content-Type", "text/html; charset=utf-8")], DONE_PAGE);
                return Ok(code.unwrap());
            }
            respond(&mut stream, "404 Not Found", &[], "Not found");
            continue;
        }
        match parse_callback(&target, expected_state) {
            CallbackOutcome::Code(found) => {
                // Redirect so the code doesn't stay in the address bar.
                respond(&mut stream, "303 See Other", &[("Location", "/done")], "");
                code = Some(found);
                done_until = deadline.min(Instant::now() + DONE_GRACE);
            }
            CallbackOutcome::WrongState => {
                respond(&mut stream, "400 Bad Request", &[], "Invalid sign-in request");
            }
            CallbackOutcome::NotCallback => {
                respond(&mut stream, "404 Not Found", &[], "Not found");
            }
        }
    }
}

#[tauri::command]
pub async fn start_login(app: tauri::AppHandle, server_url: String) -> Result<Callback, String> {
    let server = validate_server_url(&server_url)?;
    // 127.0.0.1 only, never 0.0.0.0: nothing else on the network may reach it.
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|e| e.to_string())?;
    let port = listener.local_addr().map_err(|e| e.to_string())?.port();
    let state = new_state()?;

    app.opener()
        .open_url(login_url(&server, port, &state), None::<&str>)
        .map_err(|_| "Could not open your browser".to_string())?;

    let expected = state.clone();
    let deadline = Instant::now() + LOGIN_TIMEOUT;
    let code = tauri::async_runtime::spawn_blocking(move || {
        wait_for_callback(&listener, &expected, deadline)
    })
    .await
    .map_err(|_| "Sign-in was interrupted".to_string())??;
    Ok(Callback { code, state })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn server_url_accepts_https_and_local_http() {
        for (input, want) in [
            ("https://recipeflood.hups.club", "https://recipeflood.hups.club"),
            ("https://recipeflood.hups.club/", "https://recipeflood.hups.club"),
            ("  https://example.com:8443//  ", "https://example.com:8443"),
            ("http://localhost", "http://localhost"),
            ("http://localhost:8000/", "http://localhost:8000"),
            ("http://127.0.0.1:5173", "http://127.0.0.1:5173"),
        ] {
            assert_eq!(validate_server_url(input).as_deref(), Ok(want), "{input}");
        }
    }

    #[test]
    fn server_url_rejects_everything_else() {
        for input in [
            "",
            "https://",
            "http://example.com",
            "ftp://example.com",
            "example.com",
            "https://example.com/path",
            "https://exa mple.com",
            "http://localhost:",
            "http://localhost:80a",
            "http://localhost.evil.com",
            "http://127.0.0.1.evil.com",
            "http://localhost/path",
        ] {
            assert!(validate_server_url(input).is_err(), "{input}");
        }
    }

    #[test]
    fn state_is_43_urlsafe_chars_and_differs_each_time() {
        let a = new_state().unwrap();
        let b = new_state().unwrap();
        assert_eq!(a.len(), 43);
        assert!(a.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_'));
        assert_ne!(a, b);
    }

    #[test]
    fn login_url_carries_port_and_encoded_state() {
        assert_eq!(
            login_url("https://x.example", 5555, "abc-_"),
            "https://x.example/desktop-login?port=5555&state=abc-_"
        );
        assert_eq!(
            login_url("http://localhost:8000", 40000, "a b&c"),
            "http://localhost:8000/desktop-login?port=40000&state=a+b%26c"
        );
    }

    #[test]
    fn callback_with_right_state_yields_the_code() {
        assert_eq!(
            parse_callback("/callback?code=c0de%2B&state=s3", "s3"),
            CallbackOutcome::Code("c0de+".into())
        );
    }

    #[test]
    fn callback_with_wrong_or_missing_pieces_is_rejected() {
        assert_eq!(parse_callback("/callback?code=c&state=other", "s3"), CallbackOutcome::WrongState);
        assert_eq!(parse_callback("/callback?code=c", "s3"), CallbackOutcome::WrongState);
        assert_eq!(parse_callback("/callback?state=s3", "s3"), CallbackOutcome::WrongState);
        assert_eq!(parse_callback("/callback?code=&state=s3", "s3"), CallbackOutcome::WrongState);
        assert_eq!(parse_callback("/callback", "s3"), CallbackOutcome::WrongState);
    }

    #[test]
    fn other_paths_are_not_callbacks() {
        assert_eq!(parse_callback("/favicon.ico", "s3"), CallbackOutcome::NotCallback);
        assert_eq!(parse_callback("/done?code=c&state=s3", "s3"), CallbackOutcome::NotCallback);
        assert_eq!(parse_callback("/callback/x?code=c&state=s3", "s3"), CallbackOutcome::NotCallback);
    }

    fn listener() -> (TcpListener, u16) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        (listener, port)
    }

    fn get(port: u16, target: &str) -> String {
        let mut stream = TcpStream::connect(("127.0.0.1", port)).unwrap();
        write!(stream, "GET {target} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n").unwrap();
        let mut out = String::new();
        stream.read_to_string(&mut out).unwrap();
        out
    }

    #[test]
    fn serves_the_callback_then_the_done_page_and_returns_the_code() {
        let (listener, port) = listener();
        let waiter = std::thread::spawn(move || {
            wait_for_callback(&listener, "s3", Instant::now() + Duration::from_secs(10))
        });

        let redirect = get(port, "/callback?code=abc&state=s3");
        assert!(redirect.starts_with("HTTP/1.1 303"), "{redirect}");
        assert!(redirect.contains("Location: /done"), "{redirect}");
        assert!(!redirect.contains("abc"));

        let done = get(port, "/done");
        assert!(done.starts_with("HTTP/1.1 200"), "{done}");
        assert!(done.contains("text/html"));
        assert!(done.contains("You can close this tab."));

        assert_eq!(waiter.join().unwrap(), Ok("abc".to_string()));
    }

    #[test]
    fn a_wrong_state_gets_400_and_the_wait_continues() {
        let (listener, port) = listener();
        let waiter = std::thread::spawn(move || {
            wait_for_callback(&listener, "s3", Instant::now() + Duration::from_secs(10))
        });

        assert!(get(port, "/callback?code=evil&state=nope").starts_with("HTTP/1.1 400"));
        assert!(get(port, "/favicon.ico").starts_with("HTTP/1.1 404"));
        // Still waiting, and a good callback after the bad one still works.
        assert!(get(port, "/callback?code=good&state=s3").starts_with("HTTP/1.1 303"));
        get(port, "/done");
        assert_eq!(waiter.join().unwrap(), Ok("good".to_string()));
    }

    #[test]
    fn gives_up_at_the_deadline() {
        let (listener, _port) = listener();
        let result = wait_for_callback(&listener, "s3", Instant::now() + Duration::from_millis(200));
        assert_eq!(result, Err("Timed out waiting for sign-in".to_string()));
    }

    #[test]
    fn returns_the_code_even_if_the_browser_never_asks_for_done() {
        let (listener, port) = listener();
        let waiter = std::thread::spawn(move || {
            // Deadline shorter than the done grace: the code must survive it.
            wait_for_callback(&listener, "s3", Instant::now() + Duration::from_millis(500))
        });
        get(port, "/callback?code=abc&state=s3");
        assert_eq!(waiter.join().unwrap(), Ok("abc".to_string()));
    }
}
