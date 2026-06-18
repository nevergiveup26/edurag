@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
:: EduRAG 一键部署脚本（Windows）
:: 用法: deploy.bat [start|stop|restart|logs]

if "%~1"=="" set "CMD=start" & goto :run
if /i "%~1"=="start"   set "CMD=start"   & goto :run
if /i "%~1"=="stop"    set "CMD=stop"    & goto :run
if /i "%~1"=="restart" set "CMD=restart" & goto :run
if /i "%~1"=="logs"    set "CMD=logs"    & goto :run
echo 用法: deploy.bat {start^|stop^|restart^|logs}
exit /b 1

:run
:: 检查 Docker
where docker >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [✗] 请先安装 Docker Desktop: https://docs.docker.com/get-docker/
    exit /b 1
)

:: 检查 API Key
if "%DASHSCOPE_API_KEY%"=="" (
    if exist .env (
        for /f "usebackq tokens=1,2 delims==" %%a in (.env) do (
            if "%%a"=="DASHSCOPE_API_KEY" set DASHSCOPE_API_KEY=%%b
        )
    )
)
if "%DASHSCOPE_API_KEY%"=="" (
    echo [!] 未设置 DASHSCOPE_API_KEY 环境变量
    echo [!] 请执行: set DASHSCOPE_API_KEY=your-key
    echo [!] 或在项目根目录创建 .env 文件，写入: DASHSCOPE_API_KEY=your-key
    echo.
    set /p "CONT=是否继续启动基础服务（不含API Key）？[y/N] "
    if /i not "!CONT!"=="y" exit /b 0
)

if /i "%CMD%"=="start" (
    echo [✓] 构建并启动所有服务...
    docker compose up -d --build
    echo [✓] 等待服务就绪...
    timeout /t 5 /nobreak >nul
    echo [✓] 服务状态:
    docker compose ps
    echo.
    echo [✓] 部署完成！
    echo [✓] API 文档: http://localhost:8000/docs
    echo [✓] 健康检查: http://localhost:8000/health
)

if /i "%CMD%"=="stop" (
    echo [✓] 停止所有服务...
    docker compose down
    echo [✓] 服务已停止
)

if /i "%CMD%"=="restart" (
    echo [✓] 重启所有服务...
    docker compose down
    docker compose up -d --build
    echo [✓] 重启完成
)

if /i "%CMD%"=="logs" (
    docker compose logs -f --tail=100
)

endlocal
