# JobRobo.py
import tkinter as tk
from tkinter import ttk, messagebox
from dotenv import load_dotenv
from runAiBot import run_bot
from modules.ai.resume_optimizer import run_resume_optimization
from modules.config_loader import save_runtime_config, load_runtime_config

load_dotenv()  # Load environment variables from .env

class LinkedInApp:
    def __init__(self, root):
        self.root = root
        self.root.title("LinkedIn Bot Dashboard")
        self.root.geometry("600x500")

        self.notebook = ttk.Notebook(self.root)

        self.bot_tab = ttk.Frame(self.notebook)
        self.optimizer_tab = ttk.Frame(self.notebook)

        self.notebook.add(self.bot_tab, text="Run LinkedIn Bot")
        self.notebook.add(self.optimizer_tab, text="Resume Optimizer")

        self.notebook.pack(expand=1, fill="both")

        self.init_bot_tab()
        self.init_optimizer_tab()

    def init_bot_tab(self):
        label = tk.Label(self.bot_tab, text="Click to start LinkedIn automation")
        label.pack(pady=20)

        button = tk.Button(self.bot_tab, text="Run Bot", command=run_bot)
        button.pack(pady=10)

    def init_optimizer_tab(self):
        config = load_runtime_config()

        self.fields = {}
        field_config = {
            "first_name": "First Name",
            "last_name": "Last Name",
            "resume_path": "Resume Path",
            "job_id": "Job ID",
            "job_title": "Job Title",
            "job_description": "Job Description"
        }

        for i, (key, label_text) in enumerate(field_config.items()):
            label = tk.Label(self.optimizer_tab, text=label_text)
            label.grid(row=i, column=0, sticky="e", pady=5, padx=10)
            entry = tk.Entry(self.optimizer_tab, width=60)
            entry.insert(0, config.get(key, ""))
            entry.grid(row=i, column=1, pady=5)
            self.fields[key] = entry

        self.replace_job_title_var = tk.BooleanVar(value=config.get("replace_job_title", True))
        self.rewrite_bullets_var = tk.BooleanVar(value=config.get("rewrite_bullets", True))

        tk.Checkbutton(self.optimizer_tab, text="Replace Job Title", variable=self.replace_job_title_var).grid(row=len(field_config), column=1, sticky="w")
        tk.Checkbutton(self.optimizer_tab, text="Rewrite Resume Bullets", variable=self.rewrite_bullets_var).grid(row=len(field_config)+1, column=1, sticky="w")

        run_button = tk.Button(self.optimizer_tab, text="Run Resume Optimizer", command=self.run_resume_optimizer_from_ui)
        run_button.grid(row=len(field_config)+3, column=1, pady=20)

    def run_resume_optimizer_from_ui(self):
        try:
            new_config = {
                key: self.fields[key].get() for key in self.fields
            }
            new_config["replace_job_title"] = self.replace_job_title_var.get()
            new_config["rewrite_bullets"] = self.rewrite_bullets_var.get()

            save_runtime_config(new_config)

            # Re-load to ensure consistent values
            config = load_runtime_config()

            run_resume_optimization(
                config["job_description"],
                config["resume_path"],
                config["job_id"],
                config["job_title"],
                config["first_name"],
                config["last_name"]
            )

            messagebox.showinfo("Success", "Resume optimization completed successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {str(e)}")

if __name__ == "__main__":
    root = tk.Tk()
    app = LinkedInApp(root)
    root.mainloop()