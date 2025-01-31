#!/usr/bin/env python3
"""
anything_llm_embed.py

Two modes:
----------------------------------
1) CLI Mode (--cli or -C):
   - If --api_url and --api_token not provided, user is prompted.
   - Then user picks directory & subdirs to ignore, uploads to the given AnythingLLM instance.
   - If run with --log/-L, logs also print to console.

2) GUI Mode (default):
   - Tkinter UI with:
     a) "Config" menu to set API_URL, API_TOKEN
     b) Folder selection, subdir ignoring
     c) "Start Embedding" in a background thread
     d) "Stop Embedding" if embedding is in progress
     e) A "Logs" toggle that shows a scrollable panel of logs at the bottom,
        auto-scrolling as new logs are added in real time.

Author: ...
Requires: pip install requests
"""

import os
import sys
import argparse
import requests
import logging
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from time import sleep
import concurrent.futures
from tkinter.ttk import Progressbar, Style

LOG_FILE = "process_logs.txt"

###############################################################################
# GLOBAL LOG MANAGEMENT
###############################################################################

_memory_logs = []

def init_logger(args):
    for h in logging.root.handlers[:]:
        logging.root.removeHandler(h)
    log_level = logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        filename=LOG_FILE,
        filemode="a",
    )

    if getattr(args, "log", False):
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logging.getLogger().addHandler(console_handler)

def log_message(level, msg):
    line = f"{level.upper()}: {msg}"
    _memory_logs.append(line)

    if level.lower() == "info":
        logging.info(msg)
    elif level.lower() == "warning":
        logging.warning(msg)
    elif level.lower() == "error":
        logging.error(msg)
    else:
        logging.debug(msg)

def get_memory_logs():
    return "\n".join(_memory_logs)

class Config:
    def __init__(self, url=None, token=None):
        self.api_url = url or ""
        self.api_token = token or ""

    def is_valid(self):
        return bool(self.api_url.strip()) and bool(self.api_token.strip())

def embed_files_cli(base_dir, ignored_dirs, app_config: Config):
    log_message("info", f"Starting embed in {base_dir}, ignoring {ignored_dirs}")
    api_url = app_config.api_url
    api_token = app_config.api_token

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "accept": "application/json"
    }

    all_files = []
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in ignored_dirs]
        for filename in files:
            full_path = os.path.join(root, filename)
            all_files.append(full_path)

    log_message("info", f"Found {len(all_files)} files. Beginning upload.")
    success_count = 0
    fail_count = 0

    for fpath in all_files:
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            payload = {
                "textContent": content,
                "metadata": {
                    "title": os.path.basename(fpath),
                    "fullPath": fpath
                }
            }

            resp = requests.post(api_url, headers=headers, json=payload)
            if resp.status_code == 200:
                success_count += 1
                log_message("info", f"Uploaded: {fpath}")
            else:
                fail_count += 1
                log_message("error",
                    f"FAILED uploading: {fpath}  (HTTP {resp.status_code}). Response: {resp.text}"
                )
        except Exception as e:
            fail_count += 1
            log_message("error", f"Exception reading/sending {fpath}: {e}")

    msg = f"=== Embedding Completed. Success={success_count}, Fail={fail_count}"
    log_message("info", msg)

###############################################################################
# CLI MODE
###############################################################################
def run_cli_mode(args):
    api_url = args.api_url
    api_token = args.api_token
    if not api_url:
        api_url = input("Enter the AnythingLLM API URL (e.g. http://localhost:3001/api/v1/document/raw-text): ").strip()
    if not api_token:
        api_token = input("Enter the AnythingLLM API Token: ").strip()

    app_config = Config(api_url, api_token)
    if not app_config.is_valid():
        print("ERROR: Must provide a valid API URL and Token.")
        log_message("error", "Invalid API URL/Token in CLI mode.")
        sys.exit(1)

    log_message("info", "=== CLI Mode ===")
    base_dir = input("Enter the full path of the directory to embed: ").strip()
    while not os.path.isdir(base_dir):
        log_message("warning", f"Invalid directory: {base_dir}")
        base_dir = input("Enter a valid directory path: ").strip()

    subdirs = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]
    if not subdirs:
        print("No subdirectories found to ignore.")
        log_message("info", "No subdirectories to ignore.")
        ignored_dirs = []
    else:
        print("\nSubdirectories in chosen folder:")
        for idx, sd in enumerate(subdirs, 1):
            print(f"{idx}. {sd}")
        print("Enter the numbers (comma-separated) of subfolders to ignore, or leave blank to ignore none.")
        user_input = input("Ignored subfolders? (e.g. '1,3'): ").strip()
        ignored_dirs = []
        if user_input:
            indices = [x.strip() for x in user_input.split(',')]
            for i in indices:
                try:
                    i_num = int(i)
                    if 1 <= i_num <= len(subdirs):
                        ignored_dirs.append(subdirs[i_num - 1])
                except ValueError:
                    pass

    if ignored_dirs:
        log_message("info", f"Ignoring subdirectories: {ignored_dirs}")
    else:
        log_message("info", "No subdirectories are ignored.")

    input("\nPress Enter to start embedding files into AnythingLLM...")
    embed_files_cli(base_dir, ignored_dirs, app_config)

