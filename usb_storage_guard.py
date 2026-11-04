# -*- coding: utf-8 -*-
"""
USB Storage Guard
Windows 10/11 x64. Monitors USB disks and attempts to take disks larger
than the configured threshold offline using Windows Storage cmdlets.
This is not a kernel filter driver and cannot guarantee blocking every
USB flash drive or USB bridge. See README.md.
"""
import os
import sys
import json
import time
import base64
import hashlib
import secrets
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox

APP_NAME = "USB Storage Guard"
LIMIT_GB = 265
LIMIT_BYTES = LIMIT_GB * 1_000_000_000  # Decimal GB
POLL_SECONDS = 3
APP_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "USBStorageGuard")
CONFIG_FILE = os.path.join(APP_DIR, "settings.json")
LOG_FILE = os.path.join(APP_DIR, "activity.log")


def is_admin():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def ensure_admin():
    if is_admin():
        return
    import ctypes
    params = " ".join('"' + a.replace('"', r'\"') + '"' for a in sys.argv)
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    if rc <= 32:
        messagebox.showerror(APP_NAME, "يلزم تشغيل البرنامج بصلاحيات المسؤول.")
    sys.exit(0)


def log(message):
    os.makedirs(APP_DIR, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {message}\n")


def run_powershell(script, timeout=20):
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-EncodedCommand", encoded],
        capture_output=True, text=True, timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )


def get_usb_disks():
    # Get-Disk reports physical disk capacity and bus type. The JSON is produced
    # locally; no disk contents are read.
    script = r"""
    $ErrorActionPreference = 'Stop'
    $items = @(Get-Disk | Where-Object { $_.BusType -eq 'USB' } |
      Select-Object Number,FriendlyName,SerialNumber,Size,IsOffline,IsReadOnly)
    ConvertTo-Json -InputObject $items -Compress -Depth 3
    """
    result = run_powershell(script)
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        data = json.loads(result.stdout.strip())
        if isinstance(data, dict):
            data = [data]
        return data or []
    except json.JSONDecodeError:
        log("تعذر تحليل بيانات الأقراص: " + result.stdout[:300])
        return []


def block_disk(number):
    # Taking a disk offline is reversible and does not format or erase it.
    # Windows may reject this for some removable USB flash drives.
    script = (
        "$ErrorActionPreference='Stop'; "
        f"$d=Get-Disk -Number {int(number)}; "
        "if ($d.BusType -eq 'USB') { "
        "Set-Disk -Number $d.Number -IsReadOnly $true -ErrorAction Stop; "
        "Set-Disk -Number $d.Number -IsOffline $true -ErrorAction Stop; "
        "'OK' } else { throw 'Not a USB disk' }"
    )
    return run_powershell(script)


class PasswordStore:
    @staticmethod
    def load():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    @staticmethod
    def save_password(password):
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 250_000)
        os.makedirs(APP_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"salt": base64.b64encode(salt).decode(),
                       "hash": base64.b64encode(digest).decode()}, f)

    @staticmethod
    def verify(password):
        data = PasswordStore.load()
        if not data:
            return False
        try:
            salt = base64.b64decode(data["salt"])
            expected = base64.b64decode(data["hash"])
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 250_000)
            return secrets.compare_digest(actual, expected)
        except Exception:
            return False


