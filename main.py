import os
import threading
import time
import webbrowser
import uvicorn
from web_server import app

def open_browser():
    """Ждет полторы секунды, пока поднимется сервер, и открывает браузер"""
    time.sleep(1.5)
    print("🌐 Открываю интерфейс в браузере...")
    webbrowser.open("http://127.0.0.1:8050/dashboard.html")

if __name__ == '__main__':
    print("="*50)
    print("🕷️ SPIDER V8 - WEB EDITION STARTED")
    print("="*50)
    print("Сервер запущен по адресу: http://127.0.0.1:8050/dashboard.html")
    print("Для остановки нажми CTRL+C")
    print("="*50)
    
    # Запускаем открытие браузера в фоновом потоке
    threading.Thread(target=open_browser, daemon=True).start()
    
    # Запускаем FastAPI (Uvicorn) в главном потоке
    uvicorn.run(app, host="127.0.0.1", port=8050, log_level="warning")