@echo off
cd /d D:\aaa\ing\clawith\Clawith\backend
"C:\Program Files\Python310\python.exe" -u -m uvicorn app.main:app --host 127.0.0.1 --port 8009
