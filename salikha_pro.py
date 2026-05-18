import os, time, threading, json, queue, stat, shutil
import tkinter as tk
from tkinter import scrolledtext, messagebox, ttk, filedialog
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from PIL import Image, ImageOps, ImageTk, ImageWin, UnidentifiedImageError
import win32print, win32ui

# --- PILLOW COMPATIBILITY ---
try:
    from PIL import ImageResampling
    RESAMPLE_METHOD = ImageResampling.LANCZOS
except ImportError:
    RESAMPLE_METHOD = getattr(Image, 'LANCZOS', getattr(Image, 'ANTIALIAS', 1))

CONFIG_FILE = "salikha_layout.json"

class SalikhaStudioPro:
    def __init__(self, root):
        self.root = root
        self.root.title("Salikha Studio - PRO")
        self.root.geometry("1200x850")
        
        self.style = ttk.Style(self.root)
        self.style.theme_use('clam')
        
        # --- TRAFFIC CONTROL (Engine) ---
        self.input_queue = queue.Queue() 
        self.gui_queue = queue.Queue()
        self.processed_files = set()
        
        self.boxes = [] 
        self.template_path = ""
        self.print_count = 0
        self.is_running = False  
        self.engine_start_time = 0
        self.last_printed_file = None # FAILSAFE: Memory for the last print
        
        # --- TRAFFIC CONTROL (Sorter) ---
        self.is_sorting = False  
        self.sorter_thread = None

        # Defaults Engine
        self.source_folder = os.path.abspath("./hot_input")
        self.output_folder = os.path.abspath("./prints_archive")
        
        # Defaults Sorter
        self.sd_source = ""
        self.sd_dest_prot = ""
        self.sd_dest_raw = ""

        for f in [self.source_folder, self.output_folder]:
            if not os.path.exists(f): os.makedirs(f)

        # --- TABBED LAYOUT ---
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self.design_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.design_tab, text=" 1. Template Customization ")
        self.setup_designer()

        self.engine_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.engine_tab, text=" 2. Run Event ")
        self.setup_engine()

        self.sorter_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.sorter_tab, text=" 3. SD Card Sorter ")
        self.setup_sorter()

        self.load_config()
        self.process_gui_queue()

    def process_gui_queue(self):
        try:
            while True:
                task = self.gui_queue.get_nowait()
                action = task.get("action")
                
                if action == "log":
                    self.log_box.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {task['msg']}\n")
                    self.log_box.see(tk.END)
                elif action == "sorter_log":
                    self.sorter_log_area.config(state='normal')
                    self.sorter_log_area.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {task['msg']}\n")
                    self.sorter_log_area.see(tk.END)
                    self.sorter_log_area.config(state='disabled')
                elif action == "preview":
                    self.tk_p = ImageTk.PhotoImage(task['image'])
                    self.prev_lbl.config(image=self.tk_p, text="")
                elif action == "update_count":
                    self.count_lbl.config(text=f"Total Prints: {task['count']}")
                elif action == "clear_prev":
                    self.prev_lbl.config(image='', text="Waiting for next group...")
                elif action == "enable_reprint": 
                    self.reprint_btn.config(state="normal")
                
                self.gui_queue.task_done()
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.process_gui_queue)

    # ========================================================
    # TAB 1: DESIGNER
    # ========================================================
    def setup_designer(self):
        ctrl = tk.Frame(self.design_tab, width=280, bg="#f8f9fa", relief="ridge", bd=2)
        ctrl.pack(side="left", fill="y", padx=10, pady=10)
        
        tk.Label(ctrl, text="Design Controls", font=("Arial", 14, "bold"), bg="#f8f9fa").pack(pady=(15, 5))
        ttk.Button(ctrl, text="Load Overlay PNG", command=self.load_template).pack(fill="x", padx=15, pady=5)
        
        ratio_frame = tk.LabelFrame(ctrl, text="Box Aspect Ratio", bg="#f8f9fa")
        ratio_frame.pack(fill="x", padx=15, pady=10)
        
        self.box_ratio = tk.StringVar(value="Landscape (4:3)")
        ttk.Radiobutton(ratio_frame, text="Landscape (4:3)", variable=self.box_ratio, value="Landscape (4:3)").pack(anchor="w", padx=10, pady=2)
        ttk.Radiobutton(ratio_frame, text="Portrait (3:4)", variable=self.box_ratio, value="Portrait (3:4)").pack(anchor="w", padx=10, pady=2)
        ttk.Radiobutton(ratio_frame, text="Freeform", variable=self.box_ratio, value="Freeform").pack(anchor="w", padx=10, pady=2)

        tk.Label(ctrl, text="Click & Drag to Draw.\nClick inside a box to Move it.", fg="#555", bg="#f8f9fa", justify="center").pack(pady=5)
        tk.Button(ctrl, text="Clear All Boxes", command=self.clear_boxes, bg="#ff4c4c", fg="white", font=("Arial", 10, "bold")).pack(fill="x", padx=15, pady=(20, 5))
        tk.Button(ctrl, text="SAVE CONFIG", command=self.save_config, bg="#28a745", fg="white", font=("Arial", 11, "bold"), height=2).pack(fill="x", padx=15, pady=20)

        center_frame = tk.Frame(self.design_tab, bg="#e9ecef")
        center_frame.pack(side="right", expand=True, fill="both", padx=10, pady=10)
        
        self.canvas_wrapper = tk.Frame(center_frame, relief="solid", bd=1)
        self.canvas_wrapper.pack(expand=True)

        self.canvas = tk.Canvas(self.canvas_wrapper, bg="#333", width=600, height=800, cursor="cross")
        self.canvas.pack()
        
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        
        self.action = None
        self.selected_item = None

    def load_template(self):
        p = filedialog.askopenfilename(filetypes=[("PNG", "*.png")])
        if p:
            self.template_path = p
            img = Image.open(p)
            disp = img.copy()
            disp.thumbnail((600, 800))
            self.scale = img.width / disp.width
            self.tk_t = ImageTk.PhotoImage(disp)
            
            self.canvas.config(width=disp.width, height=disp.height)
            self.canvas.delete("all")
            self.canvas.create_image(0, 0, anchor="nw", image=self.tk_t, tags="bg_template")
            
            self.canvas.create_rectangle(
                2, 2, disp.width-2, disp.height-2, 
                outline="#00ff00", width=3, dash=(5, 5), tags="template_border"
            )
            self.boxes = [] 

    def on_press(self, e):
        items = self.canvas.find_withtag("photobox")
        for item in items:
            c = self.canvas.coords(item)
            if c[0] <= e.x <= c[2] and c[1] <= e.y <= c[3]:
                self.selected_item = item
                self.action = 'move'
                self.start_x, self.start_y = e.x, e.y
                self.canvas.itemconfig(item, outline="yellow", width=4) 
                return
        
        self.action = 'draw'
        self.sx, self.sy = e.x, e.y
        self.rect = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#00aaff", width=3, tags="photobox")

    def on_drag(self, e):
        if self.action == 'move' and self.selected_item:
            dx = e.x - self.start_x
            dy = e.y - self.start_y
            self.canvas.move(self.selected_item, dx, dy)
            self.start_x, self.start_y = e.x, e.y
            
        elif self.action == 'draw':
            dx = e.x - self.sx
            dy = e.y - self.sy
            
            ratio_mode = self.box_ratio.get()
            
            if "Landscape" in ratio_mode:
                h = abs(dx) * 0.75 * (1 if dy > 0 else -1)
                self.canvas.coords(self.rect, self.sx, self.sy, self.sx + dx, self.sy + h)
            elif "Portrait" in ratio_mode:
                h = abs(dx) * (4/3) * (1 if dy > 0 else -1)
                self.canvas.coords(self.rect, self.sx, self.sy, self.sx + dx, self.sy + h)
            else:
                self.canvas.coords(self.rect, self.sx, self.sy, e.x, e.y)

    def on_release(self, e):
        if self.action == 'move' and self.selected_item:
            self.canvas.itemconfig(self.selected_item, outline="#00aaff", width=3) 
            
        if self.action == 'draw':
            c = self.canvas.coords(self.rect)
            x1, y1, x2, y2 = min(c[0], c[2]), min(c[1], c[3]), max(c[0], c[2]), max(c[1], c[3])
            if abs(x2 - x1) < 10 or abs(y2 - y1) < 10:
                self.canvas.delete(self.rect)
            else:
                self.canvas.coords(self.rect, x1, y1, x2, y2)
        
        self.sync_boxes()

    def sync_boxes(self):
        self.boxes = []
        for item in self.canvas.find_withtag("photobox"):
            c = self.canvas.coords(item)
            self.boxes.append([x * self.scale for x in c])

    def clear_boxes(self):
        self.canvas.delete("photobox")
        self.sync_boxes()

    # ========================================================
    # TAB 2: ENGINE
    # ========================================================
    def setup_engine(self):
        left = tk.Frame(self.engine_tab, width=400)
        left.pack(side="left", fill="y", padx=20, pady=20)
        
        tk.Label(left, text="📂 Folder & Print Configuration", font=("Arial", 12, "bold"), fg="#333").pack(anchor="w", pady=(0, 10))
        
        src_frame = tk.LabelFrame(left, text="Source (Camera Hot Folder)", padx=5, pady=5)
        src_frame.pack(fill="x", pady=5)
        self.src_entry = tk.Entry(src_frame, width=35)
        self.src_entry.insert(0, self.source_folder)
        self.src_entry.pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(src_frame, text="Browse", command=self.select_source).pack(side="right")

        out_frame = tk.LabelFrame(left, text="Output (Save Prints)", padx=5, pady=5)
        out_frame.pack(fill="x", pady=5)
        self.out_entry = tk.Entry(out_frame, width=35)
        self.out_entry.insert(0, self.output_folder)
        self.out_entry.pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(out_frame, text="Browse", command=self.select_output).pack(side="right")

        tk.Frame(left, height=2, bg="#ddd").pack(fill="x", pady=10)

        print_ctrl_frame = tk.Frame(left)
        print_ctrl_frame.pack(fill="x", pady=5)
        
        self.mode_var = tk.StringVar(value="Print + JPEG")
        cb = ttk.Combobox(print_ctrl_frame, textvariable=self.mode_var, values=("Print + JPEG", "JPEG Only"), state="readonly", width=15)
        cb.pack(side="left", padx=(0, 5))
        
        ttk.Button(print_ctrl_frame, text="⚙️ Printer Prefs", command=self.open_printer_preferences).pack(side="left", fill="x", expand=True)
        
        self.reprint_btn = ttk.Button(print_ctrl_frame, text="🔄 REPRINT LAST", command=self.reprint_last, state="disabled")
        self.reprint_btn.pack(side="left", fill="x", expand=True, padx=(5, 0))

        self.count_lbl = tk.Label(left, text="Total Prints: 0", font=("Arial", 16, "bold"), fg="#007bff")
        self.count_lbl.pack(pady=10)

        btn_frame = tk.Frame(left)
        btn_frame.pack(fill="x", pady=10)
        self.start_btn = tk.Button(btn_frame, text="START ENGINE", bg="#28a745", fg="white", font=("Arial", 12, "bold"), command=self.start_engine, height=2, width=15)
        self.start_btn.pack(side="left", expand=True, fill="x", padx=(0, 5))
        self.stop_btn = tk.Button(btn_frame, text="STOP", bg="#dc3545", fg="white", font=("Arial", 12, "bold"), state="disabled", command=self.stop_engine, height=2, width=8)
        self.stop_btn.pack(side="right")

        self.log_box = scrolledtext.ScrolledText(left, width=45, height=12, font=("Consolas", 8), bg="#f4f4f4")
        self.log_box.pack(pady=10, fill="both", expand=True)

        self.prev_frame = ttk.LabelFrame(self.engine_tab, text=" Live Print Preview ")
        self.prev_frame.pack(side="right", fill="both", expand=True, padx=20, pady=20)
        self.prev_lbl = tk.Label(self.prev_frame, text="Ready...", bg="#e9ecef")
        self.prev_lbl.pack(expand=True, fill="both", padx=5, pady=5)

    def select_source(self):
        path = filedialog.askdirectory()
        if path: self.source_folder = path; self.src_entry.delete(0, tk.END); self.src_entry.insert(0, path)

    def select_output(self):
        path = filedialog.askdirectory()
        if path: self.output_folder = path; self.out_entry.delete(0, tk.END); self.out_entry.insert(0, path)

    def open_printer_preferences(self):
        try:
            printer_name = win32print.GetDefaultPrinter()
            PRINTER_ALL_ACCESS = 0x000F000C
            hprinter = win32print.OpenPrinter(printer_name, {"DesiredAccess": PRINTER_ALL_ACCESS})
            win32print.DocumentProperties(0, hprinter, printer_name, None, None, 14)
            win32print.ClosePrinter(hprinter)
            self.queue_log(f"🖨️ Opened settings for: {printer_name}")
        except Exception as e:
            messagebox.showerror("Printer Settings Error", f"Could not open properties for default printer:\n{e}")

    def reprint_last(self):
        if self.last_printed_file and os.path.exists(self.last_printed_file):
            self.queue_log(f"🔄 FAILSAFE TRIPPED: Reprinting {os.path.basename(self.last_printed_file)}")
            self.silent_print(self.last_printed_file)
        else:
            messagebox.showwarning("Reprint Error", "No previous print found in memory or file was deleted.")

    def queue_log(self, msg):
        self.gui_queue.put({"action": "log", "msg": msg})

    def start_engine(self):
        if not self.boxes: return messagebox.showerror("Error", "No layout designed! Add boxes in Designer.")
        if not os.path.exists(self.source_folder): return messagebox.showerror("Error", "Source folder missing!")
        
        self.is_running = True
        self.engine_start_time = time.time()  
        self.start_btn.config(state="disabled"); self.stop_btn.config(state="normal")
        self.src_entry.config(state="disabled"); self.out_entry.config(state="disabled")

        with self.input_queue.mutex: self.input_queue.queue.clear()
        self.processed_files.clear()

        self.handler = SalikhaHandler(self.queue_file, self.queue_log, self.engine_start_time)
        self.obs = Observer()
        self.obs.schedule(self.handler, self.source_folder, recursive=False)
        self.obs.start()

        self.poller_thread = threading.Thread(target=self.safety_net_loop, daemon=True)
        self.poller_thread.start()

        self.processor_thread = threading.Thread(target=self.logic_processor_loop, daemon=True)
        self.processor_thread.start()
        
        self.queue_log(f"🚀 ENGINE STARTED: Waiting for NEW photos only.")

    def stop_engine(self):
        if hasattr(self, 'obs'): self.obs.stop()
        self.is_running = False
        self.start_btn.config(state="normal"); self.stop_btn.config(state="disabled")
        self.src_entry.config(state="normal"); self.out_entry.config(state="normal")
        self.queue_log("🛑 Engine Stopped.")

    def queue_file(self, file_path):
        norm_path = os.path.normpath(file_path)
        if norm_path not in self.processed_files:
            try:
                mtime = os.path.getmtime(norm_path)
                if mtime >= self.engine_start_time:
                    self.processed_files.add(norm_path)
                    self.input_queue.put(norm_path)
            except OSError:
                pass

    def safety_net_loop(self):
        while self.is_running:
            try:
                files = [os.path.join(self.source_folder, f) for f in os.listdir(self.source_folder)]
                files = [f for f in files if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
                files.sort(key=os.path.getmtime)
                for f in files:
                    norm_f = os.path.normpath(f)
                    if norm_f not in self.processed_files:
                        if os.path.getmtime(norm_f) >= self.engine_start_time:
                            self.queue_log(f"🔎 Safety Net found missed file: {os.path.basename(f)}")
                            self.queue_file(norm_f)
                time.sleep(3.0)
            except: time.sleep(3.0)

    def logic_processor_loop(self):
        current_session = [] 
        required_count = len(self.boxes)
        self.queue_log(f"ℹ️ Layout requires {required_count} photos.")

        while self.is_running:
            try:
                file_path = self.input_queue.get(timeout=1.0)
                retries = 0
                while not self.is_file_ready(file_path):
                    if not self.is_running: break
                    retries += 1
                    if retries % 15 == 0: self.queue_log(f"⏳ Waiting for lock release: {os.path.basename(file_path)}")
                    time.sleep(0.2)
                if not self.is_running: break

                current_session.append(file_path)
                current_step = len(current_session)
                self.queue_log(f"📸 Captured {current_step}/{required_count}: {os.path.basename(file_path)}")
                
                if current_step == required_count:
                    self.update_preview_and_save(current_session, save_to_disk=True)
                    self.queue_log("✅ PRINT COMPLETE. Waiting for next group...")
                    current_session = [] 
                    time.sleep(1.5)
                    self.gui_queue.put({"action": "clear_prev"})
                else:
                    self.update_preview_and_save(current_session, save_to_disk=False)
                
                self.input_queue.task_done()
            except queue.Empty: continue
            except Exception as e: self.queue_log(f"❌ Processing Error: {e}")

    def is_file_ready(self, filepath):
        if not os.path.exists(filepath): return False
        try:
            with open(filepath, 'ab'): pass
            return True
        except: return False

    def update_preview_and_save(self, current_files, save_to_disk):
        try:
            with Image.open(self.template_path) as t:
                overlay = t.convert("RGBA")
                canvas = Image.new("RGBA", overlay.size, (255, 255, 255, 255))
                for i, p in enumerate(current_files):
                    if i < len(self.boxes):
                        box = self.boxes[i]
                        with Image.open(p) as img:
                            img = ImageOps.exif_transpose(img)
                            w, h = int(box[2]-box[0]), int(box[3]-box[1])
                            img = ImageOps.fit(img, (w, h), RESAMPLE_METHOD)
                            canvas.paste(img, (int(box[0]), int(box[1])))
                canvas.paste(overlay, (0, 0), overlay)
                
                prev = canvas.copy()
                prev.thumbnail((600, 800), RESAMPLE_METHOD)
                self.gui_queue.put({"action": "preview", "image": prev})

                if save_to_disk:
                    filename = f"Print_{int(time.time())}.jpg"
                    out_path = os.path.join(self.output_folder, filename)
                    canvas.convert("RGB").save(out_path, "JPEG", quality=98)
                    self.queue_log(f"💾 SAVED: {filename}")

                    self.last_printed_file = out_path
                    self.gui_queue.put({"action": "enable_reprint"})

                    if "Print" in self.mode_var.get():
                        self.silent_print(out_path)
                        self.print_count += 1
                        self.gui_queue.put({"action": "update_count", "count": self.print_count})
        except Exception as e:
            self.queue_log(f"Render Error: {e}")

    def silent_print(self, file_path):
        threading.Thread(target=self._print_worker, args=(file_path,)).start()

    def _print_worker(self, file_path):
        try:
            printer_name = win32print.GetDefaultPrinter()
            hDC = win32ui.CreateDC()
            hDC.CreatePrinterDC(printer_name)
            img = Image.open(file_path)
            hDC.StartDoc(file_path); hDC.StartPage()
            dib = ImageWin.Dib(img); w = hDC.GetDeviceCaps(8); h = hDC.GetDeviceCaps(10)
            dib.draw(hDC.GetHandleOutput(), (0, 0, w, h))
            hDC.EndPage(); hDC.EndDoc(); hDC.DeleteDC()
        except Exception as e: 
            self.queue_log(f"❌ PRINTER ERROR: Check cables/paper! ({e})")

    # ========================================================
    # TAB 3: SD CARD SORTER
    # ========================================================
    def setup_sorter(self):
        container = ttk.Frame(self.sorter_tab)
        container.pack(expand=True, fill="both", padx=50, pady=20)

        # Step 1: Source
        ttk.Label(container, text="Step 1: Select SD Card (Source)", font=("Arial", 11, "bold")).pack(pady=(10, 2))
        self.src_path_var = tk.StringVar(value=self.sd_source or "Click to select SD Card...")
        tk.Button(container, textvariable=self.src_path_var, command=self.select_sorter_source, width=80, relief="groove", bg="#fff").pack(pady=2)

        # Step 2: Locked Destination (Restored)
        ttk.Label(container, text="Step 2: Folder for LOCKED Files (Favorites/Protected)", font=("Arial", 11, "bold")).pack(pady=(15, 2))
        self.dest_prot_var = tk.StringVar(value=self.sd_dest_prot or "Click to select destination...")
        tk.Button(container, textvariable=self.dest_prot_var, command=self.select_sorter_dest_prot, width=80, relief="groove", bg="#fff").pack(pady=2)

        # Step 3: Raw/Unlocked Destination
        ttk.Label(container, text="Step 3: Folder for UNLOCKED Files (Discard/Raw Archive)", font=("Arial", 11, "bold")).pack(pady=(15, 2))
        self.dest_raw_var = tk.StringVar(value=self.sd_dest_raw or "Click to select destination...")
        tk.Button(container, textvariable=self.dest_raw_var, command=self.select_sorter_dest_raw, width=80, relief="groove", bg="#fff").pack(pady=2)

        self.btn_start_sorter = tk.Button(container, text="START MONITORING & COPYING", bg="#007bff", fg="white", font=("Arial", 12, "bold"), command=self.toggle_sorter, height=2)
        self.btn_start_sorter.pack(pady=25, fill="x", padx=100)

        self.sorter_log_area = scrolledtext.ScrolledText(container, height=12, state='disabled', font=("Consolas", 9), bg="#f4f4f4")
        self.sorter_log_area.pack(padx=10, pady=10, fill="both", expand=True)

    def select_sorter_source(self):
        path = filedialog.askdirectory()
        if path: self.src_path_var.set(path)

    def select_sorter_dest_prot(self):
        path = filedialog.askdirectory()
        if path: self.dest_prot_var.set(path)

    def select_sorter_dest_raw(self):
        path = filedialog.askdirectory()
        if path: self.dest_raw_var.set(path)

    def sorter_queue_log(self, message):
        self.gui_queue.put({"action": "sorter_log", "msg": message})

    def is_locked(self, filepath):
        return not (os.stat(filepath).st_mode & stat.S_IWRITE)

    def get_orientation_folder(self, filepath):
        try:
            with Image.open(filepath) as img:
                width, height = img.size
                exif = img.getexif()
                orientation_tag = exif.get(274)

                if orientation_tag in [5, 6, 7, 8]:
                    width, height = height, width

                if width >= height:
                    return "Landscape"
                else:
                    return "Portrait"
        except (UnidentifiedImageError, OSError):
            return "Unsorted"
        except Exception:
            return "Unsorted"

    def toggle_sorter(self):
        if not self.is_sorting:
            if not all(os.path.isdir(d) for d in [self.src_path_var.get(), self.dest_prot_var.get(), self.dest_raw_var.get()]):
                messagebox.showerror("Error", "Please select valid folders for the Sorter (Source, Locked, and Unlocked).")
                return

            self.is_sorting = True
            self.btn_start_sorter.config(text="STOP COPYING", bg="#dc3545")
            self.sorter_thread = threading.Thread(target=self.sorter_monitor_loop, daemon=True)
            self.sorter_thread.start()
            self.sorter_queue_log("SD Card Monitoring started...")
        else:
            self.is_sorting = False
            self.btn_start_sorter.config(text="Stopping...", state="disabled", bg="#6c757d")

    def sorter_monitor_loop(self):
        src = self.src_path_var.get()
        dest_prot = self.dest_prot_var.get()
        dest_raw = self.dest_raw_var.get()
        valid_exts = ('.JPG', '.JPEG', '.PNG', '.CR2', '.CR3', '.NEF', '.ARW', '.MP4', '.MOV')

        while self.is_sorting:
            try:
                files = [f for f in os.listdir(src) if not f.startswith('.')]
                
                for filename in files:
                    if not self.is_sorting: break
                    
                    if filename.upper().endswith(valid_exts):
                        source_path = os.path.join(src, filename)
                        
                        if self.is_locked(source_path):
                            base_folder = dest_prot
                            lock_status = "LOCKED"
                        else:
                            base_folder = dest_raw
                            lock_status = "RAW"

                        if filename.upper().endswith(('.MP4', '.MOV')):
                            orient_folder = "Video"
                        else:
                            orient_folder = self.get_orientation_folder(source_path)

                        final_dest_folder = os.path.join(base_folder, orient_folder)
                        if not os.path.exists(final_dest_folder):
                            os.makedirs(final_dest_folder)

                        target_path = os.path.join(final_dest_folder, filename)

                        if not os.path.exists(target_path):
                            try:
                                shutil.copy2(source_path, target_path)
                                os.chmod(target_path, stat.S_IWRITE) 
                                self.sorter_queue_log(f"[{lock_status} | {orient_folder}] Copied {filename}")
                            except Exception as e:
                                self.sorter_queue_log(f"Error copying {filename}: {e}")
                        
                time.sleep(2)
            except Exception as e:
                self.sorter_queue_log(f"System Error: {e}")
                time.sleep(2)

        self.btn_start_sorter.config(text="START MONITORING & COPYING", bg="#007bff", state="normal")
        self.sorter_queue_log("Monitoring Stopped.")

    # ========================================================
    # DATA SAVING / LOADING
    # ========================================================
    def save_config(self):
        data = {
            "template": self.template_path, 
            "boxes": self.boxes, 
            "source": self.source_folder, 
            "output": self.output_folder,
            "sd_source": self.src_path_var.get() if hasattr(self, 'src_path_var') and os.path.isdir(self.src_path_var.get()) else "",
            "sd_dest_prot": self.dest_prot_var.get() if hasattr(self, 'dest_prot_var') and os.path.isdir(self.dest_prot_var.get()) else "",
            "sd_dest_raw": self.dest_raw_var.get() if hasattr(self, 'dest_raw_var') and os.path.isdir(self.dest_raw_var.get()) else ""
        }
        with open(CONFIG_FILE, "w") as f: json.dump(data, f)
        messagebox.showinfo("Salikha", "Settings and Layout successfully saved!")

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
                    
                self.template_path = data.get("template", "")
                if self.template_path and os.path.exists(self.template_path):
                    img = Image.open(self.template_path)
                    disp = img.copy()
                    disp.thumbnail((600, 800))
                    self.scale = img.width / disp.width
                    self.tk_t = ImageTk.PhotoImage(disp)
                    self.canvas.config(width=disp.width, height=disp.height)
                    self.canvas.create_image(0, 0, anchor="nw", image=self.tk_t, tags="bg_template")
                    self.canvas.create_rectangle(
                        2, 2, disp.width-2, disp.height-2, 
                        outline="#00ff00", width=3, dash=(5, 5), tags="template_border"
                    )
                
                self.boxes = data.get("boxes", [])
                for box in self.boxes:
                    scaled_box = [x / self.scale for x in box]
                    self.canvas.create_rectangle(*scaled_box, outline="#00aaff", width=3, tags="photobox")

                src = data.get("source"); out = data.get("output")
                if src and os.path.exists(src): self.source_folder = src; self.src_entry.delete(0, tk.END); self.src_entry.insert(0, src)
                if out and os.path.exists(out): self.output_folder = out; self.out_entry.delete(0, tk.END); self.out_entry.insert(0, out)

                if data.get("sd_source") and hasattr(self, 'src_path_var'): self.src_path_var.set(data["sd_source"])
                if data.get("sd_dest_prot") and hasattr(self, 'dest_prot_var'): self.dest_prot_var.set(data["sd_dest_prot"])
                if data.get("sd_dest_raw") and hasattr(self, 'dest_raw_var'): self.dest_raw_var.set(data["sd_dest_raw"])

            except Exception as e:
                print(f"Error loading config: {e}")

class SalikhaHandler(FileSystemEventHandler):
    def __init__(self, callback, log_func, engine_start_time):
        self.callback = callback; self.log = log_func
        self.engine_start_time = engine_start_time
        
    def on_created(self, event):
        if not event.is_directory and event.src_path.lower().endswith(('.jpg', '.jpeg', '.png')): 
            self.callback(event.src_path)
            
    def on_moved(self, event):
        if not event.is_directory and event.dest_path.lower().endswith(('.jpg', '.jpeg', '.png')): 
            self.callback(event.dest_path)

if __name__ == "__main__":
    root = tk.Tk()
    app = SalikhaStudioPro(root)
    root.mainloop()