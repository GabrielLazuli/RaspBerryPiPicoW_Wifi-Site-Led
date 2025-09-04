import network
import time
import socket
import neopixel
from machine import Pin

#OBSVERVAÇÃO ESSE CÓDIGO AO RODAR LIBERA UM IP USANDO ELE EM ALGUM NAVEGADOR TEM UM "SITE" COM O BOTÃO PRA ACENDER O LED

# --- Configuração do Wi-Fi ---
WIFI_SSID = "Coloque o nome do seu wifi"
WIFI_PASS = "Coloque a senha do seu wifi"

#Aqui são os pinos da MINHA placa que é uma BITDOGLAB se trata de 12 = um led qualquer 13 = uma matriz neopixel, por isso a biblioteca.
led = Pin(12, Pin.OUT)
led_azul = Pin(13, Pin.OUT)
MatrizLed = neopixel.NeoPixel(machine.Pin(7),25)

# --- Conecta ao Wi-Fi --- 
print("Conectando ao Wi-Fi...")
wifi = network.WLAN(network.STA_IF)
wifi.active(True)
wifi.connect(WIFI_SSID, WIFI_PASS)
while not wifi.isconnected():
    time.sleep(1)
print("Conectado! IP:", wifi.ifconfig()[0])

# --- Teste de internet ---
try:
    addr = socket.getaddrinfo("1.1.1.1", 80)[0][-1]
    s = socket.socket()
    s.connect(addr)
    print("Conseguiu falar com a internet!")
    s.close()
except Exception as e:
    print("Erro de internet:", e)

# --- Servidor Web para controlar o LED ---
addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
s = socket.socket()
s.bind(addr)
s.listen(1)

#Se piscou o led é porque está online
led_azul.on()
time.sleep(1)
led_azul.off()

print("Servidor online! Acesse pelo navegador:", wifi.ifconfig()[0])

while True:
    cl, addr = s.accept()
    print("Cliente conectado:", addr)
    request = cl.recv(1024).decode()

    # Comandos LED
    if "/led/on" in request:
        MatrizLed.fill((255,0,0))
        MatrizLed.write()
        print("LED ligado")
    if "/led/off" in request:
        MatrizLed.fill((0,0,0))
        MatrizLed.write()
        print("LED desligado")

    # Página HTML com CSS integrado
    response = """\
HTTP/1.1 200 OK

<html>
<head>
  <title>Pico W Web Server</title>
  <style>
    body {
      font-family: Arial, sans-serif;
      text-align: center;
      background: #f0f0f5;
      color: #333;
      margin-top: 50px;
    }
    h1 { color: #2c3e50; font-size: 2em; margin-bottom: 40px; }
    a {
      display: inline-block;
      margin: 10px;
      padding: 50px 250px;
      font-size: 40px;
      text-decoration: none;
      color: white;
      border-radius: 8px;
      transition: 0.3s;
    }
    a[href="/led/on"] { background-color: #27ae60; }   /* verde */
    a[href="/led/off"] { background-color: #c0392b; }  /* vermelho */
    a:hover { opacity: 0.8; }
  </style> 
</head>
<body>
  <h1>Pico W Web Server</h1>
  <p><a href="/led/on">Ligar LED</a></p>
  <p><a href="/led/off">Desligar LED</a></p>
</body>
</html>
"""
    cl.send(response)
    cl.close()
