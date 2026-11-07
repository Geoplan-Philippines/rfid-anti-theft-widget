@echo off
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator privileges to configure Ethernet IP and Windows Firewall...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set "IFACE=%~1"
if "%IFACE%"=="" set "IFACE=Ethernet 2"

echo [1/4] Assigning static IP 169.254.68.94/24 on "%IFACE%" (for HAX7700 at 169.254.68.93)...
netsh interface ipv4 set address name="%IFACE%" static 169.254.68.94 255.255.255.0 >nul 2>&1
netsh interface ipv4 add address "%IFACE%" 169.254.68.94 255.255.255.0 >nul 2>&1

echo [2/4] Allowing python.exe and pythonw.exe through Windows Defender Firewall...
netsh advfirewall firewall set rule name="python.exe" new action=allow >nul 2>&1
netsh advfirewall firewall set rule name="pythonw.exe" new action=allow >nul 2>&1

echo [3/4] Allowing inbound TCP ports 9090 (HAX7700 Pad) and 9000 (HAX7000 RFID Gate)...
netsh advfirewall firewall delete rule name="HAX7700 TCP 9090" >nul 2>&1
netsh advfirewall firewall add rule name="HAX7700 TCP 9090" dir=in action=allow protocol=TCP localport=9090 profile=any
netsh advfirewall firewall delete rule name="HAX7000 Gate TCP 9000" >nul 2>&1
netsh advfirewall firewall add rule name="HAX7000 Gate TCP 9000" dir=in action=allow protocol=TCP localport=9000 profile=any

echo [4/4] Verifying connectivity to HAX7700 (169.254.68.93)...
ping -n 2 169.254.68.93

echo.
echo Done! Network and Windows Firewall are configured for HAX7700.
pause