###############################################################################
# EMBEDDING LOGIC IN A THREAD (GUI)
###############################################################################
def embed_files_threaded(app, base_dir, ignored_dirs):
    log_message("info", f"Starting embed in {base_dir}, ignoring {ignored_dirs}")
    api_url = app.app_config.api_url
    api_token = app.app_config.api_token

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "accept": "application/json"
    }

    all_files = []
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in ignored_dirs]
        for filename in files:
            full_path = os.path.join(root, filename)
            all_files.append(full_path)

    total_files = len(all_files)
    log_message("info", f"Found {total_files} files. Beginning upload.")
    success_count = 0
    fail_count = 0
    
    app.progress_bar['maximum'] = total_files

    def upload_file(fpath):
        nonlocal success_count, fail_count
        if app.stop_requested:
            return
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            payload = { "textContent": content, "metadata": { "title": os.path.basename(fpath), "fullPath": fpath } }
            resp = requests.post(
                app.app_config.api_url,
                headers={
                    "Authorization": f"Bearer {app.app_config.api_token}",
                    "Content-Type": "application/json",
                    "accept": "application/json"
                },
                json=payload
            )
            if resp.status_code == 200:
                success_count += 1
                log_message("info", f"Uploaded: {fpath}")
            else:
                fail_count += 1
                log_message("error", f"FAILED uploading: {fpath} (HTTP {resp.status_code}). Response: {resp.text}")
        except Exception as e:
            fail_count += 1
            log_message("error", f"Exception reading/sending {fpath}: {e}")
    
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = { executor.submit(upload_file, fp): fp for fp in all_files }
        for fut in concurrent.futures.as_completed(futures):
            if app.stop_requested:
                break
            app.progress_bar.step()
            processed = app.progress_bar['value']
            if fail_count == 0:
                app.progress_bar.configure(style="green.Horizontal.TProgressbar")
            else:
                app.progress_bar.configure(style="red.Horizontal.TProgressbar")
            app.update_idletasks()

    if not app.stop_requested:
        msg = f"=== Embedding Completed. Success={success_count}, Fail={fail_count}"
        log_message("info", msg)
        app.progress_bar['value'] = total_files
    else:
        log_message("warning", "Embedding has been stopped by the user.")

    app.embedding_in_progress = False
    app.stop_btn.config(state="disabled")
    if not app.stop_requested:
        messagebox.showinfo("Done", "Embedding completed.")
    else:
        messagebox.showwarning("Stopped", "Embedding was stopped by user.")

###############################################################################
# GUI MODE
###############################################################################
class ConfigWindow(tk.Toplevel):
    """A small window to let user set API URL/Token."""
    def __init__(self, parent, app_config: Config):
        super().__init__(parent)
        self.parent = parent
        self.app_config = app_config
        self.title("Configuration")
        self.geometry("400x200")

        tk.Label(self, text="AnythingLLM API URL:").pack(pady=5)
        self.url_entry = tk.Entry(self, width=50)
        self.url_entry.pack()
        self.url_entry.insert(0, self.app_config.api_url)

        tk.Label(self, text="API Token:").pack(pady=5)
        self.token_entry = tk.Entry(self, width=50, show="*")
        self.token_entry.pack()
        self.token_entry.insert(0, self.app_config.api_token)

        self.save_btn = tk.Button(self, text="Save", command=self.save_config)
        self.save_btn.pack(pady=10)

    def save_config(self):
        self.app_config.api_url = self.url_entry.get().strip()
        self.app_config.api_token = self.token_entry.get().strip()
        if not self.app_config.is_valid():
            messagebox.showwarning("Invalid Config", "API URL and Token are required.")
            return
        log_message("info", f"Updated config: {self.app_config.api_url}, ***TOKEN***")
        self.destroy()


