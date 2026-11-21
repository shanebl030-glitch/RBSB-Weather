import numpy as np
from helpers import qapp
app = qapp()
from PyQt6.QtGui import QImage
from rbsb_weather import earth as E
img = E._texture(E.DAY_FILE)
w, h = img.width(), img.height()
ptr = img.constBits(); ptr.setsize(img.sizeInBytes())
a = np.frombuffer(bytes(ptr), np.uint8).reshape(h, img.bytesPerLine())[:, :w*4].reshape(h, w, 4).astype(int)
b, g, r = a[...,0], a[...,1], a[...,2]
print("size", w, h)
for name,(y,x) in {"Pacific":(512*h//1024, 100*w//2048),"Sahara":(int(h*0.36), int(w*0.53)),"Amazon":(int(h*0.53),int(w*0.33)),"Antarctica":(int(h*0.97),int(w*0.5)),"Australia":(int(h*0.64),int(w*0.87)),"Coral sea":(int(h*0.6),int(w*0.92))}.items():
    print(name, (r[y,x], g[y,x], b[y,x]))
