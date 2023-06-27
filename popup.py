import time
import tkinter as tk
from PIL import Image, ImageTk

class PopupWindow:
    y_offset = 0
    def __init__(self, title, message, x, y, width=200, height=100, image_path=None):
        self.height = height
        self.root = tk.Tk()
        self.root.withdraw()
        self.popup = tk.Toplevel()
        self.popup.title(title)
        #y += PopupWindow.y_offset
        self.popup.geometry(f'+{x}+{y}')
        self.popup.overrideredirect(True)

        if image_path:
            img = Image.open(image_path)
            img.thumbnail((width - 20, height - 20))  # Resize for a proper fit
            self.image = ImageTk.PhotoImage(img)
            image_label = tk.Label(self.popup, image=self.image)
            image_label.pack()

        label = tk.Label(self.popup, text=message, padx=10, pady=10)
        label.pack()
        self.popup.lift()
        self.popup.attributes('-topmost', True)
        self.popup.update()
        PopupWindow.y_offset += self.height

    def close(self):
        PopupWindow.y_offset -= self.height
        self.popup.update()
        self.popup.destroy()
        self.popup.update()
        self.root.destroy()
        self.popup.update()

    @classmethod
    def kill(cls):
        pass
        

if __name__ == '__main__':
    test = PopupWindow('Title', 'Message', 100, 100, 300, 200)
    time.sleep(2)
    test.close()
    print('killed')
    time.sleep(2)