# main.py
import tkinter as tk
from runAiBot import run_bot

class LinkedInApp:
    def __init__(self, root):
        self.root = root
        self.root.title("LinkedIn Bot")
        self.root.geometry("300x200")
        self.initUI()

    def initUI(self):
        self.label = tk.Label(self.root, text="Click to start automation")
        self.label.pack(pady=20)

        self.button = tk.Button(self.root, text="Run Bot", command=run_bot)
        self.button.pack(pady=10)

if __name__ == "__main__":
    root = tk.Tk()
    app = LinkedInApp(root)
    root.mainloop()