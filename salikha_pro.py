import os, time, threading, json, queue, stat, shutil, uuid, subprocess
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import scrolledtext, messagebox, ttk, filedialog
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from PIL import Image, ImageOps, ImageTk, ImageWin, ImageFilter, UnidentifiedImageError
import win32print, win32ui
from ctypes import windll, c_wchar_p, byref, c_void_p, WinError

# --- PILLOW COMPATIBILITY ---
try:
    from PIL import ImageResampling
    RESAMPLE_METHOD = ImageResampling.LANCZOS
except ImportError:
    RESAMPLE_METHOD = getattr(Image, 'LANCZOS', getattr(Image, 'ANTIALIAS', 1))

CONFIG_FILE = "salikha_layout.json"
COUNTER_FILE = "salikha_counter.json"
COPIED_FILES_FILE = "salikha_copied_files.json"

def load_copied_tracking():
    try:
        if os.path.exists(COPIED_FILES_FILE):
            with open(COPIED_FILES_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return {}

def save_copied_tracking(data):
    try:
        with open(COPIED_FILES_FILE, 'w') as f:
            json.dump(data, f)
    except:
        pass

def is_already_copied(source_path, tracking):
    entry = tracking.get(source_path)
    if not entry:
        return False
    try:
        current_size = os.path.getsize(source_path)
        current_ctime = os.path.getctime(source_path)
        return entry.get("size") == current_size and entry.get("ctime") == current_ctime
    except:
        return False

def get_next_sd_counter():
    instance_id = str(uuid.uuid4())[:8]
    
    try:
        if os.path.exists(COUNTER_FILE):
            with open(COUNTER_FILE, 'r') as f:
                data = json.load(f)
        else:
            data = {"sd_counter": 0, "instances": {}}
    except:
        data = {"sd_counter": 0, "instances": {}}
    
    counter = data.get("sd_counter", 0) + 1
    data["sd_counter"] = counter
    data["instances"][instance_id] = counter
    
    try:
        with open(COUNTER_FILE, 'w') as f:
            json.dump(data, f)
    except:
        pass
    
    return counter, instance_id

def generate_sd_filename(original_path, dest_folder):
    camera_name = os.path.splitext(os.path.basename(original_path))[0]
    counter, _ = get_next_sd_counter()
    filename = f"{camera_name}_{counter:04d}.jpg"
    
    while os.path.exists(os.path.join(dest_folder, filename)):
        counter += 1
        filename = f"{camera_name}_{counter:04d}.jpg"
        
        try:
            if os.path.exists(COUNTER_FILE):
                with open(COUNTER_FILE, 'r') as f:
                    data = json.load(f)
            else:
                data = {"sd_counter": 0, "instances": {}}
            data["sd_counter"] = counter
            with open(COUNTER_FILE, 'w') as f:
                json.dump(data, f)
        except:
            pass
    
    return filename

class TransferNotification:
    def __init__(self, parent, count, dest):
        self.count = count
        self.dest = dest
        self.window = tk.Toplevel(parent)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        
        screen_w = self.window.winfo_screenwidth()
        screen_h = self.window.winfo_screenheight()
        win_w, win_h = 350, 120
        x = screen_w - win_w - 20
        y = screen_h - win_h - 60
        
        self.window.geometry(f"{win_w}x{win_h}+{x}+{y}")
        
        self.canvas = tk.Canvas(self.window, width=win_w, height=win_h, bg="#1a1a2e", highlightthickness=0)
        self.canvas.pack()
        
        self.alpha = 0.0
        self.fade_dir = 1
        
        self.canvas.create_oval(15, 25, 55, 65, fill="#00d4aa", tags="check")
        self.canvas.create_text(35, 45, text="✓", fill="white", font=("Arial", 24, "bold"), tags="check_sym")
        
        self.canvas.create_text(70, 35, text="TRANSFER COMPLETE!", fill="#00d4aa", font=("Arial", 13, "bold"), anchor="w")
        self.canvas.create_text(70, 58, text=f"{count} files copied", fill="#ffffff", font=("Arial", 10), anchor="w")
        self.canvas.create_text(70, 78, text=f"→ {os.path.basename(dest)}", fill="#888888", font=("Arial", 9), anchor="w")
        
        self.animate()
        self.window.after(3000, self.fade_out)
    
    def animate(self):
        if self.fade_dir == 1:
            self.alpha = min(1.0, self.alpha + 0.1)
            self.window.attributes("-alpha", self.alpha)
            if self.alpha < 1.0:
                self.window.after(30, self.animate)
        else:
            self.alpha = max(0, self.alpha - 0.1)
            self.window.attributes("-alpha", self.alpha)
            if self.alpha > 0:
                self.window.after(30, self.animate)
            else:
                self.window.destroy()
    
    def fade_out(self):
        self.fade_dir = -1
        self.animate()

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
        self.box_items = []
        self.box_labels = []
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
        self.sd_source = "F:\\DCIM"
        self.sd_dest_prot = ""
        self.sd_dest_raw = ""
        
        # Sharpen (0-100%)
        self.sharpen_value = 0
        
        # Instance ID for counter
        self.instance_id = str(uuid.uuid4())[:8]

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
        
        self.box_ratio = tk.StringVar(value="Landscape (3:2)")
        ttk.Radiobutton(ratio_frame, text="Landscape (3:2)", variable=self.box_ratio, value="Landscape (3:2)").pack(anchor="w", padx=10, pady=2)
        ttk.Radiobutton(ratio_frame, text="Portrait (2:3)", variable=self.box_ratio, value="Portrait (2:3)").pack(anchor="w", padx=10, pady=2)
        ttk.Radiobutton(ratio_frame, text="Landscape (4:3)", variable=self.box_ratio, value="Landscape (4:3)").pack(anchor="w", padx=10, pady=2)
        ttk.Radiobutton(ratio_frame, text="Portrait (3:4)", variable=self.box_ratio, value="Portrait (3:4)").pack(anchor="w", padx=10, pady=2)
        ttk.Radiobutton(ratio_frame, text="Freeform", variable=self.box_ratio, value="Freeform").pack(anchor="w", padx=10, pady=2)

        dup_frame = tk.LabelFrame(ctrl, text="Duplicate Box", bg="#f8f9fa")
        dup_frame.pack(fill="x", padx=15, pady=10)
        
        self.dup_src_var = tk.StringVar(value="1")
        dup_top = tk.Frame(dup_frame, bg="#f8f9fa")
        dup_top.pack(fill="x", padx=5, pady=2)
        tk.Label(dup_top, text="Source:", bg="#f8f9fa").pack(side="left")
        self.dup_src_combo = ttk.Combobox(dup_top, textvariable=self.dup_src_var, values=[str(i) for i in range(1, 11)], width=5, state="readonly")
        self.dup_src_combo.pack(side="left", padx=5)
        tk.Button(dup_frame, text="Duplicate", command=self.duplicate_box, bg="#007bff", fg="white", font=("Arial", 9, "bold")).pack(fill="x", padx=5, pady=2)

        coord_frame = tk.LabelFrame(ctrl, text="Fine-tune Coordinates", bg="#f8f9fa")
        coord_frame.pack(fill="x", padx=15, pady=10)
        
        coord_top = tk.Frame(coord_frame, bg="#f8f9fa")
        coord_top.pack(fill="x", padx=5, pady=2)
        tk.Label(coord_top, text="Box#:", bg="#f8f9fa").pack(side="left")
        self.coord_idx_var = tk.StringVar(value="1")
        self.coord_idx_combo = ttk.Combobox(coord_top, textvariable=self.coord_idx_var, values=[str(i) for i in range(1, 11)], width=5, state="readonly")
        self.coord_idx_combo.pack(side="left", padx=5)
        tk.Button(coord_top, text="Load", command=self.load_box_coords, width=6).pack(side="left", padx=2)
        
        coord_grid = tk.Frame(coord_frame, bg="#f8f9fa")
        coord_grid.pack(fill="x", padx=5, pady=2)
        tk.Label(coord_grid, text="X1:", bg="#f8f9fa", width=4).grid(row=0, column=0)
        self.coord_x1 = tk.Entry(coord_grid, width=8)
        self.coord_x1.grid(row=0, column=1, padx=2)
        tk.Label(coord_grid, text="Y1:", bg="#f8f9fa", width=4).grid(row=0, column=2)
        self.coord_y1 = tk.Entry(coord_grid, width=8)
        self.coord_y1.grid(row=0, column=3, padx=2)
        tk.Label(coord_grid, text="X2:", bg="#f8f9fa", width=4).grid(row=1, column=0)
        self.coord_x2 = tk.Entry(coord_grid, width=8)
        self.coord_x2.grid(row=1, column=1, padx=2)
        tk.Label(coord_grid, text="Y2:", bg="#f8f9fa", width=4).grid(row=1, column=2)
        self.coord_y2 = tk.Entry(coord_grid, width=8)
        self.coord_y2.grid(row=1, column=3, padx=2)
        tk.Button(coord_frame, text="Apply Changes", command=self.apply_coord_changes, bg="#28a745", fg="white", font=("Arial", 9, "bold")).pack(fill="x", padx=5, pady=2)

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
            self.box_items = []
            self.box_labels = []

    def on_press(self, e):
        items = self.canvas.find_withtag("photobox")
        for item in items:
            c = self.canvas.coords(item)
            if c[0] <= e.x <= c[2] and c[1] <= e.y <= c[3]:
                self.selected_item = item
                self.action = 'move'
                self.start_x, self.start_y = e.x, e.y
                self.canvas.itemconfig(item, outline="yellow", width=4)
                idx = self.box_items.index(item) + 1
                self.coord_idx_var.set(str(idx))
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
            
            if ratio_mode == "Landscape (3:2)":
                h = abs(dx) * (2/3) * (1 if dy > 0 else -1)
                self.canvas.coords(self.rect, self.sx, self.sy, self.sx + dx, self.sy + h)
            elif ratio_mode == "Portrait (2:3)":
                h = abs(dx) * (3/2) * (1 if dy > 0 else -1)
                self.canvas.coords(self.rect, self.sx, self.sy, self.sx + dx, self.sy + h)
            elif ratio_mode == "Landscape (4:3)":
                h = abs(dx) * (3/4) * (1 if dy > 0 else -1)
                self.canvas.coords(self.rect, self.sx, self.sy, self.sx + dx, self.sy + h)
            elif ratio_mode == "Portrait (3:4)":
                h = abs(dx) * (4/3) * (1 if dy > 0 else -1)
                self.canvas.coords(self.rect, self.sx, self.sy, self.sx + dx, self.sy + h)
            else:
                self.canvas.coords(self.rect, self.sx, self.sy, e.x, e.y)

    def on_release(self, e):
        if self.action == 'move' and self.selected_item:
            self.canvas.itemconfig(self.selected_item, outline="#00aaff", width=3)
            self.load_box_coords()
            
        if self.action == 'draw':
            c = self.canvas.coords(self.rect)
            x1, y1, x2, y2 = min(c[0], c[2]), min(c[1], c[3]), max(c[0], c[2]), max(c[1], c[3])
            if abs(x2 - x1) < 10 or abs(y2 - y1) < 10:
                self.canvas.delete(self.rect)
            else:
                self.canvas.coords(self.rect, x1, y1, x2, y2)
                self.box_items.append(self.rect)
                new_label = len(self.box_labels) + 1
                self.box_labels.append(new_label)
        
        self.sync_boxes()

    def sync_boxes(self):
        self.boxes = []
        for i, item in enumerate(self.box_items):
            c = self.canvas.coords(item)
            self.boxes.append([x * self.scale for x in c])
        self.relabel_boxes()

    def relabel_boxes(self):
        self.canvas.delete("boxlabel")
        for i, item in enumerate(self.box_items):
            c = self.canvas.coords(item)
            label_x = c[0] + 15
            label_y = c[1] + 15
            label_text = str(self.box_labels[i])
            self.canvas.create_text(label_x, label_y, text=label_text, fill="yellow", font=("Arial", 12, "bold"), tags=("boxlabel"))

    def clear_boxes(self):
        self.canvas.delete("photobox")
        self.canvas.delete("boxlabel")
        self.boxes = []
        self.box_items = []
        self.box_labels = []

    def duplicate_box(self):
        try:
            src_num = int(self.dup_src_var.get()) - 1
            if src_num < 0 or src_num >= len(self.box_items):
                messagebox.showwarning("Duplicate", f"Box {src_num + 1} does not exist.")
                return
            item = self.box_items[src_num]
            c = self.canvas.coords(item)
            x1, y1, x2, y2 = c
            offset = 20
            new_rect = self.canvas.create_rectangle(x1 + offset, y1 + offset, x2 + offset, y2 + offset, outline="#00aaff", width=3, tags="photobox")
            self.box_items.append(new_rect)
            new_coords = [(x1 + offset) * self.scale, (y1 + offset) * self.scale, (x2 + offset) * self.scale, (y2 + offset) * self.scale]
            self.boxes.append(new_coords)
            src_label = self.box_labels[src_num]
            self.box_labels.append(src_label)
            self.relabel_boxes()
        except Exception as e:
            messagebox.showerror("Duplicate Error", str(e))

    def load_box_coords(self):
        try:
            idx = int(self.coord_idx_var.get()) - 1
            if idx < 0 or idx >= len(self.box_items):
                return
            c = self.canvas.coords(self.box_items[idx])
            self.coord_x1.delete(0, tk.END); self.coord_x1.insert(0, str(int(c[0])))
            self.coord_y1.delete(0, tk.END); self.coord_y1.insert(0, str(int(c[1])))
            self.coord_x2.delete(0, tk.END); self.coord_x2.insert(0, str(int(c[2])))
            self.coord_y2.delete(0, tk.END); self.coord_y2.insert(0, str(int(c[3])))
        except Exception as e:
            messagebox.showerror("Load Error", str(e))

    def apply_coord_changes(self):
        try:
            idx = int(self.coord_idx_var.get()) - 1
            if idx < 0 or idx >= len(self.box_items):
                messagebox.showwarning("Apply", f"Box {idx + 1} does not exist.")
                return
            x1 = int(self.coord_x1.get())
            y1 = int(self.coord_y1.get())
            x2 = int(self.coord_x2.get())
            y2 = int(self.coord_y2.get())
            self.canvas.coords(self.box_items[idx], x1, y1, x2, y2)
            self.boxes[idx] = [x1 * self.scale, y1 * self.scale, x2 * self.scale, y2 * self.scale]
            self.relabel_boxes()
        except Exception as e:
            messagebox.showerror("Apply Error", str(e))

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
        ttk.Button(src_frame, text="📂", command=self.open_event_folder, width=3).pack(side="right", padx=2)

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

        sharpen_frame = tk.LabelFrame(left, text="Sharpen (Print Output Only)", padx=5, pady=5)
        sharpen_frame.pack(fill="x", pady=5)
        self.sharpen_var = tk.IntVar(value=self.sharpen_value)
        sharpen_slider = ttk.Scale(sharpen_frame, from_=0, to=100, variable=self.sharpen_var, command=self.on_sharpen_change)
        sharpen_slider.pack(fill="x", padx=5, pady=2)
        self.sharpen_lbl = tk.Label(sharpen_frame, text=f"Sharpness: {self.sharpen_value}%", fg="#007bff")
        self.sharpen_lbl.pack()

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

    def open_event_folder(self):
        if os.path.exists(self.source_folder):
            subprocess.Popen(['explorer', self.source_folder])
        else:
            messagebox.showwarning("Folder Not Found", "Source folder does not exist.")

    def on_sharpen_change(self, val):
        self.sharpen_value = int(float(val))
        self.sharpen_lbl.config(text=f"Sharpness: {self.sharpen_value}%")

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
                files.sort(key=os.path.getctime)
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
        unique_labels = []
        for lbl in self.box_labels:
            if lbl not in unique_labels:
                unique_labels.append(lbl)
        required_count = len(unique_labels)
        self.queue_log(f"ℹ️ Layout requires {required_count} unique photo slots.")

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
                
                unique_labels = []
                for lbl in self.box_labels:
                    if lbl not in unique_labels:
                        unique_labels.append(lbl)
                label_to_idx = {lbl: idx for idx, lbl in enumerate(unique_labels)}
                
                for box_idx, (box, label) in enumerate(zip(self.boxes, self.box_labels)):
                    photo_idx = label_to_idx[label]
                    if photo_idx < len(current_files):
                        with Image.open(current_files[photo_idx]) as img:
                            img = ImageOps.exif_transpose(img)
                            w, h = int(box[2]-box[0]), int(box[3]-box[1])
                            img = ImageOps.fit(img, (w, h), RESAMPLE_METHOD)
                            canvas.paste(img, (int(box[0]), int(box[1])))
                canvas.paste(overlay, (0, 0), overlay)
                
                prev = canvas.copy()
                prev.thumbnail((600, 800), RESAMPLE_METHOD)
                self.gui_queue.put({"action": "preview", "image": prev})

                if save_to_disk:
                    if not os.path.exists(self.output_folder):
                        try:
                            os.makedirs(self.output_folder, exist_ok=True)
                        except Exception as e:
                            self.queue_log(f"❌ Cannot create output folder: {self.output_folder}")
                            return
                    filename = f"Print_{int(time.time())}.jpg"
                    out_path = os.path.join(self.output_folder, filename)
                    
                    save_img = canvas.convert("RGB")
                    
                    if self.sharpen_value > 0:
                        radius = self.sharpen_value / 10.0
                        percent = self.sharpen_value * 2
                        save_img = save_img.filter(ImageFilter.UnsharpMask(radius=radius, percent=percent))
                    
                    try:
                        save_img.save(out_path, "JPEG", quality=98)
                        self.queue_log(f"💾 SAVED: {filename}")
                    except PermissionError:
                        self.queue_log(f"❌ Permission denied saving {filename} - file may be open elsewhere")
                        return

                    self.last_printed_file = out_path
                    self.gui_queue.put({"action": "enable_reprint"})

                    if "Print" in self.mode_var.get():
                        self.silent_print(out_path)
                        self.print_count += 1
                        self.gui_queue.put({"action": "update_count", "count": self.print_count})
        except Exception as e:
            self.queue_log(f"Render Error: {e} | Path: {self.output_folder}")

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

        # Step 2: Locked Destination
        ttk.Label(container, text="Step 2: Folder for LOCKED Files (L/P separated)", font=("Arial", 11, "bold")).pack(pady=(15, 2))
        self.dest_prot_var = tk.StringVar(value=self.sd_dest_prot or "Click to select destination...")
        tk.Button(container, textvariable=self.dest_prot_var, command=self.select_sorter_dest_prot, width=80, relief="groove", bg="#fff").pack(pady=2)

        # Step 3: Raw Destination (Merged)
        ttk.Label(container, text="Step 3: Folder for RAW Archive (all photos merged)", font=("Arial", 11, "bold")).pack(pady=(15, 2))
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
            return "Raw"
        except Exception:
            return "Raw"

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
        valid_exts = ('.JPG', '.JPEG')
        tracking = load_copied_tracking()
        
        while self.is_sorting:
            try:
                all_files = []
                for root, dirs, files in os.walk(src):
                    if not self.is_sorting:
                        break
                    for filename in files:
                        if not self.is_sorting:
                            break
                        if filename.startswith('.'):
                            continue
                        
                        if filename.upper().endswith(valid_exts):
                            source_path = os.path.join(root, filename)
                            if is_already_copied(source_path, tracking):
                                continue
                            try:
                                file_ctime = os.path.getctime(source_path)
                                file_size = os.path.getsize(source_path)
                            except:
                                file_ctime = 0
                                file_size = 0
                            is_locked = self.is_locked(source_path)
                            all_files.append((source_path, filename, file_ctime, file_size, is_locked))
                
                if not self.is_sorting:
                    break
                
                if not all_files:
                    self.sorter_queue_log("No new files, waiting...")
                    time.sleep(2)
                    continue
                
                all_files.sort(key=lambda x: x[2])
                
                copy_tasks = []
                for source_path, filename, file_ctime, file_size, is_locked in all_files:
                    orient = self.get_orientation_folder(source_path)
                    copy_tasks.append({
                        'source': source_path,
                        'original_filename': filename,
                        'file_ctime': file_ctime,
                        'file_size': file_size,
                        'is_locked': is_locked,
                        'orient': orient,
                        'dest_prot': dest_prot,
                        'dest_raw': dest_raw,
                        'tracking': tracking
                    })
                
                with ThreadPoolExecutor(max_workers=10) as executor:
                    futures = []
                    for task in copy_tasks:
                        future = executor.submit(self._copy_task, task)
                        futures.append((future, task))
                    
                    copied_count = 0
                    for future, task in futures:
                        if not self.is_sorting:
                            break
                        try:
                            result = future.result()
                            if result:
                                copied_count += 1
                                self.sorter_queue_log(result)
                                source = task['source']
                                tracking[source] = {
                                    "size": task['file_size'],
                                    "ctime": task['file_ctime'],
                                    "copied_at": time.strftime("%Y-%m-%dT%H:%M:%S")
                                }
                                save_copied_tracking(tracking)
                        except Exception as e:
                            self.sorter_queue_log(f"Error copying {task['original_filename']}: {e}")
                
                if copied_count > 0:
                    self.sorter_queue_log(f"Transfer complete! {copied_count} files copied.")
                    self.root.after(100, lambda: TransferNotification(self.root, copied_count, dest_raw))
                
                time.sleep(2)
                
            except (OSError, PermissionError) as e:
                self.sorter_queue_log(f"Source folder inaccessible, waiting...")
                time.sleep(2)
                continue
        
        self.btn_start_sorter.config(text="START MONITORING & COPYING", bg="#007bff", state="normal")
        self.sorter_queue_log("Monitoring Stopped.")

    def _copy_readonly_file(self, source, dest):
        try:
            result = subprocess.run(
                ['cmd', '/c', 'copy', '/Y', '/V', source, dest],
                capture_output=True, text=True
            )
            return result.returncode == 0
        except Exception as e:
            return False

    def _copy_task(self, task):
        source = task['source']
        original_filename = task['original_filename']
        is_locked = task['is_locked']
        orient = task['orient']
        dest_prot = task['dest_prot']
        dest_raw = task['dest_raw']
        
        if not os.path.exists(dest_raw):
            os.makedirs(dest_raw, exist_ok=True)
        
        new_filename = generate_sd_filename(source, dest_raw)
        target_path_raw = os.path.join(dest_raw, new_filename)
        
        if not os.path.exists(target_path_raw):
            self._copy_readonly_file(source, target_path_raw)
        
        if is_locked:
            prot_folder = os.path.join(dest_prot, orient)
            if not os.path.exists(prot_folder):
                os.makedirs(prot_folder, exist_ok=True)
            target_path_prot = os.path.join(prot_folder, new_filename)
            if not os.path.exists(target_path_prot):
                self._copy_readonly_file(target_path_raw, target_path_prot)
            return f"[LOCKED | {orient}] {original_filename} → {new_filename}"
        else:
            return f"[RAW] {original_filename} → {new_filename}"

    # ========================================================
    # DATA SAVING / LOADING
    # ========================================================
    def save_config(self):
        data = {
            "template": self.template_path, 
            "boxes": self.boxes, 
            "box_labels": self.box_labels,
            "source": self.source_folder, 
            "output": self.output_folder,
            "sd_source": self.src_path_var.get() if hasattr(self, 'src_path_var') and os.path.isdir(self.src_path_var.get()) else "",
            "sd_dest_prot": self.dest_prot_var.get() if hasattr(self, 'dest_prot_var') and os.path.isdir(self.dest_prot_var.get()) else "",
            "sd_dest_raw": self.dest_raw_var.get() if hasattr(self, 'dest_raw_var') and os.path.isdir(self.dest_raw_var.get()) else "",
            "sharpen_value": self.sharpen_value
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
                self.box_labels = data.get("box_labels", [])
                self.box_items = []
                for box in self.boxes:
                    scaled_box = [x / self.scale for x in box]
                    item = self.canvas.create_rectangle(*scaled_box, outline="#00aaff", width=3, tags="photobox")
                    self.box_items.append(item)
                if len(self.box_labels) < len(self.box_items):
                    self.box_labels = [i + 1 for i in range(len(self.box_items))]
                self.relabel_boxes()

                src = data.get("source"); out = data.get("output")
                if src:
                    self.source_folder = src
                    self.src_entry.delete(0, tk.END); self.src_entry.insert(0, src)
                    if not os.path.exists(src): os.makedirs(src, exist_ok=True)
                if out:
                    self.output_folder = out
                    self.out_entry.delete(0, tk.END); self.out_entry.insert(0, out)
                    if not os.path.exists(out): os.makedirs(out, exist_ok=True)

                if data.get("sd_source") and hasattr(self, 'src_path_var'): self.src_path_var.set(data["sd_source"])
                if data.get("sd_dest_prot") and hasattr(self, 'dest_prot_var'): self.dest_prot_var.set(data["sd_dest_prot"])
                if data.get("sd_dest_raw") and hasattr(self, 'dest_raw_var'): self.dest_raw_var.set(data["sd_dest_raw"])

                if data.get("sharpen_value") is not None:
                    self.sharpen_value = data.get("sharpen_value", 0)
                    if hasattr(self, 'sharpen_var'):
                        self.sharpen_var.set(self.sharpen_value)
                    if hasattr(self, 'sharpen_lbl'):
                        self.sharpen_lbl.config(text=f"Sharpness: {self.sharpen_value}%")

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