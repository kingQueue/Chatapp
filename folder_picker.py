"""User-operated Windows file/folder picker, isolated from the web-server threads."""
import json
import sys
import tkinter as tk
from tkinter import filedialog

root=tk.Tk();root.withdraw();root.attributes('-topmost',True)
try:
    if sys.argv[1]=='executable':
        value=filedialog.askopenfilename(title='Character Room: choose an installed application',filetypes=[('Windows executable','*.exe')])
    else:
        value=filedialog.askdirectory(title='Character Room: choose a project or application folder',mustexist=True)
    print(json.dumps({'path':value}),flush=True)
finally:
    root.destroy()
