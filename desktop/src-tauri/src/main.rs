// agent-me desktop shell (DESIGN.md §4.3, M4).
//
// The Rust side owns exactly one job: the kernel sidecar's lifecycle. It spawns
// the Python kernel on launch, waits for it to become healthy, then reveals the
// window (whose bundled web UI — the same one the CLI's API serves — talks to the
// kernel over HTTP/WS). On window close it kills the kernel. No agent logic lives
// here; that stays in the kernel ("one kernel, two frontends").
//
// Sidecar packaging decision for M4 (DESIGN.md §8): use system Python and run
// `python -m agent_kernel`. Bundling the interpreter (PyInstaller) is deferred to
// a distribution milestone. Override the command via AGENT_KERNEL_CMD if needed.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;

use tauri::{Manager, WindowEvent};

const KERNEL_HEALTH_URL: &str = "http://127.0.0.1:8765/health";
const HEALTH_ATTEMPTS: u32 = 60;

/// Holds the kernel child process so we can kill it on exit.
struct KernelProcess(Mutex<Option<Child>>);

fn spawn_kernel() -> std::io::Result<Child> {
    // 1) Explicit override wins (e.g. a venv python: "C:\\...\\python.exe -m agent_kernel").
    if let Ok(custom) = std::env::var("AGENT_KERNEL_CMD") {
        let mut parts = custom.split_whitespace();
        let program = parts.next().unwrap_or("python");
        return Command::new(program).args(parts).spawn();
    }
    // 2) A bundled kernel binary next to this executable (the PyInstaller build,
    //    DESIGN.md §8) makes a distributed app self-contained.
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let name = if cfg!(windows) { "agent-kernel.exe" } else { "agent-kernel" };
            let bundled = dir.join(name);
            if bundled.exists() {
                return Command::new(bundled).spawn();
            }
        }
    }
    // 3) Fall back to system Python (the dev default).
    Command::new("python").args(["-m", "agent_kernel"]).spawn()
}

fn wait_for_health() -> bool {
    for _ in 0..HEALTH_ATTEMPTS {
        if ureq::get(KERNEL_HEALTH_URL)
            .timeout(Duration::from_secs(2))
            .call()
            .is_ok()
        {
            return true;
        }
        std::thread::sleep(Duration::from_millis(400));
    }
    false
}

fn main() {
    tauri::Builder::default()
        .manage(KernelProcess(Mutex::new(None)))
        .setup(|app| {
            let child = spawn_kernel().expect("failed to start the agent-me kernel");
            app.state::<KernelProcess>()
                .0
                .lock()
                .unwrap()
                .replace(child);

            // Reveal the window only once the kernel answers /health, so the UI
            // never flashes a connection error on a cold start.
            let window = app.get_webview_window("main").expect("main window missing");
            std::thread::spawn(move || {
                wait_for_health();
                let _ = window.show();
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if matches!(event, WindowEvent::Destroyed) {
                if let Some(state) = window.app_handle().try_state::<KernelProcess>() {
                    if let Some(mut child) = state.0.lock().unwrap().take() {
                        let _ = child.kill();
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running the agent-me desktop shell");
}
