//! FlowForge's desktop app (D42): the same dashboard, served by FlowForge itself.
//! It picks a free port, starts the bundled server (the sidecar), waits for it, then points the window at it.
//! The server holds this app's pipe on its stdin, so it stops when the app is gone, even after a crash.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

const READY_WITHIN: Duration = Duration::from_secs(120); // a first start unpacks Python, which can take a while

struct Server(Mutex<Option<CommandChild>>);

/// A port nothing is using on this machine's loopback address.
fn free_port() -> std::io::Result<u16> {
    Ok(TcpListener::bind(("127.0.0.1", 0))?.local_addr()?.port())
}

/// What the sidecar is started with: the dashboard on `port`, no browser of its own.
fn server_args(port: u16) -> Vec<String> {
    ["serve", "--no-open", "--port"].iter().map(|s| s.to_string()).chain([port.to_string()]).collect()
}

/// Does FlowForge answer `GET /meta` with 200 on `port`?
fn answers(port: u16) -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_millis(500)) else { return false };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let request = format!("GET /meta HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAccept: application/json\r\nConnection: close\r\n\r\n");
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut head = [0u8; 12];
    stream.read_exact(&mut head).is_ok() && head.starts_with(b"HTTP/1.1 200")
}

fn wait_until_ready(port: u16) -> bool {
    let start = Instant::now();
    while start.elapsed() < READY_WITHIN {
        if answers(port) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    false
}

fn show_failure(app: &tauri::AppHandle, why: &str) {
    if let Some(window) = app.get_webview_window("main") {
        let message = serde_json_string(why);
        let _ = window.eval(&format!("window.flowforgeFailed && window.flowforgeFailed({message})"));
    }
}

/// `text` as a JavaScript string literal.
fn serde_json_string(text: &str) -> String {
    let escaped: String = text
        .chars()
        .flat_map(|c| match c {
            '"' => vec!['\\', '"'],
            '\\' => vec!['\\', '\\'],
            '\n' => vec!['\\', 'n'],
            c if (c as u32) < 0x20 => vec![' '],
            c => vec![c],
        })
        .collect();
    format!("\"{escaped}\"")
}

/// On Linux, WebKitGTK's DMA-BUF renderer leaves the window blank on many NVIDIA setups ("Failed to create GBM
/// buffer"). Draw without it unless the user chose otherwise.
fn linux_webview_workarounds() {
    #[cfg(target_os = "linux")]
    if std::env::var_os("WEBKIT_DISABLE_DMABUF_RENDERER").is_none() {
        std::env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1");
    }
}

fn main() {
    linux_webview_workarounds();
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            // a second launch brings the open window forward instead of starting another server
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let port = free_port()?;
            let (mut events, child) = app
                .shell()
                .sidecar("flowforge-server")?
                .args(server_args(port))
                .env("FLOWFORGE_STOP_ON_EOF", "1")
                .spawn()?;
            app.manage(Server(Mutex::new(Some(child))));

            let handle = app.handle().clone();
            std::thread::spawn(move || {
                if wait_until_ready(port) {
                    if let (Some(window), Ok(url)) =
                        (handle.get_webview_window("main"), format!("http://127.0.0.1:{port}/").parse())
                    {
                        let _ = window.navigate(url);
                    }
                } else {
                    show_failure(&handle, "FlowForge's server didn't start in time.");
                }
            });

            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                while let Some(event) = events.recv().await {
                    match event {
                        CommandEvent::Stderr(line) | CommandEvent::Stdout(line) => {
                            eprintln!("[flowforge-server] {}", String::from_utf8_lossy(&line).trim_end());
                        }
                        CommandEvent::Terminated(status) => {
                            show_failure(&handle, &format!("FlowForge's server stopped (code {:?}).", status.code));
                            break;
                        }
                        _ => {}
                    }
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("FlowForge couldn't start its window")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(child) = app.state::<Server>().0.lock().ok().and_then(|mut c| c.take()) {
                    let _ = child.kill(); // the server also stops by itself once this app's pipe closes
                }
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_free_port_is_on_loopback_and_usable() {
        let port = free_port().unwrap();
        assert!(port > 0);
        assert!(TcpListener::bind(("127.0.0.1", port)).is_ok());
    }

    #[test]
    fn the_server_starts_without_a_browser_on_the_given_port() {
        assert_eq!(server_args(5123), vec!["serve", "--no-open", "--port", "5123"]);
    }

    #[test]
    fn nothing_listening_means_not_ready() {
        assert!(!answers(free_port().unwrap()));
    }

    #[test]
    fn a_failure_message_is_a_safe_js_string() {
        assert_eq!(serde_json_string("a \"b\"\n\\"), "\"a \\\"b\\\"\\n\\\\\"");
    }
}