class LlmGuiApp(tk.Tk):
    def __init__(self, app_config: Config):
        super().__init__()
        self.app_config = app_config
        self.title("Embed GUI")
        self.base_dir = ""
        self.subdirs = []
        self.ignored_dirs = []
        self.geometry("700x500")
        self.embedding_in_progress = False
        self.stop_requested = False
        self.embedding_thread = None
        menubar = tk.Menu(self)
        config_menu = tk.Menu(menubar, tearoff=0)
        config_menu.add_command(label="Settings", command=self.open_config_window)
        config_menu.add_command(label="Toggle Logs", command=self.toggle_logs)
        menubar.add_cascade(label="Config", menu=config_menu)
        self.config(menu=menubar)
        tk.Label(self, text="Easy Embed", font=("Arial", 16)).pack(pady=10)
        self.select_btn = tk.Button(self, text="Select Folder", command=self.select_folder)
        self.select_btn.pack()
        tk.Label(self, text="Ignore these subdirectories (select multiple):").pack(pady=5)
        self.subdir_listbox = tk.Listbox(self, selectmode=tk.MULTIPLE, width=40, height=8)
        self.subdir_listbox.pack()
        self.button_frame = tk.Frame(self)
        self.button_frame.pack(pady=5)
        self.embed_btn = tk.Button(self.button_frame, text="Start Embedding", command=self.start_embedding)
        self.embed_btn.pack(side="left", padx=10)
        self.stop_btn = tk.Button(self.button_frame, text="Stop Embedding", command=self.stop_embedding, state="disabled")
        self.stop_btn.pack(side="left", padx=10)
        self.log_frame = tk.Frame(self)
        self.log_text = scrolledtext.ScrolledText(self.log_frame, width=80, height=10, state="disabled")
        self.log_text.pack(padx=5, pady=5)
        self.log_frame.pack_forget()
        self.after(500, self.refresh_log_panel)
        style = Style(self)
        style.theme_use('default')
        style.configure("green.Horizontal.TProgressbar", troughcolor='#f0f0f0', background='green')
        style.configure("red.Horizontal.TProgressbar", troughcolor='#f0f0f0', background='red')
        self.progress_bar = Progressbar(self, length=400, mode='determinate', style="green.Horizontal.TProgressbar")
        self.progress_bar.pack(pady=10)

    def open_config_window(self):
        ConfigWindow(self, self.app_config)

    def toggle_logs(self):
        """Show/hide the log panel."""
        if self.log_frame.winfo_manager():
            self.log_frame.pack_forget()
        else:
            self.log_frame.pack(side="bottom", fill="x")

    def refresh_log_panel(self):
        """Periodic callback to refresh logs if log panel is visible."""
        if self.log_frame.winfo_manager():
            self.log_text.config(state="normal")
            self.log_text.delete("1.0", tk.END)
            self.log_text.insert(tk.END, get_memory_logs())
            self.log_text.config(state="disabled")
            self.log_text.yview_moveto(1.0)  # auto-scroll
        self.after(500, self.refresh_log_panel)

    def select_folder(self):
        if not self.app_config.is_valid():
            messagebox.showinfo("Configuration Needed", "Please enter API URL and Token before selecting a folder.")
            self.open_config_window()
            return

        chosen = filedialog.askdirectory(title="Select a directory")
        if chosen:
            self.base_dir = chosen
            self.subdir_listbox.delete(0, tk.END)
            self.subdirs = [
                d for d in os.listdir(self.base_dir)
                if os.path.isdir(os.path.join(self.base_dir, d))
            ]
            for sd in self.subdirs:
                self.subdir_listbox.insert(tk.END, sd)

    def start_embedding(self):
        if not self.app_config.is_valid():
            messagebox.showwarning("No Config", "Please set an API URL and Token first.")
            self.open_config_window()
            return

        if not self.base_dir:
            messagebox.showwarning("No folder selected", "Please select a folder first.")
            return

        if self.embedding_in_progress:
            messagebox.showwarning("Embedding", "An embedding process is already in progress.")
            return

        selected_indices = self.subdir_listbox.curselection()
        self.ignored_dirs = [self.subdirs[i] for i in selected_indices]
        confirm = messagebox.askyesno(
            "Confirm",
            f"Start embedding from:\n{self.base_dir}\nIgnoring: {self.ignored_dirs}\n\nAPI: {self.app_config.api_url}"
        )

        if not confirm:
            return

        self.embedding_in_progress = True
        self.stop_requested = False
        self.stop_btn.config(state="normal")   # enable stop button
        self.progress_bar['value'] = 0
        self.embedding_thread = threading.Thread(
            target=embed_files_threaded,
            args=(self, self.base_dir, self.ignored_dirs),
            daemon=True
        )
        self.embedding_thread.start()
        log_message("info", "Embedding thread started.")

    def stop_embedding(self):
        """Signal the background thread to stop."""
        if not self.embedding_in_progress:
            return
        self.stop_requested = True
        self.stop_btn.config(state="disabled")
        log_message("warning", "Stop requested by user.")


