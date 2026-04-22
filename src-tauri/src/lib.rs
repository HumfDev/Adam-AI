use std::io::{BufRead, BufReader, Write};
use std::sync::Mutex;
use std::time::Duration;
use tauri::{Manager, State};

struct SerialState(Mutex<Option<Box<dyn serialport::SerialPort>>>);

#[tauri::command]
fn list_ports() -> Vec<String> {
    serialport::available_ports()
        .unwrap_or_default()
        .into_iter()
        .map(|p| p.port_name)
        .collect()
}

#[tauri::command]
fn connect_port(port: String, state: State<SerialState>) -> Result<String, String> {
    let sp = serialport::new(&port, 115200)
        .timeout(Duration::from_millis(500))
        .open()
        .map_err(|e| e.to_string())?;
    *state.0.lock().unwrap() = Some(sp);
    Ok(format!("connected:{}", port))
}

#[tauri::command]
fn disconnect_port(state: State<SerialState>) {
    *state.0.lock().unwrap() = None;
}

#[tauri::command]
fn send_command(cmd: String, state: State<SerialState>) -> Result<String, String> {
    let mut guard = state.0.lock().unwrap();
    let sp = guard.as_mut().ok_or("not connected")?;
    let line = format!("{}\n", cmd.trim());
    sp.write_all(line.as_bytes()).map_err(|e| e.to_string())?;
    let mut reader = BufReader::new(sp.try_clone().map_err(|e| e.to_string())?);
    let mut response = String::new();
    reader.read_line(&mut response).map_err(|e| e.to_string())?;
    Ok(response.trim().to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(SerialState(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![
            list_ports,
            connect_port,
            disconnect_port,
            send_command,
        ])
        .setup(|app| {
            let window = app.get_webview_window("main").unwrap();
            window.hide().unwrap();
            let w = window.clone();
            std::thread::spawn(move || {
                std::thread::sleep(Duration::from_millis(300));
                w.show().unwrap();
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