class App:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("760x560")
        self.root.minsize(650, 480)
        self.root.configure(bg="#f0fdf4")
        self.running = False
        self.worker = None
        self.seen_blocked = set()
        self.build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(300, self.first_run_or_login)

    def build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TButton", font=("Segoe UI", 11), padding=8)
        style.configure("TLabel", background="#f0fdf4", foreground="#14532d", font=("Segoe UI", 11))
        style.configure("Title.TLabel", font=("Segoe UI", 22, "bold"), foreground="#166534")
        style.configure("Treeview", font=("Segoe UI", 10), rowheight=28)
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

        header = tk.Frame(self.root, bg="#166534", height=95)
        header.pack(fill="x")
        tk.Label(header, text="USB Storage Guard", bg="#166534", fg="white",
                 font=("Segoe UI", 23, "bold")).pack(pady=(15, 0))
        tk.Label(header, text="حماية وحدات التخزين الخارجية حسب السعة",
                 bg="#166534", fg="#dcfce7", font=("Segoe UI", 11)).pack(pady=4)

        info = tk.Frame(self.root, bg="#dcfce7", padx=14, pady=12)
        info.pack(fill="x", padx=18, pady=16)
        tk.Label(info, text="الحد المسموح: 265 GB", bg="#dcfce7", fg="#14532d",
                 font=("Segoe UI", 15, "bold")).pack()
        tk.Label(info, text="الأقراص USB الأكبر من الحد: محاولة جعلها غير متصلة وغير قابلة للكتابة",
                 bg="#dcfce7", fg="#166534", font=("Segoe UI", 10)).pack(pady=(4, 0))

        controls = tk.Frame(self.root, bg="#f0fdf4")
        controls.pack(fill="x", padx=18)
        self.start_btn = ttk.Button(controls, text="تفعيل المراقبة", command=self.toggle)
        self.start_btn.pack(side="right", padx=5)
        ttk.Button(controls, text="تغيير كلمة المرور", command=self.change_password).pack(side="right", padx=5)
        ttk.Button(controls, text="تحديث القائمة", command=self.refresh).pack(side="left", padx=5)

        self.status = tk.Label(self.root, text="الحماية متوقفة", bg="#f0fdf4", fg="#991b1b",
                               font=("Segoe UI", 11, "bold"))
        self.status.pack(pady=10)

        columns = ("number", "name", "size", "state")
        self.tree = ttk.Treeview(self.root, columns=columns, show="headings", height=8)
        for col, title, width in [
            ("number", "رقم القرص", 85), ("name", "اسم القرص", 260),
            ("size", "السعة", 120), ("state", "الحالة", 180)
        ]:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=18, pady=8)

        note = ("تنبيه: هذه نسخة مراقبة تعتمد على أوامر Windows. قد لا يستطيع Windows وضع بعض "
                "فلاشات USB القابلة للإزالة في وضع عدم الاتصال؛ لذلك لا تعتبر حماية مضمونة لكل جهاز.")
        tk.Label(self.root, text=note, bg="#f0fdf4", fg="#92400e",
                 wraplength=700, justify="center", font=("Segoe UI", 9)).pack(padx=20, pady=6)
        tk.Label(self.root, text="عمر يحي سيلان", bg="#f0fdf4", fg="#166534",
                 font=("Segoe UI", 11, "bold")).pack(pady=(2, 12))

    def first_run_or_login(self):
        data = PasswordStore.load()
        if not data:
            self.password_dialog(create=True)
        else:
            self.password_dialog(create=False)
        self.refresh()

    def password_dialog(self, create):
        win = tk.Toplevel(self.root)
        win.title("إنشاء كلمة المرور" if create else "تسجيل الدخول")
        win.configure(bg="#f0fdf4")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        tk.Label(win, text="أنشئ كلمة مرور للمسؤول" if create else "أدخل كلمة مرور المسؤول",
                 bg="#f0fdf4", fg="#166534", font=("Segoe UI", 13, "bold")).pack(padx=22, pady=(18, 10))
        first = tk.Entry(win, show="*", width=28, font=("Segoe UI", 12), justify="center")
        first.pack(padx=22, pady=5)
        second = None
        if create:
            tk.Label(win, text="تأكيد كلمة المرور", bg="#f0fdf4").pack()
            second = tk.Entry(win, show="*", width=28, font=("Segoe UI", 12), justify="center")
            second.pack(padx=22, pady=5)
        def submit():
            p = first.get()
            if len(p) < 8:
                messagebox.showwarning(APP_NAME, "اجعل كلمة المرور 8 أحرف على الأقل.", parent=win)
                return
            if create:
                if p != second.get():
                    messagebox.showerror(APP_NAME, "كلمتا المرور غير متطابقتين.", parent=win)
                    return
                PasswordStore.save_password(p)
                log("تم إنشاء كلمة مرور المسؤول.")
                win.destroy()
            elif PasswordStore.verify(p):
                win.destroy()
            else:
                messagebox.showerror(APP_NAME, "كلمة المرور غير صحيحة.", parent=win)
                first.delete(0, "end")
        ttk.Button(win, text="تأكيد", command=submit).pack(pady=16)
        win.protocol("WM_DELETE_WINDOW", self.root.destroy)
        first.focus_set()
        self.root.wait_window(win)

    def change_password(self):
        if not PasswordStore.load():
            self.password_dialog(create=True)
            return
        # Verify current password before allowing a replacement.
        win = tk.Toplevel(self.root)
        win.title("تغيير كلمة المرور")
        win.configure(bg="#f0fdf4")
        win.transient(self.root)
        win.grab_set()
        entries = []
        for label in ("كلمة المرور الحالية", "كلمة المرور الجديدة", "تأكيد الجديدة"):
            tk.Label(win, text=label, bg="#f0fdf4").pack(pady=(8, 2))
            e = tk.Entry(win, show="*", width=28, justify="center")
            e.pack()
            entries.append(e)
        def save():
            old, new, confirm = [e.get() for e in entries]
            if not PasswordStore.verify(old):
                messagebox.showerror(APP_NAME, "كلمة المرور الحالية غير صحيحة.", parent=win)
            elif len(new) < 8 or new != confirm:
                messagebox.showerror(APP_NAME, "تأكد من تطابق كلمة المرور الجديدة (8 أحرف على الأقل).", parent=win)
            else:
                PasswordStore.save_password(new)
                log("تم تغيير كلمة المرور.")
                win.destroy()
                messagebox.showinfo(APP_NAME, "تم تغيير كلمة المرور.")
        ttk.Button(win, text="حفظ", command=save).pack(pady=14)

    def toggle(self):
        if self.running:
            self.running = False
            self.start_btn.config(text="تفعيل المراقبة")
            self.status.config(text="الحماية متوقفة", fg="#991b1b")
        else:
            self.running = True
            self.start_btn.config(text="إيقاف المراقبة")
            self.status.config(text="المراقبة تعمل", fg="#166534")
            self.worker = threading.Thread(target=self.monitor_loop, daemon=True)
            self.worker.start()

    def monitor_loop(self):
        while self.running:
            try:
                disks = get_usb_disks()
                for disk in disks:
                    size = int(disk.get("Size") or 0)
                    number = int(disk.get("Number"))
                    if size > LIMIT_BYTES and not disk.get("IsOffline", False):
                        key = (number, disk.get("SerialNumber", ""))
                        if key not in self.seen_blocked:
                            result = block_disk(number)
                            if result.returncode == 0:
                                log(f"تم وضع القرص رقم {number} دون اتصال بسبب تجاوز 265 GB.")
                                self.seen_blocked.add(key)
                            else:
                                log(f"فشل منع القرص رقم {number}: {result.stderr[:500]}")
                self.root.after(0, self.populate, disks)
            except Exception as exc:
                log("خطأ في المراقبة: " + str(exc))
            time.sleep(POLL_SECONDS)

    def refresh(self):
        threading.Thread(target=self.refresh_worker, daemon=True).start()

    def refresh_worker(self):
        try:
            disks = get_usb_disks()
            self.root.after(0, self.populate, disks)
        except Exception as exc:
            log("خطأ في تحديث القائمة: " + str(exc))

    def populate(self, disks):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for d in disks:
            size = int(d.get("Size") or 0)
            gb = size / 1_000_000_000
            if size > LIMIT_BYTES:
                state = "ممنوع / غير متصل" if d.get("IsOffline") else "يتجاوز الحد - بانتظار المنع"
            else:
                state = "مسموح"
            self.tree.insert("", "end", values=(
                d.get("Number", ""), d.get("FriendlyName", "USB Disk"),
                f"{gb:.1f} GB", state
            ))

    def close(self):
        self.running = False
        self.root.destroy()


def main():
    if os.name != "nt":
        print("This application is for Windows only.")
        return
    root = tk.Tk()
    root.withdraw()
    ensure_admin()
    root.deiconify()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