def embed_files_threaded(app, base_dir, ignored_dirs):
    try:
        api_url = app.app_config.api_url
        api_token = app.app_config.api_token

        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "accept": "application/json"
        }

        all_files = []
        for root, dirs, files in os.walk(base_dir):
            if app.stop_requested:
                break
            dirs[:] = [d for d in dirs if d not in ignored_dirs]
            for filename in files:
                if app.stop_requested:
                    break
                full_path = os.path.join(root, filename)
                all_files.append(full_path)

        total_files = len(all_files)
        log_message("info", f"Found {total_files} files. Beginning upload.")
        success_count = 0
        fail_count = 0
        
        app.progress_bar['maximum'] = total_files

        def upload_file(fpath):
            nonlocal success_count, fail_count
            if app.stop_requested:
                return
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                payload = { "textContent": content, "metadata": { "title": os.path.basename(fpath), "fullPath": fpath } }
                resp = requests.post(
                    app.app_config.api_url,
                    headers={
                        "Authorization": f"Bearer {app.app_config.api_token}",
                        "Content-Type": "application/json",
                        "accept": "application/json"
                    },
                    json=payload
                )
                if resp.status_code == 200:
                    success_count += 1
                    log_message("info", f"Uploaded: {fpath}")
                else:
                    fail_count += 1
                    log_message("error", f"FAILED uploading: {fpath} (HTTP {resp.status_code}). Response: {resp.text}")
            except Exception as e:
                fail_count += 1
                log_message("error", f"Exception reading/sending {fpath}: {e}")
        
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = { executor.submit(upload_file, fp): fp for fp in all_files }
            for fut in concurrent.futures.as_completed(futures):
                if app.stop_requested:
                    break
                app.progress_bar.step()
                processed = app.progress_bar['value']
                if fail_count == 0:
                    app.progress_bar.configure(style="green.Horizontal.TProgressbar")
                else:
                    app.progress_bar.configure(style="red.Horizontal.TProgressbar")
                app.update_idletasks()

        if not app.stop_requested:
            msg = f"=== Embedding Completed. Success={success_count}, Fail={fail_count}"
            log_message("info", msg)
            app.progress_bar['value'] = total_files
        else:
            log_message("warning", "Embedding has been stopped by the user.")
    finally:
        app.embedding_in_progress = False
        app.stop_btn.config(state="disabled")
        if not app.stop_requested:
            messagebox.showinfo("Done", "Embedding completed.")
        else:
            messagebox.showwarning("Stopped", "Embedding was stopped by user.")

def run_gui_mode(args):
    app_config = Config(
        url=args.api_url or "",
        token=args.api_token or "",
    )
    app = LlmGuiApp(app_config)
    app.mainloop()

def main():
    parser = argparse.ArgumentParser(description="Easy Embed")
    parser.add_argument("--cli", "-C", action="store_true", help="Run in CLI mode instead of GUI.")
    parser.add_argument("--api_url", type=str, default=None, help="AnythingLLM API URL.")
    parser.add_argument("--api_token", type=str, default=None, help="AnythingLLM API Token.")
    parser.add_argument("--log", "-L", action="store_true", help="Show logs in real-time in CLI mode.")
    args = parser.parse_args()

    init_logger(args)

    if args.cli:
        run_cli_mode(args)
    else:
        run_gui_mode(args)

if __name__ == "__main__":
    main()
